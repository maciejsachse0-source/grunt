"""Zakladka weryfikacyjna: /api/metodologia.

Testy pilnuja jednej rzeczy: strona ma byc odczytem z kodu i z bazy, a nie
druga kopia liczb. Kazdy prog, ktory tu wyjdzie, musi byc TA SAMA wartoscia,
ktorej uzywa scoring, bo inaczej uzytkownik weryfikuje opis zamiast systemu.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from grunt.api.main import app
from grunt.api.routers import metodologia
from grunt.jobs import scheduler
from grunt.scoring import gates, market, pillars, planning, valuation


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def baza_dziala(client: TestClient) -> bool:
    return client.get("/api/health").json()["database"].get("ok", False)


@pytest.mark.db
def test_metodologia_odpowiada(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    odpowiedz = client.get("/api/metodologia")
    assert odpowiedz.status_code == 200
    dane = odpowiedz.json()
    assert set(dane) == {
        "score",
        "wycena",
        "deal",
        "rynek",
        "zrodla",
        "zadania",
        "dane",
        "prywatnosc",
    }


@pytest.mark.db
def test_wagi_sa_te_same_co_w_scoringu(client: TestClient, baza_dziala: bool) -> None:
    """Gdyby strona miala wlasna kopie wag, weryfikowalaby sama siebie."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")

    filary = client.get("/api/metodologia").json()["score"]["filary"]
    z_api = {f["klucz"]: f["waga_detaliczny"] for f in filary if f["waga_detaliczny"] is not None}
    assert z_api == pillars.WAGI["detaliczny"]

    deweloper = {f["klucz"]: f["waga_deweloper"] for f in filary if f["waga_deweloper"] is not None}
    assert deweloper == pillars.WAGI["deweloper"]


@pytest.mark.db
def test_progi_pochodza_ze_stalych(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    dane = client.get("/api/metodologia").json()

    assert dane["score"]["coverage_min"] == pillars.COVERAGE_MIN
    assert dane["deal"]["prog_okazji"] == valuation.PROG_OKAZJI
    assert dane["wycena"]["parametry"]["maks_sigma_wiarygodna"] == valuation.MAX_SIGMA_RELIABLE
    assert dane["wycena"]["parametry"]["podloga_sigma"] == valuation.SIGMA_FLOOR_LOG
    assert dane["rynek"]["progi"]["min_kwartalow_trendu"] == market.MIN_KWARTALOW_TRENDU
    assert dane["rynek"]["progi"]["maks_indeksacja"] == market.MAX_INDEKSACJA


@pytest.mark.db
def test_kazdy_filar_ma_opis(client: TestClient, baza_dziala: bool) -> None:
    """Filar bez opisu to filar, ktorego nikt nie umie sprawdzic."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    for filar in client.get("/api/metodologia").json()["score"]["filary"]:
        assert filar["jak"], f"filar {filar['klucz']} bez opisu"
        assert filar["nazwa"]


def test_opisy_filarow_pokrywaja_wagi() -> None:
    """Nowy filar w scoringu ma sie pojawic tutaj, a nie zniknac po cichu."""
    z_wag = set(pillars.WAGI["detaliczny"]) | set(pillars.WAGI["deweloper"])
    assert z_wag <= set(metodologia.FILARY_OPIS)
    assert set(metodologia.FILARY_OPIS) <= set(pillars.NAZWY)


def test_katalog_gates_wymienia_wszystkie_mnozniki() -> None:
    """Katalog jest generowany z gates.evaluate, wiec nie da sie go przeoczyc."""
    katalog = {nazwa: mnoznik for nazwa, mnoznik, _ in metodologia._katalog_gates()}
    assert katalog["brak_dostepu_do_drogi"] == gates.BRAK_DOSTEPU_DO_DROGI
    assert katalog["poza_ouz"] == gates.POZA_OUZ_BEZ_MPZP
    assert katalog["powodz_q1"] == gates.STREFA_ZALEWOWA_Q1
    assert katalog["grunt_lesny"] == gates.GRUNT_LESNY_BEZ_ODLESIENIA
    assert len(katalog) == len({n for n, _, _ in metodologia._katalog_gates()})


@pytest.mark.db
def test_statusy_planistyczne_maja_widelki_z_planning(
    client: TestClient, baza_dziala: bool
) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    statusy = client.get("/api/metodologia").json()["score"]["statusy_planistyczne"]
    assert {s["status"] for s in statusy} == set(planning.MNOZNIKI)
    for wiersz in statusy:
        widelki = planning.MNOZNIKI[wiersz["status"]]
        assert (wiersz["mnoznik_min"], wiersz["mnoznik_max"]) == widelki
        assert wiersz["opis"] == planning.OPISY[wiersz["status"]]


@pytest.mark.db
def test_zadania_odpowiadaja_harmonogramowi(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    zadania = client.get("/api/metodologia").json()["zadania"]
    assert [z["kind"] for z in zadania] == [z.kind for z in scheduler.HARMONOGRAM]


@pytest.mark.db
def test_audyt_danych_osobowych_nie_znajduje_naruszen(
    client: TestClient, baza_dziala: bool
) -> None:
    """To jest test zasady z CLAUDE.md, nie tylko endpointu.

    Kolumna mogaca trzymac dane ogloszeniodawcy albo ma jawne uzasadnienie,
    albo jej nie ma. Nowa kolumna 'telefon' wywali ten test, i o to chodzi.
    """
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    prywatnosc = client.get("/api/metodologia").json()["prywatnosc"]
    assert prywatnosc["naruszenia"] == []
    dozwolone = {(d["table_name"], d["column_name"]) for d in prywatnosc["dozwolone"]}
    assert ("listings", "phone_sha256") in dozwolone


@pytest.mark.db
def test_pokrycie_filaru_nie_przekracza_liczby_ofert(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    for filar in client.get("/api/metodologia").json()["score"]["filary"]:
        assert 0 <= filar["ma_dane"] <= filar["z_ilu"]


@pytest.mark.db
def test_rozklad_deal_score_jest_spojny(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    rozklad = client.get("/api/metodologia").json()["deal"]["rozklad"]
    if not rozklad["z_deal_score"]:
        pytest.skip("brak policzonych deal score")
    assert rozklad["min"] <= rozklad["p25"] <= rozklad["mediana"]
    assert rozklad["mediana"] <= rozklad["p75"] <= rozklad["max"]
    assert 0 <= rozklad["powyzej_progu"] <= rozklad["z_deal_score"]
