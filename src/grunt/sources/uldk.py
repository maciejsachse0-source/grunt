"""Klient ULDK (GUGiK): jedyny most miedzy wspolrzedna z ogloszenia a numerem dzialki.

To najwazniejsza operacja calego systemu: wspolrzedne z oferty -> GetParcelByXY ->
idDzialki -> join z RCN. Bez tego warstwa ofertowa i fundamentowa nie stykaja sie.

Format odpowiedzi (zweryfikowany na zywo 2026-08-21):
    linia 0: "0" gdy znaleziono, "-1 brak wyników" gdy nie
    linia 1: pola rozdzielone znakiem "|", w kolejnosci podanej w parametrze result
    geom_wkt przychodzi jako "SRID=2180;POLYGON((...))"

Usluga odpowiada w ok. 0,8 s, wiec kazde zapytanie laduje w cache w bazie
(tabela uldk_cache), lacznie z odpowiedziami negatywnymi.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from grunt.models import UldkCache
from grunt.sources import _http, geo

ULDK_URL = "https://uldk.gugik.gov.pl/"

# Kolejnosc pol jest kontraktem: ULDK zwraca dokladnie to, o co poprosimy w result.
DEFAULT_RESULT_FIELDS = (
    "id",
    "voivodeship",
    "county",
    "commune",
    "region",
    "parcel",
    "geom_wkt",
)


class UldkError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Parcel:
    """Dzialka ewidencyjna zwrocona przez ULDK."""

    uldk_id: str
    wojewodztwo: str | None
    powiat: str | None
    gmina: str | None
    obreb: str | None
    numer: str | None
    geom_wkt: str | None

    @property
    def teryt_gmina(self) -> str | None:
        """Pierwszy czlon identyfikatora ULDK to TERYT gminy z cyfra rodzaju, np. 226101_1."""
        head = self.uldk_id.split(".", 1)[0]
        digits = head.replace("_", "")
        return digits[:7] if len(digits) >= 7 else None

    @property
    def teryt_obreb(self) -> str | None:
        parts = self.uldk_id.split(".")
        return parts[1] if len(parts) >= 2 else None

    def to_payload(self) -> dict[str, Any]:
        return {
            "uldk_id": self.uldk_id,
            "wojewodztwo": self.wojewodztwo,
            "powiat": self.powiat,
            "gmina": self.gmina,
            "obreb": self.obreb,
            "numer": self.numer,
        }


def parse_response(text: str, fields: tuple[str, ...] = DEFAULT_RESULT_FIELDS) -> Parcel | None:
    """Rozbior surowej odpowiedzi ULDK. Funkcja czysta, testowana na fixture'ach."""
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines:
        raise UldkError("pusta odpowiedz ULDK")

    # Pierwsza linia to status, ale jego znaczenie zalezy od zapytania:
    #   GetParcelByXY      zwraca "0" przy powodzeniu
    #   GetParcelByIdOrNr  zwraca LICZBE znalezionych obiektow ("1", "2", ...)
    #   oba zwracaja "-1 brak wynikow", gdy nie ma nic
    # Sprawdzone na zywo 2026-08-21. Traktowanie "1" jako bledu kosztowalo
    # jedno bledne 502 z endpointu wyceny.
    status = lines[0]
    try:
        code = int(status.split()[0])
    except (ValueError, IndexError) as exc:
        raise UldkError(f"nieznany status ULDK: {status!r}") from exc
    if code < 0:
        return None
    if len(lines) < 2:
        raise UldkError(f"status {code}, ale brak linii z danymi")

    values = lines[1].split("|")
    if len(values) < len(fields):
        raise UldkError(f"oczekiwano {len(fields)} pol, dostano {len(values)}")

    data = dict(zip(fields, (v.strip() for v in values), strict=False))
    uldk_id = data.get("id")
    if not uldk_id:
        raise UldkError("odpowiedz bez identyfikatora dzialki")

    return Parcel(
        uldk_id=uldk_id,
        wojewodztwo=data.get("voivodeship") or None,
        powiat=data.get("county") or None,
        gmina=data.get("commune") or None,
        obreb=data.get("region") or None,
        numer=data.get("parcel") or None,
        geom_wkt=data.get("geom_wkt") or None,
    )


def strip_srid(wkt: str | None) -> tuple[int | None, str | None]:
    """'SRID=2180;POLYGON((...))' -> (2180, 'POLYGON((...))')."""
    if not wkt:
        return (None, None)
    if wkt.upper().startswith("SRID="):
        head, _, geometry = wkt.partition(";")
        try:
            return (int(head[5:]), geometry)
        except ValueError:
            return (None, geometry)
    return (None, wkt)


class UldkClient:
    """Cache w bazie jest opcjonalny: bez sesji klient dziala, tylko wolniej."""

    def __init__(self, session: Session | None = None, *, delay: float = 0.5) -> None:
        self.session = session
        self.delay = delay

    # ------------------------------------------------------------ zapytania

    def by_xy(self, point: geo.PL1992) -> Parcel | None:
        key = geo.uldk_xy(point)
        return self._query("xy", key, {"request": "GetParcelByXY", "xy": key})

    def by_latlon(self, lat: float, lon: float) -> Parcel | None:
        """Wygodne wejscie dla ofert, ktore podaja WGS84. Cache trzyma klucz w 2180."""
        return self.by_xy(geo.wgs84_to_pl1992(lat, lon))

    def by_id(self, uldk_id: str) -> Parcel | None:
        return self._query("id", uldk_id, {"request": "GetParcelByIdOrNr", "id": uldk_id})

    # -------------------------------------------------------------- wnetrze

    def _query(self, kind: str, key: str, params: dict[str, str]) -> Parcel | None:
        cached = self._from_cache(kind, key)
        if cached is not None:
            return cached.parcel

        params = {**params, "result": ",".join(DEFAULT_RESULT_FIELDS)}
        try:
            response = _http.get(ULDK_URL, params=params, delay=self.delay)
        except httpx.HTTPError as exc:
            raise UldkError(f"ULDK niedostepny: {exc}") from exc

        parcel = parse_response(response.text)
        self._to_cache(kind, key, parcel)
        return parcel

    @dataclass(frozen=True, slots=True)
    class _CacheHit:
        parcel: Parcel | None

    def _from_cache(self, kind: str, key: str) -> _CacheHit | None:
        if self.session is None:
            return None
        row = self.session.execute(
            select(UldkCache).where(UldkCache.query_kind == kind, UldkCache.query_key == key)
        ).scalar_one_or_none()
        if row is None:
            return None
        if not row.found:
            return self._CacheHit(None)
        payload = row.payload or {}
        return self._CacheHit(
            Parcel(
                uldk_id=row.uldk_id or "",
                wojewodztwo=payload.get("wojewodztwo"),
                powiat=payload.get("powiat"),
                gmina=payload.get("gmina"),
                obreb=payload.get("obreb"),
                numer=payload.get("numer"),
                geom_wkt=payload.get("geom_wkt"),
            )
        )

    def _to_cache(self, kind: str, key: str, parcel: Parcel | None) -> None:
        if self.session is None:
            return
        from sqlalchemy.dialects.postgresql import insert

        payload: dict[str, Any] = {}
        if parcel is not None:
            payload = parcel.to_payload()
            payload["geom_wkt"] = parcel.geom_wkt

        stmt = (
            insert(UldkCache)
            .values(
                query_kind=kind,
                query_key=key,
                uldk_id=parcel.uldk_id if parcel else None,
                payload=payload or None,
                found=parcel is not None,
            )
            .on_conflict_do_nothing(index_elements=["query_kind", "query_key"])
        )
        self.session.execute(stmt)
        self.session.commit()
