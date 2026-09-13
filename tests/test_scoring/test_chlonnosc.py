"""Testy chlonnosci (sekcja 5.2.5). Wartosci oczekiwane policzone recznie.

Liczby wskaznikow sa prawdziwe: pochodza z odpowiedzi warstwy strefaPlanistyczna
dla Gdyni, sprawdzonej zywym zapytaniem 25.08.2026.
"""

from __future__ import annotations

import pytest

from grunt.scoring import chlonnosc, pillars


def test_liczba_kondygnacji_zaokragla_w_dol() -> None:
    """9 m / 3,2 m = 2,81, czyli dwie kondygnacje. Pol pietra nie istnieje."""
    assert chlonnosc.liczba_kondygnacji(9.0) == 2
    assert chlonnosc.liczba_kondygnacji(17.0) == 5  # 17 / 3,2 = 5,31
    assert chlonnosc.liczba_kondygnacji(3.2) == 1
    assert chlonnosc.liczba_kondygnacji(2.0) == 0, "limit ponizej kondygnacji to zero, nie blad"
    assert chlonnosc.liczba_kondygnacji(None) is None


def test_liczba_kondygnacji_odrzuca_ujemna_wysokosc() -> None:
    with pytest.raises(chlonnosc.ChlonnoscError):
        chlonnosc.liczba_kondygnacji(-1.0)


def test_strefa_jednorodzinna_gdynia_sj() -> None:
    """SJ w Gdyni: intensywnosc 0,4, zabudowa 25%, wysokosc 9 m, PBC 50%.

    Dzialka 1000 m2, dwie kondygnacje (9 / 3,2 = 2):
        z intensywnosci      1000 * 0,4              =  400 m2
        z udzialu zabudowy   1000 * 0,25 * 2         =  500 m2
        z biol. czynnej      1000 * (1 - 0,50) * 2   = 1000 m2
    Wiazaca jest intensywnosc: 400 m2 powierzchni calkowitej.
    SJ to zabudowa niska, wiec eta = 0,80, czyli PUM = 320 m2.
    """
    wynik = chlonnosc.oblicz(
        1000.0,
        maks_intensywnosc=0.4,
        maks_udzial_zabudowy_proc=25.0,
        maks_wysokosc_m=9.0,
        min_biologicznie_czynne_proc=50.0,
        strefa_symbol="SJ",
    )

    assert wynik.kondygnacje == 2
    assert wynik.ograniczenia == {
        "intensywnosc": 400.0,
        "udzial_zabudowy": 500.0,
        "biologicznie_czynne": 1000.0,
    }
    assert wynik.wiazace == "intensywnosc"
    assert wynik.pc_m2 == 400.0
    assert wynik.eta == 0.80
    assert wynik.pum_m2 == pytest.approx(320.0)
    assert wynik.pum_na_m2_dzialki == pytest.approx(0.32)


def test_strefa_wielorodzinna_gdynia_sw() -> None:
    """SW w Gdyni: intensywnosc 2,5, zabudowa 50%, wysokosc 17 m, PBC 30%.

    Dzialka 1000 m2, piec kondygnacji (17 / 3,2 = 5,31):
        z intensywnosci      1000 * 2,5              = 2500 m2
        z udzialu zabudowy   1000 * 0,50 * 5         = 2500 m2
        z biol. czynnej      1000 * (1 - 0,30) * 5   = 3500 m2
    Remis miedzy dwoma pierwszymi, wiec PC = 2500, eta = 0,70, PUM = 1750 m2.
    """
    wynik = chlonnosc.oblicz(
        1000.0,
        maks_intensywnosc=2.5,
        maks_udzial_zabudowy_proc=50.0,
        maks_wysokosc_m=17.0,
        min_biologicznie_czynne_proc=30.0,
        strefa_symbol="SW",
    )

    assert wynik.kondygnacje == 5
    assert wynik.pc_m2 == 2500.0
    assert wynik.eta == 0.70
    assert wynik.pum_m2 == pytest.approx(1750.0)
    assert wynik.pum_na_m2_dzialki == pytest.approx(1.75)


def test_wiazace_jest_najostrzejsze_ograniczenie_a_nie_intensywnosc() -> None:
    """Wysoka intensywnosc przy niskim budynku: wiaze udzial zabudowy.

    Intensywnosc 3,0 dopuszczalaby 3000 m2, ale przy jednej kondygnacji
    (wysokosc 4 m) i 20% zabudowy wychodzi tylko 200 m2.
    """
    wynik = chlonnosc.oblicz(
        1000.0,
        maks_intensywnosc=3.0,
        maks_udzial_zabudowy_proc=20.0,
        maks_wysokosc_m=4.0,
        min_biologicznie_czynne_proc=30.0,
        strefa_symbol="SW",
    )

    assert wynik.kondygnacje == 1
    assert wynik.wiazace == "udzial_zabudowy"
    assert wynik.pc_m2 == 200.0


def test_bez_wysokosci_udzialy_nie_ograniczaja_niczego() -> None:
    """Udzial zabudowy ogranicza RZUT. Bez liczby kondygnacji nie wiadomo nic
    o powierzchni calkowitej, wiec zostaje sama intensywnosc."""
    wynik = chlonnosc.oblicz(
        1000.0,
        maks_intensywnosc=1.2,
        maks_udzial_zabudowy_proc=40.0,
        maks_wysokosc_m=None,
        min_biologicznie_czynne_proc=25.0,
    )

    assert wynik.kondygnacje is None
    assert set(wynik.ograniczenia) == {"intensywnosc"}
    assert wynik.pc_m2 == 1200.0


def test_brak_wszystkich_wskaznikow_to_brak_wyniku_a_nie_zero() -> None:
    """Sekcja 5.3.9: brak danych wchodzi do renormalizacji wag, nie do sredniej."""
    wynik = chlonnosc.oblicz(1000.0, strefa_symbol="SO")

    assert wynik.dostepna is False
    assert wynik.pum_m2 is None
    assert wynik.pum_na_m2_dzialki is None
    assert wynik.ograniczenia == {}


def test_zerowa_powierzchnia_to_blad() -> None:
    with pytest.raises(chlonnosc.ChlonnoscError):
        chlonnosc.oblicz(0.0, maks_intensywnosc=1.0)


def test_eta_zalezy_od_strefy() -> None:
    assert chlonnosc.eta_pum("SJ") == 0.80
    assert chlonnosc.eta_pum("SZ") == 0.80
    assert chlonnosc.eta_pum("SW") == 0.70
    assert chlonnosc.eta_pum(None) == 0.70, "domyslnie ostrozniej, czyli wielorodzinna"


# ------------------------------------------------------------------ filar


def test_filar_chlonnosci_punktuje_pum_na_metr_dzialki() -> None:
    """0,32 PUM/m2 na skali 0,2-1,5 daje (0,32-0,2)/1,3 = 9,2%, czyli 9,2 pkt."""
    wynik = chlonnosc.oblicz(
        1000.0,
        maks_intensywnosc=0.4,
        maks_udzial_zabudowy_proc=25.0,
        maks_wysokosc_m=9.0,
        min_biologicznie_czynne_proc=50.0,
        strefa_symbol="SJ",
    )
    filar = pillars.pillar_chlonnosc(wynik)

    assert filar.klucz == "chlonnosc"
    assert filar.punkty == pytest.approx(9.2, abs=0.1)
    assert filar.skladniki["wiazace_ograniczenie"] == "intensywnosc"
    assert filar.skladniki["kondygnacje"] == 2


def test_filar_chlonnosci_nasyca_sie_przy_gestej_zabudowie() -> None:
    """1,75 PUM/m2 przekracza gorny prog skali, wiec 100 punktow."""
    wynik = chlonnosc.oblicz(
        1000.0,
        maks_intensywnosc=2.5,
        maks_udzial_zabudowy_proc=50.0,
        maks_wysokosc_m=17.0,
        min_biologicznie_czynne_proc=30.0,
        strefa_symbol="SW",
    )
    assert pillars.pillar_chlonnosc(wynik).punkty == 100.0


def test_filar_chlonnosci_bez_danych_jest_niedostepny() -> None:
    assert pillars.pillar_chlonnosc(None).dostepny is False
    assert pillars.pillar_chlonnosc(chlonnosc.oblicz(500.0)).dostepny is False


def test_filar_chlonnosci_nie_wchodzi_do_profilu_detalicznego() -> None:
    """Kupujacy dzialke pod wlasny dom nie chce maksymalnej chlonnosci."""
    assert "chlonnosc" not in pillars.WAGI["detaliczny"]
    assert pillars.WAGI["deweloper"]["chlonnosc"] == 0.05
