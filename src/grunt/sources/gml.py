"""Wspolne parsowanie geometrii GML 3.2 z uslug GUGiK.

Jedno miejsce, bo ta funkcja jest krytyczna dla poprawnosci i latwo ja zepsuc
po cichu. Uslugi GUGiK (RCN, EGiB) podaja srsName w formie urn:

    urn:ogc:def:crs:EPSG::2180

a ta wymusza kolejnosc osi z definicji ukladu, czyli NORTHING EASTING.
My przechowujemy geometrie jako (easting, northing), wiec kazda pare trzeba
odwrocic. Bez tego geometria laduje kilkaset kilometrow na wschod i nic nie
zglasza bledu, bo liczby wygladaja poprawnie.

ALE NIE WSZYSTKIE USLUGI TAK ROBIA. Rejestr Urbanistyczny (MPZP, plany ogolne)
podaje srsName w formie starszej:

    http://www.opengis.net/gml/srs/epsg.xml#2180

i wtedy kolejnosc jest odwrotna, czyli EASTING NORTHING. Sprawdzone na akcie
z Hrubieszowa: pierwsza liczba w posList to 840789, a Hrubieszow ma easting
ok. 844000 i northing ok. 338000, wiec pierwsza wspolrzedna to easting.

Dlatego kolejnosc osi wynika z formy srsName, a nie z zalozenia wolajacego.
Regula jest w kolejnosc_easting_first() i to jedyne miejsce, w ktorym stoi.

Sprawdzone na zywych odpowiedziach RCN i EGiB (2026-08-21) oraz Rejestru
Urbanistycznego (2026-08-24).
"""

from __future__ import annotations

from typing import Final
from xml.etree import ElementTree as ET

NS: Final[dict[str, str]] = {
    "wfs": "http://www.opengis.net/wfs/2.0",
    "gml": "http://www.opengis.net/gml/3.2",
    "ms": "http://mapserver.gis.umn.edu/mapserver",
}

GML = NS["gml"]


class GmlError(ValueError):
    pass


def kolejnosc_easting_first(srs_name: str | None) -> bool:
    """Czy w tej odpowiedzi posList zaczyna sie od eastingu.

    Forma urn (urn:ogc:def:crs:EPSG::2180) wymusza kolejnosc osi z definicji
    ukladu, czyli northing easting. Forma starsza (epsg.xml#2180, EPSG:2180)
    oznacza kolejnosc "x y", czyli easting northing. Brak srsName traktujemy
    jak urn, bo tak zachowuja sie uslugi GUGiK, z ktorych bierzemy wiekszosc
    geometrii.
    """
    if not srs_name:
        return False
    return "urn:ogc:def:crs" not in srs_name


def poslist_to_ring(text: str, *, easting_first: bool = False) -> list[tuple[float, float]]:
    """gml:posList -> lista (easting, northing).

    easting_first mowi, w jakiej kolejnosci przyszly dane. Wyjscie jest zawsze
    takie samo, bo cala reszta projektu trzyma (easting, northing).
    """
    numbers = [float(v) for v in text.split()]
    if len(numbers) % 2:
        raise GmlError("posList o nieparzystej liczbie wspolrzednych")
    if easting_first:
        return [(numbers[i], numbers[i + 1]) for i in range(0, len(numbers), 2)]
    # ODWROCENIE: wejscie (N, E), wyjscie (E, N). To nie jest literowka.
    return [(numbers[i + 1], numbers[i]) for i in range(0, len(numbers), 2)]


def ring_to_wkt(ring: list[tuple[float, float]]) -> str:
    if ring and ring[0] != ring[-1]:
        ring = [*ring, ring[0]]
    return "(" + ",".join(f"{e:.3f} {n:.3f}" for e, n in ring) + ")"


def geometry_to_wkt(element: ET.Element, *, easting_first: bool | None = None) -> str | None:
    """Polygon albo MultiSurface z GML 3.2 -> WKT MULTIPOLYGON w EPSG:2180.

    Kolejnosc osi odczytujemy z srsName obiektu. easting_first pozwala ja
    narzucic, gdy odpowiedz w ogole nie ma srsName.
    """
    polygons: list[str] = []
    for polygon in element.iter(f"{{{GML}}}Polygon"):
        kolejnosc = (
            easting_first
            if easting_first is not None
            else kolejnosc_easting_first(polygon.get("srsName") or element.get("srsName"))
        )
        rings: list[str] = []
        exterior = polygon.find(f"{{{GML}}}exterior/{{{GML}}}LinearRing/{{{GML}}}posList")
        if exterior is None or not exterior.text:
            continue
        rings.append(ring_to_wkt(poslist_to_ring(exterior.text, easting_first=kolejnosc)))
        for interior in polygon.findall(f"{{{GML}}}interior/{{{GML}}}LinearRing/{{{GML}}}posList"):
            if interior.text:
                rings.append(ring_to_wkt(poslist_to_ring(interior.text, easting_first=kolejnosc)))
        polygons.append("(" + ",".join(rings) + ")")

    if not polygons:
        return None
    return "MULTIPOLYGON(" + ",".join(polygons) + ")"


def text_of(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def ms_field(member: ET.Element, name: str) -> str | None:
    """Wartosc pola ms:<name> w obiekcie WFS-a MapServera."""
    return text_of(member.find(f"{{{NS['ms']}}}{name}"))


def parse_ms_gml_output(xml: str) -> list[dict[str, str]]:
    """Rozbior odpowiedzi GetFeatureInfo z MapServera (msGMLOutput).

    Format jest plaski: kazdy obiekt to zagniezdzony element z polami tekstowymi.
    Pusta odpowiedz (brak obiektu w punkcie) to poprawny wynik, nie blad -
    znaczy tyle, ze w tym miejscu warstwa nic nie ma.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    obiekty: list[dict[str, str]] = []
    for layer in root:
        for feature in layer:
            pola: dict[str, str] = {}
            for child in feature:
                nazwa = child.tag.split("}")[-1]
                if nazwa in ("boundedBy", "Box", "coordinates"):
                    continue
                wartosc = (child.text or "").strip()
                if wartosc:
                    pola[nazwa] = wartosc
            if pola:
                obiekty.append(pola)
    return obiekty
