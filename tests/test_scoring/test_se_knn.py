"""Testy Modelu 2 (SE-KNN). Sekcja 5.2.3."""

from __future__ import annotations

import datetime as dt
import math

import pytest

from grunt.scoring import valuation as v

AS_OF = dt.date(2026, 8, 21)


def comp(price: float, distance_m: float, area: float = 1000.0, days_ago: int = 30) -> v.Comparable:
    return v.Comparable(
        price_per_m2=price,
        area_m2=area,
        date=AS_OF - dt.timedelta(days=days_ago),
        level="gmina",
        distance_m=distance_m,
    )


def test_blizsze_transakcje_waza_wiecej() -> None:
    """Trzy transakcje po 300 zl/m2 o 100 m i trzy po 100 zl/m2 o 10 km.

    Wynik musi lezec blizej 300 niz 200, bo jadro tlumi dalekich sasiadow.
    """
    comps = [comp(300.0, 100.0) for _ in range(3)] + [comp(100.0, 10_000.0) for _ in range(3)]
    result = v.valuate_se_knn(1000, comps, as_of=AS_OF, annual_drift=0.0)
    assert result.unit_price_norm > 200.0


def test_sasiedzi_poza_promieniem_sa_pomijani() -> None:
    comps = [comp(200.0, 500.0) for _ in range(5)] + [comp(900.0, 30_000.0) for _ in range(20)]
    result = v.valuate_se_knn(1000, comps, as_of=AS_OF, max_distance_m=15_000, annual_drift=0.0)
    assert result.unit_price_norm == pytest.approx(200.0, rel=0.05)


def test_brak_odleglosci_to_blad_a_nie_cicha_wycena() -> None:
    comps = [v.Comparable(200.0, 1000.0, AS_OF, "gmina") for _ in range(5)]
    with pytest.raises(v.ValuationError):
        v.valuate_se_knn(1000, comps, as_of=AS_OF)


def test_k_ogranicza_liczbe_sasiadow() -> None:
    comps = [comp(100.0 + i, 100.0 * i) for i in range(1, 60)]
    result = v.valuate_se_knn(1000, comps, as_of=AS_OF, k=10, annual_drift=0.0)
    assert result.n_comparables <= 10


def test_malo_sasiadow_poszerza_przedzial_i_ostrzega() -> None:
    duzo = v.valuate_se_knn(
        1000, [comp(200.0, 300.0 + i) for i in range(30)], as_of=AS_OF, annual_drift=0.0
    )
    malo = v.valuate_se_knn(
        1000, [comp(200.0, 300.0 + i) for i in range(4)], as_of=AS_OF, annual_drift=0.0
    )
    assert malo.sigma_log > duzo.sigma_log
    assert any("sasiadow" in w for w in malo.warnings)


def test_dalekie_sasiedztwo_daje_ostrzezenie() -> None:
    comps = [comp(150.0, 9_000.0 + i) for i in range(10)]
    result = v.valuate_se_knn(1000, comps, as_of=AS_OF, annual_drift=0.0)
    assert any("oddalone" in w for w in result.warnings)
    assert result.extras["mediana_odleglosci_m"] > 5000


def test_prior_z_modelu_1_przyciaga_wynik() -> None:
    """Kotwica dziala jak dodatkowa obserwacja o zadanej wadze."""
    comps = [comp(300.0, 500.0) for _ in range(4)]
    bez = v.valuate_se_knn(1000, comps, as_of=AS_OF, annual_drift=0.0)
    z_priorem = v.valuate_se_knn(
        1000,
        comps,
        as_of=AS_OF,
        annual_drift=0.0,
        prior_log_price=math.log(100.0),
        prior_weight=20.0,
    )
    assert z_priorem.unit_price_norm < bez.unit_price_norm
    assert z_priorem.extras["prior_uzyty"] is True


def test_normalizacja_powierzchni_dziala_tak_jak_w_modelu_1() -> None:
    """Sasiedzi maja 2000 m2, wyceniamy 500 m2: cena za m2 musi wyjsc wyzsza."""
    comps = [comp(100.0, 200.0, area=2000.0) for _ in range(10)]
    result = v.valuate_se_knn(500, comps, as_of=AS_OF, annual_drift=0.0)
    assert result.unit_price_for_area > 100.0


def test_odstajace_ceny_sa_odrzucane() -> None:
    comps = [comp(p, 200.0) for p in (195, 198, 200, 202, 205, 199, 201, 203)]
    comps.append(comp(1.0, 210.0))
    comps.append(comp(40_000.0, 220.0))
    result = v.valuate_se_knn(1000, comps, as_of=AS_OF, annual_drift=0.0)
    assert 190 < result.unit_price_norm < 210
    assert result.dropped_outliers >= 2


def test_metoda_i_pola_wyniku() -> None:
    comps = [comp(200.0, 300.0 + i) for i in range(15)]
    result = v.valuate_se_knn(1000, comps, as_of=AS_OF, annual_drift=0.0)
    payload = result.to_dict()
    assert payload["metoda"] == "se_knn"
    assert payload["poziom"] is None
    assert payload["porownywalne"]
    assert result.extras["lambda"] == 0.7
    assert result.ci_low_grosze < result.v_hat_grosze < result.ci_high_grosze


def test_dobor_spoza_segmentu_poszerza_przedzial() -> None:
    comps = [comp(200.0, 300.0 + i) for i in range(15)]
    czysty = v.valuate_se_knn(1000, comps, as_of=AS_OF, annual_drift=0.0, segments_used=("rolna",))
    mieszany = v.valuate_se_knn(
        1000, comps, as_of=AS_OF, annual_drift=0.0, segments_used=("rolna", "lesna", "nieokreslona")
    )
    assert mieszany.sigma_log > czysty.sigma_log
