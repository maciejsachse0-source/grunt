"""Rodzaj dzialki i gmina oferty. Warstwa czytajaca baze, rachunek jest w scoring/.

Ten krok jest tani: nie odpytuje zadnej uslugi zewnetrznej, liczy sie na tym,
co juz jest w bazie. Dlatego chodzi po WSZYSTKICH aktywnych ofertach, a nie
porcjami jak wzbogacanie (jedna oferta to tam ok. 20 zapytan HTTP).

DWA WYNIKI, DWA ROZNE ZRODLA

* rodzaj: scoring/rodzaj.py na podstawie strefy planu ogolnego (gdy oferta
  przeszla juz wzbogacanie) albo tresci ogloszenia;
* gmina: z dzialki ewidencyjnej, gdy dopasowanie sie udalo, a gdy nie,
  z najblizszej transakcji RCN. To nie jest zgadywanie: operator <-> na indeksie
  GiST zwraca faktycznie najblizszy punkt, a gminy maja kilkanascie kilometrow
  srednicy. Zrodlo zapisujemy obok wyniku, zeby bylo widac, ktory to przypadek.

Oferta bez wspolrzednych nie dostaje gminy. Bez tego LATERAL sortowalby
po odleglosci od NULL i wpisywal pierwsza lepsza gmine z bazy.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.scoring import rodzaj as rodzaj_scoring

log = logging.getLogger(__name__)

# TERYT gminy zapisany w identyfikatorze ULDK: "220101_1.0001.123/4" -> "2201011".
GMINA_Z_DZIALKI = """
    CASE WHEN le.parcel_uldk_id ~ '^[0-9]{6}_[0-9]'
         THEN substr(replace(split_part(le.parcel_uldk_id, '.', 1), '_', ''), 1, 7)
    END
"""

# Najblizsza transakcja RCN jako zrodlo gminy dla ofert bez pewnie dopasowanej
# dzialki. Warunek na l.geom jest w srodku celowo: dla oferty bez wspolrzednych
# odleglosc jest NULL-em, wiec LIMIT 1 zwrocilby przypadkowy wiersz.
JOIN_NAJBLIZSZEJ_GMINY = """
    LEFT JOIN LATERAL (
        SELECT r.teryt_gmina
        FROM rcn_transactions r
        WHERE l.geom IS NOT NULL
          AND r.centroid_2180 IS NOT NULL
          AND r.teryt_gmina IS NOT NULL
        ORDER BY r.centroid_2180 <-> l.geom
        LIMIT 1
    ) najblizsza ON true
"""

SELECT_OFERTY = text(
    f"""
    SELECT l.id, l.title, l.przeznaczenie_raw, le.plan_strefa,
           {GMINA_Z_DZIALKI} AS gmina_z_dzialki,
           najblizsza.teryt_gmina AS gmina_z_rcn
    FROM listings l
    LEFT JOIN listing_enrichment le ON le.listing_id = l.id
    {JOIN_NAJBLIZSZEJ_GMINY}
    WHERE l.is_active
    """  # noqa: S608 - fragmenty sa stalymi modulu, nie wejsciem uzytkownika
)

UPSERT = text(
    """
    INSERT INTO listing_category (
        listing_id, rodzaj, rodzaj_zrodlo, teryt_gmina, gmina_zrodlo, computed_at
    ) VALUES (
        :listing_id, :rodzaj, :rodzaj_zrodlo, :teryt_gmina, :gmina_zrodlo, now()
    )
    ON CONFLICT (listing_id) DO UPDATE SET
        rodzaj = EXCLUDED.rodzaj,
        rodzaj_zrodlo = EXCLUDED.rodzaj_zrodlo,
        teryt_gmina = EXCLUDED.teryt_gmina,
        gmina_zrodlo = EXCLUDED.gmina_zrodlo,
        computed_at = now()
    """
)

PORCJA = 500


def run(session: Session) -> dict[str, Any]:
    """Przeliczenie rodzaju i gminy dla wszystkich aktywnych ofert."""
    # now() jest stale w transakcji, wiec wiersze ofert, ktore w miedzyczasie
    # wygasly, zostana starsze niz znacznik i pojda do kasacji na koncu.
    znacznik = session.execute(text("SELECT now()")).scalar_one()

    rodzaje: dict[str, int] = {}
    zrodla_rodzaju: dict[str, int] = {}
    gminy: dict[str, int] = {}
    oferty = 0
    bufor: list[dict[str, Any]] = []

    for row in session.execute(SELECT_OFERTY).mappings():
        oferty += 1
        wynik = rodzaj_scoring.okresl(
            plan_strefa=row["plan_strefa"],
            przeznaczenie_raw=row["przeznaczenie_raw"],
            tytul=row["title"],
        )
        gmina = row["gmina_z_dzialki"] or row["gmina_z_rcn"]
        gmina_zrodlo = (
            "dzialka" if row["gmina_z_dzialki"] else ("rcn" if row["gmina_z_rcn"] else None)
        )

        if wynik.rodzaj is not None and wynik.zrodlo is not None:
            rodzaje[wynik.rodzaj] = rodzaje.get(wynik.rodzaj, 0) + 1
            zrodla_rodzaju[wynik.zrodlo] = zrodla_rodzaju.get(wynik.zrodlo, 0) + 1
        if gmina_zrodlo is not None:
            gminy[gmina_zrodlo] = gminy.get(gmina_zrodlo, 0) + 1

        bufor.append(
            {
                "listing_id": row["id"],
                "rodzaj": wynik.rodzaj,
                "rodzaj_zrodlo": wynik.zrodlo,
                "teryt_gmina": gmina,
                "gmina_zrodlo": gmina_zrodlo,
            }
        )
        if len(bufor) >= PORCJA:
            session.execute(UPSERT, bufor)
            bufor.clear()

    if bufor:
        session.execute(UPSERT, bufor)

    usuniete = session.execute(
        text("DELETE FROM listing_category WHERE computed_at < :znacznik"),
        {"znacznik": znacznik},
    ).rowcount

    z_rodzajem = sum(rodzaje.values())
    log.info(
        "kategorie: %s ofert, %s z rodzajem, %s z gmina", oferty, z_rodzajem, sum(gminy.values())
    )
    return {
        "oferty": oferty,
        "rodzaje": dict(sorted(rodzaje.items())),
        "bez_rodzaju": oferty - z_rodzajem,
        "zrodla_rodzaju": dict(sorted(zrodla_rodzaju.items())),
        "z_gmina": sum(gminy.values()),
        "bez_gminy": oferty - sum(gminy.values()),
        "zrodla_gminy": dict(sorted(gminy.items())),
        "usuniete_nieaktualne": usuniete,
    }
