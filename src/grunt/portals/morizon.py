"""Adapter Morizona. Sekcja 18 dokumentu.

Co ustalono na zywym serwisie 2026-08-21 i co ksztaltuje ten plik:

1. ROBOTS.TXT ZABRANIA GLEBOKIEJ PAGINACJI I SORTOWANIA.
   "Disallow: *page=*" z wyjatkami "Allow: *page=2$" ... "*page=10$", a takze
   "Disallow: */najnowsze/*" i "Disallow: *sort=*". W pomorskim jest 4 952
   dzialek na 142 stronach po 35, wiec jedno zapytanie wojewodzkie daje
   legalnie najwyzej 350 ofert. Dlatego list_urls rozbija region na powiaty.
   To takze uniewaznia pomysl z sekcji 18.2, zeby skanowac listing posortowany
   po dacie i przerywac na pierwszej niezmienionej stronie: sortowac nie wolno.
   Oszczednosc DIFF zostaje, bo bierze sie z niepobierania detali, nie z sortu.

2. LISTING MA KOMPLETNY JSON-LD.
   Blok Product > AggregateOffer > offers[] zawiera cene, powierzchnie, adres
   i URL kazdej oferty. Parsujemy dane, nie selektory CSS, wiec przebudowa
   szablonu nie psuje adaptera.

3. WSPOLRZEDNE SA W __NUXT_DATA__ I SA PRZYBLIZONE.
   Struktura to splaszczona tablica z indeksami: {"center":125,"zoom":128}
   wskazuje na {"latitude":126,"longitude":127}, a dopiero pod tymi indeksami
   leza liczby. Uwaga: na tej samej stronie sa tez rogi bboxa dzielnicy
   (northeast/southwest), ktore latwo wziac za wspolrzedne oferty.
   Sprawdzenie na ofercie z ul. Wieckiej: punkt trafia we wlasciwy obreb,
   ale ULDK zwraca dzialke o 886 m2 przy deklarowanych 1115 m2. Stad
   geom_precision = "approx": to podpowiedz, gdzie szukac dzialki, a nie jej
   identyfikacja.

4. PARAMETRY DZIALKI SA W OPISIE, NIE W POLACH.
   MPZP, media i dojazd wystepuja jako zdania w tresci ogloszenia. Wyciagamy
   z nich flagi, ale samego opisu nie zapisujemy (sekcja 8.2).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from grunt.config import REPO_ROOT
from grunt.portals import _shared
from grunt.portals.base import ListingDetail, ListingStub

SEED = REPO_ROOT / "db" / "seed" / "morizon_powiaty_pomorskie.json"

# robots.txt: Allow konczy sie na page=10
MAX_PAGE_ALLOWED = 10

_JSONLD_RE = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S)
# identyfikator oferty siedzi na koncu sluga: ...-568m2-mzn2047606024
_OFFER_ID_RE = re.compile(r"-(mzn\d+)/?$")


class MorizonAdapter:
    name = "morizon"
    base_url = "https://www.morizon.pl"
    delay_seconds = 2.0
    requires_js = False

    # --------------------------------------------------------------- adresy

    def list_urls(self, region_teryt: str) -> Iterable[str]:
        """Jedno zapytanie na powiat. Powod: limit 10 stron w robots.txt."""
        data = json.loads(SEED.read_text(encoding="utf-8"))
        for teryt, slug in sorted(data["powiaty"].items()):
            if teryt.startswith(region_teryt):
                yield f"{self.base_url}/dzialki/{slug}/"

    def next_page_url(self, url: str, page: int) -> str | None:
        """None powyzej strony 10: dalej robots.txt nie pozwala."""
        if page < 2 or page > MAX_PAGE_ALLOWED:
            return None
        base = url.split("?")[0]
        return f"{base}?page={page}"

    # ------------------------------------------------------------ parsowanie

    def parse_listing_page(self, html: str) -> list[ListingStub]:
        stubs: list[ListingStub] = []
        seen: set[str] = set()

        for offer in _iter_jsonld_offers(html):
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
        offer = _first_jsonld_of_type(html, "Offer") or {}
        canonical = _canonical_url(html)
        offer_id = offer_id_from_url(canonical or offer.get("url") or "")

        lat, lon = _nuxt_center(html)
        # Opis sluzy wylacznie do wyciagniecia flag i nigdy nie jest zapisywany.
        description = str(offer.get("description") or "")

        return ListingDetail(
            portal_offer_id=offer_id or "",
            title=_clean(offer.get("name")) or _title(html),
            price_grosze=_to_grosze(offer.get("price")),
            area_m2=_area_from_html(html),
            lat=lat,
            lon=lon,
            geom_precision="approx" if lat is not None else None,
            przeznaczenie_raw=_przeznaczenie(description, html),
            media_raw=media_flags(description),
            road_access_raw=_dojazd(description),
            thumb_url=_thumb(offer, html),
            raw={
                "jsonld_typ": offer.get("@type"),
                "canonical": canonical,
                "ma_opis": bool(description),
            },
        )


# ------------------------------------------------------------------ pomocnicze


def offer_id_from_url(url: str) -> str | None:
    match = _OFFER_ID_RE.search(url.split("?")[0])
    return match.group(1) if match else None


# Nazwy zachowane, bo importuje je test snapshotowy i reszta pliku. Rachunek
# jest teraz w portals/_shared.py, wspolny z Gratka i Otodomem.
_clean = _shared.clean
_to_grosze = _shared.to_grosze
_to_m2 = _shared.to_m2
_iter_jsonld_offers = _shared.iter_jsonld_offers
_first_jsonld_of_type = _shared.first_jsonld_of_type


_nuxt_center = _shared.nuxt_center


_canonical_url = _shared.canonical_url
_title = _shared.title_tag
fold_pl = _shared.fold_pl
media_flags = _shared.media_flags
MEDIA_PATTERNS = _shared.MEDIA_PATTERNS
_przeznaczenie_opis = _shared.przeznaczenie_z_opisu
_dojazd = _shared.dojazd_z_opisu


def _area_from_html(html: str) -> int | None:
    """Powierzchnia z naglowka oferty, np. 'Dzialka na sprzedaz 1 115 m2'."""
    for pattern in (
        r"<title>[^<]*?(\d[\d\s ]*)\s*m²",
        r'"floorSize"[^}]*?"value"\s*:\s*"?([\d.,]+)',
        r"(\d[\d\s ]*)\s*m²\s*</",
    ):
        match = re.search(pattern, html)
        if match:
            value = _to_m2(match.group(1))
            if value:
                return value
    return None


def _przeznaczenie(description: str, html: str) -> str | None:
    return _shared.przeznaczenie_z_opisu(description, html)


def _thumb(offer: dict[str, Any], html: str) -> str | None:
    return _shared.thumb_from(offer, html)
