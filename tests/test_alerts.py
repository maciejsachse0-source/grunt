"""Testy alertow i watchdoga. Sekcje 4.2 i 7.4 dokumentu."""

from __future__ import annotations

from grunt.alerts import telegram, watchdog


def przykladowy_alert(**zmiany: object) -> telegram.Alert:
    dane: dict[str, object] = {
        "tytul": "Dzialka budowlana, Kartuzy",
        "url": "https://example.invalid/oferta/1",
        "cena_zl": 250_000,
        "powierzchnia_m2": 1000,
        "score": 74.0,
        "deal_score": 1.8,
        "coverage": 0.73,
        "plan_status": "B",
        "koszt_mediow_pln": 25_500,
    }
    dane.update(zmiany)
    return telegram.Alert(**dane)  # type: ignore[arg-type]


def test_alert_zawiera_liczby_ktore_decyduja() -> None:
    tresc = przykladowy_alert().na_tekst()
    assert "250 000 zl" in tresc
    assert "1000 m2" in tresc
    assert "250 zl/m2" in tresc  # cena jednostkowa liczona, nie przepisana
    assert "score 74" in tresc
    assert "deal +1.8" in tresc
    assert "kompletnosc 73%" in tresc


def test_alert_nie_zawiera_danych_kontaktowych() -> None:
    """Sekcja 8.2: w alercie jest link do oferty, nie telefon sprzedajacego."""
    tresc = przykladowy_alert().na_tekst()
    assert "tel" not in tresc.lower()
    assert "@" not in tresc


def test_alert_pokazuje_czerwone_flagi() -> None:
    tresc = przykladowy_alert(flagi=("waski front (14 m)", "strefa zalewowa q1")).na_tekst()
    assert "waski front" in tresc
    assert "strefa zalewowa" in tresc


def test_alert_ogranicza_liczbe_flag() -> None:
    """Alert czyta sie na telefonie, wiec nie moze byc scienna tekstu."""
    tresc = przykladowy_alert(flagi=tuple(f"flaga {i}" for i in range(10))).na_tekst()
    assert tresc.count("⚠") <= 3


def test_alert_radzi_sobie_z_brakami() -> None:
    minimalny = telegram.Alert(tytul="Dzialka", url="https://example.invalid/x")
    tresc = minimalny.na_tekst()
    assert "Dzialka" in tresc
    assert "None" not in tresc


def test_znaki_specjalne_w_tytule_nie_psuja_markdownu() -> None:
    tresc = przykladowy_alert(tytul="Dzialka *super* [okazja]").na_tekst()
    assert "\\*super\\*" in tresc


def test_klawiatura_ma_trzy_przyciski() -> None:
    """Sekcja 7.4: Zapisz, Ukryj, Otworz."""
    klawiatura = przykladowy_alert().klawiatura()
    przyciski = klawiatura["inline_keyboard"][0]
    assert [p["text"] for p in przyciski] == ["Zapisz", "Ukryj", "Otworz"]
    assert przyciski[2]["url"].startswith("https://")


def test_bez_tokena_alert_nie_wychodzi_ale_zwraca_tresc() -> None:
    """Brak konfiguracji nie moze wywalac harmonogramu."""
    wynik = telegram.send(przykladowy_alert(), dry_run=True)
    assert wynik["wyslane"] is False
    assert "score 74" in wynik["tresc"]


def test_raport_watchdoga_bez_problemow() -> None:
    assert "wszystko dziala" in watchdog.raport([])


def test_raport_watchdoga_rozroznia_alarmy_od_uwag() -> None:
    problemy = [
        watchdog.Problem("alarm", "portal_milczy", "morizon: cisza od 3 dni"),
        watchdog.Problem("uwaga", "portal_bez_ofert", "gruntguru: brak ofert"),
    ]
    tresc = watchdog.raport(problemy)
    assert "1 alarm" in tresc
    assert "‼" in tresc and "•" in tresc


def test_problem_ma_czytelna_reprezentacje() -> None:
    p = watchdog.Problem("alarm", "kod", "cos sie stalo")
    assert "cos sie stalo" in str(p)
