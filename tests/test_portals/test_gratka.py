"""Testy adaptera Gratki na zapisanych stronach.

Snapshoty pobrane 2026-08-25 i przepuszczone przez scripts/scrub_snapshot.py
(scrubber wymienil 30 numerow telefonu w tych dwoch plikach). Wartosci oczekiwane
odczytane ze strony, nie przepisane z wyniku parsera.

Procedura naprawy po zmianie HTML na portalu (sekcja 18.3):
  1. zapisz nowy HTML do tests/snapshots/gratka/
  2. uv run python scripts/scrub_snapshot.py tests/snapshots
  3. uruchom testy, zobacz co sie rozjechalo
  4. popraw odczyt pol w src/grunt/portals/gratka.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from grunt.config import REPO_ROOT
from grunt.portals.base import ListingDetail, ListingStub, PortalAdapter
from grunt.portals.gratka import SEED, GratkaAdapter, area_from_title, offer_id_from_url

SNAPSHOTS = Path(__file__).resolve().parents[1] / "snapshots" / "gratka"


@pytest.fixture(scope="module")
def adapter() -> GratkaAdapter:
    return GratkaAdapter()


@pytest.fixture(scope="module")
def listing_html() -> str:
    return (SNAPSHOTS / "listing_powiat_gdanski.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def detail_html() -> str:
    return (SNAPSHOTS / "detail_dzialka_dlugie_pole.html").read_text(encoding="utf-8")


def test_adapter_spelnia_protokol(adapter: GratkaAdapter) -> None:
    assert isinstance(adapter, PortalAdapter)
    assert adapter.name == "gratka"
    assert adapter.requires_js is False


# ------------------------------------------------------------------- adresy


def test_jeden_adres_na_powiat(adapter: GratkaAdapter) -> None:
    """robots.txt Gratki ma te sama konstrukcje co Morizona: page=2..10.

    Przy takim limicie zapytanie wojewodzkie oddaje najwyzej 10 stron, wiec
    region rozbijamy na powiaty. To nie jest przypadek: Gratka i Morizon naleza
    do tej samej grupy i dziela nawet CDN obrazkow.
    """
    adresy = list(adapter.list_urls("22"))

    assert len(adresy) == 20, "20 powiatow pomorskiego"
    assert adresy[0] == "https://gratka.pl/nieruchomosci/dzialki-grunty/powiat-bytowski"
    assert "https://gratka.pl/nieruchomosci/dzialki-grunty/gdansk" in adresy


def test_slug_ma_dwa_ksztalty() -> None:
    """Powiaty ziemskie z przedrostkiem, miasta na prawach powiatu bez niego.

    Pomylka w te strone daje 404, wiec pilnujemy jej testem, a nie pamiecia.
    """
    powiaty = json.loads(SEED.read_text(encoding="utf-8"))["powiaty"]

    assert powiaty["2204"] == "powiat-gdanski"
    assert powiaty["2261"] == "gdansk"
    assert powiaty["2264"] == "sopot"
    assert all(not s.startswith("powiat-") for s in ("gdansk", "gdynia", "slupsk", "sopot"))


def test_seed_pokrywa_sie_z_seedem_morizona() -> None:
    """Oba portale maja objac te same 20 powiatow. Rozjazd znaczy literowke."""
    gratka = json.loads(SEED.read_text(encoding="utf-8"))["powiaty"]
    morizon = json.loads(
        (REPO_ROOT / "db" / "seed" / "morizon_powiaty_pomorskie.json").read_text(encoding="utf-8")
    )["powiaty"]

    assert set(gratka) == set(morizon)


def test_paginacja_konczy_sie_na_dziesiatej_stronie(adapter: GratkaAdapter) -> None:
    baza = "https://gratka.pl/nieruchomosci/dzialki-grunty/gdansk"

    assert adapter.next_page_url(baza, 2) == f"{baza}?page=2"
    assert adapter.next_page_url(baza, 10) == f"{baza}?page=10"
    assert adapter.next_page_url(baza, 11) is None, "robots.txt dalej nie pozwala"
    assert adapter.next_page_url(baza, 1) is None


def test_identyfikator_z_adresu() -> None:
    assert offer_id_from_url("https://gratka.pl/nieruchomosci/dzialka-x/ob/48607801") == "48607801"
    assert offer_id_from_url("https://gratka.pl/nieruchomosci/dzialka-x/ob/48607801?utm=1") == (
        "48607801"
    )
    assert offer_id_from_url("https://gratka.pl/nieruchomosci/cos-innego") is None


# ------------------------------------------------------------------- listing


def test_lista_zwraca_oferty_z_jsonld(adapter: GratkaAdapter, listing_html: str) -> None:
    stubs = adapter.parse_listing_page(listing_html)

    assert len(stubs) == 34
    assert all(isinstance(s, ListingStub) for s in stubs)
    assert len({s.portal_offer_id for s in stubs}) == 34


def test_oferta_z_listy_ma_odczytane_liczby(adapter: GratkaAdapter, listing_html: str) -> None:
    """Wislinka: 373 240 zl za 1204 m2, cena z JSON-LD w formacie '373240.00'."""
    oferta = next(
        s for s in adapter.parse_listing_page(listing_html) if s.portal_offer_id == "48721003"
    )

    assert oferta.price_grosze == 37_324_000
    assert oferta.area_m2 == 1204
    assert oferta.url.endswith("/ob/48721003")


def test_lista_bez_jsonld_nie_wybucha(adapter: GratkaAdapter) -> None:
    assert adapter.parse_listing_page("<html><body>pusto</body></html>") == []


# -------------------------------------------------------------------- detal


def test_detal_odczytuje_komplet_pol(adapter: GratkaAdapter, detail_html: str) -> None:
    detal = adapter.parse_detail(detail_html)

    assert isinstance(detal, ListingDetail)
    assert detal.portal_offer_id == "48607801"
    assert detal.price_grosze == 17_000_000
    assert detal.area_m2 == 1250


def test_detal_bierze_wspolrzedne_z_klucza_center(adapter: GratkaAdapter, detail_html: str) -> None:
    """Na tej stronie sa cztery inne pary latitude/longitude (rogi bboxow).

    Naiwne wziecie pierwszej pary liczb daloby punkt oddalony o kilkaset metrow,
    dlatego _shared.nuxt_center szuka po kluczu "center", a nie po nazwach pol.
    """
    detal = adapter.parse_detail(detail_html)

    assert detal.lat == pytest.approx(54.23579)
    assert detal.lon == pytest.approx(18.86978)
    assert detal.geom_precision == "approx"


def test_media_wychodza_z_opisu_mimo_znacznikow_html(
    adapter: GratkaAdapter, detail_html: str
) -> None:
    """Gratka podaje opis jako HTML z akapitami.

    Znaczniki zamieniamy na spacje, a nie usuwamy: "</p><p>KANALIZACJA" bez
    spacji sklejaloby sie w jedno slowo i wzorce mediow przestalyby trafiac.
    """
    detal = adapter.parse_detail(detail_html)

    assert detal.media_raw == {"woda": True, "kanalizacja": True}


def test_dojazd_lapie_wjazd_a_nie_tylko_dojazd(adapter: GratkaAdapter, detail_html: str) -> None:
    """Ogloszenie mowi "Wjazd na dzialke BEZPOSREDNIO z drogi GMINNEJ".

    Samo slowo "dojazd" by tego nie zlapalo, a to jest dokladnie ten fakt,
    o ktory pyta bramka brak_dostepu_do_drogi (mnoznik 0,35, sekcja 5.3.5).
    """
    detal = adapter.parse_detail(detail_html)

    assert detal.road_access_raw is not None
    assert "drogi GMINNEJ" in detal.road_access_raw


def test_powierzchnia_z_tytulu_z_twarda_spacja() -> None:
    assert area_from_title("Działka lub grunt na sprzedaż, 1204 m² Wiślinka") == 1204
    assert area_from_title("Działka lub grunt na sprzedaż, 19 793 m² Borowina") == 19793
    assert area_from_title("Bez powierzchni") is None
    assert area_from_title(None) is None


def test_detal_bez_jsonld_nie_wybucha(adapter: GratkaAdapter) -> None:
    detal = adapter.parse_detail("<html><title>Cokolwiek</title></html>")

    assert detal.portal_offer_id == ""
    assert detal.lat is None


def test_adapter_nie_zapisuje_danych_kontaktowych(adapter: GratkaAdapter, detail_html: str) -> None:
    """JSON-LD detalu ma pole "seller" z danymi biura. Nie moze wyjsc z adaptera."""
    detal = adapter.parse_detail(detail_html)
    zrzut = repr(detal.model_dump()).lower()

    for zakazane in ("seller", "@gmail", "@wp.pl", "telefon"):
        assert zakazane not in zrzut, f"do detalu wyciekl {zakazane}"
