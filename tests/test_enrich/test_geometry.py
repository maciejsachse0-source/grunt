"""Testy cech ksztaltu dzialki. Sekcja 5.3.6 dokumentu."""

from __future__ import annotations

import math

import pytest

from grunt.enrich.geometry import compactness, from_wkt


def prostokat(szer: float, dlug: float, e0: float = 468_000, n0: float = 719_000) -> str:
    return (
        f"POLYGON(({e0} {n0},{e0 + szer} {n0},{e0 + szer} {n0 + dlug},{e0} {n0 + dlug},{e0} {n0}))"
    )


def test_kwadrat_ma_zwartosc_okolo_0785() -> None:
    """4*pi*A/P^2 dla kwadratu to pi/4."""
    k = from_wkt(prostokat(30, 30))
    assert k.zwartosc == pytest.approx(math.pi / 4, abs=0.001)
    assert k.smuklosc == pytest.approx(1.0, abs=0.01)


def test_dzialka_waska_i_dluga_ma_wysoka_smuklosc() -> None:
    d = from_wkt(prostokat(10, 100))
    assert d.smuklosc == pytest.approx(10.0, abs=0.1)
    assert d.front_m == pytest.approx(10.0, abs=0.1)
    assert d.dlugosc_m == pytest.approx(100.0, abs=0.1)


def test_waski_front_daje_ostrzezenie() -> None:
    """Ponizej 18 m przepisy o odleglosci od granicy moga uniemozliwic zabudowe."""
    d = from_wkt(prostokat(12, 60))
    assert any("waski front" in u for u in d.uwagi)


def test_szeroka_dzialka_nie_ma_ostrzezenia_o_froncie() -> None:
    d = from_wkt(prostokat(25, 40))
    assert not any("front" in u for u in d.uwagi)


def test_smukla_dzialka_daje_ostrzezenie() -> None:
    d = from_wkt(prostokat(8, 90))
    assert any("smuklosc" in u for u in d.uwagi)


def test_nieregularny_ksztalt_daje_ostrzezenie() -> None:
    """Litera L: male pole przy duzym obwodzie, czyli niska zwartosc."""
    wkt = (
        "POLYGON((468000 719000,468060 719000,468060 719010,468010 719010,"
        "468010 719060,468000 719060,468000 719000))"
    )
    d = from_wkt(wkt)
    assert d.zwartosc is not None and d.zwartosc < 0.45
    assert any("nieregularny" in u for u in d.uwagi)


def test_wymiary_z_ogloszenia_maja_pierwszenstwo_przed_proxy() -> None:
    """Nieruchomosci-online podaje wymiary wprost, wiec nie zgadujemy z geometrii."""
    d = from_wkt(prostokat(30, 40), front_z_ogloszenia_m=24.0)
    assert d.front_m == 24.0
    assert d.front_zrodlo == "ogloszenie"


def test_front_z_geometrii_jest_oznaczony_jako_przyblizenie() -> None:
    """Nie mamy warstwy drog, wiec front to krotszy bok, a nie granica przy drodze."""
    d = from_wkt(prostokat(30, 40))
    assert d.front_zrodlo == "geometria (proxy)"


def test_azymut_osi_dla_dzialki_polnoc_poludnie() -> None:
    d = from_wkt(prostokat(20, 80))
    assert d.azymut_osi is not None
    assert d.azymut_osi < 10 or d.azymut_osi > 170


def test_azymut_osi_dla_dzialki_wschod_zachod() -> None:
    d = from_wkt(prostokat(80, 20))
    assert d.azymut_osi is not None
    assert 80 <= d.azymut_osi <= 100


def test_brak_geometrii_nie_wywala_ale_zachowuje_front_z_ogloszenia() -> None:
    d = from_wkt(None, front_z_ogloszenia_m=18.0)
    assert d.area_m2 is None
    assert d.front_m == 18.0
    assert d.front_zrodlo == "ogloszenie"


def test_uszkodzona_geometria_zwraca_puste_cechy() -> None:
    d = from_wkt("to nie jest WKT")
    assert d.area_m2 is None
    assert d.uwagi == ()


def test_zwartosc_wymaga_dodatnich_wartosci() -> None:
    assert compactness(0, 100) is None
    assert compactness(100, 0) is None
    assert compactness(1000, 130) == pytest.approx(0.743, abs=0.01)
