"""Testy klienta MPZP z Rejestru Urbanistycznego.

Snapshot: tests/fixtures/mpzp_wfs_gdansk.xml, trzy akty z Gdanska pobrane
2026-08-24. Testy nie dotykaja sieci poza tymi z markerem network.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from grunt.sources import geo, mpzp

FIXTURE = Path(__file__).parent / "fixtures" / "mpzp_wfs_gdansk.xml"


@pytest.fixture(scope="module")
def akty() -> list[mpzp.AktMpzp]:
    return mpzp.parse_akty(FIXTURE.read_text(encoding="utf-8"))


def test_parsuje_wszystkie_akty(akty: list[mpzp.AktMpzp]) -> None:
    assert len(akty) == 3
    assert all(a.lokalny_id for a in akty)
    assert all(a.tytul and "miejscowy plan" in a.tytul for a in akty)


def test_teryt_gminy_wyciagany_z_przestrzeni_nazw(akty: list[mpzp.AktMpzp]) -> None:
    """PL.ZIPPZP.2000/226101-MPZP -> 226101, czyli Gdansk."""
    assert {a.teryt_gmina for a in akty} == {"226101"}


def test_status_prawnie_wiazacy(akty: list[mpzp.AktMpzp]) -> None:
    assert all(a.obowiazujacy for a in akty)
    assert all(a.obowiazuje_od == dt.date(2024, 7, 11) for a in akty[:2])


def test_geometria_ma_poprawna_kolejnosc_osi(akty: list[mpzp.AktMpzp]) -> None:
    """Ten rejestr podaje posList jako easting northing, odwrotnie niz RCN.

    Bez rozpoznania kolejnosci po srsName geometria Gdanska (easting ok. 465 tys.,
    northing ok. 725 tys.) wyladowalaby z zamienionymi wspolrzednymi, czyli
    kilkaset kilometrow dalej, i nic by tego nie zglosilo.
    """
    from shapely import wkt as shapely_wkt

    for akt in akty:
        assert akt.geometria_wkt is not None
        ksztalt = shapely_wkt.loads(akt.geometria_wkt)
        srodek = ksztalt.representative_point()
        assert 440_000 < srodek.x < 500_000, "easting poza Gdanskiem"
        assert 700_000 < srodek.y < 745_000, "northing poza Gdanskiem"
        # kontrola dodatkowa: przeliczenie wraca na wspolrzedne Trojmiasta
        wgs = geo.pl1992_to_wgs84(srodek.x, srodek.y)
        assert 54.2 < wgs.lat < 54.6
        assert 18.3 < wgs.lon < 18.9


def test_bbox_ma_easting_przed_northingiem() -> None:
    """Ta usluga z krotkim kodem EPSG czyta BBOX jako easting, northing.

    geo.wfs_bbox daje kolejnosc odwrotna (poprawna dla uslug GUGiK) i na tym
    rejestrze zwraca zero obiektow. Stad osobny format.
    """
    punkt = geo.PL1992(easting=464_475.0, northing=725_243.0)
    bbox = geo.bbox_around(punkt, 50)
    param = mpzp.bbox_param(bbox)

    liczby = [float(v) for v in param.split(",")[:4]]
    assert liczby[0] < liczby[2] and liczby[1] < liczby[3]
    assert abs(liczby[0] - 464_425) < 1, "pierwsza wspolrzedna musi byc eastingiem"
    assert abs(liczby[1] - 725_193) < 1, "druga wspolrzedna musi byc northingiem"
    assert param.endswith("EPSG:2180")
    assert param != geo.wfs_bbox(bbox)


def test_pusta_odpowiedz_to_poprawny_wynik() -> None:
    """Punkt bez planu to informacja, nie blad."""
    pusta = (
        '<?xml version="1.0"?><wfs:FeatureCollection '
        'xmlns:wfs="http://www.opengis.net/wfs/2.0" numberMatched="0" numberReturned="0"/>'
    )
    assert mpzp.parse_akty(pusta) == []


def test_zepsuty_xml_to_blad_a_nie_cisza() -> None:
    with pytest.raises(mpzp.MpzpError):
        mpzp.parse_akty("<to nie jest xml")


def test_brak_aktu_nie_znaczy_brak_planu() -> None:
    """Rejestr ma 524 akty w kraju, wiec cisza nie jest dowodem (sekcja 5.3.3)."""
    info = mpzp.MpzpInfo(objeta_mpzp=False)
    assert info.uwaga is not None
    assert "nie dowod" in info.uwaga
    assert mpzp.MpzpInfo(objeta_mpzp=True).uwaga is None


@pytest.mark.network
def test_wfs_odpowiada_i_ma_znane_typy_obiektow() -> None:
    """Kontrola, czy usluga nadal wystawia to samo. Adresy z 2026-08-24."""
    from grunt.sources import _http

    odpowiedz = _http.get(
        mpzp.WFS_MPZP,
        params={"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetCapabilities"},
        timeout=60,
    )
    assert odpowiedz.status_code == 200
    assert mpzp.TYP_AKT in odpowiedz.text


@pytest.mark.network
def test_punkt_w_gdansku_jest_objety_mpzp() -> None:
    """Punkt wziety ze srodka aktu Klukowo. Sprawdza caly przebieg na zywo."""
    punkt = geo.PL1992(easting=464_475.0, northing=725_243.0)
    info = mpzp.sprawdz_punkt(punkt)

    assert info.objeta_mpzp is True
    assert info.akt is not None
    assert info.akt.teryt_gmina == "226101"
