"""Zapis geometrii dzialki: czesc czysta, czyli obsluga WKT ze zrodel.

EGiB oddaje samo "MULTIPOLYGON(...)", ULDK "SRID=2180;POLYGON(...)". Rozne
formaty ida do tej samej kolumny, wiec rozbieznosc rozstrzygamy raz, tutaj.
"""

from __future__ import annotations

from grunt.enrich.parcel_store import strip_srid


def test_wkt_z_egib_przechodzi_bez_zmian() -> None:
    wkt = "MULTIPOLYGON(((1 2,3 4,5 6,1 2)))"
    assert strip_srid(wkt) == wkt


def test_prefiks_srid_z_uldk_jest_scinany() -> None:
    assert strip_srid("SRID=2180;POLYGON((1 2,3 4,5 6,1 2))") == "POLYGON((1 2,3 4,5 6,1 2))"


def test_obcy_uklad_jest_odrzucany_zamiast_zgadywany() -> None:
    """Geometria w 4326 zapisana jako 2180 wyladowalaby poza Polska i nikt by
    tego nie zauwazyl, bo obrys po prostu by sie nie pokazal."""
    assert strip_srid("SRID=4326;POLYGON((18 54,18 55,19 55,18 54))") is None


def test_brak_geometrii_to_brak_wyniku() -> None:
    assert strip_srid(None) is None
    assert strip_srid("") is None
    assert strip_srid("   ") is None
    assert strip_srid("SRID=2180;") is None
