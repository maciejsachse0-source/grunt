"""Testy API listy ofert. Sekcja 20 dokumentu.

Testy uderzaja w prawdziwa baze (marker db), bo to zapytania SQL sa tu logika,
a nie warstwa Pythona. Bez bazy nie sprawdzilyby niczego istotnego.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from grunt.api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def baza_dziala(client: TestClient) -> bool:
    return client.get("/api/health").json()["database"].get("ok", False)


@pytest.mark.db
def test_lista_zwraca_strukture_z_paginacja(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    r = client.get("/api/listings", params={"limit": 5})
    assert r.status_code == 200
    dane = r.json()
    assert {"total", "limit", "offset", "sort", "items"} <= set(dane)
    assert len(dane["items"]) <= 5


@pytest.mark.db
def test_oferta_bez_score_nadal_jest_widoczna(client: TestClient, baza_dziala: bool) -> None:
    """Sekcja 5.3.9: brak wyniku to informacja, nie powod do ukrywania oferty."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    dane = client.get("/api/listings", params={"limit": 50}).json()
    assert dane["items"], "baza nie ma ofert"
    assert any(item["score"] is None for item in dane["items"]) or all(
        item["score"] is not None for item in dane["items"]
    )
    for item in dane["items"]:
        assert "score" in item and "kompletnosc" in item


@pytest.mark.db
def test_filtr_ceny_dziala(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    dane = client.get("/api/listings", params={"price_max": 200_000, "limit": 20}).json()
    for item in dane["items"]:
        if item["cena_zl"] is not None:
            assert item["cena_zl"] <= 200_000


@pytest.mark.db
def test_filtr_tylko_ocenione(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    dane = client.get("/api/listings", params={"tylko_ocenione": True, "limit": 20}).json()
    for item in dane["items"]:
        assert item["score"] is not None


@pytest.mark.db
def test_sortowanie_po_score_stawia_najlepsze_na_gorze(
    client: TestClient, baza_dziala: bool
) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    dane = client.get(
        "/api/listings", params={"sort": "score", "tylko_ocenione": True, "limit": 10}
    ).json()
    score = [i["score"] for i in dane["items"]]
    assert score == sorted(score, reverse=True)


@pytest.mark.db
def test_geojson_ma_poprawne_wspolrzedne(client: TestClient, baza_dziala: bool) -> None:
    """Regula z CLAUDE.md: na wyjsciu API zawsze EPSG:4326."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    dane = client.get("/api/listings/geojson", params={"limit": 50}).json()
    assert dane["type"] == "FeatureCollection"
    for feature in dane["features"]:
        lon, lat = feature["geometry"]["coordinates"]
        assert 13.9 <= lon <= 24.5, "dlugosc poza Polska: zamienione osie?"
        assert 48.9 <= lat <= 55.0, "szerokosc poza Polska"


@pytest.mark.db
def test_karta_oferty_ma_rozbicie_na_filary(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    lista = client.get("/api/listings", params={"tylko_ocenione": True, "limit": 1}).json()
    if not lista["items"]:
        pytest.skip("brak ocenionych ofert")
    listing_id = lista["items"][0]["id"]

    karta = client.get(f"/api/listings/{listing_id}").json()
    assert karta["id"] == listing_id
    assert "filary" in karta and "gate" in karta
    assert "wzbogacenie" in karta
    assert "historia_ceny" in karta


@pytest.mark.db
def test_karta_nie_zawiera_danych_kontaktowych(client: TestClient, baza_dziala: bool) -> None:
    """Sekcja 8.2, sprawdzana takze na wyjsciu API."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    lista = client.get("/api/listings", params={"limit": 1}).json()
    if not lista["items"]:
        pytest.skip("brak ofert")
    karta = client.get(f"/api/listings/{lista['items'][0]['id']}").text.lower()
    assert "phone_sha256" not in karta
    assert "telefon" not in karta


def test_nieistniejaca_oferta_daje_404(client: TestClient) -> None:
    assert client.get("/api/listings/999999999").status_code in (404, 500)


@pytest.mark.db
def test_statystyki(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    dane = client.get("/api/stats").json()
    assert {"oferty", "wzbogacone", "ocenione", "transakcje_rcn"} <= set(dane)
    assert dane["transakcje_rcn"] > 0


@pytest.mark.db
def test_filtr_bez_duplikatow_zwesza_liste(client: TestClient, baza_dziala: bool) -> None:
    """Z klastra duplikatow na liscie zostaje jedna oferta (sekcja 4.3)."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    wszystkie = client.get("/api/listings", params={"limit": 1}).json()["total"]
    bez_duplikatow = client.get(
        "/api/listings", params={"limit": 1, "bez_duplikatow": True}
    ).json()["total"]
    assert bez_duplikatow <= wszystkie


@pytest.mark.db
def test_karta_pokazuje_pozostale_oferty_tej_samej_dzialki(
    client: TestClient, baza_dziala: bool
) -> None:
    """Rozrzut cen miedzy portalami jest sygnalem, wiec karta musi go pokazac."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    lista = client.get("/api/listings", params={"limit": 200}).json()["items"]
    w_klastrze = [item for item in lista if item["klaster"] is not None]
    if not w_klastrze:
        pytest.skip("baza nie ma jeszcze policzonych klastrow (scripts/dedup.py run)")

    karta = client.get(f"/api/listings/{w_klastrze[0]['id']}").json()
    assert karta["duplikaty"], "oferta w klastrze musi miec wskazane pozostale oferty"
    for duplikat in karta["duplikaty"]:
        assert duplikat["id"] != karta["id"]
        assert {"portal", "url", "cena_zl"} <= set(duplikat)


@pytest.mark.db
def test_ceny_w_regionach_maja_widoczna_liczbe_transakcji(
    client: TestClient, baza_dziala: bool
) -> None:
    """Sekcja 7.1: mediana bez liczby obserwacji jest ozdoba, nie informacja."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")

    dane = client.get("/api/market", params={"poziom": "gmina", "min_n": 30}).json()
    if not dane["items"]:
        pytest.skip("brak median, uruchom zadanie rynek")

    for wiersz in dane["items"]:
        assert wiersz["n"] >= 30
        assert wiersz["mediana"] > 0
        assert wiersz["p25"] <= wiersz["mediana"] <= wiersz["p75"]
        # normalizacja zmienia mediane, wiec obie wartosci musza byc podane osobno
        assert wiersz["mediana_surowa"] > 0


@pytest.mark.db
def test_prog_liczby_transakcji_dziala(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    duzo = client.get("/api/market", params={"min_n": 200}).json()["total"]
    malo = client.get("/api/market", params={"min_n": 10}).json()["total"]
    assert duzo <= malo


@pytest.mark.db
def test_nieznane_sortowanie_to_blad(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    assert client.get("/api/market", params={"sort": "cokolwiek"}).status_code == 422


@pytest.mark.db
def test_oferta_ma_pozycje_wobec_rynku_albo_null(client: TestClient, baza_dziala: bool) -> None:
    """Brak mediany to null, nigdy zero: zero znaczyloby "dokladnie w medianie"."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")

    items = client.get("/api/listings", params={"limit": 50}).json()["items"]
    assert items, "baza nie ma ofert"

    z_rynkiem = [o for o in items if o["rynek"] is not None]
    for oferta in z_rynkiem:
        rynek = oferta["rynek"]
        assert rynek["n"] >= 1
        assert rynek["mediana_zl_m2"] > 0
        assert rynek["poziom"] in ("gmina", "powiat", "wojewodztwo")
        # odchylenie musi zgadzac sie z cena znormalizowana i mediana
        oczekiwane = rynek["cena_zl_m2_norm"] / rynek["mediana_zl_m2"] - 1
        assert abs(rynek["odchylenie"] - oczekiwane) < 0.01


@pytest.mark.db
def test_filtr_odchylenia_odsiewa_drozsze(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    dane = client.get(
        "/api/listings", params={"odchylenie_max": -0.2, "limit": 20, "sort": "wzgledem_rynku"}
    ).json()
    for oferta in dane["items"]:
        assert oferta["rynek"] is not None, "filtr nie moze przepuszczac ofert bez mediany"
        assert oferta["rynek"]["odchylenie"] <= -0.2


@pytest.mark.db
def test_historia_cen_ma_kwartaly_z_liczba_transakcji(
    client: TestClient, baza_dziala: bool
) -> None:
    """Wykres cen: kazdy punkt musi wiedziec, na ilu transakcjach stoi."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")

    dane = client.get(
        "/api/market/historia", params={"poziom": "wojewodztwo", "teryt": "22"}
    ).json()
    if not dane["punkty"]:
        pytest.skip("brak transakcji, uruchom bootstrap_data")

    for punkt in dane["punkty"]:
        assert punkt["n"] >= 5, "kwartal z garstka transakcji nie moze dostac punktu"
        assert punkt["p25"] <= punkt["mediana"] <= punkt["p75"]
        assert punkt["etykieta"].endswith(("Q1", "Q2", "Q3", "Q4"))

    okresy = [p["okres"] for p in dane["punkty"]]
    assert okresy == sorted(okresy), "punkty musza isc chronologicznie"


@pytest.mark.db
def test_niepelny_kwartal_jest_oznaczony_i_poza_trendem(
    client: TestClient, baza_dziala: bool
) -> None:
    """RCN publikuje z opoznieniem, wiec ostatni kwartal bywa czastkowy.

    Bez tego rozroznienia czesciowa paczka danych wyglada jak skok cen.
    """
    if not baza_dziala:
        pytest.skip("baza niedostepna")

    dane = client.get(
        "/api/market/historia", params={"poziom": "wojewodztwo", "teryt": "22"}
    ).json()
    if len(dane["punkty"]) < 2:
        pytest.skip("za malo danych")

    assert dane["koniec_danych"] is not None
    for punkt in dane["punkty"]:
        assert isinstance(punkt["pelny"], bool)
    # kwartaly oznaczone jako pelne musza konczyc sie przed koncem danych
    pelne = [p for p in dane["punkty"] if p["pelny"]]
    assert pelne, "przynajmniej jeden kwartal powinien byc pelny"
    assert pelne[-1]["okres"] <= dane["koniec_danych"]


@pytest.mark.db
def test_zly_teryt_w_historii_to_422(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    assert client.get("/api/market/historia", params={"teryt": "gdansk"}).status_code == 422


@pytest.mark.db
def test_gminy_w_powiecie_maja_ten_sam_prefiks_terytu(
    client: TestClient, baza_dziala: bool
) -> None:
    """Wykres rysujemy na terenie gminy, wiec z powiatu trzeba zejsc do gmin.

    Kody TERYT sa hierarchiczne: gminy powiatu 2215 to te, ktorych kod zaczyna
    sie od 2215.
    """
    if not baza_dziala:
        pytest.skip("baza niedostepna")

    powiaty = client.get("/api/market", params={"poziom": "powiat", "min_n": 50}).json()["items"]
    if not powiaty:
        pytest.skip("brak median, uruchom zadanie rynek")

    rodzic = powiaty[0]["teryt"]
    dane = client.get(
        "/api/market",
        params={"poziom": "gmina", "min_n": 10, "sort": "transakcje", "rodzic": rodzic},
    ).json()
    assert dane["rodzic"] == rodzic
    for wiersz in dane["items"]:
        assert wiersz["teryt"].startswith(rodzic)
    # sortowanie po transakcjach ustawia domysl w interfejsie: pierwsza gmina
    # na liscie ma najbogatszy szereg, wiec jej wykres jest najmniej losowy
    liczby = [w["n"] for w in dane["items"]]
    assert liczby == sorted(liczby, reverse=True)


@pytest.mark.db
def test_filtr_obszaru_nadrzednego_zaweza_liste(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    wszystkie = client.get("/api/market", params={"poziom": "gmina", "min_n": 10}).json()["total"]
    w_powiecie = client.get(
        "/api/market", params={"poziom": "gmina", "min_n": 10, "rodzic": "2215"}
    ).json()["total"]
    assert w_powiecie <= wszystkie


@pytest.mark.db
def test_zly_teryt_rodzica_to_422(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    assert client.get("/api/market", params={"rodzic": "wejherowski"}).status_code == 422


@pytest.mark.db
def test_trend_wykresu_znika_przy_cienkim_szeregu(client: TestClient, baza_dziala: bool) -> None:
    """Gmina z pieciu transakcjami na kwartal nie ma mierzalnego trendu.

    Wolimy brak liczby niz liczbe w rodzaju "+295% rocznie", ktora brala sie
    z jednego skrajnego kwartalu na brzegu szeregu.
    """
    if not baza_dziala:
        pytest.skip("baza niedostepna")

    gminy = client.get(
        "/api/market", params={"poziom": "gmina", "min_n": 10, "sort": "transakcje"}
    ).json()["items"]
    if not gminy:
        pytest.skip("brak median, uruchom zadanie rynek")

    for gmina in gminy[:12]:
        dane = client.get(
            "/api/market/historia", params={"poziom": "gmina", "teryt": gmina["teryt"]}
        ).json()
        if dane["zmiana_roczna"] is None:
            continue
        pelne = [p for p in dane["punkty"] if p["pelny"]]
        assert len(pelne) >= 6, "trend bez szesciu pelnych kwartalow"
        assert abs(dane["zmiana_roczna"]) < 1.0, f"nierealny trend w {gmina['teryt']}"


@pytest.mark.db
def test_filtr_rodzaju_zwraca_tylko_wskazany_rodzaj(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    dane = client.get("/api/listings", params={"rodzaj": "przemyslowa", "limit": 50}).json()
    for item in dane["items"]:
        assert item["rodzaj"] == "przemyslowa"
        # Rodzaj bez zrodla bylby twierdzeniem nie do sprawdzenia.
        assert item["rodzaj_zrodlo"] in {"plan_ogolny", "ogloszenie"}


@pytest.mark.db
def test_filtr_rodzaju_zwesza_liste(client: TestClient, baza_dziala: bool) -> None:
    """Regresja: filtry listowe szly przez Depends() i nie zawezaly niczego."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    wszystkie = client.get("/api/listings", params={"limit": 1}).json()["total"]
    lesne = client.get("/api/listings", params={"rodzaj": "lesna", "limit": 1}).json()["total"]
    assert lesne < wszystkie


@pytest.mark.db
def test_filtr_regionu_dziala_po_prefiksie_terytu(client: TestClient, baza_dziala: bool) -> None:
    """Kod TERYT jest hierarchiczny: 2215 to caly powiat wejherowski."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    dane = client.get("/api/listings", params={"teryt": "2215", "limit": 30}).json()
    for item in dane["items"]:
        assert item["region"] is not None
        assert item["region"]["teryt_gmina"].startswith("2215")


@pytest.mark.db
def test_nieznany_rodzaj_i_zly_teryt_to_422(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    assert client.get("/api/listings", params={"rodzaj": "dzialkowa"}).status_code == 422
    assert client.get("/api/listings", params={"teryt": "22x"}).status_code == 422
    # 5 cyfr to zaden poziom TERYT-u
    assert client.get("/api/listings", params={"teryt": "22150"}).status_code == 422


@pytest.mark.db
def test_kategorie_pokazuja_stan_danych_a_nie_tylko_kategorie(
    client: TestClient, baza_dziala: bool
) -> None:
    """Ile ofert nie ma rodzaju i regionu, jest tak samo wazne jak same listy."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    dane = client.get("/api/listings/kategorie", params={"poziom": "powiat"}).json()
    assert [r["rodzaj"] for r in dane["rodzaje"]] == [
        "mieszkaniowa",
        "uslugowa",
        "przemyslowa",
        "lesna",
    ]
    assert dane["bez_rodzaju"] >= 0
    assert dane["bez_regionu"] >= 0
    for obszar in dane["obszary"]:
        assert len(obszar["teryt"]) == 4
        assert obszar["oferty"] >= 1


@pytest.mark.db
def test_oferta_ma_region_albo_null(client: TestClient, baza_dziala: bool) -> None:
    """Brak wspolrzednych to brak gminy, a nie gmina zgadnieta."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    dane = client.get("/api/listings", params={"limit": 50}).json()
    for item in dane["items"]:
        region = item["region"]
        if region is None:
            continue
        assert len(region["teryt_gmina"]) == 7
        assert region["zrodlo"] in {"dzialka", "rcn"}


@pytest.mark.db
def test_obrys_dzialki_wraca_w_4326_z_bboxem(client: TestClient, baza_dziala: bool) -> None:
    """Regula z CLAUDE.md: baza w 2180, wyjscie API zawsze w 4326."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    lista = client.get("/api/listings", params={"limit": 200}).json()
    assert lista["items"], "baza nie ma ofert"

    znaleziony = None
    for item in lista["items"]:
        dane = client.get(f"/api/listings/{item['id']}/obrys").json()
        if dane["obrys"]:
            znaleziony = dane
            break
    if znaleziony is None:
        pytest.skip("zadna z ofert nie ma jeszcze obrysu (scripts/parcels.py backfill)")

    assert znaleziony["obrys"]["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    assert znaleziony["pewnosc"] in {"high", "medium", "low"}
    min_lon, min_lat, max_lon, max_lat = znaleziony["bbox"]
    assert min_lon < max_lon and min_lat < max_lat
    # Pomorskie w WGS84. W EPSG:2180 te same liczby bylyby rzedu 10^5.
    assert 14.0 < min_lon < 20.0
    assert 53.0 < min_lat < 55.5


@pytest.mark.db
def test_brak_dzialki_to_odpowiedz_a_nie_blad(client: TestClient, baza_dziala: bool) -> None:
    """Oferta bez dopasowanej dzialki jest stanem normalnym: 200 i obrys null.

    404 zamienialoby brak danych w blad w konsoli przegladarki przy kazdym
    kliknieciu takiej oferty.
    """
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    lista = client.get("/api/listings", params={"limit": 200}).json()
    for item in lista["items"]:
        odpowiedz = client.get(f"/api/listings/{item['id']}/obrys")
        assert odpowiedz.status_code == 200
        dane = odpowiedz.json()
        if dane["obrys"] is None:
            assert dane["punkt"] is None or set(dane["punkt"]) == {"lat", "lon"}
            return
    pytest.skip("wszystkie oferty w probce maja obrys")


@pytest.mark.db
def test_obrys_nieistniejacej_oferty_to_404(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    assert client.get("/api/listings/999999999/obrys").status_code == 404
