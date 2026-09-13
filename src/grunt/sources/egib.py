"""Ewidencja Gruntow i Budynkow: dzialki w promieniu jednym zapytaniem.

Po co, skoro jest ULDK: ULDK odpowiada na pytanie "jaka dzialka jest W TYM
PUNKCIE", a wspolrzedne z ogloszen sa przyblizone. Sprawdzone na dwoch ofertach:

    Morizon, Gdansk ul. Wiecka   deklarowane 1115 m2, ULDK zwraca 886 m2
    N-O, Katy Rybackie           deklarowane  835 m2, ULDK zwraca 18 983 m2

W drugim przypadku punkt trafil w dzialke-matke, bo ogloszenie dotyczy dzialki
dopiero wydzielanej. Zadne z tych dopasowan nie nadaje sie do liczenia cech.

EGiB pozwala pobrac WSZYSTKIE dzialki z prostokata jednym zapytaniem (50 sztuk
z kwadratu 240 m w Gdansku), wiec zamiast wierzyc jednemu punktowi mozemy
wybrac kandydata, ktorego powierzchnia zgadza sie z ogloszeniem.

Pulapki potwierdzone na zywo 2026-08-21:
* srsName w formie urn, czyli posList w kolejnosci NORTHING EASTING (patrz gml.py)
* POLE_EWIDENYJNE i KLASOUZYTKI_EGIB przychodza PUSTE, mimo ze sa w schemacie.
  Powierzchnie liczymy z geometrii, a klasy bonitacyjne trzeba brac z KIUG.
* dane maja date waznosci w polu DATA (widziano 2026-08-19)
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from grunt.sources import _http, geo
from grunt.sources.gml import NS, geometry_to_wkt, ms_field

EGIB_WFS = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/EGIB/WFS/UslugaZbiorcza"
TYPENAME = "ms:dzialki"

# Ile dzialek maksymalnie z jednego prostokata. W miescie 240 m to ok. 50 dzialek,
# na wsi kilka. Wiecej niz 200 oznacza, ze promien jest za duzy.
DEFAULT_COUNT = 200


class EgibError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EgibParcel:
    id_dzialki: str
    numer_dzialki: str | None
    numer_obrebu: str | None
    nazwa_obrebu: str | None
    nazwa_gminy: str | None
    geom_wkt: str | None
    area_m2: float | None
    data: dt.date | None = None

    @property
    def teryt_gmina(self) -> str | None:
        head = self.id_dzialki.split(".", 1)[0]
        digits = head.replace("_", "")
        return digits[:7] if len(digits) >= 7 else None

    @property
    def teryt_obreb(self) -> str | None:
        parts = self.id_dzialki.split(".")
        return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else None


def _area_from_wkt(wkt: str | None) -> float | None:
    if not wkt:
        return None
    from shapely import wkt as shapely_wkt

    try:
        return float(shapely_wkt.loads(wkt).area)
    except Exception:  # geometria z uslugi bywa uszkodzona
        return None


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_response(xml: bytes | str) -> list[EgibParcel]:
    """Rozbior odpowiedzi WFS. Funkcja czysta, testowana na zapisanym fixture."""
    root = ET.fromstring(xml.decode("utf-8") if isinstance(xml, bytes) else xml)
    if root.tag.endswith("ExceptionReport"):
        raise EgibError(f"EGiB zwrocil wyjatek: {''.join(root.itertext())[:300]}")

    parcels: list[EgibParcel] = []
    for member in root.findall(f"{{{NS['wfs']}}}member"):
        for feature in member:
            id_dzialki = ms_field(feature, "ID_DZIALKI")
            if not id_dzialki:
                continue
            # EGiB trzyma geometrie w ms:geom, RCN w ms:msGeometry. Zamiast
            # zgadywac nazwe, oddajemy caly obiekt: parser szuka gml:Polygon
            # w glab, a gml:Envelope z boundedBy go nie myli.
            wkt = geometry_to_wkt(feature)
            parcels.append(
                EgibParcel(
                    id_dzialki=id_dzialki,
                    numer_dzialki=ms_field(feature, "NUMER_DZIALKI"),
                    numer_obrebu=ms_field(feature, "NUMER_OBREBU"),
                    nazwa_obrebu=ms_field(feature, "NAZWA_OBREBU"),
                    nazwa_gminy=ms_field(feature, "NAZWA_GMINY"),
                    geom_wkt=wkt,
                    area_m2=_area_from_wkt(wkt),
                    data=_parse_date(ms_field(feature, "DATA")),
                )
            )
    return parcels


def parcels_around(
    point: geo.PL1992,
    *,
    radius_m: float = 120.0,
    count: int = DEFAULT_COUNT,
    delay: float = 1.0,
) -> list[EgibParcel]:
    """Wszystkie dzialki ewidencyjne w kwadracie o polowie boku radius_m."""
    params = geo.wfs_getfeature_params(TYPENAME, geo.bbox_around(point, radius_m), count=count)
    response = _http.get(EGIB_WFS, params=params, delay=delay, timeout=90)
    return parse_response(response.content)
