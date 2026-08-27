"""Co robi kazdy rodzaj zadania. Jedyne miejsce wiazace kolejke z pipeline'ami.

Importy sa wewnatrz funkcji celowo: worker startuje bez wciagania curl-cffi,
shapely i reszty, a zepsuty modul jednego zadania nie blokuje pozostalych.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Final

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

Handler = Callable[[Session, dict[str, Any]], dict[str, Any]]


def scrape(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from grunt.ingest import runner
    from grunt.portals import registry

    adaptery = registry.enabled()
    if not adaptery:
        return {"pominiete": "brak wlaczonych portali w PORTALS_ENABLED"}

    statystyki = runner.run_all(
        session,
        adaptery,
        max_pages=payload.get("max_pages"),
        max_details=payload.get("max_details"),
    )
    wynik: dict[str, Any] = {"portale": [s.as_dict() for s in statystyki]}

    # Nazwa w PORTALS_ENABLED bez adaptera jest po cichu pomijana. Skrypt reczny
    # wypisuje to na ekran, ale w jobs.wynik tego nie bylo widac, wiec "zadanie
    # done" wygladalo jak przebieg po wszystkich portalach z konfiguracji.
    # Cisza po portalu ma byc widoczna tam, gdzie sie czyta historie przebiegow.
    if pominiete := registry.skipped():
        wynik["bez_adaptera"] = pominiete
    return wynik


def enrich(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from grunt.enrich import pipeline

    return dict(
        pipeline.run(
            session,
            limit=int(payload.get("limit", 20)),
            max_wiek_dni=int(payload.get("max_wiek_dni", 30)),
        )
    )


def score(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from grunt.enrich import score_listings

    return dict(
        score_listings.run(
            session,
            limit=int(payload.get("limit", 500)),
            profil=payload.get("profil", "detaliczny"),
        )
    )


def dedup(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from grunt.dedup import pipeline

    wynik = pipeline.run(session)
    # Same klastry sa juz w bazie, w wyniku zadania zostawiamy tylko liczby.
    return {klucz: wartosc for klucz, wartosc in wynik.items() if klucz != "klastry_szczegoly"}


def kategorie(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from grunt.enrich import kategoria

    return kategoria.run(session)


def rynek(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from grunt.enrich import market

    return market.run(session, okres_lat=int(payload.get("okres_lat", 4)))


def kalibracja(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from grunt.enrich import calibrate

    wynik = calibrate.run(
        session,
        limit=int(payload.get("limit", 500)),
        profil=payload.get("profil", "detaliczny"),
    )
    # beta1 i spread sa juz w tabeli calibrations, w historii zadania zostaja liczby
    return {
        "spread": (wynik["spread_oferty"] or {}).get("(globalny)"),
        "spread_pary": wynik["spread_pary"],
        "beta1": wynik["beta1"],
        "dyskryminacja": wynik["dyskryminacja"],
    }


def alerty(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from grunt.alerts import saved_filters

    wynik = saved_filters.run(session, dry_run=payload.get("dry_run"))
    return wynik


def watchdog(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from grunt.alerts import watchdog as watchdog_modul

    wynik = watchdog_modul.powiadom(session)
    # Tresc alertu poszla na Telegram, w historii zadania wystarcza liczby.
    return {klucz: wartosc for klucz, wartosc in wynik.items() if klucz != "tresc"}


def sprzatanie(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from grunt.jobs import queue

    usuniete = queue.sprzataj(session, starsze_niz_dni=int(payload.get("starsze_niz_dni", 30)))
    return {"usuniete_zadania": usuniete}


HANDLERY: Final[dict[str, Handler]] = {
    "scrape": scrape,
    "enrich": enrich,
    "score": score,
    "dedup": dedup,
    "kategorie": kategorie,
    "rynek": rynek,
    "alerty": alerty,
    "kalibracja": kalibracja,
    "watchdog": watchdog,
    "sprzatanie": sprzatanie,
}


class NieznaneZadanie(KeyError):
    pass


def obsluz(session: Session, kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    handler = HANDLERY.get(kind)
    if handler is None:
        raise NieznaneZadanie(f"nieznany rodzaj zadania: {kind}. Znane: {', '.join(HANDLERY)}")
    return handler(session, payload or {})
