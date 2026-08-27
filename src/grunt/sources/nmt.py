"""Numeryczny Model Terenu: wysokosc n.p.m. i spadek terenu.

Usluga punktowa GUGiK, zweryfikowana na zywo: Gdansk 4,9 m, Kartuzy ok. 215 m.

PULAPKA KOLEJNOSCI OSI: NMT przyjmuje x=northing, y=easting, czyli ODWROTNIE
niz ULDK. Parametry sklada wylacznie sources/geo.py i nie wolno ich budowac
recznie (sekcja 19 dokumentu).

Spadek liczymy tak, jak opisuje sekcja 19.2: osiem punktow w siatce wokol
srodka i gradient z nich. To dziewiec zapytan na dzialke, wiec funkcja przyjmuje
gotowy zestaw wysokosci do policzenia gradientu osobno (czysta) i osobno robi
zapytania.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import httpx

from grunt.sources import _http, geo

NMT_URL = "https://services.gugik.gov.pl/nmt/"

# Zakres wysokosci dla Polski, z zapasem. Poza nim to blad uslugi, nie teren.
MIN_H, MAX_H = -20.0, 2600.0


class NmtError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Terrain:
    wysokosc_npm: float | None
    spadek_proc: float | None
    azymut_spadku: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "wysokosc_npm": round(self.wysokosc_npm, 1) if self.wysokosc_npm is not None else None,
            "spadek_proc": round(self.spadek_proc, 2) if self.spadek_proc is not None else None,
            "azymut_spadku": self.azymut_spadku,
        }


def height(point: geo.PL1992, *, delay: float = 0.4) -> float | None:
    """Wysokosc n.p.m. w metrach. None, gdy usluga nie zna punktu."""
    try:
        response = _http.get(NMT_URL, params=geo.nmt_params(point), delay=delay, timeout=30)
    except httpx.HTTPError as exc:
        raise NmtError(f"NMT niedostepny: {exc}") from exc

    tekst = response.text.strip()
    if not tekst or "brak" in tekst.lower():
        return None
    try:
        wartosc = float(tekst.split()[-1].replace(",", "."))
    except ValueError:
        return None
    return wartosc if MIN_H <= wartosc <= MAX_H else None


def slope_from_grid(
    center: float | None, ring: list[float | None], step_m: float
) -> tuple[float | None, int | None]:
    """Spadek w procentach i azymut z osmiu wysokosci wokol punktu.

    ring to wysokosci w kolejnosci: N, NE, E, SE, S, SW, W, NW.
    Funkcja czysta: liczy gradient metoda roznic skonczonych po dwoch osiach.
    """
    if center is None or len(ring) != 8 or any(h is None for h in ring):
        return (None, None)
    n, ne, e, se, s, sw, w, nw = (float(h) for h in ring)  # type: ignore[arg-type]

    # gradient wschod-zachod i polnoc-poludnie (metoda Horna, uproszczona)
    dz_de = ((ne + 2 * e + se) - (nw + 2 * w + sw)) / (8 * step_m)
    dz_dn = ((nw + 2 * n + ne) - (sw + 2 * s + se)) / (8 * step_m)

    nachylenie = math.hypot(dz_de, dz_dn)
    spadek_proc = nachylenie * 100.0

    if nachylenie == 0:
        return (0.0, None)
    # azymut kierunku SPADKU (dokad splywa woda), 0 = polnoc, rosnie na wschod
    azymut = (math.degrees(math.atan2(-dz_de, -dz_dn)) + 360) % 360
    return (spadek_proc, int(round(azymut)))


def terrain(point: geo.PL1992, *, step_m: float = 10.0, delay: float = 0.4) -> Terrain:
    """Wysokosc i spadek. Dziewiec zapytan do uslugi (srodek plus osiem sasiadow)."""
    center = height(point, delay=delay)
    if center is None:
        return Terrain(wysokosc_npm=None, spadek_proc=None)

    przesuniecia = [
        (0, 1),
        (1, 1),
        (1, 0),
        (1, -1),
        (0, -1),
        (-1, -1),
        (-1, 0),
        (-1, 1),
    ]  # N, NE, E, SE, S, SW, W, NW
    ring: list[float | None] = []
    for de, dn in przesuniecia:
        sasiad = geo.PL1992(
            easting=point.easting + de * step_m, northing=point.northing + dn * step_m
        )
        ring.append(height(sasiad, delay=delay))

    spadek, azymut = slope_from_grid(center, ring, step_m)
    return Terrain(wysokosc_npm=center, spadek_proc=spadek, azymut_spadku=azymut)
