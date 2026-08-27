"""Wzbogacanie ofert danymi publicznymi. Kolejnosc z sekcji 6 dokumentu.

    wspolrzedne oferty
        -> dzialki ewidencyjne w promieniu (EGiB)  -> dopasowanie i geometria
        -> plan ogolny i OUZ                        -> filar 1
        -> strefy powodziowe                        -> filar 5
        -> wysokosc i spadek                        -> filar 4
        -> uzbrojenie i koszt doprowadzenia         -> filar 3

CO LICZYMY DLA PUNKTU, A CO DLA DZIALKI

Wspolrzedne z portali sa przyblizone (pomiar w match_parcel.py), wiec dzielimy
cechy na dwie klasy:

  dla punktu   plan ogolny, OUZ, powodz, wysokosc, spadek, uzbrojenie
               Te warstwy sa wieksze niz dzialka, wiec bledy rzedu 100 m
               nie zmieniaja wyniku.

  dla dzialki  front, smuklosc, zwartosc, azymut
               Te wymagaja pewnego dopasowania. Gdy go nie ma, zostaja puste
               i obnizaja coverage, zamiast byc zmyslone.

Koszt jednej oferty: ok. 20 zapytan HTTP (1 EGiB, 3 plan ogolny, 4 ISOK,
8 KIUT, 9 NMT), czyli przy 0,5 s odstepu ok. 12 sekund. Przy 700 ofertach
to ponad dwie godziny, dlatego wzbogacanie ma limity i kolejkuje sie
przyrostowo.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.enrich import geometry, match_parcel, parcel_store
from grunt.scoring import planning
from grunt.sources import egib, geo, isok, kiut, nmt, plan_ogolny
from grunt.sources import mpzp as mpzp_zrodlo

log = logging.getLogger(__name__)

# Wagi zrodel przy liczeniu kompletnosci. Odpowiadaja wagom filarow z sekcji
# 5.3.2, bo brak danych planistycznych boli bardziej niz brak spadku terenu.
WAGI_ZRODEL: dict[str, float] = {
    "planistyka": 0.35,
    "uzbrojenie": 0.18,
    "teren": 0.10,
    "powodz": 0.10,
    "dzialka": 0.10,
}


@dataclass
class EnrichmentResult:
    listing_id: int
    zrodla_ok: list[str] = field(default_factory=list)
    zrodla_bledy: list[str] = field(default_factory=list)
    # Udzial zrodla w kompletnosci: 1,0 gdy dostarczylo komplet, mniej gdy tylko
    # czesc. Bez tego oferta z samym frontem z ogloszenia mialaby taka sama
    # kompletnosc jak oferta z pewnie dopasowana dzialka i pelna geometria.
    udzialy: dict[str, float] = field(default_factory=dict)
    plan: plan_ogolny.PlanOgolnyInfo | None = None
    mpzp: mpzp_zrodlo.MpzpInfo | None = None
    ocena_planistyczna: planning.PlanningAssessment | None = None
    powodz: isok.FloodRisk | None = None
    teren: nmt.Terrain | None = None
    media: kiut.Utilities | None = None
    dopasowanie: match_parcel.MatchResult | None = None
    ksztalt: geometry.ParcelShape | None = None

    @property
    def coverage(self) -> float:
        """Udzial wagi zrodel, ktore odpowiedzialy, w wadze wszystkich.

        Sekcja 5.3.9: kompletnosc pokazujemy osobno i jawnie, a ponizej 40%
        nie pokazujemy wyniku wcale.
        """
        zebrane = sum(
            WAGI_ZRODEL[z] * self.udzialy.get(z, 1.0) for z in self.zrodla_ok if z in WAGI_ZRODEL
        )
        return round(zebrane / sum(WAGI_ZRODEL.values()), 3)

    def to_features(self) -> dict[str, Any]:
        return {
            "planistyka": self.plan.to_dict() if self.plan else None,
            "mpzp": (
                {
                    "objeta": self.mpzp.objeta_mpzp,
                    "akt": self.mpzp.akt.tytul if self.mpzp.akt else None,
                    "obowiazuje_od": (
                        self.mpzp.akt.obowiazuje_od.isoformat()
                        if self.mpzp.akt and self.mpzp.akt.obowiazuje_od
                        else None
                    ),
                    "teryt_gmina": self.mpzp.akt.teryt_gmina if self.mpzp.akt else None,
                    "zrodlo": self.mpzp.zrodlo,
                    "uwaga": self.mpzp.uwaga,
                }
                if self.mpzp
                else None
            ),
            "ocena_planistyczna": (
                self.ocena_planistyczna.to_dict() if self.ocena_planistyczna else None
            ),
            "powodz": self.powodz.to_dict() if self.powodz else None,
            "teren": self.teren.to_dict() if self.teren else None,
            "media": self.media.to_dict() if self.media else None,
            "dzialka": self.dopasowanie.to_dict() if self.dopasowanie else None,
            "ksztalt": self.ksztalt.to_dict() if self.ksztalt else None,
        }


UPSERT = text(
    """
    INSERT INTO listing_enrichment (
        listing_id, enriched_at, zrodla_ok, zrodla_bledy,
        plan_status, plan_strefa, plan_w_ouz, plan_akt, mpzp_symbol,
        strefy_powodziowe, wysokosc_npm, spadek_proc,
        front_m, front_zrodlo, smuklosc, zwartosc,
        media, media_koszt_pln,
        parcel_uldk_id, parcel_match, parcel_area_m2,
        coverage, features
    ) VALUES (
        :listing_id, now(), :zrodla_ok, :zrodla_bledy,
        :plan_status, :plan_strefa, :plan_w_ouz, :plan_akt, :mpzp_symbol,
        :strefy_powodziowe, :wysokosc_npm, :spadek_proc,
        :front_m, :front_zrodlo, :smuklosc, :zwartosc,
        CAST(:media AS jsonb), :media_koszt_pln,
        :parcel_uldk_id, :parcel_match, :parcel_area_m2,
        :coverage, CAST(:features AS jsonb)
    )
    ON CONFLICT (listing_id) DO UPDATE SET
        enriched_at = now(),
        zrodla_ok = EXCLUDED.zrodla_ok,
        zrodla_bledy = EXCLUDED.zrodla_bledy,
        plan_status = EXCLUDED.plan_status,
        plan_strefa = EXCLUDED.plan_strefa,
        plan_w_ouz = EXCLUDED.plan_w_ouz,
        plan_akt = EXCLUDED.plan_akt,
        mpzp_symbol = EXCLUDED.mpzp_symbol,
        strefy_powodziowe = EXCLUDED.strefy_powodziowe,
        wysokosc_npm = EXCLUDED.wysokosc_npm,
        spadek_proc = EXCLUDED.spadek_proc,
        front_m = EXCLUDED.front_m,
        front_zrodlo = EXCLUDED.front_zrodlo,
        smuklosc = EXCLUDED.smuklosc,
        zwartosc = EXCLUDED.zwartosc,
        media = EXCLUDED.media,
        media_koszt_pln = EXCLUDED.media_koszt_pln,
        parcel_uldk_id = EXCLUDED.parcel_uldk_id,
        parcel_match = EXCLUDED.parcel_match,
        parcel_area_m2 = EXCLUDED.parcel_area_m2,
        coverage = EXCLUDED.coverage,
        features = EXCLUDED.features
    """
)

SELECT_DO_WZBOGACENIA = text(
    """
    SELECT l.id, ST_X(l.geom) AS e, ST_Y(l.geom) AS n, l.area_m2,
           l.przeznaczenie_raw, l.raw_jsonb
    FROM listings l
    LEFT JOIN listing_enrichment le ON le.listing_id = l.id
    WHERE l.geom IS NOT NULL
      AND l.is_active
      AND (le.listing_id IS NULL OR le.enriched_at < now() - make_interval(days => :max_wiek))
    ORDER BY l.first_seen_at DESC
    LIMIT :limit
    """
)


def enrich_point(
    listing_id: int,
    point: geo.PL1992,
    *,
    declared_area_m2: float | None = None,
    front_z_ogloszenia_m: float | None = None,
    mpzp_symbol: str | None = None,
    delay: float = 0.5,
) -> EnrichmentResult:
    """Wzbogacenie jednej oferty. Kazde zrodlo osobno, bledy nie zatrzymuja reszty."""
    wynik = EnrichmentResult(listing_id=listing_id)

    # 1. dzialka ewidencyjna i ksztalt
    try:
        kandydaci = egib.parcels_around(point, radius_m=150, delay=delay)
        dopasowanie = match_parcel.choose_parcel(
            kandydaci,
            point_easting=point.easting,
            point_northing=point.northing,
            declared_area_m2=declared_area_m2,
        )
        wynik.dopasowanie = dopasowanie
        if dopasowanie.usable_for_features and dopasowanie.parcel:
            wynik.ksztalt = geometry.from_wkt(
                dopasowanie.parcel.geom_wkt, front_z_ogloszenia_m=front_z_ogloszenia_m
            )
            wynik.zrodla_ok.append("dzialka")
        else:
            # Bez pewnego dopasowania zostaje tylko to, co podal portal
            wynik.ksztalt = geometry.from_wkt(None, front_z_ogloszenia_m=front_z_ogloszenia_m)
            if front_z_ogloszenia_m:
                # Sam front z ogloszenia to jedna cecha z pieciu, nie caly filar
                wynik.zrodla_ok.append("dzialka")
                wynik.udzialy["dzialka"] = 0.4
    except Exception as exc:
        wynik.zrodla_bledy.append(f"egib: {exc}")

    # 2a. MPZP z Rejestru Urbanistycznego. Osobno od planu ogolnego, bo to inna
    # usluga i jej awaria nie moze zabrac nam stanu planistycznego z GUGiK.
    try:
        wynik.mpzp = mpzp_zrodlo.sprawdz_punkt(point, timeout=60.0)
    except Exception as exc:
        wynik.zrodla_bledy.append(f"mpzp: {exc}")

    # 2b. planistyka
    try:
        plan = plan_ogolny.query(point, delay=delay)
        wynik.plan = plan
        wynik.ocena_planistyczna = planning.assess(
            planning.PlanningInputs(
                mpzp_symbol=mpzp_symbol,
                objeta_mpzp=wynik.mpzp.objeta_mpzp if wynik.mpzp else None,
                ma_plan_ogolny=plan.ma_plan,
                strefa_symbol=plan.strefa_symbol,
                w_ouz=plan.w_ouz,
            )
        )
        wynik.zrodla_ok.append("planistyka")
    except Exception as exc:
        wynik.zrodla_bledy.append(f"plan_ogolny: {exc}")

    # 3. powodz
    try:
        wynik.powodz = isok.query(point, delay=delay)
        if wynik.powodz.kompletne:
            wynik.zrodla_ok.append("powodz")
    except Exception as exc:
        wynik.zrodla_bledy.append(f"isok: {exc}")

    # 4. teren
    try:
        wynik.teren = nmt.terrain(point, delay=delay)
        if wynik.teren.wysokosc_npm is not None:
            wynik.zrodla_ok.append("teren")
    except Exception as exc:
        wynik.zrodla_bledy.append(f"nmt: {exc}")

    # 5. uzbrojenie
    try:
        wynik.media = kiut.query(point, delay=delay)
        if wynik.media.w_zasiegu_uslugi:
            wynik.zrodla_ok.append("uzbrojenie")
    except Exception as exc:
        wynik.zrodla_bledy.append(f"kiut: {exc}")

    return wynik


def save(session: Session, wynik: EnrichmentResult) -> None:
    plan = wynik.plan
    ocena = wynik.ocena_planistyczna
    ksztalt = wynik.ksztalt
    dop = wynik.dopasowanie

    session.execute(
        UPSERT,
        {
            "listing_id": wynik.listing_id,
            "zrodla_ok": wynik.zrodla_ok,
            "zrodla_bledy": wynik.zrodla_bledy[:5],
            "plan_status": ocena.status if ocena else None,
            "plan_strefa": plan.strefa_symbol if plan else None,
            "plan_w_ouz": plan.w_ouz if plan else None,
            "plan_akt": plan.akt_tytul if plan else None,
            "mpzp_symbol": None,
            "strefy_powodziowe": list(wynik.powodz.strefy) if wynik.powodz else None,
            "wysokosc_npm": wynik.teren.wysokosc_npm if wynik.teren else None,
            "spadek_proc": wynik.teren.spadek_proc if wynik.teren else None,
            "front_m": ksztalt.front_m if ksztalt else None,
            "front_zrodlo": ksztalt.front_zrodlo if ksztalt else None,
            "smuklosc": ksztalt.smuklosc if ksztalt else None,
            "zwartosc": ksztalt.zwartosc if ksztalt else None,
            "media": json.dumps(wynik.media.to_dict(), ensure_ascii=False) if wynik.media else None,
            "media_koszt_pln": wynik.media.koszt_pln() if wynik.media else None,
            "parcel_uldk_id": dop.parcel.id_dzialki if dop and dop.parcel else None,
            "parcel_match": dop.confidence if dop else None,
            "parcel_area_m2": (
                int(dop.parcel.area_m2) if dop and dop.parcel and dop.parcel.area_m2 else None
            ),
            "coverage": wynik.coverage,
            "features": json.dumps(wynik.to_features(), ensure_ascii=False, default=str),
        },
    )

    # Geometria dzialki idzie do parcels, zeby mapa miala co narysowac po
    # kliknieciu oferty. Sam poziom pewnosci zostaje wyzej, w parcel_match.
    parcel_id = None
    if dop and dop.parcel and dop.parcel.geom_wkt:
        parcel_id = parcel_store.upsert(
            session,
            uldk_id=dop.parcel.id_dzialki,
            geom_wkt=dop.parcel.geom_wkt,
            area_ewid_m2=int(dop.parcel.area_m2) if dop.parcel.area_m2 else None,
            teryt_gmina=dop.parcel.teryt_gmina,
            teryt_obreb=dop.parcel.teryt_obreb,
        )
    parcel_store.link(session, listing_id=wynik.listing_id, parcel_id=parcel_id)


def run(
    session: Session,
    *,
    limit: int = 20,
    max_wiek_dni: int = 30,
    delay: float = 0.5,
    progress: Any = None,
) -> dict[str, Any]:
    """Wzbogacenie kolejnych ofert bez wzbogacenia albo z przestarzalym."""
    rows = (
        session.execute(SELECT_DO_WZBOGACENIA, {"limit": limit, "max_wiek": max_wiek_dni})
        .mappings()
        .all()
    )

    statystyki: dict[str, Any] = {
        "przetworzone": 0,
        "bledy": 0,
        "coverage_suma": 0.0,
        "start": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }

    for row in rows:
        punkt = geo.PL1992(easting=float(row["e"]), northing=float(row["n"]))
        raw = row["raw_jsonb"] or {}
        front = raw.get("front_m") if isinstance(raw, dict) else None

        try:
            wynik = enrich_point(
                int(row["id"]),
                punkt,
                declared_area_m2=float(row["area_m2"]) if row["area_m2"] else None,
                front_z_ogloszenia_m=float(front) if front else None,
                mpzp_symbol=None,
                delay=delay,
            )
        except Exception as exc:
            log.exception("wzbogacanie oferty %s nie powiodlo sie", row["id"])
            statystyki["bledy"] += 1
            if progress:
                progress(f"oferta {row['id']}: blad {exc}")
            continue

        save(session, wynik)
        session.commit()
        statystyki["przetworzone"] += 1
        statystyki["coverage_suma"] += wynik.coverage
        if progress:
            status = wynik.ocena_planistyczna.status if wynik.ocena_planistyczna else "?"
            progress(
                f"oferta {row['id']}: status {status}, coverage {wynik.coverage:.0%}, "
                f"zrodla {len(wynik.zrodla_ok)}/5"
            )

    if statystyki["przetworzone"]:
        statystyki["coverage_sredni"] = round(
            statystyki["coverage_suma"] / statystyki["przetworzone"], 3
        )
    return statystyki
