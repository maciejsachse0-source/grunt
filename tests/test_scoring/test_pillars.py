"""Testy scoringu potencjalu: gate'y, filary, renormalizacja wag.

Sekcje 5.3.1, 5.3.2 i 5.3.9 dokumentu. Wyniki policzone recznie.
"""

from __future__ import annotations

import pytest

from grunt.scoring import gates, pillars

# ------------------------------------------------------------------ gate'y


def test_brak_gate_daje_mnoznik_jeden() -> None:
    assert gates.evaluate(road_access=2, plan_status="A").mnoznik == 1.0


def test_brak_dostepu_do_drogi_zeruje_wynik() -> None:
    """Nie "o 10% gorsza", tylko niebudowlana. To sedno idei gate'a."""
    g = gates.evaluate(road_access=0)
    assert g.mnoznik == pytest.approx(0.35)
    assert g.dyskwalifikujacy is True


def test_nieznany_dostep_do_drogi_nie_karze() -> None:
    """NULL to NULL: brak danych o drodze nie moze dzialac jak brak drogi."""
    assert gates.evaluate(road_access=None).mnoznik == 1.0


def test_status_D_wlacza_gate_planistyczny() -> None:
    g = gates.evaluate(plan_status="D")
    assert g.mnoznik == pytest.approx(0.40)
    assert "poza_ouz" in g.aktywne


def test_gate_powodziowy_bierze_najgorszy_scenariusz() -> None:
    assert gates.evaluate(strefy_powodziowe=["q10", "q1"]).mnoznik == pytest.approx(0.40)
    assert gates.evaluate(strefy_powodziowe=["hWZ"]).mnoznik == pytest.approx(0.60)


def test_gate_y_sie_mnoza() -> None:
    """Dwie wady naraz sa gorsze niz kazda osobno."""
    g = gates.evaluate(road_access=0, plan_status="D")
    assert g.mnoznik == pytest.approx(0.35 * 0.40)
    assert len(g.aktywne) == 2


# ------------------------------------------------------------------ filary


def test_filar_planistyczny_odzwierciedla_status() -> None:
    a = pillars.pillar_planistyka("A", None)
    d = pillars.pillar_planistyka("D", False)
    assert a.punkty is not None and d.punkty is not None
    assert a.punkty > d.punkty
    assert pillars.pillar_planistyka(None, None).dostepny is False


def test_infrastruktura_liczona_kosztem_a_nie_flaga() -> None:
    """Sekcja 5.3.5: 0 zl to komplet mediow, 150 tys. to praktycznie ich brak."""
    tanio = pillars.pillar_infrastruktura(25_000, 2)
    drogo = pillars.pillar_infrastruktura(120_000, 2)
    assert tanio.punkty is not None and drogo.punkty is not None
    assert tanio.punkty > drogo.punkty


def test_infrastruktura_bez_danych_jest_niedostepna() -> None:
    assert pillars.pillar_infrastruktura(None, None).dostepny is False


def test_fizyka_karze_waski_front_i_duzy_spadek() -> None:
    dobra = pillars.pillar_fizyka(front_m=28, spadek_proc=2, zwartosc=0.75)
    slaba = pillars.pillar_fizyka(front_m=11, spadek_proc=14, zwartosc=0.40)
    assert dobra.punkty is not None and slaba.punkty is not None
    assert dobra.punkty > slaba.punkty + 40


def test_fizyka_liczy_z_tego_co_jest() -> None:
    """Sam front tez wystarczy, zeby filar byl dostepny."""
    czesciowa = pillars.pillar_fizyka(front_m=24, spadek_proc=None, zwartosc=None)
    assert czesciowa.dostepny is True
    assert pillars.pillar_fizyka(None, None, None).dostepny is False


def test_ryzyka_bez_stref_daja_maksimum() -> None:
    assert pillars.pillar_ryzyka([]).punkty == 100.0


def test_ryzyka_ranguja_scenariusze_powodziowe() -> None:
    q10 = pillars.pillar_ryzyka(["q10"]).punkty
    q1 = pillars.pillar_ryzyka(["q1"]).punkty
    hwz = pillars.pillar_ryzyka(["hWZ"]).punkty
    q02 = pillars.pillar_ryzyka(["q0_2"]).punkty
    assert q10 is not None and q1 is not None and hwz is not None and q02 is not None
    assert q10 < q1 < hwz < q02 < 100


def test_niesprawdzone_ryzyka_to_brak_danych_a_nie_brak_ryzyka() -> None:
    assert pillars.pillar_ryzyka([], sprawdzone=False).dostepny is False


# --------------------------------------------------- skladanie i coverage


def komplet() -> list[pillars.PillarScore]:
    return [
        pillars.pillar_planistyka("B", True),
        pillars.pillar_lokalizacja(czas_do_rdzenia_min=25, odleglosc_do_morza_m=5000),
        pillars.pillar_infrastruktura(25_000, 2),
        pillars.pillar_fizyka(24, 3, 0.72),
        pillars.pillar_ryzyka([]),
        pillars.pillar_rynek(dynamika_cen_3y=0.10, plynnosc=4),
    ]


def test_pelny_komplet_danych_daje_wynik_i_kompletnosc_sto_procent() -> None:
    wynik = pillars.combine(komplet(), gates.evaluate(road_access=2))
    assert wynik.wiarygodny is True
    assert wynik.coverage == 1.0
    assert 0 < wynik.punkty <= 100


def test_gate_obcina_gotowy_wynik() -> None:
    bez_gate = pillars.combine(komplet(), gates.evaluate(road_access=2))
    z_gate = pillars.combine(komplet(), gates.evaluate(road_access=0))
    assert z_gate.punkty == pytest.approx(bez_gate.punkty * 0.35, abs=0.2)


def test_wagi_sa_renormalizowane_na_dostepne_filary() -> None:
    """Sekcja 5.3.9 punkt 2: S = suma(w*z po dostepnych) / suma(w po dostepnych)."""
    czesciowe = [
        pillars.pillar_planistyka("B", True),
        pillars.pillar_infrastruktura(25_000, 2),
        pillars.pillar_ryzyka([]),
        pillars.pillar_lokalizacja(),  # niedostepny
        pillars.pillar_fizyka(None, None, None),  # niedostepny
        pillars.pillar_rynek(),  # niedostepny
    ]
    wynik = pillars.combine(czesciowe, gates.evaluate())
    assert wynik.wiarygodny is True
    assert wynik.coverage == pytest.approx((0.35 + 0.18 + 0.10) / 1.0, abs=0.01)
    assert wynik.punkty is not None and wynik.punkty > 0


def test_ponizej_progu_kompletnosci_nie_ma_wyniku() -> None:
    """Regula produktowa: zly score jest gorszy niz brak score'u."""
    ubogie = [
        pillars.pillar_ryzyka([]),  # tylko 10% wagi
        pillars.pillar_planistyka(None, None),
        pillars.pillar_lokalizacja(),
        pillars.pillar_infrastruktura(None, None),
        pillars.pillar_fizyka(None, None, None),
        pillars.pillar_rynek(),
    ]
    wynik = pillars.combine(ubogie, gates.evaluate())
    assert wynik.wiarygodny is False
    assert wynik.punkty is None
    assert wynik.powod_braku is not None and "kompletnosc" in wynik.powod_braku
    assert "Planistyka" in wynik.powod_braku or "Lokalizacja" in wynik.powod_braku


def test_profil_dewelopera_wazy_planistyke_mocniej() -> None:
    assert pillars.WAGI["deweloper"]["planistyka"] > pillars.WAGI["detaliczny"]["planistyka"]
    assert (
        pillars.WAGI["deweloper"]["infrastruktura"] < pillars.WAGI["detaliczny"]["infrastruktura"]
    )


def test_wagi_kazdego_profilu_sumuja_sie_do_jednosci() -> None:
    for profil, wagi in pillars.WAGI.items():
        assert sum(wagi.values()) == pytest.approx(1.0), profil


def test_wynik_zawiera_rozbicie_na_filary_i_gate() -> None:
    wynik = pillars.combine(komplet(), gates.evaluate(strefy_powodziowe=["hWZ"]))
    payload = wynik.to_dict()
    assert len(payload["filary"]) == 6
    assert payload["gate"]["mnoznik"] == pytest.approx(0.60)
    assert payload["kompletnosc"] == 1.0
