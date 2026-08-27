"""Normalizacja danych z ofert: cena, powierzchnia, jednostki, telefon.

Pulapki wymienione w sekcji 19.3 dokumentu i potwierdzone na zywych stronach:

* Morizon oddziela tysiace TWARDA SPACJA (\\xa0), nie zwykla. "649 000 zl"
  wyglada identycznie, a int() sie na tym wywraca.
* Powierzchnia bywa w arach i hektarach, przy czym "1,5 ha" nie zawsze ma
  jednostke tuz obok liczby. Bez parsera jednostek 1,5 ha ladowaloby w bazie
  jako 2 metry kwadratowe, czyli cena za m2 rosla dziesieciotysieckrotnie.
* Ceny bywaja podane jako "za m2" zamiast calkowitych.

Wszystko tutaj to funkcje czyste. Konwersje ukladow wspolrzednych ida przez
sources/geo.py, tu tylko sprawdzamy sensownosc.
"""

from __future__ import annotations

import hashlib
import re
from typing import Final

# Twarda spacja, waska spacja nierozdzielajaca i zwykla spacja
_SPACJE: Final = ("\xa0", " ", " ", " ")

# Mnozniki jednostek powierzchni w metrach kwadratowych
JEDNOSTKI_POWIERZCHNI: Final[dict[str, float]] = {
    "m2": 1.0,
    "m²": 1.0,
    "mkw": 1.0,
    "m": 1.0,
    "a": 100.0,
    "ar": 100.0,
    "ary": 100.0,
    "arow": 100.0,
    "ha": 10_000.0,
    "hektar": 10_000.0,
    "hektara": 10_000.0,
    "hektarow": 10_000.0,
}

# Granice zdroworozsadkowe. Poza nimi to blad parsowania, a nie oferta.
MIN_AREA_M2: Final = 50
MAX_AREA_M2: Final = 5_000_000  # 500 ha
MIN_PRICE_GROSZE: Final = 100_00  # 100 zl
MAX_PRICE_GROSZE: Final = 500_000_000_00  # 500 mln zl


class NormalizationError(ValueError):
    pass


def _odspacjuj(text: str) -> str:
    for spacja in _SPACJE:
        text = text.replace(spacja, "")
    return text


def parse_price_grosze(value: str | int | float | None) -> int | None:
    """Cena w groszach jako integer. Nigdy float, zgodnie z konwencja projektu.

    Obsluguje '649 000 zl' z twarda spacja, '649000,00', '649 000 PLN'.
    """
    if value is None:
        return None
    if isinstance(value, int | float):
        grosze = int(round(float(value) * 100))
        return grosze if MIN_PRICE_GROSZE <= grosze <= MAX_PRICE_GROSZE else None

    text = _odspacjuj(str(value)).lower()
    text = text.replace("zl", "").replace("zł", "").replace("pln", "")
    text = re.sub(r"[^\d,.]", "", text)
    if not text:
        return None

    # "649000,00" i "649000.00" znacza to samo; kropka bywa tez separatorem tysiecy
    if text.count(",") == 1 and text.count(".") == 0:
        text = text.replace(",", ".")
    elif text.count(".") > 1 or (text.count(".") == 1 and len(text.split(".")[-1]) == 3):
        text = text.replace(".", "")
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")

    try:
        grosze = int(round(float(text) * 100))
    except ValueError:
        return None
    return grosze if MIN_PRICE_GROSZE <= grosze <= MAX_PRICE_GROSZE else None


_AREA_RE = re.compile(
    r"(?P<liczba>\d+(?:[.,]\d+)?)\s*(?P<jednostka>m2|m²|mkw|ha|hektar\w*|ar\w*|a)\b",
    re.I,
)


def parse_area_m2(value: str | int | float | None) -> int | None:
    """Powierzchnia w metrach kwadratowych.

    '1,5 ha' -> 15000, '15 a' -> 1500, '1500 m2' -> 1500.
    Sama liczba bez jednostki jest traktowana jako metry, bo tak podaja JSON-LD.
    """
    if value is None:
        return None
    if isinstance(value, int | float):
        area = int(round(float(value)))
        return area if MIN_AREA_M2 <= area <= MAX_AREA_M2 else None

    text = _odspacjuj(str(value))
    match = _AREA_RE.search(text)
    if match:
        liczba = float(match.group("liczba").replace(",", "."))
        jednostka = match.group("jednostka").lower()
        mnoznik = JEDNOSTKI_POWIERZCHNI.get(jednostka)
        if mnoznik is None:
            # hektarow, arow itp.
            mnoznik = next(
                (m for j, m in JEDNOSTKI_POWIERZCHNI.items() if jednostka.startswith(j)),
                1.0,
            )
        area = int(round(liczba * mnoznik))
    else:
        cleaned = re.sub(r"[^\d,.]", "", text).replace(",", ".")
        if not cleaned:
            return None
        try:
            area = int(round(float(cleaned)))
        except ValueError:
            return None

    return area if MIN_AREA_M2 <= area <= MAX_AREA_M2 else None


def price_per_m2(price_grosze: int | None, area_m2: int | None) -> float | None:
    if not price_grosze or not area_m2:
        return None
    return price_grosze / 100.0 / area_m2


def hash_phone(phone: str | None) -> str | None:
    """SHA-256 numeru telefonu, WYLACZNIE do deduplikacji (sekcja 8.2).

    Numer jest wczesniej sprowadzany do samych cyfr, zeby '+48 501 178 937',
    '501178937' i '501-178-937' dawaly ten sam hash. Oryginal nigdy nie jest
    zwracany ani zapisywany.
    """
    if not phone:
        return None
    cyfry = re.sub(r"\D", "", phone)
    if cyfry.startswith("48") and len(cyfry) == 11:
        cyfry = cyfry[2:]
    if len(cyfry) < 9:
        return None
    return hashlib.sha256(cyfry.encode("ascii")).hexdigest()


def looks_like_land_offer(title: str | None, area_m2: int | None) -> bool:
    """Odsiew ofert, ktore nie sa dzialka, mimo ze trafily do kategorii.

    W kategorii dzialek pojawiaja sie gospodarstwa z zabudowaniami i lokale
    uzytkowe. Nie blokujemy ich twardo, ale runner moze je oznaczyc.
    """
    if area_m2 is None or not (MIN_AREA_M2 <= area_m2 <= MAX_AREA_M2):
        return False
    if not title:
        return True
    lowered = title.lower()
    return not any(
        slowo in lowered
        for slowo in ("mieszkanie", "apartament", "kawalerka", "lokal", "hala", "garaż")
    )


def coords_ok(lat: float | None, lon: float | None) -> bool:
    """Czy wspolrzedne w ogole leza w Polsce. Reszte sprawdza sources/geo.py."""
    if lat is None or lon is None:
        return False
    return 48.9 <= lat <= 55.0 and 13.9 <= lon <= 24.5
