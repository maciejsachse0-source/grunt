"""POST /api/valuate: wycena dowolnej dzialki, takze bez oferty (sekcja 20 dokumentu).

Ten endpoint jest wazniejszy, niz wyglada: sprawia, ze system ma wartosc od fazy 1,
zanim powstanie jakikolwiek scraper. Wklejasz numer dzialki albo wspolrzedne,
dostajesz wycene z przedzialem i lista porownywalnych transakcji.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from grunt.config import settings
from grunt.db import get_db
from grunt.scoring import segments, valuation
from grunt.sources import rcn_query, uldk
from grunt.sources.uldk import UldkClient

router = APIRouter()

# Ponizej tego progu transakcje w RCN to regulacje stanu prawnego i przekazania
# nominalne, nie obrot rynkowy. Szczegoly w scripts/eval_valuation.py.
MIN_MARKET_PRICE_M2 = 5.0


class ValuateRequest(BaseModel):
    uldk_id: str | None = Field(default=None, description="Numer dzialki, np. 226101_1.0089.433/2")
    lat: float | None = Field(default=None, description="Szerokosc geograficzna WGS84")
    lon: float | None = Field(default=None, description="Dlugosc geograficzna WGS84")
    area_m2: int | None = Field(
        default=None, description="Powierzchnia. Bez niej bierzemy powierzchnie geometrii z ULDK"
    )
    price_pln: int | None = Field(
        default=None, description="Cena ofertowa. Podana, zwracamy takze deal score"
    )
    przeznaczenie: str | None = Field(
        default=None,
        description=(
            "Przeznaczenie w MPZP, np. budownictwoMieszkanioweJednorodzinne. "
            "Decyduje o segmencie rynku, czyli o tym, do czego dzialka jest porownywana. "
            "Do czasu zbudowania modulu MPZP (faza 3) podaje sie je recznie"
        ),
    )
    sposob_uzyt: str | None = Field(
        default=None, description="Klasyfikacja ewidencyjna, np. gruntyRolne"
    )
    months_back: int = Field(default=36, ge=6, le=240)
    confidence: float = Field(default=0.80)
    model: str = Field(default="knn", description="knn (Model 2) albo median (Model 1)")

    @model_validator(mode="after")
    def _wymagaj_lokalizacji(self) -> ValuateRequest:
        if not self.uldk_id and (self.lat is None or self.lon is None):
            raise ValueError("podaj uldk_id albo pare lat i lon")
        return self


@router.post("/valuate")
def valuate(request: ValuateRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    client = UldkClient(session=session)

    try:
        parcel = (
            client.by_id(request.uldk_id)
            if request.uldk_id
            else client.by_latlon(request.lat, request.lon)  # type: ignore[arg-type]
        )
    except uldk.UldkError as exc:
        raise HTTPException(status_code=502, detail=f"ULDK: {exc}") from exc

    if parcel is None:
        raise HTTPException(status_code=404, detail="ULDK nie zna dzialki w tym miejscu")

    area = request.area_m2 or _area_from_wkt(parcel.geom_wkt)
    if not area:
        raise HTTPException(
            status_code=422,
            detail="brak powierzchni: ULDK nie zwrocil geometrii, podaj area_m2",
        )

    obreb, gmina, powiat, woj = rcn_query.teryt_from_uldk_id(parcel.uldk_id)
    as_of = dt.date.today()
    since = as_of - dt.timedelta(days=30 * request.months_back)
    target = segments.classify(request.przeznaczenie, request.sposob_uzyt)

    comparables = rcn_query.fetch_comparables(
        session,
        rcn_query.ComparableQuery(
            teryt_obreb=obreb,
            teryt_gmina=gmina,
            teryt_powiat=powiat,
            teryt_woj=woj,
            since=since,
            area_m2=float(area),
        ),
        as_of=as_of,
    )
    comparables = rcn_query.exclude_transaction(comparables, parcel.uldk_id)
    comparables = [c for c in comparables if c.price_per_m2 >= MIN_MARKET_PRICE_M2]

    if not comparables:
        raise HTTPException(
            status_code=404,
            detail=(
                "brak transakcji porownywalnych w bazie dla tego regionu. "
                "Uruchom import RCN dla wlasciwego wojewodztwa"
            ),
        )

    selected, used_segments = segments.select_by_segment(
        comparables, target, segment_of=lambda c: c.segment, level_of=lambda c: c.level
    )

    try:
        result = valuation.valuate_median_shrinkage(
            float(area),
            selected,
            as_of=as_of,
            confidence=request.confidence,
            segments_used=used_segments,
        )
    except valuation.ValuationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Model 2 wymaga geometrii dzialki. Gdy ULDK jej nie zwrocil albo w promieniu
    # nie ma transakcji, zostaje wynik Modelu 1 - dlatego Model 1 liczymy zawsze.
    _, wkt = uldk.strip_srid(parcel.geom_wkt)
    if request.model == "knn" and wkt:
        neighbours = rcn_query.fetch_spatial_comparables(
            session,
            wkt,
            teryt_obreb=obreb,
            teryt_gmina=gmina,
            teryt_powiat=powiat,
            as_of=as_of,
            since=since,
            area_m2=float(area),
            cena_min=MIN_MARKET_PRICE_M2,
        )
        neighbours = rcn_query.exclude_transaction(neighbours, parcel.uldk_id)
        if neighbours:
            knn_selected, knn_segments = segments.select_by_segment(
                neighbours, target, segment_of=lambda c: c.segment, level_of=lambda c: c.level
            )
            with contextlib.suppress(valuation.ValuationError):
                result = valuation.valuate_se_knn(
                    float(area),
                    knn_selected,
                    as_of=as_of,
                    confidence=request.confidence,
                    segments_used=knn_segments,
                    target_segment=target,
                )

    payload: dict[str, Any] = {
        "dzialka": {
            "uldk_id": parcel.uldk_id,
            "wojewodztwo": parcel.wojewodztwo,
            "powiat": parcel.powiat,
            "gmina": parcel.gmina,
            "obreb": parcel.obreb,
            "numer": parcel.numer,
            "powierzchnia_m2": area,
            "powierzchnia_zrodlo": "podana" if request.area_m2 else "geometria ULDK",
        },
        "wycena": result.to_dict(),
        "segment": target,
        "model": settings.scoring_model_version,
    }

    if request.price_pln:
        deal = valuation.deal_score(request.price_pln * 100, result)
        payload["deal_score"] = round(deal, 3)
        payload["ocena_ceny"] = _opisz_deal(deal)

    return payload


def _area_from_wkt(geom_wkt: str | None) -> int | None:
    """Powierzchnia z geometrii ULDK. W EPSG:2180 wychodzi wprost w metrach."""
    _, wkt = uldk.strip_srid(geom_wkt)
    if not wkt:
        return None
    from shapely import wkt as shapely_wkt

    try:
        return int(round(shapely_wkt.loads(wkt).area))
    except Exception:  # geometria z ULDK bywa uszkodzona, to nie powod do bledu 500
        return None


def _opisz_deal(deal: float) -> str:
    """Progi z sekcji 5.4."""
    if deal > 2.5:
        return "wyraznie ponizej wyceny (wymaga weryfikacji, czy tanio nie ma powodu)"
    if deal > 1.5:
        return "potencjalna okazja"
    if deal < -1.5:
        return "przeszacowana"
    return "cena w granicach wyceny"
