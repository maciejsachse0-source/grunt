"""Testy zrodel fizycznych i ryzyk: NMT, ISOK, KIUT.

Czesc czysta (gradient, koszty, gate) testowana bez sieci. Testy sieciowe
sprawdzaja punkty o znanych wlasciwosciach terenowych i sa oznaczone markerem.
"""

from __future__ import annotations

import pytest

from grunt.sources import geo, isok, kiut, nmt

# Punkty referencyjne o znanych cechach
GDANSK_CENTRUM = (54.3487, 18.6533)  # ok. 5 m n.p.m., pelne uzbrojenie
KATY_RYBACKIE = (54.3400378, 19.2319577)  # Mierzeja: 1,7 m n.p.m., strefa hWZ
KARTUZY = (54.3336, 18.1976)  # wysoczyzna, ok. 206 m n.p.m.


# ------------------------------------------------------------------- NMT


def test_teren_plaski_ma_zerowy_spadek() -> None:
    plaski = [100.0] * 8
    spadek, azymut = nmt.slope_from_grid(100.0, plaski, step_m=10)
    assert spadek == 0.0
    assert azymut is None


def test_stok_opadajacy_na_poludnie() -> None:
    """Polnoc wyzej, poludnie nizej: woda splywa na poludnie, azymut ok. 180."""
    # kolejnosc: N, NE, E, SE, S, SW, W, NW
    ring = [110.0, 110.0, 100.0, 90.0, 90.0, 90.0, 100.0, 110.0]
    spadek, azymut = nmt.slope_from_grid(100.0, ring, step_m=10)
    assert spadek is not None and spadek > 0
    assert azymut is not None and 150 <= azymut <= 210


def test_spadek_jest_w_procentach() -> None:
    """Roznica 10 m na 10 m odleglosci to 100%, czyli 45 stopni.

    Wschod i zachod musza byc na wysokosci srodka, inaczej powstaje takze
    gradient wschod-zachod i wypadkowa jest wieksza niz 100%.
    """
    ring = [110.0, 110.0, 100.0, 90.0, 90.0, 90.0, 100.0, 110.0]
    spadek, _ = nmt.slope_from_grid(100.0, ring, step_m=10)
    assert spadek is not None
    assert 95 <= spadek <= 105


def test_spadek_skosny_jest_wypadkowa_obu_osi() -> None:
    """Stok opadajacy na poludniowy zachod ma spadek wiekszy niz kazda ze skladowych."""
    ring = [110.0, 110.0, 110.0, 110.0, 90.0, 90.0, 90.0, 90.0]
    spadek, azymut = nmt.slope_from_grid(100.0, ring, step_m=10)
    assert spadek is not None and spadek > 100
    assert azymut is not None


def test_brak_wysokosci_nie_daje_spadku() -> None:
    """NULL to NULL: bez kompletu pomiarow nie zgadujemy nachylenia."""
    assert nmt.slope_from_grid(None, [100.0] * 8, 10) == (None, None)
    assert nmt.slope_from_grid(100.0, [100.0] * 7 + [None], 10) == (None, None)
    assert nmt.slope_from_grid(100.0, [100.0] * 3, 10) == (None, None)


# ------------------------------------------------------------------ ISOK


def test_gate_bierze_najpowazniejszy_scenariusz() -> None:
    ryzyko = isok.FloodRisk(strefy=("q1", "q0_2"), sprawdzone=tuple(isok.SCENARIUSZE))
    assert ryzyko.gate == 0.55
    assert ryzyko.najpowazniejsza == "q1"


def test_brak_stref_to_brak_kary() -> None:
    ryzyko = isok.FloodRisk(strefy=(), sprawdzone=tuple(isok.SCENARIUSZE))
    assert ryzyko.gate == 1.0
    assert ryzyko.zagrozona is False
    assert ryzyko.kompletne is True


def test_powodz_dziesiecioletnia_jest_grozniejsza_niz_piecsetletnia() -> None:
    """Sekcja 5.3.7: q10 to sygnal znacznie powazniejszy niz q0_2."""
    assert isok.GATE["q10"] < isok.GATE["q0_2"]


def test_niepelne_sprawdzenie_jest_widoczne() -> None:
    ryzyko = isok.FloodRisk(strefy=(), sprawdzone=("q1",), bledy=("q10: timeout",))
    assert ryzyko.kompletne is False


def test_wykrywanie_obiektow_w_odpowiedzi() -> None:
    assert isok._ma_obiekty('{"type":"FeatureCollection","features":[{"id":1}]}') is True
    assert isok._ma_obiekty('{"type":"FeatureCollection","features":[]}') is False
    assert isok._ma_obiekty("") is False
    assert isok._ma_obiekty("nie-json") is False


# ------------------------------------------------------------------ KIUT


def test_koszt_rosnie_z_odlegloscia() -> None:
    blisko = kiut.Utilities(
        odleglosci={"prad": "<=50m", "woda": "<=50m", "kanalizacja": "<=50m", "gaz": "<=50m"},
        w_zasiegu_uslugi=True,
    )
    daleko = kiut.Utilities(
        odleglosci={
            "prad": "50-200m",
            "woda": "50-200m",
            "kanalizacja": "50-200m",
            "gaz": "50-200m",
        },
        w_zasiegu_uslugi=True,
    )
    assert daleko.koszt_pln() > blisko.koszt_pln()


def test_brak_sieci_wodnej_przelacza_na_studnie() -> None:
    """Sekcja 5.3.5: przy sieci dalej niz 200 m tansza jest studnia glebinowa."""
    bez_wody = kiut.Utilities(
        odleglosci={"prad": "<=50m", "woda": ">200m", "kanalizacja": "<=50m", "gaz": "<=50m"},
        w_zasiegu_uslugi=True,
    )
    koszt = bez_wody.koszt_pln()
    assert koszt is not None
    assert koszt < 4_500 + 50_000 + 7_500 + 5_500  # tansze niz ciagniecie sieci


def test_poza_zasiegiem_uslugi_nie_zgadujemy_kosztu() -> None:
    """Brak danych to nie brak sieci (sekcja 5.3.5, ostrzezenie o warstwie gesut)."""
    nieznane = kiut.Utilities(
        odleglosci=dict.fromkeys(kiut.MEDIA_PODSTAWOWE, "brak danych"),
        w_zasiegu_uslugi=False,
    )
    assert nieznane.koszt_pln() is None
    assert nieznane.dostepne == ()


def test_lista_dostepnych_mediow() -> None:
    media = kiut.Utilities(
        odleglosci={
            "prad": "<=50m",
            "woda": "50-200m",
            "kanalizacja": ">200m",
            "gaz": "brak danych",
        },
        w_zasiegu_uslugi=True,
    )
    assert set(media.dostepne) == {"prad", "woda"}


# ------------------------------------------------------------ na zywo


@pytest.mark.network
def test_nmt_rozroznia_mierzeje_od_wysoczyzny() -> None:
    """Katy Rybackie leza na poziomie morza, Kartuzy 200 m wyzej."""
    mierzeja = nmt.height(geo.wgs84_to_pl1992(*KATY_RYBACKIE))
    wysoczyzna = nmt.height(geo.wgs84_to_pl1992(*KARTUZY))
    assert mierzeja is not None and wysoczyzna is not None
    assert mierzeja < 10
    assert wysoczyzna > 150


@pytest.mark.network
def test_isok_wykrywa_scenariusz_morski_na_mierzei() -> None:
    """Sekcja 5.3.7 wymienia Mierzeje Wislana jako obszar krytyczny."""
    ryzyko = isok.query(geo.wgs84_to_pl1992(*KATY_RYBACKIE))
    assert "hWZ" in ryzyko.strefy
    assert ryzyko.gate < 1.0


@pytest.mark.network
def test_isok_nie_zglasza_powodzi_na_wysoczyznie() -> None:
    ryzyko = isok.query(geo.wgs84_to_pl1992(*KARTUZY))
    assert ryzyko.strefy == ()


@pytest.mark.network
def test_kiut_widzi_uzbrojenie_w_centrum_miasta() -> None:
    media = kiut.query(geo.wgs84_to_pl1992(*GDANSK_CENTRUM))
    assert media.w_zasiegu_uslugi is True
    assert set(media.dostepne) >= {"prad", "woda", "kanalizacja"}


# ---------------- wskazniki zabudowy ze strefy planistycznej (filar chlonnosci)


def test_wskazniki_zabudowy_z_realnej_odpowiedzi_strefy() -> None:
    """Slownik jak z GetFeatureInfo warstwy strefaPlanistyczna, Gdynia, SJ.

    Zapisany z zywej odpowiedzi 25.08.2026. Usluga oddaje wskazniki w tym samym
    zapytaniu, ktorym pytamy o symbol strefy, wiec filar chlonnosci nie kosztuje
    ani jednego zapytania wiecej.
    """
    from grunt.sources import plan_ogolny

    strefa = {
        "gml_id": "PL.ZIPPZP.9790_226201-POG_1POG-77SJ_20260218T113323",
        "oznaczenie": "77SJ",
        "symbol": "SJ",
        "obowiazujeOd": "2026/04/26",
        "maksNadziemnaIntensywnoscZabudowy": "0.4",
        "maksUdzialPowierzchniZabudowy": "25",
        "maksWysokoscZabudowy": "9",
        "maksWysokoscZabudowy_uom": "m",
        "minUdzialPowierzchniBiologicznieCzynnej": "50",
    }
    w = plan_ogolny.wskazniki_ze_strefy(strefa)

    assert w.maks_intensywnosc == 0.4
    assert w.maks_udzial_zabudowy_proc == 25.0
    assert w.maks_wysokosc_m == 9.0
    assert w.min_biologicznie_czynne_proc == 50.0
    assert w.pusty is False


def test_wskazniki_zabudowy_puste_pole_to_brak_a_nie_zero() -> None:
    """Strefa gospodarcza bez limitu wysokosci ma None, nie 0 m."""
    from grunt.sources import plan_ogolny

    w = plan_ogolny.wskazniki_ze_strefy(
        {"symbol": "SP", "maksNadziemnaIntensywnoscZabudowy": "1.5", "maksWysokoscZabudowy": ""}
    )

    assert w.maks_intensywnosc == 1.5
    assert w.maks_wysokosc_m is None
    assert w.maks_udzial_zabudowy_proc is None
    assert w.pusty is False


def test_wskazniki_zabudowy_ze_strefy_bez_zadnego_pola() -> None:
    from grunt.sources import plan_ogolny

    assert plan_ogolny.wskazniki_ze_strefy({"symbol": "SO"}).pusty is True


def test_wskazniki_zabudowy_przecinek_dziesietny() -> None:
    """Usluga potrafi podac 0,4 zamiast 0.4."""
    from grunt.sources import plan_ogolny

    w = plan_ogolny.wskazniki_ze_strefy({"maksNadziemnaIntensywnoscZabudowy": "0,4"})
    assert w.maks_intensywnosc == 0.4
