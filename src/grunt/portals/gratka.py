"""Adapter Gratki. Sekcja 18 dokumentu.

Co ustalono na zywym serwisie 2026-08-25 i co ksztaltuje ten plik:

1. ROBOTS.TXT MA TE SAMA KONSTRUKCJE CO MORIZON, co do znaku.
   "Disallow: *page=*" z wyjatkami "Allow: *page=2$" ... "*page=10$", do tego
   "Disallow: /*sort=*" i "Disallow: /mapa/*". Wniosek jest wiec ten sam:
   glebokiej paginacji nie wolno, sortowac nie wolno, a region rozbijamy na
   powiaty. Nie jest to przypadek - Gratka i Morizon naleza do tej samej grupy
   i dziela nawet CDN obrazkow (img1.staticmorizon.com.pl w URL-ach Gratki).

2. SLUG POWIATU MA DWA KSZTALTY.
   Powiaty ziemskie sa jako "powiat-gdanski", a miasta na prawach powiatu jako
   "gdansk", "gdynia", "slupsk", "sopot". Wszystkie 20 slugow pomorskiego jest
   w db/seed/gratka_powiaty_pomorskie.json i kazdy zostal sprawdzony zapytaniem.

3. LISTING MA KOMPLETNY JSON-LD, tak jak Morizon.
   Product > AggregateOffer > offers[] z cena, powierzchnia (itemOffered.
   floorSize), adresem i URL-em. Parsujemy dane, nie selektory CSS.

4. WSPOLRZEDNE SA W __NUXT_DATA__ I SA PRZYBLIZONE.
   Uklad jest identyczny jak w Morizonie, wiec obsluguje go ten sam
   _shared.nuxt_center. Na stronie detalu sa dodatkowo cztery inne pary
   latitude/longitude (rogi bboxow), ktore latwo wziac za wspolrzedne oferty -
   dlatego szukamy po kluczu "center", a nie pierwszej pary liczb.
   geom_precision zostaje "approx": to podpowiedz, gdzie szukac dzialki.

5. JSON-LD DETALU MA POLE "seller" I NIGDY GO NIE TYKAMY.
   Zawiera nazwe i dane biura. Sekcja 8.2 i CLAUDE.md: do bazy nie trafiaja
   zadne dane kontaktowe, a opis sluzy wylacznie do wyciagniecia flag.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from grunt.config import REPO_ROOT
from grunt.portals import _shared
from grunt.portals.base import ListingDetail, ListingStub

SEED = REPO_ROOT / "db" / "seed" / "gratka_powiaty_pomorskie.json"

# robots.txt: Allow konczy sie na page=10
MAX_PAGE_ALLOWED = 10

# identyfikator oferty siedzi na koncu sciezki: .../dzialka-gdanski-.../ob/48607801
_OFFER_ID_RE = re.compile(r"/ob/(\d+)/?$")


class GratkaAdapter:
    name = "gratka"
    base_url = "https://gratka.pl"
    delay_seconds = 2.0
    requires_js = False

    # --------------------------------------------------------------- adresy

    def list_urls(self, region_teryt: str) -> Iterable[str]:
        """Jedno zapytanie na powiat. Powod: limit 10 stron w robots.txt."""
        data = json.loads(SEED.read_text(encoding="utf-8"))
        for teryt, slug in sorted(data["powiaty"].items()):
            if teryt.startswith(region_teryt):
                yield f"{self.base_url}/nieruchomosci/dzialki-grunty/{slug}"

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

        for offer in _shared.iter_jsonld_offers(html):
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
                    price_grosze=_shared.to_grosze(offer.get("price")),
                    area_m2=_shared.to_m2(floor.get("value")),
                    title=_shared.clean(offer.get("name")),
                ).with_hash()
            )
        return stubs

    def parse_detail(self, html: str) -> ListingDetail:
        offer = _shared.first_jsonld_of_type(html, "Offer") or {}
        canonical = _shared.canonical_url(html)
        offer_id = offer_id_from_url(canonical or offer.get("url") or "")

        lat, lon = _shared.nuxt_center(html)
        # Opis sluzy wylacznie do wyciagniecia flag i nigdy nie jest zapisywany.
        # Gratka podaje go jako HTML z akapitami, wiec najpierw zdejmujemy znaczniki.
        description = _odznacz(str(offer.get("description") or ""))

        return ListingDetail(
            portal_offer_id=offer_id or "",
            title=_shared.clean(offer.get("name")) or _shared.title_tag(html),
            price_grosze=_shared.to_grosze(offer.get("price")),
            area_m2=area_from_title(offer.get("name")) or _area_z_opisu(description),
            lat=lat,
            lon=lon,
            geom_precision="approx" if lat is not None else None,
            przeznaczenie_raw=_shared.przeznaczenie_z_opisu(description, html),
            media_raw=_shared.media_flags(description),
            road_access_raw=_shared.dojazd_z_opisu(description),
            thumb_url=_shared.thumb_from(offer, html),
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


def _odznacz(html_fragment: str) -> str:
    """Opis Gratki przychodzi jako HTML. Znaczniki zamieniamy na spacje.

    Zamieniamy, a nie usuwamy: "</p><p>KANALIZACJA" bez spacji sklejaloby sie
    w jedno slowo i wzorce mediow przestalyby trafiac.
    """
    if not html_fragment:
        return ""
    return _shared.clean(re.sub(r"<[^>]+>", " ", html_fragment)) or ""


def area_from_title(name: Any) -> int | None:
    """Powierzchnia z tytulu oferty: 'Dzialka lub grunt na sprzedaz, 1204 m2 ...'.

    Tytul jest jedynym miejscem na stronie detalu, gdzie powierzchnia stoi
    w polu, a nie w zdaniu. Format bywa z twarda spacja ("1 204 m²").
    """
    if not isinstance(name, str):
        return None
    match = re.search(r"(\d[\d\s ]*)\s*m²", name)
    return _shared.to_m2(match.group(1)) if match else None


def _area_z_opisu(description: str) -> int | None:
    """Ostatnia deska ratunku: 'o pow 1250 m2' w tresci ogloszenia.

    Swiadomie slabsze zrodlo niz tytul, bo w opisie potrafia byc powierzchnie
    kilku dzialek naraz ("od 1193 do 1773 m2"). Bierzemy pierwsza liczbe przy
    slowie o powierzchni, a nie dowolna liczbe z "m2".
    """
    if not description:
        return None
    match = re.search(
        r"(?:pow(?:ierzchni[aei])?\.?)\s*(?:ok\.?\s*)?(\d[\d\s ]*)\s*m[²2]",
        description,
        re.I,
    )
    return _shared.to_m2(match.group(1)) if match else None
