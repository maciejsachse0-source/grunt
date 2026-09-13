"""Testy korekty efektu skali. Wyniki policzone recznie, nie przepisane z kodu."""

from __future__ import annotations

import math

import numpy as np
import pytest

from grunt.scoring import normalize_area as na


def test_dzialka_referencyjna_nie_zmienia_ceny() -> None:
    """1000 m2 przy A_ref = 1000 m2 to mnoznik 1 z definicji."""
    assert na.normalize_price_per_m2(250.0, 1000.0) == pytest.approx(250.0)


def test_wzor_z_dokumentu_dla_stalej_elastycznosci() -> None:
    """p_norm = p_obs * (A_obs / A_ref)^(1 - b1).

    Dla p = 200 zl/m2, A = 2000 m2, b1 = 0,85, A_ref = 1000:
    (2000/1000)^0,15 = 2^0,15 = 1,109569...  ->  221,91 zl/m2
    """
    expected = 200.0 * 2.0**0.15
    assert na.normalize_price_per_m2(200.0, 2000.0) == pytest.approx(expected, rel=1e-9)
    assert expected == pytest.approx(221.9139, abs=1e-3)


def test_duza_dzialka_idzie_w_gore_mala_w_dol() -> None:
    """Sedno korekty: bez niej duze dzialki wygladaja na okazje, a male na drogie."""
    duza = na.normalize_price_per_m2(100.0, 10_000.0)
    mala = na.normalize_price_per_m2(100.0, 300.0)
    assert duza > 100.0 > mala


def test_denormalizacja_jest_odwrotnoscia() -> None:
    for area in (300.0, 1000.0, 2500.0, 12_000.0):
        norm = na.normalize_price_per_m2(180.0, area)
        assert na.denormalize_price_per_m2(norm, area) == pytest.approx(180.0, rel=1e-9)


def test_elastycznosc_1_oznacza_brak_korekty() -> None:
    """b1 = 1 to cena proporcjonalna do powierzchni, czyli cena za m2 stala."""
    curve = na.LogPriceCurve.constant(beta1=1.0)
    assert na.normalize_price_per_m2(150.0, 5000.0, curve=curve) == pytest.approx(150.0)


def test_estymacja_odtwarza_znana_elastycznosc() -> None:
    """Dane generowane z ln(P) = 6 + 0,8 ln(A). Estymator ma trafic w 0,8."""
    rng = np.random.default_rng(42)
    areas = np.exp(rng.uniform(math.log(200), math.log(20_000), size=2000))
    prices = np.exp(6.0 + 0.8 * np.log(areas) + rng.normal(0, 0.15, size=areas.size))

    curve = na.estimate_curve(areas, prices, knots_m2=None)
    assert curve.slope0 == pytest.approx(0.8, abs=0.02)
    assert curve.beta_at(1000.0) == pytest.approx(0.8, abs=0.02)
    assert curve.n_obs == 2000
    assert curve.r2 > 0.9


def test_estymacja_lamana_lapie_zmiane_nachylenia() -> None:
    """Ritter: relacja jest niemonotoniczna. Lamana ma to wychwycic.

    Generujemy b1 = 0,9 ponizej 3000 m2 i b1 = 0,6 powyzej.
    """
    rng = np.random.default_rng(7)
    areas = np.exp(rng.uniform(math.log(300), math.log(30_000), size=4000))
    log_a = np.log(areas)
    knot = math.log(3000.0)
    log_p = 6.0 + 0.9 * log_a - 0.3 * np.maximum(0.0, log_a - knot)
    prices = np.exp(log_p + rng.normal(0, 0.10, size=areas.size))

    curve = na.estimate_curve(areas, prices, knots_m2=(3000.0,))
    assert curve.beta_at(1000.0) == pytest.approx(0.9, abs=0.03)
    assert curve.beta_at(10_000.0) == pytest.approx(0.6, abs=0.05)


def test_wezel_bez_danych_jest_usuwany() -> None:
    """Nie dopasowujemy odcinka do trzech punktow."""
    rng = np.random.default_rng(1)
    areas = np.exp(rng.uniform(math.log(300), math.log(900), size=300))
    prices = np.exp(6.0 + 0.85 * np.log(areas))
    curve = na.estimate_curve(areas, prices, knots_m2=(3000.0, 10_000.0))
    assert curve.knots_m2 == ()


def test_lamana_jest_ciagla_na_wezle() -> None:
    """Skok na granicy przedzialu bylby bledem: dwie prawie identyczne dzialki
    nie moga dostac roznych cen znormalizowanych."""
    curve = na.LogPriceCurve(intercept=6.0, slope0=0.9, deltas=(-0.3,), knots_m2=(3000.0,))
    ponizej = na.normalize_price_per_m2(120.0, 2999.0, curve=curve)
    powyzej = na.normalize_price_per_m2(120.0, 3001.0, curve=curve)
    assert ponizej == pytest.approx(powyzej, rel=1e-3)


def test_walidacja_wykrywa_zle_dobrana_elastycznosc() -> None:
    """Test z sekcji 5.2.1: po normalizacji korelacja z ln(A) ma byc bliska zeru."""
    rng = np.random.default_rng(11)
    areas = np.exp(rng.uniform(math.log(300), math.log(20_000), size=1500))
    prices = np.exp(6.0 + 0.8 * np.log(areas) + rng.normal(0, 0.10, size=areas.size))
    unit = prices / areas

    dobra = na.check_normalization(areas, unit, curve=na.LogPriceCurve.constant(0.8))
    zla = na.check_normalization(areas, unit, curve=na.LogPriceCurve.constant(1.0))

    assert dobra.passed
    assert abs(dobra.corr_normalized) < 0.05
    assert not zla.passed
    assert abs(zla.corr_raw) > 0.5


def test_niedodatnie_wejscie_wybucha() -> None:
    with pytest.raises(na.NormalizationError):
        na.normalize_price_per_m2(0.0, 1000.0)
    with pytest.raises(na.NormalizationError):
        na.normalize_price_per_m2(200.0, 0.0)
    with pytest.raises(na.NormalizationError):
        na.estimate_curve([1, 2], [1, 2])
