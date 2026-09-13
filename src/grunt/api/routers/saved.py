"""Ulubione, notatki, oceny i zapisane filtry. Sekcje 7.3 i 7.4 dokumentu.

JEDEN UZYTKOWNIK, ZERO LOGOWANIA

CLAUDE.md mowi wprost: ten projekt ma jednego uzytkownika. Zamiast sesji, tokenow
i ekranu logowania jest jeden wiersz w tabeli users i funkcja uzytkownik_id().
Kolumna user_id zostaje w schemacie, wiec dolozenie drugiej osoby to dopisanie
uwierzytelniania, a nie migracja danych.

DLACZEGO ZAPISUJEMY OFERTE, A NIE DZIALKE

Pewne dopasowanie do dzialki ewidencyjnej mamy dla czesci ofert (migracja 007
i sekcja "Czego nauczyly nas dane", punkt 5). Zapisac do obserwowanych chce sie
to, co sie wlasnie oglada, czyli ogloszenie. Stad saved_listings.

FILTR ZAPISANY TO TEN SAM KSZTALT, CO FILTR W LISCIE

saved_filters.filter trzyma dokladnie to, co przyjmuje GET /api/listings.
Dzieki temu alert nie ma wlasnej logiki dopasowania: sklada ListingFilter
z zapisanego JSON-a i uzywa tego samego SQL-a, co lista. Filtr, ktory pokazuje
co innego niz alert, byłby gorszy niz brak alertu.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.api.routers.listings import ListingFilter
from grunt.db import get_db

router = APIRouter()

DOMYSLNY_UZYTKOWNIK = "lokalny@grunt"

STATUSY = ("nowa", "obserwuje", "kontakt", "odrzucona", "kupiona")
Status = Literal["nowa", "obserwuje", "kontakt", "odrzucona", "kupiona"]


def uzytkownik_id(session: Session) -> int:
    """Identyfikator jedynego uzytkownika. Tworzy wiersz, gdy go nie ma."""
    istniejacy = session.execute(
        text("SELECT id FROM users WHERE email = :email"), {"email": DOMYSLNY_UZYTKOWNIK}
    ).scalar_one_or_none()
    if istniejacy is not None:
        return int(istniejacy)

    nowy = session.execute(
        text("INSERT INTO users (email) VALUES (:email) RETURNING id"),
        {"email": DOMYSLNY_UZYTKOWNIK},
    ).scalar_one()
    session.commit()
    return int(nowy)


class ZapiszOferte(BaseModel):
    status: Status = "obserwuje"
    note: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = None


class ZapiszFiltr(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    filter: dict[str, Any]
    alert_enabled: bool = False
    alert_channel: str | None = Field(default="telegram")


class ZmienFiltr(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    filter: dict[str, Any] | None = None
    alert_enabled: bool | None = None


# --------------------------------------------------------------- ulubione


SELECT_ZAPISANE = """
    SELECT s.listing_id AS id, s.status, s.note, s.tags, s.created_at, s.updated_at,
           l.portal::text AS portal, l.url, l.title, l.price_grosze, l.area_m2,
           l.price_per_m2, l.is_active, l.cluster_id,
           ST_Y(ST_Transform(l.geom, 4326)) AS lat,
           ST_X(ST_Transform(l.geom, 4326)) AS lon,
           le.plan_status, le.media_koszt_pln, le.strefy_powodziowe,
           sc.score_total, sc.deal_score, sc.coverage, sc.red_flags,
           lc.rodzaj, lc.rodzaj_zrodlo, lc.teryt_gmina, lc.gmina_zrodlo,
           tg.nazwa AS gmina_nazwa, tg.powiat AS powiat_nazwa,
           f.verdict
    FROM saved_listings s
    JOIN listings l ON l.id = s.listing_id
    LEFT JOIN listing_enrichment le ON le.listing_id = l.id
    LEFT JOIN scores sc ON sc.listing_id = l.id
    LEFT JOIN listing_category lc ON lc.listing_id = l.id
    LEFT JOIN teryt_names tg ON tg.teryt = lc.teryt_gmina
    LEFT JOIN LATERAL (
        SELECT verdict FROM feedback
        WHERE user_id = s.user_id AND listing_id = s.listing_id
        ORDER BY created_at DESC LIMIT 1
    ) f ON true
    WHERE s.user_id = :user_id
"""


def _wiersz(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row["status"],
        "note": row["note"],
        "tags": row["tags"] or [],
        "zapisano": row["created_at"],
        "zmieniono": row["updated_at"],
        "portal": row["portal"],
        "url": row["url"],
        "tytul": row["title"],
        "cena_zl": row["price_grosze"] // 100 if row["price_grosze"] else None,
        "powierzchnia_m2": row["area_m2"],
        "cena_m2": float(row["price_per_m2"]) if row["price_per_m2"] else None,
        "lat": row["lat"],
        "lon": row["lon"],
        # Oferta zapisana zostaje w ulubionych po wygasnieciu ogloszenia,
        # ale musi byc widoczne, ze zniknela z portalu.
        "aktywna": row["is_active"],
        "klaster": row["cluster_id"],
        "planistyka": {"status": row["plan_status"]},
        "rodzaj": row["rodzaj"],
        "rodzaj_zrodlo": row["rodzaj_zrodlo"],
        "region": (
            {
                "teryt_gmina": row["teryt_gmina"],
                "gmina": row["gmina_nazwa"],
                "powiat": row["powiat_nazwa"],
                "zrodlo": row["gmina_zrodlo"],
            }
            if row["teryt_gmina"]
            else None
        ),
        "media_koszt_pln": row["media_koszt_pln"],
        "strefy_powodziowe": row["strefy_powodziowe"] or [],
        "score": float(row["score_total"]) if row["score_total"] is not None else None,
        "deal_score": float(row["deal_score"]) if row["deal_score"] is not None else None,
        "kompletnosc": float(row["coverage"]) if row["coverage"] is not None else None,
        "czerwone_flagi": row["red_flags"] or [],
        "ocena": row["verdict"],
    }


@router.get("/saved")
def lista_zapisanych(
    status: Status | None = Query(default=None),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Obserwowane oferty razem z ocena i notatka."""
    user_id = uzytkownik_id(session)
    warunek = " AND s.status = :status" if status else ""
    rows = (
        session.execute(
            text(SELECT_ZAPISANE + warunek + " ORDER BY s.updated_at DESC"),
            {"user_id": user_id, "status": status},
        )
        .mappings()
        .all()
    )
    return {"total": len(rows), "items": [_wiersz(r) for r in rows]}


@router.put("/saved/{listing_id}")
def zapisz(
    listing_id: int, dane: ZapiszOferte, session: Session = Depends(get_db)
) -> dict[str, Any]:
    """Zapisanie oferty albo zmiana statusu i notatki."""
    user_id = uzytkownik_id(session)
    istnieje = session.execute(
        text("SELECT 1 FROM listings WHERE id = :id"), {"id": listing_id}
    ).scalar_one_or_none()
    if istnieje is None:
        raise HTTPException(status_code=404, detail="nie ma takiej oferty")

    session.execute(
        text(
            """
            INSERT INTO saved_listings (user_id, listing_id, status, note, tags)
            VALUES (:user_id, :listing_id, :status, :note, :tags)
            ON CONFLICT (user_id, listing_id) DO UPDATE SET
                status = EXCLUDED.status,
                note = EXCLUDED.note,
                tags = EXCLUDED.tags,
                updated_at = now()
            """
        ),
        {
            "user_id": user_id,
            "listing_id": listing_id,
            "status": dane.status,
            "note": dane.note,
            "tags": dane.tags,
        },
    )
    session.commit()
    return {"zapisano": True, "listing_id": listing_id, "status": dane.status}


@router.delete("/saved/{listing_id}")
def usun(listing_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    user_id = uzytkownik_id(session)
    usuniete = session.execute(
        text("DELETE FROM saved_listings WHERE user_id = :u AND listing_id = :l"),
        {"u": user_id, "l": listing_id},
    ).rowcount
    session.commit()
    if not usuniete:
        raise HTTPException(status_code=404, detail="ta oferta nie byla zapisana")
    return {"usunieto": True, "listing_id": listing_id}


class OcenOferte(BaseModel):
    verdict: Literal[-1, 0, 1]


@router.post("/saved/{listing_id}/ocena")
def ocen(listing_id: int, dane: OcenOferte, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Kciuk w gore albo w dol. Material na proxy do kalibracji z sekcji 5.6.

    Historia ocen zostaje: klucz zawiera created_at, wiec zmiana zdania nie
    kasuje poprzedniej oceny, tylko dokłada nowa. Interfejs pokazuje ostatnia.
    """
    user_id = uzytkownik_id(session)
    session.execute(
        text(
            """
            INSERT INTO feedback (user_id, listing_id, verdict)
            VALUES (:user_id, :listing_id, :verdict)
            """
        ),
        {"user_id": user_id, "listing_id": listing_id, "verdict": dane.verdict},
    )
    session.commit()
    return {"zapisano": True, "listing_id": listing_id, "verdict": dane.verdict}


# ---------------------------------------------------------- zapisane filtry


@router.get("/filters")
def lista_filtrow(session: Session = Depends(get_db)) -> dict[str, Any]:
    user_id = uzytkownik_id(session)
    rows = (
        session.execute(
            text(
                """
                SELECT f.id, f.name, f.filter, f.alert_enabled, f.alert_channel,
                       f.last_alert_at,
                       (SELECT count(*) FROM alert_log a WHERE a.filter_id = f.id) AS wyslane
                FROM saved_filters f
                WHERE f.user_id = :user_id
                ORDER BY f.id
                """
            ),
            {"user_id": user_id},
        )
        .mappings()
        .all()
    )
    return {"total": len(rows), "items": [dict(r) for r in rows]}


def sprawdz_filtr(filtr: dict[str, Any]) -> None:
    """Filtr musi dac sie wykonac przez GET /api/listings, inaczej alert klamie.

    Pydantic domyslnie ignoruje nadmiarowe pola, wiec literowka w nazwie pola
    przeszlaby bez sladu i alert szukalby czegos innego, niz zapisal uzytkownik.
    Stad jawne porownanie kluczy.
    """
    nieznane = set(filtr) - set(ListingFilter.model_fields)
    if nieznane:
        raise HTTPException(
            status_code=422,
            detail=f"nieznane pola filtru: {', '.join(sorted(nieznane))}",
        )
    try:
        ListingFilter(**filtr)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"zly filtr: {exc}") from exc


@router.post("/filters")
def dodaj_filtr(dane: ZapiszFiltr, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Zapisanie filtru. Ksztalt jest walidowany modelem listy, nie przyjmujemy smieci."""
    sprawdz_filtr(dane.filter)

    user_id = uzytkownik_id(session)
    import json

    nowy = session.execute(
        text(
            """
            INSERT INTO saved_filters (user_id, name, filter, alert_enabled, alert_channel)
            VALUES (:user_id, :name, CAST(:filter AS jsonb), :alert_enabled, :alert_channel)
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "name": dane.name,
            "filter": json.dumps(dane.filter, ensure_ascii=False),
            "alert_enabled": dane.alert_enabled,
            "alert_channel": dane.alert_channel,
        },
    ).scalar_one()
    session.commit()
    return {"id": int(nowy), "name": dane.name, "alert_enabled": dane.alert_enabled}


@router.patch("/filters/{filter_id}")
def zmien_filtr(
    filter_id: int, dane: ZmienFiltr, session: Session = Depends(get_db)
) -> dict[str, Any]:
    import json

    user_id = uzytkownik_id(session)
    if dane.filter is not None:
        sprawdz_filtr(dane.filter)

    zmienione = session.execute(
        text(
            """
            UPDATE saved_filters SET
                name = COALESCE(:name, name),
                filter = COALESCE(CAST(:filter AS jsonb), filter),
                alert_enabled = COALESCE(:alert_enabled, alert_enabled)
            WHERE id = :id AND user_id = :user_id
            """
        ),
        {
            "id": filter_id,
            "user_id": user_id,
            "name": dane.name,
            "filter": json.dumps(dane.filter, ensure_ascii=False) if dane.filter else None,
            "alert_enabled": dane.alert_enabled,
        },
    ).rowcount
    session.commit()
    if not zmienione:
        raise HTTPException(status_code=404, detail="nie ma takiego filtru")
    return {"zmieniono": True, "id": filter_id}


@router.delete("/filters/{filter_id}")
def usun_filtr(filter_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    user_id = uzytkownik_id(session)
    usuniete = session.execute(
        text("DELETE FROM saved_filters WHERE id = :id AND user_id = :user_id"),
        {"id": filter_id, "user_id": user_id},
    ).rowcount
    session.commit()
    if not usuniete:
        raise HTTPException(status_code=404, detail="nie ma takiego filtru")
    return {"usunieto": True, "id": filter_id}
