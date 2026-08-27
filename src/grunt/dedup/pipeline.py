"""Deduplikacja na danych z bazy: jedyne miejsce w dedup/, ktore dotyka SQL.

Przebieg jest w calosci przeliczalny: kazde uruchomienie liczy pary od nowa
i doprowadza baze do stanu wynikajacego z danych. Wyjatkiem jest kolumna
listing_duplicates.potwierdzone, czyli werdykt czlowieka. Recznie oznakowany
zbior par jest w sekcji 4.3 warunkiem strojenia progow, wiec przebieg nigdy go
nie nadpisuje ani nie kasuje.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.dedup import cluster, keys, pairing

log = logging.getLogger(__name__)

SELECT_OFERTY = text(
    """
    SELECT l.id, l.portal::text AS portal,
           ST_X(l.geom) AS e, ST_Y(l.geom) AS n,
           l.area_m2, l.price_grosze, l.title,
           l.phone_sha256, l.thumb_phash::text AS thumb_phash, l.thumb_url,
           le.parcel_uldk_id, le.parcel_match
    FROM listings l
    LEFT JOIN listing_enrichment le ON le.listing_id = l.id
    WHERE l.is_active AND l.geom IS NOT NULL
    ORDER BY l.id
    """
)

UPSERT_PARY = text(
    """
    INSERT INTO listing_duplicates (
        listing_a, listing_b, pewnosc, etap, w_klastrze, powody, computed_at
    ) VALUES (
        :a, :b, :pewnosc, :etap, :w_klastrze, CAST(:powody AS jsonb), now()
    )
    ON CONFLICT (listing_a, listing_b) DO UPDATE SET
        pewnosc = EXCLUDED.pewnosc,
        etap = EXCLUDED.etap,
        w_klastrze = EXCLUDED.w_klastrze,
        powody = EXCLUDED.powody,
        computed_at = now()
    """
)

# Para, ktora przestala byc podejrzana (spadla cena, zmienil sie tytul, oferta
# wygasla). Recznie ocenionych nie ruszamy, bo to zbior testowy dla progow.
SKASUJ_NIEAKTUALNE = text(
    """
    DELETE FROM listing_duplicates
    WHERE potwierdzone IS NULL
      AND computed_at < :znacznik
    """
)

WYCZYSC_KLASTRY = text("UPDATE listings SET cluster_id = NULL WHERE cluster_id IS NOT NULL")

USTAW_KLASTER = text("UPDATE listings SET cluster_id = :cluster_id WHERE id = :listing_id")


def _oferta(row: Any) -> pairing.Oferta:
    return pairing.Oferta(
        id=int(row["id"]),
        portal=row["portal"],
        easting=float(row["e"]),
        northing=float(row["n"]),
        area_m2=int(row["area_m2"]) if row["area_m2"] else None,
        price_grosze=int(row["price_grosze"]) if row["price_grosze"] else None,
        tytul=row["title"],
        phone_sha256=row["phone_sha256"],
        thumb_phash=row["thumb_phash"],
        obraz_klucz=keys.klucz_obrazu(row["thumb_url"]),
        uldk_id=row["parcel_uldk_id"],
        # ULDK po wspolrzednych to generator kandydata, nie identyfikacja
        # (punkt 5 sekcji "Czego nauczyly nas dane"). Jako twardego klucza
        # uzywamy go wylacznie przy pewnym dopasowaniu.
        uldk_pewny=row["parcel_match"] == "high",
    )


def wczytaj(session: Session) -> list[pairing.Oferta]:
    """Aktywne oferty ze wspolrzednymi. Bez geometrii nie ma blockingu."""
    rows = session.execute(SELECT_OFERTY).mappings().all()
    return [_oferta(row) for row in rows]


def run(session: Session, *, zapisz: bool = True) -> dict[str, Any]:
    """Pelny przebieg: pary, klastry, zapis. Zwraca statystyki i klastry."""
    oferty = wczytaj(session)
    werdykty = pairing.znajdz(oferty)
    przypisanie = cluster.przypisz(werdykty)
    klastry = cluster.podsumuj(oferty, przypisanie)

    statystyki: dict[str, Any] = {
        "oferty": len(oferty),
        "pary": len(werdykty),
        "pary_w_klastrze": sum(1 for w in werdykty if w.do_klastra),
        "pary_do_przejrzenia": sum(1 for w in werdykty if not w.do_klastra),
        "klastry": len(klastry),
        "oferty_w_klastrach": len(przypisanie),
        "duplikaty_proc": (
            round(100 * (len(przypisanie) - len(klastry)) / len(oferty), 1) if oferty else 0.0
        ),
        "etapy": {},
    }
    for werdykt in werdykty:
        if werdykt.do_klastra:
            statystyki["etapy"][werdykt.etap] = statystyki["etapy"].get(werdykt.etap, 0) + 1

    if not zapisz:
        return {**statystyki, "klastry_szczegoly": klastry}

    # now() jest stale w obrebie transakcji, wiec wiersze zapisane nizej maja
    # dokladnie ten znacznik, a starsze (z poprzednich przebiegow) sa mniejsze.
    znacznik = session.execute(text("SELECT now()")).scalar_one()
    for werdykt in werdykty:
        session.execute(
            UPSERT_PARY,
            {
                "a": werdykt.a_id,
                "b": werdykt.b_id,
                "pewnosc": werdykt.pewnosc,
                "etap": werdykt.etap,
                "w_klastrze": werdykt.do_klastra,
                "powody": json.dumps(list(werdykt.powody), ensure_ascii=False),
            },
        )
    skasowane = session.execute(SKASUJ_NIEAKTUALNE, {"znacznik": znacznik}).rowcount

    session.execute(WYCZYSC_KLASTRY)
    for listing_id, cluster_id in sorted(przypisanie.items()):
        session.execute(USTAW_KLASTER, {"cluster_id": cluster_id, "listing_id": listing_id})

    statystyki["pary_skasowane"] = skasowane
    log.info(
        "deduplikacja: %s ofert, %s par, %s klastrow",
        statystyki["oferty"],
        statystyki["pary"],
        statystyki["klastry"],
    )
    return {**statystyki, "klastry_szczegoly": klastry}


def status(session: Session) -> dict[str, Any]:
    """Stan deduplikacji w bazie, bez przeliczania."""
    row = (
        session.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM listings WHERE is_active) AS oferty,
                    (SELECT count(*) FROM listings
                      WHERE is_active AND cluster_id IS NOT NULL) AS w_klastrach,
                    (SELECT count(DISTINCT cluster_id) FROM listings
                      WHERE cluster_id IS NOT NULL) AS klastry,
                    (SELECT count(*) FROM listing_duplicates) AS pary,
                    (SELECT count(*) FROM listing_duplicates WHERE potwierdzone IS NOT NULL)
                        AS oznakowane
                """
            )
        )
        .mappings()
        .one()
    )
    wynik = dict(row)
    oferty = int(wynik["oferty"] or 0)
    w_klastrach = int(wynik["w_klastrach"] or 0)
    klastry = int(wynik["klastry"] or 0)
    wynik["duplikaty_proc"] = round(100 * (w_klastrach - klastry) / oferty, 1) if oferty else 0.0
    return wynik


def klastry_z_bazy(session: Session, *, limit: int = 20) -> list[dict[str, Any]]:
    """Klastry z rozrzutem cen: ta sama dzialka, dwie ceny (sekcja 4.3)."""
    return [
        dict(row)
        for row in session.execute(
            text(
                """
                SELECT cluster_id,
                       count(*) AS oferty,
                       array_agg(DISTINCT portal::text) AS portale,
                       array_agg(id ORDER BY id) AS listingi,
                       min(price_grosze)/100 AS cena_min_zl,
                       max(price_grosze)/100 AS cena_max_zl,
                       min(area_m2) AS area_min,
                       max(area_m2) AS area_max
                FROM listings
                WHERE cluster_id IS NOT NULL AND is_active
                GROUP BY cluster_id
                ORDER BY count(*) DESC, cluster_id
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        .mappings()
        .all()
    ]
