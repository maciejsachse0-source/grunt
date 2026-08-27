"""Jak liczony jest score, wycena, deal score i mediany. Zakladka weryfikacyjna.

PO CO TO ISTNIEJE. System podaje uzytkownikowi liczby, na ktorych podstawie
wydaje sie kilkaset tysiecy zlotych. Kazda z nich musi dac sie sprawdzic: skad
przyszla, jaka funkcja ja policzyla, na ilu obserwacjach stoi i czego w niej
brakuje. Ta zakladka nie jest dokumentacja obok kodu, tylko odczytem Z kodu
i Z bazy.

ZASADA: zadna liczba na tej stronie nie jest przepisana recznie.

* progi i wagi sa importowane ze scoring/, wiec zmiana stalej w kodzie zmienia
  strone w tej samej sekundzie i nie da sie ich rozjechac;
* pokrycie, rozklady i liczba obserwacji ida z zapytan do bazy, wiec strona
  pokazuje stan faktyczny, a nie zamierzony;
* filar, ktory w kodzie istnieje, ale nigdy nie dostaje danych, ma tu zero przy
  pokryciu i to jest wlasnie ta informacja, po ktora sie tu przychodzi.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.db import get_db
from grunt.jobs import scheduler
from grunt.scoring import gates, market, pillars, planning, valuation

router = APIRouter()


# --------------------------------------------------------------- opisy filarow

# Skad filar bierze dane i co dokladnie robi z nimi funkcja w scoring/pillars.py.
# Klucze musza zgadzac sie z pillars.WAGI; pilnuje tego test.
FILARY_OPIS: dict[str, dict[str, Any]] = {
    "planistyka": {
        "funkcja": "pillars.pillar_planistyka",
        "wejscie": "status planistyczny A-E z scoring/planning.py",
        "zrodla": ["plan_ogolny", "mpzp", "egib"],
        "jak": (
            "Status planistyczny przechodzi na punkty przez staly slownik "
            "PUNKTY_STATUSU. To nie jest skala ciagla: miedzy 'dzialka w OUZ' "
            "a 'dzialka poza OUZ' nie ma polowy drogi."
        ),
    },
    "lokalizacja": {
        "funkcja": "pillars.pillar_lokalizacja",
        "wejscie": "czas dojazdu do rdzenia, odleglosc do morza",
        "zrodla": [],
        "jak": (
            "Filar wymaga izochron z Valhalli i ekstraktu OSM, ktorych jeszcze "
            "nie ma. Scoring wola pillar_lokalizacja() bez argumentow, wiec filar "
            "jest zawsze niedostepny i jego waga wchodzi do renormalizacji. "
            "Wpisanie tu wartosci srodkowej byloby udawaniem, ze cos wiemy."
        ),
    },
    "infrastruktura": {
        "funkcja": "pillars.pillar_infrastruktura",
        "wejscie": "koszt doprowadzenia mediow w zlotowkach, dostep do drogi",
        "zrodla": ["kiut"],
        "jak": (
            "Uzbrojenie liczone kosztem, nie flaga: 0 zl to 100 punktow, "
            "150 tys. zl to 0. Drugi skladnik, dostep do drogi, nie jest jeszcze "
            "zbierany, wiec filar stoi dzis wylacznie na koszcie mediow."
        ),
    },
    "fizyka": {
        "funkcja": "pillars.pillar_fizyka",
        "wejscie": "front dzialki, spadek terenu, zwartosc ksztaltu",
        "zrodla": ["egib", "nmt"],
        "jak": (
            "Trzy skladniki skalowane liniowo z obcieciem: front 10-30 m, "
            "spadek 0-15% odwrotnie, zwartosc 0,35-0,78. Srednia z tych, ktore "
            "sa dostepne. Front i zwartosc wymagaja PEWNEGO dopasowania dzialki "
            "ewidencyjnej, bo licza sie z jej geometrii."
        ),
    },
    "ryzyka": {
        "funkcja": "pillars.pillar_ryzyka",
        "wejscie": "strefy zagrozenia powodziowego, obszary chronione",
        "zrodla": ["isok"],
        "jak": (
            "Najgorsza strefa decyduje: q10 to 10 punktow, q1 30, hWZ 45, "
            "q0,2 75, brak strefy 100. Filar liczy sie tylko wtedy, gdy odpytanie "
            "ISOK bylo kompletne; przy czesciowej odpowiedzi zostaje niedostepny, "
            "bo brak trafienia w niesprawdzonej warstwie nie znaczy 'bezpiecznie'."
        ),
    },
    "rynek": {
        "funkcja": "pillars.pillar_rynek",
        "wejscie": "dynamika cen gminy (CAGR), plynnosc rynku",
        "zrodla": ["rcn"],
        "jak": (
            "Dynamika skalowana z przedzialu -5%..+20% rocznie. Plynnosc "
            "(transakcje na 1000 mieszkancow) wymaga GUS BDL i jeszcze jej nie ma, "
            "wiec filar stoi na samej dynamice."
        ),
    },
    "chlonnosc": {
        "funkcja": "brak",
        "wejscie": "PUM mozliwy do uzyskania na dzialce",
        "zrodla": [],
        "jak": (
            "Filar wystepuje tylko w profilu deweloperskim i nie jest policzony: "
            "wymaga wskaznikow z tresci MPZP, a Rejestr Urbanistyczny udostepnia "
            "granice aktow, nie ich zapisy."
        ),
    },
}


# ------------------------------------------------------------- opisy zrodel

ZRODLA: tuple[dict[str, Any], ...] = (
    {
        "klucz": "rcn",
        "nazwa": "RCN - Rejestr Cen Nieruchomosci",
        "co_daje": "ceny transakcyjne z aktow notarialnych: cena, powierzchnia, data, TERYT",
        "url": "https://mapy.geoportal.gov.pl/wss/service/rcn (WFS)",
        "uwaga": (
            "Jedyne zrodlo cen faktycznie zaplaconych. Wszystko inne w tym systemie "
            "sluzy do tego, zeby oferte porownac z tymi cenami."
        ),
        "tabela": "rcn_transactions",
    },
    {
        "klucz": "uldk",
        "nazwa": "ULDK - lokalizacja dzialek",
        "co_daje": "geometria dzialki po identyfikatorze, nazwy gminy i powiatu",
        "url": "https://uldk.gugik.gov.pl/",
        "uwaga": "Odpowiedzi sa cache'owane, wiec kolejne przebiegi nie odpytuja ponownie.",
        "tabela": "uldk_cache",
    },
    {
        "klucz": "egib",
        "krok": "dzialka",
        "nazwa": "EGiB - ewidencja gruntow i budynkow",
        "co_daje": "dzialki w promieniu punktu oferty, ich geometria i sposob uzytkowania",
        "url": "https://mapy.geoportal.gov.pl/wss/service/PZGIK/EGIB/WFS/UslugaZbiorcza",
        "uwaga": "Z geometrii licza sie front, zwartosc i smuklosc, czyli caly filar fizyki.",
        "tabela": None,
    },
    {
        "klucz": "plan_ogolny",
        "krok": "planistyka",
        "nazwa": "Plany ogolne gmin",
        "co_daje": "czy gmina ma plan ogolny, strefa planistyczna, przynaleznosc do OUZ",
        "url": "https://mapy.geoportal.gov.pl/wss/ext/PlanyOgolneGmin",
        "uwaga": (
            "Najwazniejsze pojedyncze zrodlo w systemie: przejscie gminy ze stanu E "
            "do D obniza wartosc dzialek poza OUZ o kilkadziesiat procent."
        ),
        "tabela": None,
    },
    {
        "klucz": "mpzp",
        "nazwa": "Rejestr Urbanistyczny",
        "co_daje": "granice obowiazujacych aktow planow miejscowych",
        "url": "https://rejestr-urbanistyczny.gov.pl/uslugi-sieciowe (WFS)",
        "uwaga": (
            "Rejestr podaje granice aktu, a nie symbol przeznaczenia. Dlatego dzialka "
            "objeta MPZP o nieznanym przeznaczeniu dostaje status '?' i szeroki "
            "przedzial mnoznika 0,45-1,00, zamiast udawanego 'A'."
        ),
        "tabela": None,
    },
    {
        "klucz": "isok",
        "krok": "powodz",
        "nazwa": "ISOK - mapy zagrozenia powodziowego",
        "co_daje": "strefy q10, q1, q0,2 i hWZ",
        "url": "https://wody.isok.gov.pl/wss/INSPIRE/INSPIRE_NZ_HY_MZPMRP_WMS",
        "uwaga": (
            "Cztery zapytania na oferte. Niepelna odpowiedz oznacza brak filaru, nie zero ryzyka."
        ),
        "tabela": None,
    },
    {
        "klucz": "kiut",
        "krok": "uzbrojenie",
        "nazwa": "KIUT - Krajowa Integracja Uzbrojenia Terenu",
        "co_daje": "przebiegi sieci wodociagowej, kanalizacyjnej, gazowej i elektrycznej",
        "url": "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaUzbrojeniaTerenu",
        "uwaga": "Z odleglosci do sieci liczony jest koszt doprowadzenia mediow w zlotowkach.",
        "tabela": None,
    },
    {
        "klucz": "nmt",
        "krok": "teren",
        "nazwa": "NMT - numeryczny model terenu",
        "co_daje": "wysokosc nad poziomem morza w punktach, a z nich spadek terenu",
        "url": "https://services.gugik.gov.pl/nmt/",
        "uwaga": "Dziewiec zapytan na oferte: srodek dzialki i osiem punktow wokol.",
        "tabela": None,
    },
)


# --------------------------------------------------------------- zapytania

# Pokrycie filarow czytamy z zapisanych wynikow, nie z definicji. Filar, ktory
# w kodzie istnieje, ale nigdy nie dostaje danych, ma tu zero i wlasnie o to
# chodzi: definicja mowi, co zamierzamy, a to zapytanie, co naprawde mamy.
POKRYCIE_FILAROW = text(
    """
    SELECT e.key AS filar,
           count(*) FILTER (WHERE e.value <> 'null'::jsonb) AS ma,
           count(*) AS razem
    FROM scores s, LATERAL jsonb_each(s.pillar_scores) AS e(key, value)
    GROUP BY e.key
    """
)

ROZKLAD_SCORE = text(
    """
    SELECT count(*) AS razem,
           count(score_total) AS z_wynikiem,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY score_total) AS mediana,
           min(score_total) AS minimum, max(score_total) AS maksimum,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY coverage) AS mediana_coverage,
           count(*) FILTER (WHERE coverage < :prog) AS ponizej_progu,
           max(computed_at) AS ostatnie_liczenie
    FROM scores
    """
)

AKTYWNE_GATES = text(
    """
    SELECT g->>'nazwa' AS nazwa, count(*) AS ile
    FROM scores s, LATERAL jsonb_array_elements(s.gates->'aktywne') AS g
    GROUP BY 1
    """
)

STATUSY_PLANISTYCZNE = text(
    """
    SELECT COALESCE(plan_status, '?') AS status, count(*) AS ile
    FROM listing_enrichment
    GROUP BY 1
    """
)

ROZKLAD_DEAL = text(
    """
    SELECT count(deal_score) AS z_deal,
           percentile_cont(0.25) WITHIN GROUP (ORDER BY deal_score) AS p25,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY deal_score) AS mediana,
           percentile_cont(0.75) WITHIN GROUP (ORDER BY deal_score) AS p75,
           min(deal_score) AS minimum, max(deal_score) AS maksimum,
           count(*) FILTER (WHERE deal_score >= :prog) AS okazje
    FROM scores
    """
)

KALIBRACJE = text(
    """
    SELECT DISTINCT ON (kind, segment) kind, segment, wartosc, n_obs, zrodlo, computed_at
    FROM calibrations
    ORDER BY kind, segment, computed_at DESC
    """
)

ZRODLA_OK = text(
    "SELECT unnest(zrodla_ok) AS zrodlo, count(*) AS ile FROM listing_enrichment GROUP BY 1"
)

# Blad jest zapisany jako "klucz: tresc", wiec do zliczenia wystarczy prefiks.
ZRODLA_BLEDY = text(
    """
    SELECT split_part(b, ':', 1) AS zrodlo, count(*) AS ile
    FROM listing_enrichment, LATERAL unnest(zrodla_bledy) AS b
    GROUP BY 1
    """
)

OSTATNIE_ZADANIA = text(
    """
    SELECT DISTINCT ON (kind) kind, status, finished_at, wynik
    FROM jobs
    ORDER BY kind, COALESCE(finished_at, created_at) DESC
    """
)

# Audyt danych osobowych. Nie sprawdzamy deklaracji, tylko schemat: kolumna
# o takiej nazwie albo istnieje, albo nie.
AUDYT_OSOBOWY = text(
    """
    SELECT table_name, column_name
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND column_name ~ '(imie|nazwisko|phone|telefon|email|mail|seller|ogloszeniodawca)'
    ORDER BY table_name, column_name
    """
)

# Dwa trafienia audytu sa dozwolone i musza byc nazwane, inaczej strona
# krzyczalaby na wlasny, zgodny z zasada stan:
#   listings.phone_sha256  numer telefonu wolno przetworzyc do SHA-256 i zapisac
#                          jako hash, wylacznie na potrzeby deduplikacji;
#   users.email            adres wlasciciela systemu, potrzebny do wysylki
#                          alertow. Zasada dotyczy danych OGLOSZENIODAWCOW,
#                          a nie konta uzytkownika narzedzia.
DOZWOLONE_OSOBOWE: dict[tuple[str, str], str] = {
    ("listings", "phone_sha256"): (
        "hash SHA-256 numeru z ogloszenia, wylacznie do deduplikacji; "
        "z hasza nie da sie odtworzyc numeru"
    ),
    ("users", "email"): ("adres wlasciciela systemu do wysylki alertow, nie dane ogloszeniodawcy"),
}

# Tabele, ktorych liczebnosc pokazujemy. Stala, nie parametr: nazwy tabel nie da
# sie zbindowac, wiec lista musi pochodzic z kodu, a nie z zapytania HTTP.
TABELE: tuple[str, ...] = (
    "listings",
    "listing_enrichment",
    "scores",
    "rcn_transactions",
    "uldk_cache",
    "market_medians",
    "market_dynamics",
    "listing_market",
    "teryt_names",
    "listing_duplicates",
)


def _liczby_wierszy(session: Session) -> dict[str, int]:
    """Liczba wierszy w tabelach ze stalej TABELE, jednym zapytaniem."""
    czesci = " UNION ALL ".join(f"SELECT '{t}' AS tabela, count(*) AS n FROM {t}" for t in TABELE)
    rows = session.execute(text(czesci)).mappings().all()  # noqa: S608 - nazwy tabel ze stalej
    return {r["tabela"]: r["n"] for r in rows}


@router.get("/metodologia")
def metodologia(session: Session = Depends(get_db)) -> dict[str, Any]:
    """Opis metody razem z aktualnym stanem danych.

    Wszystkie progi i wagi pochodza z modulow scoring/, a wszystkie liczby
    obserwacji z biezacych zapytan. Ta warstwa nie ma wlasnych stalych liczbowych.
    """
    pokrycie = {
        r["filar"]: {"ma": r["ma"], "razem": r["razem"]}
        for r in session.execute(POKRYCIE_FILAROW).mappings()
    }
    rozklad = session.execute(ROZKLAD_SCORE, {"prog": pillars.COVERAGE_MIN}).mappings().one()
    aktywne_gates = {r["nazwa"]: r["ile"] for r in session.execute(AKTYWNE_GATES).mappings()}
    statusy = {r["status"]: r["ile"] for r in session.execute(STATUSY_PLANISTYCZNE).mappings()}
    deal = session.execute(ROZKLAD_DEAL, {"prog": valuation.PROG_OKAZJI}).mappings().one()
    kalibracje = [dict(r) for r in session.execute(KALIBRACJE).mappings()]
    ok = {r["zrodlo"]: r["ile"] for r in session.execute(ZRODLA_OK).mappings()}
    bledy = {r["zrodlo"]: r["ile"] for r in session.execute(ZRODLA_BLEDY).mappings()}
    zadania = {r["kind"]: dict(r) for r in session.execute(OSTATNIE_ZADANIA).mappings()}
    trafienia = [dict(r) for r in session.execute(AUDYT_OSOBOWY).mappings()]
    liczby = _liczby_wierszy(session)

    spread = next((k for k in kalibracje if k["kind"] == "spread" and k["segment"] is None), None)
    beta1 = sorted(
        (k for k in kalibracje if k["kind"] == "beta1"), key=lambda k: -(k["n_obs"] or 0)
    )

    return {
        "score": _sekcja_score(pokrycie, rozklad, aktywne_gates, statusy),
        "wycena": _sekcja_wycena(beta1),
        "deal": _sekcja_deal(deal, spread),
        "rynek": _sekcja_rynek(liczby),
        "zrodla": _sekcja_zrodla(ok, bledy, liczby),
        "zadania": _sekcja_zadania(zadania),
        "dane": liczby,
        "prywatnosc": {
            "zasada": (
                "Do bazy nie trafiaja imiona, nazwiska, numery telefonu ani adresy e-mail "
                "ogloszeniodawcow. Numer telefonu wolno przetworzyc wylacznie do SHA-256 "
                "i zapisac jako hash, tylko na potrzeby deduplikacji. Pelne opisy ogloszen "
                "nie sa przechowywane, zdjecia tez nie: zostaje URL i pHash miniatury."
            ),
            "co_sprawdzamy": (
                "wszystkie kolumny schematu public pod katem nazw wskazujacych na dane "
                "osobowe. Trafienie jest albo jawnie dozwolone i wtedy ma uzasadnienie, "
                "albo jest naruszeniem zasady i wtedy nie ma go czym wytlumaczyc."
            ),
            "dozwolone": [
                {**t, "uzasadnienie": DOZWOLONE_OSOBOWE[(t["table_name"], t["column_name"])]}
                for t in trafienia
                if (t["table_name"], t["column_name"]) in DOZWOLONE_OSOBOWE
            ],
            "naruszenia": [
                t for t in trafienia if (t["table_name"], t["column_name"]) not in DOZWOLONE_OSOBOWE
            ],
        },
    }


def _sekcja_score(
    pokrycie: dict[str, dict[str, int]],
    rozklad: Any,
    aktywne_gates: dict[str, int],
    statusy: dict[str, int],
) -> dict[str, Any]:
    filary = []
    for klucz, nazwa in pillars.NAZWY.items():
        opis = FILARY_OPIS.get(klucz, {})
        stan = pokrycie.get(klucz, {"ma": 0, "razem": rozklad["razem"] or 0})
        filary.append(
            {
                "klucz": klucz,
                "nazwa": nazwa,
                "waga_detaliczny": pillars.WAGI["detaliczny"].get(klucz),
                "waga_deweloper": pillars.WAGI["deweloper"].get(klucz),
                "funkcja": opis.get("funkcja"),
                "wejscie": opis.get("wejscie"),
                "zrodla": opis.get("zrodla", []),
                "jak": opis.get("jak"),
                "ma_dane": stan["ma"],
                "z_ilu": stan["razem"],
            }
        )

    return {
        "wzor": "Score = Gate x suma(waga_k x ocena_k) / suma(waga_k po dostepnych)",
        "wyjasnienie_wzoru": (
            "Filary, dla ktorych brakuje danych, nie dostaja wartosci srodkowej: "
            "wypadaja z sumy, a wagi pozostalych sa renormalizowane. Osobno raportowana "
            "jest kompletnosc, czyli udzial wagi filarow, ktore dalo sie policzyc."
        ),
        "coverage_min": pillars.COVERAGE_MIN,
        "regula_coverage": (
            f"Ponizej {pillars.COVERAGE_MIN:.0%} kompletnosci nie zwracamy liczby, tylko powod. "
            "Zly score jest gorszy niz brak score'u."
        ),
        "profil_domyslny": "detaliczny",
        "filary": filary,
        "punkty_statusu": pillars.PUNKTY_STATUSU,
        "gates": [
            {
                "nazwa": nazwa,
                "mnoznik": mnoznik,
                "powod": powod,
                "aktywny_w_ofertach": aktywne_gates.get(nazwa, 0),
            }
            for nazwa, mnoznik, powod in _katalog_gates()
        ],
        "wyjasnienie_gates": (
            "Gate to mnoznik, nie skladnik sumy. Czynnik, ktorego brak dyskwalifikuje "
            "inwestycje, nie moze byc usredniany z zaletami: dzialka bez dostepu do drogi "
            "nie jest o 10% gorsza, tylko niebudowlana."
        ),
        "statusy_planistyczne": [
            {
                "status": status,
                "opis": planning.OPISY[status],
                "mnoznik_min": widelki[0],
                "mnoznik_max": widelki[1],
                "punkty": pillars.PUNKTY_STATUSU.get(status),
                "ofert": statusy.get(status, 0),
            }
            for status, widelki in planning.MNOZNIKI.items()
        ],
        "rozklad": {
            "ocenionych": rozklad["razem"],
            "z_wynikiem": rozklad["z_wynikiem"],
            "bez_wyniku": (rozklad["razem"] or 0) - (rozklad["z_wynikiem"] or 0),
            "mediana": _f(rozklad["mediana"]),
            "min": _f(rozklad["minimum"]),
            "max": _f(rozklad["maksimum"]),
            "mediana_kompletnosci": _f(rozklad["mediana_coverage"]),
            "ponizej_progu_kompletnosci": rozklad["ponizej_progu"],
            "ostatnie_liczenie": rozklad["ostatnie_liczenie"],
        },
    }


def _katalog_gates() -> list[tuple[str, float, str]]:
    """Wszystkie mnozniki zerujace, ktore moze zwrocic gates.evaluate.

    Wolamy funkcje na spreparowanych wejsciach, zamiast przepisywac liste, zeby
    nowy gate w kodzie pojawil sie tutaj sam i z wlasnym uzasadnieniem.
    """
    warianty: list[dict[str, Any]] = [
        {"road_access": 0},
        {"plan_status": "D"},
        {"strefy_powodziowe": ["q10"]},
        {"strefy_powodziowe": ["q1"]},
        {"strefy_powodziowe": ["hWZ"]},
        {"sposob_uzyt": "grunty lesne", "odlesienie_mozliwe": False},
    ]
    katalog: list[tuple[str, float, str]] = []
    for wariant in warianty:
        katalog.extend(
            (gate.nazwa, gate.mnoznik, gate.powod) for gate in gates.evaluate(**wariant).gates
        )
    return katalog


def _sekcja_wycena(beta1: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "model": "SE-KNN (Model 2 z sekcji 5.2.4)",
        "opis": (
            "k najblizszych transakcji w przestrzeni laczacej geografie i cechy dzialki. "
            "Odleglosc laczona: d = (1-lambda) x roznica cech + lambda x roznica geografii, "
            "przy czym lambda = 0,7 znaczy, ze geografia wazy wiecej niz cechy. "
            "Wszystko liczone na logarytmach cen i statystykach odpornych (mediana, MAD), "
            "bo RCN zawiera ceny 1 zl i powierzchnie 5 mln m2."
        ),
        "normalizacja": (
            "Cena za m2 spada z powierzchnia dzialki, wiec przed porownaniem kazda cena jest "
            "sprowadzana do dzialki 1000 m2 krzywa log-cenowa o wykladniku beta1. Wykladnik "
            "jest kalibrowany osobno w kazdym segmencie rynku, na wlasnych danych RCN."
        ),
        "parametry": {
            "k_sasiadow": 20,
            "lambda_geografia": 0.7,
            "maks_odleglosc_m": 15_000,
            "drift_roczny": 0.08,
            "kara_za_inny_segment": valuation.SEGMENT_MISMATCH_PENALTY,
            "k_shrinkage_model1": valuation.DEFAULT_K_SHRINK,
            "min_obs_dla_sigmy": valuation.MIN_OBS_FOR_SIGMA,
            "mnoznik_mad": valuation.OUTLIER_MAD_MULTIPLIER,
            "podloga_sigma": valuation.SIGMA_FLOOR_LOG,
            "maks_sigma_wiarygodna": valuation.MAX_SIGMA_RELIABLE,
            "poziom_ufnosci": 0.80,
            "okno_transakcji_mies": 36,
        },
        "wyjasnienie_sigma": (
            f"Wycena z sigma powyzej {valuation.MAX_SIGMA_RELIABLE} nie jest zwracana wcale. "
            "Sigma 0,60 to przedzial 80% szeroki mniej wiecej dwukrotnie, czyli od -54% do "
            f"+116% wzgledem punktu. Podloga {valuation.SIGMA_FLOOR_LOG} istnieje, bo nawet "
            "przy tysiacu porownywalnych nie udajemy, ze znamy cene z dokladnoscia do 5%."
        ),
        "beta1": [
            {
                "segment": k["segment"],
                "wartosc": _f(k["wartosc"]),
                "n": k["n_obs"],
                "zrodlo": k["zrodlo"],
                "kiedy": k["computed_at"],
            }
            for k in beta1
        ],
        "wyjasnienie_beta1": (
            "beta1 = 0,76 znaczy, ze dwukrotnie wieksza dzialka ma cene za m2 nizsza o okolo "
            "16%. Wartosc blisko 1,0 to brak efektu skali, ponizej 0,5 - efekt bardzo silny. "
            "Segment z beta1 powyzej 1 mowi, ze tam wieksze dzialki bywaja DROZSZE za m2."
        ),
    }


def _sekcja_deal(deal: Any, spread: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "wzor": "D = (V x (1 + spread) - cena_ofertowa) / (V x (1 + spread) x sigma)",
        "opis": (
            "Deal score mowi, o ile odchylen standardowych cena ofertowa lezy PONIZEJ wyceny. "
            "Dzielenie przez sigma jest tu kluczowe: bez niego system zalewa uzytkownika "
            "'okazjami' z gmin, o ktorych model nic nie wie, bo tam kazda wycena jest szeroka."
        ),
        "spread": (
            {
                "wartosc": _f(spread["wartosc"]),
                "n": spread["n_obs"],
                "zrodlo": spread["zrodlo"],
                "kiedy": spread["computed_at"],
            }
            if spread
            else None
        ),
        "wyjasnienie_spreadu": (
            "V pochodzi z RCN, czyli z cen TRANSAKCYJNYCH, a porownujemy je z cena OFERTOWA. "
            "Bez korekty deal score jest systematycznie ujemny i nie oznacza wtedy braku okazji, "
            "tylko sam fakt, ze ogloszenia sa drozsze od aktow notarialnych. Spread jest mierzony "
            "z wlasnych danych, a nie zalozony: domyslne 0,0 zostawia surowe porownanie, zeby "
            "brak kalibracji byl widoczny w liczbie, a nie ukryty w zalozeniu."
        ),
        "prog_okazji": valuation.PROG_OKAZJI,
        "wyjasnienie_progu": (
            f"D >= {valuation.PROG_OKAZJI} to prog uwagi, nie prog decyzji. Przy zalozeniu "
            "rozkladu normalnego to mniej wiecej 7. percentyl, ale czesc tych ofert ma niska "
            "cene z powodu, ktorego model nie widzi: sluzebnosci, wspolwlasnosci, ksztaltu "
            "nie do zabudowy."
        ),
        "rozklad": {
            "z_deal_score": deal["z_deal"],
            "p25": _f(deal["p25"]),
            "mediana": _f(deal["mediana"]),
            "p75": _f(deal["p75"]),
            "min": _f(deal["minimum"]),
            "max": _f(deal["maksimum"]),
            "powyzej_progu": deal["okazje"],
        },
    }


def _sekcja_rynek(liczby: dict[str, int]) -> dict[str, Any]:
    from grunt.enrich import market as market_enrich

    return {
        "opis": (
            "Mediana ceny transakcyjnej za m2 w obszarze, znormalizowana do dzialki 1000 m2 "
            "i zindeksowana na dzis dynamika tego obszaru. Oferta jest z nia porownywana "
            "w tym samym segmencie rynku, a gdy portal nie podal przeznaczenia - z mediana "
            "wszystkich segmentow razem."
        ),
        "wybor_poziomu": (
            "Bierzemy najbardziej lokalna mediane, ktora ma dosc obserwacji: gmina, potem "
            "powiat, potem wojewodztwo. Poziomow NIE mieszamy, inaczej niz przy dynamice: "
            "uzytkownik czyta 'mediana w gminie X, n=142' i to musi byc prawdziwa mediana "
            "tej gminy, a nie liczba sklejona z dwoch poziomow."
        ),
        "progi": {
            "min_transakcji_mediany": market.MIN_OBS_MEDIANY,
            "min_transakcji_zapisu": market_enrich.MIN_OBS_ZAPISU,
            "min_transakcji_kwartalu": market_enrich.MIN_OBS_KWARTALU,
            "min_kwartalow_trendu": market.MIN_KWARTALOW_TRENDU,
            "min_mediana_n_trendu": market.MIN_MEDIANA_N_TRENDU,
            "min_lata_trendu": market.MIN_LATA_TRENDU,
            "min_transakcji_rok": market.MIN_OBS_ROK,
            "maks_roczna_zmiana": market.MAX_ROCZNA_ZMIANA,
            "maks_indeksacja": market.MAX_INDEKSACJA,
            "k_shrinkage": market.K_SHRINKAGE,
            "min_cena_m2": market_enrich.MIN_CENA_M2,
            "maks_cena_m2": market_enrich.MAX_CENA_M2,
        },
        "filtr_transakcji": (
            "Do median wchodza wylacznie transakcje wolnorynkowe i przetargowe, z pelnym "
            "udzialem we wlasnosci. Sprzedaz z bonifikata i na cel publiczny jest odrzucana, "
            "bo to ceny ustalone administracyjnie, nie obrot rynkowy."
        ),
        "trend": (
            "Trend roczny na wykresie liczy Theil-Sen, czyli mediana nachylen wszystkich par "
            "kwartalow po logarytmie ceny. Roznica pierwszego i ostatniego kwartalu dawala na "
            "poziomie gminy wyniki w rodzaju +295% rocznie, bo caly wynik stal na dwoch "
            "najbardziej przypadkowych punktach szeregu."
        ),
        "stan": {
            "median_w_bazie": liczby.get("market_medians", 0),
            "obszarow_z_dynamika": liczby.get("market_dynamics", 0),
            "ofert_przypisanych_do_rynku": liczby.get("listing_market", 0),
            "transakcji_rcn": liczby.get("rcn_transactions", 0),
        },
    }


def _sekcja_zrodla(
    ok: dict[str, int], bledy: dict[str, int], liczby: dict[str, int]
) -> list[dict[str, Any]]:
    """Zrodla razem z tym, ile razy naprawde odpowiedzialy.

    Sukces jest liczony po KROKU wzbogacania (pipeline zapisuje "powodz",
    "teren", "dzialka"), a blad po nazwie USLUGI, bo tak sa zapisane w bazie.
    Zrodlo bez kroku, jak RCN, jest odpytywane wsadowo poza petla wzbogacania
    i wtedy zamiast licznika odpytan pokazujemy liczbe wierszy w bazie.
    """
    return [
        {
            **{k: v for k, v in zrodlo.items() if k not in ("tabela", "krok")},
            "udanych_odpytan": ok.get(zrodlo["krok"]) if zrodlo.get("krok") else None,
            "bledow": bledy.get(zrodlo["klucz"], 0),
            "wierszy_w_bazie": liczby.get(zrodlo["tabela"]) if zrodlo["tabela"] else None,
        }
        for zrodlo in ZRODLA
    ]


def _sekcja_zadania(ostatnie: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "kind": zadanie.kind,
            "opis": zadanie.opis,
            "co_ile_godzin": round(zadanie.interwal / dt.timedelta(hours=1), 1),
            "ostatnie": (ostatnie.get(zadanie.kind) or {}).get("finished_at"),
            "status": (ostatnie.get(zadanie.kind) or {}).get("status"),
            "wynik": (ostatnie.get(zadanie.kind) or {}).get("wynik"),
        }
        for zadanie in scheduler.HARMONOGRAM
    ]


def _f(wartosc: Any) -> float | None:
    """Numeric z bazy na float. None zostaje None, bo brak to nie zero."""
    return float(wartosc) if wartosc is not None else None
