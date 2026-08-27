"""Zapis geometrii dzialki ewidencyjnej do tabeli parcels.

Do 25.08.2026 wzbogacanie pobieralo geometrie z EGiB, liczylo z niej front,
smuklosc i zwartosc (geometry.py), po czym ja wyrzucalo. Tabela parcels
i kolumna listings.parcel_id istnialy od migracji 001 i staly puste.

Mapa potrzebuje tej geometrii, zeby narysowac obrys kliknietej dzialki.
Alternatywa, czyli pytanie ULDK przy kazdym kliknieciu, oznaczaloby zapytanie
do uslugi GUGiK w sciezce zadania API: wolniej, zawodniej i wbrew sekcji
o higienie w CLAUDE.md. Wiec zapisujemy raz, przy wzbogacaniu.

Zapisujemy geometrie dla KAZDEGO dopasowania, ktore ma ksztalt, takze przy
pewnosci low. Poziom pewnosci zostaje w listing_enrichment.parcel_match
i to on decyduje, jak mapa obrys narysuje. Ukrycie dzialki low byloby strata
informacji, a narysowanie jej jak pewnej byloby klamstwem.

Bez I/O sieciowego: wejsciem jest WKT, ktory ktos juz pobral.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

# ST_Multi, bo EGiB oddaje MULTIPOLYGON, a ULDK zwykle POLYGON, kolumna zas
# jest MULTIPOLYGON. COALESCE w UPDATE: druga oferta na tej samej dzialce nie
# moze skasowac atrybutu, ktory przyniosla pierwsza.
_UPSERT_PARCEL = text(
    """
    INSERT INTO parcels (uldk_id, geom, area_ewid_m2, teryt_gmina, teryt_obreb)
    VALUES (
        :uldk_id,
        ST_Multi(ST_GeomFromText(:wkt, 2180)),
        :area_ewid_m2, :teryt_gmina, :teryt_obreb
    )
    ON CONFLICT (uldk_id) DO UPDATE SET
        geom = EXCLUDED.geom,
        area_ewid_m2 = COALESCE(EXCLUDED.area_ewid_m2, parcels.area_ewid_m2),
        teryt_gmina  = COALESCE(EXCLUDED.teryt_gmina, parcels.teryt_gmina),
        teryt_obreb  = COALESCE(EXCLUDED.teryt_obreb, parcels.teryt_obreb)
    RETURNING id
    """
)

_LINK_LISTING = text("UPDATE listings SET parcel_id = :parcel_id WHERE id = :listing_id")

_UNLINK_LISTING = text("UPDATE listings SET parcel_id = NULL WHERE id = :listing_id")


def strip_srid(wkt: str | None) -> str | None:
    """ULDK oddaje 'SRID=2180;POLYGON(...)', EGiB samo 'MULTIPOLYGON(...)'.

    Inny SRID niz 2180 odrzucamy zamiast zgadywac: geometria w zlym ukladzie
    wyladowalaby po drugiej stronie Polski i nikt by tego nie zauwazyl.
    """
    tekst = (wkt or "").strip()
    if not tekst:
        return None
    if tekst.upper().startswith("SRID="):
        naglowek, _, reszta = tekst.partition(";")
        kod = naglowek[5:].strip()
        if kod and kod != "2180":
            return None
        return reszta.strip() or None
    return tekst


def upsert(
    session: Session,
    *,
    uldk_id: str,
    geom_wkt: str,
    area_ewid_m2: int | None = None,
    teryt_gmina: str | None = None,
    teryt_obreb: str | None = None,
) -> int | None:
    """Zapisuje dzialke i zwraca jej id. None, gdy geometria jest bezuzyteczna."""
    wkt = strip_srid(geom_wkt)
    if not wkt:
        return None
    return session.execute(
        _UPSERT_PARCEL,
        {
            "uldk_id": uldk_id,
            "wkt": wkt,
            "area_ewid_m2": area_ewid_m2,
            "teryt_gmina": teryt_gmina,
            "teryt_obreb": teryt_obreb,
        },
    ).scalar_one()


def link(session: Session, *, listing_id: int, parcel_id: int | None) -> None:
    """Wiaze oferte z dzialka albo zrywa wiazanie, gdy dopasowania nie ma."""
    if parcel_id is None:
        session.execute(_UNLINK_LISTING, {"listing_id": listing_id})
    else:
        session.execute(_LINK_LISTING, {"listing_id": listing_id, "parcel_id": parcel_id})
