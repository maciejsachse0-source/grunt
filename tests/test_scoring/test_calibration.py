"""Testy kalibracji (sekcja 5.6). Wartosci oczekiwane policzone recznie."""

from __future__ import annotations

import math

import pytest

from grunt.scoring import calibration, valuation


def test_spread_to_mediana_ilorazu_pomniejszona_o_jeden() -> None:
    """Oferty 120, 130, 150 przy wycenach 100: mediana ilorazu 1,30, spread +30%."""
    wynik = calibration.szacuj_spread([120.0, 130.0, 150.0], [100.0, 100.0, 100.0])
    assert round(wynik.mediana, 6) == 0.30
    assert wynik.n == 3
    assert wynik.zrodlo == "oferty_vs_model"


def test_spread_odporny_na_pojedyncza_bzdure() -> None:
    """Przeniesienie po 1,8 zl/m2 przesuwa srednia, ale nie mediane.

    Piec ilorazow 1,2 i jeden 40: srednia to 7,7 (spread +670%), mediana 1,2.
    Iloraz 40 wypada zreszta poza dopuszczalny zakres i w ogole nie wchodzi.
    """
    oferty = [120.0] * 5 + [4000.0]
    wyceny = [100.0] * 6
    wynik = calibration.szacuj_spread(oferty, wyceny)
    assert round(wynik.mediana, 6) == 0.20
    assert wynik.n == 5  # obserwacja z ilorazem 40 odrzucona jako blad danych


def test_spread_ponizej_trzydziestu_obserwacji_nie_jest_wiarygodny() -> None:
    wynik = calibration.szacuj_spread([120.0] * 10, [100.0] * 10)
    assert wynik.wiarygodny is False
    assert calibration.szacuj_spread([120.0] * 30, [100.0] * 30).wiarygodny is True


def test_spread_porownany_z_zakresem_z_literatury() -> None:
    """Sekcja 5.6: 12-20% dla budowlanych, 20-35% dla rolnych."""
    wynik = calibration.szacuj_spread([115.0] * 5, [100.0] * 5)
    assert wynik.w_oczekiwanym_zakresie("budowlana") is True
    assert wynik.w_oczekiwanym_zakresie("rolna") is False
    assert wynik.w_oczekiwanym_zakresie("przemyslowa") is None


def test_bez_obserwacji_spread_to_blad_a_nie_zero() -> None:
    """Zasada z CLAUDE.md: brak danych nie zamienia sie w wartosc domyslna."""
    with pytest.raises(calibration.CalibrationError):
        calibration.szacuj_spread([], [])


def test_poziom_ofertowy_podnosi_wycene_o_spread() -> None:
    assert calibration.poziom_ofertowy(300_000.0, 0.20) == 360_000.0
    with pytest.raises(calibration.CalibrationError):
        calibration.poziom_ofertowy(300_000.0, -1.5)


def test_deal_score_bez_spreadu_jest_ujemny_a_ze_spreadem_dodatni() -> None:
    """Punkt 7 z "Czego nauczyly nas dane" i jego rozwiazanie z sekcji 5.6.

    Wycena transakcyjna 300 tys., oferta 330 tys., sigma_log 0,25.
    Bez korekty: (300 - 330) / (300 * 0,25) = -0,40.
    Ze spreadem 20%: V = 360, sigma = 90, deal = (360 - 330) / 90 = +0,333.
    """
    wycena = valuation.ValuationResult(
        v_hat_grosze=300_000_00,
        ci_low_grosze=250_000_00,
        ci_high_grosze=350_000_00,
        unit_price_norm=300.0,
        unit_price_for_area=300.0,
        sigma_log=0.25,
        confidence=0.80,
        n_comparables=20,
        method="se_knn",
        level_used="obreb",
        levels=(),
        comparables=(),
    )
    surowy = valuation.deal_score(330_000_00, wycena)
    skorygowany = valuation.deal_score(330_000_00, wycena, spread=0.20)

    assert round(surowy, 3) == -0.400
    assert round(skorygowany, 3) == 0.333


def test_spearman_na_odwroconej_kolejnosci() -> None:
    assert round(calibration.spearman([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0]), 6) == 1.0
    assert round(calibration.spearman([1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0]), 6) == -1.0


def test_spearman_usrednia_rangi_remisow() -> None:
    """Dwie rowne wartosci dostaja range 1,5, a nie 1 i 2 w przypadkowej kolejnosci."""
    a = [10.0, 10.0, 30.0, 40.0]
    b = [1.0, 2.0, 3.0, 4.0]
    assert round(calibration.spearman(a, b), 4) == round(calibration.spearman(a, b), 4)
    assert calibration.spearman(a, b) > 0.9


def test_spearman_na_stalej_serii_to_nan_a_nie_zero() -> None:
    """Korelacja z seria bez zroznicowania jest nieokreslona, nie zerowa."""
    assert math.isnan(calibration.spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]))


def test_perturbacja_wag_jest_odtwarzalna_i_sumuje_sie_do_jednego() -> None:
    wagi = {"planistyka": 0.35, "lokalizacja": 0.22, "infrastruktura": 0.18}
    a = calibration.zaburz_wagi(wagi, skala=0.3, seed=7)
    b = calibration.zaburz_wagi(wagi, skala=0.3, seed=7)
    c = calibration.zaburz_wagi(wagi, skala=0.3, seed=8)

    assert a == b, "ten sam seed musi dac te same wagi"
    assert a != c
    assert round(sum(a.values()), 9) == 1.0

    # Po renormalizacji udzial kazdej wagi moze zmienic sie najwyzej w stosunku
    # skrajnych czynnikow, czyli 1,3/0,7. Wiecej znaczyloby blad w perturbacji.
    suma_bazowa = sum(wagi.values())
    for klucz, waga in a.items():
        udzial_bazowy = wagi[klucz] / suma_bazowa
        assert 0.7 / 1.3 <= waga / udzial_bazowy <= 1.3 / 0.7


def test_stabilnosc_rankingu_gdy_kolejnosc_sie_nie_zmienia() -> None:
    bazowy = {1: 90.0, 2: 80.0, 3: 70.0, 4: 60.0, 5: 50.0}
    zaburzony = {1: 91.0, 2: 79.0, 3: 71.0, 4: 61.0, 5: 49.0}
    wynik = calibration.stabilnosc_rankingu(bazowy, zaburzony, top_n=3)

    assert wynik.pokrycie_top == 1.0
    assert round(wynik.rho, 6) == 1.0
    assert wynik.stabilny is True


def test_stabilnosc_rankingu_gdy_czolowka_sie_rozsypuje() -> None:
    """Ranking odwrocony: zaden z top-2 nie zostaje, korelacja rang -1."""
    bazowy = {1: 90.0, 2: 80.0, 3: 70.0, 4: 60.0}
    zaburzony = {1: 10.0, 2: 20.0, 3: 30.0, 4: 40.0}
    wynik = calibration.stabilnosc_rankingu(bazowy, zaburzony, top_n=2)

    assert wynik.pokrycie_top == 0.0
    assert round(wynik.rho, 6) == -1.0
    assert wynik.stabilny is False


def test_dyskryminacja_wykrywa_scoring_ktory_nic_nie_rozroznia() -> None:
    """Sekcja 5.6: 80% dzialek w przedziale 60-70 to scoring bez informacji."""
    wyniki = [65.0] * 16 + [20.0, 45.0, 80.0, 95.0]
    wynik = calibration.dyskryminacja(wyniki)

    assert wynik.n == 20
    assert wynik.udzial_najliczniejszego == 0.8
    assert wynik.przedzial_najliczniejszy == (60.0, 70.0)
    assert wynik.rozroznia is False


def test_dyskryminacja_na_rozkladzie_rozlozonym_rowno() -> None:
    wyniki = [float(5 + 10 * i) for i in range(10)] * 2
    wynik = calibration.dyskryminacja(wyniki)

    assert wynik.udzial_najliczniejszego == 0.1
    assert wynik.rozroznia is True


def test_dyskryminacja_wymaga_minimum_danych() -> None:
    with pytest.raises(calibration.CalibrationError):
        calibration.dyskryminacja([50.0] * 5)


# ------------------ wrazliwosc na wage pojedynczego filaru (kryterium fazy 6)


def test_skaluj_wage_podnosi_jeden_filar_i_renormalizuje_reszte() -> None:
    """0,50 * 1,2 = 0,60, suma 1,10, wiec po renormalizacji 0,60/1,10 = 0,545455."""
    wagi = {"a": 0.50, "b": 0.30, "c": 0.20}
    po = calibration.skaluj_wage(wagi, "a", 1.2)

    assert round(po["a"], 6) == 0.545455
    assert round(po["b"], 6) == 0.272727
    assert round(po["c"], 6) == 0.181818
    assert round(sum(po.values()), 9) == 1.0

    # Filary, ktorych nie ruszamy, zachowuja swoj wzajemny stosunek: 0,30/0,20.
    assert round(po["b"] / po["c"], 6) == 1.5


def test_skaluj_wage_w_dol_jest_odwrotnoscia_kierunku_w_gore() -> None:
    wagi = {"a": 0.50, "b": 0.50}
    assert calibration.skaluj_wage(wagi, "a", 0.8)["a"] < wagi["a"]
    assert calibration.skaluj_wage(wagi, "a", 1.2)["a"] > wagi["a"]


def test_skaluj_wage_odrzuca_nieznany_filar() -> None:
    with pytest.raises(calibration.CalibrationError):
        calibration.skaluj_wage({"a": 1.0}, "b", 1.2)


def test_pozycje_licza_od_jedynki_a_remis_rozstrzyga_identyfikator() -> None:
    assert calibration.pozycje({7: 50.0, 3: 90.0, 5: 50.0}) == {3: 1, 5: 2, 7: 3}


def test_przesuniecie_gdy_czolowka_stoi_w_miejscu() -> None:
    bazowy = {i: 100.0 - i for i in range(1, 21)}
    zmieniony = {i: 100.0 - i * 1.01 for i in range(1, 21)}
    wynik = calibration.przesuniecie_rankingu(bazowy, zmieniony, top_n=10)

    assert wynik.max_przesuniecie == 0
    assert wynik.wymiana_czolowki == 0
    assert wynik.stabilny is True


def test_przesuniecie_daleko_ale_czolowka_prawie_ta_sama() -> None:
    """Oferta spada z 1. na 11. miejsce: 10 pozycji, ale tylko jedna wymiana.

    Wyniki bazowe to 100-i, wiec oferta 11 ma 89, a oferta 12 ma 88. Oferta 1
    przestawiona na 88,5 laduje miedzy nimi: oferty 2-11 ida o miejsce w gore,
    a ona sama na 11. miejsce.

    To jest przypadek, na ktorym rozjezdzaja sie dwa odczyty kryterium sekcji 21,
    i test pilnuje, po ktorej stronie stoi werdykt. Obowiazuje sklad czolowki:
    wymienila sie JEDNA oferta z dziesieciu, wiec ranking jest stabilny, mimo
    ze najdalszy ruch wyniosl 10 pozycji. Uzasadnienie przy MAX_ZMIANA_CZOLOWKI.
    """
    bazowy = {i: 100.0 - i for i in range(1, 21)}
    zmieniony = dict(bazowy) | {1: 88.5}
    wynik = calibration.przesuniecie_rankingu(bazowy, zmieniony, top_n=10)

    assert wynik.max_przesuniecie == 10, "diagnostyka nadal liczona"
    assert wynik.mediana_przesuniecia == 1.0
    assert wynik.wymiana_czolowki == 1
    assert wynik.stabilny is True


def test_wymiana_powyzej_progu_to_ranking_niestabilny() -> None:
    """Cztery oferty z dziesiatki wypadaja poza nia: prog 3 przekroczony."""
    bazowy = {i: 100.0 - i for i in range(1, 21)}
    zmieniony = dict(bazowy) | {1: 10.0, 2: 10.1, 3: 10.2, 4: 10.3}
    wynik = calibration.przesuniecie_rankingu(bazowy, zmieniony, top_n=10)

    assert wynik.wymiana_czolowki == 4
    assert wynik.stabilny is False


def test_oferta_bez_wyniku_liczy_sie_do_wymiany_czolowki() -> None:
    """Wieksza waga niedostepnego filaru moze zbic oferte ponizej progu 40%.

    Oferta, ktora stracila wynik, wypadla z rankingu, wiec wypadla tez
    z czolowki i liczy sie do wymiany bez zadnej osobnej reguly.
    """
    bazowy = {i: 100.0 - i for i in range(1, 21)}
    zmieniony = {i: v for i, v in bazowy.items() if i != 3}
    wynik = calibration.przesuniecie_rankingu(bazowy, zmieniony, top_n=10)

    assert wynik.bez_wyniku == 1
    assert wynik.wymiana_czolowki == 1
    assert wynik.stabilny is True

    # Cztery oferty bez wyniku to juz przekroczenie progu.
    bez_czterech = {i: v for i, v in bazowy.items() if i not in (1, 2, 3, 4)}
    gorszy = calibration.przesuniecie_rankingu(bazowy, bez_czterech, top_n=10)
    assert gorszy.bez_wyniku == 4
    assert gorszy.stabilny is False


def test_prog_dotyczy_skladu_a_nie_pozycji() -> None:
    """Kontrola samej decyzji: prog czyta sie jako liczba wymienionych ofert.

    Gdyby werdykt wracal do odczytu przez pozycje, ten test padnie i zmusi
    do przeczytania uzasadnienia przy MAX_ZMIANA_CZOLOWKI, zamiast po cichu
    zmienic znaczenie kryterium akceptacji fazy 6.
    """
    bazowy = {i: 100.0 - i for i in range(1, 51)}
    # Jedna oferta z czolowki na sam koniec stawki: 45 pozycji, jedna wymiana.
    wynik = calibration.przesuniecie_rankingu(bazowy, dict(bazowy) | {5: 0.0}, top_n=10)

    assert wynik.max_przesuniecie == 45
    assert wynik.wymiana_czolowki == 1
    assert wynik.stabilny is True


def test_przesuniecie_odrzuca_ranking_bez_trzech_ofert() -> None:
    with pytest.raises(calibration.CalibrationError):
        calibration.przesuniecie_rankingu({1: 10.0, 2: 20.0}, {1: 10.0, 2: 20.0})
