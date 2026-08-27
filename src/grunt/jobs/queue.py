"""Kolejka zadan oparta o tabele jobs z sekcji 16.

Dlaczego nie APScheduler ani Celery: caly stan, ktory scheduler musialby
trzymac, i tak jest juz w tabeli jobs (kind, payload, status, attempts,
run_after, locked_at). Przy jednym uzytkowniku i jednym procesie druga
biblioteka do tego samego dolozylaby wlasny magazyn stanu i wlasny format
harmonogramu, ktore trzeba by godzic z tabela. SELECT ... FOR UPDATE SKIP
LOCKED daje dokladnie te gwarancje, ktorych potrzebujemy, i przezywa restart
komputera, bo stan jest w bazie, a nie w pamieci procesu.

Zadanie zawieszone (proces ubity w polowie) wraca do kolejki po
ODBLOKUJ_PO_MINUTACH, bo status "running" bez zywego procesu nikogo nie broni.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

MAX_PROB: Final = 5
BAZOWE_OPOZNIENIE: Final = dt.timedelta(minutes=5)
MAX_OPOZNIENIE: Final = dt.timedelta(hours=6)
ODBLOKUJ_PO_MINUTACH: Final = 60

STATUSY: Final = ("pending", "running", "done", "failed")


def opoznienie(proba: int) -> dt.timedelta:
    """Wykladniczy backoff: 5, 10, 20, 40 minut, dalej sufit 6 godzin.

    Zrodla publiczne padaja na kwadrans i wracaja. Ponawianie co minute
    dokladalo by im ruchu dokladnie wtedy, gdy maja klopot.
    """
    if proba <= 1:
        return BAZOWE_OPOZNIENIE
    return min(BAZOWE_OPOZNIENIE * 2 ** (proba - 1), MAX_OPOZNIENIE)


def enqueue(
    session: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    run_after: dt.datetime | None = None,
) -> int:
    """Dopisanie zadania do kolejki. Zwraca jego identyfikator."""
    return int(
        session.execute(
            text(
                """
                INSERT INTO jobs (kind, payload, status, run_after)
                VALUES (:kind, CAST(:payload AS jsonb), 'pending',
                        COALESCE(:run_after, now()))
                RETURNING id
                """
            ),
            {
                "kind": kind,
                "payload": json.dumps(payload or {}, ensure_ascii=False),
                "run_after": run_after,
            },
        ).scalar_one()
    )


def pobierz(session: Session) -> dict[str, Any] | None:
    """Zajecie jednego zadania gotowego do uruchomienia.

    SKIP LOCKED zamiast zwyklego FOR UPDATE: drugi worker ma wziac nastepne
    zadanie, a nie czekac na pierwsze.
    """
    row = (
        session.execute(
            text(
                """
                UPDATE jobs SET status = 'running', locked_at = now(), attempts = attempts + 1
                WHERE id = (
                    SELECT id FROM jobs
                    WHERE status = 'pending' AND run_after <= now()
                    ORDER BY run_after, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING id, kind, payload, attempts
                """
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def zakoncz(session: Session, job_id: int, wynik: dict[str, Any] | None = None) -> None:
    session.execute(
        text(
            """
            UPDATE jobs
            SET status = 'done', finished_at = now(), locked_at = NULL,
                last_error = NULL, wynik = CAST(:wynik AS jsonb)
            WHERE id = :id
            """
        ),
        {"id": job_id, "wynik": json.dumps(wynik or {}, ensure_ascii=False, default=str)},
    )


def blad(session: Session, job_id: int, wyjatek: BaseException, *, proba: int) -> str:
    """Ponowienie z backoffem albo poddanie sie po MAX_PROB probach."""
    tresc = f"{type(wyjatek).__name__}: {wyjatek}"[:2000]
    if proba >= MAX_PROB:
        session.execute(
            text(
                """
                UPDATE jobs SET status = 'failed', finished_at = now(), locked_at = NULL,
                                last_error = :blad
                WHERE id = :id
                """
            ),
            {"id": job_id, "blad": tresc},
        )
        log.error("zadanie %s poddane po %s probach: %s", job_id, proba, tresc)
        return "failed"

    session.execute(
        text(
            """
            UPDATE jobs SET status = 'pending', locked_at = NULL, last_error = :blad,
                            run_after = now() + CAST(:opoznienie AS interval)
            WHERE id = :id
            """
        ),
        {
            "id": job_id,
            "blad": tresc,
            "opoznienie": f"{int(opoznienie(proba).total_seconds())} seconds",
        },
    )
    log.warning("zadanie %s ponowione za %s: %s", job_id, opoznienie(proba), tresc)
    return "pending"


def odblokuj_zawieszone(session: Session, *, po_minutach: int = ODBLOKUJ_PO_MINUTACH) -> int:
    """Zadania w statusie running po ubitym procesie wracaja do kolejki."""
    return int(
        session.execute(
            text(
                """
                UPDATE jobs SET status = 'pending', locked_at = NULL,
                                last_error = 'proces przerwany, zadanie wznowione'
                WHERE status = 'running'
                  AND locked_at < now() - CAST(:okno AS interval)
                """
            ),
            {"okno": f"{po_minutach} minutes"},
        ).rowcount
    )


def ostatnie_udane(session: Session) -> dict[str, dt.datetime]:
    """Kiedy ostatnio zakonczyl sie sukcesem kazdy rodzaj zadania."""
    rows = session.execute(
        text(
            """
            SELECT kind, max(finished_at) AS ostatnie
            FROM jobs WHERE status = 'done' AND finished_at IS NOT NULL
            GROUP BY kind
            """
        )
    ).all()
    return dict(rows)  # type: ignore[arg-type]


def w_kolejce(session: Session) -> set[str]:
    """Rodzaje zadan, ktore czekaja albo wlasnie sie wykonuja."""
    return {
        kind
        for (kind,) in session.execute(
            text("SELECT DISTINCT kind FROM jobs WHERE status IN ('pending', 'running')")
        ).all()
    }


def lista(session: Session, *, limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in session.execute(
            text(
                """
                SELECT id, kind, status, attempts, run_after, locked_at, finished_at,
                       last_error, wynik
                FROM jobs
                -- CAST, bo bez niego Postgres nie zna typu parametru
                WHERE (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
                ORDER BY COALESCE(finished_at, run_after) DESC, id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit, "status": status},
        )
        .mappings()
        .all()
    ]


def sprzataj(session: Session, *, starsze_niz_dni: int = 30) -> int:
    """Historia zakonczonych zadan po miesiacu nie sluzy juz niczemu."""
    return int(
        session.execute(
            text(
                """
                DELETE FROM jobs
                WHERE status IN ('done', 'failed')
                  AND finished_at < now() - CAST(:okno AS interval)
                """
            ),
            {"okno": f"{starsze_niz_dni} days"},
        ).rowcount
    )
