"""Jedyne miejsce rejestracji adapterow portali.

Nowy portal dodaje sie w dwoch linijkach: import i wpis w ADAPTERS. Nigdzie
indziej w kodzie nie ma listy portali, wiec runner, harmonogram i watchdog
dostaja nowy portal automatycznie.

Ktore portale sa faktycznie uruchamiane, decyduje PORTALS_ENABLED w .env.

OLX nie ma tu wpisu i dlugo nie bedzie mial: zwraca 403 nawet na robots.txt,
wiec nie da sie nawet sprawdzic, na co pozwala. Jedyne wyjscia to platny aktor
Apify albo podszycie sie pod przegladarke, a tego drugiego CLAUDE.md zabrania
wprost. Otodom ODZYSKAL wpis 2026-08-25: dokument mowil o 403, ale uczciwy
naglowek dostaje dzis 200 i "Allow: /" w robots.txt (szczegoly w otodom.py).
"""

from __future__ import annotations

from grunt.config import settings
from grunt.portals.base import PortalAdapter
from grunt.portals.gratka import GratkaAdapter
from grunt.portals.morizon import MorizonAdapter
from grunt.portals.nieruchomosci_online import NieruchomosciOnlineAdapter
from grunt.portals.otodom import OtodomAdapter

ADAPTERS: dict[str, PortalAdapter] = {
    MorizonAdapter.name: MorizonAdapter(),
    NieruchomosciOnlineAdapter.name: NieruchomosciOnlineAdapter(),
    OtodomAdapter.name: OtodomAdapter(),
    GratkaAdapter.name: GratkaAdapter(),
}


def get(name: str) -> PortalAdapter:
    try:
        return ADAPTERS[name]
    except KeyError:
        raise KeyError(
            f"nieznany portal: {name}. Dostepne: {', '.join(sorted(ADAPTERS))}"
        ) from None


def enabled() -> list[PortalAdapter]:
    """Adaptery wlaczone w konfiguracji, w kolejnosci z PORTALS_ENABLED."""
    names = settings.portals_enabled or list(ADAPTERS)
    return [ADAPTERS[name] for name in names if name in ADAPTERS]


def skipped() -> list[str]:
    """Nazwy z PORTALS_ENABLED, dla ktorych nie ma jeszcze adaptera.

    Watchdog ma o nich wiedziec, zeby cisza po portalu nie wygladala jak awaria.
    """
    return [name for name in settings.portals_enabled if name not in ADAPTERS]
