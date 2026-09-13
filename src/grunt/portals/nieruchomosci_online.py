"""Adapter Nieruchomosci-online. Sekcja 2.2 dokumentu: najbogatsze pola dla dzialek.

Ustalenia z zywego serwisu 2026-08-21:

1. WEJSCIE JEST NA SUBDOMENIE WOJEWODZTWA.
   Serwis dzieli sie na subdomeny miejscowosci (gdansk.nieruchomosci-online.pl),
   ale istnieje takze subdomena wojewodzka: pomorskie.nieruchomosci-online.pl.
   Dzieki temu nie trzeba obchodzic kilkuset miejscowosci osobno.
   W pomorskim jest 6 282 dzialek po 41 na stronie, czyli ok. 154 strony.

2. ROBOTS.TXT NAS NIE OGRANICZA.
   Plik zawiera grupy tylko dla Googlebota, bingbota, botow reklamowych i liste
   blokowanych crawlerow SEO (dotbot, AhrefsBot, MJ12bot...). Grupy "User-agent: *"
   nie ma w ogole, wiec zadna regula nie dotyczy naszego klienta. Mimo to
   trzymamy 2 s odstepu, bo grupa bingbota deklaruje Crawl-delay: 1.

3. PAGINACJA TO ?p=N.
   Sprawdzone empirycznie: ?strona=, ?page= i ?o= sa ignorowane i zwracaja
   strone pierwsza. Przy ?p=2 wspolne ze strona 1 sa tylko dwie oferty
   (sloty promowane), wiec paginacja dziala poprawnie.

4. JSON-LD MA DANE, KTORYCH NIE MA MORIZON.
   Blok Product zawiera geo (7 miejsc po przecinku) oraz additionalProperty:
   Land area, Land dimensions ("24m x 25m", czyli front dzialki), Land type,
   Land shape, Land slope. Do tego w HTML sa etykiety Media, Dojazd, Ksztalt,
   Forma wlasnosci i data aktualizacji oferty.

5. WSPOLRZEDNE TEZ SA PRZYBLIZONE.
   Dla oferty z Katow Rybackich (835 m2) ULDK zwraca dzialke 18 983 m2, bo
   ogloszenie dotyczy dzialki wydzielanej z wiekszej ("powstanie z podzialu
   dzialki nr 273"). Stad geom_precision = "approx", tak samo jak na Morizonie.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterable
from typing import Any

from grunt.portals.base import ListingDetail, ListingStub
from grunt.portals.morizon import fold_pl

# TERYT wojewodztwa -> subdomena serwisu
WOJEWODZTWA: dict[str, str] = {
    "02": "dolnoslaskie",
    "04": "kujawsko-pomorskie",
    "06": "lubelskie",
    "08": "lubuskie",
    "10": "lodzkie",
    "12": "malopolskie",
    "14": "mazowieckie",
    "16": "opolskie",
    "18": "podkarpackie",
    "20": "podlaskie",
    "22": "pomorskie",
    "24": "slaskie",
    "26": "swietokrzyskie",
    "28": "warminsko-mazurskie",
    "30": "wielkopolskie",
    "32": "zachodniopomorskie",
}

_JSONLD_RE = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S)
_OFFER_ID_RE = re.compile(r"/(\d{6,})\.html")

MIESIACE = {
    "stycznia": 1,
    "lutego": 2,
    "marca": 3,
    "kwietnia": 4,
    "maja": 5,
    "czerwca": 6,
    "lipca": 7,
    "sierpnia": 8,
    "wrzesnia": 9,
    "pazdziernika": 10,
    "listopada": 11,
    "grudnia": 12,
}


class NieruchomosciOnlineAdapter:
    name = "nieruchomosci_online"
    base_url = "https://www.nieruchomosci-online.pl"
    delay_seconds = 2.0
    requires_js = False

    # --------------------------------------------------------------- adresy

    def list_urls(self, region_teryt: str) -> Iterable[str]:
        slug = WOJEWODZTWA.get(region_teryt[:2])
        if slug:
            yield f"https://{slug}.nieruchomosci-online.pl/dzialki/"

    def next_page_url(self, url: str, page: int) -> str | None:
        if page < 2:
            return None
        return f"{url.split('?')[0]}?p={page}"

    # ------------------------------------------------------------ parsowanie

    def parse_listing_page(self, html: str) -> list[ListingStub]:
        stubs: list[ListingStub] = []
        seen: set[str] = set()

        for offer in _iter_offers(html):
            url = offer.get("url")
            if not isinstance(url, str):
                continue
            offer_id = offer_id_from_url(url)
            if offer_id is None or offer_id in seen:
                continue
            seen.add(offer_id)

            item = offer.get("itemOffered") or {}
            floor = item.get("floorSize") or {}

            stubs.append(
                ListingStub(
                    portal_offer_id=offer_id,
                    url=url,
                    price_grosze=_to_grosze(offer.get("price")),
                    area_m2=_to_m2(floor.get("value")),
                    title=_clean(offer.get("name")),
                ).with_hash()
            )
        return stubs

    def parse_detail(self, html: str) -> ListingDetail:
        # Na stronie oferty blok nazywa sie RealEstateListing, na listingu Product.
        product = _first_of_type(html, ("RealEstateListing", "Product", "Accommodation")) or {}
        offer = _first_of_type(html, ("Offer",)) or {}
        canonical = _canonical(html)

        geo = product.get("geo") or {}
        lat = _to_float(geo.get("latitude"))
        lon = _to_float(geo.get("longitude"))

        extra = additional_properties(product)
        labels = html_labels(html)

        return ListingDetail(
            portal_offer_id=offer_id_from_url(canonical or "") or "",
            title=_clean(product.get("name")) or _title(html),
            price_grosze=_to_grosze(offer.get("price")),
            area_m2=_to_m2(extra.get("land area"))
            or _to_m2((product.get("floorSize") or {}).get("value")),
            lat=lat,
            lon=lon,
            geom_precision="approx" if lat is not None else None,
            przeznaczenie_raw=labels.get("rodzaj dzialki") or extra.get("land type"),
            media_raw=media_from_label(labels.get("media")),
            road_access_raw=labels.get("dojazd"),
            ksztalt_raw=labels.get("ksztalt") or extra.get("land shape"),
            forma_wlasnosci_raw=labels.get("forma wlasnosci"),
            thumb_url=_thumb(product, html),
            # UWAGA: blok RealEstateListing zawiera takze pole "agent" z danymi
            # posrednika i pelny "description". Zadne z nich nie trafia do raw
            # ani nigdzie dalej (sekcja 8.2).
            raw={
                "wymiary": extra.get("land dimensions"),
                "front_m": front_from_dimensions(extra.get("land dimensions")),
                "ukszaltowanie": extra.get("land slope"),
                "zaktualizowano": _iso(
                    parse_date_any(product.get("datePosted"))
                    or parse_pl_date(labels.get("zaktualizowane"))
                ),
                "canonical": canonical,
            },
        )


# ------------------------------------------------------------------ pomocnicze


def offer_id_from_url(url: str) -> str | None:
    match = _OFFER_ID_RE.search(url)
    return match.group(1) if match else None


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None


def _to_grosze(value: Any) -> int | None:
    if value is None:
        return None
    text = re.sub(r"[^\d.,]", "", str(value).replace("\xa0", "")).replace(",", ".")
    try:
        return int(round(float(text) * 100))
    except ValueError:
        return None


def _to_m2(value: Any) -> int | None:
    """Powierzchnia bywa podana jako '835.00m²' albo '835,00'."""
    if value is None:
        return None
    text = re.sub(r"[^\d.,]", "", str(value).replace("\xa0", "")).replace(",", ".")
    try:
        return int(round(float(text)))
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _iter_jsonld(html: str) -> Iterable[Any]:
    for match in _JSONLD_RE.finditer(html):
        try:
            yield json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue


def _iter_offers(html: str) -> Iterable[dict[str, Any]]:
    def walk(node: Any) -> Iterable[dict[str, Any]]:
        if isinstance(node, dict):
            if "Offer" in _types_of(node) and "url" in node:
                yield node
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    for block in _iter_jsonld(html):
        yield from walk(block)


def _types_of(node: dict[str, Any]) -> tuple[str, ...]:
    """@type bywa napisem albo lista.

    Na listingu blok oferty ma @type "Product", na stronie oferty
    "RealEstateListing", a schema.org dopuszcza tez liste typow. Porownanie
    "node.get('@type') in types" cicho przegapiaeloby dwa z tych trzech
    przypadkow i detal wracalby bez wspolrzednych.
    """
    value = node.get("@type")
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    return ()


def _first_of_type(html: str, types: tuple[str, ...]) -> dict[str, Any] | None:
    def walk(node: Any) -> dict[str, Any] | None:
        if isinstance(node, dict):
            if set(_types_of(node)) & set(types):
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

    for block in _iter_jsonld(html):
        found = walk(block)
        if found is not None:
            return found
    return None


def additional_properties(product: dict[str, Any]) -> dict[str, str]:
    """PropertyValue z JSON-LD jako slownik o kluczach malymi literami."""
    out: dict[str, str] = {}
    for item in product.get("additionalProperty") or []:
        if isinstance(item, dict) and item.get("name"):
            out[str(item["name"]).strip().lower()] = str(item.get("value") or "").strip()
    return out


# Etykiety wystepuja w kilku znacznikach: <span>Media:</span> oraz
# <strong>Forma wlasnosci:</strong>. Ograniczenie do samego <span> gubilo
# forme wlasnosci, czyli pole potrzebne do wykrycia udzialow i uzytkowania
# wieczystego.
_LABEL_RE = re.compile(
    r"<(?:span|strong|b|dt|th)[^>]*>\s*([A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż ]{3,28}):\s*</(?:span|strong|b|dt|th)>"
    r"\s*(?:<[^>]+>\s*)*([^<]{1,80})"
)


def html_labels(html: str) -> dict[str, str]:
    """Pary etykieta-wartosc z karty oferty, klucze bez polskich znakow."""
    out: dict[str, str] = {}
    for match in _LABEL_RE.finditer(html):
        key = fold_pl(match.group(1).strip()).lower()
        value = re.sub(r"\s+", " ", match.group(2)).strip()
        if value and key not in out:
            out[key] = value
    return out


def media_from_label(value: str | None) -> dict[str, Any] | None:
    """'gaz, prąd, woda' -> {'gaz': True, 'prad': True, 'woda': True}.

    Wymienione media sa pewne. Niewymienione zostaja nieznane, a nie faluszywe:
    regula "NULL to NULL" z CLAUDE.md.
    """
    if not value:
        return None
    slownik = {
        "prad": "prad",
        "elektr": "prad",
        "woda": "woda",
        "wodociag": "woda",
        "gaz": "gaz",
        "kanaliz": "kanalizacja",
        "szambo": "szambo",
        "oczyszczalnia": "oczyszczalnia",
    }
    lowered = fold_pl(value).lower()
    found = {target: True for needle, target in slownik.items() if needle in lowered}
    return found or None


def front_from_dimensions(value: str | None) -> float | None:
    """'24m x 25m' -> 24.0. Front to krotszy bok przy drodze, wiec bierzemy mniejszy.

    Sekcja 5.3.6: front ponizej 18 m przy zabudowie wolnostojacej to problem,
    wiec ta liczba realnie wchodzi do scoringu.
    """
    if not value:
        return None
    numbers = [float(n.replace(",", ".")) for n in re.findall(r"(\d+(?:[.,]\d+)?)\s*m", value)]
    return min(numbers) if len(numbers) >= 2 else None


def parse_date_any(value: str | None) -> dt.date | None:
    """Data z pola datePosted albo z etykiety w HTML.

    Serwis zwraca w datePosted lancuch wadliwy wedlug ISO 8601:
    "2026-07-13CEST20:53:48Z" - nazwa strefy jest wklejona w srodek. Zamiast
    walczyc z takim zapisem bierzemy z niego sam prefiks z data.
    """
    if not value:
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value.strip())
    if match:
        try:
            return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return parse_pl_date(value)


def parse_pl_date(value: str | None) -> dt.date | None:
    """'10 sierpnia 2026' -> date(2026, 8, 10)."""
    if not value:
        return None
    match = re.search(r"(\d{1,2})\s+([a-zA-ZąćęłńóśźżĄ]+)\s+(\d{4})", value)
    if not match:
        return None
    month = MIESIACE.get(fold_pl(match.group(2)).lower())
    if not month:
        return None
    try:
        return dt.date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def _iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value else None


def _canonical(html: str) -> str | None:
    match = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', html)
    return match.group(1) if match else None


def _title(html: str) -> str | None:
    match = re.search(r"<title>([^<]*)</title>", html)
    return _clean(match.group(1)) if match else None


def _thumb(product: dict[str, Any], html: str) -> str | None:
    image = product.get("image")
    if isinstance(image, str) and image.startswith("http"):
        return image
    if isinstance(image, list) and image and isinstance(image[0], str):
        return image[0]
    match = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
    return match.group(1) if match else None
