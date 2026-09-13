"""Alerty Telegram. Sekcja 7.4 dokumentu.

Natychmiastowe powiadomienie przy trafieniu w zapisany filtr, z przyciskami
inline (Zapisz, Ukryj, Otworz). Bot jest darmowy i wysyla z komputera
uzytkownika, wiec dziala takze w wariancie lokalnym.

Bez tokena w .env modul dziala w trybie sucho: formatuje wiadomosc i zwraca ja
zamiast wysylac. Dzieki temu da sie testowac tresc alertow bez konta i bez
sieci, a brak konfiguracji nie wywala harmonogramu.

Zasada z sekcji 8.2 obowiazuje takze tutaj: w alercie nie ma danych
kontaktowych sprzedajacego, jest link do oferty.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from grunt.config import settings

API = "https://api.telegram.org"


class TelegramError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Alert:
    tytul: str
    url: str
    cena_zl: int | None = None
    powierzchnia_m2: int | None = None
    score: float | None = None
    deal_score: float | None = None
    coverage: float | None = None
    plan_status: str | None = None
    koszt_mediow_pln: int | None = None
    flagi: tuple[str, ...] = field(default_factory=tuple)

    def na_tekst(self) -> str:
        """Wiadomosc w Markdown. Liczby przed opisem, bo alert czyta sie na telefonie."""
        linie: list[str] = [f"*{_escape(self.tytul)}*"]

        podstawa: list[str] = []
        if self.cena_zl:
            podstawa.append(f"{self.cena_zl:,} zl".replace(",", " "))
        if self.powierzchnia_m2:
            podstawa.append(f"{self.powierzchnia_m2} m2")
        if self.cena_zl and self.powierzchnia_m2:
            podstawa.append(f"{self.cena_zl // self.powierzchnia_m2} zl/m2")
        if podstawa:
            linie.append(" · ".join(podstawa))

        ocena: list[str] = []
        if self.score is not None:
            ocena.append(f"score {self.score:.0f}")
        if self.deal_score is not None:
            ocena.append(f"deal {self.deal_score:+.1f}")
        if self.coverage is not None:
            ocena.append(f"kompletnosc {self.coverage:.0%}")
        if ocena:
            linie.append(" · ".join(ocena))

        if self.plan_status:
            linie.append(f"status planistyczny: {self.plan_status}")
        if self.koszt_mediow_pln:
            linie.append(f"media do doprowadzenia: ok. {self.koszt_mediow_pln // 1000} tys. zl")

        for flaga in self.flagi[:3]:
            linie.append(f"⚠ {_escape(flaga)}")

        return "\n".join(linie)

    def klawiatura(self) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "Zapisz", "callback_data": f"save:{self.url[-40:]}"},
                    {"text": "Ukryj", "callback_data": f"hide:{self.url[-40:]}"},
                    {"text": "Otworz", "url": self.url},
                ]
            ]
        }


def _escape(tekst: str) -> str:
    """Minimalne escapowanie Markdown, zeby nawias w tytule nie psul wiadomosci."""
    for znak in ("*", "_", "`", "["):
        tekst = tekst.replace(znak, f"\\{znak}")
    return tekst


def skonfigurowany() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def send(alert: Alert, *, dry_run: bool | None = None) -> dict[str, Any]:
    """Wysylka alertu. Bez tokena zwraca tresc zamiast wysylac."""
    tresc = alert.na_tekst()
    sucho = (not skonfigurowany()) if dry_run is None else dry_run

    if sucho:
        return {"wyslane": False, "powod": "brak konfiguracji Telegrama", "tresc": tresc}

    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": tresc,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
        "reply_markup": json.dumps(alert.klawiatura()),
    }
    url = f"{API}/bot{settings.telegram_bot_token}/sendMessage"
    try:
        response = httpx.post(url, data=payload, timeout=20)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise TelegramError(f"nie udalo sie wyslac alertu: {exc}") from exc

    return {"wyslane": True, "tresc": tresc, "odpowiedz": response.json().get("ok")}


def send_text(tekst: str, *, dry_run: bool | None = None) -> dict[str, Any]:
    """Zwykla wiadomosc, uzywana przez watchdoga."""
    sucho = (not skonfigurowany()) if dry_run is None else dry_run
    if sucho:
        return {"wyslane": False, "powod": "brak konfiguracji Telegrama", "tresc": tekst}

    url = f"{API}/bot{settings.telegram_bot_token}/sendMessage"
    try:
        response = httpx.post(
            url,
            data={"chat_id": settings.telegram_chat_id, "text": tekst},
            timeout=20,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise TelegramError(f"nie udalo sie wyslac wiadomosci: {exc}") from exc
    return {"wyslane": True, "tresc": tekst}
