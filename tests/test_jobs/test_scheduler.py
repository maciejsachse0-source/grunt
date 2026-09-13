"""Testy decyzji harmonogramu i backoffu. Bez bazy, bez czekania na zegar."""

from __future__ import annotations

import datetime as dt

from grunt.jobs import queue, scheduler

TERAZ = dt.datetime(2026, 8, 24, 12, 0, tzinfo=dt.UTC)

HARMONOGRAM_TESTOWY = (
    scheduler.Zadanie(kind="scrape", interwal=dt.timedelta(hours=6), opis="portale"),
    scheduler.Zadanie(kind="enrich", interwal=dt.timedelta(hours=1), opis="wzbogacanie"),
)


def test_zadanie_nigdy_nieuruchomione_jest_wymagalne_od_razu() -> None:
    """Pierwszy start workera ma zrobic wszystko, a nie czekac dobe."""
    zadania = scheduler.do_zaplanowania(TERAZ, {}, harmonogram=HARMONOGRAM_TESTOWY)
    assert [z.kind for z in zadania] == ["scrape", "enrich"]


def test_interwal_liczy_sie_od_ostatniego_UDANEGO_przebiegu() -> None:
    ostatnie = {
        "scrape": TERAZ - dt.timedelta(hours=5, minutes=59),
        "enrich": TERAZ - dt.timedelta(hours=1),
    }
    zadania = scheduler.do_zaplanowania(TERAZ, ostatnie, harmonogram=HARMONOGRAM_TESTOWY)
    # scrape ma jeszcze minute do terminu, enrich trafil w niego co do sekundy
    assert [z.kind for z in zadania] == ["enrich"]


def test_zadanie_juz_w_kolejce_nie_dubluje_sie() -> None:
    """Worker moze stac na dlugim scrapie. Harmonogram nie ma dokladac kolejnych."""
    zadania = scheduler.do_zaplanowania(
        TERAZ, {}, w_kolejce={"scrape"}, harmonogram=HARMONOGRAM_TESTOWY
    )
    assert [z.kind for z in zadania] == ["enrich"]


def test_domyslny_harmonogram_pokrywa_wszystkie_rodzaje_zadan() -> None:
    """Kazdy wpis harmonogramu musi miec handler, inaczej worker sie wywroci."""
    from grunt.jobs import handlers

    for zadanie in scheduler.HARMONOGRAM:
        assert zadanie.kind in handlers.HANDLERY


def test_backoff_rosnie_wykladniczo_i_ma_sufit() -> None:
    """5, 10, 20, 40 minut, dalej sufit 6 godzin."""
    assert queue.opoznienie(1) == dt.timedelta(minutes=5)
    assert queue.opoznienie(2) == dt.timedelta(minutes=10)
    assert queue.opoznienie(3) == dt.timedelta(minutes=20)
    assert queue.opoznienie(4) == dt.timedelta(minutes=40)
    assert queue.opoznienie(12) == dt.timedelta(hours=6)


def test_opis_harmonogramu_jest_czytelny_dla_cli() -> None:
    opis = {wpis["kind"]: wpis for wpis in scheduler.opis_harmonogramu()}
    assert opis["scrape"]["co_ile_godzin"] == 6.0
    assert opis["enrich"]["payload"] == {"limit": 60}


def test_scrape_raportuje_portale_bez_adaptera(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Nazwa w PORTALS_ENABLED bez adaptera musi byc widoczna w wyniku zadania.

    Bez tego "scrape done" wyglada jak przebieg po wszystkich portalach
    z konfiguracji, a faktycznie czesc z nich zostala po cichu pominieta.
    """
    from grunt.jobs import handlers
    from grunt.portals import registry

    monkeypatch.setattr(registry, "skipped", lambda: ["domiporta", "gruntguru"])
    monkeypatch.setattr(registry, "enabled", lambda: [object()])
    monkeypatch.setattr("grunt.ingest.runner.run_all", lambda *a, **k: [])

    wynik = handlers.scrape(None, {})  # type: ignore[arg-type]
    assert wynik["bez_adaptera"] == ["domiporta", "gruntguru"]


def test_scrape_nie_dopisuje_klucza_gdy_wszystkie_portale_maja_adapter(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from grunt.jobs import handlers
    from grunt.portals import registry

    monkeypatch.setattr(registry, "skipped", list)
    monkeypatch.setattr(registry, "enabled", lambda: [object()])
    monkeypatch.setattr("grunt.ingest.runner.run_all", lambda *a, **k: [])

    assert "bez_adaptera" not in handlers.scrape(None, {})  # type: ignore[arg-type]
