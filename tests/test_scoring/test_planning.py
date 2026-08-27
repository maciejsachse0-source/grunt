"""Testy statusu planistycznego A-E. Sekcja 5.3.3 dokumentu."""

from __future__ import annotations

import pytest

from grunt.scoring.planning import PlanningInputs, assess, normalize_mpzp_symbol


def test_mpzp_budowlane_to_stan_A() -> None:
    w = assess(PlanningInputs(mpzp_symbol="12MN"))
    assert w.status == "A"
    assert w.mnoznik == 1.0
    assert w.gate == 1.0


def test_plan_ogolny_i_ouz_to_stan_B() -> None:
    w = assess(PlanningInputs(ma_plan_ogolny=True, w_ouz=True, strefa_symbol="SJ"))
    assert w.status == "B"
    assert 0.90 <= w.mnoznik <= 1.00
    assert w.gate == 1.0


def test_wazna_wz_to_stan_C() -> None:
    w = assess(PlanningInputs(ma_plan_ogolny=False, wz_wazna=True))
    assert w.status == "C"
    assert 0.85 <= w.mnoznik <= 0.95


def test_poza_ouz_to_stan_D_i_gate() -> None:
    """Najwazniejszy przypadek w calym module: dzialka traci sciezke do zabudowy."""
    w = assess(PlanningInputs(ma_plan_ogolny=True, w_ouz=False, strefa_symbol="SO"))
    assert w.status == "D"
    assert w.mnoznik <= 0.5
    assert w.gate == 0.40


def test_brak_planu_ogolnego_to_stan_E() -> None:
    """Dzis dotyczy ponad 90% gmin pomorskiego, wiec to nie jest przypadek brzegowy."""
    w = assess(PlanningInputs(ma_plan_ogolny=False))
    assert w.status == "E"
    assert w.gate == 1.0
    assert 0.50 <= w.mnoznik <= 0.75


def test_stan_E_ma_szerszy_przedzial_niz_B() -> None:
    """Brak planu to niepewnosc, nie zla wiadomosc. Przedzial ma to pokazywac."""
    e = assess(PlanningInputs(ma_plan_ogolny=False))
    b = assess(PlanningInputs(ma_plan_ogolny=True, w_ouz=True, strefa_symbol="SW"))
    assert e.szerokosc_przedzialu > b.szerokosc_przedzialu


def test_brak_danych_to_znak_zapytania_a_nie_stan_E() -> None:
    """None znaczy "nie wiadomo". Mylenie tego z "nie ma" zawyzaloby ocene."""
    w = assess(PlanningInputs())
    assert w.status == "?"
    assert w.pewne is False


def test_mpzp_bije_plan_ogolny() -> None:
    """MPZP jest aktem prawa miejscowego i rozstrzyga niezaleznie od OUZ."""
    w = assess(
        PlanningInputs(mpzp_symbol="MN", ma_plan_ogolny=True, w_ouz=False, strefa_symbol="SO")
    )
    assert w.status == "A"
    assert w.gate == 1.0


def test_ouz_w_strefie_nieprzeznaczonej_pod_zabudowe_jest_traktowane_ostroznie() -> None:
    w = assess(PlanningInputs(ma_plan_ogolny=True, w_ouz=True, strefa_symbol="SO"))
    assert w.status == "D"
    assert w.pewne is False


def test_poza_ouz_ale_strefa_budowlana_daje_gorna_polowe_widelek() -> None:
    poza_w_so = assess(PlanningInputs(ma_plan_ogolny=True, w_ouz=False, strefa_symbol="SO"))
    poza_w_sj = assess(PlanningInputs(ma_plan_ogolny=True, w_ouz=False, strefa_symbol="SJ"))
    assert poza_w_sj.mnoznik > poza_w_so.mnoznik
    assert poza_w_sj.status == poza_w_so.status == "D"


def test_normalizacja_symbolu_mpzp() -> None:
    # MN/U to przeznaczenie mieszkaniowo-uslugowe, wiec MNU jest trafniejsze niz MN
    assert normalize_mpzp_symbol("12MN/U") == "MNU"
    assert normalize_mpzp_symbol("12MN") == "MN"
    assert normalize_mpzp_symbol("mw") == "MW"
    assert normalize_mpzp_symbol("3.RM") == "RM"
    assert normalize_mpzp_symbol("") is None
    assert normalize_mpzp_symbol(None) is None
    assert normalize_mpzp_symbol("ZL") == "ZL"  # lesny, nierozpoznany jako budowlany


def test_mpzp_lesny_nie_jest_budowlany() -> None:
    w = assess(PlanningInputs(mpzp_symbol="ZL", ma_plan_ogolny=False))
    assert w.status == "E"


def test_mnoznik_zawsze_miesci_sie_w_przedziale() -> None:
    for wejscie in (
        PlanningInputs(mpzp_symbol="MN"),
        PlanningInputs(ma_plan_ogolny=True, w_ouz=True, strefa_symbol="SJ"),
        PlanningInputs(ma_plan_ogolny=True, w_ouz=False, strefa_symbol="SO"),
        PlanningInputs(ma_plan_ogolny=False),
        PlanningInputs(),
    ):
        w = assess(wejscie)
        assert w.mnoznik_min <= w.mnoznik <= w.mnoznik_max
        assert 0 < w.mnoznik <= 1.0
        assert 0 < w.gate <= 1.0
        assert w.to_dict()["status"] == w.status


@pytest.mark.parametrize("strefa", ["SW", "SJ", "SZ", "SU", "SH", "SP"])
def test_strefy_budowlane_w_ouz_daja_stan_B(strefa: str) -> None:
    assert (
        assess(PlanningInputs(ma_plan_ogolny=True, w_ouz=True, strefa_symbol=strefa)).status == "B"
    )


@pytest.mark.parametrize("strefa", ["SO", "SN", "SR", "SC", "SG", "SK", "SI"])
def test_strefy_niebudowlane_w_ouz_sa_podejrzane(strefa: str) -> None:
    w = assess(PlanningInputs(ma_plan_ogolny=True, w_ouz=True, strefa_symbol=strefa))
    assert w.status == "D"
    assert w.pewne is False
