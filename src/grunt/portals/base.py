"""Protokol adaptera portalu. Sekcja 18.1 dokumentu.

To najczesciej modyfikowany fragment systemu, wiec ma najostrzejszy kontrakt:

    ADAPTER NIE ROBI ZADAN HTTP I NIE DOTYKA BAZY.
    Dostaje HTML, zwraca obiekty Pydantic.

Cala siec i persystencja siedza w ingest/runner.py. To jedyny powod, dla ktorego
testy snapshotowe w ogole dzialaja: parser da sie uruchomic na zapisanym pliku,
bez internetu i bez Postgresa.

Podzial na stub i detal wynika z ekonomii: strona wynikow jest tania i pobierana
przy kazdym przebiegu, strona oferty jest droga i pobierana tylko dla ofert
nowych albo zmienionych (strategia DIFF, sekcja 18.2).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator


class ListingStub(BaseModel):
    """Co widac na stronie wynikow. Tanie, pobierane przy kazdym przebiegu."""

    portal_offer_id: str
    url: str
    price_grosze: int | None = None
    area_m2: int | None = None
    posted_at: dt.datetime | None = None
    title: str | None = None
    content_hash: str = ""

    @field_validator("url")
    @classmethod
    def _absolutny_adres(cls, v: str) -> str:
        if not v.startswith("http"):
            raise ValueError(f"url musi byc bezwzgledny, dostano: {v!r}")
        return v

    def with_hash(self) -> ListingStub:
        """Hash pol, ktore realnie oznaczaja zmiane oferty.

        Nie hashujemy URL-a ani tytulu: portale potrafia przebudowac slug bez
        zmiany tresci, a to generowaloby fale niepotrzebnych pobran detalu.
        """
        payload = json.dumps(
            {"price": self.price_grosze, "area": self.area_m2},
            sort_keys=True,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
        return self.model_copy(update={"content_hash": digest})


class ListingDetail(BaseModel):
    """Strona oferty. Droga, pobierana tylko dla nowych i zmienionych.

    UWAGA na pole phone_raw: adapter moze je wydobyc, ale runner natychmiast
    zamienia je na SHA-256 i wyrzuca oryginal. Nigdy nie trafia do bazy
    (sekcja 8.2). Tak samo pelny opis oferty - parsujemy go po to, zeby wyciagnac
    liczby, i nie zapisujemy.
    """

    portal_offer_id: str
    title: str | None = None
    price_grosze: int | None = None
    area_m2: int | None = None
    lat: float | None = None
    lon: float | None = None
    geom_precision: str | None = None  # exact | approx | geocoded
    przeznaczenie_raw: str | None = None
    media_raw: dict[str, Any] | None = None
    road_access_raw: str | None = None
    ksztalt_raw: str | None = None
    forma_wlasnosci_raw: str | None = None
    numer_dzialki_raw: str | None = None
    thumb_url: str | None = None
    phone_raw: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    def bez_danych_kontaktowych(self) -> ListingDetail:
        """Kopia gotowa do zapisu: bez telefonu i bez opisu w polu raw."""
        clean_raw = {
            k: v
            for k, v in self.raw.items()
            if k not in {"description", "opis", "phone", "telefon", "contact", "seller"}
        }
        return self.model_copy(update={"phone_raw": None, "raw": clean_raw})


@runtime_checkable
class PortalAdapter(Protocol):
    """Kontrakt, ktory implementuje kazdy plik w portals/."""

    name: str
    base_url: str
    delay_seconds: float
    requires_js: bool

    def list_urls(self, region_teryt: str) -> Iterable[str]:
        """Adresy stron wynikow dla regionu.

        Implementacja odpowiada za to, zeby nie wychodzic poza to, na co pozwala
        robots.txt portalu (np. Morizon nie zezwala na strony powyzej 10.).
        """
        ...

    def next_page_url(self, url: str, page: int) -> str | None:
        """Adres kolejnej strony wynikow albo None, gdy dalej nie wolno."""
        ...

    def parse_listing_page(self, html: str) -> list[ListingStub]: ...

    def parse_detail(self, html: str) -> ListingDetail: ...
