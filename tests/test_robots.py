"""Testy interpretacji robots.txt na plikach pobranych z portali 2026-08-21.

Ten modul powstal, bo urllib.robotparser z biblioteki standardowej przepuszczal
adresy, ktorych Morizon zabrania wprost. Testy pilnuja, zeby nie wrocic do tego
stanu: przestrzeganie robots.txt jest w tym projekcie elementem obrony prawnej
(sekcja 8.2), a nie kosmetyka.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grunt.ingest.robots import Robots

FIXTURES = Path(__file__).parent / "fixtures"
UA = "GRUNT/0.1 (prywatne narzedzie analityczne; kontakt: ktos@example.invalid)"


@pytest.fixture(scope="module")
def morizon() -> Robots:
    return Robots.from_text((FIXTURES / "robots_morizon.txt").read_text(encoding="utf-8"), UA)


@pytest.fixture(scope="module")
def no() -> Robots:
    return Robots.from_text(
        (FIXTURES / "robots_nieruchomosci_online.txt").read_text(encoding="utf-8"), UA
    )


# ------------------------------------------------------------------ Morizon


def test_listing_i_oferta_sa_dozwolone(morizon: Robots) -> None:
    assert morizon.can_fetch("https://www.morizon.pl/dzialki/kartuski/")
    assert morizon.can_fetch("https://www.morizon.pl/oferta/sprzedaz-dzialka-mzn123")


def test_paginacja_do_dziesiatej_strony(morizon: Robots) -> None:
    """Allow: *page=2$ ... *page=10$ przy ogolnym Disallow: *page=*."""
    for page in range(2, 11):
        assert morizon.can_fetch(f"https://www.morizon.pl/dzialki/kartuski/?page={page}"), page


def test_strona_jedenasta_zabroniona(morizon: Robots) -> None:
    """To jest dokladnie ten przypadek, ktorego nie lapal parser standardowy."""
    assert not morizon.can_fetch("https://www.morizon.pl/dzialki/kartuski/?page=11")
    assert not morizon.can_fetch("https://www.morizon.pl/dzialki/kartuski/?page=142")


def test_sortowanie_zabronione(morizon: Robots) -> None:
    """Stad odstepstwo od sekcji 18.2: nie da sie skanowac listingu po dacie."""
    assert not morizon.can_fetch("https://www.morizon.pl/dzialki/kartuski/?sort=date")
    assert not morizon.can_fetch("https://www.morizon.pl/dzialki/pomorskie/najnowsze/")
    assert not morizon.can_fetch("https://www.morizon.pl/dzialki/pomorskie/najtansze/")


def test_reguly_z_obu_grup_gwiazdkowych_obowiazuja(morizon: Robots) -> None:
    """Plik ma dwie sekcje "User-agent: *". RFC 9309 kaze je scalic.

    Disallow /api jest w pierwszej, reguly paginacji w drugiej. Branie tylko
    jednej z grup gubi polowe zakazow.
    """
    assert not morizon.can_fetch("https://www.morizon.pl/api/cokolwiek")  # grupa 1
    assert not morizon.can_fetch("https://www.morizon.pl/dzialki/x/?page=11")  # grupa 2
    assert not morizon.can_fetch("https://www.morizon.pl/oferta/x/drukuj")  # grupa 2


def test_pozostale_zakazy_morizona(morizon: Robots) -> None:
    assert not morizon.can_fetch("https://www.morizon.pl/mapa/pomorskie")
    assert not morizon.can_fetch("https://www.morizon.pl/polityka_cookies")


# --------------------------------------------------- Nieruchomosci-online


def test_brak_grupy_gwiazdkowej_oznacza_brak_ograniczen(no: Robots) -> None:
    """Plik ma reguly tylko dla Googlebota, bingbota i botow SEO.

    Naszego agenta nie dotyczy zadna z nich, wiec wszystko jest dozwolone.
    Mimo to trzymamy 2 s odstepu, bo tak wypada.
    """
    assert no.can_fetch("https://pomorskie.nieruchomosci-online.pl/dzialki/")
    assert no.can_fetch("https://pomorskie.nieruchomosci-online.pl/dzialki/?p=50")
    assert no.can_fetch("https://katy-rybackie.nieruchomosci-online.pl/dzialka,pusta/26827193.html")


def test_bot_seo_dostalby_zakaz_wszystkiego() -> None:
    """Sprawdzenie, ze parser w ogole widzi grupy imienne."""
    tresc = (FIXTURES / "robots_nieruchomosci_online.txt").read_text(encoding="utf-8")
    ahrefs = Robots.from_text(tresc, "AhrefsBot/7.0")
    assert not ahrefs.can_fetch("https://www.nieruchomosci-online.pl/dzialki/")


def test_crawl_delay_czytany_z_grupy_agenta() -> None:
    tresc = (FIXTURES / "robots_nieruchomosci_online.txt").read_text(encoding="utf-8")
    assert Robots.from_text(tresc, "bingbot/2.0").crawl_delay == 1.0


# ------------------------------------------------------ semantyka wzorcow


def test_najdluzszy_wzorzec_wygrywa() -> None:
    tresc = "User-agent: *\nDisallow: /a/\nAllow: /a/b/\n"
    r = Robots.from_text(tresc, UA)
    assert not r.can_fetch("https://x.pl/a/inne")
    assert r.can_fetch("https://x.pl/a/b/plik")


def test_remis_rozstrzyga_na_korzysc_allow() -> None:
    tresc = "User-agent: *\nDisallow: /x/\nAllow: /x/\n"
    assert Robots.from_text(tresc, UA).can_fetch("https://x.pl/x/cos")


def test_pusty_disallow_nie_blokuje_niczego() -> None:
    tresc = "User-agent: *\nDisallow:\n"
    assert Robots.from_text(tresc, UA).can_fetch("https://x.pl/cokolwiek")


def test_kotwica_konca_adresu() -> None:
    tresc = "User-agent: *\nDisallow: /plik$\n"
    r = Robots.from_text(tresc, UA)
    assert not r.can_fetch("https://x.pl/plik")
    assert r.can_fetch("https://x.pl/plik.html")


def test_komentarze_i_puste_linie_sa_pomijane() -> None:
    tresc = "# komentarz\n\nUser-agent: *\nDisallow: /tajne  # tez komentarz\n"
    r = Robots.from_text(tresc, UA)
    assert not r.can_fetch("https://x.pl/tajne/plik")
    assert r.can_fetch("https://x.pl/jawne")


def test_pusty_plik_oznacza_pelna_swobode() -> None:
    assert Robots.from_text("", UA).can_fetch("https://x.pl/cokolwiek")
