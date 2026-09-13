"""Petla workera: zaplanuj, wez jedno zadanie, wykonaj, zapisz wynik.

Kazdy krok ma wlasna transakcje i to jest cala sztuczka. Gdyby zajecie zadania,
jego wykonanie i zapis wyniku dzialy sie w jednej transakcji, to wyjatek
w srodku cofnalby rowniez zajecie, a nastepny obrot petli wzialby to samo
zepsute zadanie natychmiast, bez backoffu. Osobne transakcje daja tez to, ze
zadanie, ktore zdazylo zapisac czesc danych, tej czesci nie traci.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any

from grunt.db import session_scope
from grunt.jobs import handlers, queue, scheduler

log = logging.getLogger(__name__)

DOMYSLNY_ODSTEP_S = 30.0


def wykonaj_jedno() -> dict[str, Any] | None:
    """Jedno zadanie z kolejki. None, gdy nie ma nic gotowego."""
    with session_scope() as session:
        zadanie = queue.pobierz(session)

    if zadanie is None:
        return None

    start = time.monotonic()
    try:
        with session_scope() as session:
            wynik = handlers.obsluz(session, zadanie["kind"], zadanie["payload"] or {})
        with session_scope() as session:
            queue.zakoncz(session, zadanie["id"], wynik)
        czas = time.monotonic() - start
        log.info("zadanie %s (%s) gotowe w %.1f s", zadanie["id"], zadanie["kind"], czas)
        return {
            "id": zadanie["id"],
            "kind": zadanie["kind"],
            "status": "done",
            "czas_s": round(czas, 1),
            "wynik": wynik,
        }
    except Exception as exc:
        with session_scope() as session:
            status = queue.blad(session, zadanie["id"], exc, proba=int(zadanie["attempts"]))
        return {
            "id": zadanie["id"],
            "kind": zadanie["kind"],
            "status": status,
            "czas_s": round(time.monotonic() - start, 1),
            "blad": f"{type(exc).__name__}: {exc}",
        }


def tick(*, teraz: dt.datetime | None = None) -> dict[str, Any]:
    """Jeden obrot: odzyskanie zawieszonych, harmonogram, jedno zadanie."""
    with session_scope() as session:
        odzyskane = queue.odblokuj_zawieszone(session)
        zaplanowane = scheduler.zaplanuj(session, teraz=teraz)

    wykonane = wykonaj_jedno()
    return {"odzyskane": odzyskane, "zaplanowane": zaplanowane, "wykonane": wykonane}


def pracuj(
    *,
    odstep_s: float = DOMYSLNY_ODSTEP_S,
    max_obrotow: int | None = None,
    progress: Any = None,
) -> dict[str, Any]:
    """Petla workera. Konczy sie na Ctrl+C albo po max_obrotow obrotach."""
    podsumowanie: dict[str, Any] = {"obroty": 0, "wykonane": 0, "bledy": 0, "zaplanowane": 0}
    try:
        while max_obrotow is None or podsumowanie["obroty"] < max_obrotow:
            wynik = tick()
            podsumowanie["obroty"] += 1
            podsumowanie["zaplanowane"] += len(wynik["zaplanowane"])

            wykonane = wynik["wykonane"]
            if wykonane:
                podsumowanie["wykonane"] += 1
                if wykonane["status"] != "done":
                    podsumowanie["bledy"] += 1
                if progress:
                    progress(wykonane)
                # Kolejka moze miec wiecej gotowych zadan, wiec nie spimy.
                continue

            if progress and wynik["zaplanowane"]:
                progress({"zaplanowane": wynik["zaplanowane"]})
            if max_obrotow is not None and podsumowanie["obroty"] >= max_obrotow:
                break
            time.sleep(odstep_s)
    except KeyboardInterrupt:
        podsumowanie["przerwane"] = True
    return podsumowanie
