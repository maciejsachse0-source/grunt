"""Nazwy gmin w wyborze obszaru pod wykresem cen.

Gmina miejsko-wiejska ma w TERYT dwa kody: miasto konczy sie na 4, obszar
wiejski na 5. ULDK zwraca dla obu te sama nazwe, a ich mediany cen roznia sie
nawet dwukrotnie, wiec bez rodzaju lista wyboru pokazywala dwa nierozroznialne
wiersze.
"""

from __future__ import annotations

from grunt.enrich.market import nazwa_gminy


def test_miasto_w_gminie_miejsko_wiejskiej() -> None:
    assert nazwa_gminy("Kobylnica", "2212064") == "Kobylnica (miasto)"


def test_obszar_wiejski_w_gminie_miejsko_wiejskiej() -> None:
    assert nazwa_gminy("Kobylnica", "2212065") == "Kobylnica (obszar wiejski)"


def test_gmina_wiejska_i_miejska_zostaja_bez_dopisku() -> None:
    """Rodzaj 1, 2 i 3 wystepuja w powiecie tylko raz, wiec nie ma czego roznicowac."""
    assert nazwa_gminy("Szemud", "2215092") == "Szemud"
    assert nazwa_gminy("Linia", "2215062") == "Linia"


def test_nazwa_juz_doprecyzowana_przez_uldk_zostaje_nietknieta() -> None:
    assert nazwa_gminy("Rumia (miasto)", "2215021") == "Rumia (miasto)"


def test_kod_powiatu_nie_jest_gmina() -> None:
    assert nazwa_gminy("powiat wejherowski", "2215") == "powiat wejherowski"
