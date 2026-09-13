"""Testy wiazania oferty z dzialka ewidencyjna.

Kontekst pomiarowy z zywych danych (2026-08-21), ktory ksztaltuje te reguly:
* wspolrzedne z portali sa przyblizone (Morizon mylil sie o 21% powierzchni,
  N-O trafil w dzialke-matke 18 983 m2 przy ofercie 835 m2);
* w promieniu 150 m od oferty w Gdansku lezy 16 dzialek o powierzchni zgodnej
  z ogloszeniem, wiec sama powierzchnia nie rozstrzyga.

Stad zasada: system woli powiedziec "nie wiem" niz przypisac ofercie cechy
cudzego gruntu.
"""

from __future__ import annotations

from grunt.enrich.match_parcel import area_ratio, choose_parcel
from grunt.sources.egib import EgibParcel


# Kwadrat o boku 30 m (900 m2) zaczepiony w podanym rogu
def kwadrat(id_dzialki: str, easting: float, northing: float, bok: float) -> EgibParcel:
    e, n, b = easting, northing, bok
    wkt = f"MULTIPOLYGON((({e} {n},{e + b} {n},{e + b} {n + b},{e} {n + b},{e} {n})))"
    return EgibParcel(
        id_dzialki=id_dzialki,
        numer_dzialki=id_dzialki.split(".")[-1],
        numer_obrebu="0036",
        nazwa_obrebu="Testowo",
        nazwa_gminy="M.Testowo",
        geom_wkt=wkt,
        area_m2=b * b,
    )


PUNKT_E, PUNKT_N = 468_500.0, 719_500.0


def test_punkt_w_dzialce_i_zgodna_powierzchnia_to_wysoka_pewnosc() -> None:
    dzialki = [kwadrat("x.1", 468_490, 719_490, 30)]  # 900 m2, punkt w srodku
    wynik = choose_parcel(
        dzialki, point_easting=PUNKT_E, point_northing=PUNKT_N, declared_area_m2=900
    )
    assert wynik.confidence == "high"
    assert wynik.parcel is not None and wynik.parcel.id_dzialki == "x.1"
    assert wynik.usable_for_features is True


def test_punkt_w_dzialce_ale_inna_powierzchnia_to_niska_pewnosc() -> None:
    """Przypadek z Katow Rybackich: punkt trafil w dzialke-matke."""
    dzialki = [kwadrat("x.matka", 468_400, 719_400, 140)]  # 19 600 m2
    wynik = choose_parcel(
        dzialki, point_easting=PUNKT_E, point_northing=PUNKT_N, declared_area_m2=835
    )
    assert wynik.confidence == "low"
    assert wynik.usable_for_features is False
    assert "powierzchnia sie nie zgadza" in wynik.reason


def test_zgodna_powierzchnia_obok_punktu_to_srednia_pewnosc() -> None:
    dzialki = [
        kwadrat("x.daleka", 468_560, 719_560, 30),  # 900 m2, ok. 60 m od punktu
        kwadrat("x.duza", 468_400, 719_400, 140),  # obejmuje punkt, ale 19 600 m2
    ]
    wynik = choose_parcel(
        dzialki, point_easting=PUNKT_E, point_northing=PUNKT_N, declared_area_m2=900
    )
    assert wynik.confidence == "medium"
    assert wynik.parcel is not None and wynik.parcel.id_dzialki == "x.daleka"
    assert wynik.usable_for_features is True


def test_kilka_dzialek_o_tej_samej_powierzchni_to_niska_pewnosc() -> None:
    """Realia podmiejskiej zabudowy: sasiednie parcele maja podobny rozmiar.

    Pomiar w Gdansku: 16 kandydatow w promieniu 150 m. Wskazanie jednego z nich
    byloby zgadywaniem, wiec system tego nie robi.
    """
    dzialki = [
        kwadrat("x.1", 468_530, 719_530, 30),
        kwadrat("x.2", 468_540, 719_545, 30),
        kwadrat("x.3", 468_555, 719_535, 30),
    ]
    wynik = choose_parcel(
        dzialki, point_easting=PUNKT_E, point_northing=PUNKT_N, declared_area_m2=900
    )
    assert wynik.confidence == "low"
    assert wynik.usable_for_features is False
    assert len(wynik.alternatives) >= 1


def test_brak_kandydatow_w_promieniu() -> None:
    dzialki = [kwadrat("x.1", 470_000, 721_000, 30)]  # kilka kilometrow dalej
    wynik = choose_parcel(
        dzialki, point_easting=PUNKT_E, point_northing=PUNKT_N, declared_area_m2=900
    )
    assert wynik.confidence == "none"
    assert wynik.parcel is None


def test_brak_powierzchni_w_ofercie_nie_wywala_dopasowania() -> None:
    dzialki = [kwadrat("x.1", 468_490, 719_490, 30)]
    wynik = choose_parcel(
        dzialki, point_easting=PUNKT_E, point_northing=PUNKT_N, declared_area_m2=None
    )
    assert wynik.confidence == "low"
    assert wynik.usable_for_features is False


def test_zgodnosc_powierzchni_jest_symetryczna() -> None:
    assert area_ratio(1000, 1000) == 1.0
    assert area_ratio(900, 1000) == area_ratio(1000, 900)
    assert area_ratio(500, 1000) == 0.5
    assert area_ratio(None, 1000) is None
    assert area_ratio(0, 1000) is None
