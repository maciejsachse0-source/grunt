"""Testy normalizacji. Kazdy przypadek to pulapka z sekcji 19.3 albo z zywych danych."""

from __future__ import annotations

import pytest

from grunt.ingest import normalize as n

# ------------------------------------------------------------------- ceny


def test_twarda_spacja_morizona() -> None:
    """Morizon oddziela tysiace znakiem \\xa0, ktory wyglada jak spacja."""
    assert n.parse_price_grosze("649\xa0000 zł") == 64_900_000
    assert n.parse_price_grosze("649 000 zł") == 64_900_000
    assert n.parse_price_grosze("649000") == 64_900_000


def test_cena_z_groszami_i_separatorami() -> None:
    assert n.parse_price_grosze("850000.00") == 85_000_000
    assert n.parse_price_grosze("850000,50") == 85_000_050
    assert n.parse_price_grosze("1.250.000 PLN") == 125_000_000
    assert n.parse_price_grosze(690000) == 69_000_000


def test_cena_poza_zakresem_zdrowego_rozsadku() -> None:
    """1 zl i miliard zl to blad parsowania, nie oferta."""
    assert n.parse_price_grosze("1 zł") is None
    assert n.parse_price_grosze("999999999999") is None
    assert n.parse_price_grosze("") is None
    assert n.parse_price_grosze(None) is None


# ---------------------------------------------------------- powierzchnie


def test_hektary_i_ary() -> None:
    """Bez parsera jednostek 1,5 ha wpadaloby do bazy jako 2 m2."""
    assert n.parse_area_m2("1,5 ha") == 15_000
    assert n.parse_area_m2("1.5 ha") == 15_000
    assert n.parse_area_m2("15 a") == 1_500
    assert n.parse_area_m2("15 arów") == 1_500
    assert n.parse_area_m2("2 hektary") == 20_000


def test_metry_w_roznych_zapisach() -> None:
    assert n.parse_area_m2("1500 m2") == 1500
    assert n.parse_area_m2("1 115 m²") == 1115
    assert n.parse_area_m2("835.00m²") == 835
    assert n.parse_area_m2("1\xa0500 m2") == 1500
    assert n.parse_area_m2(835) == 835


def test_powierzchnia_poza_zakresem() -> None:
    assert n.parse_area_m2("2 m2") is None  # ponizej progu
    assert n.parse_area_m2("1000 ha") is None  # 10 mln m2
    assert n.parse_area_m2("") is None


def test_kolejnosc_jednostek_nie_myli_ara_z_hektarem() -> None:
    """'a' jest przedrostkiem 'ha', wiec regex musi dopasowac dluzsza jednostke."""
    assert n.parse_area_m2("3 ha") == 30_000
    assert n.parse_area_m2("3 a") == 300


# ------------------------------------------------------------------ reszta


def test_cena_za_m2() -> None:
    assert n.price_per_m2(64_900_000, 1115) == pytest.approx(582.06, abs=0.01)
    assert n.price_per_m2(None, 1000) is None
    assert n.price_per_m2(10_000_00, 0) is None


def test_hash_telefonu_jest_stabilny_i_nieodwracalny() -> None:
    """Rozne zapisy tego samego numeru daja ten sam hash (sekcja 4.3 etap 1)."""
    a = n.hash_phone("+48 501 178 937")
    b = n.hash_phone("501178937")
    c = n.hash_phone("501-178-937")
    assert a == b == c
    assert a is not None and len(a) == 64
    assert "501" not in a  # numer nie da sie odczytac z hasha


def test_hash_telefonu_odrzuca_smieci() -> None:
    assert n.hash_phone(None) is None
    assert n.hash_phone("") is None
    assert n.hash_phone("123") is None


def test_odsiew_ofert_ktore_nie_sa_dzialka() -> None:
    assert n.looks_like_land_offer("Działka budowlana 1115 m2", 1115) is True
    assert n.looks_like_land_offer("Mieszkanie 3-pokojowe", 60) is False
    assert n.looks_like_land_offer("Hala magazynowa z gruntem", 5000) is False
    assert n.looks_like_land_offer(None, 800) is True
    assert n.looks_like_land_offer("Działka", None) is False


def test_wspolrzedne_w_polsce() -> None:
    assert n.coords_ok(54.3487, 18.6533) is True
    assert n.coords_ok(18.6533, 54.3487) is False  # zamienione osie
    assert n.coords_ok(None, 18.65) is False
