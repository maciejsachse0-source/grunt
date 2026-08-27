"""Testy adaptera Nieruchomosci-online na zapisanych stronach.

Snapshoty pobrane 2026-08-21, przepuszczone przez scripts/scrub_snapshot.py.
Wartosci oczekiwane odczytane ze strony oferty w Katach Rybackich:
690 000 zl, 835 m2, wymiary 24m x 25m, media gaz/prad/woda, droga asfaltowa.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from grunt.portals.base import ListingDetail, ListingStub, PortalAdapter
from grunt.portals.nieruchomosci_online import (
    NieruchomosciOnlineAdapter,
    front_from_dimensions,
    media_from_label,
    offer_id_from_url,
    parse_date_any,
    parse_pl_date,
)

SNAPSHOTS = Path(__file__).resolve().parents[1] / "snapshots" / "nieruchomosci_online"


@pytest.fixture(scope="module")
def adapter() -> NieruchomosciOnlineAdapter:
    return NieruchomosciOnlineAdapter()


@pytest.fixture(scope="module")
def listing_html() -> str:
    return (SNAPSHOTS / "listing_pomorskie.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def detail_html() -> str:
    return (SNAPSHOTS / "detail_dzialka_katy_rybackie.html").read_text(encoding="utf-8")


def test_adapter_spelnia_protokol(adapter: NieruchomosciOnlineAdapter) -> None:
    assert isinstance(adapter, PortalAdapter)
    assert adapter.name == "nieruchomosci_online"


# ------------------------------------------------------------------- listing


def test_listing_zwraca_wszystkie_oferty(
    adapter: NieruchomosciOnlineAdapter, listing_html: str
) -> None:
    """Serwis pokazuje 41 ofert na stronie (offerCount w JSON-LD)."""
    stubs = adapter.parse_listing_page(listing_html)
    assert len(stubs) == 41
    assert all(isinstance(s, ListingStub) for s in stubs)
    assert all(s.price_grosze and s.area_m2 for s in stubs)


def test_listing_konkretna_oferta(adapter: NieruchomosciOnlineAdapter, listing_html: str) -> None:
    stubs = {s.portal_offer_id: s for s in adapter.parse_listing_page(listing_html)}
    stub = stubs["26827193"]
    assert stub.price_grosze == 69_000_000  # 690 000 zl
    assert stub.area_m2 == 835
    assert stub.url.startswith("https://katy-rybackie.nieruchomosci-online.pl/")


def test_identyfikator_z_nazwy_pliku() -> None:
    assert (
        offer_id_from_url("https://x.nieruchomosci-online.pl/dzialka,pusta/26827193.html")
        == "26827193"
    )
    assert offer_id_from_url("https://pomorskie.nieruchomosci-online.pl/dzialki/") is None


# -------------------------------------------------------------------- detal


def test_detal_czyta_blok_realestatelisting(
    adapter: NieruchomosciOnlineAdapter, detail_html: str
) -> None:
    """Na listingu blok ma @type Product, na stronie oferty RealEstateListing.

    Adapter musi ogarniac oba, a takze @type podany jako lista.
    """
    d = adapter.parse_detail(detail_html)
    assert isinstance(d, ListingDetail)
    assert d.portal_offer_id == "26827193"
    assert d.price_grosze == 69_000_000
    assert d.area_m2 == 835


def test_detal_ma_wspolrzedne_z_pola_geo(
    adapter: NieruchomosciOnlineAdapter, detail_html: str
) -> None:
    d = adapter.parse_detail(detail_html)
    assert d.lat == pytest.approx(54.3400378, abs=1e-6)
    assert d.lon == pytest.approx(19.2319577, abs=1e-6)
    # ULDK w tym punkcie zwraca dzialke 18 983 m2 przy ofercie 835 m2,
    # bo ogloszenie dotyczy dzialki wydzielanej z wiekszej
    assert d.geom_precision == "approx"


def test_detal_ma_pola_ktorych_nie_ma_morizon(
    adapter: NieruchomosciOnlineAdapter, detail_html: str
) -> None:
    """To jest powod, dla ktorego dokument nazywa ten portal najbogatszym."""
    d = adapter.parse_detail(detail_html)
    assert d.przeznaczenie_raw == "usługowa"
    assert d.road_access_raw == "droga asfaltowa"
    assert d.ksztalt_raw == "prostokąt"
    assert d.forma_wlasnosci_raw == "własność"
    assert d.media_raw == {"gaz": True, "prad": True, "woda": True}


def test_detal_wylicza_front_z_wymiarow(
    adapter: NieruchomosciOnlineAdapter, detail_html: str
) -> None:
    """'24m x 25m' daje front 24 m, czyli dana do filaru 4 (sekcja 5.3.6)."""
    d = adapter.parse_detail(detail_html)
    assert d.raw["wymiary"] == "24m x 25m"
    assert d.raw["front_m"] == 24.0


def test_detal_radzi_sobie_z_wadliwa_data_portalu(
    adapter: NieruchomosciOnlineAdapter, detail_html: str
) -> None:
    """Serwis zwraca datePosted jako '2026-07-13CEST20:53:48Z', czyli zepsute ISO."""
    d = adapter.parse_detail(detail_html)
    assert d.raw["zaktualizowano"] == "2026-07-13"


def test_detal_nie_przenosi_danych_posrednika(
    adapter: NieruchomosciOnlineAdapter, detail_html: str
) -> None:
    """Blok RealEstateListing zawiera pole 'agent' i pelny opis. Zadne nie moze wyjsc."""
    d = adapter.parse_detail(detail_html)
    assert d.phone_raw is None
    assert "agent" not in d.raw
    assert "description" not in d.raw
    czysty = d.bez_danych_kontaktowych()
    assert czysty.phone_raw is None


# ---------------------------------------------------------------- pomocnicze


def test_media_z_etykiety() -> None:
    assert media_from_label("gaz, prąd, woda") == {"gaz": True, "prad": True, "woda": True}
    assert media_from_label("prad, szambo") == {"prad": True, "szambo": True}
    assert media_from_label("") is None
    assert media_from_label(None) is None


def test_front_wymaga_dwoch_wymiarow() -> None:
    assert front_from_dimensions("24m x 25m") == 24.0
    assert front_from_dimensions("18,5m x 40m") == 18.5
    assert front_from_dimensions("835 m2") is None
    assert front_from_dimensions(None) is None


def test_daty() -> None:
    assert parse_date_any("2026-07-13CEST20:53:48Z") == dt.date(2026, 7, 13)
    assert parse_date_any("10 sierpnia 2026") == dt.date(2026, 8, 10)
    assert parse_pl_date("1 stycznia 2025") == dt.date(2025, 1, 1)
    assert parse_date_any("kiedys tam") is None
    assert parse_date_any(None) is None


# --------------------------------------------------------------------- adresy


def test_list_urls_uzywa_subdomeny_wojewodztwa(adapter: NieruchomosciOnlineAdapter) -> None:
    assert list(adapter.list_urls("22")) == ["https://pomorskie.nieruchomosci-online.pl/dzialki/"]
    assert list(adapter.list_urls("14")) == ["https://mazowieckie.nieruchomosci-online.pl/dzialki/"]
    assert list(adapter.list_urls("99")) == []


def test_paginacja_uzywa_parametru_p(adapter: NieruchomosciOnlineAdapter) -> None:
    """Sprawdzone na zywo: ?strona=, ?page= i ?o= sa ignorowane."""
    url = "https://pomorskie.nieruchomosci-online.pl/dzialki/"
    assert adapter.next_page_url(url, 2) == f"{url}?p=2"
    assert adapter.next_page_url(f"{url}?p=2", 3) == f"{url}?p=3"
    assert adapter.next_page_url(url, 1) is None
