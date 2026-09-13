"""Testy wyciagania numeru dzialki z tresci ogloszenia.

Pomiar na 16 losowych ofertach z Morizona i N-O: ZERO zawieralo numer dzialki
w opisie z JSON-LD. Ta sciezka jest wiec dodatkiem, ktory czasem daje pewne
dopasowanie, a nie podstawa wiazania oferty z dzialka. Testy pilnuja, zeby
przy okazji nie zaczela zmyslac numerow tam, gdzie ich nie ma.
"""

from __future__ import annotations

from grunt.enrich.parcel_ref import build_uldk_id, extract


def test_numer_dzialki_z_obrebem() -> None:
    ref = extract("Nieruchomosc przy ul. Sw. Huberta (Obreb 63, dzialka nr 129/3).")
    assert ref.numery == ("129/3",)
    assert ref.obreb_numer == "0063"
    assert ref.pewny is True


def test_numer_bez_ukosnika() -> None:
    ref = extract("dzialka powstanie z podzialu dzialki nr 273")
    assert ref.numery == ("273",)


def test_nazwa_obrebu_gdy_brak_numeru() -> None:
    ref = extract("Sprzedam dzialke ewidencyjna nr 208/25 w obrebie Kielpino Gorne")
    assert ref.numery == ("208/25",)
    assert ref.obreb_nazwa == "Kielpino Gorne"


def test_powierzchnia_nie_jest_brana_za_numer() -> None:
    """Najczestszy falszywy trop: "dzialka 1200 m2"."""
    assert extract("Piekna dzialka 1200 m2 w spokojnej okolicy").numery == ()
    assert extract("Dzialka o powierzchni 850 metrow").numery == ()


def test_dwie_dzialki_w_jednym_zdaniu_nie_sa_pewne() -> None:
    """Ogloszenie na zestaw dzialek nie moze udawac jednoznacznego."""
    ref = extract("Dzialki nr 12/3 oraz 12/4, razem 2400 m2")
    assert set(ref.numery) == {"12/3", "12/4"}
    assert ref.pewny is False


def test_numer_planu_mpzp_nie_jest_numerem_dzialki() -> None:
    """Realny przypadek z Morizona: opis wymienia plan nr 2219."""
    ref = extract("Mozliwosci zabudowy (MPZP - plan nr 2219): dzialka objeta jest planem")
    assert "2219" not in ref.numery


def test_html_w_opisie_nie_przeszkadza() -> None:
    ref = extract("<p>Sprzedam <strong>dzialke nr 45/2</strong> w obrebie 12</p>")
    assert ref.numery == ("45/2",)
    assert ref.obreb_numer == "0012"


def test_pusty_opis() -> None:
    assert bool(extract(None)) is False
    assert bool(extract("")) is False
    assert extract("Ladna dzialka nad jeziorem").numery == ()


def test_skladanie_identyfikatora_uldk() -> None:
    assert build_uldk_id("226101_1", "36", "208/25") == "226101_1.0036.208/25"
    assert build_uldk_id("226101_1", "0036", "208/25") == "226101_1.0036.208/25"
