"""Kalibracja na wlasnych danych: warstwa czytajaca baze. Sekcja 5.6 dokumentu.

Sam rachunek jest w scoring/calibration.py i nie dotyka bazy. Tutaj jest to,
co bez bazy zrobic sie nie da: zebranie obserwacji, uruchomienie wyceny dla
kazdej oferty i zapis pomiaru do tabeli calibrations.

CZTERY POMIARY

* **spread** - o ile ceny ofertowe leza wyzej niz transakcyjne. Docelowo liczony
  na parach "oferta zniknela, dzialka pojawila sie w RCN" (zrodlo "pary").
  Zanim takie pary beda, liczymy szacunek zastepczy: iloraz ceny ofertowej
  do wyceny modelu (zrodlo "oferty_vs_model"). To NIE jest to samo. Szacunek
  zastepczy miesza prawdziwy spread z bledem modelu i po jego zastosowaniu
  mediana deal score'u z definicji siada blisko zera, wiec deal score znaczy
  wtedy "tansza niz typowa oferta", a nie "tansza niz wartosc".
* **beta1** - elastycznosc ceny wzgledem powierzchni, osobno dla kazdego
  segmentu rynku. Na wymieszanych danych wychodzila 0,26 zamiast 0,85, bo
  powierzchnia byla zmienna zastepcza dla przeznaczenia.
* **wagi** - stabilnosc rankingu przy perturbacji wag o +/-30%.
* **dyskryminacja** - czy rozklad wynikow w ogole rozroznia dzialki.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.scoring import calibration, normalize_area, pillars, segments

log = logging.getLogger(__name__)

# Ponizej tylu obserwacji pomiar zapisujemy, ale nie uzywamy go do korekty.
MIN_OBS_SPREAD = 30
MIN_OBS_BETA1 = 200

SELECT_DO_WYCENY = text(
    """
    SELECT le.listing_id, le.parcel_uldk_id, le.parcel_match,
           l.price_grosze, l.area_m2, l.przeznaczenie_raw,
           ST_AsText(l.geom) AS geom_wkt
    FROM listing_enrichment le
    JOIN listings l ON l.id = le.listing_id
    WHERE l.is_active
      AND l.price_grosze IS NOT NULL
      AND l.area_m2 IS NOT NULL
      AND l.geom IS NOT NULL
      AND le.parcel_uldk_id IS NOT NULL
    ORDER BY le.listing_id
    LIMIT :limit
    """
)

# Para w rozumieniu sekcji 5.6: oferta widziana na portalu, a potem transakcja
# ta sama dzialka. data_trans musi byc pozniejsza niz pierwsze widzenie oferty,
# inaczej to poprzedni wlasciciel, a nie sprzedaz tej oferty.
SELECT_PARY = text(
    """
    SELECT l.id AS listing_id, l.portal::text AS portal, l.price_grosze,
           l.area_m2, l.first_seen_at::date AS pierwszy_raz,
           l.last_seen_at::date AS ostatni_raz, l.is_active,
           r.cena_grosze, r.pow_gruntu_m2, r.data_trans, r.przeznaczenie,
           (r.data_trans - l.first_seen_at::date) AS dni_do_transakcji,
           (l.last_seen_at::date - l.first_seen_at::date) AS dni_na_rynku
    FROM listings l
    JOIN listing_enrichment le ON le.listing_id = l.id
    JOIN rcn_transactions r ON r.id_dzialki = le.parcel_uldk_id
    WHERE le.parcel_match = 'high'
      AND r.cena_grosze IS NOT NULL
      AND r.pow_gruntu_m2 > 0
      AND r.data_trans > l.first_seen_at::date
      AND r.data_trans <= l.first_seen_at::date + :okno_dni
    ORDER BY r.data_trans
    """
)

ZAPISZ = text(
    """
    INSERT INTO calibrations (kind, segment, wartosc, n_obs, zrodlo, szczegoly)
    VALUES (:kind, :segment, :wartosc, :n_obs, :zrodlo, CAST(:szczegoly AS jsonb))
    RETURNING id
    """
)


def zapisz(
    session: Session,
    *,
    kind: str,
    wartosc: float | None,
    n_obs: int,
    zrodlo: str,
    segment: str | None = None,
    szczegoly: dict[str, Any] | None = None,
) -> int:
    """Dopisanie pomiaru. Historia, nie stan: nic nie jest nadpisywane."""
    return int(
        session.execute(
            ZAPISZ,
            {
                "kind": kind,
                "segment": segment,
                "wartosc": wartosc,
                "n_obs": n_obs,
                "zrodlo": zrodlo,
                "szczegoly": json.dumps(szczegoly or {}, ensure_ascii=False, default=str),
            },
        ).scalar_one()
    )


def aktualna(session: Session, kind: str, segment: str | None = None) -> dict[str, Any] | None:
    """Najswiezszy pomiar danego rodzaju. Segment ma pierwszenstwo przed globalnym."""
    row = (
        session.execute(
            text(
                """
                SELECT kind, segment, wartosc, n_obs, zrodlo, szczegoly, computed_at
                FROM calibrations
                WHERE kind = :kind
                  AND (segment = :segment OR (:segment IS NULL AND segment IS NULL))
                ORDER BY computed_at DESC
                LIMIT 1
                """
            ),
            {"kind": kind, "segment": segment},
        )
        .mappings()
        .one_or_none()
    )
    if row is None and segment is not None:
        return aktualna(session, kind, None)
    return dict(row) if row else None


def aktualny_spread(session: Session, segment: str | None = None) -> float:
    """Spread do deal score'u. Zero, gdy pomiaru nie ma albo jest za slaby.

    Zero znaczy "porownujemy oferte wprost z wycena transakcyjna", czyli deal
    score bedzie systematycznie ujemny. To celowe: brak kalibracji ma byc widoczny
    w liczbie, a nie zalatany zalozeniem z literatury.
    """
    pomiar = aktualna(session, "spread", segment)
    if pomiar is None or pomiar["wartosc"] is None:
        return 0.0
    if int(pomiar["n_obs"] or 0) < MIN_OBS_SPREAD:
        log.info("spread pominiety, za malo obserwacji: %s", pomiar["n_obs"])
        return 0.0
    return float(pomiar["wartosc"])


# ------------------------------------------------------------------ spread


def wyceny_ofert(session: Session, *, limit: int = 500) -> list[dict[str, Any]]:
    """Cena ofertowa i wycena modelu dla kazdej oferty, ktora da sie wycenic."""
    from grunt.enrich import score_listings

    as_of = dt.date.today()
    wyniki: list[dict[str, Any]] = []
    for row in session.execute(SELECT_DO_WYCENY, {"limit": limit}).mappings().all():
        wycena = score_listings.wycen_oferte(session, row, as_of=as_of)
        if wycena is None:
            continue
        wyniki.append(
            {
                "listing_id": row["listing_id"],
                "cena_grosze": int(row["price_grosze"]),
                "wycena_grosze": float(wycena.v_hat_grosze),
                "segment": segments.classify(row["przeznaczenie_raw"], None),
                "area_m2": int(row["area_m2"]),
            }
        )
    return wyniki


def spread_z_ofert(
    session: Session, *, limit: int = 500, min_obs_segmentu: int = 20
) -> dict[str, calibration.Spread]:
    """Szacunek zastepczy spreadu: globalny i per segment rynku."""
    wyceny = wyceny_ofert(session, limit=limit)
    if not wyceny:
        return {}

    wynik: dict[str, calibration.Spread] = {
        "": calibration.szacuj_spread(
            [w["cena_grosze"] for w in wyceny],
            [w["wycena_grosze"] for w in wyceny],
        )
    }

    po_segmencie: dict[str, list[dict[str, Any]]] = {}
    for w in wyceny:
        po_segmencie.setdefault(w["segment"], []).append(w)
    for segment, grupa in po_segmencie.items():
        if len(grupa) < min_obs_segmentu:
            continue
        wynik[segment] = calibration.szacuj_spread(
            [w["cena_grosze"] for w in grupa],
            [w["wycena_grosze"] for w in grupa],
        )
    return wynik


def pary_oferta_transakcja(session: Session, *, okno_dni: int = 200) -> list[dict[str, Any]]:
    """Oferty, ktorych dzialka pojawila sie potem w RCN. Wlasciwy pomiar spreadu."""
    return [
        dict(row) for row in session.execute(SELECT_PARY, {"okno_dni": okno_dni}).mappings().all()
    ]


def spread_z_par(session: Session, *, okno_dni: int = 200) -> calibration.Spread | None:
    """Spread na zmatchowanych parach. None, dopoki par nie ma."""
    pary = pary_oferta_transakcja(session, okno_dni=okno_dni)
    if not pary:
        return None
    return calibration.szacuj_spread(
        [float(p["price_grosze"]) for p in pary],
        [float(p["cena_grosze"]) for p in pary],
        zrodlo="pary",
    )


# ------------------------------------------------------------------- beta1


def transakcje_per_segment(
    session: Session, *, od: dt.date | None = None
) -> dict[str, list[tuple[float, float]]]:
    """Powierzchnia i cena calkowita transakcji, pogrupowane po segmencie rynku.

    Zakres stosowalnosci jest ten sam co w scripts/eval_valuation.py: bez
    udzialow, bez transakcji z przyszlosci, bez cen ponizej 5 zl/m2.
    """
    od = od or dt.date(2023, 1, 1)
    rows = (
        session.execute(
            text(
                """
                SELECT przeznaczenie, pow_gruntu_m2, cena_grosze
                FROM rcn_transactions
                WHERE cena_grosze IS NOT NULL
                  AND pow_gruntu_m2 > 0
                  AND data_trans BETWEEN :od AND current_date
                  AND (udzial IS NULL OR udzial IN ('1', '1/1'))
                  AND cena_grosze / 100.0 / pow_gruntu_m2 >= 5.0
                """
            ),
            {"od": od},
        )
        .mappings()
        .all()
    )

    po_segmencie: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        segment = segments.classify(row["przeznaczenie"], None)
        po_segmencie.setdefault(segment, []).append(
            (float(row["pow_gruntu_m2"]), float(row["cena_grosze"]) / 100.0)
        )

    return po_segmencie


def beta1_per_segment(
    session: Session,
    *,
    min_obs: int = MIN_OBS_BETA1,
    od: dt.date | None = None,
    z_wezlami: bool = True,
    dane: dict[str, list[tuple[float, float]]] | None = None,
) -> dict[str, normalize_area.LogPriceCurve]:
    """Elastycznosc ceny wzgledem powierzchni, osobno w kazdym segmencie rynku.

    z_wezlami=False daje jedna liczbe na segment, porownywalna z literatura
    (0,80-0,90, sekcja 5.2.3). Wersja z wezlami jest dokladniejsza, ale jej
    elastycznosc rozni sie miedzy pasmami powierzchni i nie da sie jej zestawic
    z pojedyncza wartoscia z artykulu.
    """
    po_segmencie = dane if dane is not None else transakcje_per_segment(session, od=od)

    krzywe: dict[str, normalize_area.LogPriceCurve] = {}
    for segment, obserwacje in po_segmencie.items():
        if len(obserwacje) < min_obs:
            continue
        try:
            krzywe[segment] = normalize_area.estimate_curve(
                [a for a, _ in obserwacje],
                [c for _, c in obserwacje],
                knots_m2=normalize_area.DEFAULT_KNOTS_M2 if z_wezlami else None,
            )
        except normalize_area.NormalizationError as exc:
            log.warning("segment %s pominiety: %s", segment, exc)
    return krzywe


# --------------------------------------------------------- wrazliwosc wag


def wynik_przy_wagach(
    filary: dict[str, float | None],
    wagi: dict[str, float],
    *,
    mnoznik: float,
    coverage_min: float = pillars.COVERAGE_MIN,
) -> float | None:
    """Ten sam rachunek co pillars.combine, ale na zapisanych filarach.

    Analiza wrazliwosci nie moze przeliczac calego pipeline'u dla kazdej
    perturbacji, bo to setki zapytan do uslug publicznych. Filary sa juz
    policzone i zapisane w scores.pillar_scores, wiec wystarczy zmienic wagi.
    Zgodnosc tej funkcji z oryginalem sprawdza kontrola w wrazliwosc_wag:
    dla wag bazowych musi wyjsc dokladnie zapisany score.
    """
    dostepne = {k: v for k, v in filary.items() if v is not None and k in wagi}
    waga_dostepnych = sum(wagi[k] for k in dostepne)
    waga_wszystkich = sum(wagi.values())
    if not waga_wszystkich:
        return None
    coverage = waga_dostepnych / waga_wszystkich
    if coverage < coverage_min or not dostepne:
        return None
    surowy = sum(wagi[k] * v for k, v in dostepne.items()) / waga_dostepnych
    return round(surowy * mnoznik, 1)


def wrazliwosc_wag(
    session: Session,
    *,
    profil: pillars.Profil = "detaliczny",
    powtorzenia: int = 20,
    skala: float = 0.30,
    seed: int = 2026,
    top_n: int = 100,
) -> dict[str, Any]:
    """Perturbacja wag i stabilnosc top-N. Sekcja 5.6, walidacja bez etykiet."""
    rows = (
        session.execute(
            text(
                """
                SELECT listing_id, score_total, pillar_scores, gates
                FROM scores
                WHERE score_total IS NOT NULL AND pillar_scores IS NOT NULL
                """
            )
        )
        .mappings()
        .all()
    )
    if len(rows) < 10:
        return {"n": len(rows), "powod": "za malo ocenionych ofert do analizy wrazliwosci"}

    wagi_bazowe = pillars.WAGI[profil]
    filary = {int(r["listing_id"]): dict(r["pillar_scores"]) for r in rows}
    mnozniki = {int(r["listing_id"]): float((r["gates"] or {}).get("mnoznik", 1.0)) for r in rows}
    zapisane = {int(r["listing_id"]): float(r["score_total"]) for r in rows}

    bazowy = {
        listing_id: wynik
        for listing_id, punkty in filary.items()
        if (wynik := wynik_przy_wagach(punkty, dict(wagi_bazowe), mnoznik=mnozniki[listing_id]))
        is not None
    }
    niezgodne = [i for i, w in bazowy.items() if abs(w - zapisane[i]) > 0.15]

    # Czolowka wieksza niz cwierc zbioru nie sprawdza niczego: przy 101 ofertach
    # "top-100" zawsze pokryje sie w 100%, niezaleznie od wag.
    top_n_efektywny = min(top_n, max(5, len(bazowy) // 4))

    wyniki: list[calibration.StabilnoscRankingu] = []
    for i in range(powtorzenia):
        wagi = calibration.zaburz_wagi(wagi_bazowe, skala=skala, seed=seed + i)
        zaburzony = {
            listing_id: wynik
            for listing_id, punkty in filary.items()
            if (wynik := wynik_przy_wagach(punkty, wagi, mnoznik=mnozniki[listing_id])) is not None
        }
        wyniki.append(calibration.stabilnosc_rankingu(bazowy, zaburzony, top_n=top_n_efektywny))

    pokrycia = sorted(w.pokrycie_top for w in wyniki)
    rho = sorted(w.rho for w in wyniki)

    # Test wrazliwosci ma sens tylko wtedy, gdy jest co wazyc. Gdy w kazdej
    # ofercie dostepny jest ten sam podzbior filarow, wagi renormalizuja sie
    # identycznie i ranking nie ma jak sie rozjechac. To nie jest dowod
    # stabilnosci scoringu, tylko skutek brakujacych zrodel danych.
    dostepne_filary = {
        klucz
        for punkty in filary.values()
        for klucz, wartosc in punkty.items()
        if wartosc is not None and klucz in wagi_bazowe
    }
    wzorce = {
        tuple(sorted(k for k, v in punkty.items() if v is not None)) for punkty in filary.values()
    }

    return {
        "n": len(bazowy),
        "top_n": wyniki[0].top_n,
        "top_n_zadany": top_n,
        "powtorzenia": powtorzenia,
        "skala": skala,
        "seed": seed,
        "pokrycie_min": pokrycia[0],
        "pokrycie_mediana": pokrycia[len(pokrycia) // 2],
        "rho_min": rho[0],
        "rho_mediana": rho[len(rho) // 2],
        "stabilny": all(w.stabilny for w in wyniki),
        "filary_dostepne": sorted(dostepne_filary),
        "filary_wszystkie": sorted(wagi_bazowe),
        "wzorce_dostepnosci": len(wzorce),
        "miarodajny": len(dostepne_filary) == len(wagi_bazowe),
        "kontrola_rekonstrukcji": {
            "sprawdzone": len(bazowy),
            "niezgodne": len(niezgodne),
            "przyklady": niezgodne[:5],
        },
    }


# ------------------------------ wrazliwosc na wage pojedynczego filaru


SELECT_RANKING = text(
    """
    SELECT listing_id, score_total, pillar_scores, gates
    FROM scores
    WHERE score_total IS NOT NULL AND pillar_scores IS NOT NULL
    """
)


def ranking_przy_wagach(
    filary: Mapping[int, Mapping[str, float | None]],
    mnozniki: Mapping[int, float],
    wagi: Mapping[str, float],
) -> dict[int, float]:
    """Wynik kazdej oferty przy zadanym zestawie wag. Oferty bez wyniku wypadaja."""
    return {
        listing_id: wynik
        for listing_id, punkty in filary.items()
        if (wynik := wynik_przy_wagach(dict(punkty), dict(wagi), mnoznik=mnozniki[listing_id]))
        is not None
    }


def wrazliwosc_filarow(
    filary: Mapping[int, Mapping[str, float | None]],
    mnozniki: Mapping[int, float],
    *,
    wagi: Mapping[str, float],
    skala: float = calibration.WRAZLIWOSC_SKALA,
    top_n: int = calibration.WRAZLIWOSC_TOP_N,
    prog: int = calibration.MAX_ZMIANA_CZOLOWKI,
) -> dict[str, Any]:
    """Kryterium fazy 6: kazdemu filarowi po kolei +/-20% wagi i pomiar czolowki.

    Funkcja czysta, bez bazy: dostaje juz zebrane filary i mnozniki bramek.
    Dzieki temu da sie ja przetestowac na recznie policzonym przykladzie, a
    warstwa bazodanowa (analiza_wrazliwosci) tylko dostarcza dane.

    Filar, ktorego nie ma w ZADNEJ ofercie, jest raportowany osobno i nie liczy
    sie do werdyktu. Jego waga i tak wypada w renormalizacji, wiec przesuniecie
    zawsze wynosi zero - a zero, ktore bierze sie z braku danych, nie jest
    dowodem stabilnosci rankingu.
    """
    bazowy = ranking_przy_wagach(filary, mnozniki, wagi)
    if len(bazowy) < top_n:
        return {
            "n": len(bazowy),
            "powod": (
                f"za malo ocenionych ofert do analizy wrazliwosci: {len(bazowy)}, "
                f"potrzeba co najmniej {top_n}"
            ),
        }

    z_danymi = {
        klucz
        for punkty in filary.values()
        for klucz, wartosc in punkty.items()
        if wartosc is not None and klucz in wagi
    }

    pomiary: list[dict[str, Any]] = []
    for filar in wagi:
        for kierunek, czynnik in (("+", 1.0 + skala), ("-", 1.0 - skala)):
            zmienione = calibration.skaluj_wage(wagi, filar, czynnik)
            wynik = calibration.przesuniecie_rankingu(
                bazowy,
                ranking_przy_wagach(filary, mnozniki, zmienione),
                top_n=top_n,
                prog=prog,
            )
            pomiary.append(
                {
                    "filar": filar,
                    "kierunek": f"{kierunek}{skala:.0%}",
                    "waga_bazowa": round(wagi[filar], 4),
                    "waga_po": round(zmienione[filar], 4),
                    "ma_dane": filar in z_danymi,
                    **wynik.to_dict(),
                }
            )

    liczone = [p for p in pomiary if p["ma_dane"]]
    # Najgorszy przypadek wybieramy ta sama miara, ktora rozstrzyga werdykt,
    # czyli wymiana skladu. Przesuniecie w pozycjach jest tylko rozstrzygnieciem
    # remisu, zeby przy zerowej wymianie dalo sie wskazac cokolwiek sensownego.
    najgorszy = max(
        liczone,
        key=lambda p: (int(p["wymiana_czolowki"]), int(p["max_przesuniecie"])),
        default=None,
    )  # type: ignore[arg-type]

    # Czy ten pomiar w ogole moze cokolwiek wykryc. Kolejnosc w czolowce ustala
    # sie WYLACZNIE z tych filarow, ktore w czolowce przyjmuja rozne wartosci.
    # Gdy taki filar jest jeden, ranking jest jego posortowaniem i zaden dobor
    # wag go nie odwroci: wszystkie oferty przesuwaja sie o to samo. Zerowe
    # przesuniecie jest wtedy prawda o rachunku, a nie dowodem, ze wagi sa
    # dobrane dobrze - i tak trzeba je czytac.
    czolowka = sorted(bazowy, key=lambda i: (-bazowy[i], i))[: min(top_n, len(bazowy))]
    rozniace = sorted(
        klucz
        for klucz in wagi
        if len({filary[i].get(klucz) for i in czolowka if filary[i].get(klucz) is not None}) > 1
    )
    wyniki_czolowki = [bazowy[i] for i in czolowka]
    remisy = len(wyniki_czolowki) - len(set(wyniki_czolowki))

    return {
        "n": len(bazowy),
        "top_n": min(top_n, len(bazowy)),
        "skala": skala,
        "prog": prog,
        "filary_bez_danych": sorted(set(wagi) - z_danymi),
        "pomiary": pomiary,
        "max_przesuniecie": max((int(p["max_przesuniecie"]) for p in liczone), default=0),
        "max_wymiana_czolowki": max((int(p["wymiana_czolowki"]) for p in liczone), default=0),
        "najgorszy": (
            {"filar": najgorszy["filar"], "kierunek": najgorszy["kierunek"]} if najgorszy else None
        ),
        "spelnione": bool(liczone) and all(p["stabilny"] for p in liczone),
        "miarodajny": not set(wagi) - z_danymi,
        "filary_rozniacace_czolowke": rozniace,
        "remisy_w_czolowce": remisy,
        "rozstrzygajacy": len(rozniace) > 1,
    }


def analiza_wrazliwosci(
    session: Session,
    *,
    profil: pillars.Profil = "detaliczny",
    skala: float = calibration.WRAZLIWOSC_SKALA,
    top_n: int = calibration.WRAZLIWOSC_TOP_N,
    prog: int = calibration.MAX_ZMIANA_CZOLOWKI,
) -> dict[str, Any]:
    """To samo na danych z bazy. Filary sa juz policzone w scores.pillar_scores."""
    rows = session.execute(SELECT_RANKING).mappings().all()
    filary: dict[int, Mapping[str, float | None]] = {
        int(r["listing_id"]): dict(r["pillar_scores"]) for r in rows
    }
    mnozniki = {int(r["listing_id"]): float((r["gates"] or {}).get("mnoznik", 1.0)) for r in rows}

    wynik = wrazliwosc_filarow(
        filary,
        mnozniki,
        wagi=pillars.WAGI[profil],
        skala=skala,
        top_n=top_n,
        prog=prog,
    )
    wynik["profil"] = profil
    return wynik


# --------------------------------------------------------- dyskryminacja


def dyskryminacja(session: Session) -> calibration.Dyskryminacja | None:
    """Rozklad wynikow: czy scoring w ogole rozroznia dzialki."""
    wyniki = [
        float(w)
        for (w,) in session.execute(
            text("SELECT score_total FROM scores WHERE score_total IS NOT NULL")
        ).all()
    ]
    if len(wyniki) < 10:
        return None
    return calibration.dyskryminacja(wyniki)


# -------------------------------------------------------------- caly przebieg


def run(
    session: Session,
    *,
    limit: int = 500,
    profil: pillars.Profil = "detaliczny",
    top_n_wrazliwosc: int = calibration.WRAZLIWOSC_TOP_N,
) -> dict[str, Any]:
    """Wszystkie cztery pomiary i zapis do tabeli calibrations."""
    podsumowanie: dict[str, Any] = {}

    # 1. spread: najpierw pary, bo to wlasciwy pomiar. Szacunek zastepczy
    #    zapisujemy zawsze, zeby bylo widac, jak sie od par rozni, gdy pary beda.
    pary = spread_z_par(session)
    if pary is not None:
        zapisz(
            session,
            kind="spread",
            wartosc=pary.mediana,
            n_obs=pary.n,
            zrodlo="pary",
            szczegoly=pary.to_dict(),
        )
    podsumowanie["spread_pary"] = pary.to_dict() if pary else None

    spready = spread_z_ofert(session, limit=limit)
    for segment, spread in spready.items():
        zapisz(
            session,
            kind="spread",
            segment=segment or None,
            wartosc=spread.mediana,
            n_obs=spread.n,
            zrodlo=spread.zrodlo,
            szczegoly=spread.to_dict(),
        )
    podsumowanie["spread_oferty"] = {k or "(globalny)": v.to_dict() for k, v in spready.items()}

    # 2. beta1 per segment. Zapisujemy wartosc ze stalej elastycznosci, bo to
    #    ona jest porownywalna z 0,80-0,90 z literatury, a lamana ze wszystkimi
    #    wspolczynnikami idzie do szczegolow.
    obserwacje = transakcje_per_segment(session)
    stale = beta1_per_segment(session, z_wezlami=False, dane=obserwacje)
    lamane = beta1_per_segment(session, z_wezlami=True, dane=obserwacje)
    for segment, krzywa in stale.items():
        lamana = lamane.get(segment)
        zapisz(
            session,
            kind="beta1",
            segment=segment,
            wartosc=krzywa.slope0,
            n_obs=krzywa.n_obs,
            zrodlo="rcn",
            szczegoly={
                "r2_stala": krzywa.r2,
                "lamana": (
                    {
                        "slope0": lamana.slope0,
                        "deltas": list(lamana.deltas),
                        "knots_m2": list(lamana.knots_m2),
                        "r2": lamana.r2,
                        "beta_500": lamana.beta_at(500.0),
                        "beta_1500": lamana.beta_at(1500.0),
                        "beta_5000": lamana.beta_at(5000.0),
                    }
                    if lamana
                    else None
                ),
            },
        )
    podsumowanie["beta1"] = {segment: round(k.slope0, 3) for segment, k in stale.items()}

    # 3. wrazliwosc wag
    wrazliwosc = wrazliwosc_wag(session, profil=profil)
    if "pokrycie_mediana" in wrazliwosc:
        zapisz(
            session,
            kind="wagi",
            segment=profil,
            wartosc=wrazliwosc["pokrycie_mediana"],
            n_obs=int(wrazliwosc["n"]),
            zrodlo="perturbacja",
            szczegoly=wrazliwosc,
        )
    podsumowanie["wagi"] = wrazliwosc

    # 3b. wrazliwosc na wage pojedynczego filaru: kryterium akceptacji fazy 6.
    #     Zapisujemy najwieksze przesuniecie czolowki, bo to ta liczba jest
    #     porownywana z progiem 3 pozycji.
    per_filar = analiza_wrazliwosci(session, profil=profil, top_n=top_n_wrazliwosc)
    if "pomiary" in per_filar:
        zapisz(
            session,
            kind="wrazliwosc",
            segment=profil,
            wartosc=float(per_filar["max_przesuniecie"]),
            n_obs=int(per_filar["n"]),
            zrodlo="filar_pm20",
            szczegoly=per_filar,
        )
    podsumowanie["wrazliwosc"] = per_filar

    # 4. dyskryminacja
    rozklad = dyskryminacja(session)
    if rozklad is not None:
        zapisz(
            session,
            kind="dyskryminacja",
            wartosc=rozklad.udzial_najliczniejszego,
            n_obs=rozklad.n,
            zrodlo="scores",
            szczegoly={
                "przedzialy": list(rozklad.przedzialy),
                "najliczniejszy": list(rozklad.przedzial_najliczniejszy),
                "iqr": rozklad.rozstep_miedzykwartylowy,
                "odchylenie": rozklad.odchylenie,
                "rozroznia": rozklad.rozroznia,
                **rozklad.szczegoly,
            },
        )
    podsumowanie["dyskryminacja"] = (
        {
            "n": rozklad.n,
            "udzial_najliczniejszego": round(rozklad.udzial_najliczniejszego, 3),
            "przedzial": list(rozklad.przedzial_najliczniejszy),
            "rozroznia": rozklad.rozroznia,
        }
        if rozklad
        else None
    )
    return podsumowanie
