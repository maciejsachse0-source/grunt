"""Test rekonstrukcji wyniku z zapisanych filarow.

Analiza wrazliwosci nie przelicza calego pipeline'u dla kazdej perturbacji,
tylko wazy filary zapisane w scores.pillar_scores. Ten test pilnuje, zeby ten
skrot dawal dokladnie to samo, co pillars.combine: gdyby sie
rozjechal, kalibracja mierzylaby inny scoring niz ten, ktory dziala.
"""

from __future__ import annotations

from grunt.enrich import calibrate
from grunt.scoring import gates, pillars

WAGI = pillars.WAGI["detaliczny"]


def _score_oryginalem(punkty: dict[str, float | None], mnoznik: float) -> float | None:
    filary = [pillars.PillarScore(klucz=k, punkty=v) for k, v in punkty.items()]
    gate = (
        gates.GateResult()
        if mnoznik == 1.0
        else gates.GateResult(gates=(gates.Gate(nazwa="test", mnoznik=mnoznik, powod="test"),))
    )
    return pillars.combine(filary, gate, profil="detaliczny").punkty


def test_rekonstrukcja_zgadza_sie_z_oryginalem_przy_pelnych_danych() -> None:
    punkty: dict[str, float | None] = {
        "planistyka": 80.0,
        "lokalizacja": 60.0,
        "infrastruktura": 50.0,
        "fizyka": 40.0,
        "ryzyka": 100.0,
        "rynek": 30.0,
    }
    assert calibrate.wynik_przy_wagach(punkty, dict(WAGI), mnoznik=1.0) == _score_oryginalem(
        punkty, 1.0
    )


def test_rekonstrukcja_zgadza_sie_przy_brakach_i_gate_cie() -> None:
    """Realny ksztalt danych: dwa filary niedostepne, gate poza OUZ z mnoznikiem 0,4."""
    punkty: dict[str, float | None] = {
        "planistyka": 20.0,
        "lokalizacja": None,
        "infrastruktura": 83.0,
        "fizyka": 59.7,
        "ryzyka": 100.0,
        "rynek": None,
    }
    assert calibrate.wynik_przy_wagach(punkty, dict(WAGI), mnoznik=0.4) == _score_oryginalem(
        punkty, 0.4
    )


def test_ponizej_progu_kompletnosci_nie_ma_wyniku() -> None:
    """Sekcja 5.3.9: ponizej 40% kompletnosci system nie zwraca liczby."""
    punkty: dict[str, float | None] = {
        "planistyka": None,
        "lokalizacja": None,
        "infrastruktura": None,
        "fizyka": 90.0,
        "ryzyka": None,
        "rynek": None,
    }
    assert calibrate.wynik_przy_wagach(punkty, dict(WAGI), mnoznik=1.0) is None
    assert _score_oryginalem(punkty, 1.0) is None


def test_zmiana_wag_zmienia_wynik() -> None:
    """Kontrola sensu: gdyby wagi nie wplywaly na wynik, test wrazliwosci bylby pusty."""
    punkty: dict[str, float | None] = {
        "planistyka": 90.0,
        "lokalizacja": 10.0,
        "infrastruktura": 50.0,
        "fizyka": 50.0,
        "ryzyka": 50.0,
        "rynek": 50.0,
    }
    bazowy = calibrate.wynik_przy_wagach(punkty, dict(WAGI), mnoznik=1.0)
    inne_wagi = dict(WAGI) | {"planistyka": 0.10, "lokalizacja": 0.47}
    zmieniony = calibrate.wynik_przy_wagach(punkty, inne_wagi, mnoznik=1.0)

    assert bazowy is not None and zmieniony is not None
    assert bazowy > zmieniony


# ------------------ wrazliwosc na wage pojedynczego filaru (kryterium fazy 6)


def _zbior(n: int) -> tuple[dict[int, dict[str, float | None]], dict[int, float]]:
    """n ofert, w ktorych planistyka rosnie, a infrastruktura maleje z numerem.

    Dwa filary ciagnace ranking w przeciwne strony to najostrzejszy przypadek
    dla tego testu: zmiana wagi ktoregokolwiek z nich naprawde przestawia
    kolejnosc, wiec zerowe przesuniecie nie moglo wziac sie z bezwladu danych.
    """
    filary: dict[int, dict[str, float | None]] = {}
    for i in range(1, n + 1):
        udzial = (i - 1) / (n - 1)
        filary[i] = {
            "planistyka": round(20.0 + 60.0 * udzial, 1),
            "lokalizacja": 50.0,
            "infrastruktura": round(80.0 - 60.0 * udzial, 1),
            "fizyka": 50.0,
            "ryzyka": 50.0,
            "rynek": 50.0,
        }
    return filary, dict.fromkeys(filary, 1.0)


def test_wrazliwosc_mierzy_kazdy_filar_w_obie_strony() -> None:
    filary, mnozniki = _zbior(40)
    wynik = calibrate.wrazliwosc_filarow(filary, mnozniki, wagi=WAGI)

    assert wynik["n"] == 40
    assert wynik["top_n"] == 10
    assert wynik["skala"] == 0.20
    assert len(wynik["pomiary"]) == len(WAGI) * 2
    assert {p["kierunek"] for p in wynik["pomiary"]} == {"+20%", "-20%"}
    assert {p["filar"] for p in wynik["pomiary"]} == set(WAGI)
    assert wynik["miarodajny"] is True


def test_wrazliwosc_wylapuje_ranking_rozjezdzajacy_sie_na_wadze_filaru() -> None:
    """Filar o wadze 1,0 kontra filar o wadze 0,0: kolejnosc odwraca sie calkiem.

    Planistyka rosnie, a infrastruktura maleje z numerem oferty, wiec przy
    wadze skupionej na infrastrukturze ranking jest dokladnie odwrotny.
    Przesuniecie musi wyjsc duze, inaczej pomiar niczego nie mierzy.
    """
    filary, mnozniki = _zbior(40)
    wagi = {"planistyka": 0.999, "infrastruktura": 0.001}
    wynik = calibrate.wrazliwosc_filarow(filary, mnozniki, wagi=wagi, skala=0.999, top_n=10, prog=3)

    assert wynik["spelnione"] is False
    assert wynik["max_wymiana_czolowki"] > 3, "przy odwroceniu rankingu wymienia sie cala czolowka"
    assert wynik["max_przesuniecie"] >= 20
    assert wynik["najgorszy"]["filar"] in wagi


def test_wrazliwosc_nie_uznaje_filaru_bez_danych_za_stabilny() -> None:
    """Lokalizacja i chlonnosc: 0 ofert. Ich waga wypada w renormalizacji."""
    filary, mnozniki = _zbior(40)
    for punkty in filary.values():
        punkty["lokalizacja"] = None

    wynik = calibrate.wrazliwosc_filarow(filary, mnozniki, wagi=WAGI)
    lokalizacja = [p for p in wynik["pomiary"] if p["filar"] == "lokalizacja"]

    assert wynik["filary_bez_danych"] == ["lokalizacja"]
    assert wynik["miarodajny"] is False
    assert all(p["ma_dane"] is False for p in lokalizacja)
    assert all(p["max_przesuniecie"] == 0 for p in lokalizacja), (
        "waga niedostepnego filaru nie ma jak ruszyc rankingiem"
    )


def test_wrazliwosc_odmawia_gdy_ofert_jest_mniej_niz_czolowka() -> None:
    filary, mnozniki = _zbior(6)
    wynik = calibrate.wrazliwosc_filarow(filary, mnozniki, wagi=WAGI, top_n=10)

    assert "pomiary" not in wynik
    assert "za malo ocenionych ofert" in wynik["powod"]


def test_wrazliwosc_liczy_ranking_bazowy_tym_samym_rachunkiem_co_scoring() -> None:
    """Kontrola spojnosci: ranking bazowy musi zgadzac sie z pillars.combine."""
    filary, mnozniki = _zbior(15)
    bazowy = calibrate.ranking_przy_wagach(filary, mnozniki, WAGI)

    for listing_id, punkty in filary.items():
        assert bazowy[listing_id] == _score_oryginalem(dict(punkty), 1.0)


def test_wrazliwosc_wykrywa_czolowke_rozstrzygana_jednym_filarem() -> None:
    """Realny ksztalt danych z 25.08: w top-10 rozni sie tylko fizyka.

    Gdy w czolowce jeden filar przyjmuje rozne wartosci, a pozostale sa w kazdej
    z tych ofert takie same, kolejnosc jest posortowaniem tego jednego filaru.
    Wtedy zadna zmiana wag jej nie ruszy i zerowe przesuniecie nie jest dowodem
    stabilnosci. Pomiar musi to o sobie powiedziec.
    """
    filary: dict[int, dict[str, float | None]] = {
        i: {
            "planistyka": 88.0,
            "lokalizacja": None,
            "infrastruktura": 83.0,
            "fizyka": 95.0 - i,
            "ryzyka": 100.0,
            "rynek": 36.6,
        }
        for i in range(1, 41)
    }
    wynik = calibrate.wrazliwosc_filarow(filary, dict.fromkeys(filary, 1.0), wagi=WAGI)

    assert wynik["max_przesuniecie"] == 0
    assert wynik["spelnione"] is True
    assert wynik["filary_rozniacace_czolowke"] == ["fizyka"]
    assert wynik["rozstrzygajacy"] is False, (
        "zerowe przesuniecie przy jednym zmiennym filarze to wlasciwosc rachunku, "
        "a nie wynik pomiaru"
    )


def test_wrazliwosc_jest_rozstrzygajaca_gdy_czolowke_ustala_wiecej_filarow() -> None:
    filary, mnozniki = _zbior(40)
    wynik = calibrate.wrazliwosc_filarow(filary, mnozniki, wagi=WAGI)

    assert wynik["filary_rozniacace_czolowke"] == ["infrastruktura", "planistyka"]
    assert wynik["rozstrzygajacy"] is True


def test_wrazliwosc_liczy_remisy_w_czolowce() -> None:
    """Osiem identycznych ofert w czolowce: o ich kolejnosci decyduje identyfikator."""
    filary: dict[int, dict[str, float | None]] = {}
    for i in range(1, 41):
        fizyka = 71.5 if i <= 8 else 60.0 - i
        filary[i] = {
            "planistyka": 88.0,
            "lokalizacja": None,
            "infrastruktura": 83.0,
            "fizyka": fizyka,
            "ryzyka": 100.0,
            "rynek": 36.6,
        }
    wynik = calibrate.wrazliwosc_filarow(filary, dict.fromkeys(filary, 1.0), wagi=WAGI)

    assert wynik["remisy_w_czolowce"] == 7, "osiem ofert o tym samym wyniku to siedem remisow"
