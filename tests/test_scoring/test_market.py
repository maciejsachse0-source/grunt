"""Testy dynamiki rynku (filar 6). Wartosci oczekiwane policzone recznie."""

from __future__ import annotations

import pytest

from grunt.scoring import market


def test_cagr_to_zmiana_skladana() -> None:
    """100 -> 121 przez dwa lata to 10% rocznie, nie 10,5% ze sredniej arytmetycznej."""
    assert round(market.cagr(100.0, 121.0, 2), 6) == 0.10
    assert round(market.cagr(100.0, 133.1, 3), 6) == 0.10
    assert round(market.cagr(100.0, 90.0, 1), 6) == -0.10


def test_cagr_odrzuca_bezsensowne_wejscie() -> None:
    with pytest.raises(market.MarketError):
        market.cagr(0.0, 121.0, 2)
    with pytest.raises(market.MarketError):
        market.cagr(100.0, 121.0, 0)


def test_dynamika_z_jednego_segmentu() -> None:
    mediany = {"mieszkaniowa_jednorodzinna": {2023: (100.0, 20), 2026: (133.1, 20)}}
    wynik = market.dynamika_z_median(mediany, poziom="gmina")

    assert wynik is not None
    assert round(wynik.cagr, 6) == 0.10
    assert wynik.n_obs == 20
    assert (wynik.rok_od, wynik.rok_do) == (2023, 2026)
    assert wynik.lata == 3


def test_segmenty_wazone_liczba_transakcji() -> None:
    """Segment z 20 transakcjami wazy cztery razy wiecej niz ten z pieciu.

    (0,10 * 20 + 0,20 * 5) / 25 = 0,12.
    """
    mediany = {
        "mieszkaniowa_jednorodzinna": {2024: (100.0, 20), 2026: (121.0, 20)},
        "rolna": {2024: (50.0, 12), 2026: (72.0, 12)},
    }
    wynik = market.dynamika_z_median(mediany, poziom="gmina")

    assert wynik is not None
    assert round(wynik.segmenty["mieszkaniowa_jednorodzinna"], 6) == 0.10
    assert round(wynik.segmenty["rolna"], 4) == 0.2000
    assert round(wynik.cagr, 4) == round((0.10 * 20 + 0.2 * 12) / 32, 4)


def test_rok_z_garstka_transakcji_nie_liczy_sie() -> None:
    """Trzy transakcje w roku to szum. Zostaje jeden uzyteczny rok, wiec brak wyniku."""
    mediany = {"rolna": {2024: (100.0, 3), 2026: (150.0, 40)}}
    assert market.dynamika_z_median(mediany, poziom="gmina") is None


def test_absurdalna_zmiana_jest_odrzucana() -> None:
    """+100% rocznie to artefakt skladu albo jedna duza transakcja, nie rynek."""
    mediany = {"rolna": {2024: (100.0, 15), 2026: (400.0, 15)}}
    assert market.dynamika_z_median(mediany, poziom="gmina") is None


def test_brak_dynamiki_to_none_a_nie_zero() -> None:
    """Zasada z CLAUDE.md: filar niedostepny wchodzi do renormalizacji wag."""
    assert market.dynamika_z_median({}, poziom="gmina") is None
    assert market.dynamika_z_median({"rolna": {2026: (100.0, 50)}}, poziom="gmina") is None


def test_nieznany_poziom_to_blad() -> None:
    with pytest.raises(market.MarketError):
        market.dynamika_z_median({}, poziom="powiatek")


def _dyn(poziom: str, cagr: float, n_obs: int) -> market.Dynamika:
    return market.Dynamika(cagr=cagr, poziom=poziom, n_obs=n_obs, rok_od=2023, rok_do=2026)


def test_shrinkage_miesza_poziomy_wedlug_liczby_obserwacji() -> None:
    """n=30 przy k=30 daje lambda 0,5; n=90 daje 0,75; n=270 daje 0,9.

    Wagi koncowe: gmina 0,5, powiat 0,25 * 0,75 = 0,375, wojewodztwo 0,125.
    Wynik: 0,5*0,20 + 0,375*0,10 + 0,125*0,04 = 0,1425.
    """
    wynik = market.shrinkage(
        {
            "gmina": _dyn("gmina", 0.20, 30),
            "powiat": _dyn("powiat", 0.10, 90),
            "wojewodztwo": _dyn("wojewodztwo", 0.04, 270),
        },
        k=30,
    )

    assert wynik is not None
    assert round(wynik.cagr, 6) == 0.1425
    assert wynik.wagi_poziomow == {"gmina": 0.5, "powiat": 0.375, "wojewodztwo": 0.125}
    assert round(sum(wynik.wagi_poziomow.values()), 6) == 1.0
    # opis zrodla zostaje najbardziej lokalny, mimo ze liczba jest mieszana
    assert wynik.poziom == "gmina"
    assert wynik.n_obs == 30


def test_gmina_z_garstka_transakcji_jest_sciagana_do_powiatu() -> None:
    """3 transakcje przy k=30 daja lambda 0,09: gmina prawie nie wplywa na wynik."""
    wynik = market.shrinkage(
        {
            "gmina": _dyn("gmina", 0.50, 3),
            "powiat": _dyn("powiat", 0.10, 270),
        },
        k=30,
    )

    assert wynik is not None
    assert wynik.wagi_poziomow["gmina"] < 0.10
    assert round(wynik.cagr, 4) == round(3 / 33 * 0.50 + 30 / 33 * 0.10, 4)


def test_shrinkage_z_jednym_poziomem_nic_nie_zmienia() -> None:
    wynik = market.shrinkage({"wojewodztwo": _dyn("wojewodztwo", 0.08, 5000)})
    assert wynik is not None
    assert wynik.cagr == 0.08
    assert wynik.wagi_poziomow == {"wojewodztwo": 1.0}


def test_shrinkage_bez_danych_zwraca_none() -> None:
    assert market.shrinkage({"gmina": None, "powiat": None}) is None


# ------------------------------------------------- trend szeregu kwartalnego


def _szereg(
    mediany: list[float], *, n: int = 30, krok: float = 0.25
) -> list[tuple[float, float, int]]:
    """Kwartalny szereg z zadanymi medianami. Kwartal to 0,25 roku."""
    return [(i * krok, m, n) for i, m in enumerate(mediany)]


def test_trend_wykrywa_rowny_wzrost() -> None:
    """Szereg rosnacy o 2% na kwartal to 1,02^4 - 1 = 8,24% rocznie."""
    mediany = [100.0 * 1.02**i for i in range(12)]
    wynik = market.trend_szeregu(_szereg(mediany))
    assert wynik is not None
    assert round(wynik, 4) == round(1.02**4 - 1, 4)


def test_plaski_szereg_daje_zero() -> None:
    wynik = market.trend_szeregu(_szereg([150.0] * 10))
    assert wynik is not None
    assert abs(wynik) < 1e-9


def test_jeden_dziki_kwartal_nie_ustawia_trendu() -> None:
    """To jest ten przypadek z Wejherowa: pierwszy punkt 10 zl/m2 zamiast 180.

    Iloraz koncow dawal +295% rocznie. Mediana nachylen par ma prawo drgnac,
    ale nie ma prawa oderwac sie od reszty szeregu.
    """
    zdrowe = [100.0 * 1.02**i for i in range(12)]
    zepsute = [10.0, *zdrowe[1:]]
    bez_skazy = market.trend_szeregu(_szereg(zdrowe))
    ze_skaza = market.trend_szeregu(_szereg(zepsute))
    assert bez_skazy is not None and ze_skaza is not None
    assert abs(ze_skaza - bez_skazy) < 0.02


def test_za_malo_kwartalow_to_brak_trendu() -> None:
    assert market.trend_szeregu(_szereg([100.0, 110.0, 120.0, 130.0, 140.0])) is None


def test_cienki_kwartal_to_brak_trendu() -> None:
    """Jedenascie kwartalow po osiem transakcji to jedenascie przypadkow."""
    assert market.trend_szeregu(_szereg([100.0 * 1.02**i for i in range(11)], n=8)) is None


def test_krotkie_okno_to_brak_trendu() -> None:
    """Szesc kwartalow to poltora roku. Roczne tempo bylo by ekstrapolacja."""
    assert market.trend_szeregu(_szereg([100.0 * 1.05**i for i in range(6)])) is None


def test_spadek_ma_znak_ujemny() -> None:
    wynik = market.trend_szeregu(_szereg([200.0 * 0.98**i for i in range(12)]))
    assert wynik is not None
    assert round(wynik, 4) == round(0.98**4 - 1, 4)


def test_dziury_w_szeregu_nie_przeszkadzaja() -> None:
    """Kwartal bez transakcji nie ma punktu; Theil-Sen liczy pary po datach."""
    pelny = _szereg([100.0 * 1.02**i for i in range(13)])
    z_dziurami = [p for i, p in enumerate(pelny) if i not in (3, 4, 8)]
    wynik = market.trend_szeregu(z_dziurami)
    assert wynik is not None
    assert round(wynik, 3) == round(1.02**4 - 1, 3)


def test_zerowa_mediana_nie_wysadza_logarytmu() -> None:
    punkty = [*_szereg([100.0 * 1.02**i for i in range(12)]), (3.0, 0.0, 30)]
    assert market.trend_szeregu(punkty) is not None
