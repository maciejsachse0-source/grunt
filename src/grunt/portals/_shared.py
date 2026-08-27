"""Kawalki wspolne dla adapterow portali.

Ten plik powstal dopiero przy trzecim i czwartym portalu, i to jest jego jedyne
uzasadnienie. CLAUDE.md zabrania warstw abstrakcji "na przyszlosc", ale Morizon,
Gratka i Otodom naprawde parsuja te same rzeczy: ceny w formacie "850000.00",
powierzchnie z twarda spacja, bloki JSON-LD i te same slowa o mediach w opisie.
Trzecia kopia tych samych 150 linii byla gorsza niz jeden wspolny plik.

Czego tu NIE MA i miec nie powinno: niczego, co dotyczy konkretnego portalu.
Slugi, adresy, limity paginacji i uklad danych zostaja w plikach adapterow, bo
to wlasnie one rozjezdzaja sie miedzy serwisami i to one sie psuja.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

_JSONLD_RE = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S)


def clean(value: Any) -> str | None:
    """Tekst bez nadmiarowych bialych znakow. None zostaje None."""
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None


def to_grosze(value: Any) -> int | None:
    """Cena w groszach. JSON-LD podaje '850000.00', HTML bywa z twarda spacja.

    Wszystkie kwoty w projekcie sa w groszach jako int (CLAUDE.md), wiec
    zaokraglenie robimy tu raz, a nie w kazdym adapterze osobno.
    """
    if value is None:
        return None
    text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return int(round(float(text) * 100))
    except ValueError:
        return None


def to_m2(value: Any) -> int | None:
    """Powierzchnia w m2 jako int (CLAUDE.md)."""
    if value is None:
        return None
    text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return int(round(float(text)))
    except ValueError:
        return None


def iter_jsonld(html: str) -> Iterable[Any]:
    """Kolejne bloki ld+json, z pominieciem tych, ktorych nie da sie sparsowac."""
    for match in _JSONLD_RE.finditer(html):
        try:
            yield json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue


def iter_jsonld_offers(html: str) -> Iterable[dict[str, Any]]:
    """Wszystkie obiekty Offer, niezaleznie od tego, jak gleboko sa zagniezdzone.

    Morizon i Gratka trzymaja je w Product > AggregateOffer > offers[], ale
    przechodzimy drzewo w calosci, zeby zmiana zagniezdzenia nie psula adaptera.
    """

    def walk(node: Any) -> Iterable[dict[str, Any]]:
        if isinstance(node, dict):
            if node.get("@type") == "Offer" and "url" in node:
                yield node
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    for block in iter_jsonld(html):
        yield from walk(block)


def first_jsonld_of_type(html: str, typ: str) -> dict[str, Any] | None:
    def walk(node: Any) -> dict[str, Any] | None:
        if isinstance(node, dict):
            if node.get("@type") == typ:
                return node
            for value in node.values():
                found = walk(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = walk(value)
                if found is not None:
                    return found
        return None

    for block in iter_jsonld(html):
        found = walk(block)
        if found is not None:
            return found
    return None


def canonical_url(html: str) -> str | None:
    match = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', html)
    return match.group(1) if match else None


def title_tag(html: str) -> str | None:
    match = re.search(r"<title>([^<]*)</title>", html)
    return clean(match.group(1)) if match else None


def og_image(html: str) -> str | None:
    match = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
    return match.group(1) if match else None


def thumb_from(offer: dict[str, Any], html: str) -> str | None:
    """Miniatura z JSON-LD, a w ostatecznosci z og:image.

    Zapisujemy URL, nigdy sam obrazek (CLAUDE.md).
    """
    image = offer.get("image")
    if isinstance(image, str) and image.startswith("http"):
        return image
    if isinstance(image, list) and image and isinstance(image[0], str):
        return image[0]
    return og_image(html)


# Wzorce zapisane BEZ diakrytykow: tekst ogloszenia przed porownaniem przechodzi
# przez fold_pl(), bo czesc ogloszen jest pisana bez ogonkow ("prad", "kanalizacja
# w drodze"), a czesc z nimi. Bez tego adapter gubi media zaleznie od tego,
# jak sprzedajacy ustawil klawiature.
MEDIA_PATTERNS: dict[str, tuple[str, ...]] = {
    "prad": ("prad", "energia elektryczna", "elektryczn"),
    "woda": ("wodociag", "woda miejska", "przylacze wody", "woda "),
    "gaz": ("gaz",),
    "kanalizacja": ("kanaliza",),
}

_PL_FOLD = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def fold_pl(text: str) -> str:
    """Usuniecie polskich diakrytykow do porownan tekstowych."""
    return text.translate(_PL_FOLD)


def media_flags(text: str) -> dict[str, Any] | None:
    """Flagi mediow wyciagniete z tresci ogloszenia.

    Zwracamy tylko to, co znalezione. Brak wzmianki NIE oznacza braku medium
    (regula "NULL to NULL" z CLAUDE.md), dlatego nie wpisujemy tu wartosci false.
    """
    if not text:
        return None
    lowered = fold_pl(text).lower()
    found = {
        medium: True
        for medium, needles in MEDIA_PATTERNS.items()
        if any(needle in lowered for needle in needles)
    }
    return found or None


def przeznaczenie_z_opisu(description: str, html: str) -> str | None:
    """Zdanie o MPZP albo planie miejscowym z tresci ogloszenia."""
    for source in (description, html):
        if not source:
            continue
        match = re.search(
            r"(?:MPZP|plan(?:em|u)? (?:miejscow|zagospodarowania))[^.]{0,160}",
            source,
            re.I,
        )
        if match:
            czysty = clean(re.sub(r"<[^>]+>", " ", match.group(0)))
            if czysty:
                return czysty[:300]
    return None


# Slowa, przy ktorych w ogole warto szukac zdania o dostepie do drogi. Samo
# "dojazd" nie wystarcza: Gratka opisuje ten sam fakt jako "Wjazd na dzialke
# BEZPOSREDNIO z drogi GMINNEJ" albo "polozona bezposrednio przy drodze
# gminnej", i oba zdania niosa dokladnie to, o co pyta bramka
# brak_dostepu_do_drogi. Sprawdzone na zywym ogloszeniu 2026-08-25.
_WYZWALACZ_DOJAZDU = (
    r"[^.]{0,80}(?:dojazd|droga dojazdowa|wjazd|przy drodze|przy drog[ae])[^.]{0,120}"
)


def dojazd_z_opisu(description: str) -> str | None:
    """Dostep do drogi, a nie czas dojazdu do miasta.

    Samo slowo "dojazd" lapie zdania marketingowe ("szybki dojazd do centrum
    w 20 minut"), ktore nie mowia nic o dostepie do drogi publicznej - a to
    jest czynnik gate'owy (mnoznik 0,35 w sekcji 5.3.5). Wymagamy wiec, zeby
    w zdaniu pojawilo sie takze slowo o samej drodze albo jej nawierzchni.
    """
    if not description:
        return None
    for match in re.finditer(_WYZWALACZ_DOJAZDU, description, re.I):
        fragment = re.sub(r"<[^>]+>", " ", match.group(0))
        if re.search(
            r"asfalt|utwardz|szutrow|gruntow|droga (?:gminn|powiatow|publiczn|wewnetrzn)"
            r"|slepa|serwitut|sluzebnos",
            fragment,
            re.I,
        ):
            return (clean(fragment) or "")[:200] or None
    return None


_NUXT_RE = re.compile(r'id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)


def nuxt_center(html: str) -> tuple[float | None, float | None]:
    """Wspolrzedne srodka mapy oferty ze splaszczonej struktury __NUXT_DATA__.

    Morizon i Gratka stoja na tym samym Nuxcie i maja identyczny uklad danych.
    Format trzyma wartosci w jednej tablicy, a obiekty odwoluja sie do nich
    indeksami: {"center": 102, "zoom": 105}, gdzie data[102] to
    {"latitude": 103, "longitude": 104}, a data[103] i data[104] to liczby.

    Szukamy klucza "center", bo latitude/longitude wystepuje takze w rogach
    bboxa dzielnicy (northeast, southwest) i naiwne wyszukanie pierwszej pary
    liczb daje punkt oddalony o kilkaset metrow. W snapshocie Gratki takich
    dodatkowych par jest cztery.
    """
    match = _NUXT_RE.search(html)
    if not match:
        return (None, None)
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return (None, None)
    if not isinstance(data, list):
        return (None, None)

    def resolve(index: Any) -> Any:
        return data[index] if isinstance(index, int) and 0 <= index < len(data) else None

    for node in data:
        if not (isinstance(node, dict) and "center" in node and "zoom" in node):
            continue
        center = resolve(node["center"])
        if not isinstance(center, dict):
            continue
        lat = resolve(center.get("latitude"))
        lon = resolve(center.get("longitude"))
        if isinstance(lat, int | float) and isinstance(lon, int | float):
            return (float(lat), float(lon))
    return (None, None)
