"""Cechy fizyczne dzialki z jej geometrii. Sekcja 5.3.6 dokumentu.

Wszystko liczone z jednego wielokata, bez odpytywania czegokolwiek. Reguly
kciuka z dokumentu, ktore nadaja tym liczbom sens:

    front ponizej 18 m         problem przy zabudowie wolnostojacej, bo przepisy
                               wymagaja 3 i 4 m odstepu od granicy
    smuklosc powyzej 5         mocno ogranicza projektowanie
    zwartosc ponizej 0,45      zwykle dzialka po podziale rodzinnym, realny dyskont

UCZCIWE ZASTRZEZENIE CO DO FRONTU. Dokument definiuje front jako dlugosc granicy
przylegajacej do drogi. Nie mamy jeszcze warstwy drog, wiec liczymy PROXY:
krotszy bok prostokata o najmniejszym polu opisanego na dzialce. Dla typowej
parceli prostopadlej do drogi to dobre przyblizenie, dla dzialki narozej albo
o nietypowym ksztalcie moze byc mylace. Dlatego wynik jest oznaczony jako
przyblizony, a gdy portal podaje wymiary wprost (Nieruchomosci-online robi to
w polu "Land dimensions"), pierwszenstwo ma wartosc z ogloszenia.

Funkcje czyste.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# Progi z sekcji 5.3.6
FRONT_PROBLEMATYCZNY_M = 18.0
SMUKLOSC_PROBLEMATYCZNA = 5.0
ZWARTOSC_PROBLEMATYCZNA = 0.45


@dataclass(frozen=True, slots=True)
class ParcelShape:
    area_m2: float | None = None
    obwod_m: float | None = None
    front_m: float | None = None
    front_zrodlo: str | None = None  # "ogloszenie" albo "geometria (proxy)"
    dlugosc_m: float | None = None
    smuklosc: float | None = None
    zwartosc: float | None = None
    azymut_osi: int | None = None
    wypelnienie_prostokata: float | None = None

    @property
    def uwagi(self) -> tuple[str, ...]:
        """Czerwone flagi wynikajace wprost z ksztaltu."""
        flagi: list[str] = []
        if self.front_m is not None and self.front_m < FRONT_PROBLEMATYCZNY_M:
            flagi.append(
                f"waski front ({self.front_m:.0f} m): przy zabudowie wolnostojacej "
                "przepisy o odlegloscii od granicy moga uniemozliwic zabudowe"
            )
        if self.smuklosc is not None and self.smuklosc > SMUKLOSC_PROBLEMATYCZNA:
            flagi.append(f"dzialka bardzo waska i dluga (smuklosc {self.smuklosc:.1f})")
        if self.zwartosc is not None and self.zwartosc < ZWARTOSC_PROBLEMATYCZNA:
            flagi.append(
                f"nieregularny ksztalt (zwartosc {self.zwartosc:.2f}), "
                "typowy dla dzialek po podziale rodzinnym"
            )
        return tuple(flagi)

    def to_dict(self) -> dict[str, Any]:
        return {
            "powierzchnia_m2": round(self.area_m2) if self.area_m2 else None,
            "front_m": round(self.front_m, 1) if self.front_m else None,
            "front_zrodlo": self.front_zrodlo,
            "dlugosc_m": round(self.dlugosc_m, 1) if self.dlugosc_m else None,
            "smuklosc": round(self.smuklosc, 2) if self.smuklosc else None,
            "zwartosc": round(self.zwartosc, 3) if self.zwartosc else None,
            "azymut_osi": self.azymut_osi,
            "wypelnienie_prostokata": (
                round(self.wypelnienie_prostokata, 3) if self.wypelnienie_prostokata else None
            ),
            "uwagi": list(self.uwagi),
        }


def compactness(area_m2: float, obwod_m: float) -> float | None:
    """Zwartosc 4*pi*A / P^2. Kolo daje 1,0, kwadrat 0,785."""
    if area_m2 <= 0 or obwod_m <= 0:
        return None
    return (4 * math.pi * area_m2) / (obwod_m**2)


def from_wkt(geom_wkt: str | None, *, front_z_ogloszenia_m: float | None = None) -> ParcelShape:
    """Komplet cech ksztaltu z geometrii dzialki w EPSG:2180."""
    if not geom_wkt:
        return ParcelShape(
            front_m=front_z_ogloszenia_m,
            front_zrodlo="ogloszenie" if front_z_ogloszenia_m else None,
        )

    from shapely import wkt as shapely_wkt

    try:
        geom = shapely_wkt.loads(geom_wkt)
    except Exception:
        return ParcelShape()

    if geom.is_empty or geom.area <= 0:
        return ParcelShape()

    area = float(geom.area)
    obwod = float(geom.length)

    # prostokat o najmniejszym polu opisany na dzialce daje dlugosc i szerokosc
    prostokat = geom.minimum_rotated_rectangle
    boki = _boki_prostokata(prostokat)
    if boki:
        krotszy, dluzszy = boki
    else:
        krotszy = dluzszy = None

    front = front_z_ogloszenia_m or krotszy
    zrodlo = "ogloszenie" if front_z_ogloszenia_m else ("geometria (proxy)" if krotszy else None)

    smuklosc = (dluzszy / krotszy) if (krotszy and dluzszy and krotszy > 0) else None
    wypelnienie = (area / float(prostokat.area)) if prostokat.area > 0 else None

    return ParcelShape(
        area_m2=area,
        obwod_m=obwod,
        front_m=front,
        front_zrodlo=zrodlo,
        dlugosc_m=dluzszy,
        smuklosc=smuklosc,
        zwartosc=compactness(area, obwod),
        azymut_osi=_azymut_dluzszego_boku(prostokat),
        wypelnienie_prostokata=wypelnienie,
    )


def _wierzcholki(prostokat: Any) -> list[tuple[float, float]]:
    try:
        return list(prostokat.exterior.coords)[:5]
    except AttributeError:
        return []


def _boki_prostokata(prostokat: Any) -> tuple[float, float] | None:
    """(krotszy bok, dluzszy bok) prostokata opisanego."""
    punkty = _wierzcholki(prostokat)
    if len(punkty) < 3:
        return None
    a = math.dist(punkty[0], punkty[1])
    b = math.dist(punkty[1], punkty[2])
    if a <= 0 or b <= 0:
        return None
    return (min(a, b), max(a, b))


def _azymut_dluzszego_boku(prostokat: Any) -> int | None:
    """Azymut osi dluzszej w stopniach: 0 to polnoc, rosnie na wschod.

    Wplywa na naslonecznienie i na to, jak da sie ustawic budynek.
    """
    punkty = _wierzcholki(prostokat)
    if len(punkty) < 3:
        return None
    krawedzie = [(punkty[0], punkty[1]), (punkty[1], punkty[2])]
    (p1, p2) = max(krawedzie, key=lambda kr: math.dist(kr[0], kr[1]))
    de = p2[0] - p1[0]
    dn = p2[1] - p1[1]
    if de == 0 and dn == 0:
        return None
    azymut = (math.degrees(math.atan2(de, dn)) + 360) % 180  # os, nie kierunek
    return int(round(azymut))
