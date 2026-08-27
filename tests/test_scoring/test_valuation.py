"""Testy Modelu 1. Kazdy wynik policzony recznie albo wynikajacy z wlasnosci modelu."""

from __future__ import annotations

import datetime as dt
import math

import pytest

from grunt.scoring import valuation as v
from grunt.scoring.normalize_area import LogPriceCurve

AS_OF = dt.date(2026, 8, 21)


def comp(
    price_per_m2: float,
    level: v.Level = "gmina",
    area: float = 1000.0,
    days_ago: int = 30,
) -> v.Comparable:
    return v.Comparable(
        price_per_m2=price_per_m2,
        area_m2=area,
        date=AS_OF - dt.timedelta(days=days_ago),
        level=level,
    )


def test_bez_shrinkage_wychodzi_mediana() -> None:
    """Jeden poziom, dzialki referencyjne, swieze transakcje: wycena = mediana * powierzchnia."""
    comps = [comp(p, "gmina", days_ago=0) for p in (180, 200, 220)]
    result = v.valuate_median_shrinkage(1000, comps, as_of=AS_OF, annual_drift=0.0)
    assert result.unit_price_norm == pytest.approx(200.0, rel=1e-9)
    assert result.v_hat_grosze == pytest.approx(200.0 * 1000 * 100, rel=1e-9)


def test_shrinkage_ciagnie_w_strone_poziomu_nadrzednego() -> None:
    """lambda = n/(n+k). Przy n=2 i k=10 gmina wazy 2/12 = 0,1667.

    powiat: mediana 100 zl/m2 (20 transakcji), gmina: mediana 200 zl/m2 (2 transakcje).
    W logarytmach: 0,1667*ln(200) + 0,8333*ln(100) = 5,7215 -> 305,4... nie, sprawdzmy:
    ln(200)=5,29832, ln(100)=4,60517 -> 0,166667*5,29832 + 0,833333*4,60517 = 4,72070
    exp(4,72070) = 112,25 zl/m2
    """
    comps = [comp(100.0, "powiat", days_ago=0) for _ in range(20)]
    comps += [comp(200.0, "gmina", days_ago=0) for _ in range(2)]
    result = v.valuate_median_shrinkage(1000, comps, as_of=AS_OF, annual_drift=0.0)
    assert result.unit_price_norm == pytest.approx(112.25, abs=0.5)
    assert result.level_used == "gmina"


def test_duzo_lokalnych_danych_prawie_wypiera_prior() -> None:
    """n=100, k=10 -> lambda = 0,909. Wycena ma byc blisko mediany gminy."""
    comps = [comp(100.0, "powiat", days_ago=0) for _ in range(50)]
    comps += [comp(200.0, "gmina", days_ago=0) for _ in range(100)]
    result = v.valuate_median_shrinkage(1000, comps, as_of=AS_OF, annual_drift=0.0)
    expected = math.exp(0.909091 * math.log(200) + 0.090909 * math.log(100))
    assert result.unit_price_norm == pytest.approx(expected, rel=0.01)
    assert result.unit_price_norm > 180


def test_brak_danych_lokalnych_nie_wywala_modelu() -> None:
    """Kluczowa wlasnosc: model schodzi na poziom wyzej i poszerza przedzial."""
    comps = [comp(150.0, "wojewodztwo", days_ago=0) for _ in range(40)]
    result = v.valuate_median_shrinkage(1200, comps, as_of=AS_OF, annual_drift=0.0)
    assert result.level_used == "wojewodztwo"
    assert result.method.endswith("kcs")
    assert result.ci_high_grosze > result.v_hat_grosze > result.ci_low_grosze


def test_malo_porownywalnych_poszerza_przedzial() -> None:
    waski = v.valuate_median_shrinkage(
        1000, [comp(200.0, "gmina", days_ago=0) for _ in range(40)], as_of=AS_OF, annual_drift=0.0
    )
    szeroki = v.valuate_median_shrinkage(
        1000, [comp(200.0, "gmina", days_ago=0) for _ in range(4)], as_of=AS_OF, annual_drift=0.0
    )
    assert szeroki.sigma_log > waski.sigma_log
    assert szeroki.warnings


def test_jedna_transakcja_daje_ostrzezenie_a_nie_wyjatek() -> None:
    result = v.valuate_median_shrinkage(
        900, [comp(300.0, "gmina", days_ago=0)], as_of=AS_OF, annual_drift=0.0
    )
    assert result.method.endswith("regionalny")
    assert any("orientacyjna" in w for w in result.warnings)


def test_normalizacja_powierzchni_dziala_w_obie_strony() -> None:
    """Porownywalne to dzialki 2000 m2, wyceniamy 500 m2.

    Cena za m2 malej dzialki musi wyjsc WYZSZA niz duzych, bo cena jednostkowa
    spada z powierzchnia. Bez normalizacji model zwrocilby to samo 100 zl/m2.
    """
    comps = [comp(100.0, "gmina", area=2000.0, days_ago=0) for _ in range(20)]
    result = v.valuate_median_shrinkage(500, comps, as_of=AS_OF, annual_drift=0.0)
    assert result.unit_price_for_area > 100.0
    # 100 * (2000/1000)^0,15 = 110,96 znormalizowane; z powrotem na 500 m2:
    # 110,96 / (500/1000)^0,15 = 123,15
    assert result.unit_price_for_area == pytest.approx(123.15, abs=0.5)


def test_odstajaca_cena_nie_psuje_wyceny() -> None:
    """RCN zawiera ceny 1 zl (darowizny, transakcje rodzinne). MAD ma je odciac."""
    comps = [comp(p, "gmina", days_ago=0) for p in (195, 198, 200, 202, 205, 199, 201, 203)]
    comps.append(comp(1.0, "gmina", days_ago=0))
    comps.append(comp(50_000.0, "gmina", days_ago=0))
    result = v.valuate_median_shrinkage(1000, comps, as_of=AS_OF, annual_drift=0.0)
    assert 190 < result.unit_price_norm < 210
    assert result.dropped_outliers == 2


def test_indeksacja_czasowa_podnosi_stare_transakcje() -> None:
    """Transakcja sprzed 2 lat przy drifcie 8% rocznie to mnoznik 1,08^2 = 1,1664."""
    stare = [comp(100.0, "gmina", days_ago=730) for _ in range(20)]
    result = v.valuate_median_shrinkage(1000, stare, as_of=AS_OF, annual_drift=0.08)
    assert result.unit_price_norm == pytest.approx(100.0 * 1.08**2, rel=0.01)


def test_przedzial_ufnosci_rosnie_z_poziomem_ufnosci() -> None:
    comps = [comp(200.0 + i, "gmina", days_ago=0) for i in range(30)]
    p80 = v.valuate_median_shrinkage(1000, comps, as_of=AS_OF, confidence=0.80, annual_drift=0.0)
    p95 = v.valuate_median_shrinkage(1000, comps, as_of=AS_OF, confidence=0.95, annual_drift=0.0)
    assert p95.ci_high_grosze > p80.ci_high_grosze
    assert p95.ci_low_grosze < p80.ci_low_grosze


def test_niepewnosc_ma_podloge() -> None:
    """Nawet przy 200 identycznych transakcjach nie udajemy dokladnosci 1%."""
    comps = [comp(200.0, "gmina", days_ago=0) for _ in range(200)]
    result = v.valuate_median_shrinkage(1000, comps, as_of=AS_OF, annual_drift=0.0)
    assert result.sigma_log >= v.SIGMA_FLOOR_LOG


def test_deal_score_dzieli_przez_niepewnosc() -> None:
    comps = [comp(200.0, "gmina", days_ago=0) for _ in range(30)]
    wycena = v.valuate_median_shrinkage(1000, comps, as_of=AS_OF, annual_drift=0.0)
    # wycena 200 000 zl; oferta 150 000 zl
    d = v.deal_score(150_000 * 100, wycena)
    expected = (wycena.v_hat_grosze - 150_000 * 100) / (wycena.v_hat_grosze * wycena.sigma_log)
    assert d == pytest.approx(expected)
    assert d > 1.0  # tania wzgledem niepewnosci
    # oferta powyzej wyceny daje ujemny deal score
    assert v.deal_score(260_000 * 100, wycena) < 0


def test_wynik_zawiera_rozklad_na_poziomy() -> None:
    comps = [comp(100.0, "powiat", days_ago=0) for _ in range(30)]
    comps += [comp(180.0, "gmina", days_ago=0) for _ in range(10)]
    result = v.valuate_median_shrinkage(1000, comps, as_of=AS_OF, annual_drift=0.0)
    payload = result.to_dict()
    poziomy = {p["poziom"] for p in payload["poziomy"]}
    assert poziomy == {"powiat", "gmina"}
    assert payload["liczba_porownywalnych"] == 40
    assert payload["porownywalne"]
    assert payload["porownywalne"][0]["poziom"] == "gmina"  # najpierw najbardziej lokalne


def test_krzywa_niestala_jest_uzywana() -> None:
    curve = LogPriceCurve(intercept=0.0, slope0=0.95, deltas=(-0.25,), knots_m2=(3000.0,))
    comps = [comp(80.0, "gmina", area=8000.0, days_ago=0) for _ in range(20)]
    result = v.valuate_median_shrinkage(8000, comps, as_of=AS_OF, curve=curve, annual_drift=0.0)
    # ta sama powierzchnia co porownywalne, wiec normalizacja i denormalizacja
    # musza sie skrocic co do grosza
    assert result.unit_price_for_area == pytest.approx(80.0, rel=1e-9)


def test_bledne_wejscie() -> None:
    with pytest.raises(v.ValuationError):
        v.valuate_median_shrinkage(0, [comp(200.0)], as_of=AS_OF)
    with pytest.raises(v.ValuationError):
        v.valuate_median_shrinkage(1000, [], as_of=AS_OF)
    with pytest.raises(v.ValuationError):
        v.valuate_median_shrinkage(1000, [comp(200.0)], as_of=AS_OF, confidence=0.5)
