"""Ceny w regionach: mediany transakcyjne per obszar i segment rynku.

Sekcja 7.1 dokumentu wymaga "percentylu w rynku lokalnym z widoczna liczba
obserwacji". Ten router wystawia to, co dotad system liczyl tylko wewnatrz
modelu wyceny i nigdzie nie pokazywal.

CO ZNACZA TE LICZBY

* mediana_norm: cena za m2 sprowadzona do dzialki 1000 m2 i zindeksowana na
  dzis. TYLKO tej wolno uzywac do porownan miedzy dzialkami o roznej wielkosci
  (sekcja 5.2.1);
* mediana_surowa: mediana cen faktycznie zaplaconych, bez zadnych korekt.
  Do pokazania obok, zeby bylo widac, ile robi normalizacja;
* n: liczba transakcji, na ktorych stoi mediana. Bez tego liczba jest ozdoba;
* segment "*": wszystkie segmenty razem. Tlo dla ofert, ktorych przeznaczenia
  portal nie podal.

Zrodlem jest RCN, czyli ceny TRANSAKCYJNE. Oferty leza wyzej o zmierzony spread
(sekcja 5.6), wiec porownanie oferty z ta mediana pokazuje pozycje wobec cen,
po ktorych ludzie faktycznie kupuja, a nie wobec cen, po ktorych sprzedajacy
chcieliby sprzedac.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.db import get_db

router = APIRouter()

Poziom = Literal["gmina", "powiat", "wojewodztwo"]

SORTOWANIE: dict[str, str] = {
    "mediana": "m.mediana_norm DESC",
    "mediana_rosnaco": "m.mediana_norm ASC",
    "transakcje": "m.n DESC",
    "dynamika": "d.cagr DESC NULLS LAST",
    "nazwa": "COALESCE(t.nazwa, m.teryt) ASC",
}


@router.get("/market")
def ceny_w_regionach(
    poziom: Poziom = Query(default="gmina"),
    segment: str = Query(default="*", description='Segment rynku albo "*" dla wszystkich'),
    min_n: int = Query(default=10, ge=1, description="Minimalna liczba transakcji"),
    sort: str = Query(default="mediana"),
    rodzic: str | None = Query(
        default=None,
        description="TERYT obszaru nadrzednego, np. 2215 zwroci gminy powiatu wejherowskiego",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Tabela cen: mediana, kwartyle, liczba transakcji i dynamika per obszar."""
    if sort not in SORTOWANIE:
        raise HTTPException(status_code=422, detail=f"sort musi byc z: {', '.join(SORTOWANIE)}")
    if rodzic is not None and not rodzic.isdigit():
        raise HTTPException(status_code=422, detail="TERYT to same cyfry")

    rows = (
        session.execute(
            text(
                f"""
                SELECT m.teryt, m.poziom, m.segment, m.n,
                       m.mediana_norm, m.p25_norm, m.p75_norm, m.mediana_surowa,
                       m.okres_od, m.okres_do,
                       t.nazwa, t.powiat,
                       d.cagr, d.n_obs AS dynamika_n,
                       -- TERYT gminy ma 7 znakow, powiatu 4, wojewodztwa 2,
                       -- wiec dopasowanie idzie po prefiksie, inaczej powiat
                       -- pokazywalby zero ofert mimo pelnej bazy.
                       (SELECT count(*) FROM listing_market lm
                         WHERE left(lm.teryt_gmina, length(m.teryt)) = m.teryt) AS oferty
                FROM market_medians m
                LEFT JOIN teryt_names t ON t.teryt = m.teryt
                LEFT JOIN market_dynamics d ON d.teryt = m.teryt AND d.poziom = m.poziom
                WHERE m.poziom = :poziom AND m.segment = :segment AND m.n >= :min_n
                  -- Filtr po obszarze nadrzednym: kody TERYT sa hierarchiczne,
                  -- wiec gminy powiatu 2215 to te, ktorych kod zaczyna sie od 2215.
                  AND (CAST(:rodzic AS text) IS NULL
                       OR left(m.teryt, length(CAST(:rodzic AS text))) = CAST(:rodzic AS text))
                ORDER BY {SORTOWANIE[sort]}
                LIMIT :limit
                """  # noqa: S608 - sort jest wybierany ze slownika, nie z wejscia
            ),
            {
                "poziom": poziom,
                "segment": segment,
                "min_n": min_n,
                "limit": limit,
                "rodzic": rodzic,
            },
        )
        .mappings()
        .all()
    )

    return {
        "poziom": poziom,
        "segment": segment,
        "min_n": min_n,
        "sort": sort,
        "rodzic": rodzic,
        "total": len(rows),
        "items": [
            {
                "teryt": r["teryt"],
                # Nazwa bywa pusta: ULDK nie rozpoznal trzech gmin. Wtedy
                # pokazujemy kod TERYT, zamiast zgadywac nazwe.
                "nazwa": r["nazwa"],
                "powiat": r["powiat"],
                "n": r["n"],
                "mediana": float(r["mediana_norm"]),
                "p25": float(r["p25_norm"]),
                "p75": float(r["p75_norm"]),
                "mediana_surowa": float(r["mediana_surowa"]),
                "dynamika": float(r["cagr"]) if r["cagr"] is not None else None,
                "oferty": r["oferty"],
                "okres": f"{r['okres_od']} - {r['okres_do']}",
            }
            for r in rows
        ],
    }


@router.get("/market/segmenty")
def segmenty(
    poziom: Poziom = Query(default="gmina"),
    min_n: int = Query(default=10, ge=1),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Segmenty, dla ktorych sa mediany, razem z liczba obszarow i transakcji."""
    rows = (
        session.execute(
            text(
                """
                SELECT segment, count(*) AS obszary, sum(n) AS transakcje,
                       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY mediana_norm)::numeric, 0)
                           AS mediana_median
                FROM market_medians
                WHERE poziom = :poziom AND n >= :min_n
                GROUP BY segment
                ORDER BY sum(n) DESC
                """
            ),
            {"poziom": poziom, "min_n": min_n},
        )
        .mappings()
        .all()
    )
    return {"items": [dict(r) for r in rows]}


@router.get("/market/historia")
def historia_cen(
    poziom: Poziom = Query(default="gmina"),
    teryt: str = Query(min_length=2, max_length=7),
    segment: str = Query(default="*"),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Mediana ceny za m2 kwartal po kwartale dla jednego obszaru.

    Ceny sa znormalizowane do dzialki 1000 m2, ale nie indeksowane na dzis:
    tutaj chodzi wlasnie o to, jak zmienialy sie w czasie. Kwartal z mniej niz
    pieciu transakcjami nie dostaje punktu, a kwartal niepelny (RCN publikuje
    z opoznieniem) jest oznaczony i nie wchodzi do trendu.
    """
    if not teryt.isdigit():
        raise HTTPException(status_code=422, detail="TERYT to same cyfry")

    from grunt.enrich import market as market_enrich

    wynik = market_enrich.historia_cen(session, poziom=poziom, teryt=teryt, segment=segment)
    nazwa = session.execute(
        text("SELECT nazwa FROM teryt_names WHERE teryt = :teryt"), {"teryt": teryt}
    ).scalar_one_or_none()
    return {**wynik, "nazwa": nazwa}
