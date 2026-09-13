"""Dynamika rynku per obszar: warstwa czytajaca baze. Filar 6, sekcja 5.3.6.

Rachunek jest w scoring/market.py i nie dotyka bazy. Tutaj jest zbieranie
transakcji, normalizacja ceny do dzialki 1000 m2 i zapis do market_dynamics.

Normalizacja uzywa elastycznosci `b1` skalibrowanej na wlasnych danych
(tabela calibrations, kind='beta1', osobno dla kazdego segmentu). Gdy segment
nie ma jeszcze pomiaru, wchodzi wartosc startowa 0,85 z literatury. Bez
normalizacji rok, w ktorym sprzedano wiecej malych dzialek, wygladalby na rok
drozszy, a to jest dokladnie ten blad, przed ktorym ostrzega sekcja 5.2.1.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.scoring import market, normalize_area, segments

log = logging.getLogger(__name__)

# Cztery lata kalendarzowe daja trzy pelne przejscia rok do roku.
DOMYSLNY_OKRES_LAT = 4

# Rodzaje transakcji, ktore sa obrotem rynkowym. Sprzedaz z bonifikata (387
# rekordow) i na cel publiczny (361) to ceny ustalone administracyjnie, wiec
# w medianie rynku nie maja czego szukac. Zabudowanych nieruchomosci nie
# filtrujemy, bo RCN w tej bazie ma wylacznie
# nieruchomoscGruntowaNiezabudowana: sprawdzone na wszystkich 137 298 rekordach.
FILTR_RYNKOWY = (
    "AND (rodzaj_trans IS NULL OR rodzaj_trans IN ('wolnyRynek', 'sprzedazPrzetargowa'))"
)

SELECT_TRANSAKCJE = text(
    """
    SELECT teryt_gmina, teryt_powiat,
           EXTRACT(YEAR FROM data_trans)::int AS rok,
           przeznaczenie, pow_gruntu_m2, cena_m2
    FROM rcn_transactions
    WHERE cena_grosze IS NOT NULL
      AND pow_gruntu_m2 > 0
      AND cena_m2 >= 5.0
      AND data_trans BETWEEN :od AND current_date
      AND (udzial IS NULL OR udzial IN ('1', '1/1'))
      AND teryt_gmina IS NOT NULL
    """
    + FILTR_RYNKOWY
)

UPSERT = text(
    """
    INSERT INTO market_dynamics (poziom, teryt, cagr, n_obs, rok_od, rok_do, segmenty, computed_at)
    VALUES (:poziom, :teryt, :cagr, :n_obs, :rok_od, :rok_do, CAST(:segmenty AS jsonb), now())
    ON CONFLICT (poziom, teryt) DO UPDATE SET
        cagr = EXCLUDED.cagr,
        n_obs = EXCLUDED.n_obs,
        rok_od = EXCLUDED.rok_od,
        rok_do = EXCLUDED.rok_do,
        segmenty = EXCLUDED.segmenty,
        computed_at = now()
    """
)


def krzywe_z_kalibracji(session: Session) -> dict[str, normalize_area.LogPriceCurve]:
    """Elastycznosc per segment z ostatniej kalibracji. Pusto = wartosc startowa."""
    rows = session.execute(
        text(
            """
            SELECT DISTINCT ON (segment) segment, wartosc
            FROM calibrations
            WHERE kind = 'beta1' AND segment IS NOT NULL AND wartosc IS NOT NULL
            ORDER BY segment, computed_at DESC
            """
        )
    ).all()
    return {segment: normalize_area.LogPriceCurve.constant(float(beta)) for segment, beta in rows}


def _mediany(
    session: Session, *, od_roku: int
) -> tuple[dict[tuple[str, str], dict[str, dict[int, tuple[float, int]]]], int]:
    """Mediana znormalizowanej ceny za m2 per (poziom, teryt, segment, rok)."""
    krzywe = krzywe_z_kalibracji(session)
    domyslna = normalize_area.LogPriceCurve.constant()

    zebrane: dict[tuple[str, str], dict[str, dict[int, list[float]]]] = {}
    wiersze = 0

    for row in session.execute(SELECT_TRANSAKCJE, {"od": dt.date(od_roku, 1, 1)}).mappings():
        segment = segments.classify(row["przeznaczenie"], None)
        try:
            znormalizowana = normalize_area.normalize_price_per_m2(
                float(row["cena_m2"]),
                float(row["pow_gruntu_m2"]),
                curve=krzywe.get(segment, domyslna),
            )
        except normalize_area.NormalizationError:
            continue

        wiersze += 1
        gmina = row["teryt_gmina"]
        klucze = [
            ("gmina", gmina),
            ("powiat", row["teryt_powiat"] or gmina[:4]),
            ("wojewodztwo", gmina[:2]),
        ]
        for poziom, teryt in klucze:
            if not teryt:
                continue
            (
                zebrane.setdefault((poziom, teryt), {})
                .setdefault(segment, {})
                .setdefault(int(row["rok"]), [])
                .append(znormalizowana)
            )

    mediany: dict[tuple[str, str], dict[str, dict[int, tuple[float, int]]]] = {}
    for klucz, per_segment in zebrane.items():
        mediany[klucz] = {
            segment: {rok: (float(np.median(ceny)), len(ceny)) for rok, ceny in lata.items()}
            for segment, lata in per_segment.items()
        }
    return mediany, wiersze


def run(session: Session, *, okres_lat: int = DOMYSLNY_OKRES_LAT) -> dict[str, Any]:
    """Przeliczenie dynamiki dla wszystkich obszarow i zapis do market_dynamics."""
    od_roku = dt.date.today().year - okres_lat + 1
    # Nazwa lokalna celowo inna niz funkcja mediany(): przy "mediany" zmienna
    # przeslanialaby funkcje wolana nizej i przebieg wywracal sie na
    # "'dict' object is not callable".
    zebrane_mediany, wiersze = _mediany(session, od_roku=od_roku)

    # now() jest stale w transakcji, wiec wiersze zapisane nizej maja dokladnie
    # ten znacznik, a te z poprzedniego przebiegu sa starsze i pojda do kasacji.
    # Bez tego zmiana progu zostawialaby w tabeli obszary policzone na starych
    # zasadach, a status pokazywalby ich sume.
    znacznik = session.execute(text("SELECT now()")).scalar_one()

    zapisane = {"gmina": 0, "powiat": 0, "wojewodztwo": 0}
    pominiete = 0
    for (poziom, teryt), dane in sorted(zebrane_mediany.items()):
        dynamika = market.dynamika_z_median(dane, poziom=poziom)
        if dynamika is None:
            pominiete += 1
            continue
        session.execute(
            UPSERT,
            {
                "poziom": poziom,
                "teryt": teryt,
                "cagr": round(dynamika.cagr, 4),
                "n_obs": dynamika.n_obs,
                "rok_od": dynamika.rok_od,
                "rok_do": dynamika.rok_do,
                "segmenty": json.dumps(dynamika.segmenty, ensure_ascii=False),
            },
        )
        zapisane[poziom] += 1

    nieaktualne = session.execute(
        text("DELETE FROM market_dynamics WHERE computed_at < :znacznik"),
        {"znacznik": znacznik},
    ).rowcount

    log.info("dynamika rynku: %s obszarow, %s transakcji", sum(zapisane.values()), wiersze)
    podsumowanie: dict[str, Any] = {
        "transakcje": wiersze,
        "obszary": zapisane,
        "bez_dynamiki": pominiete,
        "usuniete_nieaktualne": nieaktualne,
        "od_roku": od_roku,
    }

    # Kolejnosc ma znaczenie: mediany indeksuje sie dynamika policzona wyzej,
    # a dopasowanie ofert korzysta z median. Nazwy sa niezalezne, ale ida tu,
    # bo to jedyne miejsce, ktore wie, dla ktorych obszarow sa potrzebne.
    podsumowanie["mediany"] = mediany(session)
    podsumowanie["nazwy"] = nazwy_teryt(session)
    podsumowanie["oferty"] = dopasuj_oferty(session)
    return podsumowanie


def dla_terytu(
    session: Session,
    *,
    gmina: str | None,
    powiat: str | None,
    wojewodztwo: str | None,
    k: int = market.K_SHRINKAGE,
) -> market.Dynamika | None:
    """Dynamika dla dzialki: gmina sciagnieta do powiatu i wojewodztwa."""
    kandydaci: dict[str, market.Dynamika | None] = {}
    for poziom, teryt in (
        ("gmina", gmina),
        ("powiat", powiat),
        ("wojewodztwo", wojewodztwo),
    ):
        if not teryt:
            continue
        row = (
            session.execute(
                text(
                    """
                    SELECT cagr, n_obs, rok_od, rok_do, segmenty
                    FROM market_dynamics WHERE poziom = :poziom AND teryt = :teryt
                    """
                ),
                {"poziom": poziom, "teryt": teryt},
            )
            .mappings()
            .one_or_none()
        )
        kandydaci[poziom] = (
            market.Dynamika(
                cagr=float(row["cagr"]),
                poziom=poziom,
                n_obs=int(row["n_obs"]),
                rok_od=int(row["rok_od"]),
                rok_do=int(row["rok_do"]),
                segmenty={k: float(v) for k, v in (row["segmenty"] or {}).items()},
            )
            if row
            else None
        )
    return market.shrinkage(kandydaci, k=k)


def status(session: Session) -> dict[str, Any]:
    """Ile obszarow ma policzona dynamike i jak wygladaja skrajne wartosci."""
    row = (
        session.execute(
            text(
                """
                SELECT count(*) FILTER (WHERE poziom = 'gmina') AS gminy,
                       count(*) FILTER (WHERE poziom = 'powiat') AS powiaty,
                       count(*) FILTER (WHERE poziom = 'wojewodztwo') AS wojewodztwa,
                       round(avg(cagr) FILTER (WHERE poziom = 'gmina'), 4) AS srednia_gmin,
                       max(computed_at) AS ostatnie
                FROM market_dynamics
                """
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


# ------------------------------------------------- mediany rynku lokalnego

OKNO_MEDIANY_MIESIECY = 24

SELECT_DO_MEDIAN = text(
    """
    SELECT teryt_gmina, teryt_powiat,
           przeznaczenie, pow_gruntu_m2, cena_m2, data_trans
    FROM rcn_transactions
    WHERE cena_grosze IS NOT NULL
      AND pow_gruntu_m2 > 0
      AND cena_m2 >= 5.0
      AND data_trans BETWEEN :od AND current_date
      AND (udzial IS NULL OR udzial IN ('1', '1/1'))
      AND teryt_gmina IS NOT NULL
    """
    + FILTR_RYNKOWY
)

UPSERT_MEDIANA = text(
    """
    INSERT INTO market_medians (
        poziom, teryt, segment, n, mediana_norm, p25_norm, p75_norm,
        mediana_surowa, okres_od, okres_do, computed_at
    ) VALUES (
        :poziom, :teryt, :segment, :n, :mediana_norm, :p25_norm, :p75_norm,
        :mediana_surowa, :okres_od, current_date, now()
    )
    ON CONFLICT (poziom, teryt, segment) DO UPDATE SET
        n = EXCLUDED.n,
        mediana_norm = EXCLUDED.mediana_norm,
        p25_norm = EXCLUDED.p25_norm,
        p75_norm = EXCLUDED.p75_norm,
        mediana_surowa = EXCLUDED.mediana_surowa,
        okres_od = EXCLUDED.okres_od,
        okres_do = EXCLUDED.okres_do,
        computed_at = now()
    """
)

# Ponizej tylu transakcji nie zapisujemy nawet tla: mediana z trzech transakcji
# to nie jest informacja o rynku, tylko trzy liczby.
MIN_OBS_ZAPISU = 5

# Klucz mediany liczonej po wszystkich segmentach razem.
SEGMENT_ZBIORCZY = "*"

# Znormalizowana cena za m2 poza tym zakresem to blad danych, nie okazja.
# Przyklad z bazy: "Gospodarstwo rolne, 150 m2 za 4,29 mln zl" - w polu
# powierzchni siedzi budynek, nie grunt, wiec wychodzi 14 512 zl/m2 i oferta
# udaje 161-krotnosc mediany. Takich wierszy nie porownujemy wcale.
MIN_CENA_M2 = 1.0
MAX_CENA_M2 = 5000.0


def _cagr_gmin(session: Session) -> dict[str, float]:
    """Dynamika per gmina do indeksacji cen. Pusto, gdy zadania rynek jeszcze nie bylo."""
    return {
        teryt: float(cagr)
        for teryt, cagr in session.execute(
            text("SELECT teryt, cagr FROM market_dynamics WHERE poziom = 'gmina'")
        ).all()
    }


def mediany(session: Session, *, okno_miesiecy: int = OKNO_MEDIANY_MIESIECY) -> dict[str, Any]:
    """Mediana ceny znormalizowanej per (poziom, teryt, segment), zindeksowana na dzis."""
    dzis = dt.date.today()
    od = dzis - dt.timedelta(days=int(okno_miesiecy * 30.44))
    krzywe = krzywe_z_kalibracji(session)
    domyslna = normalize_area.LogPriceCurve.constant()
    cagr = _cagr_gmin(session)

    # klucz -> (znormalizowane zindeksowane, surowe)
    zebrane: dict[tuple[str, str, str], tuple[list[float], list[float]]] = {}
    wiersze = 0

    for row in session.execute(SELECT_DO_MEDIAN, {"od": od}).mappings():
        segment = segments.classify(row["przeznaczenie"], None)
        try:
            znorm = normalize_area.normalize_price_per_m2(
                float(row["cena_m2"]),
                float(row["pow_gruntu_m2"]),
                curve=krzywe.get(segment, domyslna),
            )
        except normalize_area.NormalizationError:
            continue

        gmina = row["teryt_gmina"]
        lata = (dzis - row["data_trans"]).days / 365.25
        zindeksowana = market.indeksuj_do_dzis(znorm, cagr.get(gmina), lata)
        wiersze += 1

        for poziom, teryt in (
            ("gmina", gmina),
            ("powiat", row["teryt_powiat"] or gmina[:4]),
            ("wojewodztwo", gmina[:2]),
        ):
            if not teryt:
                continue
            # Segment wlasciwy oraz kubel zbiorczy "*": ten drugi jest jedynym
            # uczciwym tlem dla oferty, ktorej przeznaczenia portal nie podal.
            # Porownywanie jej do kubla "nieokreslona" z RCN bylo bledem: tam
            # siedza glownie tanie grunty rolne, wiec kazda oferta wychodzila
            # kilkadziesiat procent powyzej rynku.
            for klucz_segmentu in (segment, SEGMENT_ZBIORCZY):
                kubel = zebrane.setdefault((poziom, teryt, klucz_segmentu), ([], []))
                kubel[0].append(zindeksowana)
                kubel[1].append(float(row["cena_m2"]))

    znacznik = session.execute(text("SELECT now()")).scalar_one()
    zapisane = 0
    # Nazwa inna niz "segment" wyzej: tam byl segment RCN, tu kluczem bywa
    # takze "*", czyli kubel zbiorczy, ktory segmentem nie jest.
    for (poziom, teryt, klucz), (znormalizowane, surowe) in sorted(zebrane.items()):
        if len(znormalizowane) < MIN_OBS_ZAPISU:
            continue
        tablica = np.array(znormalizowane)
        session.execute(
            UPSERT_MEDIANA,
            {
                "poziom": poziom,
                "teryt": teryt,
                "segment": klucz,
                "n": len(znormalizowane),
                "mediana_norm": round(float(np.median(tablica)), 2),
                "p25_norm": round(float(np.percentile(tablica, 25)), 2),
                "p75_norm": round(float(np.percentile(tablica, 75)), 2),
                "mediana_surowa": round(float(np.median(surowe)), 2),
                "okres_od": od,
            },
        )
        zapisane += 1

    nieaktualne = session.execute(
        text("DELETE FROM market_medians WHERE computed_at < :znacznik"),
        {"znacznik": znacznik},
    ).rowcount

    return {
        "transakcje": wiersze,
        "mediany": zapisane,
        "usuniete_nieaktualne": nieaktualne,
        "okres_od": od.isoformat(),
    }


# ------------------------------------------------------------ nazwy TERYT

# Nazwy wojewodztw sa stale i nie warto o nie pytac uslugi. Reszta nazw
# pochodzi z ULDK, ktory przy zapytaniu o dzialke zwraca gmine i powiat.
WOJEWODZTWA: dict[str, str] = {
    "02": "dolnoslaskie",
    "04": "kujawsko-pomorskie",
    "06": "lubelskie",
    "08": "lubuskie",
    "10": "lodzkie",
    "12": "malopolskie",
    "14": "mazowieckie",
    "16": "opolskie",
    "18": "podkarpackie",
    "20": "podlaskie",
    "22": "pomorskie",
    "24": "slaskie",
    "26": "swietokrzyskie",
    "28": "warminsko-mazurskie",
    "30": "wielkopolskie",
    "32": "zachodniopomorskie",
}

UPSERT_NAZWA = text(
    """
    INSERT INTO teryt_names (teryt, poziom, nazwa, powiat, zrodlo)
    VALUES (:teryt, :poziom, :nazwa, :powiat, :zrodlo)
    ON CONFLICT (teryt) DO UPDATE SET
        nazwa = EXCLUDED.nazwa,
        powiat = EXCLUDED.powiat,
        zrodlo = EXCLUDED.zrodlo,
        fetched_at = now()
    """
)


# Ostatnia cyfra siedmioznakowego kodu TERYT to rodzaj gminy. Dla gminy
# miejsko-wiejskiej ULDK zwraca te sama nazwe dla miasta (4) i dla obszaru
# wiejskiego (5), wiec w wyborze gminy pod wykresem staly obok siebie dwie
# "Kobylnice" z roznymi medianami i nie bylo jak ich rozroznic. Rodzaj bierzemy
# z kodu, bo tam jest zapisany wprost, a nie zgadujemy go z nazwy.
RODZAJ_GMINY: dict[str, str] = {"4": "miasto", "5": "obszar wiejski"}


def nazwa_gminy(nazwa: str, teryt: str) -> str:
    """Nazwa gminy uzupelniona o rodzaj, gdy sam kod TERYT go rozroznia.

    Nazwy, ktore ULDK juz doprecyzowal (np. "Rumia (miasto)"), zostaja bez zmian.
    """
    if len(teryt) != 7 or "(" in nazwa:
        return nazwa
    rodzaj = RODZAJ_GMINY.get(teryt[-1])
    return f"{nazwa} ({rodzaj})" if rodzaj else nazwa


# Nazwy zapisane przed wprowadzeniem rodzaju gminy trzeba poprawic w miejscu:
# nazwy_teryt uzupelnia tylko braki, wiec sam nigdy by do nich nie wrocil.
UZUPELNIJ_RODZAJ = text(
    """
    UPDATE teryt_names
       SET nazwa = nazwa || ' (' || CASE right(teryt, 1)
                                      WHEN '4' THEN 'miasto'
                                      ELSE 'obszar wiejski'
                                    END || ')'
     WHERE poziom = 'gmina'
       AND length(teryt) = 7
       AND right(teryt, 1) IN ('4', '5')
       AND position('(' in nazwa) = 0
    """
)


def nazwy_teryt(session: Session, *, limit: int | None = None) -> dict[str, Any]:
    """Uzupelnienie nazw gmin i powiatow: dla obszarow z mediana i dla gmin ofert.

    Jedno zapytanie do ULDK na gmine, wynik trafia do cache'u ULDK i do
    teryt_names, wiec kolejne przebiegi nic nie pobieraja. Gmina, ktorej ULDK
    nie rozpozna, zostaje bez nazwy i interfejs pokaze sam kod TERYT: to
    uczciwsze niz zgadywanie nazwy z numeru.
    """
    from grunt.sources import uldk

    braki = (
        session.execute(
            text(
                """
            -- Dwa zrodla gmin, bo to sa dwa rozne zbiory. Gminy z mediana
            -- opisuja rynek (tabela cen), gminy ofert opisuja to, gdzie
            -- faktycznie cos jest na sprzedaz. Filtr regionu na liscie ofert
            -- pokazywalby sam kod TERYT dla kazdej gminy spoza pierwszego
            -- zbioru, a kod TERYT nie jest nazwa, tylko numerem.
            SELECT DISTINCT g.teryt
            FROM (
                SELECT m.teryt FROM market_medians m WHERE m.poziom = 'gmina'
                UNION
                SELECT lc.teryt_gmina
                FROM listing_category lc
                JOIN listings l ON l.id = lc.listing_id AND l.is_active
                WHERE lc.teryt_gmina IS NOT NULL
            ) g
            LEFT JOIN teryt_names n ON n.teryt = g.teryt
            WHERE n.teryt IS NULL
            ORDER BY g.teryt
            """
            )
        )
        .scalars()
        .all()
    )

    if limit is not None:
        braki = braki[:limit]

    klient = uldk.UldkClient(session)
    pobrane = 0
    nieznane: list[str] = []

    for teryt in braki:
        id_dzialki = session.execute(
            text(
                """
                SELECT id_dzialki FROM rcn_transactions
                WHERE teryt_gmina = :teryt AND id_dzialki IS NOT NULL
                LIMIT 1
                """
            ),
            {"teryt": teryt},
        ).scalar_one_or_none()
        if not id_dzialki:
            nieznane.append(teryt)
            continue

        try:
            dzialka = klient.by_id(id_dzialki)
        except Exception as exc:  # jedna gmina bez nazwy nie moze zatrzymac reszty
            log.warning("ULDK nie odpowiedzial dla %s: %s", teryt, exc)
            nieznane.append(teryt)
            continue

        if dzialka is None or not dzialka.gmina:
            nieznane.append(teryt)
            continue

        session.execute(
            UPSERT_NAZWA,
            {
                "teryt": teryt,
                "poziom": "gmina",
                "nazwa": nazwa_gminy(dzialka.gmina, teryt),
                "powiat": dzialka.powiat,
                "zrodlo": "uldk",
            },
        )
        if dzialka.powiat:
            session.execute(
                UPSERT_NAZWA,
                {
                    "teryt": teryt[:4],
                    "poziom": "powiat",
                    "nazwa": dzialka.powiat,
                    "powiat": None,
                    "zrodlo": "uldk",
                },
            )
        pobrane += 1

    for kod, nazwa in WOJEWODZTWA.items():
        session.execute(
            UPSERT_NAZWA,
            {
                "teryt": kod,
                "poziom": "wojewodztwo",
                "nazwa": nazwa,
                "powiat": None,
                "zrodlo": "stala",
            },
        )

    poprawione = session.execute(UZUPELNIJ_RODZAJ).rowcount

    return {
        "do_pobrania": len(braki),
        "pobrane": pobrane,
        "bez_nazwy": len(nieznane),
        "doprecyzowane": poprawione,
    }


# ---------------------------------------------- przypisanie oferty do rynku

# Gmina oferty: najpierw z pewnie dopasowanej dzialki ewidencyjnej, a gdy jej
# nie ma, z najblizszej transakcji RCN. To nie jest zgadywanie: operator <->
# na indeksie GiST po centroidzie zwraca faktycznie najblizszy punkt, a gminy
# maja kilkanascie kilometrow srednicy, wiec najblizsza transakcja niemal
# zawsze lezy w tej samej gminie co oferta.
SELECT_OFERTY_DO_RYNKU = text(
    """
    SELECT l.id, l.price_grosze, l.area_m2, l.przeznaczenie_raw, l.title,
           COALESCE(
               CASE WHEN le.parcel_uldk_id ~ '^[0-9]{6}_[0-9]'
                    THEN substr(
                        replace(split_part(le.parcel_uldk_id, '.', 1), '_', ''), 1, 7)
               END,
               najblizsza.teryt_gmina
           ) AS teryt_gmina
    FROM listings l
    LEFT JOIN listing_enrichment le ON le.listing_id = l.id
    LEFT JOIN LATERAL (
        SELECT r.teryt_gmina
        FROM rcn_transactions r
        WHERE r.centroid_2180 IS NOT NULL AND r.teryt_gmina IS NOT NULL
        ORDER BY r.centroid_2180 <-> l.geom
        LIMIT 1
    ) najblizsza ON true
    WHERE l.is_active
      AND l.geom IS NOT NULL
      AND l.price_grosze IS NOT NULL
      AND l.area_m2 > 0
    """
)

UPSERT_LISTING_MARKET = text(
    """
    INSERT INTO listing_market (
        listing_id, teryt_gmina, segment, poziom, teryt_mediany,
        mediana_norm, n, cena_norm, odchylenie, computed_at
    ) VALUES (
        :listing_id, :teryt_gmina, :segment, :poziom, :teryt_mediany,
        :mediana_norm, :n, :cena_norm, :odchylenie, now()
    )
    ON CONFLICT (listing_id) DO UPDATE SET
        teryt_gmina = EXCLUDED.teryt_gmina,
        segment = EXCLUDED.segment,
        poziom = EXCLUDED.poziom,
        teryt_mediany = EXCLUDED.teryt_mediany,
        mediana_norm = EXCLUDED.mediana_norm,
        n = EXCLUDED.n,
        cena_norm = EXCLUDED.cena_norm,
        odchylenie = EXCLUDED.odchylenie,
        computed_at = now()
    """
)


def _mediany_z_bazy(session: Session) -> dict[tuple[str, str, str], market.Mediana]:
    return {
        (row["poziom"], row["teryt"], row["segment"]): market.Mediana(
            poziom=row["poziom"],
            teryt=row["teryt"],
            segment=row["segment"],
            mediana_norm=float(row["mediana_norm"]),
            p25_norm=float(row["p25_norm"]),
            p75_norm=float(row["p75_norm"]),
            n=int(row["n"]),
        )
        for row in session.execute(
            text(
                """
                SELECT poziom, teryt, segment, mediana_norm, p25_norm, p75_norm, n
                FROM market_medians
                """
            )
        ).mappings()
    }


def dopasuj_oferty(session: Session) -> dict[str, Any]:
    """Dla kazdej aktywnej oferty: mediana jej rynku i odchylenie od niej."""
    slownik = _mediany_z_bazy(session)
    krzywe = krzywe_z_kalibracji(session)
    domyslna = normalize_area.LogPriceCurve.constant()

    znacznik = session.execute(text("SELECT now()")).scalar_one()
    statystyki: dict[str, Any] = {
        "oferty": 0,
        "z_mediana": 0,
        "bez_mediany": 0,
        "odstajace": 0,
        "poziomy": {},
    }

    for row in session.execute(SELECT_OFERTY_DO_RYNKU).mappings():
        statystyki["oferty"] += 1
        gmina = row["teryt_gmina"]
        if not gmina:
            statystyki["bez_mediany"] += 1
            continue

        # Segment czytamy z tresci ogloszenia, nie ze slownika RCN: portale
        # nie mowia jezykiem RCN. Gdy nie da sie rozpoznac, porownujemy
        # do calego rynku gminy i tak to opisujemy w interfejsie.
        rozpoznany = segments.z_ogloszenia(row["przeznaczenie_raw"], row["title"])
        # Typ jest szerszy niz Segment, bo "*" nie jest segmentem RCN, tylko
        # kluczem kubla zbiorczego.
        segment: str = rozpoznany or SEGMENT_ZBIORCZY
        kandydatki = {
            "gmina": slownik.get(("gmina", gmina, segment)),
            "powiat": slownik.get(("powiat", gmina[:4], segment)),
            "wojewodztwo": slownik.get(("wojewodztwo", gmina[:2], segment)),
        }
        mediana = market.wybierz_mediane(kandydatki)
        if mediana is None:
            statystyki["bez_mediany"] += 1
            continue

        area = float(row["area_m2"])
        cena_m2 = float(row["price_grosze"]) / 100.0 / area
        if not MIN_CENA_M2 <= cena_m2 <= MAX_CENA_M2:
            statystyki["odstajace"] += 1
            continue
        try:
            cena_norm = normalize_area.normalize_price_per_m2(
                cena_m2, area, curve=krzywe.get(segment, domyslna)
            )
        except normalize_area.NormalizationError:
            statystyki["bez_mediany"] += 1
            continue

        odchylenie = market.odchylenie_od_mediany(cena_norm, mediana.mediana_norm)
        if odchylenie is None:
            statystyki["bez_mediany"] += 1
            continue

        session.execute(
            UPSERT_LISTING_MARKET,
            {
                "listing_id": row["id"],
                "teryt_gmina": gmina,
                "segment": segment,
                "poziom": mediana.poziom,
                "teryt_mediany": mediana.teryt,
                "mediana_norm": round(mediana.mediana_norm, 2),
                "n": mediana.n,
                "cena_norm": round(cena_norm, 2),
                "odchylenie": round(odchylenie, 3),
            },
        )
        statystyki["z_mediana"] += 1
        statystyki["poziomy"][mediana.poziom] = statystyki["poziomy"].get(mediana.poziom, 0) + 1

    statystyki["usuniete_nieaktualne"] = session.execute(
        text("DELETE FROM listing_market WHERE computed_at < :znacznik"),
        {"znacznik": znacznik},
    ).rowcount
    return statystyki


# ------------------------------------------------- szereg czasowy cen

# Kwartal, nie miesiac: w gminie miesiac to czesto trzy transakcje, a mediana
# z trzech liczb skacze o kilkadziesiat procent i wyglada jak zmiana rynku.
SELECT_HISTORIA = text(
    """
    SELECT date_trunc('quarter', data_trans)::date AS okres,
           przeznaczenie, pow_gruntu_m2, cena_m2
    FROM rcn_transactions
    WHERE cena_grosze IS NOT NULL
      AND pow_gruntu_m2 > 0
      AND cena_m2 >= 5.0
      AND data_trans BETWEEN :od AND current_date
      AND (udzial IS NULL OR udzial IN ('1', '1/1'))
      AND left(teryt_gmina, :dlugosc) = :teryt
      AND (rodzaj_trans IS NULL OR rodzaj_trans IN ('wolnyRynek', 'sprzedazPrzetargowa'))
    """
)

# Ponizej tylu transakcji w kwartale nie rysujemy punktu. Nie zastepujemy go
# zerem ani interpolacja: dziura w szeregu to informacja, ze w tym kwartale
# w tej gminie po prostu nic sie nie sprzedalo.
MIN_OBS_KWARTALU = 5


def relativedelta_kwartal() -> dt.timedelta:
    """Trzy miesiace liczone ostroznie: 92 dni to najdluzszy kwartal.

    Wystarcza, bo sluzy tylko do stwierdzenia, czy paczka danych z RCN objela
    juz caly kwartal. Zaden rachunek cenowy na tym nie stoi.
    """
    return dt.timedelta(days=92)


def historia_cen(
    session: Session,
    *,
    poziom: str,
    teryt: str,
    segment: str = SEGMENT_ZBIORCZY,
    od: dt.date | None = None,
) -> dict[str, Any]:
    """Mediana ceny za m2 kwartal po kwartale dla jednego obszaru i segmentu.

    Ceny sa znormalizowane do dzialki 1000 m2, ale CELOWO NIE indeksowane na
    dzis: indeksacja splaszczylaby dokladnie to, co ten wykres ma pokazac.
    W tabeli median jest odwrotnie, bo tam porownujemy oferte z dzisiejszym
    poziomem cen.
    """
    od = od or dt.date(2023, 1, 1)
    krzywe = krzywe_z_kalibracji(session)
    domyslna = normalize_area.LogPriceCurve.constant()

    kubelki: dict[dt.date, list[float]] = {}
    for row in session.execute(
        SELECT_HISTORIA, {"od": od, "teryt": teryt, "dlugosc": len(teryt)}
    ).mappings():
        rodzaj = segments.classify(row["przeznaczenie"], None)
        if segment != SEGMENT_ZBIORCZY and rodzaj != segment:
            continue
        try:
            znorm = normalize_area.normalize_price_per_m2(
                float(row["cena_m2"]),
                float(row["pow_gruntu_m2"]),
                curve=krzywe.get(rodzaj, domyslna),
            )
        except normalize_area.NormalizationError:
            continue
        kubelki.setdefault(row["okres"], []).append(znorm)

    # RCN publikuje z opoznieniem, wiec ostatni kwartal jest zwykle niepelny.
    # Widac to golym okiem: w pomorskim 2026 Q3 mial 109 transakcji wobec ok.
    # 1700 w pelnych kwartalach, a mediana skoczyla z 93 na 154 zl/m2. To nie
    # jest zmiana rynku, tylko czesciowa paczka danych, wiec taki punkt
    # oznaczamy i nie liczymy z niego trendu.
    koniec_danych = session.execute(
        text("SELECT max(data_trans) FROM rcn_transactions WHERE data_trans <= current_date")
    ).scalar_one()

    punkty: list[dict[str, Any]] = []
    for okres, ceny in sorted(kubelki.items()):
        if len(ceny) < MIN_OBS_KWARTALU:
            continue
        koniec_kwartalu = okres + relativedelta_kwartal()
        tablica = np.array(ceny)
        punkty.append(
            {
                "okres": okres.isoformat(),
                "etykieta": f"{okres.year} Q{(okres.month - 1) // 3 + 1}",
                "mediana": round(float(np.median(tablica)), 2),
                "p25": round(float(np.percentile(tablica, 25)), 2),
                "p75": round(float(np.percentile(tablica, 75)), 2),
                "n": len(ceny),
                "pelny": bool(koniec_danych and koniec_danych >= koniec_kwartalu),
            }
        )

    # Trend z regresji po calym szeregu, nie z ilorazu pierwszego i ostatniego
    # kwartalu. Na poziomie gminy kwartal miewa 5-15 transakcji i pojedynczy
    # skrajny punkt na brzegu szeregu potrafil zamienic wzrost kilkunastu
    # procent w "+295% rocznie". Szczegoly w scoring/market.trend_szeregu.
    pelne = [p for p in punkty if p["pelny"]]
    zmiana: float | None = None
    if pelne:
        poczatek = dt.date.fromisoformat(str(pelne[0]["okres"]))
        szereg = [
            (
                (dt.date.fromisoformat(str(p["okres"])) - poczatek).days / 365.25,
                float(p["mediana"]),
                int(p["n"]),
            )
            for p in pelne
        ]
        nachylenie = market.trend_szeregu(szereg)
        zmiana = round(nachylenie, 4) if nachylenie is not None else None

    return {
        "poziom": poziom,
        "teryt": teryt,
        "segment": segment,
        "punkty": punkty,
        "koniec_danych": koniec_danych.isoformat() if koniec_danych else None,
        "transakcje": sum(p["n"] for p in punkty),
        "kwartaly_pominiete": len(kubelki) - len(punkty),
        "zmiana_roczna": zmiana,
    }
