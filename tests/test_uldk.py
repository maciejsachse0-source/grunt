"""Testy parsera ULDK na zapisanych odpowiedziach uslugi."""

from __future__ import annotations

from pathlib import Path

import pytest

from grunt.sources import geo, uldk

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parsuje_odpowiedz_pozytywna() -> None:
    parcel = uldk.parse_response(load("uldk_gdansk_ok.txt"))
    assert parcel is not None
    assert parcel.uldk_id == "226101_1.0089.433/2"
    assert parcel.wojewodztwo == "pomorskie"
    assert parcel.numer == "433/2"
    assert parcel.geom_wkt is not None
    assert parcel.geom_wkt.startswith("SRID=2180;POLYGON")


def test_teryt_wyciagany_z_identyfikatora() -> None:
    parcel = uldk.parse_response(load("uldk_gdansk_ok.txt"))
    assert parcel is not None
    assert parcel.teryt_gmina == "2261011"  # Gdansk, miasto na prawach powiatu
    assert parcel.teryt_obreb == "0089"


def test_status_bedacy_liczba_wynikow_jest_poprawny() -> None:
    """GetParcelByIdOrNr zwraca liczbe znalezionych obiektow, nie zero."""
    parcel = uldk.parse_response(load("uldk_by_id_ok.txt"))
    assert parcel is not None
    assert parcel.uldk_id == "226101_1.0089.433/2"


def test_brak_dzialki_zwraca_none_a_nie_wyjatek() -> None:
    """Punkt na morzu albo poza ewidencja to normalny przypadek, nie blad."""
    assert uldk.parse_response(load("uldk_brak.txt")) is None


def test_pusta_odpowiedz_to_blad() -> None:
    with pytest.raises(uldk.UldkError):
        uldk.parse_response("")


def test_status_0_bez_danych_to_blad() -> None:
    with pytest.raises(uldk.UldkError):
        uldk.parse_response("0\n")


def test_za_malo_pol_to_blad() -> None:
    with pytest.raises(uldk.UldkError):
        uldk.parse_response("0\n226101_1.0089.433/2|pomorskie")


def test_strip_srid() -> None:
    srid, wkt = uldk.strip_srid("SRID=2180;POLYGON((0 0,1 0,1 1,0 0))")
    assert srid == 2180
    assert wkt == "POLYGON((0 0,1 0,1 1,0 0))"
    assert uldk.strip_srid(None) == (None, None)
    assert uldk.strip_srid("POINT(1 2)") == (None, "POINT(1 2)")


@pytest.mark.network
def test_klient_bez_cache_odpytuje_usluge() -> None:
    client = uldk.UldkClient(session=None)
    parcel = client.by_xy(geo.PL1992(easting=477471, northing=720567))
    assert parcel is not None
    assert parcel.uldk_id == "226101_1.0089.433/2"

    by_id = client.by_id(parcel.uldk_id)
    assert by_id is not None
    assert by_id.uldk_id == parcel.uldk_id


@pytest.mark.network
def test_klient_przyjmuje_wspolrzedne_z_ogloszenia() -> None:
    """Sciezka realna: oferta podaje WGS84, my potrzebujemy numeru dzialki."""
    client = uldk.UldkClient(session=None)
    parcel = client.by_latlon(54.3487, 18.6533)
    assert parcel is not None
    assert parcel.uldk_id.startswith("226101_1")
