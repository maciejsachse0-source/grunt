"""Testy kolejnosci osi. Sekcja 19 dokumentu: to zjada wiecej czasu niz wszystko inne.

Punkt referencyjny: dzialka w Gdansku, dla ktorej dokument podaje oba zapisy
tej samej lokalizacji:
    ULDK EPSG:2180  xy=477471,720567
    ULDK WGS84      xy=18.6533,54.3487,4326
Jesli te dwa zapisy rozjada sie o wiecej niz kilkanascie metrow, cos jest zle
w transformacji, a nie w tescie.
"""

from __future__ import annotations

import math

import pytest

from grunt.sources import geo

# Gdansk, dzialka 226101_1.0089.433/2
GDANSK_LAT = 54.3487
GDANSK_LON = 18.6533
GDANSK_EASTING = 477471.0
GDANSK_NORTHING = 720567.0

# Kartuzy, punkt kontrolny w glebi ladu (dokument: NMT zwraca ok. 215 m n.p.m.)
KARTUZY_LAT = 54.3336
KARTUZY_LON = 18.1976


def test_wgs84_na_pl1992_zgadza_sie_z_przykladem_uldk() -> None:
    p = geo.wgs84_to_pl1992(GDANSK_LAT, GDANSK_LON)
    assert p.easting == pytest.approx(GDANSK_EASTING, abs=2.0)
    assert p.northing == pytest.approx(GDANSK_NORTHING, abs=2.0)


def test_roundtrip_2180_4326() -> None:
    back = geo.pl1992_to_wgs84(GDANSK_EASTING, GDANSK_NORTHING)
    assert back.lat == pytest.approx(GDANSK_LAT, abs=1e-4)
    assert back.lon == pytest.approx(GDANSK_LON, abs=1e-4)


def test_uldk_ma_kolejnosc_easting_northing() -> None:
    p = geo.PL1992(easting=GDANSK_EASTING, northing=GDANSK_NORTHING)
    assert geo.uldk_xy(p) == "477471.00,720567.00"


def test_uldk_wgs84_ma_kolejnosc_lon_lat_srid() -> None:
    assert geo.uldk_xy_wgs84(GDANSK_LAT, GDANSK_LON) == "18.6533000,54.3487000,4326"


def test_nmt_ma_kolejnosc_odwrotna_niz_uldk() -> None:
    """NMT: x=northing, y=easting. To najczestsze zrodlo cichych bledow."""
    p = geo.PL1992(easting=GDANSK_EASTING, northing=GDANSK_NORTHING)
    params = geo.nmt_params(p)
    assert params["x"] == "720567.00"  # northing
    assert params["y"] == "477471.00"  # easting
    assert params["x"] != geo.uldk_xy(p).split(",")[0]


def test_wms_bbox_zaczyna_sie_od_northing() -> None:
    p = geo.PL1992(easting=GDANSK_EASTING, northing=GDANSK_NORTHING)
    bbox = geo.bbox_around(p, 100)
    assert geo.wms_bbox(bbox) == "720467.00,477371.00,720667.00,477571.00"


def test_wfs_bbox_dokleja_srs() -> None:
    p = geo.PL1992(easting=GDANSK_EASTING, northing=GDANSK_NORTHING)
    assert geo.wfs_bbox(geo.bbox_around(p, 100)).endswith(",EPSG:2180")


def test_getfeatureinfo_ma_styles_i_punkt_w_srodku() -> None:
    """MapServer GUGiK bez STYLES zwraca MissingParameterValue."""
    p = geo.PL1992(easting=GDANSK_EASTING, northing=GDANSK_NORTHING)
    params = geo.wms_getfeatureinfo_params("przewod_wodociagowy", p, size_px=101)
    assert params["STYLES"] == ""
    assert params["I"] == params["J"] == 50
    assert params["CRS"] == "EPSG:2180"


def test_zamieniona_kolejnosc_lat_lon_wybucha() -> None:
    """Chcemy glosnego bledu zamiast cichej odpowiedzi z innego miejsca w Polsce."""
    with pytest.raises(geo.AxisOrderError):
        geo.wgs84_to_pl1992(GDANSK_LON, GDANSK_LAT)


def test_wspolrzedne_wgs84_wpuszczone_jako_metry_wybuchaja() -> None:
    with pytest.raises(geo.AxisOrderError):
        geo.PL1992(easting=18.6533, northing=54.3487)


def test_bbox_wymaga_dodatniego_promienia() -> None:
    p = geo.PL1992(easting=GDANSK_EASTING, northing=GDANSK_NORTHING)
    with pytest.raises(ValueError):
        geo.bbox_around(p, 0)


def test_dystans_w_2180_jest_w_metrach() -> None:
    """Sanity check: 1 km na wschod w EPSG:2180 to naprawde ok. 1 km."""
    a = geo.PL1992(easting=GDANSK_EASTING, northing=GDANSK_NORTHING)
    b = geo.PL1992(easting=GDANSK_EASTING + 1000, northing=GDANSK_NORTHING)
    wa, wb = geo.pl1992_to_wgs84(*a.as_tuple_en()), geo.pl1992_to_wgs84(*b.as_tuple_en())
    # przyblizenie haversine wystarczy do sprawdzenia rzedu wielkosci
    dlon = math.radians(wb.lon - wa.lon) * math.cos(math.radians(wa.lat)) * 6371000
    assert abs(dlon) == pytest.approx(1000, rel=0.01)


# ------------------------------------------------------------------ na zywo
# Uruchom swiadomie: uv run pytest -m network


@pytest.mark.network
def test_uldk_zwraca_dzialke_z_dokumentu() -> None:
    # przez wlasnego klienta, nie httpx wprost: ma throttling per domena,
    # bez ktorego uslugi GUGiK potrafia odpowiedziec bledem przy serii zapytan
    from grunt.sources import _http

    p = geo.PL1992(easting=GDANSK_EASTING, northing=GDANSK_NORTHING)
    r = _http.get(
        "https://uldk.gugik.gov.pl/",
        params={"request": "GetParcelByXY", "xy": geo.uldk_xy(p), "result": "id"},
    )
    status, _, payload = r.text.partition("\n")
    assert status.strip() == "0"
    assert payload.strip() == "226101_1.0089.433/2"


@pytest.mark.network
def test_nmt_zwraca_wysokosc_zgodna_z_terenem() -> None:
    """Gdansk ok. 5 m n.p.m., Kartuzy ok. 215 m. Przy zamienionych osiach wyjdzie co innego."""
    from grunt.sources import _http

    def height(lat: float, lon: float) -> float:
        p = geo.wgs84_to_pl1992(lat, lon)
        r = _http.get("https://services.gugik.gov.pl/nmt/", params=geo.nmt_params(p))
        return float(r.text.strip().split()[-1])

    assert 0 <= height(GDANSK_LAT, GDANSK_LON) <= 30
    assert 150 <= height(KARTUZY_LAT, KARTUZY_LON) <= 280
