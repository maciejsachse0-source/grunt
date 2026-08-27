"""Testy porownania oferty z mediana rynku lokalnego. Sekcja 7.1.

Wartosci oczekiwane policzone recznie.
"""

from __future__ import annotations

import pytest

from grunt.scoring import market, segments


def test_indeksacja_podnosi_stara_cene_do_dzisiejszego_poziomu() -> None:
    """Transakcja sprzed dwoch lat przy dynamice 10% rocznie: 100 -> 121."""
    assert round(market.indeksuj_do_dzis(100.0, 0.10, 2.0), 6) == 121.0
    assert market.indeksuj_do_dzis(100.0, 0.10, 0.0) == 100.0


def test_bez_dynamiki_wchodzi_tempo_domyslne() -> None:
    """8% to wartosc uzywana tez przez Model 2 (annual_drift)."""
    assert round(market.indeksuj_do_dzis(100.0, None, 1.0), 6) == 108.0


def test_absurdalna_dynamika_jest_przycinana() -> None:
    """Gmina z +52% rocznie po trzech latach dawalaby mnoznik 3,5. Rynek tego nie robi."""
    przyciete = market.indeksuj_do_dzis(100.0, 0.52, 3.0)
    assert round(przyciete, 2) == round(100.0 * 1.25**3, 2)
    assert round(market.indeksuj_do_dzis(100.0, -0.90, 2.0), 2) == round(100.0 * 0.75**2, 2)


def test_odchylenie_od_mediany() -> None:
    """134 zl/m2 przy medianie 100 to +34%."""
    assert round(market.odchylenie_od_mediany(134.0, 100.0), 6) == 0.34
    assert round(market.odchylenie_od_mediany(50.0, 100.0), 6) == -0.5


def test_brak_mediany_to_none_a_nie_zero() -> None:
    """Zero znaczyloby "dokladnie w medianie", a to co innego niz "nie wiadomo"."""
    assert market.odchylenie_od_mediany(134.0, None) is None
    assert market.odchylenie_od_mediany(134.0, 0.0) is None


def _mediana(poziom: str, n: int, wartosc: float = 100.0) -> market.Mediana:
    return market.Mediana(
        poziom=poziom,
        teryt="2261011",
        segment="mieszkaniowa_jednorodzinna",
        mediana_norm=wartosc,
        p25_norm=wartosc * 0.7,
        p75_norm=wartosc * 1.4,
        n=n,
    )


def test_wybierana_jest_najbardziej_lokalna_mediana_z_dosc_danymi() -> None:
    wynik = market.wybierz_mediane(
        {
            "gmina": _mediana("gmina", 40, 300.0),
            "powiat": _mediana("powiat", 900, 200.0),
            "wojewodztwo": _mediana("wojewodztwo", 16000, 120.0),
        }
    )
    assert wynik is not None
    assert wynik.poziom == "gmina"
    assert wynik.mediana_norm == 300.0


def test_gmina_z_garstka_transakcji_ustepuje_powiatowi() -> None:
    """Inaczej niz przy dynamice NIE mieszamy poziomow.

    Uzytkownik czyta "mediana w gminie X, n=142" i to musi byc prawdziwa mediana
    tej gminy, a nie liczba sklejona z dwoch poziomow.
    """
    wynik = market.wybierz_mediane(
        {
            "gmina": _mediana("gmina", 4, 900.0),
            "powiat": _mediana("powiat", 900, 200.0),
        }
    )
    assert wynik is not None
    assert wynik.poziom == "powiat"
    assert wynik.mediana_norm == 200.0


def test_gdy_nigdzie_nie_ma_progu_wygrywa_najbogatsza_proba() -> None:
    wynik = market.wybierz_mediane({"gmina": _mediana("gmina", 3), "powiat": _mediana("powiat", 7)})
    assert wynik is not None
    assert wynik.poziom == "powiat"
    assert wynik.wiarygodna is False


def test_mediana_z_malej_proby_jest_oznaczona() -> None:
    assert _mediana("gmina", 9).wiarygodna is False
    assert _mediana("gmina", 10).wiarygodna is True


def test_rozrzut_pokazuje_jak_jednorodny_jest_rynek() -> None:
    """Kwartyle 70 i 140 przy medianie 100 to rozrzut 0,7."""
    assert round(_mediana("gmina", 100).rozrzut, 6) == 0.7


def test_brak_kandydatek_to_none() -> None:
    assert market.wybierz_mediane({"gmina": None, "powiat": None}) is None


# ------------------------------------------- segment z tresci ogloszenia


def test_segment_z_ogloszenia_rozpoznaje_typowe_sformulowania() -> None:
    assert segments.z_ogloszenia("budowlana", None) == "mieszkaniowa_jednorodzinna"
    assert segments.z_ogloszenia(None, "Działka rolna 3 ha") == "rolna"
    assert segments.z_ogloszenia(None, "Gospodarstwo rolne na sprzedaż") == "rolna"
    assert segments.z_ogloszenia(None, "Działka rekreacyjna nad jeziorem") == "rekreacyjna"
    assert segments.z_ogloszenia(None, "Grunt inwestycyjny 2 ha") == "uslugowa_produkcyjna"


def test_ogonki_nie_maja_znaczenia() -> None:
    assert segments.z_ogloszenia(None, "Działka pod zabudowę") == "mieszkaniowa_jednorodzinna"
    assert segments.z_ogloszenia(None, "dzialka pod zabudowe") == "mieszkaniowa_jednorodzinna"


def test_budowlane_rozstrzyga_przed_rolnym() -> None:
    """Dla kupujacego "rolno-budowlana" to dzialka budowlana."""
    assert segments.z_ogloszenia(None, "Działka rolno-budowlana") == "mieszkaniowa_jednorodzinna"


def test_strzepy_opisu_nie_sa_klasyfikacja() -> None:
    """To wlasnie te wartosci wrzucaly 351 z 361 ofert do zlego kubla.

    None znaczy "portal nic nie powiedzial" i uruchamia porownanie do calego
    rynku obszaru, zamiast do przypadkowego segmentu.
    """
    assert segments.z_ogloszenia("Planem Zagospodarowania", None) is None
    assert segments.z_ogloszenia("mpzp", None) is None
    assert segments.z_ogloszenia("inna", None) is None
    assert segments.z_ogloszenia(None, None) is None
    assert segments.z_ogloszenia("", "") is None


def test_tytul_bez_rodzaju_gruntu_nie_daje_segmentu() -> None:
    """Tytuly Morizona sa generowane ze wzorca i zwykle nie mowia o przeznaczeniu."""
    assert segments.z_ogloszenia(None, "Działka na sprzedaż, 719 m² Klukowo, Radarowa") is None


@pytest.mark.parametrize("tekst", ["Działka usługowa", "teren przemysłowy", "hala magazynowa"])
def test_uslugowe_i_produkcyjne(tekst: str) -> None:
    assert segments.z_ogloszenia(None, tekst) == "uslugowa_produkcyjna"
