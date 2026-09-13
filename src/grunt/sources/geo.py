"""Przeliczenia ukladow wspolrzednych i budowanie parametrow uslug GUGiK.

TO JEST JEDYNE MIEJSCE W PROJEKCIE, KTORE SKLADA PARAMETRY xy / BBOX.
Powod: trzy uslugi, ktorych uzywamy obok siebie, maja trzy rozne konwencje osi,
a przy zlej kolejnosci nie zglaszaja bledu, tylko zwracaja dane z innego miejsca
w Polsce. To wyglada na poprawna odpowiedz i potrafi zabrac dzien.

    ULDK              xy=easting,northing              np. xy=477471,720567
    NMT GetHByXY      x=northing&y=easting             ODWROTNIE niz ULDK
    WMS 1.3.0 / 2180  BBOX=northing,easting,northing,easting
    WFS 2.0.0 / 2180  BBOX=northing,easting,northing,easting,EPSG:2180

Dodatkowo MapServer w uslugach GUGiK wymaga parametru STYLES, nawet pustego.

Slownik pojec, konsekwentnie w calym projekcie:
    easting  = wspolrzedna wschodnia (w EPSG:2180 rosnie na wschod), ok. 170-870 tys.
    northing = wspolrzedna polnocna  (rosnie na polnoc),             ok. 130-790 tys.
W EPSG:2180 formalna kolejnosc osi to (northing, easting), dlatego nigdzie w kodzie
nie uzywamy nazw "x" i "y" bez kwalifikatora.

Endpointy i pulapki: sekcja 19 dokumentu koncepcyjnego.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final

from pyproj import Transformer

EPSG_PL1992: Final = 2180
EPSG_WGS84: Final = 4326

# Zakresy EPSG:2180 dla obszaru Polski, z zapasem. Sluza wylacznie do wykrywania
# grubych bledow (zamiana osi, wspolrzedne WGS84 wpuszczone jako metry).
EASTING_RANGE: Final = (140_000.0, 880_000.0)
NORTHING_RANGE: Final = (100_000.0, 830_000.0)

# Zakresy WGS84 dla Polski, z zapasem.
LAT_RANGE: Final = (48.9, 55.0)
LON_RANGE: Final = (13.9, 24.5)


class AxisOrderError(ValueError):
    """Wspolrzedne poza obszarem Polski. Prawie zawsze oznacza zamieniona kolejnosc osi."""


@lru_cache(maxsize=4)
def _transformer(src: int, dst: int) -> Transformer:
    # always_xy=True: wejscie i wyjscie zawsze w kolejnosci (easting/lon, northing/lat),
    # niezaleznie od formalnej definicji osi w CRS. Kolejnosc dla uslug skladamy
    # jawnie w funkcjach ponizej.
    return Transformer.from_crs(f"EPSG:{src}", f"EPSG:{dst}", always_xy=True)


@dataclass(frozen=True, slots=True)
class PL1992:
    """Punkt w EPSG:2180. Pola nazwane jawnie, zeby nie dalo sie ich pomylic."""

    easting: float
    northing: float

    def __post_init__(self) -> None:
        validate_pl1992(self.easting, self.northing)

    def as_tuple_en(self) -> tuple[float, float]:
        """(easting, northing) - kolejnosc ULDK i shapely."""
        return (self.easting, self.northing)

    def as_tuple_ne(self) -> tuple[float, float]:
        """(northing, easting) - kolejnosc NMT i WMS 1.3.0."""
        return (self.northing, self.easting)


@dataclass(frozen=True, slots=True)
class WGS84:
    lat: float
    lon: float

    def __post_init__(self) -> None:
        validate_wgs84(self.lat, self.lon)


@dataclass(frozen=True, slots=True)
class BBox2180:
    """Prostokat w EPSG:2180."""

    min_easting: float
    min_northing: float
    max_easting: float
    max_northing: float


def validate_pl1992(easting: float, northing: float) -> None:
    if not (EASTING_RANGE[0] <= easting <= EASTING_RANGE[1]):
        raise AxisOrderError(
            f"easting={easting:.1f} poza zakresem Polski {EASTING_RANGE}. "
            "Sprawdz, czy nie podano (northing, easting) zamiast (easting, northing)."
        )
    if not (NORTHING_RANGE[0] <= northing <= NORTHING_RANGE[1]):
        raise AxisOrderError(
            f"northing={northing:.1f} poza zakresem Polski {NORTHING_RANGE}. Sprawdz kolejnosc osi."
        )


def validate_wgs84(lat: float, lon: float) -> None:
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1]):
        raise AxisOrderError(
            f"lat={lat} poza zakresem Polski {LAT_RANGE}. Sprawdz, czy nie zamieniono lat z lon."
        )
    if not (LON_RANGE[0] <= lon <= LON_RANGE[1]):
        raise AxisOrderError(f"lon={lon} poza zakresem Polski {LON_RANGE}. Sprawdz kolejnosc.")


# ---------------------------------------------------------------- przeliczenia


def wgs84_to_pl1992(lat: float, lon: float) -> PL1992:
    easting, northing = _transformer(EPSG_WGS84, EPSG_PL1992).transform(lon, lat)
    return PL1992(easting=easting, northing=northing)


def pl1992_to_wgs84(easting: float, northing: float) -> WGS84:
    lon, lat = _transformer(EPSG_PL1992, EPSG_WGS84).transform(easting, northing)
    return WGS84(lat=lat, lon=lon)


def bbox_around(point: PL1992, radius_m: float) -> BBox2180:
    """Kwadrat o boku 2*radius wokol punktu. W EPSG:2180 metry sa metrami."""
    if radius_m <= 0:
        raise ValueError("radius_m musi byc dodatni")
    return BBox2180(
        min_easting=point.easting - radius_m,
        min_northing=point.northing - radius_m,
        max_easting=point.easting + radius_m,
        max_northing=point.northing + radius_m,
    )


# ------------------------------------------------- parametry konkretnych uslug


def uldk_xy(point: PL1992) -> str:
    """ULDK: xy=easting,northing (EPSG:2180 jest domyslny, wiec bez SRID)."""
    return f"{point.easting:.2f},{point.northing:.2f}"


def uldk_xy_wgs84(lat: float, lon: float) -> str:
    """ULDK w WGS84: xy=lon,lat,4326. Trzeci element to SRID, kolejnosc jak wyzej."""
    validate_wgs84(lat, lon)
    return f"{lon:.7f},{lat:.7f},{EPSG_WGS84}"


def nmt_params(point: PL1992) -> dict[str, str]:
    """NMT GetHByXY: x=northing, y=easting. ODWROTNIE niz ULDK, to nie jest literowka."""
    return {
        "request": "GetHByXY",
        "x": f"{point.northing:.2f}",
        "y": f"{point.easting:.2f}",
    }


def wms_bbox(bbox: BBox2180) -> str:
    """WMS 1.3.0 dla EPSG:2180: BBOX=minN,minE,maxN,maxE."""
    return (
        f"{bbox.min_northing:.2f},{bbox.min_easting:.2f},"
        f"{bbox.max_northing:.2f},{bbox.max_easting:.2f}"
    )


def wfs_bbox(bbox: BBox2180, with_srs: bool = True) -> str:
    """WFS 2.0.0 dla EPSG:2180: BBOX=minN,minE,maxN,maxE[,EPSG:2180]."""
    base = wms_bbox(bbox)
    return f"{base},EPSG:{EPSG_PL1992}" if with_srs else base


def wms_getfeatureinfo_params(
    layers: str,
    point: PL1992,
    *,
    radius_m: float = 50.0,
    size_px: int = 101,
    info_format: str = "application/json",
    query_layers: str | None = None,
) -> dict[str, Any]:
    """Parametry GetFeatureInfo z punktem trafienia dokladnie w srodku obrazu.

    STYLES jest wysylany zawsze, nawet pusty: MapServer w uslugach GUGiK bez niego
    zwraca MissingParameterValue.
    """
    if size_px % 2 == 0:
        raise ValueError("size_px musi byc nieparzysty, zeby punkt trafil w srodek piksela")
    bbox = bbox_around(point, radius_m)
    center = size_px // 2
    return {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": layers,
        "QUERY_LAYERS": query_layers or layers,
        "STYLES": "",
        "CRS": f"EPSG:{EPSG_PL1992}",
        "BBOX": wms_bbox(bbox),
        "WIDTH": size_px,
        "HEIGHT": size_px,
        "I": center,
        "J": center,
        "FORMAT": "image/png",
        "INFO_FORMAT": info_format,
        "FEATURE_COUNT": 10,
    }


def wfs_getfeature_params(
    typenames: str,
    bbox: BBox2180,
    *,
    count: int = 100,
    version: str = "2.0.0",
) -> dict[str, Any]:
    """Parametry GetFeature z BBOX w kolejnosci wymaganej przez EPSG:2180."""
    return {
        "SERVICE": "WFS",
        "VERSION": version,
        "REQUEST": "GetFeature",
        "TYPENAMES": typenames,
        "SRSNAME": f"EPSG:{EPSG_PL1992}",
        "COUNT": count,
        "BBOX": wfs_bbox(bbox),
    }
