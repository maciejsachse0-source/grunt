"""Lista ofert z filtrami, sortowaniem i paginacja serwerowa. Sekcja 20 dokumentu.

Endpointy:
    GET /api/listings          lista z filtrami
    GET /api/listings/{id}     pelna karta oferty
    GET /api/listings/{id}/obrys  geometria dopasowanej dzialki dla mapy
    GET /api/listings/geojson  te same filtry, wynik dla mapy (EPSG:4326)
    GET /api/stats             co jest w bazie, dla naglowka aplikacji

Model filtra jest jednym obiektem, bo ten sam ksztalt trafi pozniej do
saved_filters jako filter_jsonb (sekcja 7.2).

DWIE ZASADY WIDOCZNE W ODPOWIEDZI

1. Oferta bez policzonego score'u nadal jest pokazywana, tylko z score = null
   i podanym powodem. Sekcja 5.3.9: brak wyniku to informacja, nie pustka.
2. Domyslne sortowanie to score malejaco, ale oferty bez wyniku ladu ja na koncu,
   zamiast udawac, ze maja zero punktow.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.db import get_db
from grunt.scoring import rodzaj as rodzaj_scoring

router = APIRouter()

SORTOWANIE: dict[str, str] = {
    "score": "s.score_total DESC NULLS LAST, l.first_seen_at DESC",
    "deal": "s.deal_score DESC NULLS LAST, s.score_total DESC NULLS LAST",
    "cena": "l.price_grosze ASC NULLS LAST",
    "cena_m2": "l.price_per_m2 ASC NULLS LAST",
    "powierzchnia": "l.area_m2 DESC NULLS LAST",
    "najnowsze": "l.first_seen_at DESC",
    # Od najtanszej wzgledem wlasnego rynku lokalnego, nie wzgledem calej bazy
    "wzgledem_rynku": "lm.odchylenie ASC NULLS LAST",
}


class ListingFilter(BaseModel):
    """Filtry z sekcji 7.2. Ten sam ksztalt trafi do saved_filters.

    UWAGA NA POLA LISTOWE. FastAPI 0.141 przy modelu wzietym przez Depends()
    gubi po cichu kazde pole listowe: ?portal=otodom i ?status_planistyczny=A
    nie zawezaly wyniku, tylko zwracaly cala baze (7 300 ofert, pomiar
    25.08.2026). Model jako Annotated[..., Query()] radzi sobie z listami,
    ale w tej wersji przestaje dzialac, gdy w sygnaturze stoi jakikolwiek
    inny parametr zapytania, czyli w kazdym z naszych endpointow.

    Dlatego pola listowe stoja w sygnaturach endpointow jeszcze raz, jawnie,
    i sa wstrzykiwane do modelu przez _z_listami(). Brzydkie, ale widoczne:
    filtr, ktory nic nie filtruje, jest gorszy niz jego brak.
    """

    price_min: int | None = Field(default=None, description="Cena w zlotych")
    price_max: int | None = None
    area_min: int | None = None
    area_max: int | None = None
    price_per_m2_max: float | None = None
    portal: list[str] | None = None
    rodzaj: list[str] | None = Field(
        default=None,
        description="mieszkaniowa, uslugowa, przemyslowa albo lesna (scoring/rodzaj.py)",
    )
    teryt: list[str] | None = Field(
        default=None,
        description=(
            "Kod TERYT obszaru: 7 znakow gmina, 4 powiat, 2 wojewodztwo. "
            "Dopasowanie po prefiksie, wiec 2215 zwraca caly powiat wejherowski"
        ),
    )
    status_planistyczny: list[str] | None = Field(
        default=None, description="A, B, C, D, E albo ? (sekcja 5.3.3)"
    )
    w_ouz: bool | None = None
    media_koszt_max: int | None = Field(
        default=None, description="Maksymalny koszt doprowadzenia mediow w zlotych"
    )
    front_min: float | None = None
    spadek_max: float | None = None
    exclude_flood: bool = Field(default=False, description="Odrzuc dzialki w strefach zalewowych")
    score_min: float | None = None
    deal_score_min: float | None = None
    coverage_min: float = 0.0
    tylko_ocenione: bool = Field(default=False, description="Tylko oferty z policzonym score'em")
    odchylenie_max: float | None = Field(
        default=None,
        description="Najwyzsze dopuszczalne odchylenie od mediany rynku, np. -0.1 to 10% ponizej",
    )
    bez_duplikatow: bool = Field(
        default=False,
        description="Z kazdego klastra duplikatow pokaz jedna oferte (sekcja 4.3)",
    )

    # Walidacja wartosci siedzi na modelu, a nie w _warunki, bo ten sam model
    # zapisuje sie w saved_filters i chodzi w alertach. Filtr z literowka ma
    # sie nie dac zapisac, zamiast po cichu nie dopasowywac niczego.
    @field_validator("rodzaj")
    @classmethod
    def _sprawdz_rodzaj(cls, wartosc: list[str] | None) -> list[str] | None:
        nieznane = sorted(set(wartosc or ()) - set(rodzaj_scoring.RODZAJE))
        if nieznane:
            raise ValueError(
                f"nieznany rodzaj: {', '.join(nieznane)}. "
                f"Znane: {', '.join(rodzaj_scoring.RODZAJE)}"
            )
        return wartosc

    @field_validator("teryt")
    @classmethod
    def _sprawdz_teryt(cls, wartosc: list[str] | None) -> list[str] | None:
        zle = [kod for kod in wartosc or () if not kod.isdigit() or len(kod) not in (2, 4, 7)]
        if zle:
            raise ValueError(f"TERYT to 2, 4 albo 7 cyfr, dostalem: {', '.join(zle)}")
        return wartosc


# Pola, ktore FastAPI gubi przy Depends() i ktore endpointy deklaruja jeszcze
# raz. Nazwy musza sie zgadzac z polami ListingFilter, wiec sprawdzamy to przy
# imporcie: literowka byla by cichym wylaczeniem filtru.
POLA_LISTOWE: tuple[str, ...] = ("portal", "rodzaj", "teryt", "status_planistyczny")
assert not set(POLA_LISTOWE) - set(ListingFilter.model_fields)


def _z_listami(filtr: ListingFilter, **listy: list[str] | None) -> ListingFilter:
    """Model uzupelniony o pola listowe odczytane wprost z zapytania.

    Skladamy model od nowa, a nie przez model_copy: copy pomija walidatory,
    wiec ?rodzaj=dzialkowa przeszloby do SQL-a i po cichu nic nie zwrocilo.
    """
    ustawione = {nazwa: wartosc for nazwa, wartosc in listy.items() if wartosc}
    if not ustawione:
        return filtr
    try:
        return ListingFilter.model_validate({**filtr.model_dump(), **ustawione})
    except ValidationError as blad:
        raise HTTPException(
            status_code=422,
            detail="; ".join(szczegol["msg"] for szczegol in blad.errors()),
        ) from blad


def _warunki(f: ListingFilter) -> tuple[list[str], dict[str, Any]]:
    warunki = ["l.is_active"]
    params: dict[str, Any] = {}

    def dodaj(warunek: str, **kwargs: Any) -> None:
        warunki.append(warunek)
        params.update(kwargs)

    if f.price_min is not None:
        dodaj("l.price_grosze >= :price_min", price_min=f.price_min * 100)
    if f.price_max is not None:
        dodaj("l.price_grosze <= :price_max", price_max=f.price_max * 100)
    if f.area_min is not None:
        dodaj("l.area_m2 >= :area_min", area_min=f.area_min)
    if f.area_max is not None:
        dodaj("l.area_m2 <= :area_max", area_max=f.area_max)
    if f.price_per_m2_max is not None:
        dodaj("l.price_per_m2 <= :ppm2", ppm2=f.price_per_m2_max)
    if f.portal:
        dodaj("l.portal::text = ANY(:portale)", portale=list(f.portal))
    if f.rodzaj:
        # Oferta bez rozpoznanego rodzaju NIE przechodzi tego filtru. NULL nie
        # rowna sie niczemu: nie wiemy, czy to dzialka przemyslowa, wiec
        # wpuszczenie jej do wyniku bylo by zgadywaniem (sekcja o brakach danych).
        dodaj("lc.rodzaj = ANY(:rodzaje)", rodzaje=list(f.rodzaj))
    if f.teryt:
        # Kody TERYT sa hierarchiczne, wiec gminy powiatu 2215 to te, ktorych
        # kod zaczyna sie od 2215. Jedno wyrazenie obsluguje wszystkie poziomy.
        dodaj(
            "EXISTS (SELECT 1 FROM unnest(CAST(:teryty AS text[])) obszar"
            " WHERE left(lc.teryt_gmina, length(obszar)) = obszar)",
            teryty=list(f.teryt),
        )
    if f.status_planistyczny:
        dodaj("le.plan_status = ANY(:statusy)", statusy=list(f.status_planistyczny))
    if f.w_ouz is not None:
        dodaj("le.plan_w_ouz IS NOT DISTINCT FROM :w_ouz", w_ouz=f.w_ouz)
    if f.media_koszt_max is not None:
        dodaj("le.media_koszt_pln <= :media_max", media_max=f.media_koszt_max)
    if f.front_min is not None:
        dodaj("le.front_m >= :front_min", front_min=f.front_min)
    if f.spadek_max is not None:
        dodaj("le.spadek_proc <= :spadek_max", spadek_max=f.spadek_max)
    if f.exclude_flood:
        warunki.append(
            "(le.strefy_powodziowe IS NULL OR array_length(le.strefy_powodziowe, 1) IS NULL)"
        )
    if f.score_min is not None:
        dodaj("s.score_total >= :score_min", score_min=f.score_min)
    if f.deal_score_min is not None:
        dodaj("s.deal_score >= :deal_min", deal_min=f.deal_score_min)
    if f.coverage_min:
        dodaj("coalesce(s.coverage, 0) >= :coverage_min", coverage_min=f.coverage_min)
    if f.tylko_ocenione:
        warunki.append("s.score_total IS NOT NULL")
    if f.odchylenie_max is not None:
        # Oferta bez policzonej mediany nie przechodzi tego filtru: nie wiemy,
        # czy jest tania, a NULL nie jest mniejszy od progu.
        dodaj("lm.odchylenie <= :odchylenie_max", odchylenie_max=f.odchylenie_max)
    if f.bez_duplikatow:
        # cluster_id to z definicji najmniejszy identyfikator w klastrze
        # (dedup/cluster.py), wiec reprezentant klastra rozpoznaje sie bez
        # podzapytania: to ta oferta, ktorej id rowna sie numerowi klastra.
        warunki.append("(l.cluster_id IS NULL OR l.cluster_id = l.id)")

    return warunki, params


BAZA_ZAPYTANIA = """
    FROM listings l
    LEFT JOIN listing_enrichment le ON le.listing_id = l.id
    LEFT JOIN scores s ON s.listing_id = l.id
    LEFT JOIN listing_market lm ON lm.listing_id = l.id
    LEFT JOIN teryt_names tn ON tn.teryt = lm.teryt_mediany
    LEFT JOIN listing_category lc ON lc.listing_id = l.id
    -- Nazwa gminy oferty. Osobny join niz tn wyzej: tamten opisuje obszar,
    -- z ktorego wzieta jest mediana, a ten gmine, w ktorej lezy dzialka.
    -- Przy medianie z poziomu powiatu to sa dwa rozne obszary.
    LEFT JOIN teryt_names tg ON tg.teryt = lc.teryt_gmina
    WHERE {warunki}
"""


@router.get("/listings")
def list_listings(
    filtr: ListingFilter = Depends(),
    portal: list[str] | None = Query(default=None, description="Nazwy portali"),
    rodzaj: list[str] | None = Query(
        default=None, description="mieszkaniowa, uslugowa, przemyslowa albo lesna"
    ),
    teryt: list[str] | None = Query(
        default=None, description="Kody TERYT obszarow: 7 gmina, 4 powiat, 2 wojewodztwo"
    ),
    status_planistyczny: list[str] | None = Query(default=None, description="A, B, C, D, E"),
    sort: Literal[
        "score", "deal", "cena", "cena_m2", "powierzchnia", "najnowsze", "wzgledem_rynku"
    ] = "score",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    filtr = _z_listami(
        filtr,
        portal=portal,
        rodzaj=rodzaj,
        teryt=teryt,
        status_planistyczny=status_planistyczny,
    )
    warunki, params = _warunki(filtr)
    where = " AND ".join(warunki)

    total = session.execute(
        text("SELECT count(*) " + BAZA_ZAPYTANIA.format(warunki=where)), params
    ).scalar_one()

    rows = (
        session.execute(
            text(
                """
            SELECT l.id, l.portal::text AS portal, l.url, l.title,
                   l.price_grosze, l.area_m2, l.price_per_m2,
                   l.first_seen_at, l.thumb_url, l.cluster_id,
                   lm.odchylenie, lm.mediana_norm, lm.cena_norm, lm.n AS mediana_n,
                   lm.poziom AS mediana_poziom, lm.segment AS mediana_segment,
                   tn.nazwa AS mediana_obszar,
                   lc.rodzaj, lc.rodzaj_zrodlo, lc.teryt_gmina, lc.gmina_zrodlo,
                   tg.nazwa AS gmina_nazwa, tg.powiat AS powiat_nazwa,
                   ST_Y(ST_Transform(l.geom, 4326)) AS lat,
                   ST_X(ST_Transform(l.geom, 4326)) AS lon,
                   le.plan_status, le.plan_strefa, le.plan_w_ouz,
                   le.media_koszt_pln, le.front_m, le.spadek_proc,
                   le.strefy_powodziowe, le.parcel_uldk_id, le.parcel_match,
                   s.score_total, s.deal_score, s.coverage, s.red_flags
            """
                + BAZA_ZAPYTANIA.format(warunki=where)
                + f" ORDER BY {SORTOWANIE[sort]} LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        )
        .mappings()
        .all()
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "items": [_wiersz_na_oferte(r) for r in rows],
    }


@router.get("/listings/geojson")
def listings_geojson(
    filtr: ListingFilter = Depends(),
    portal: list[str] | None = Query(default=None, description="Nazwy portali"),
    rodzaj: list[str] | None = Query(
        default=None, description="mieszkaniowa, uslugowa, przemyslowa albo lesna"
    ),
    teryt: list[str] | None = Query(
        default=None, description="Kody TERYT obszarow: 7 gmina, 4 powiat, 2 wojewodztwo"
    ),
    status_planistyczny: list[str] | None = Query(default=None, description="A, B, C, D, E"),
    limit: int = Query(default=2000, ge=1, le=5000),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Te same filtry, wynik dla mapy. Zawsze EPSG:4326 (regula z CLAUDE.md)."""
    filtr = _z_listami(
        filtr,
        portal=portal,
        rodzaj=rodzaj,
        teryt=teryt,
        status_planistyczny=status_planistyczny,
    )
    warunki, params = _warunki(filtr)
    warunki.append("l.geom IS NOT NULL")
    where = " AND ".join(warunki)

    rows = (
        session.execute(
            text(
                """
            SELECT l.id, l.title, l.price_grosze, l.area_m2, l.url,
                   ST_Y(ST_Transform(l.geom, 4326)) AS lat,
                   ST_X(ST_Transform(l.geom, 4326)) AS lon,
                   s.score_total, s.deal_score, le.plan_status,
                   lc.rodzaj, tg.nazwa AS gmina_nazwa
            """
                + BAZA_ZAPYTANIA.format(warunki=where)
                + " ORDER BY s.score_total DESC NULLS LAST LIMIT :limit"
            ),
            {**params, "limit": limit},
        )
        .mappings()
        .all()
    )

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": row["id"],
                "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
                "properties": {
                    "tytul": row["title"],
                    "cena_zl": row["price_grosze"] // 100 if row["price_grosze"] else None,
                    "powierzchnia_m2": row["area_m2"],
                    "score": float(row["score_total"]) if row["score_total"] else None,
                    "deal_score": float(row["deal_score"]) if row["deal_score"] else None,
                    "plan_status": row["plan_status"],
                    "rodzaj": row["rodzaj"],
                    "gmina": row["gmina_nazwa"],
                    "url": row["url"],
                },
            }
            for row in rows
        ],
    }


@router.get("/listings/kategorie")
def kategorie(
    poziom: Literal["gmina", "powiat"] = "gmina",
    min_ofert: int = Query(default=1, ge=1),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Co jest do wyboru w filtrze rodzaju i regionu, razem z liczba ofert.

    Lista gmin nie jest slownikiem administracyjnym, tylko tym, co faktycznie
    jest w bazie. Filtr, ktory oferuje gmine bez ani jednej oferty, klamie
    o zasiegu systemu.
    """
    wiersze_rodzajow = (
        session.execute(
            text(
                """
                SELECT lc.rodzaj, count(*) AS oferty
                FROM listing_category lc
                JOIN listings l ON l.id = lc.listing_id AND l.is_active
                GROUP BY lc.rodzaj
                """
            )
        )
        .mappings()
        .all()
    )
    policzone = {r["rodzaj"]: r["oferty"] for r in wiersze_rodzajow}

    # Poziom powiatu to pierwsze cztery znaki kodu gminy, bo TERYT jest
    # hierarchiczny. Nazwa powiatu stoi w teryt_names pod tym samym kodem.
    kod = "lc.teryt_gmina" if poziom == "gmina" else "left(lc.teryt_gmina, 4)"
    obszary = (
        session.execute(
            text(
                f"""
                SELECT {kod} AS teryt, tn.nazwa, tn.powiat, count(*) AS oferty
                FROM listing_category lc
                JOIN listings l ON l.id = lc.listing_id AND l.is_active
                LEFT JOIN teryt_names tn ON tn.teryt = {kod}
                WHERE lc.teryt_gmina IS NOT NULL
                GROUP BY 1, 2, 3
                HAVING count(*) >= :min_ofert
                ORDER BY oferty DESC, teryt
                """  # noqa: S608 - kod pochodzi z Literal, nie z wejscia
            ),
            {"min_ofert": min_ofert},
        )
        .mappings()
        .all()
    )

    return {
        "poziom": poziom,
        # Kolejnosc stala, zeby filtr nie przestawial checkboxow miedzy
        # przebiegami tylko dlatego, ze zmienily sie liczby.
        "rodzaje": [
            {"rodzaj": nazwa, "oferty": policzone.get(nazwa, 0)} for nazwa in rodzaj_scoring.RODZAJE
        ],
        # Osobno, a nie jako pozycja listy: "nie wiemy" nie jest kategoria
        # do zaznaczenia, tylko informacja o stanie danych.
        "bez_rodzaju": policzone.get(None, 0),
        "obszary": [
            {
                "teryt": o["teryt"],
                "nazwa": o["nazwa"],
                "powiat": o["powiat"],
                "oferty": o["oferty"],
            }
            for o in obszary
        ],
        "bez_regionu": session.execute(
            text(
                """
                SELECT count(*) FROM listings l
                LEFT JOIN listing_category lc ON lc.listing_id = l.id
                WHERE l.is_active AND lc.teryt_gmina IS NULL
                """
            )
        ).scalar_one(),
    }


@router.get("/listings/{listing_id}")
def listing_detail(listing_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Pelna karta oferty: wzbogacenie, rozbicie score'u i czerwone flagi."""
    row = (
        session.execute(
            text(
                """
            SELECT l.id, l.portal::text AS portal, l.url, l.title,
                   l.price_grosze, l.area_m2, l.price_per_m2, l.przeznaczenie_raw,
                   l.cluster_id,
                   lm.odchylenie, lm.mediana_norm, lm.cena_norm, lm.n AS mediana_n,
                   lm.poziom AS mediana_poziom, lm.segment AS mediana_segment,
                   tn.nazwa AS mediana_obszar,
                   lc.rodzaj, lc.rodzaj_zrodlo, lc.teryt_gmina, lc.gmina_zrodlo,
                   tg.nazwa AS gmina_nazwa, tg.powiat AS powiat_nazwa,
                   l.media_raw, l.first_seen_at, l.last_seen_at, l.thumb_url,
                   ST_Y(ST_Transform(l.geom, 4326)) AS lat,
                   ST_X(ST_Transform(l.geom, 4326)) AS lon,
                   l.geom_precision, l.raw_jsonb,
                   le.plan_status, le.plan_strefa, le.plan_w_ouz, le.plan_akt,
                   le.strefy_powodziowe, le.wysokosc_npm, le.spadek_proc,
                   le.front_m, le.front_zrodlo, le.smuklosc, le.zwartosc,
                   le.media, le.media_koszt_pln, le.parcel_uldk_id, le.parcel_match,
                   le.parcel_area_m2, le.coverage AS coverage_danych, le.features,
                   le.enriched_at, le.zrodla_bledy,
                   s.score_total, s.deal_score, s.coverage, s.pillar_scores,
                   s.gates, s.red_flags, s.computed_at
            FROM listings l
            LEFT JOIN listing_enrichment le ON le.listing_id = l.id
            LEFT JOIN scores s ON s.listing_id = l.id
            LEFT JOIN listing_market lm ON lm.listing_id = l.id
            LEFT JOIN teryt_names tn ON tn.teryt = lm.teryt_mediany
            LEFT JOIN listing_category lc ON lc.listing_id = l.id
            LEFT JOIN teryt_names tg ON tg.teryt = lc.teryt_gmina
            WHERE l.id = :id
            """
            ),
            {"id": listing_id},
        )
        .mappings()
        .one_or_none()
    )

    if row is None:
        raise HTTPException(status_code=404, detail="nie ma takiej oferty")

    historia = (
        session.execute(
            text(
                """
            SELECT price_grosze / 100 AS cena_zl, observed_at
            FROM price_history WHERE listing_id = :id ORDER BY observed_at
            """
            ),
            {"id": listing_id},
        )
        .mappings()
        .all()
    )

    duplikaty = (
        session.execute(
            text(
                """
            SELECT l.id, l.portal::text AS portal, l.url, l.title,
                   l.price_grosze / 100 AS cena_zl, l.area_m2, l.last_seen_at,
                   d.pewnosc, d.etap, d.powody
            FROM listings l
            -- LEFT JOIN, bo klaster bywa przechodni: A skleilo sie z B, B z C,
            -- ale pary A-C nigdy nie bylo. C nadal jest ta sama dzialka.
            LEFT JOIN listing_duplicates d
              ON (d.listing_a = LEAST(l.id, :id) AND d.listing_b = GREATEST(l.id, :id))
            WHERE l.cluster_id = :cluster AND l.id <> :id AND l.is_active
            ORDER BY l.price_grosze NULLS LAST
            """
            ),
            {"id": listing_id, "cluster": row["cluster_id"]},
        )
        .mappings()
        .all()
        if row["cluster_id"] is not None
        else []
    )

    # Filar 6 dostaje wyjasnienie: sama liczba punktow nie mowi, czy rynek
    # w gminie rosnie, czy stoi.
    dynamika = None
    if row["parcel_uldk_id"]:
        from grunt.enrich import market as market_enrich
        from grunt.sources import rcn_query

        _, gmina, powiat, woj = rcn_query.teryt_from_uldk_id(row["parcel_uldk_id"])
        wynik = market_enrich.dla_terytu(session, gmina=gmina, powiat=powiat, wojewodztwo=woj)
        if wynik is not None:
            dynamika = {
                "cagr": round(wynik.cagr, 4),
                "poziom": wynik.poziom,
                "n_obs": wynik.n_obs,
                "okres": f"{wynik.rok_od}-{wynik.rok_do}",
                "segmenty": {k: round(v, 4) for k, v in sorted(wynik.segmenty.items())},
                "wagi_poziomow": wynik.wagi_poziomow,
            }

    oferta = _wiersz_na_oferte(row)
    oferta["dynamika_rynku"] = dynamika
    # Rozrzut cen miedzy portalami sam w sobie jest sygnalem (sekcja 4.3).
    oferta["duplikaty"] = [
        {
            "id": d["id"],
            "portal": d["portal"],
            "url": d["url"],
            "tytul": d["title"],
            "cena_zl": d["cena_zl"],
            "powierzchnia_m2": d["area_m2"],
            "pewnosc": float(d["pewnosc"]) if d["pewnosc"] is not None else None,
            "etap": d["etap"],
            "powody": d["powody"] or [],
        }
        for d in duplikaty
    ]
    oferta["wzbogacenie"] = {
        "enriched_at": row["enriched_at"],
        "coverage_danych": float(row["coverage_danych"]) if row["coverage_danych"] else None,
        "wysokosc_npm": float(row["wysokosc_npm"]) if row["wysokosc_npm"] else None,
        "smuklosc": float(row["smuklosc"]) if row["smuklosc"] else None,
        "zwartosc": float(row["zwartosc"]) if row["zwartosc"] else None,
        "front_zrodlo": row["front_zrodlo"],
        "plan_akt": row["plan_akt"],
        "media": row["media"],
        "parcel_area_m2": row["parcel_area_m2"],
        "bledy_zrodel": row["zrodla_bledy"],
        "szczegoly": row["features"],
    }
    oferta["filary"] = row["pillar_scores"]
    oferta["gate"] = row["gates"]
    oferta["historia_ceny"] = [
        {"cena_zl": h["cena_zl"], "data": h["observed_at"]} for h in historia
    ]
    oferta["z_ogloszenia"] = {
        "przeznaczenie": row["przeznaczenie_raw"],
        "media": row["media_raw"],
        "geom_precision": row["geom_precision"],
        "dodatkowe": row["raw_jsonb"],
    }
    return oferta


@router.get("/listings/{listing_id}/obrys")
def listing_obrys(listing_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Obrys dopasowanej dzialki i punkt oferty, do przyblizenia mapy.

    Brak dzialki to 200 z obrys = null, nie 404. Oferta bez pewnego dopasowania
    to stan normalny (47 ze 121 wzbogaconych ofert ma pewnosc low), a 404
    zamieniloby go w blad w konsoli przegladarki.

    Punkt oferty jest w odpowiedzi osobno, bo w widoku "zapisane" oferta nie
    musi byc w GeoJSON-ie mapy, ktory idzie z aktualnych filtrow. Bez punktu
    mapa nie wiedzialaby, dokad przyblizyc.
    """
    row = (
        session.execute(
            text(
                """
            SELECT t.listing_id, t.pewnosc, t.uldk_id, t.area_ewid_m2, t.area_z_egib,
                   ST_Y(t.punkt) AS lat, ST_X(t.punkt) AS lon,
                   ST_AsGeoJSON(t.obrys, 6) AS obrys,
                   ST_XMin(t.obrys) AS min_lon, ST_YMin(t.obrys) AS min_lat,
                   ST_XMax(t.obrys) AS max_lon, ST_YMax(t.obrys) AS max_lat
            FROM (
                SELECT l.id AS listing_id,
                       le.parcel_match AS pewnosc,
                       COALESCE(p.uldk_id, le.parcel_uldk_id) AS uldk_id,
                       p.area_ewid_m2,
                       le.parcel_area_m2 AS area_z_egib,
                       ST_Transform(l.geom, 4326) AS punkt,
                       ST_Transform(p.geom, 4326) AS obrys
                FROM listings l
                LEFT JOIN listing_enrichment le ON le.listing_id = l.id
                LEFT JOIN parcels p ON p.id = l.parcel_id
                WHERE l.id = :id
            ) t
            """
            ),
            {"id": listing_id},
        )
        .mappings()
        .one_or_none()
    )

    if row is None:
        raise HTTPException(status_code=404, detail="nie ma takiej oferty")

    punkt = (
        {"lat": float(row["lat"]), "lon": float(row["lon"])}
        if row["lat"] is not None and row["lon"] is not None
        else None
    )

    if row["obrys"] is None:
        return {
            "listing_id": listing_id,
            "punkt": punkt,
            "obrys": None,
            "pewnosc": row["pewnosc"],
            "uldk_id": row["uldk_id"],
        }

    return {
        "listing_id": listing_id,
        "punkt": punkt,
        "pewnosc": row["pewnosc"],
        "uldk_id": row["uldk_id"],
        # Powierzchnia z geometrii ewidencyjnej, nie z ogloszenia: to ona opisuje
        # rysowany obrys.
        "powierzchnia_ewid_m2": row["area_ewid_m2"] or row["area_z_egib"],
        "bbox": [
            float(row["min_lon"]),
            float(row["min_lat"]),
            float(row["max_lon"]),
            float(row["max_lat"]),
        ],
        "obrys": {
            "type": "Feature",
            "id": listing_id,
            "geometry": json.loads(row["obrys"]),
            "properties": {
                "pewnosc": row["pewnosc"],
                "uldk_id": row["uldk_id"],
            },
        },
    }


@router.get("/stats")
def stats(session: Session = Depends(get_db)) -> dict[str, Any]:
    """Liczby do naglowka aplikacji."""
    row = (
        session.execute(
            text(
                """
            SELECT
              (SELECT count(*) FROM listings WHERE is_active) AS oferty,
              (SELECT count(*) FROM listings WHERE is_active AND geom IS NOT NULL) AS ze_wspolrzednymi,
              (SELECT count(*) FROM listing_enrichment) AS wzbogacone,
              (SELECT count(*) FROM scores WHERE score_total IS NOT NULL) AS ocenione,
              (SELECT count(*) FROM rcn_transactions) AS transakcje_rcn,
              (SELECT max(last_seen_at) FROM listings) AS ostatni_scraping
            """
            )
        )
        .mappings()
        .one()
    )

    # Deal score znaczy co innego z kalibracja i bez niej (sekcja 5.6), wiec
    # aplikacja musi umiec powiedziec, ktory wariant wlasnie oglada.
    kalibracja = (
        session.execute(
            text(
                """
            SELECT wartosc, n_obs, zrodlo, computed_at
            FROM calibrations
            WHERE kind = 'spread' AND segment IS NULL
            ORDER BY computed_at DESC LIMIT 1
            """
            )
        )
        .mappings()
        .one_or_none()
    )

    wynik = dict(row)
    wynik["kalibracja"] = (
        {
            "spread": float(kalibracja["wartosc"]),
            "n": kalibracja["n_obs"],
            "zrodlo": kalibracja["zrodlo"],
            "kiedy": kalibracja["computed_at"],
        }
        if kalibracja and kalibracja["wartosc"] is not None
        else None
    )
    return wynik


def _wiersz_na_oferte(row: Any) -> dict[str, Any]:
    # Ta sama funkcja obsluguje wiersz z listy i z karty, a karta ma wiecej
    # kolumn. get() zdejmuje potrzebe sprawdzania, ktory to przypadek.
    flagi = row.get("red_flags")
    return {
        "id": row["id"],
        "portal": row["portal"],
        "url": row["url"],
        "tytul": row["title"],
        "cena_zl": row["price_grosze"] // 100 if row["price_grosze"] else None,
        "powierzchnia_m2": row["area_m2"],
        "cena_m2": float(row["price_per_m2"]) if row["price_per_m2"] else None,
        "lat": row["lat"],
        "lon": row["lon"],
        "thumb_url": row["thumb_url"],
        "pierwszy_raz": row["first_seen_at"],
        "planistyka": {
            "status": row["plan_status"],
            "strefa": row["plan_strefa"],
            "w_ouz": row["plan_w_ouz"],
        },
        # Rodzaj bywa None i tak ma zostac: "nie wiemy" to nie to samo,
        # co "zadna z czterech kategorii" i na pewno nie to samo, co dowolna.
        "rodzaj": row.get("rodzaj"),
        "rodzaj_zrodlo": row.get("rodzaj_zrodlo"),
        # Region oferty. None, gdy nie da sie ustalic gminy: oferta bez
        # wspolrzednych i bez dopasowanej dzialki nie ma jak jej dostac.
        "region": (
            {
                "teryt_gmina": row["teryt_gmina"],
                # Nazwa bywa pusta, dopoki ULDK nie doda gminy do teryt_names.
                # Interfejs pokazuje wtedy sam kod, zamiast zgadywac nazwe.
                "gmina": row.get("gmina_nazwa"),
                "powiat": row.get("powiat_nazwa"),
                "zrodlo": row.get("gmina_zrodlo"),
            }
            if row.get("teryt_gmina")
            else None
        ),
        "media_koszt_pln": row["media_koszt_pln"],
        "front_m": float(row["front_m"]) if row["front_m"] else None,
        "spadek_proc": float(row["spadek_proc"]) if row["spadek_proc"] else None,
        "strefy_powodziowe": row["strefy_powodziowe"] or [],
        "dzialka": {
            "uldk_id": row["parcel_uldk_id"],
            "pewnosc_dopasowania": row["parcel_match"],
        },
        "score": float(row["score_total"]) if row["score_total"] is not None else None,
        "deal_score": float(row["deal_score"]) if row["deal_score"] is not None else None,
        "kompletnosc": float(row["coverage"]) if row["coverage"] is not None else None,
        "czerwone_flagi": flagi or [],
        # NULL oznacza "nie znaleziono duplikatu", a nie "nie sprawdzano"
        "klaster": row.get("cluster_id"),
        # Pozycja wobec rynku lokalnego (sekcja 7.1). None, gdy nie ma z czym
        # porownac: brak mediany to brak informacji, nie zero procent.
        "rynek": (
            {
                "odchylenie": float(row["odchylenie"]),
                "mediana_zl_m2": float(row["mediana_norm"]),
                "cena_zl_m2_norm": float(row["cena_norm"]),
                "n": row["mediana_n"],
                "poziom": row["mediana_poziom"],
                "obszar": row["mediana_obszar"],
                "segment": row["mediana_segment"],
            }
            if row.get("odchylenie") is not None
            else None
        ),
    }
