"""Alerty z zapisanych filtrow. Sekcja 7.4 dokumentu.

JEDNO ZRODLO PRAWDY O TYM, CO FILTR ZNACZY

Ten modul importuje budowanie warunkow z api/routers/listings.py. Wyglada to
na zaleznosc w zla strone, ale alternatywa jest gorsza: drugi zestaw warunkow
SQL, ktory po pierwszej zmianie filtru zaczyna pokazywac co innego niz lista.
Alert, ktory przysyla oferty niepasujace do zapisanego filtru, jest gorszy niz
brak alertu, bo uczy nie ufac systemowi.

PIERWSZY PRZEBIEG NIE WYSYLA NICZEGO

Filtr zapisany na bazie z 700 ofertami pasuje od razu do kilkudziesieciu z nich.
Wyslanie ich wszystkich w jednej serii to nie alert, tylko spam, po ktorym
uzytkownik wylacza powiadomienia. Dlatego pierwszy przebieg oznacza biezace
trafienia jako znane (wpis w alert_log bez wysylki) i alarmuje dopiero o tym,
co pojawi sie pozniej.

CO JUZ POSZLO, NIE IDZIE DRUGI RAZ

alert_log trzyma pare (filtr, oferta). Bez niego restart workera, zmiana progu
albo ponowne uruchomienie zadania powtarzaloby cala historie.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.alerts import telegram
from grunt.api.routers.listings import BAZA_ZAPYTANIA, ListingFilter, _warunki

log = logging.getLogger(__name__)

# Ile alertow najwyzej wysylamy z jednego filtru w jednym przebiegu. Reszta
# poczeka do nastepnego: lepiej powiadamiac wolniej niz zalac telefon.
MAX_NA_PRZEBIEG = 10

SELECT_FILTRY = text(
    """
    SELECT id, name, filter, alert_channel, last_alert_at
    FROM saved_filters
    WHERE alert_enabled
    ORDER BY id
    """
)

OZNACZ_ZNANE = text(
    """
    INSERT INTO alert_log (filter_id, listing_id)
    SELECT :filter_id, :listing_id
    ON CONFLICT (filter_id, listing_id) DO NOTHING
    """
)


def dopasowane(session: Session, filtr: dict[str, Any], filter_id: int) -> list[dict[str, Any]]:
    """Oferty pasujace do filtru, o ktorych jeszcze nie alarmowalismy."""
    model = ListingFilter(**filtr)
    warunki, params = _warunki(model)
    where = " AND ".join(warunki)

    zapytanie = (
        """
        SELECT l.id, l.url, l.title, l.price_grosze, l.area_m2, l.first_seen_at,
               le.plan_status, le.media_koszt_pln,
               s.score_total, s.deal_score, s.coverage, s.red_flags
        """
        + BAZA_ZAPYTANIA.format(warunki=where)
        + """
          AND NOT EXISTS (
              SELECT 1 FROM alert_log a
              WHERE a.filter_id = :filter_id AND a.listing_id = l.id
          )
        ORDER BY s.deal_score DESC NULLS LAST, l.first_seen_at DESC
        LIMIT :limit
        """
    )
    return [
        dict(row)
        for row in session.execute(
            text(zapytanie),
            {**params, "filter_id": filter_id, "limit": MAX_NA_PRZEBIEG},
        )
        .mappings()
        .all()
    ]


def na_alert(row: dict[str, Any], nazwa_filtru: str) -> telegram.Alert:
    return telegram.Alert(
        tytul=f"[{nazwa_filtru}] {row['title'] or 'Dzialka'}",
        url=row["url"],
        cena_zl=row["price_grosze"] // 100 if row["price_grosze"] else None,
        powierzchnia_m2=row["area_m2"],
        score=float(row["score_total"]) if row["score_total"] is not None else None,
        deal_score=float(row["deal_score"]) if row["deal_score"] is not None else None,
        coverage=float(row["coverage"]) if row["coverage"] is not None else None,
        plan_status=row["plan_status"],
        koszt_mediow_pln=row["media_koszt_pln"],
        flagi=tuple(row["red_flags"] or []),
    )


def run(session: Session, *, dry_run: bool | None = None) -> dict[str, Any]:
    """Przebieg po wszystkich wlaczonych filtrach."""
    filtry = session.execute(SELECT_FILTRY).mappings().all()
    podsumowanie: dict[str, Any] = {
        "filtry": len(filtry),
        "wyslane": 0,
        "oznaczone_jako_znane": 0,
        "bledy": [],
        "szczegoly": [],
    }

    for filtr in filtry:
        try:
            trafienia = dopasowane(session, filtr["filter"] or {}, int(filtr["id"]))
        except Exception as exc:
            log.exception("filtr %s nie da sie wykonac", filtr["id"])
            podsumowanie["bledy"].append(f"filtr {filtr['id']}: {exc}")
            continue

        pierwszy_przebieg = filtr["last_alert_at"] is None
        wyslane = 0

        for row in trafienia:
            if not pierwszy_przebieg:
                telegram.send(na_alert(row, filtr["name"]), dry_run=dry_run)
                wyslane += 1
            session.execute(OZNACZ_ZNANE, {"filter_id": filtr["id"], "listing_id": row["id"]})

        session.execute(
            text("UPDATE saved_filters SET last_alert_at = now() WHERE id = :id"),
            {"id": filtr["id"]},
        )

        podsumowanie["wyslane"] += wyslane
        if pierwszy_przebieg:
            podsumowanie["oznaczone_jako_znane"] += len(trafienia)
        podsumowanie["szczegoly"].append(
            {
                "filtr": filtr["name"],
                "trafienia": len(trafienia),
                "wyslane": wyslane,
                "pierwszy_przebieg": pierwszy_przebieg,
            }
        )

    return podsumowanie


def status(session: Session) -> list[dict[str, Any]]:
    """Stan alertow per filtr, do CLI i do sprawdzenia, czy cos nie ucichlo."""
    return [
        dict(row)
        for row in session.execute(
            text(
                """
                SELECT f.id, f.name, f.alert_enabled, f.last_alert_at,
                       count(a.listing_id) AS wyslane,
                       max(a.sent_at) AS ostatni
                FROM saved_filters f
                LEFT JOIN alert_log a ON a.filter_id = f.id
                GROUP BY f.id, f.name, f.alert_enabled, f.last_alert_at
                ORDER BY f.id
                """
            )
        )
        .mappings()
        .all()
    ]
