"""Testy adaptera Otodomu na zapisanych stronach.

Snapshoty pobrane 2026-08-25 i przepuszczone przez scripts/scrub_snapshot.py
(scrubber wymienil 14 numerow telefonu w tych dwoch plikach). Wartosci oczekiwane
odczytane ze strony, nie przepisane z wyniku parsera.

Procedura naprawy po zmianie HTML na portalu (sekcja 18.3):
  1. zapisz nowy HTML do tests/snapshots/otodom/
  2. uv run python scripts/scrub_snapshot.py tests/snapshots
  3. uruchom testy, zobacz co sie rozjechalo
  4. popraw odczyt pol w src/grunt/portals/otodom.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grunt.portals.base import ListingDetail, ListingStub, PortalAdapter
from grunt.portals.otodom import (
    OtodomAdapter,
    dojazd_z_pola,
    media_z_pola,
    offer_id_from_slug,
    przeznaczenie_z_pola,
)

SNAPSHOTS = Path(__file__).resolve().parents[1] / "snapshots" / "otodom"


@pytest.fixture(scope="module")
def adapter() -> OtodomAdapter:
    return OtodomAdapter()


@pytest.fixture(scope="module")
def listing_html() -> str:
    return (SNAPSHOTS / "listing_pomorskie.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def detail_html() -> str:
    return (SNAPSHOTS / "detail_dzialka_mikoszewo.html").read_text(encoding="utf-8")


def test_adapter_spelnia_protokol(adapter: OtodomAdapter) -> None:
    assert isinstance(adapter, PortalAdapter)
    assert adapter.name == "otodom"
    assert adapter.requires_js is False, "dane sa w __NEXT_DATA__, JS nie jest potrzebny"


# ------------------------------------------------------------------- adresy


def test_jeden_adres_na_wojewodztwo(adapter: OtodomAdapter) -> None:
    """W odroznieniu od Morizona i Gratki nie rozbijamy regionu na powiaty.

    Powod jest w robots.txt Otodomu: nie ma tam ani jednej reguly na "page=",
    wiec paginacja jest dozwolona i jedno zapytanie wojewodzkie wystarcza.
    """
    adresy = list(adapter.list_urls("22"))
    assert adresy == ["https://www.otodom.pl/pl/wyniki/sprzedaz/dzialka/pomorskie"]


def test_nieznane_wojewodztwo_nie_daje_adresu(adapter: OtodomAdapter) -> None:
    assert list(adapter.list_urls("14")) == []


def test_paginacja_ma_wlasny_limit_a_nie_limit_robots(adapter: OtodomAdapter) -> None:
    """Limit 25 stron jest NASZ, z higieny scrapingu, a nie z robots.txt.

    Portal pozwolilby na wszystkie 142 strony, ale 142 zadania w kilka minut do
    jednego serwisu to nie jest zachowanie, ktore chcemy (sekcja 8.2).
    """
    baza = "https://www.otodom.pl/pl/wyniki/sprzedaz/dzialka/pomorskie"
    assert adapter.next_page_url(baza, 2) == f"{baza}?page=2"
    assert adapter.next_page_url(baza, 25) == f"{baza}?page=25"
    assert adapter.next_page_url(baza, 26) is None
    assert adapter.next_page_url(baza, 1) is None


def test_identyfikator_ze_sluga() -> None:
    assert (
        offer_id_from_slug("dzialka-z-mpzp-uslugowo-mieszkan-10-min-do-morza-ID4Bjm4") == "ID4Bjm4"
    )
    assert offer_id_from_slug("bez-identyfikatora") is None


# ------------------------------------------------------------------- listing


def test_lista_zwraca_wszystkie_oferty_ze_strony(adapter: OtodomAdapter, listing_html: str) -> None:
    """Strona wynikow ma 36 ofert (pagination.itemsPerPage = 36)."""
    stubs = adapter.parse_listing_page(listing_html)
    assert len(stubs) == 36
    assert all(isinstance(s, ListingStub) for s in stubs)
    assert len({s.portal_offer_id for s in stubs}) == 36, "identyfikatory musza byc unikalne"


def test_pierwsza_oferta_z_listy_ma_odczytane_liczby(
    adapter: OtodomAdapter, listing_html: str
) -> None:
    """Mikoszewo: 335 000 zl za 1124 m2. Cena w groszach, powierzchnia w m2."""
    oferta = next(
        s for s in adapter.parse_listing_page(listing_html) if s.portal_offer_id == "ID4Bjm4"
    )

    assert oferta.price_grosze == 33_500_000
    assert oferta.area_m2 == 1124
    assert oferta.url == (
        "https://www.otodom.pl/pl/oferta/dzialka-z-mpzp-uslugowo-mieszkan-10-min-do-morza-ID4Bjm4"
    )
    assert oferta.title is not None and "MPZP" in oferta.title


def test_lista_bez_next_data_nie_wybucha(adapter: OtodomAdapter) -> None:
    """Portal bez __NEXT_DATA__ ma dac pusta liste, a nie wyjatek."""
    assert adapter.parse_listing_page("<html><body>nic tu nie ma</body></html>") == []
    assert adapter.parse_listing_page('<script id="__NEXT_DATA__">{zepsuty json</script>') == []


# -------------------------------------------------------------------- detal


def test_detal_odczytuje_komplet_pol(adapter: OtodomAdapter, detail_html: str) -> None:
    detal = adapter.parse_detail(detail_html)

    assert isinstance(detal, ListingDetail)
    assert detal.portal_offer_id == "ID4Bjm4"
    assert detal.price_grosze == 33_500_000
    assert detal.area_m2 == 1124
    assert detal.title is not None and "MPZP" in detal.title


def test_detal_ma_wspolrzedne_ale_oznaczone_jako_przyblizone(
    adapter: OtodomAdapter, detail_html: str
) -> None:
    """Portal sam deklaruje rozmycie: location.mapDetails.radius = 100 m.

    Dlatego mimo konkretnej pary liczb geom_precision zostaje "approx". To ta
    sama decyzja co w Morizonie: punkt jest podpowiedzia, gdzie szukac dzialki,
    a nie jej identyfikacja.
    """
    detal = adapter.parse_detail(detail_html)

    assert detal.lat == pytest.approx(54.33399)
    assert detal.lon == pytest.approx(18.95969)
    assert detal.geom_precision == "approx"
    assert detal.raw["promien_m"] == 100


def test_cechy_ida_z_pol_a_nie_z_opisu(adapter: OtodomAdapter, detail_html: str) -> None:
    """To jest powod, dla ktorego Otodom jest najlepszym zrodlem cech.

    Morizon i Gratka wymagaja wylapywania mediow i dojazdu regexem z tresci
    ogloszenia. Otodom podaje je jako pola, wiec nie zaleza od tego, jak
    sprzedajacy sformulowal zdanie.
    """
    detal = adapter.parse_detail(detail_html)

    assert detal.raw["zrodlo_cech"] == "target"
    assert detal.przeznaczenie_raw == "budowlana"
    assert detal.media_raw == {"woda": True, "prad": True}
    assert detal.road_access_raw == "hard_surfaced"


def test_detal_bez_next_data_nie_wybucha(adapter: OtodomAdapter) -> None:
    detal = adapter.parse_detail("<html><title>Cokolwiek</title></html>")
    assert detal.portal_offer_id == ""
    assert detal.lat is None
    assert detal.geom_precision is None


# ------------------------------------------------- przelozenie pol na nasze


def test_przeznaczenie_z_pola_tlumaczy_znane_kody() -> None:
    assert przeznaczenie_z_pola({"Type": ["building"]}) == "budowlana"
    assert przeznaczenie_z_pola({"Type": ["agricultural", "recreational"]}) == "rolna, rekreacyjna"


def test_przeznaczenie_z_pola_oddaje_nieznany_kod_surowy() -> None:
    """Lepiej oddac 'orchard' i nie rozpoznac go w segments.py, niz zgubic."""
    assert przeznaczenie_z_pola({"Type": ["orchard"]}) == "orchard"


def test_przeznaczenie_z_pola_gdy_brak() -> None:
    assert przeznaczenie_z_pola({}) is None
    assert przeznaczenie_z_pola({"Type": []}) is None


def test_media_z_pola_nie_wpisuje_falszu() -> None:
    """Regula "NULL to NULL": brak medium na liscie nie znaczy, ze go nie ma."""
    wynik = media_z_pola({"Media_types": ["water", "electricity"]})

    assert wynik == {"woda": True, "prad": True}
    assert wynik is not None and "gaz" not in wynik


def test_media_z_pola_pomija_nieznane_kody() -> None:
    assert media_z_pola({"Media_types": ["water", "teleportacja"]}) == {"woda": True}
    assert media_z_pola({"Media_types": ["teleportacja"]}) is None


def test_dojazd_z_pola_oddaje_wartosc_surowa() -> None:
    """Przelozenie na trojstan 0/1/2 nalezy do wzbogacania, nie do adaptera."""
    assert dojazd_z_pola({"Access_types": ["hard_surfaced"]}) == "hard_surfaced"
    assert dojazd_z_pola({"Access_types": ["asphalt", "dirt"]}) == "asphalt, dirt"
    assert dojazd_z_pola({}) is None


def test_adapter_nie_zapisuje_danych_kontaktowych(adapter: OtodomAdapter, detail_html: str) -> None:
    """Sekcja 8.2: w bazie nie ma danych kontaktowych, jest URL.

    Strona detalu zawiera agency, advertOwner i seller_id. Zaden z tych kluczy
    nie moze wyjsc z adaptera - ani w polach, ani w raw.
    """
    detal = adapter.parse_detail(detail_html)
    zrzut = repr(detal.model_dump()).lower()

    for zakazane in ("seller_id", "advertowner", "organisationassignedmember", "@gmail", "@wp.pl"):
        assert zakazane not in zrzut, f"do detalu wyciekl {zakazane}"
