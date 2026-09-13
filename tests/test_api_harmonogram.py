"""Zakladka rytmu pobran: /api/harmonogram.

Testy pilnuja tego samego, co przy metodologii: strona ma byc odczytem z kodu
i z bazy, a nie druga kopia liczb. Interwal, ktory zobaczy uzytkownik, musi byc
TYM SAMYM interwalem, wedlug ktorego planuje worker, bo inaczej strona opisuje
system, ktorego nie ma.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from grunt.api.main import app
from grunt.api.routers import harmonogram as modul
from grunt.config import settings
from grunt.ingest import runner
from grunt.jobs import queue, scheduler
from grunt.portals import otodom, registry


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def baza_dziala(client: TestClient) -> bool:
    return client.get("/api/health").json()["database"].get("ok", False)


@pytest.mark.db
def test_harmonogram_odpowiada(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    odpowiedz = client.get("/api/harmonogram")
    assert odpowiedz.status_code == 200
    assert set(odpowiedz.json()) == {
        "teraz",
        "worker",
        "scrape",
        "portale",
        "zadania",
        "zasady",
    }


@pytest.mark.db
def test_interwaly_sa_te_same_co_w_schedulerze(client: TestClient, baza_dziala: bool) -> None:
    """Gdyby strona miala wlasna kopie interwalow, opisywalaby sama siebie."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    dane = client.get("/api/harmonogram").json()

    ze_strony = {z["kind"]: z["co_ile_godzin"] for z in dane["zadania"]}
    z_kodu = {z.kind: z.interwal.total_seconds() / 3600 for z in scheduler.HARMONOGRAM}
    assert ze_strony == z_kodu
    assert dane["scrape"]["co_ile_godzin"] == z_kodu["scrape"]


@pytest.mark.db
def test_zasady_ida_z_konfiguracji(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    zasady = client.get("/api/harmonogram").json()["zasady"]
    assert zasady["odstep_s"] == settings.scraper_delay_seconds
    assert zasady["maks_stron_na_przebieg"] == settings.scraper_max_pages_per_run
    assert zasady["wygaszenie_po_dniach"] == runner.STALE_AFTER_DAYS
    assert zasady["maks_prob"] == queue.MAX_PROB
    assert zasady["user_agent"] == settings.scraper_user_agent


@pytest.mark.db
def test_kazdy_adapter_ma_wiersz(client: TestClient, baza_dziala: bool) -> None:
    """Portal wlaczony i milczacy ma byc wierszem z zerami, a nie brakiem wiersza.

    To jest cala wartosc tej tabeli: cisza po portalu musi byc widoczna, bo
    wyglada dokladnie tak samo jak rynek bez nowych ofert.
    """
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    portale = client.get("/api/harmonogram").json()["portale"]
    nazwy = {p["portal"] for p in portale}
    assert set(registry.ADAPTERS) <= nazwy
    assert set(registry.skipped()) <= nazwy


@pytest.mark.db
def test_nastepny_przebieg_to_ostatni_plus_interwal(client: TestClient, baza_dziala: bool) -> None:
    """Harmonogram liczy sie od ostatniego udanego przebiegu, nie od pelnej godziny."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    scrape = client.get("/api/harmonogram").json()["scrape"]
    if scrape["ostatni"] is None:
        pytest.skip("scrape nie uruchomil sie jeszcze ani razu")
    ostatni = dt.datetime.fromisoformat(scrape["ostatni"])
    nastepny = dt.datetime.fromisoformat(scrape["nastepny"])
    assert nastepny - ostatni == dt.timedelta(hours=scrape["co_ile_godzin"])


def test_limit_stron_odczytany_z_adaptera() -> None:
    """Limit stron ma byc policzony wolaniem adaptera, a nie przepisany z komentarza.

    Bez bazy: to czysta funkcja na adapterach, wiec test nie ma powodu jej wymagac.
    """
    limity = {nazwa: modul._limit_stron(adapter) for nazwa, adapter in registry.ADAPTERS.items()}
    # Morizon i Gratka koncza na dziesiatej stronie przez wlasny robots.txt.
    assert limity["morizon"] == 10
    assert limity["gratka"] == 10
    # Otodom ma wlasny limit z higieny scrapingu, nie z robots.txt.
    assert limity["otodom"] == otodom.MAX_PAGES_PER_RUN
    # Portal bez wlasnego limitu siega do sufitu z konfiguracji.
    assert limity["nieruchomosci_online"] == settings.scraper_max_pages_per_run
    assert all(1 <= limit <= settings.scraper_max_pages_per_run for limit in limity.values())
