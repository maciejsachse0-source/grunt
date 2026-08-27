"""Testy klastrowania duplikatow (union-find, rekord kanoniczny, rozrzut cen)."""

from __future__ import annotations

from grunt.dedup import cluster
from grunt.dedup.pairing import Oferta, Werdykt

E0, N0 = 6_540_100.0, 6_027_300.0


def oferta(listing_id: int, **kwargs: object) -> Oferta:
    dane: dict[str, object] = {
        "portal": "morizon",
        "easting": E0,
        "northing": N0,
        "area_m2": 1000,
        "price_grosze": 300_000_00,
    }
    dane.update(kwargs)
    return Oferta(id=listing_id, **dane)  # type: ignore[arg-type]


def werdykt(a: int, b: int, pewnosc: float) -> Werdykt:
    return Werdykt(a_id=a, b_id=b, pewnosc=pewnosc, etap="phash")


def test_przechodniosc_sklejania() -> None:
    """A z B i B z C daje jeden klaster trzech ofert, choc pary A-C nie bylo."""
    przypisanie = cluster.przypisz([werdykt(11, 22, 0.9), werdykt(22, 33, 0.75)])
    assert przypisanie == {11: 11, 22: 11, 33: 11}


def test_numer_klastra_to_najmniejszy_identyfikator_niezaleznie_od_kolejnosci() -> None:
    """Dwa przebiegi po tych samych danych musza dac ten sam numer klastra."""
    a = cluster.przypisz([werdykt(50, 9, 0.8), werdykt(9, 30, 0.8)])
    b = cluster.przypisz([werdykt(9, 30, 0.8), werdykt(50, 9, 0.8)])
    assert a == b == {9: 9, 30: 9, 50: 9}


def test_para_ponizej_progu_nie_skleja() -> None:
    """0,60 to podejrzenie do przejrzenia, nie decyzja."""
    assert cluster.przypisz([werdykt(1, 2, 0.60)]) == {}


def test_oferta_bez_duplikatu_nie_dostaje_klastra() -> None:
    przypisanie = cluster.przypisz([werdykt(1, 2, 0.9)])
    assert 3 not in przypisanie


def test_kanoniczna_to_oferta_najbogatsza_w_dane() -> None:
    """Tansza, ale uboga oferta przegrywa z bogatsza: to ona trafia na liste."""
    uboga = oferta(1, price_grosze=250_000_00, area_m2=None, thumb_phash=None)
    bogata = oferta(2, price_grosze=300_000_00, thumb_phash="0" * 64, uldk_id="226101_1.0089.433/2")
    assert cluster.kanoniczna([uboga, bogata]) == 2


def test_kanoniczna_przy_remisie_wybiera_tansza() -> None:
    tansza = oferta(5, price_grosze=280_000_00)
    drozsza = oferta(4, price_grosze=310_000_00)
    assert cluster.kanoniczna([drozsza, tansza]) == 5


def test_podsumowanie_pokazuje_rozrzut_cen_miedzy_portalami() -> None:
    """Ta sama dzialka za 300 tys. i za 330 tys. to 10% rozrzutu."""
    oferty = [
        oferta(1, price_grosze=300_000_00),
        oferta(2, portal="nieruchomosci-online", price_grosze=330_000_00),
    ]
    klastry = cluster.podsumuj(oferty, cluster.przypisz([werdykt(1, 2, 0.9)]))

    assert len(klastry) == 1
    klaster = klastry[0]
    assert klaster.cluster_id == 1
    assert klaster.czlonkowie == (1, 2)
    assert klaster.portale == ("morizon", "nieruchomosci-online")
    assert klaster.rozrzut_cen is not None
    assert round(klaster.rozrzut_cen, 3) == 0.1


def test_rozrzut_bez_cen_to_null_a_nie_zero() -> None:
    """Zasada z CLAUDE.md: brak danych nie jest wartoscia zerowa."""
    oferty = [oferta(1, price_grosze=None), oferta(2, price_grosze=None)]
    klaster = cluster.podsumuj(oferty, cluster.przypisz([werdykt(1, 2, 0.9)]))[0]
    assert klaster.cena_min_grosze is None
    assert klaster.rozrzut_cen is None
