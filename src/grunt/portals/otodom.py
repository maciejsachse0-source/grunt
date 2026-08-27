"""Adapter Otodomu. Sekcja 18 dokumentu.

DOKUMENT MOWI, ZE OTODOM ZWRACA 403 I ZE JEDYNA DROGA JEST APIFY. Sprawdzone
ponownie 2026-08-25 uczciwym naglowkiem z adresem kontaktowym: **listing zwraca
200 i 1 MB HTML-a, a robots.txt konczy sie na "Allow: /"**. Sciezka wynikow nie
jest zabroniona zadna regula. Pomiar z sekcji 2.2 dokumentu byl wiec albo
chwilowy, albo dotyczyl innego naglowka. Adapter dziala bez posrednika i bez
kosztu miesiecznego. Gdyby portal kiedys zaczal odmawiac, wraca temat Apify -
ale nie wczesniej i nie "na wszelki wypadek".

Co jeszcze ustalono na zywym serwisie i co ksztaltuje ten plik:

1. PAGINACJA JEST DOZWOLONA, w odroznieniu od Morizona i Gratki.
   robots.txt zabrania konkretnych slotow reklamowych i "/*?*map=1", ale nie ma
   ani jednej reguly na "page=". W pomorskim jest 5 087 dzialek na 142 stronach
   po 36. Nie rozbijamy wiec regionu na powiaty: jedno zapytanie wojewodzkie
   plus paginacja jest tansze dla serwera niz 20 osobnych sesji.

2. DANE SA W __NEXT_DATA__, NIE W JSON-LD.
   Listing: props.pageProps.data.searchAds.items[] z id, slug, tytulem,
   totalPrice.value i areaInSquareMeters. Detal: props.pageProps.ad z komplet
   atrybutow. Parsujemy dane aplikacji, nie selektory CSS.

3. DETAL MA DOSTEP DO DROGI I MEDIA JAKO POLA, A NIE JAKO ZDANIA.
   target.Access_types (np. ["hard_surfaced"]) i target.Media_types (np.
   ["water", "electricity"]) to najlepsze zrodlo tych cech w calym projekcie:
   Morizon i Gratka wymagaja wylapywania ich z tresci ogloszenia regexem.
   target.Access_types zasila bramke brak_dostepu_do_drogi, ktora do tej pory
   nie miala zadnego wejscia.

4. WSPOLRZEDNE SA DOKLADNIEJSZE NIZ U KONKURENCJI, ALE NADAL PRZYBLIZONE.
   location.coordinates to konkretna para liczb, ale obok stoi
   location.mapDetails.radius = 100, czyli portal sam deklaruje rozmycie do
   100 m. Zostaje wiec geom_precision "approx", tak samo jak w Morizonie.
   Na liscie wspolrzednych NIE MA - sa dopiero na stronie detalu.

5. CZEGO NIE TYKAMY.
   Obiekt oferty zawiera agency, advertOwner, organisationAssignedMember
   i seller_id. Zadne z tych pol nie trafia do ListingDetail ani do raw.
   Sekcja 8.2 i CLAUDE.md: w bazie nie ma danych kontaktowych, jest URL.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from grunt.portals import _shared
from grunt.portals.base import ListingDetail, ListingStub

_NEXT_RE = re.compile(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
# identyfikator oferty siedzi na koncu sluga: ...-10-min-do-morza-ID4Bjm4
_OFFER_ID_RE = re.compile(r"-(ID[A-Za-z0-9]+)/?$")

# Ile stron wynikow bierzemy z jednego przebiegu. robots.txt nie stawia tu
# granicy, ale 142 strony na przebieg to 142 zadania do jednego serwisu w kilka
# minut. Limit jest nasz, nie ich, i wynika z sekcji 8.2 (higiena scrapingu).
MAX_PAGES_PER_RUN = 25

# Slownik przeznaczen z pola target.Type. Wartosci sa surowe i takie trafiaja do
# przeznaczenie_raw: segmentacje robi scoring/segments.py, nie adapter.
TYPY_DZIALKI: dict[str, str] = {
    "building": "budowlana",
    "agricultural": "rolna",
    "recreational": "rekreacyjna",
    "investment": "inwestycyjna",
    "industrial": "przemyslowa",
    "habitat": "siedliskowa",
    "forest": "lesna",
}

# target.Media_types -> nasze nazwy mediow z _shared.MEDIA_PATTERNS
MEDIA_Z_POLA: dict[str, str] = {
    "electricity": "prad",
    "water": "woda",
    "gas": "gaz",
    "sewage": "kanalizacja",
    "sewerage": "kanalizacja",
}


class OtodomAdapter:
    name = "otodom"
    base_url = "https://www.otodom.pl"
    delay_seconds = 2.0
    requires_js = False

    # --------------------------------------------------------------- adresy

    def list_urls(self, region_teryt: str) -> Iterable[str]:
        """Jeden adres na wojewodztwo. Paginacja robi reszte.

        Tu nie ma seeda ze slugami powiatow, bo nie jest potrzebny: robots.txt
        nie ogranicza paginacji, wiec jedno zapytanie wojewodzkie z kolejnymi
        stronami jest prostsze i tansze niz 20 osobnych.
        """
        wojewodztwo = WOJEWODZTWA.get(region_teryt[:2])
        if wojewodztwo is None:
            return
        yield f"{self.base_url}/pl/wyniki/sprzedaz/dzialka/{wojewodztwo}"

    def next_page_url(self, url: str, page: int) -> str | None:
        if page < 2 or page > MAX_PAGES_PER_RUN:
            return None
        base = url.split("?")[0]
        return f"{base}?page={page}"

    # ------------------------------------------------------------ parsowanie

    def parse_listing_page(self, html: str) -> list[ListingStub]:
        dane = next_data(html)
        items = _sciezka(dane, "props", "pageProps", "data", "searchAds", "items")
        if not isinstance(items, list):
            return []

        stubs: list[ListingStub] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug")
            if not isinstance(slug, str):
                continue
            offer_id = offer_id_from_slug(slug)
            if offer_id is None or offer_id in seen:
                continue
            seen.add(offer_id)

            stubs.append(
                ListingStub(
                    portal_offer_id=offer_id,
                    url=f"{self.base_url}/pl/oferta/{slug}",
                    price_grosze=_shared.to_grosze(_sciezka(item, "totalPrice", "value")),
                    area_m2=_shared.to_m2(item.get("areaInSquareMeters")),
                    title=_shared.clean(item.get("title")),
                ).with_hash()
            )
        return stubs

    def parse_detail(self, html: str) -> ListingDetail:
        dane = next_data(html)
        surowe_ad = _sciezka(dane, "props", "pageProps", "ad")
        ad: dict[str, Any] = surowe_ad if isinstance(surowe_ad, dict) else {}
        surowy_target = ad.get("target")
        target: dict[str, Any] = surowy_target if isinstance(surowy_target, dict) else {}

        slug = ad.get("slug")
        offer_id = offer_id_from_slug(slug) if isinstance(slug, str) else None

        lat = _liczba(_sciezka(ad, "location", "coordinates", "latitude"))
        lon = _liczba(_sciezka(ad, "location", "coordinates", "longitude"))

        # Opis sluzy wylacznie do wyciagniecia flag i nigdy nie jest zapisywany.
        # Przy Otodomie jest zreszta zapasem: cechy sa w polach target.
        opis = re.sub(r"<[^>]+>", " ", str(ad.get("description") or ""))

        return ListingDetail(
            portal_offer_id=offer_id or "",
            title=_shared.clean(ad.get("title")) or _shared.title_tag(html),
            price_grosze=_shared.to_grosze(target.get("Price") or _sciezka(ad, "price", "value")),
            area_m2=_shared.to_m2(target.get("Area")),
            lat=lat,
            lon=lon,
            geom_precision="approx" if lat is not None else None,
            przeznaczenie_raw=przeznaczenie_z_pola(target)
            or _shared.przeznaczenie_z_opisu(opis, html),
            media_raw=media_z_pola(target) or _shared.media_flags(opis),
            road_access_raw=dojazd_z_pola(target) or _shared.dojazd_z_opisu(opis),
            thumb_url=_shared.og_image(html),
            raw={
                "zrodlo_cech": "target" if target else "opis",
                "promien_m": _sciezka(ad, "location", "mapDetails", "radius"),
                "ma_opis": bool(opis.strip()),
            },
        )


# Otodom uzywa nazw wojewodztw w adresie. Rozszerzamy slownik, gdy projekt
# wyjdzie poza pomorskie - dzis jedno wojewodztwo to nie jest uproszczenie,
# tylko zakres z REGION_TERYT.
WOJEWODZTWA: dict[str, str] = {
    "22": "pomorskie",
}


# ------------------------------------------------------------------ pomocnicze


def next_data(html: str) -> Any:
    """Zawartosc __NEXT_DATA__ jako struktura Pythona. None, gdy jej nie ma."""
    match = _NEXT_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _sciezka(node: Any, *klucze: str) -> Any:
    """Zejscie po slownikach bez wybuchania na brakujacym kluczu."""
    for klucz in klucze:
        if not isinstance(node, dict):
            return None
        node = node.get(klucz)
    return node


def _liczba(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def offer_id_from_slug(slug: str) -> str | None:
    """Identyfikator z konca sluga. 'dzialka-...-ID4Bjm4' -> 'ID4Bjm4'.

    Bierzemy identyfikator ze sluga, a nie pole 'id' (liczbe), bo to slug stoi
    w adresie oferty. Dzieki temu portal_offer_id da sie odtworzyc z samego URL,
    tak samo jak w pozostalych adapterach.
    """
    match = _OFFER_ID_RE.search(slug.split("?")[0])
    return match.group(1) if match else None


def przeznaczenie_z_pola(target: dict[str, Any]) -> str | None:
    """Przeznaczenie z target.Type, np. ['building'] -> 'budowlana'.

    Nieznany kod oddajemy surowy, zamiast zwracac None: lepiej, zeby segments.py
    dostal 'orchard' i go nie rozpoznal, niz zebysmy po cichu zgubili informacje.
    """
    typy = target.get("Type")
    if not isinstance(typy, list) or not typy:
        return None
    nazwy = [TYPY_DZIALKI.get(str(t), str(t)) for t in typy if t]
    return ", ".join(nazwy) or None


def media_z_pola(target: dict[str, Any]) -> dict[str, Any] | None:
    """Media z target.Media_types.

    Jak w _shared.media_flags: zapisujemy tylko to, co znalezione. Brak medium
    na liscie NIE znaczy, ze go nie ma (regula "NULL to NULL" z CLAUDE.md),
    wiec nie wpisujemy tu wartosci false.
    """
    typy = target.get("Media_types")
    if not isinstance(typy, list) or not typy:
        return None
    found = {MEDIA_Z_POLA[str(t)]: True for t in typy if str(t) in MEDIA_Z_POLA}
    return found or None


def dojazd_z_pola(target: dict[str, Any]) -> str | None:
    """Dostep do drogi z target.Access_types, np. ['hard_surfaced'].

    Oddajemy surowa wartosc, bo przelozenie na trojstan 0/1/2 z sekcji 5.3.5
    nalezy do warstwy wzbogacania, a nie do adaptera. Adapter ma dostarczyc
    fakt z portalu, a nie go zinterpretowac.
    """
    typy = target.get("Access_types")
    if not isinstance(typy, list) or not typy:
        return None
    return ", ".join(str(t) for t in typy if t) or None
