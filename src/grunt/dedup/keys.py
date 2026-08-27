"""Klucze i miary podobienstwa uzywane przy deduplikacji.

Wszystko tutaj to funkcje czyste. Trzy odstepstwa od sekcji 4.3 dokumentu,
kazde wymuszone przez to, co faktycznie mamy w bazie:

1. Zamiast geohasha precyzji 7 blokujemy po siatce metrycznej. Geohash operuje
   na stopniach, a my trzymamy geometrie w EPSG:2180, czyli w metrach. Siatka
   500 m robi dokladnie to samo (redukcja par z O(n^2) do O(n)), ale bez
   przeliczania tam i z powrotem, wiec bez okazji do pomylenia osi.
2. Odleglosc weryfikujemy potem wprost, w metrach. Geohash mial te wade, ze
   dwie oferty po dwoch stronach granicy komorki nigdy nie trafialy do pary.
   Siatka ma ja tak samo, dlatego pary bierzemy z komorki i osmiu sasiednich.
3. Zamiast RapidFuzz token_set_ratio liczymy pokrycie zbiorow tokenow. Tytuly
   ofert to kilka slow, wiec calej maszynerii RapidFuzz (a wiec i zaleznosci)
   nie potrzebujemy. Miara jest inna niz token_set_ratio, stad inna nazwa.
4. Doszedl czwarty klucz, ktorego w dokumencie nie ma: adres pliku miniatury.
   Uzasadnienie i pomiar sa przy klucz_obrazu().
"""

from __future__ import annotations

import base64
import re
import unicodedata
from typing import Final

# Bok komorki siatki w metrach. 500 m przy tolerancji powierzchni +/-3%
# zostawia w bloku pojedyncze oferty, a nie setki.
ROZMIAR_KOMORKI_M: Final = 500

# Slowa, ktore wystepuja w prawie kazdym tytule ogloszenia o dzialce i przez to
# nic nie roznicuja. Bez tej listy dwie przypadkowe dzialki maja pokrycie 0,6.
STOPWORDY: Final[frozenset[str]] = frozenset(
    {
        "dzialka",
        "dzialki",
        "dzialke",
        "grunt",
        "gruntu",
        "teren",
        "na",
        "nad",
        "pod",
        "przy",
        "w",
        "we",
        "z",
        "za",
        "do",
        "i",
        "oraz",
        "sprzedam",
        "sprzedaz",
        "sprzedazy",
        "oferta",
        "okazja",
        "polecam",
        "m2",
        "mkw",
        "ar",
        "ary",
        "arow",
        "ha",
        "zl",
        "pln",
    }
)

_NIEALFANUM = re.compile(r"[^0-9a-z]+")


def bez_ogonkow(tekst: str) -> str:
    """Polskie znaki na ascii. "Kąty Rybackie" i "Katy Rybackie" to jedno miejsce."""
    rozlozony = unicodedata.normalize("NFKD", tekst.replace("ł", "l").replace("Ł", "L"))
    return "".join(znak for znak in rozlozony if not unicodedata.combining(znak))


def tokeny(tytul: str | None) -> frozenset[str]:
    """Tytul na zbior znaczacych tokenow. Puste wejscie daje pusty zbior."""
    if not tytul:
        return frozenset()
    oczyszczony = _NIEALFANUM.sub(" ", bez_ogonkow(tytul).lower())
    return frozenset(
        token for token in oczyszczony.split() if len(token) > 1 and token not in STOPWORDY
    )


def pokrycie_tokenow(a: frozenset[str], b: frozenset[str]) -> float:
    """Czesc wspolna podzielona przez mniejszy zbior, zakres 0-1.

    Celowo nie Jaccard: jeden portal daje "Dzialka budowlana Kokoszki 1115 m2",
    drugi "Kokoszki, dzialka z warunkami zabudowy, blisko obwodnicy". Jaccard
    karalby za dlugosc drugiego tytulu, choc krotszy jest w calosci zawarty
    w dluzszym. Pusty zbior po ktorejkolwiek stronie to brak sygnalu, czyli 0.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def komorka(easting: float, northing: float, rozmiar_m: int = ROZMIAR_KOMORKI_M) -> tuple[int, int]:
    """Komorka siatki metrycznej dla punktu w EPSG:2180."""
    return (int(easting // rozmiar_m), int(northing // rozmiar_m))


def sasiednie_komorki(cel: tuple[int, int]) -> list[tuple[int, int]]:
    """Komorka i osiem sasiednich. Oferta przy krawedzi ma szanse na pare."""
    x, y = cel
    return [(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]


def dystans_m(
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    """Odleglosc euklidesowa w metrach. EPSG:2180 jest ukladem metrycznym."""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def powierzchnia_zgodna(a: int | None, b: int | None, tolerancja: float = 0.03) -> bool:
    """Bucket powierzchni +/-3% z sekcji 4.3. Brak powierzchni to brak zgody."""
    if not a or not b:
        return False
    return abs(a - b) <= tolerancja * min(a, b)


def cena_zgodna(a: int | None, b: int | None, tolerancja: float = 0.05) -> bool:
    """Ta sama dzialka bywa na dwoch portalach w dwoch cenach, ale nie w kazdej."""
    if not a or not b:
        return False
    return abs(a - b) <= tolerancja * min(a, b)


def bity(wartosc: str | int | None) -> int | None:
    """pHash z bazy do inta. BIT(64) wraca z psycopg jako ciag zer i jedynek."""
    if wartosc is None:
        return None
    if isinstance(wartosc, int):
        return wartosc
    oczyszczona = wartosc.strip()
    if not oczyszczona:
        return None
    if set(oczyszczona) <= {"0", "1"}:
        return int(oczyszczona, 2)
    return int(oczyszczona, 16)


def hamming(a: str | int | None, b: str | int | None) -> int | None:
    """Odleglosc Hamminga dwoch pHashy. None, gdy ktoregos nie ma."""
    left, right = bity(a), bity(b)
    if left is None or right is None:
        return None
    return (left ^ right).bit_count()


# Miniatury Morizona i Gratki chodza przez ten sam przekaznik:
# img1.staticmorizon.com.pl/thumb/<base64 adresu zrodlowego>. Po rozkodowaniu
# oba portale pokazuja ten sam plik na d-gr.cdngr.pl, wiec adres zrodlowy jest
# gotowym twardym kluczem - nie trzeba ani pobierac obrazu, ani liczyc pHasha,
# ani dokladac zaleznosci do obrazow.
_THUMB_RE = re.compile(r"/thumb/([A-Za-z0-9_\-]+=*)")


def klucz_obrazu(thumb_url: str | None) -> str | None:
    """Adres pliku miniatury sprowadzony do postaci porownywalnej miedzy portalami.

    Pomiar na 2 413 miniaturach z bazy (25.08.2026), ktory decyduje o tym, ze
    ten klucz jest TWARDY, a nie skladnikiem punktacji:

    * ani razu ten sam klucz nie wystapil w dwoch ofertach tego samego portalu.
      Obawa z sekcji 4.3 o agencje wrzucajaca ten sam baner na kazde ogloszenie
      po prostu sie nie zmaterializowala;
    * 238 kluczy wystapilo na dwoch portalach naraz i w 238 przypadkach na 238
      cena byla identyczna co do grosza, a w 237 na 238 takze powierzchnia.

    Dlaczego to nie jest to samo co pHash: pHash odpowiada na pytanie "czy te
    dwa obrazy wygladaja podobnie" i wymaga pobrania obu. Tu porownujemy adres
    tego samego pliku na tym samym serwerze, czyli tozsamosc, a nie podobienstwo.

    Adres spoza przekaznika oddajemy bez parametrow zapytania: dla portalu
    z wlasnym CDN-em plik nadal identyfikuje oferte, tylko nie skleja sie
    z niczym z zewnatrz.
    """
    if not thumb_url:
        return None
    match = _THUMB_RE.search(thumb_url)
    if match:
        zakodowany = match.group(1)
        # Padding "=" bywa uciety w adresie, wiec dokladamy go sami.
        uzupelniony = zakodowany + "=" * (-len(zakodowany) % 4)
        try:
            rozkodowany = base64.urlsafe_b64decode(uzupelniony).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            rozkodowany = ""
        if rozkodowany.startswith("http"):
            return rozkodowany.split("?")[0]
    return thumb_url.split("?")[0]
