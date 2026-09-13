"""Testy ulubionych, notatek, ocen i zapisanych filtrow (sekcje 7.3 i 7.4).

Testy uderzaja w prawdziwa baze (marker db), bo logika siedzi w SQL-u.
Kazdy test sprzata po sobie: baza uzytkownika nie ma zostac ze smieciami.
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


@pytest.fixture
def oferta_id(client: TestClient, baza_dziala: bool) -> int:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    items = client.get("/api/listings", params={"limit": 1}).json()["items"]
    if not items:
        pytest.skip("baza nie ma ofert")
    return int(items[0]["id"])


@pytest.mark.db
def test_zapisanie_oferty_i_notatki(client: TestClient, oferta_id: int) -> None:
    try:
        odpowiedz = client.put(
            f"/api/saved/{oferta_id}",
            json={"status": "kontakt", "note": "test: dojazd zima", "tags": ["test"]},
        )
        assert odpowiedz.status_code == 200

        zapisane = client.get("/api/saved").json()
        moja = next(o for o in zapisane["items"] if o["id"] == oferta_id)
        assert moja["status"] == "kontakt"
        assert moja["note"] == "test: dojazd zima"
        assert moja["tags"] == ["test"]
        # karta zapisanej oferty niesie te same liczby, co lista
        assert "score" in moja and "deal_score" in moja and "aktywna" in moja
    finally:
        client.delete(f"/api/saved/{oferta_id}")


@pytest.mark.db
def test_ponowny_zapis_nadpisuje_zamiast_dublowac(client: TestClient, oferta_id: int) -> None:
    try:
        client.put(f"/api/saved/{oferta_id}", json={"status": "obserwuje"})
        client.put(f"/api/saved/{oferta_id}", json={"status": "odrzucona", "note": "za drogo"})

        zapisane = [o for o in client.get("/api/saved").json()["items"] if o["id"] == oferta_id]
        assert len(zapisane) == 1
        assert zapisane[0]["status"] == "odrzucona"
    finally:
        client.delete(f"/api/saved/{oferta_id}")


@pytest.mark.db
def test_filtr_po_statusie(client: TestClient, oferta_id: int) -> None:
    try:
        client.put(f"/api/saved/{oferta_id}", json={"status": "kupiona"})
        kupione = client.get("/api/saved", params={"status": "kupiona"}).json()
        assert any(o["id"] == oferta_id for o in kupione["items"])

        odrzucone = client.get("/api/saved", params={"status": "odrzucona"}).json()
        assert all(o["id"] != oferta_id for o in odrzucone["items"])
    finally:
        client.delete(f"/api/saved/{oferta_id}")


@pytest.mark.db
def test_ocena_zapisuje_sie_i_wraca_ostatnia(client: TestClient, oferta_id: int) -> None:
    """Historia ocen zostaje, interfejs pokazuje ostatnia (material z sekcji 5.6)."""
    try:
        client.put(f"/api/saved/{oferta_id}", json={"status": "obserwuje"})
        assert client.post(f"/api/saved/{oferta_id}/ocena", json={"verdict": 1}).status_code == 200
        assert client.post(f"/api/saved/{oferta_id}/ocena", json={"verdict": -1}).status_code == 200

        moja = next(o for o in client.get("/api/saved").json()["items"] if o["id"] == oferta_id)
        assert moja["ocena"] == -1
    finally:
        client.delete(f"/api/saved/{oferta_id}")


@pytest.mark.db
def test_zapis_nieistniejacej_oferty_to_404(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")
    assert client.put("/api/saved/999999999", json={"status": "obserwuje"}).status_code == 404


@pytest.mark.db
def test_usuniecie_niezapisanej_oferty_to_404(client: TestClient, oferta_id: int) -> None:
    client.delete(f"/api/saved/{oferta_id}")
    assert client.delete(f"/api/saved/{oferta_id}").status_code == 404


@pytest.mark.db
def test_zapisany_filtr_musi_dac_sie_wykonac(client: TestClient, baza_dziala: bool) -> None:
    """Literowka w nazwie pola przeszlaby cicho i alert szukalby czegos innego."""
    if not baza_dziala:
        pytest.skip("baza niedostepna")

    zly = client.post("/api/filters", json={"name": "test zly", "filter": {"cena_maksymalna": 100}})
    assert zly.status_code == 422
    assert "cena_maksymalna" in zly.json()["detail"]

    zly_typ = client.post("/api/filters", json={"name": "test typ", "filter": {"area_min": "duzo"}})
    assert zly_typ.status_code == 422


@pytest.mark.db
def test_cykl_zycia_zapisanego_filtru(client: TestClient, baza_dziala: bool) -> None:
    if not baza_dziala:
        pytest.skip("baza niedostepna")

    utworzony = client.post(
        "/api/filters",
        json={
            "name": "test: tanie budowlane",
            "filter": {"price_max": 250_000, "status_planistyczny": ["A", "B"]},
            "alert_enabled": False,
        },
    )
    assert utworzony.status_code == 200
    filter_id = utworzony.json()["id"]

    try:
        lista = client.get("/api/filters").json()["items"]
        moj = next(f for f in lista if f["id"] == filter_id)
        assert moj["filter"]["price_max"] == 250_000
        assert moj["alert_enabled"] is False
        assert moj["wyslane"] == 0

        assert (
            client.patch(f"/api/filters/{filter_id}", json={"alert_enabled": True}).status_code
            == 200
        )
        po_zmianie = next(
            f for f in client.get("/api/filters").json()["items"] if f["id"] == filter_id
        )
        assert po_zmianie["alert_enabled"] is True
    finally:
        assert client.delete(f"/api/filters/{filter_id}").status_code == 200

    assert client.delete(f"/api/filters/{filter_id}").status_code == 404
