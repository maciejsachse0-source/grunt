"""Uzbrojenie terenu z Krajowej Integracji Uzbrojenia Terenu.

Sekcja 5.3.5 dokumentu kaze zamienic flage "uzbrojona: tak/nie" na FUNKCJE
KOSZTOWA w zlotowkach, opartu o odleglosc do sieci. Cztery media to od 20 tys.
do ponad 150 tys. zl roznicy, a to tlumaczy sie uzytkownikowi lepiej niz punkty.

JAK TO ZMIERZYC, skoro usluga jest tylko obrazkowa:

GetFeatureInfo w KIUT jest bezuzyteczny - dla kazdej warstwy, kazdego promienia
i kazdego formatu zwraca ten sam komunikat "Usluga nie udostepnia danych
opisowych dla wybranego obiektu". Sprawdzone.

Dziala natomiast GetMap: renderujemy warstwe przewodu na malym wycinku wokol
punktu i patrzymy, czy cokolwiek narysowano. Rozmiary odpowiedzi sa
jednoznaczne (pomiar 2026-08-21):

    237 B    pusty, przezroczysty PNG, czyli w tym wycinku nie ma przewodu
    114 B    odmowa ze wzgledu na skale (warstwy maja MaxScaleDenominator 1000)
    > 2 kB   cos narysowano

Przyklady: centrum Gdanska ma wszystkie cztery media (12-28 kB), srodek Borow
Tucholskich zadnego (4 x 237 B), a Katy Rybackie maja wode, kanalizacje i prad,
ale NIE MAJA GAZU - mimo ze ogloszenie deklarowalo gaz.

BRAK DANYCH TO NIE BRAK SIECI. Dokument ostrzega o tym wprost. Nie da sie
odroznic powiatu spoza uslugi od terenu bez uzbrojenia, patrzac na jedna
warstwe. Przyjmujemy regule: jesli CHOC JEDNO medium jest widoczne, to obszar
jest w usludze i brak pozostalych jest faktem. Jesli zadne, zwracamy None.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx

from grunt.sources import _http, geo

KIUT_WMS = "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaUzbrojeniaTerenu"

WARSTWY: dict[str, str] = {
    "prad": "przewod_elektroenergetyczny",
    "woda": "przewod_wodociagowy",
    "kanalizacja": "przewod_kanalizacyjny",
    "gaz": "przewod_gazowy",
    "cieplo": "przewod_cieplowniczy",
    "telekom": "przewod_telekomunikacyjny",
}

MEDIA_PODSTAWOWE = ("prad", "woda", "kanalizacja", "gaz")

# Progi z sekcji 5.3.5
Bracket = Literal["<=50m", "50-200m", ">200m", "brak danych"]

# Koszt doprowadzenia w zlotowkach, srodek widelek z tabeli w sekcji 5.3.5
KOSZTY: dict[str, dict[Bracket, int]] = {
    "prad": {"<=50m": 4_500, "50-200m": 11_500, ">200m": 25_000, "brak danych": 0},
    "woda": {"<=50m": 8_000, "50-200m": 17_500, ">200m": 50_000, "brak danych": 0},
    "kanalizacja": {"<=50m": 7_500, "50-200m": 17_500, ">200m": 40_000, "brak danych": 0},
    "gaz": {"<=50m": 5_500, "50-200m": 14_000, ">200m": 35_000, "brak danych": 0},
    "cieplo": {"<=50m": 0, "50-200m": 0, ">200m": 0, "brak danych": 0},
    "telekom": {"<=50m": 0, "50-200m": 0, ">200m": 0, "brak danych": 0},
}

# Alternatywy, gdy sieci nie ma w ogole (sekcja 5.3.5)
ALTERNATYWY = {
    "woda": ("studnia glebinowa", 21_000),
    "kanalizacja": ("oczyszczalnia przydomowa", 16_500),
}

PUSTY_PNG_MAX = 500  # bajtow; pusty przezroczysty PNG to ok. 237 B, odmowa 114 B
ODMOWA_SKALI_MAX = 150


class KiutError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Utilities:
    odleglosci: dict[str, Bracket]
    w_zasiegu_uslugi: bool

    def koszt_pln(self, media: tuple[str, ...] = MEDIA_PODSTAWOWE) -> int | None:
        """Szacunkowy koszt doprowadzenia wskazanych mediow.

        None, gdy obszar jest poza usluga: wtedy nie wiemy nic i zgadywanie
        byloby gorsze niz milczenie.
        """
        if not self.w_zasiegu_uslugi:
            return None
        suma = 0
        for medium in media:
            bracket = self.odleglosci.get(medium, "brak danych")
            koszt = KOSZTY[medium][bracket]
            if bracket == ">200m" and medium in ALTERNATYWY:
                # Taniej zrobic wlasne ujecie niz ciagnac siec przez 200 m
                koszt = min(koszt, ALTERNATYWY[medium][1])
            suma += koszt
        return suma

    @property
    def dostepne(self) -> tuple[str, ...]:
        return tuple(m for m, b in self.odleglosci.items() if b in ("<=50m", "50-200m"))

    def to_dict(self) -> dict[str, object]:
        return {
            "odleglosci": dict(self.odleglosci),
            "dostepne": list(self.dostepne),
            "koszt_doprowadzenia_pln": self.koszt_pln(),
            "w_zasiegu_uslugi": self.w_zasiegu_uslugi,
        }


def _render_size(point: geo.PL1992, layer: str, radius_m: float, delay: float) -> int:
    bbox = geo.bbox_around(point, radius_m)
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": "",
        "CRS": f"EPSG:{geo.EPSG_PL1992}",
        "BBOX": geo.wms_bbox(bbox),
        "WIDTH": 201,
        "HEIGHT": 201,
        "FORMAT": "image/png",
        "TRANSPARENT": "TRUE",
    }
    try:
        response = _http.get(KIUT_WMS, params=params, delay=delay, timeout=60)
    except httpx.HTTPError as exc:
        raise KiutError(f"KIUT niedostepny: {exc}") from exc
    return len(response.content)


def _has_network(point: geo.PL1992, layer: str, radius_m: float, delay: float) -> bool | None:
    """True gdy cos narysowano, False gdy pusto, None gdy odmowa ze wzgledu na skale."""
    rozmiar = _render_size(point, layer, radius_m, delay)
    if rozmiar <= ODMOWA_SKALI_MAX:
        return None
    return rozmiar > PUSTY_PNG_MAX


def query(
    point: geo.PL1992,
    *,
    media: tuple[str, ...] = MEDIA_PODSTAWOWE,
    delay: float = 0.5,
) -> Utilities:
    """Odleglosc do sieci w trzech koszykach: do 50 m, 50-200 m, powyzej.

    Dwa zapytania na medium. Przy czterech mediach to osiem zapytan na dzialke.
    """
    odleglosci: dict[str, Bracket] = {}
    cokolwiek_widoczne = False

    for medium in media:
        layer = WARSTWY[medium]
        blisko = _has_network(point, layer, 50, delay)
        if blisko:
            odleglosci[medium] = "<=50m"
            cokolwiek_widoczne = True
            continue

        daleko = _has_network(point, layer, 200, delay)
        if daleko:
            odleglosci[medium] = "50-200m"
            cokolwiek_widoczne = True
        elif daleko is None and blisko is None:
            odleglosci[medium] = "brak danych"
        else:
            odleglosci[medium] = ">200m"

    return Utilities(odleglosci=odleglosci, w_zasiegu_uslugi=cokolwiek_widoczne)
