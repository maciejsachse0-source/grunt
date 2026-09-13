"""Strona odczytowa RCN: dobor transakcji porownywalnych dla wyceny.

Kazda transakcja dostaje etykiete najbardziej szczegolowego poziomu, na ktorym
pasuje do wycenianej dzialki (obreb -> gmina -> powiat -> wojewodztwo). Zbiory sa
rozlaczne: transakcja z tego samego obrebu nie liczy sie drugi raz jako gminna.
Dzieki temu poziom nadrzedny jest prawdziwym prior'em "reszta okolicy", a nie
kopia danych lokalnych.

Filtry twarde, wynikajace z ksztaltu danych RCN (patrz rcn.py):
    udzial = '1/1'                    bez udzialow ulamkowych
    rodzaj_trans = 'wolnyRynek'       bez darowizn i transakcji rodzinnych
    nier_rodzaj = niezabudowana       model gruntowy, nie budynkowy
    cena_m2 w rozsadnych granicach    RCN zawiera ceny 1 zl i powierzchnie 5 mln m2
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.scoring.valuation import Comparable

# Granice zdroworozsadkowe dla ceny za m2 gruntu w Polsce. Wszystko poza nimi to
# blad w rejestrze albo transakcja, ktora nie jest transakcja rynkowa.
CENA_M2_MIN = 1.0
CENA_M2_MAX = 20_000.0

DEFAULT_MONTHS_BACK = 36
DEFAULT_LIMIT_PER_LEVEL = 1500

SQL = text(
    """
    WITH kandydaci AS (
        SELECT
            id_dzialki,
            cena_m2::float8                AS cena_m2,
            pow_gruntu_m2                  AS pow_m2,
            data_trans,
            przeznaczenie,
            sposob_uzyt,
            teryt_gmina,
            CASE
                WHEN CAST(:teryt_obreb AS text)  IS NOT NULL AND teryt_obreb  = CAST(:teryt_obreb AS text)  THEN 'obreb'
                WHEN CAST(:teryt_gmina AS text)  IS NOT NULL AND teryt_gmina  = CAST(:teryt_gmina AS text)  THEN 'gmina'
                WHEN CAST(:teryt_powiat AS text) IS NOT NULL AND teryt_powiat = CAST(:teryt_powiat AS text) THEN 'powiat'
                ELSE 'wojewodztwo'
            END AS poziom,
            row_number() OVER (
                PARTITION BY CASE
                    WHEN CAST(:teryt_obreb AS text)  IS NOT NULL AND teryt_obreb  = CAST(:teryt_obreb AS text)  THEN 'obreb'
                    WHEN CAST(:teryt_gmina AS text)  IS NOT NULL AND teryt_gmina  = CAST(:teryt_gmina AS text)  THEN 'gmina'
                    WHEN CAST(:teryt_powiat AS text) IS NOT NULL AND teryt_powiat = CAST(:teryt_powiat AS text) THEN 'powiat'
                    ELSE 'wojewodztwo'
                END
                ORDER BY data_trans DESC
            ) AS lp
        FROM rcn_transactions
        WHERE cena_grosze IS NOT NULL
          AND pow_gruntu_m2 > 0
          AND udzial = '1/1'
          AND rodzaj_trans = 'wolnyRynek'
          AND nier_rodzaj = 'nieruchomoscGruntowaNiezabudowana'
          AND data_trans >= :since
          -- RCN zawiera rekordy z data w przyszlosci (widziano 2027-07-15).
          -- Indeksacja czasowa takiego rekordu obnizylaby cene, wiec odpadaja.
          AND data_trans <= :as_of
          AND cena_m2 BETWEEN :cena_min AND :cena_max
          AND (CAST(:teryt_woj AS text) IS NULL OR teryt_powiat LIKE CAST(:teryt_woj_like AS text))
          AND (CAST(:sposob_uzyt AS text) IS NULL OR sposob_uzyt = CAST(:sposob_uzyt AS text))
          AND (CAST(:pow_min AS integer) IS NULL OR pow_gruntu_m2 >= CAST(:pow_min AS integer))
          AND (CAST(:pow_max AS integer) IS NULL OR pow_gruntu_m2 <= CAST(:pow_max AS integer))
    )
    SELECT * FROM kandydaci WHERE lp <= :limit_per_level
    """
)


@dataclass(frozen=True, slots=True)
class ComparableQuery:
    teryt_obreb: str | None = None
    teryt_gmina: str | None = None
    teryt_powiat: str | None = None
    teryt_woj: str | None = None
    since: dt.date | None = None
    sposob_uzyt: str | None = None
    area_m2: float | None = None
    area_tolerance: float = 8.0
    limit_per_level: int = DEFAULT_LIMIT_PER_LEVEL


def fetch_comparables(
    session: Session, query: ComparableQuery, *, as_of: dt.date | None = None
) -> list[Comparable]:
    as_of = as_of or dt.date.today()
    since = query.since or (as_of - dt.timedelta(days=30 * DEFAULT_MONTHS_BACK))

    # Odsiew skrajnie roznych powierzchni. Korekta skali radzi sobie z roznica
    # dwukrotna, ale nie z porownywaniem dzialki 800 m2 do 40 ha.
    pow_min = pow_max = None
    if query.area_m2 and query.area_tolerance > 1:
        pow_min = int(query.area_m2 / query.area_tolerance)
        pow_max = int(query.area_m2 * query.area_tolerance)

    params = {
        "teryt_obreb": query.teryt_obreb,
        "teryt_gmina": query.teryt_gmina,
        "teryt_powiat": query.teryt_powiat,
        "teryt_woj": query.teryt_woj,
        "teryt_woj_like": f"{query.teryt_woj}%" if query.teryt_woj else None,
        "since": since,
        "as_of": as_of,
        "sposob_uzyt": query.sposob_uzyt,
        "cena_min": CENA_M2_MIN,
        "cena_max": CENA_M2_MAX,
        "pow_min": pow_min,
        "pow_max": pow_max,
        "limit_per_level": query.limit_per_level,
    }

    rows = session.execute(SQL, params).mappings().all()
    return [
        Comparable(
            price_per_m2=float(row["cena_m2"]),
            area_m2=float(row["pow_m2"]),
            date=row["data_trans"],
            level=row["poziom"],
            id_dzialki=row["id_dzialki"],
            przeznaczenie=row["przeznaczenie"],
            sposob_uzyt=row["sposob_uzyt"],
            teryt_gmina=row["teryt_gmina"],
        )
        for row in rows
    ]


def teryt_from_uldk_id(uldk_id: str) -> tuple[str | None, str | None, str | None, str | None]:
    """'226101_1.0089.433/2' -> (obreb, gmina, powiat, wojewodztwo)."""
    parts = uldk_id.split(".")
    head = parts[0]
    digits = head.replace("_", "")
    gmina = digits[:7] if len(digits) >= 7 else None
    powiat = digits[:4] if len(digits) >= 4 else None
    woj = digits[:2] if len(digits) >= 2 else None
    obreb = f"{head}.{parts[1]}" if len(parts) >= 2 else None
    return obreb, gmina, powiat, woj


def sample_for_evaluation(
    session: Session,
    *,
    limit: int = 50,
    since: dt.date | None = None,
    as_of: dt.date | None = None,
    min_cena_m2: float = CENA_M2_MIN,
    seed: int = 20260821,
) -> list[dict[str, object]]:
    """Losowa, powtarzalna proba transakcji do walidacji modelu (scripts/eval_valuation.py)."""
    session.execute(text("SELECT setseed(:seed)"), {"seed": (seed % 1000) / 1000.0})
    rows = (
        session.execute(
            text(
                """
            SELECT id_dzialki, cena_m2::float8 AS cena_m2, pow_gruntu_m2 AS pow_m2,
                   data_trans, sposob_uzyt, przeznaczenie, teryt_gmina, teryt_obreb,
                   teryt_powiat, iip_id, ST_AsText(geom) AS geom_wkt
            FROM rcn_transactions
            WHERE cena_grosze IS NOT NULL
              AND pow_gruntu_m2 > 0
              AND udzial = '1/1'
              AND rodzaj_trans = 'wolnyRynek'
              AND nier_rodzaj = 'nieruchomoscGruntowaNiezabudowana'
              AND id_dzialki IS NOT NULL
              AND cena_m2 BETWEEN :cena_min AND :cena_max
              AND geom IS NOT NULL
              AND (CAST(:since AS date) IS NULL OR data_trans >= CAST(:since AS date))
              AND data_trans <= :as_of
            ORDER BY random()
            LIMIT :limit
            """
            ),
            {
                "limit": limit,
                "since": since,
                "as_of": as_of or dt.date.today(),
                "cena_min": min_cena_m2,
                "cena_max": CENA_M2_MAX,
            },
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def exclude_transaction(comparables: list[Comparable], id_dzialki: str | None) -> list[Comparable]:
    """Walidacja bez wycieku: model nie moze widziec wycenianej transakcji."""
    if not id_dzialki:
        return comparables
    return [c for c in comparables if c.id_dzialki != id_dzialki]


SQL_KNN = text(
    """
    WITH target AS (
        SELECT ST_Centroid(ST_GeomFromText(CAST(:wkt AS text), 2180)) AS g
    )
    SELECT r.id_dzialki,
           r.cena_m2::float8 AS cena_m2,
           r.pow_gruntu_m2   AS pow_m2,
           r.data_trans,
           r.przeznaczenie,
           r.sposob_uzyt,
           r.teryt_gmina,
           ST_Distance(r.centroid_2180, target.g) AS dist_m,
           CASE
               WHEN CAST(:teryt_obreb AS text) IS NOT NULL
                    AND r.teryt_obreb = CAST(:teryt_obreb AS text) THEN 'obreb'
               WHEN CAST(:teryt_gmina AS text) IS NOT NULL
                    AND r.teryt_gmina = CAST(:teryt_gmina AS text) THEN 'gmina'
               WHEN CAST(:teryt_powiat AS text) IS NOT NULL
                    AND r.teryt_powiat = CAST(:teryt_powiat AS text) THEN 'powiat'
               ELSE 'wojewodztwo'
           END AS poziom
    FROM rcn_transactions r, target
    WHERE r.cena_grosze IS NOT NULL
      AND r.pow_gruntu_m2 > 0
      AND r.udzial = '1/1'
      AND r.rodzaj_trans = 'wolnyRynek'
      AND r.nier_rodzaj = 'nieruchomoscGruntowaNiezabudowana'
      AND r.centroid_2180 IS NOT NULL
      AND r.data_trans >= :since
      AND r.data_trans <= :as_of
      AND r.cena_m2 BETWEEN :cena_min AND :cena_max
      AND (CAST(:pow_min AS integer) IS NULL OR r.pow_gruntu_m2 >= CAST(:pow_min AS integer))
      AND (CAST(:pow_max AS integer) IS NULL OR r.pow_gruntu_m2 <= CAST(:pow_max AS integer))
      AND ST_DWithin(r.centroid_2180, target.g, :max_dist)
    ORDER BY r.centroid_2180 <-> target.g
    LIMIT :limit
    """
)


def fetch_spatial_comparables(
    session: Session,
    geom_wkt: str,
    *,
    teryt_obreb: str | None = None,
    teryt_gmina: str | None = None,
    teryt_powiat: str | None = None,
    as_of: dt.date | None = None,
    since: dt.date | None = None,
    area_m2: float | None = None,
    area_tolerance: float = 8.0,
    max_distance_m: float = 15_000.0,
    limit: int = 600,
    cena_min: float = CENA_M2_MIN,
) -> list[Comparable]:
    """K najblizszych transakcji wzgledem centroidu dzialki (operator <-> na indeksie GiST).

    Odleglosc liczona w EPSG:2180, czyli wprost w metrach, bez transformacji.
    """
    as_of = as_of or dt.date.today()
    since = since or (as_of - dt.timedelta(days=30 * DEFAULT_MONTHS_BACK))

    pow_min = pow_max = None
    if area_m2 and area_tolerance > 1:
        pow_min = int(area_m2 / area_tolerance)
        pow_max = int(area_m2 * area_tolerance)

    rows = (
        session.execute(
            SQL_KNN,
            {
                "wkt": geom_wkt,
                "teryt_obreb": teryt_obreb,
                "teryt_gmina": teryt_gmina,
                "teryt_powiat": teryt_powiat,
                "since": since,
                "as_of": as_of,
                "cena_min": cena_min,
                "cena_max": CENA_M2_MAX,
                "pow_min": pow_min,
                "pow_max": pow_max,
                "max_dist": max_distance_m,
                "limit": limit,
            },
        )
        .mappings()
        .all()
    )

    return [
        Comparable(
            price_per_m2=float(row["cena_m2"]),
            area_m2=float(row["pow_m2"]),
            date=row["data_trans"],
            level=row["poziom"],
            id_dzialki=row["id_dzialki"],
            przeznaczenie=row["przeznaczenie"],
            sposob_uzyt=row["sposob_uzyt"],
            teryt_gmina=row["teryt_gmina"],
            distance_m=float(row["dist_m"]),
        )
        for row in rows
    ]
