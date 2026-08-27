"""Policzenie score'u potencjalu dla wzbogaconych ofert i zapis do bazy.

Warstwa laczaca: czyta listing_enrichment, wola czyste funkcje ze scoring/
i zapisuje wynik do tabeli scores. Sam scoring nie dotyka bazy (CLAUDE.md).

Deal score (warstwa C z sekcji 5.4) liczymy tylko wtedy, gdy oferta ma cene
i da sie ja wycenic modelem. Bez wyceny nie ma sensu pytac, czy jest tania.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.scoring import chlonnosc, gates, pillars, segments, valuation
from grunt.sources import rcn_query

SELECT_WZBOGACONE = text(
    """
    SELECT le.listing_id, le.plan_status, le.plan_w_ouz, le.plan_strefa,
           le.strefy_powodziowe,
           le.wysokosc_npm, le.spadek_proc, le.front_m, le.smuklosc, le.zwartosc,
           le.media_koszt_pln, le.parcel_uldk_id, le.parcel_match,
           le.parcel_area_m2, le.features,
           l.price_grosze, l.area_m2, l.przeznaczenie_raw,
           ST_X(l.geom) AS e, ST_Y(l.geom) AS n,
           ST_AsText(l.geom) AS geom_wkt
    FROM listing_enrichment le
    JOIN listings l ON l.id = le.listing_id
    WHERE l.is_active
    ORDER BY le.enriched_at DESC
    LIMIT :limit
    """
)

UPSERT_SCORE = text(
    """
    INSERT INTO scores (
        listing_id, score_total, pillar_scores, gates, coverage, deal_score,
        red_flags, model_version, computed_at
    ) VALUES (
        :listing_id, :score_total, CAST(:pillar_scores AS jsonb), CAST(:gates AS jsonb),
        :coverage, :deal_score, CAST(:red_flags AS jsonb), :model_version, now()
    )
    ON CONFLICT (listing_id) DO UPDATE SET
        score_total = EXCLUDED.score_total,
        pillar_scores = EXCLUDED.pillar_scores,
        gates = EXCLUDED.gates,
        coverage = EXCLUDED.coverage,
        deal_score = EXCLUDED.deal_score,
        red_flags = EXCLUDED.red_flags,
        model_version = EXCLUDED.model_version,
        computed_at = now()
    """
)


def _czerwone_flagi(features: dict[str, Any], row: Any) -> tuple[str, ...]:
    flagi: list[str] = []

    ksztalt = (features or {}).get("ksztalt") or {}
    flagi.extend(ksztalt.get("uwagi") or [])

    if row["plan_status"] == "D":
        flagi.append(
            "dzialka poza Obszarem Uzupelnienia Zabudowy: po reformie planistycznej "
            "praktycznie brak sciezki do zabudowy"
        )
    if row["strefy_powodziowe"]:
        flagi.append(f"strefa zagrozenia powodziowego: {', '.join(row['strefy_powodziowe'])}")
    if row["media_koszt_pln"] and row["media_koszt_pln"] > 60_000:
        flagi.append(
            f"wysoki koszt doprowadzenia mediow: ok. {row['media_koszt_pln'] // 1000} tys. zl"
        )
    if row["parcel_match"] in ("low", "none"):
        flagi.append(
            "nie udalo sie jednoznacznie wskazac dzialki ewidencyjnej, "
            "cechy geometryczne moga dotyczyc sasiedniej parceli"
        )
    return tuple(flagi)


def chlonnosc_oferty(row: Any) -> chlonnosc.Chlonnosc | None:
    """Chlonnosc z wskaznikow zabudowy zapisanych przy wzbogacaniu.

    Wskazniki siedza w features->planistyka->wskazniki, bo przychodza w tym
    samym GetFeatureInfo, ktorym pytamy o symbol strefy. Powierzchnia idzie
    z dzialki ewidencyjnej, a dopiero gdy jej nie ma - z ogloszenia:
    powierzchnia deklarowana przez sprzedajacego bywa powierzchnia dzialki-matki.
    """
    features = row["features"] or {}
    wskazniki = ((features.get("planistyka") or {}).get("wskazniki")) or {}
    if not any(v is not None for v in wskazniki.values()):
        return None

    powierzchnia = row["parcel_area_m2"] or row["area_m2"]
    if not powierzchnia:
        return None

    return chlonnosc.oblicz(
        float(powierzchnia),
        maks_intensywnosc=wskazniki.get("maks_intensywnosc"),
        maks_udzial_zabudowy_proc=wskazniki.get("maks_udzial_zabudowy_proc"),
        maks_wysokosc_m=wskazniki.get("maks_wysokosc_m"),
        min_biologicznie_czynne_proc=wskazniki.get("min_biologicznie_czynne_proc"),
        strefa_symbol=row["plan_strefa"],
    )


def score_row(
    row: Any,
    *,
    profil: pillars.Profil = "detaliczny",
    dynamika_cen: float | None = None,
) -> pillars.Score:
    """Score jednej oferty z jej wzbogacenia. Bez sieci i bez bazy.

    dynamika_cen to srednioroczna zmiana cen w gminie dzialki (filar 6).
    Przychodzi z zewnatrz, bo jest cecha obszaru i liczy sie ja raz na tydzien
    dla calego wojewodztwa, a nie przy kazdym scoringu oferty.
    """
    features = row["features"] or {}

    filary = [
        pillars.pillar_chlonnosc(chlonnosc_oferty(row)),
        pillars.pillar_planistyka(row["plan_status"], row["plan_w_ouz"]),
        pillars.pillar_lokalizacja(),  # izochrony dopiero przed nami
        pillars.pillar_infrastruktura(row["media_koszt_pln"], None),
        pillars.pillar_fizyka(
            float(row["front_m"]) if row["front_m"] else None,
            float(row["spadek_proc"]) if row["spadek_proc"] else None,
            float(row["zwartosc"]) if row["zwartosc"] else None,
        ),
        pillars.pillar_ryzyka(
            row["strefy_powodziowe"] or [],
            sprawdzone=bool((features.get("powodz") or {}).get("kompletne")),
        ),
        pillars.pillar_rynek(dynamika_cen_3y=dynamika_cen),
    ]

    gate = gates.evaluate(
        plan_status=row["plan_status"],
        strefy_powodziowe=row["strefy_powodziowe"] or [],
    )

    return pillars.combine(
        filary, gate, profil=profil, czerwone_flagi=_czerwone_flagi(features, row)
    )


def run(
    session: Session,
    *,
    limit: int = 500,
    profil: pillars.Profil = "detaliczny",
    z_wycena: bool = True,
    spread: float | None = None,
    progress: Any = None,
) -> dict[str, Any]:
    # Import lokalny, zeby kalibracja mogla korzystac z wycen_oferte bez cyklu.
    from grunt.enrich import calibrate

    rows = session.execute(SELECT_WZBOGACONE, {"limit": limit}).mappings().all()
    as_of = dt.date.today()
    spread = calibrate.aktualny_spread(session) if spread is None else spread

    statystyki = {
        "policzone": 0,
        "z_wynikiem": 0,
        "bez_danych": 0,
        "z_deal_score": 0,
        "spread": spread,
    }

    for row in rows:
        wynik = score_row(row, profil=profil, dynamika_cen=_dynamika_cen(session, row))
        deal = None

        if z_wycena and row["price_grosze"] and row["area_m2"]:
            deal = _deal_score(session, row, as_of=as_of, spread=spread)

        session.execute(
            UPSERT_SCORE,
            {
                "listing_id": row["listing_id"],
                "score_total": wynik.punkty,
                "pillar_scores": json.dumps(
                    {f.klucz: f.punkty for f in wynik.filary}, ensure_ascii=False
                ),
                "gates": json.dumps(wynik.gate.to_dict(), ensure_ascii=False),
                "coverage": wynik.coverage,
                "deal_score": deal,
                "red_flags": json.dumps(list(wynik.czerwone_flagi), ensure_ascii=False),
                "model_version": "score-v1",
            },
        )

        statystyki["policzone"] += 1
        if wynik.wiarygodny:
            statystyki["z_wynikiem"] += 1
        else:
            statystyki["bez_danych"] += 1
        if deal is not None:
            statystyki["z_deal_score"] += 1
        if progress:
            progress(
                f"oferta {row['listing_id']}: score "
                f"{wynik.punkty if wynik.wiarygodny else 'brak'} "
                f"(kompletnosc {wynik.coverage:.0%})"
            )

    session.commit()
    return statystyki


def _dynamika_cen(session: Session, row: Any) -> float | None:
    """Filar 6 dla oferty: dynamika cen w gminie jej dzialki.

    Bez numeru dzialki nie ma TERYT-u, a bez TERYT-u nie ma jak wskazac gminy.
    Wtedy filar zostaje niedostepny i wchodzi do renormalizacji wag.
    """
    from grunt.enrich import market

    uldk_id = row["parcel_uldk_id"]
    if not uldk_id:
        return None
    _, gmina, powiat, woj = rcn_query.teryt_from_uldk_id(uldk_id)
    dynamika = market.dla_terytu(session, gmina=gmina, powiat=powiat, wojewodztwo=woj)
    return dynamika.cagr if dynamika else None


def wycen_oferte(session: Session, row: Any, *, as_of: dt.date) -> Any | None:
    """Wycena Modelem 2 dla wiersza oferty. None, gdy nie ma z czego wycenic.

    Publiczna, bo tego samego przebiegu potrzebuje kalibracja spreadu
    (enrich/calibrate.py): jesli policzylaby wycene inaczej niz scoring,
    kalibrowalaby cos innego, niz potem koryguje.
    """
    uldk_id = row["parcel_uldk_id"]
    if not uldk_id:
        return None

    obreb, gmina, powiat, woj = rcn_query.teryt_from_uldk_id(uldk_id)
    target = segments.classify(row["przeznaczenie_raw"], None)

    comps = rcn_query.fetch_spatial_comparables(
        session,
        row["geom_wkt"],
        teryt_obreb=obreb,
        teryt_gmina=gmina,
        teryt_powiat=powiat,
        as_of=as_of,
        area_m2=float(row["area_m2"]),
        cena_min=5.0,
    )
    if not comps:
        return None

    wybrane, uzyte = segments.select_by_segment(
        comps, target, segment_of=lambda c: c.segment, level_of=lambda c: c.level
    )
    try:
        wycena = valuation.valuate_se_knn(
            float(row["area_m2"]),
            wybrane,
            as_of=as_of,
            segments_used=uzyte,
            target_segment=target,
        )
    except valuation.ValuationError:
        return None
    return wycena if wycena.reliable else None


def _deal_score(session: Session, row: Any, *, as_of: dt.date, spread: float = 0.0) -> float | None:
    """Warstwa C: (wycena skorygowana o spread - cena) / sigma. Sekcje 5.4 i 5.6."""
    wycena = wycen_oferte(session, row, as_of=as_of)
    if wycena is None:
        return None
    try:
        return round(valuation.deal_score(int(row["price_grosze"]), wycena, spread=spread), 3)
    except valuation.ValuationError:
        return None
