"""Testy parsera RCN na zapisanej odpowiedzi WFS.

Fixture pobrany na zywo 2026-08-21 z bboxu 3x3 km w Gdansku, filtr:
grunty niezabudowane, transakcje od 2024-01-01.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from grunt.sources import geo, rcn

FIXTURE = Path(__file__).parent / "fixtures" / "rcn_wfs_gdansk.xml"


@pytest.fixture(scope="module")
def records() -> list[rcn.RcnRecord]:
    return rcn.parse_response(FIXTURE.read_text(encoding="utf-8"))


def test_parsuje_wszystkie_rekordy(records: list[rcn.RcnRecord]) -> None:
    assert len(records) == 3


def test_pierwszy_rekord_ma_pelne_dane(records: list[rcn.RcnRecord]) -> None:
    r = records[0]
    assert r.id_dzialki == "226101_1.0091.81/23"
    assert r.teryt_powiat == "2261"
    assert r.data_trans == dt.date(2024, 9, 9)
    assert r.cena_grosze == 387_450_000  # 3 874 500 zl
    assert r.pow_gruntu_m2 == 151
    assert r.udzial == "1/1"
    assert r.rodzaj_trans == "wolnyRynek"
    assert r.nier_rodzaj == "nieruchomoscGruntowaNiezabudowana"


def test_cena_m2_liczona_z_poziomu_transakcji(records: list[rcn.RcnRecord]) -> None:
    """Cena i powierzchnia dotycza calej transakcji, nie pojedynczej dzialki."""
    r = records[0]
    assert r.cena_m2 == pytest.approx(3_874_500 / 151, rel=1e-6)


def test_udzial_ulamkowy_odpada_z_modelu(records: list[rcn.RcnRecord]) -> None:
    """Rekord 1/222 przy powierzchni 1 m2 to udzial we wspolwlasnosci, nie dzialka."""
    ulamkowe = [r for r in records if r.udzial not in (None, "1/1")]
    assert ulamkowe, "fixture mial zawierac przyklad udzialu ulamkowego"
    for r in ulamkowe:
        assert r.is_usable_for_model is False


def test_rekord_kompletny_nadaje_sie_do_modelu(records: list[rcn.RcnRecord]) -> None:
    assert records[0].is_usable_for_model is True


def test_geometria_ma_odwrocone_osie(records: list[rcn.RcnRecord]) -> None:
    """gml:posList jest w kolejnosci northing easting; my zapisujemy easting northing.

    Sprawdzenie merytoryczne: pierwsza wspolrzedna musi wygladac jak easting
    Gdanska (ok. 476-479 tys.), a nie jak northing (ok. 719-722 tys.).
    """
    wkt = records[0].geom_wkt
    assert wkt is not None
    assert wkt.startswith("MULTIPOLYGON(((")
    first_pair = wkt.split("(((", 1)[1].split(",", 1)[0]
    easting, northing = (float(v) for v in first_pair.split())
    assert 476_000 < easting < 479_000
    assert 719_000 < northing < 722_000
    # i to samo formalnie: walidator zakresow nie moze protestowac
    geo.PL1992(easting=easting, northing=northing)


def test_pusta_cena_nie_wywraca_parsera() -> None:
    xml = """<?xml version="1.0"?>
    <wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"
        xmlns:ms="http://mapserver.gis.umn.edu/mapserver">
      <wfs:member><ms:dzialki>
        <ms:teryt>2205</ms:teryt>
        <ms:dok_data>2025-03-01 02:00:00+02</ms:dok_data>
        <ms:nier_cena_brutto></ms:nier_cena_brutto>
        <ms:dzi_pow_ewid>1200</ms:dzi_pow_ewid>
      </ms:dzialki></wfs:member>
    </wfs:FeatureCollection>"""
    record = rcn.parse_response(xml)[0]
    assert record.cena_grosze is None
    assert record.is_usable_for_model is False
    assert record.cena_m2 is None


def test_wyjatek_wfs_jest_zglaszany() -> None:
    xml = """<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1">
        <ows:Exception><ows:ExceptionText>msWFSGetFeature(): blad</ows:ExceptionText></ows:Exception>
    </ows:ExceptionReport>"""
    with pytest.raises(rcn.RcnError):
        rcn.parse_response(xml)


def test_filtr_ogc_ma_kolejnosc_osi_northing_easting() -> None:
    bbox = geo.BBox2180(476_000, 719_000, 479_000, 722_000)
    filter_xml = rcn.build_filter(bbox, since=dt.date(2024, 1, 1))
    assert "<gml:lowerCorner>719000.0 476000.0</gml:lowerCorner>" in filter_xml
    assert "urn:ogc:def:crs:EPSG::2180" in filter_xml
    assert "nieruchomoscGruntowaNiezabudowana" in filter_xml
    assert "<fes:And>" in filter_xml


def test_filtr_bez_daty_nie_owija_w_and() -> None:
    bbox = geo.BBox2180(476_000, 719_000, 479_000, 722_000)
    filter_xml = rcn.build_filter(bbox, nier_rodzaj=None)
    assert "<fes:And>" not in filter_xml


def test_zasieg_wojewodztwa_obejmuje_gdansk() -> None:
    from grunt.sources.rcn_import import region_bbox

    bbox = region_bbox("22")
    assert bbox.min_easting < 477_471 < bbox.max_easting
    assert bbox.min_northing < 720_567 < bbox.max_northing


@pytest.mark.network
def test_hits_zwraca_sensowna_liczbe() -> None:
    bbox = geo.BBox2180(476_000, 719_000, 479_000, 722_000)
    total = rcn.count_features(bbox, since=dt.date(2024, 1, 1))
    assert 100 < total < 10_000
