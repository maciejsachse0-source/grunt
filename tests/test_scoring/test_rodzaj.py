"""Testy rodzaju dzialki. Wejscia sa przepisane z prawdziwych rekordow bazy.

Pulapki, ktore te testy pilnuja, wyszly z pomiaru na 7 300 aktywnych ofertach
25.08.2026, a nie z wyobrazni: "Smoldzinski Las" w tytule, ulica "Lesna"
w adresie i wies "Lesniewo" to trzy rozne sposoby na zrobienie z dzialki
budowlanej dzialki lesnej.
"""

from __future__ import annotations

import pytest

from grunt.scoring import rodzaj


def test_strefa_planu_ogolnego_ma_pierwszenstwo_przed_ogloszeniem() -> None:
    """Strefa mowi, co WOLNO postawic. Ogloszenie tylko, co ktos chce sprzedac."""
    wynik = rodzaj.okresl(plan_strefa="SP", przeznaczenie_raw="dzialka budowlana")
    assert wynik.rodzaj == "przemyslowa"
    assert wynik.zrodlo == "plan_ogolny"


@pytest.mark.parametrize(
    ("strefa", "oczekiwany"),
    [
        ("SJ", "mieszkaniowa"),
        ("SW", "mieszkaniowa"),
        ("SZ", "mieszkaniowa"),
        ("SU", "uslugowa"),
        ("SH", "uslugowa"),
        ("SP", "przemyslowa"),
    ],
)
def test_strefy_mapuja_sie_na_kubelki(strefa: str, oczekiwany: str) -> None:
    assert rodzaj.ze_strefy(strefa) == oczekiwany


@pytest.mark.parametrize("strefa", ["SR", "SN", "SI", "SC", "SG", "SO", "SK", "", None])
def test_strefa_spoza_czterech_kategorii_nie_dostaje_rodzaju(strefa: str | None) -> None:
    """Strefa rolnicza to nie jest zadna z czterech kategorii. None, nie zgadywanie."""
    assert rodzaj.ze_strefy(strefa) is None


def test_pierwsze_slowo_w_zdaniu_rozstrzyga() -> None:
    """Zapis z planu wymienia wiodace przeznaczenie jako pierwsze."""
    assert (
        rodzaj.z_przeznaczenia("teren zabudowy mieszkaniowej jednorodzinnej z uslugami")
        == "mieszkaniowa"
    )
    assert rodzaj.z_przeznaczenia("teren zabudowy uslugowej i mieszkaniowej") == "uslugowa"
    assert rodzaj.z_przeznaczenia("teren produkcyjno-uslugowy") == "przemyslowa"


def test_kody_przeznaczenia_z_otodomu() -> None:
    """Otodom podaje gotowa kategorie, adapter tlumaczy ja na polskie slowo."""
    assert rodzaj.z_przeznaczenia("budowlana") == "mieszkaniowa"
    assert rodzaj.z_przeznaczenia("przemyslowa") == "przemyslowa"
    assert rodzaj.z_przeznaczenia("lesna") == "lesna"
    assert rodzaj.z_przeznaczenia("siedliskowa") == "mieszkaniowa"


def test_kategorie_bez_odpowiednika_zostaja_bez_rodzaju() -> None:
    """Rolna, rekreacyjna i inwestycyjna nie sa zadna z czterech kategorii."""
    assert rodzaj.z_przeznaczenia("rolna") is None
    assert rodzaj.z_przeznaczenia("rekreacyjna") is None
    assert rodzaj.z_przeznaczenia("inwestycyjna") is None
    assert rodzaj.okresl(przeznaczenie_raw="rolna").zrodlo is None


def test_ogonki_nie_maja_znaczenia() -> None:
    assert rodzaj.z_przeznaczenia("teren zabudowy usługowej") == "uslugowa"
    assert rodzaj.z_przeznaczenia("działka leśna") == "lesna"


def test_nazwa_miejscowosci_w_tytule_nie_robi_dzialki_lesnej() -> None:
    """Trzy prawdziwe tytuly z bazy. Zaden nie mowi nic o rodzaju dzialki."""
    assert rodzaj.z_tytulu("Działka na sprzedaż, 1508 m² Smołdzino, Smołdziński Las") is None
    assert rodzaj.z_tytulu("Działka na sprzedaż, 926 m² Leśniewo, Kwiatowa") is None
    assert rodzaj.z_tytulu("Działka na sprzedaż, 570 m² Smolno, Leśna") is None


def test_tytul_dziala_tylko_w_oknie_po_slowie_dzialka() -> None:
    assert rodzaj.z_tytulu("Działka budowlana 800 m², ul. Leśna") == "mieszkaniowa"
    assert rodzaj.z_tytulu("Sprzedam grunt leśny 3 ha") == "lesna"


def test_tytul_jest_ostatnia_deska_ratunku() -> None:
    """Przeznaczenie bije tytul, a tytul wchodzi dopiero, gdy przeznaczenia brak."""
    wynik = rodzaj.okresl(
        przeznaczenie_raw="teren zabudowy usługowej", tytul="Działka budowlana 800 m²"
    )
    assert wynik.rodzaj == "uslugowa"

    wynik = rodzaj.okresl(przeznaczenie_raw="MPZP", tytul="Działka budowlana 800 m²")
    assert wynik.rodzaj == "mieszkaniowa"
    assert wynik.zrodlo == "ogloszenie"


def test_brak_danych_to_brak_rodzaju() -> None:
    """NULL to NULL: pusta oferta nie dostaje kategorii domyslnej."""
    wynik = rodzaj.okresl()
    assert wynik.rodzaj is None
    assert wynik.zrodlo is None
    assert wynik.to_dict() == {"rodzaj": None, "zrodlo": None}


def test_zdanie_o_mpzp_bez_przeznaczenia_nic_nie_mowi() -> None:
    """Najczestsza wartosc w bazie: "planem zagospodarowania przestrzennego"."""
    assert rodzaj.z_przeznaczenia("planem zagospodarowania przestrzennego") is None


def test_zabudowa_uslugowa_wygrywa_z_ogolnym_pod_zabudowe() -> None:
    """Prawdziwy rekord z bazy: "przeznaczona pod zabudowę usługową".

    Bez wyjatku "pod zabudowe" padalo w zdaniu wczesniej niz "uslugowa"
    i dzialka uslugowa ladowala w kubelku mieszkaniowym.
    """
    assert rodzaj.z_przeznaczenia("mpzp i przeznaczona pod zabudowę usługową") == "uslugowa"
    assert rodzaj.z_przeznaczenia("działka pod zabudowę") == "mieszkaniowa"


def test_symbole_mpzp_mn_i_mw() -> None:
    """MN i MW sa jednoznaczne. ZL, U i P celowo nie sa rozpoznawane."""
    assert rodzaj.z_przeznaczenia("MPZP o symbolu terenu MN1") == "mieszkaniowa"
    assert rodzaj.z_przeznaczenia("planem zagospodarowania 43 U/MN, MW") == "mieszkaniowa"
    # "zl" po zdjeciu ogonkow to zlotowka, nie zielen lesna
    assert rodzaj.z_przeznaczenia("MPZP | 1 019 m² 220 000 zł Słajszewo") is None
