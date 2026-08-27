"""Testy adaptera Morizona na zapisanych stronach.

Snapshoty pobrane 2026-08-21 i przepuszczone przez scripts/scrub_snapshot.py.
Wartosci oczekiwane odczytane ze strony, nie przepisane z wyniku parsera.

Procedura naprawy po zmianie HTML na portalu (sekcja 18.3):
  1. zapisz nowy HTML do tests/snapshots/morizon/
  2. uv run python scripts/scrub_snapshot.py tests/snapshots
  3. uruchom testy, zobacz co sie rozjechalo
  4. popraw selektory w src/grunt/portals/morizon.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grunt.portals.base import ListingDetail, ListingStub, PortalAdapter
from grunt.portals.morizon import MorizonAdapter, media_flags, offer_id_from_url

SNAPSHOTS = Path(__file__).resolve().parents[1] / "snapshots" / "morizon"


@pytest.fixture(scope="module")
def adapter() -> MorizonAdapter:
    return MorizonAdapter()


@pytest.fixture(scope="module")
def listing_html() -> str:
    return (SNAPSHOTS / "listing_pomorskie.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def detail_html() -> str:
    return (SNAPSHOTS / "detail_dzialka_gdansk_kokoszki.html").read_text(encoding="utf-8")


def test_adapter_spelnia_protokol(adapter: MorizonAdapter) -> None:
    assert isinstance(adapter, PortalAdapter)
    assert adapter.name == "morizon"
    assert adapter.requires_js is False


# ------------------------------------------------------------------- listing


def test_listing_zwraca_wszystkie_oferty_ze_strony(
    adapter: MorizonAdapter, listing_html: str
) -> None:
    """Morizon pokazuje 35 ofert na stronie wynikow."""
    stubs = adapter.parse_listing_page(listing_html)
    assert len(stubs) == 35
    assert all(isinstance(s, ListingStub) for s in stubs)


def test_listing_ma_komplet_cen_i_powierzchni(adapter: MorizonAdapter, listing_html: str) -> None:
    """JSON-LD podaje oba pola dla kazdej oferty. Brak choc jednego to regres."""
    stubs = adapter.parse_listing_page(listing_html)
    assert all(s.price_grosze for s in stubs)
    assert all(s.area_m2 for s in stubs)


def test_listing_konkretna_oferta(adapter: MorizonAdapter, listing_html: str) -> None:
    """Dzialka przy ul. Wieckiej: 649 000 zl za 1115 m2."""
    stubs = {s.portal_offer_id: s for s in adapter.parse_listing_page(listing_html)}
    stub = stubs["mzn2047458917"]
    assert stub.price_grosze == 64_900_000
    assert stub.area_m2 == 1115
    assert stub.url.endswith("sprzedaz-dzialka-gdansk-kokoszki-wiecka-1115m2-mzn2047458917")


def test_identyfikator_z_konca_sluga() -> None:
    assert (
        offer_id_from_url("https://www.morizon.pl/oferta/x-568m2-mzn2047606024") == "mzn2047606024"
    )
    assert offer_id_from_url("https://www.morizon.pl/oferta/x-mzn123/") == "mzn123"
    assert offer_id_from_url("https://www.morizon.pl/dzialki/pomorskie/") is None


def test_content_hash_reaguje_na_cene_a_nie_na_adres() -> None:
    """DIFF ma sie uruchamiac przy zmianie ceny, a nie przy przebudowie sluga."""
    a = ListingStub(
        portal_offer_id="mzn1",
        url="https://www.morizon.pl/oferta/a-mzn1",
        price_grosze=100_000,
        area_m2=500,
    ).with_hash()
    inny_adres = ListingStub(
        portal_offer_id="mzn1",
        url="https://www.morizon.pl/oferta/zupelnie-inny-slug-mzn1",
        price_grosze=100_000,
        area_m2=500,
        title="inny tytul",
    ).with_hash()
    inna_cena = ListingStub(
        portal_offer_id="mzn1",
        url="https://www.morizon.pl/oferta/a-mzn1",
        price_grosze=99_000,
        area_m2=500,
    ).with_hash()

    assert a.content_hash == inny_adres.content_hash
    assert a.content_hash != inna_cena.content_hash


# -------------------------------------------------------------------- detal


def test_detal_podstawowe_pola(adapter: MorizonAdapter, detail_html: str) -> None:
    d = adapter.parse_detail(detail_html)
    assert isinstance(d, ListingDetail)
    assert d.portal_offer_id == "mzn2047458917"
    assert d.price_grosze == 64_900_000
    assert d.area_m2 == 1115
    assert d.title is not None and "1115" in d.title


def test_detal_wspolrzedne_to_srodek_mapy_a_nie_rog_bboxa(
    adapter: MorizonAdapter, detail_html: str
) -> None:
    """Na stronie sa tez rogi bboxa dzielnicy (54.34017, 18.50887 i 54.33747, 18.50617).

    Wziecie pierwszej pary liczb z HTML dawaloby punkt oddalony o kilkaset metrow.
    """
    d = adapter.parse_detail(detail_html)
    assert d.lat == pytest.approx(54.3392275, abs=1e-6)
    assert d.lon == pytest.approx(18.5150243, abs=1e-6)
    assert d.lat != pytest.approx(54.34017313, abs=1e-6)


def test_detal_wspolrzedne_sa_oznaczone_jako_przyblizone(
    adapter: MorizonAdapter, detail_html: str
) -> None:
    """ULDK w tym punkcie zwraca dzialke 886 m2, a oferta deklaruje 1115 m2.

    Wspolrzedne wskazuja okolice, nie konkretna dzialke, i pipeline musi to wiedziec.
    """
    d = adapter.parse_detail(detail_html)
    assert d.geom_precision == "approx"


def test_detal_wyciaga_media_z_opisu(adapter: MorizonAdapter, detail_html: str) -> None:
    d = adapter.parse_detail(detail_html)
    assert d.media_raw == {"prad": True, "woda": True, "gaz": True, "kanalizacja": True}


def test_media_nie_wpisuja_falszu_przy_braku_wzmianki() -> None:
    """NULL to NULL: brak wzmianki o gazie nie znaczy, ze gazu nie ma."""
    assert media_flags("Na dzialce jest prad.") == {"prad": True}
    assert media_flags("") is None
    assert media_flags("Piekna dzialka w lesie.") is None


def test_media_dzialaja_z_polskimi_znakami_i_bez_nich() -> None:
    """Ogloszenia bywaja pisane bez ogonkow i nie moze to zmieniac wyniku."""
    assert media_flags("Prąd i kanalizacja w drodze") == media_flags("Prad i kanalizacja w drodze")
    assert media_flags("wodociąg przy działce") == {"woda": True}


def test_detal_lapie_mpzp(adapter: MorizonAdapter, detail_html: str) -> None:
    d = adapter.parse_detail(detail_html)
    assert d.przeznaczenie_raw is not None
    assert "plan" in d.przeznaczenie_raw.lower()


def test_detal_nie_zwraca_telefonu_ani_opisu(adapter: MorizonAdapter, detail_html: str) -> None:
    """Zasada twarda z sekcji 8.2, sprawdzana automatycznie."""
    d = adapter.parse_detail(detail_html)
    assert d.phone_raw is None
    czysty = d.bez_danych_kontaktowych()
    assert "description" not in czysty.raw
    assert "opis" not in czysty.raw
    assert all(not isinstance(v, str) or len(v) < 300 for v in czysty.raw.values())


# --------------------------------------------------------------------- adresy


def test_list_urls_daje_jeden_adres_na_powiat(adapter: MorizonAdapter) -> None:
    """20 jednostek pomorskiego: 16 powiatow plus 4 miasta na prawach powiatu."""
    urls = list(adapter.list_urls("22"))
    assert len(urls) == 20
    assert "https://www.morizon.pl/dzialki/kartuski/" in urls
    assert "https://www.morizon.pl/dzialki/gdansk/" in urls


def test_paginacja_zatrzymuje_sie_na_dziesiatej_stronie(adapter: MorizonAdapter) -> None:
    """robots.txt: Disallow *page=* z Allow tylko do page=10."""
    url = "https://www.morizon.pl/dzialki/kartuski/"
    assert adapter.next_page_url(url, 2) == f"{url}?page=2"
    assert adapter.next_page_url(url, 10) == f"{url}?page=10"
    assert adapter.next_page_url(url, 11) is None
    assert adapter.next_page_url(url, 1) is None


def test_paginacja_nie_dokleja_sie_do_istniejacego_parametru(adapter: MorizonAdapter) -> None:
    url = "https://www.morizon.pl/dzialki/kartuski/?page=2"
    assert adapter.next_page_url(url, 3) == "https://www.morizon.pl/dzialki/kartuski/?page=3"
