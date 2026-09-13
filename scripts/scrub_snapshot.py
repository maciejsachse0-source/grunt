"""Usuwanie danych kontaktowych ze snapshotow HTML.

Sekcja 18.3 dokumentu kaze trzymac zapisane strony portali jako podstawe testow
adapterow. Sekcja 8.2 zabrania przechowywania numerow telefonu i adresow e-mail
ogloszeniodawcow. Te dwie rzeczy sa sprzeczne tylko pozornie: do testu selektorow
potrzebna jest STRUKTURA strony, a nie czyjs numer telefonu.

Kazdy nowy snapshot przepuszczamy przez ten skrypt zanim trafi do repozytorium:

    uv run python scripts/scrub_snapshot.py tests/snapshots/morizon/detail.html
    uv run python scripts/scrub_snapshot.py tests/snapshots --check

Podmieniamy na wartosci zastepcze, a nie usuwamy, zeby nie zmienic struktury
dokumentu, ktora testujemy.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(add_completion=False)
console = Console()

PHONE_PLACEHOLDER = "+48 500 000 000"
PHONE_PLACEHOLDER_PLAIN = "500000000"
EMAIL_PLACEHOLDER = "kontakt@example.invalid"

# Domeny operatorow portali. To adresy firmowe (biuro obslugi, inspektor RODO),
# nie dane ogloszeniodawcow, i sa czescia struktury strony.
CORPORATE_DOMAINS = (
    "morizon-gratka.pl",
    "nieruchomosci-online.pl",
    "morizon.pl",
    "gratka.pl",
    "lendi.pl",
    "sentry.io",
    "example.invalid",
)

# 1. linki tel: oraz atrybuty data-phone
PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(tel:)\+?[\d\s\-()]{7,20}"), r"\g<1>" + PHONE_PLACEHOLDER),
    (
        re.compile(
            r'(["\']?(?:telephone|phone|telefon|phoneNumber)["\']?\s*[:=]\s*["\'])'
            r'\+?[\d\s\-()]{7,20}(["\'])',
            re.I,
        ),
        r"\g<1>" + PHONE_PLACEHOLDER + r"\g<2>",
    ),
    # 2. numery w formacie polskim Z SEPARATORAMI. Bez separatorow nie ruszamy,
    #    bo identyfikatory ofert (mzn2047458917, 26827193) tez sa ciagami cyfr.
    (
        re.compile(r"(?<![\d/])(?:\+48[\s\-]?)?\d{3}[\s\-]\d{3}[\s\-]\d{3}(?![\d/])"),
        PHONE_PLACEHOLDER,
    ),
    (re.compile(r"(?<![\d/])\+48[\s\-]?\d{9}(?![\d/])"), PHONE_PLACEHOLDER),
)


def _scrub_emails(text: str) -> tuple[str, int]:
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        address = match.group(0)
        if any(
            address.lower().endswith(d) or f"@{d}" in address.lower() for d in CORPORATE_DOMAINS
        ):
            return address
        count += 1
        return EMAIL_PLACEHOLDER

    return re.sub(r"[\w.+-]+@[\w-]+\.[\w.]{2,}", repl, text), count


def _is_placeholder(value: str) -> bool:
    return PHONE_PLACEHOLDER in value or PHONE_PLACEHOLDER_PLAIN in value


def scrub(text: str) -> tuple[str, dict[str, int]]:
    """Idempotentne: drugie uruchomienie na tym samym pliku nic nie zmienia.

    Bez tego wartosc zastepcza sama pasuje do wzorca numeru i skrypt w kolko
    zglasza zmiany, przez co kontrola --check nigdy nie przechodzi.
    """
    stats: dict[str, int] = {"telefony": 0, "emaile": 0}
    for pattern, replacement in PATTERNS:

        def repl(match: re.Match[str], _replacement: str = replacement) -> str:
            if _is_placeholder(match.group(0)):
                return match.group(0)
            stats["telefony"] += 1
            return match.expand(_replacement)

        text = pattern.sub(repl, text)
    text, n = _scrub_emails(text)
    stats["emaile"] = n
    return text, stats


def find_remaining(text: str) -> list[str]:
    """Co jeszcze wyglada na dane kontaktowe po czyszczeniu."""
    hits: list[str] = []
    for match in re.finditer(
        r'(?:tel:|telephone["\']?\s*[:=])\s*["\']?([^"\'<>]{7,25})', text, re.I
    ):
        value = match.group(1).strip()
        # ciag bez co najmniej 7 cyfr to nie numer, tylko atrybut w rodzaju
        # autocomplete="tel" albo telephone=no
        if _is_placeholder(value) or sum(c.isdigit() for c in value) < 7:
            continue
        hits.append(value)
    for match in re.finditer(r"[\w.+-]+@[\w-]+\.[\w.]{2,}", text):
        address = match.group(0)
        if not any(d in address.lower() for d in CORPORATE_DOMAINS):
            hits.append(address)
    return hits


@app.command()
def main(
    target: Path = typer.Argument(..., help="Plik HTML albo katalog ze snapshotami"),
    check: bool = typer.Option(
        False, help="Tylko sprawdz, nie zapisuj. Kod wyjscia 1 przy trafieniu"
    ),
) -> None:
    files = sorted(target.rglob("*.html")) if target.is_dir() else [target]
    if not files:
        console.print(f"[yellow]brak plikow HTML w {target}[/yellow]")
        raise typer.Exit(code=0)

    dirty = False
    for path in files:
        original = path.read_text(encoding="utf-8")
        cleaned, stats = scrub(original)
        remaining = find_remaining(cleaned)

        if check:
            if cleaned != original or remaining:
                dirty = True
                console.print(
                    f"[red]{path}[/red]: do wyczyszczenia "
                    f"(telefony {stats['telefony']}, e-maile {stats['emaile']}, "
                    f"pozostale {len(remaining)})"
                )
            else:
                console.print(f"[green]{path}[/green]: czysty")
            continue

        if cleaned != original:
            path.write_text(cleaned, encoding="utf-8")
            console.print(
                f"[cyan]{path}[/cyan]: telefony {stats['telefony']}, e-maile {stats['emaile']}"
            )
        else:
            console.print(f"[green]{path}[/green]: nic do zmiany")

        if remaining:
            console.print(f"  [yellow]sprawdz recznie: {remaining[:5]}[/yellow]")

    if check and dirty:
        sys.exit(1)


if __name__ == "__main__":
    app()
