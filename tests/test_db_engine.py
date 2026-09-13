"""Wykrywanie poolera transakcyjnego.

Pomylka tutaj nie objawia sie przy pierwszym zapytaniu, tylko przy drugim,
komunikatem o juz istniejacym prepared statement. Stad test na kazdy z trzech
adresow, ktore realnie wystepuja: lokalny, pooler Supabase, polaczenie
bezposrednie do Supabase (tego uzywaja migracje).
"""

from __future__ import annotations

import pytest

from grunt.config import settings
from grunt.db import _tryb_poolera

LOKALNY = "postgresql+psycopg://grunt:grunt@localhost:5433/grunt"
POOLER = (
    "postgresql+psycopg://postgres.abcdef:haslo"
    "@aws-1-eu-central-1.pooler.supabase.com:6543/postgres"
)
BEZPOSREDNI = "postgresql+psycopg://postgres:haslo@db.abcdef.supabase.co:5432/postgres"


@pytest.fixture(autouse=True)
def bez_jawnego_ustawienia(monkeypatch: pytest.MonkeyPatch) -> None:
    """Domyslnie sprawdzamy samo wykrywanie, bez DB_POOLER z .env."""
    monkeypatch.setattr(settings, "db_pooler", None)


def test_lokalna_baza_to_nie_pooler() -> None:
    assert _tryb_poolera(LOKALNY) is False


def test_port_6543_to_pooler() -> None:
    assert _tryb_poolera(POOLER) is True


def test_polaczenie_bezposrednie_to_nie_pooler() -> None:
    """Port 5432 w Supabase to tryb sesji, gdzie prepared statements dzialaja."""
    assert _tryb_poolera(BEZPOSREDNI) is False


def test_jawne_ustawienie_wygrywa_z_wykrywaniem(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "db_pooler", True)
    assert _tryb_poolera(LOKALNY) is True
    monkeypatch.setattr(settings, "db_pooler", False)
    assert _tryb_poolera(POOLER) is False
