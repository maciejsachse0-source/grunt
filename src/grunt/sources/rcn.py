"""Rejestr Cen Nieruchomosci: fundament calego projektu.

RCN jest bezplatny od 13.02.2026 i daje to, czego nie ma zaden portal: realna cene
transakcyjna z aktu notarialnego razem z geometria dzialki, jej numerem ewidencyjnym
i przeznaczeniem w MPZP. Na tym uczy sie warstwa A (wycena).

Zrodlo: WFS https://mapy.geoportal.gov.pl/wss/service/rcn, typename ms:dzialki.
Zweryfikowane na zywo 2026-08-21.

DWIE PULAPKI, obie kosztowne:

1. KOLEJNOSC OSI. gml:posList przychodzi jako "northing easting", bo srsName jest
   podany w formie urn (urn:ogc:def:crs:EPSG::2180), a ta wymusza kolejnosc osi
   z definicji ukladu. My przechowujemy geometrie jako (easting, northing),
   czyli kazda pare trzeba odwrocic. Bez tego cala Polska laduje w Rosji.

2. WOLUMEN. Warstwa zawiera wszystkie transakcje, takze budynkowe i lokalowe.
   Bbox 12x12 km wokol Gdanska to 328 744 rekordy. Po odfiltrowaniu
   nier_rodzaj=nieruchomoscGruntowaNiezabudowana i daty od 2024 zostaje ok. 2%.
   Filtr OGC (FILTER=...) dziala i jest jedynym sensownym sposobem pobierania.

Ceny: nier_cena_brutto dotyczy calej transakcji (moze obejmowac kilka dzialek),
dzi_cena_brutto tylko tej jednej dzialki i bywa puste. Do modelu liczymy
cene jednostkowa z poziomu transakcji: nier_cena_brutto / nier_pow_gruntu.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree as ET

from grunt.sources import _http, geo
from grunt.sources.gml import NS, geometry_to_wkt, ms_field, text_of

RCN_WFS = "https://mapy.geoportal.gov.pl/wss/service/rcn"
TYPENAME = "ms:dzialki"


# Rodzaje nieruchomosci w RCN, ktore sa gruntem bez zabudowy.
RODZAJ_NIEZABUDOWANA = "nieruchomoscGruntowaNiezabudowana"

PAGE_SIZE = 1000
# Powyzej tego progu dzielimy kafel na cztery. Gleboka paginacja w MapServerze
# jest wolna, a i tak trzeba bylo zejsc nizej, zeby zmiescic sie w limitach.
MAX_FEATURES_PER_TILE = 5000


class RcnError(RuntimeError):
    pass


@dataclass(slots=True)
class RcnRecord:
    """Jedna dzialka w jednej transakcji."""

    iip_id: str | None
    id_dzialki: str | None
    teryt_powiat: str | None
    data_trans: dt.date | None
    cena_grosze: int | None
    pow_m2: int | None
    pow_gruntu_m2: int | None
    przeznaczenie: str | None
    sposob_uzyt: str | None
    rodzaj_rynku: str | None
    rodzaj_trans: str | None
    nier_rodzaj: str | None
    udzial: str | None
    geom_wkt: str | None
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def is_usable_for_model(self) -> bool:
        """Rekord nadaje sie do uczenia wyceny.

        Odrzucamy: brak ceny, brak powierzchni, udzialy ulamkowe (cena dotyczy
        czesci nieruchomosci, nie calosci) i transakcje poza wolnym rynkiem
        (darowizny, przetargi wewnetrzne, sprzedaz miedzy krewnymi).
        """
        return (
            self.cena_grosze is not None
            and self.cena_grosze > 0
            and self.pow_gruntu_m2 is not None
            and self.pow_gruntu_m2 > 0
            and (self.udzial in (None, "1/1"))
            and self.rodzaj_trans == "wolnyRynek"
        )

    @property
    def cena_m2(self) -> float | None:
        """Cena za m2 liczona z poziomu transakcji, bo cena dotyczy calej transakcji."""
        if self.cena_grosze is None or not self.pow_gruntu_m2:
            return None
        return self.cena_grosze / 100.0 / self.pow_gruntu_m2


# --------------------------------------------------------------- parsowanie


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = value.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return int(round(float(cleaned)))
    except ValueError:
        return None


def _to_date(value: str | None) -> dt.date | None:
    """dok_data przychodzi jako '2021-04-26 02:00:00+02'."""
    if not value:
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not match:
        return None
    try:
        return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_feature(member: ET.Element) -> RcnRecord:
    def ms(name: str) -> str | None:
        return ms_field(member, name)

    raw = {
        key: value
        for key, value in ((child.tag.split("}")[-1], text_of(child)) for child in member)
        if value is not None and key != "msGeometry" and key != "boundedBy"
    }

    geometry_el = member.find(f"{{{NS['ms']}}}msGeometry")
    geom_wkt = geometry_to_wkt(geometry_el) if geometry_el is not None else None

    cena = _to_int(ms("dzi_cena_brutto")) or _to_int(ms("nier_cena_brutto"))

    return RcnRecord(
        iip_id=ms("tran_lokalny_id_iip"),
        id_dzialki=ms("dzi_id_dzialki"),
        teryt_powiat=ms("teryt"),
        data_trans=_to_date(ms("dok_data")),
        cena_grosze=cena * 100 if cena is not None else None,
        pow_m2=_to_int(ms("dzi_pow_ewid")),
        pow_gruntu_m2=_to_int(ms("nier_pow_gruntu")),
        przeznaczenie=ms("dzi_przezn_wmpzp"),
        sposob_uzyt=ms("dzi_sposob_uzyt"),
        rodzaj_rynku=ms("tran_rodzaj_rynku"),
        rodzaj_trans=ms("tran_rodzaj_trans"),
        nier_rodzaj=ms("nier_rodzaj"),
        udzial=ms("nier_udzial"),
        geom_wkt=geom_wkt,
        raw=raw,
    )


def parse_response(xml: bytes | str) -> list[RcnRecord]:
    """Rozbior odpowiedzi WFS. Funkcja czysta, testowana na zapisanym fixture."""
    root = ET.fromstring(xml) if isinstance(xml, str) else ET.fromstring(xml.decode("utf-8"))
    if root.tag.endswith("ExceptionReport"):
        raise RcnError(f"WFS zwrocil wyjatek: {''.join(root.itertext())[:300]}")

    records: list[RcnRecord] = []
    for member in root.findall(f"{{{NS['wfs']}}}member"):
        for feature in member:
            records.append(parse_feature(feature))
    return records


def count_from_response(xml: bytes | str) -> int:
    text = xml.decode("utf-8", "ignore") if isinstance(xml, bytes) else xml
    match = re.search(r'numberMatched="(\d+)"', text)
    if not match:
        raise RcnError("brak numberMatched w odpowiedzi RESULTTYPE=hits")
    return int(match.group(1))


# ------------------------------------------------------------------ zapytania


def build_filter(
    bbox: geo.BBox2180,
    *,
    since: dt.date | None = None,
    nier_rodzaj: str | None = RODZAJ_NIEZABUDOWANA,
) -> str:
    """Filtr OGC 2.0. Envelope w kolejnosci osi ukladu, czyli northing easting."""
    parts = [
        "<fes:BBOX><fes:ValueReference>msGeometry</fes:ValueReference>"
        '<gml:Envelope srsName="urn:ogc:def:crs:EPSG::2180">'
        f"<gml:lowerCorner>{bbox.min_northing:.1f} {bbox.min_easting:.1f}</gml:lowerCorner>"
        f"<gml:upperCorner>{bbox.max_northing:.1f} {bbox.max_easting:.1f}</gml:upperCorner>"
        "</gml:Envelope></fes:BBOX>"
    ]
    if since is not None:
        # Wszystkie pola sa typu string, wiec porownanie jest leksykograficzne.
        # Dla formatu ISO daje to poprawny porzadek chronologiczny.
        parts.append(
            "<fes:PropertyIsGreaterThan><fes:ValueReference>dok_data</fes:ValueReference>"
            f"<fes:Literal>{since.isoformat()}</fes:Literal></fes:PropertyIsGreaterThan>"
        )
    if nier_rodzaj:
        parts.append(
            "<fes:PropertyIsEqualTo><fes:ValueReference>nier_rodzaj</fes:ValueReference>"
            f"<fes:Literal>{nier_rodzaj}</fes:Literal></fes:PropertyIsEqualTo>"
        )

    inner = "".join(parts)
    if len(parts) > 1:
        inner = f"<fes:And>{inner}</fes:And>"
    return (
        '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0" '
        f'xmlns:gml="http://www.opengis.net/gml/3.2">{inner}</fes:Filter>'
    )


def _params(filter_xml: str, **extra: Any) -> dict[str, Any]:
    return {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": TYPENAME,
        "SRSNAME": "EPSG:2180",
        "FILTER": filter_xml,
        **extra,
    }


def count_features(bbox: geo.BBox2180, *, since: dt.date | None = None, delay: float = 1.0) -> int:
    """RESULTTYPE=hits: jedno tanie zapytanie zamiast pobierania kafla w ciemno."""
    filter_xml = build_filter(bbox, since=since)
    response = _http.get(RCN_WFS, params=_params(filter_xml, RESULTTYPE="hits"), delay=delay)
    return count_from_response(response.content)


def iter_tile(
    bbox: geo.BBox2180,
    *,
    since: dt.date | None = None,
    delay: float = 1.0,
    page_size: int = PAGE_SIZE,
) -> Iterator[RcnRecord]:
    """Paginacja po jednym kaflu."""
    filter_xml = build_filter(bbox, since=since)
    start = 0
    while True:
        response = _http.get(
            RCN_WFS,
            params=_params(filter_xml, COUNT=page_size, STARTINDEX=start),
            delay=delay,
            timeout=180.0,
        )
        records = parse_response(response.content)
        yield from records
        if len(records) < page_size:
            return
        start += page_size


def iter_region(
    bbox: geo.BBox2180,
    *,
    since: dt.date | None = None,
    delay: float = 1.0,
    max_per_tile: int = MAX_FEATURES_PER_TILE,
    min_tile_m: float = 1000.0,
    on_tile: Any = None,
) -> Iterator[RcnRecord]:
    """Adaptacyjny quadtree: kafel dzieli sie na cztery, dopoki jest za gesty.

    Dzieki temu Gdansk schodzi do kilkuset metrow, a pustkowia Kaszub zostaja
    jednym duzym kaflem. Bez tego albo topimy sie w glebokiej paginacji,
    albo robimy tysiace pustych zapytan.
    """
    stack = [bbox]
    while stack:
        tile = stack.pop()
        width = tile.max_easting - tile.min_easting
        height = tile.max_northing - tile.min_northing
        total = count_features(tile, since=since, delay=delay)

        if on_tile is not None:
            on_tile(tile, total)

        if total == 0:
            continue
        if total > max_per_tile and width > min_tile_m and height > min_tile_m:
            mid_e = (tile.min_easting + tile.max_easting) / 2
            mid_n = (tile.min_northing + tile.max_northing) / 2
            stack.extend(
                [
                    geo.BBox2180(tile.min_easting, tile.min_northing, mid_e, mid_n),
                    geo.BBox2180(mid_e, tile.min_northing, tile.max_easting, mid_n),
                    geo.BBox2180(tile.min_easting, mid_n, mid_e, tile.max_northing),
                    geo.BBox2180(mid_e, mid_n, tile.max_easting, tile.max_northing),
                ]
            )
            continue

        yield from iter_tile(tile, since=since, delay=delay)
