"""Testy bramki konfiguracyjnej scrapera.

Sekcja 8.2 punkt 7 dokumentu: uczciwy User-Agent z adresem kontaktowym jest
elementem obrony prawnej, a podszywanie sie pod przegladarke jest okolicznoscia
obciazajaca. Dlatego zly naglowek zatrzymuje przebieg, zamiast trafiac do logu.
"""

from __future__ import annotations

import httpx
import pytest

from grunt.ingest.runner import ScraperConfigError, assert_honest_user_agent

POPRAWNY = "GRUNT/0.1 (prywatne narzedzie analityczne; kontakt: ktos@example.org)"


def test_poprawny_naglowek_przechodzi() -> None:
    assert assert_honest_user_agent(POPRAWNY) == POPRAWNY


def test_placeholder_z_env_example_jest_odrzucany() -> None:
    """Placeholder jest gorszy niz brak deklaracji: wyglada jak bot udajacy kontakt."""
    with pytest.raises(ScraperConfigError, match="placeholder"):
        assert_honest_user_agent("GRUNT/0.1 (kontakt: TWOJ@EMAIL)")


def test_sam_adres_email_to_za_malo() -> None:
    """Naglowek ma powiedziec, CZYM jest klient, nie tylko do kogo pisac."""
    with pytest.raises(ScraperConfigError, match="nie identyfikuje narzedzia"):
        assert_honest_user_agent("ktos@example.org")


def test_brak_kontaktu_jest_odrzucany() -> None:
    with pytest.raises(ScraperConfigError, match="adresu kontaktowego"):
        assert_honest_user_agent("GRUNT/0.1")


def test_podszywanie_sie_pod_przegladarke_jest_odrzucane() -> None:
    """To nie jest tylko brak kontaktu, to okolicznosc obciazajaca (sekcja 8.2)."""
    with pytest.raises(ScraperConfigError):
        assert_honest_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")


def test_biale_znaki_nie_psuja_walidacji() -> None:
    assert assert_honest_user_agent(f"  {POPRAWNY}  ") == POPRAWNY


# ---------------------- koniec stron kontra prawdziwy blad (runner)


def _blad_http(status: int) -> httpx.HTTPStatusError:
    zadanie = httpx.Request("GET", "https://gratka.pl/x?page=2")
    return httpx.HTTPStatusError(
        "blad", request=zadanie, response=httpx.Response(status, request=zadanie)
    )


def test_404_na_drugiej_stronie_to_koniec_wynikow() -> None:
    """Gratka ma w Sopocie 15 ofert, czyli jedna strone, a adapter proponuje ?page=2.

    Bez tego rozroznienia kazdy maly powiat dokladalby falszywy blad do wyniku
    zadania i mylil watchdoga, ktory ma alarmowac o portalu naprawde milczacym.
    """
    from grunt.ingest.runner import _koniec_stron

    assert _koniec_stron(_blad_http(404), page=2) is True
    assert _koniec_stron(_blad_http(404), page=7) is True


def test_404_na_pierwszej_stronie_to_prawdziwy_blad() -> None:
    """Na stronie 1 czterysta cztery znaczy zly slug, a to musi byc widoczne."""
    from grunt.ingest.runner import _koniec_stron

    assert _koniec_stron(_blad_http(404), page=1) is False


def test_inne_statusy_zostaja_bledem_takze_na_dalszych_stronach() -> None:
    """403 albo 500 na stronie 5 to awaria, a nie koniec listy."""
    from grunt.ingest.runner import _koniec_stron

    assert _koniec_stron(_blad_http(403), page=5) is False
    assert _koniec_stron(_blad_http(500), page=5) is False


def test_blad_sieci_bez_odpowiedzi_zostaje_bledem() -> None:
    """Timeout nie ma statusu, wiec nie da sie go wziac za koniec stron."""
    from grunt.ingest.runner import _koniec_stron

    timeout = httpx.ConnectTimeout("za dlugo", request=httpx.Request("GET", "https://x/y?page=3"))
    assert _koniec_stron(timeout, page=3) is False


# ------------- oferta ze stubem, ale bez pobranego detalu (dziura w DIFF)


class _FakeResult:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def mappings(self) -> _FakeResult:
        return self

    def one_or_none(self) -> dict[str, object] | None:
        return self._row

    def one(self) -> dict[str, object]:
        assert self._row is not None
        return self._row


class _FakeSession:
    """Sesja oddajaca zaplanowane wiersze. Test dotyczy decyzji, nie SQL-a."""

    def __init__(self, istniejacy: dict[str, object] | None) -> None:
        self.istniejacy = istniejacy
        self.wywolania: list[str] = []

    def execute(self, statement: object, params: object = None) -> _FakeResult:
        tekst = str(statement)
        if "raw_jsonb IS NULL" in tekst:
            self.wywolania.append("select")
            return _FakeResult(self.istniejacy)
        if "INSERT INTO listings" in tekst:
            self.wywolania.append("upsert")
            return _FakeResult({"id": 7, "wstawiony": False, "content_hash": "x"})
        self.wywolania.append("inne")
        return _FakeResult({"id": 7})


def _stub(content_hash: str = "aaa"):  # type: ignore[no-untyped-def]
    from grunt.portals.base import ListingStub

    return ListingStub(
        portal_offer_id="1",
        url="https://example.com/oferta/1",
        price_grosze=100_000,
        area_m2=1000,
        title="Dzialka",
        content_hash=content_hash,
    )


def test_oferta_bez_pobranego_detalu_wraca_do_kolejki() -> None:
    """Bez tego stanu oferta zostawalaby "bez zmian" na zawsze.

    Stub zapisuje sie od razu, a detale pobierane sa dopiero po calym listingu.
    Przebieg przerwany albo ograniczony (--max-details) zostawia wiec oferty
    z content_hashem, ale bez wspolrzednych i przeznaczenia. Przy nastepnym
    przebiegu hash sie zgadza, wiec bez tej sciezki detal nie zostalby pobrany
    NIGDY.
    """
    from grunt.ingest.runner import _upsert_stub

    session = _FakeSession(
        {"id": 7, "content_hash": "aaa", "price_grosze": 100_000, "bez_detalu": True}
    )
    listing_id, status = _upsert_stub(session, "otodom", _stub("aaa"))  # type: ignore[arg-type]

    assert listing_id == 7
    assert status == "bez_detalu"


def test_oferta_z_detalem_i_bez_zmian_zostaje_bez_zmian() -> None:
    from grunt.ingest.runner import _upsert_stub

    session = _FakeSession(
        {"id": 7, "content_hash": "aaa", "price_grosze": 100_000, "bez_detalu": False}
    )
    _, status = _upsert_stub(session, "otodom", _stub("aaa"))  # type: ignore[arg-type]

    assert status == "unchanged"


def test_zmieniony_hash_ma_pierwszenstwo_przed_brakiem_detalu() -> None:
    """Zmiana oferty to zmiana, niezaleznie od tego, czy detal juz byl."""
    from grunt.ingest.runner import _upsert_stub

    session = _FakeSession(
        {"id": 7, "content_hash": "stary", "price_grosze": 90_000, "bez_detalu": True}
    )
    _, status = _upsert_stub(session, "otodom", _stub("nowy"))  # type: ignore[arg-type]

    assert status == "changed"


def test_update_detalu_rzutuje_wspolrzedne_na_konkretny_typ() -> None:
    """Oferta bez wspolrzednych nie moze wywalac calego przebiegu.

    Bez rzutowania sterownik wysyla NULL bez typu, PostgreSQL nie umie go
    wywnioskowac z samego "IS NULL" i odpowiada bledem AmbiguousParameter
    ("could not determine data type of parameter"). Trafialo to wylacznie
    w oferty bez wspolrzednych, wiec przebieg dla Morizona konczyl sie dobrze,
    a dla Nieruchomosci-online wywracal sie w polowie.

    Testujemy tekst zapytania, bo to jedyny sposob bez bazy - a blad byl
    dokladnie w tekscie zapytania, nie w logice Pythona.
    """
    from grunt.ingest.runner import UPDATE_DETAIL

    sql = str(UPDATE_DETAIL)

    assert "CAST(:easting AS double precision)" in sql
    assert "CAST(:northing AS double precision)" in sql
    assert "WHEN :easting IS NULL" not in sql, "goly parametr w IS NULL wraca do bledu"
