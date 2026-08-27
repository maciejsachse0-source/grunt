"""Token na dane uzytkownika.

Dwie rzeczy warte pilnowania: bez API_WRITE_TOKEN nic sie nie zmienia (tak
chodzi srodowisko lokalne i reszta testow), a z tokenem router `saved` odrzuca
zadanie, zanim dotknie bazy. To drugie znaczy, ze te testy nie potrzebuja bazy.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from grunt.api.auth import wymagaj_tokenu
from grunt.api.main import app
from grunt.config import settings


def test_bez_konfiguracji_przepuszcza(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "api_write_token", None)
    assert wymagaj_tokenu(None) is None
    assert wymagaj_tokenu("cokolwiek") is None


def test_brak_naglowka_to_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "api_write_token", "sekret")
    with pytest.raises(HTTPException) as blad:
        wymagaj_tokenu(None)
    assert blad.value.status_code == 401


def test_zly_token_to_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """401 znaczy "nie przedstawiles sie", 403 "przedstawiles sie zle"."""
    monkeypatch.setattr(settings, "api_write_token", "sekret")
    with pytest.raises(HTTPException) as blad:
        wymagaj_tokenu("nie ten")
    assert blad.value.status_code == 403


def test_dobry_token_przechodzi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "api_write_token", "sekret")
    assert wymagaj_tokenu("sekret") is None


def test_saved_odrzuca_zanim_dotknie_bazy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "api_write_token", "sekret")
    client = TestClient(app)
    assert client.get("/api/saved").status_code == 401
    assert client.put("/api/saved/1", json={"status": "nowa"}).status_code == 401
    assert client.get("/api/filters").status_code == 401


def test_token_z_naglowka_wpuszcza_do_routera(monkeypatch: pytest.MonkeyPatch) -> None:
    """Z poprawnym tokenem zadanie idzie dalej, wiec 401 juz nie wroci.

    Co sie stanie dalej, zalezy od bazy, ktorej w tym tescie moze nie byc.
    raise_server_exceptions=False zamienia jej brak w 500 zamiast wyjatku:
    bez bazy dostaniemy 500, z baza 200, i jedno i drugie dowodzi, ze zapora
    przepuscila. Ten test nie ma markera db wlasnie dlatego.
    """
    monkeypatch.setattr(settings, "api_write_token", "sekret")
    client = TestClient(app, raise_server_exceptions=False)
    odpowiedz = client.get("/api/saved", headers={"X-Grunt-Token": "sekret"})
    assert odpowiedz.status_code in (200, 500)
