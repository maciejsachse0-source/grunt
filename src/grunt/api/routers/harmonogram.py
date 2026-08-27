"""GET /api/harmonogram: kiedy i co ile pobieramy nowe oferty.

PO CO TO ISTNIEJE. Na kazdej innej zakladce widac WYNIK zbierania danych, ale
nie widac jego RYTMU. Pytanie "czy ta lista jest sprzed godziny, czy sprzed
tygodnia" rozstrzyga o tym, czy w ogole warto na nia patrzec, a odpowiedz na nie
byla dotad rozsypana po kodzie: interwaly w jobs/scheduler.py, limity stron
w portals/, odstepy miedzy zadaniami w sources/_http.py.

ZASADA TA SAMA CO NA ZAKLADCE METODOLOGII: zadna liczba nie jest tu przepisana
recznie. Interwaly ida z scheduler.HARMONOGRAM, odstepy i limity z konfiguracji
i z samych adapterow, a daty przebiegow z tabeli jobs. Jesli ktos zmieni
interwal scrape'u na 12 godzin, ta strona pokaze 12 godzin w tej samej sekundzie.

DWIE RZECZY, KTORE STRONA MA POWIEDZIEC WPROST, BO INACZEJ MYLA:

1. Harmonogram nie jest zegarem sciennym. Zadanie jest wymagalne po uplywie
   interwalu OD OSTATNIEGO UDANEGO PRZEBIEGU, wiec przebiegi nie wypadaja
   o rownych godzinach i przesuwaja sie po kazdej dluzszej przerwie.
2. Nic nie dzieje sie samo, dopoki nie chodzi worker. Zatrzymany worker nie
   generuje bledu, tylko cisze, a cisza wyglada dokladnie tak samo jak rynek
   bez nowych ofert. Dlatego pole "ostatnie zadanie" jest tu wazniejsze niz
   sam harmonogram.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.config import settings
from grunt.db import get_db
from grunt.ingest import runner
from grunt.jobs import queue, scheduler
from grunt.portals import registry
from grunt.portals.base import PortalAdapter

router = APIRouter()

# Po jakiej ciszy uznajemy, ze worker nie chodzi. Najkrotszy interwal
# w harmonogramie to godzina, wiec zdrowy worker zapisuje cos przynajmniej raz
# na godzine. Kwadrans marginesu na dlugie zadanie i na to, ze petla spi.
PROG_CISZY = dt.timedelta(minutes=75)

PORTALE_STAN = text(
    """
    SELECT portal::text AS portal,
           count(*) AS ofert,
           count(*) FILTER (WHERE is_active) AS aktywnych,
           count(*) FILTER (WHERE first_seen_at > now() - interval '24 hours') AS nowych_24h,
           count(*) FILTER (WHERE first_seen_at > now() - interval '7 days') AS nowych_7d,
           max(first_seen_at) AS ostatnia_nowa,
           max(last_seen_at) AS ostatnio_widziana
    FROM listings
    GROUP BY portal
    """
)

PRZEBIEGI = text(
    """
    SELECT id, status, created_at, finished_at, attempts, last_error, wynik
    FROM jobs
    WHERE kind = 'scrape'
    ORDER BY COALESCE(finished_at, created_at) DESC, id DESC
    LIMIT 5
    """
)

STAN_KOLEJKI = text("SELECT status, count(*) AS ile FROM jobs GROUP BY status")

NAJBLIZSZE = text("SELECT min(run_after) AS kiedy FROM jobs WHERE status = 'pending'")

OSTATNIA_AKTYWNOSC = text("SELECT max(finished_at) AS kiedy FROM jobs")


@router.get("/harmonogram")
def harmonogram(session: Session = Depends(get_db)) -> dict[str, Any]:
    teraz = dt.datetime.now(dt.UTC)

    ostatnie_udane = queue.ostatnie_udane(session)
    w_kolejce = queue.w_kolejce(session)
    stan = {r["portal"]: dict(r) for r in session.execute(PORTALE_STAN).mappings()}
    przebiegi = [dict(r) for r in session.execute(PRZEBIEGI).mappings()]
    kolejka = {r["status"]: r["ile"] for r in session.execute(STAN_KOLEJKI).mappings()}
    najblizsze = session.execute(NAJBLIZSZE).scalar()
    aktywnosc = session.execute(OSTATNIA_AKTYWNOSC).scalar()

    zadanie_scrape = next(z for z in scheduler.HARMONOGRAM if z.kind == "scrape")

    return {
        "teraz": teraz,
        "worker": _sekcja_worker(teraz, aktywnosc, kolejka, najblizsze),
        "scrape": _sekcja_scrape(teraz, zadanie_scrape, ostatnie_udane, w_kolejce, przebiegi),
        "portale": _sekcja_portale(stan, przebiegi),
        "zadania": _sekcja_zadania(teraz, ostatnie_udane, w_kolejce),
        "zasady": _sekcja_zasady(),
    }


# ------------------------------------------------------------------- sekcje


def _sekcja_worker(
    teraz: dt.datetime,
    aktywnosc: dt.datetime | None,
    kolejka: dict[str, int],
    najblizsze: dt.datetime | None,
) -> dict[str, Any]:
    cisza = (teraz - aktywnosc) if aktywnosc else None
    return {
        "opis": (
            "Harmonogram wykonuje jeden proces: petla workera. Sprawdza, ktore zadania "
            "sa wymagalne, dopisuje je do kolejki i bierze z niej jedno na raz. Bez "
            "uruchomionego workera nie pobiera sie nic i nie ma o tym zadnego bledu."
        ),
        "jak_uruchomic": "uv run python scripts/jobs.py worker",
        "ostatnie_zadanie": aktywnosc,
        "cisza_minut": round(cisza.total_seconds() / 60, 1) if cisza else None,
        "prog_ciszy_minut": PROG_CISZY.total_seconds() / 60,
        # Domysl, nie pomiar: worker nie melduje sie osobno, wiec jedynym sladem
        # jego zycia sa zakonczone zadania.
        "prawdopodobnie_chodzi": bool(cisza and cisza < PROG_CISZY),
        "kolejka": {
            "czeka": kolejka.get("pending", 0),
            "w_trakcie": kolejka.get("running", 0),
            "zakonczone": kolejka.get("done", 0),
            "nieudane": kolejka.get("failed", 0),
        },
        "najblizsze_zadanie": najblizsze,
        "odstep_petli_s": 30.0,
    }


def _sekcja_scrape(
    teraz: dt.datetime,
    zadanie: scheduler.Zadanie,
    ostatnie_udane: dict[str, dt.datetime],
    w_kolejce: set[str],
    przebiegi: list[dict[str, Any]],
) -> dict[str, Any]:
    """Sam przebieg po portalach: co ile, kiedy ostatnio, kiedy nastepny."""
    ostatni = ostatnie_udane.get("scrape")
    nastepny = (ostatni + zadanie.interwal) if ostatni else None
    return {
        "co_ile_godzin": zadanie.interwal.total_seconds() / 3600,
        "dlaczego_tyle": (
            "Nowa oferta dzialki pojawia sie w skali godzin, nie minut, a strategia DIFF "
            "i tak pobiera strone oferty tylko dla ofert nowych i zmienionych. Szesc godzin "
            "to cztery przebiegi na dobe przy ruchu, ktorego portal nie ma powodu zauwazyc."
        ),
        "ostatni": ostatni,
        "nastepny": nastepny,
        "za_ile_godzin": (
            round((nastepny - teraz).total_seconds() / 3600, 1)
            if nastepny and nastepny > teraz
            else None
        ),
        "w_kolejce": "scrape" in w_kolejce,
        "strategia": (
            "Jeden przebieg obchodzi po kolei wszystkie wlaczone portale, wiec wszystkie "
            "maja ten sam rytm. Dla kazdego portalu pobierane sa strony wynikow, hash ceny "
            "i powierzchni jest porownywany z baza, a strona oferty schodzi tylko dla "
            "pozycji nowych i zmienionych. Oferta niewidziana przez "
            f"{runner.STALE_AFTER_DAYS} dni zostaje oznaczona jako nieaktywna."
        ),
        "przebiegi": [
            {
                "id": p["id"],
                "status": p["status"],
                "start": p["created_at"],
                "koniec": p["finished_at"],
                "trwalo_minut": (
                    round((p["finished_at"] - p["created_at"]).total_seconds() / 60, 1)
                    if p["finished_at"] and p["created_at"]
                    else None
                ),
                "prob": p["attempts"],
                "blad": p["last_error"],
                "portale": (p["wynik"] or {}).get("portale", []),
            }
            for p in przebiegi
        ],
    }


def _limit_stron(adapter: PortalAdapter) -> int:
    """Ile stron wynikow adapter odda, zanim powie "dalej nie wolno".

    Liczone przez wolanie next_page_url, a nie przepisane z komentarza
    w adapterze: Morizon i Gratka koncza na dziesiatej stronie przez robots.txt,
    Otodom i nieruchomosci-online dopiero na limicie z konfiguracji.
    """
    sufit = settings.scraper_max_pages_per_run
    url = next(iter(adapter.list_urls(settings.region_teryt)), adapter.base_url)
    strona = 2
    while strona <= sufit and adapter.next_page_url(url, strona):
        strona += 1
    return strona - 1


def _sekcja_portale(
    stan: dict[str, dict[str, Any]], przebiegi: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Portal po portalu: skad startuje, ile stron obchodzi, co przyniosl.

    Lista idzie po ADAPTERS, a nie po tym, co jest w bazie, zeby portal wlaczony
    i milczacy byl widoczny jako wiersz z zerami, a nie jako brak wiersza.
    """
    ostatni_udany = next((p for p in przebiegi if p["status"] == "done"), None)
    z_przebiegu = {
        str(portal.get("portal")): portal
        for portal in ((ostatni_udany or {}).get("wynik") or {}).get("portale", [])
    }
    wlaczone = {adapter.name for adapter in registry.enabled()}

    wiersze: list[dict[str, Any]] = []
    for nazwa, adapter in sorted(registry.ADAPTERS.items()):
        dane = stan.get(nazwa, {})
        wiersze.append(
            {
                "portal": nazwa,
                "adres": adapter.base_url,
                "wlaczony": nazwa in wlaczone,
                "bez_adaptera": False,
                "odstep_s": adapter.delay_seconds,
                "adresow_startowych": sum(1 for _ in adapter.list_urls(settings.region_teryt)),
                "maks_stron_na_adres": _limit_stron(adapter),
                "ofert_w_bazie": dane.get("ofert", 0),
                "aktywnych": dane.get("aktywnych", 0),
                "nowych_24h": dane.get("nowych_24h", 0),
                "nowych_7d": dane.get("nowych_7d", 0),
                "ostatnia_nowa": dane.get("ostatnia_nowa"),
                "ostatnio_widziany": dane.get("ostatnio_widziana"),
                "ostatni_przebieg": z_przebiegu.get(nazwa),
            }
        )

    # Nazwa z PORTALS_ENABLED bez adaptera to co innego niz portal wylaczony:
    # ten ma dzialac, tylko nie ma czym. Cisza po nim musi byc widoczna.
    for nazwa in registry.skipped():
        dane = stan.get(nazwa, {})
        wiersze.append(
            {
                "portal": nazwa,
                "adres": None,
                "wlaczony": True,
                "bez_adaptera": True,
                "odstep_s": None,
                "adresow_startowych": 0,
                "maks_stron_na_adres": 0,
                "ofert_w_bazie": dane.get("ofert", 0),
                "aktywnych": dane.get("aktywnych", 0),
                "nowych_24h": dane.get("nowych_24h", 0),
                "nowych_7d": dane.get("nowych_7d", 0),
                "ostatnia_nowa": dane.get("ostatnia_nowa"),
                "ostatnio_widziany": dane.get("ostatnio_widziana"),
                "ostatni_przebieg": None,
            }
        )
    return wiersze


def _sekcja_zadania(
    teraz: dt.datetime,
    ostatnie_udane: dict[str, dt.datetime],
    w_kolejce: set[str],
) -> list[dict[str, Any]]:
    """Caly harmonogram, bo sam scraping nie decyduje o tym, kiedy oferta jest gotowa.

    Oferta pobrana o 6:00 nie ma jeszcze ani danych publicznych, ani score'u:
    dostaje je dopiero kolejne przebiegi enrich i score. Ta tabela jest po to,
    zeby dalo sie te droge policzyc.
    """
    wynik: list[dict[str, Any]] = []
    for zadanie in scheduler.HARMONOGRAM:
        ostatnie = ostatnie_udane.get(zadanie.kind)
        nastepne = (ostatnie + zadanie.interwal) if ostatnie else None
        wynik.append(
            {
                "kind": zadanie.kind,
                "opis": zadanie.opis,
                "co_ile_godzin": zadanie.interwal.total_seconds() / 3600,
                "payload": zadanie.payload,
                "ostatnie": ostatnie,
                "nastepne": nastepne,
                "za_ile_godzin": (
                    round((nastepne - teraz).total_seconds() / 3600, 1)
                    if nastepne and nastepne > teraz
                    else None
                ),
                "wymagalne": nastepne is None or nastepne <= teraz,
                "w_kolejce": zadanie.kind in w_kolejce,
            }
        )
    return wynik


def _sekcja_zasady() -> dict[str, Any]:
    """Reguly higieny scrapingu. Liczby z konfiguracji, nie z komentarzy."""
    return {
        "odstep_s": settings.scraper_delay_seconds,
        "maks_stron_na_przebieg": settings.scraper_max_pages_per_run,
        "user_agent": settings.scraper_user_agent,
        "region_teryt": settings.region_teryt,
        "wygaszenie_po_dniach": runner.STALE_AFTER_DAYS,
        "backoff_minut": [
            round(queue.opoznienie(proba).total_seconds() / 60)
            for proba in range(1, queue.MAX_PROB)
        ],
        "maks_prob": queue.MAX_PROB,
        "punkty": [
            (
                f"Odstep {settings.scraper_delay_seconds:g} s miedzy zadaniami do tej samej "
                "domeny. Gdy robots.txt portalu deklaruje wlasny Crawl-delay, obowiazuje "
                "wartosc wieksza."
            ),
            (
                "robots.txt jest sprawdzany przed kazdym adresem, niezaleznie od limitow "
                "zaszytych w adapterze. Adres zabroniony nie jest pobierany i widac go "
                "w wyniku przebiegu jako zablokowany."
            ),
            (
                "User-Agent przedstawia narzedzie i podaje adres kontaktowy. Bez tego "
                "przebieg konczy sie bledem, zamiast ruszyc anonimowo."
            ),
            (
                "Strona oferty jest pobierana tylko wtedy, gdy oferta jest nowa albo gdy "
                "zmienila sie jej cena lub powierzchnia. Reszta przebiegu to same strony "
                "wynikow, ktore waza kilkadziesiat razy mniej."
            ),
            (
                "Nieudane zadanie wraca do kolejki z rosnacym opoznieniem "
                f"(do {queue.MAX_PROB} prob), zamiast dokladac ruchu zrodlu, ktore wlasnie "
                "ma klopot."
            ),
        ],
    }
