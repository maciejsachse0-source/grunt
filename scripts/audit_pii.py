"""Audyt danych osobowych w bazie. Kryterium akceptacji fazy 2.

Sekcja 8.2 dokumentu stawia zasade: zadnych imion, nazwisk, numerow telefonu
ani adresow e-mail ogloszeniodawcow. Numer telefonu wolno trzymac wylacznie
jako SHA-256, na potrzeby deduplikacji. Ta jedna decyzja usuwa wiekszosc
ryzyka RODO, wiec nie moze opierac sie na dobrych checiach - musi byc
sprawdzalna zapytaniem.

Skrypt przeglada wszystkie kolumny tekstowe i jsonb w tabeli listings
i szuka wzorcow kontaktowych. Zwraca kod wyjscia 1, gdy cokolwiek znajdzie,
wiec nadaje sie do uruchamiania po kazdym przebiegu scrapera.

    uv run python scripts/audit_pii.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grunt.db import session_scope  # noqa: E402

app = typer.Typer(add_completion=False)
console = Console()

# Kolumny, ktore moglyby przenosic tresc z portalu
KOLUMNY_TEKSTOWE = ("title", "url", "przeznaczenie_raw", "geom_precision")

WZORCE = {
    "e-mail": r"[[:alnum:]._%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}",
    "telefon z separatorami": r"(\+48[[:space:]-]?)?[0-9]{3}[[:space:]-][0-9]{3}[[:space:]-][0-9]{3}",
    "telefon 9 cyfr po slowie tel": r"tel[[:space:].:]*[0-9]{9}",
}


@app.command()
def main(fail_on_find: bool = typer.Option(True, help="Kod wyjscia 1 przy trafieniu")) -> None:
    znaleziono = False
    table = Table(title="Audyt danych kontaktowych w tabeli listings")
    table.add_column("sprawdzenie")
    table.add_column("trafienia", justify="right")
    table.add_column("werdykt")

    with session_scope() as session:
        total = session.execute(text("SELECT count(*) FROM listings")).scalar_one()
        table.add_row("ofert w bazie", str(total), "")

        for opis, wzorzec in WZORCE.items():
            warunki = " OR ".join(
                f"coalesce({kolumna}, '') ~ :wzorzec" for kolumna in KOLUMNY_TEKSTOWE
            )
            warunki += " OR coalesce(raw_jsonb::text, '') ~ :wzorzec"
            count = session.execute(
                text(f"SELECT count(*) FROM listings WHERE {warunki}"), {"wzorzec": wzorzec}
            ).scalar_one()
            if count:
                znaleziono = True
            table.add_row(
                opis,
                str(count),
                "[red]ZNALEZIONO[/red]" if count else "[green]czysto[/green]",
            )

        # phone_sha256 moze istniec, ale musi byc hashem, a nie numerem
        zle_hashe = session.execute(
            text(
                """
                SELECT count(*) FROM listings
                WHERE phone_sha256 IS NOT NULL
                  AND phone_sha256 !~ '^[0-9a-f]{64}$'
                """
            )
        ).scalar_one()
        if zle_hashe:
            znaleziono = True
        table.add_row(
            "phone_sha256 nie jest hashem",
            str(zle_hashe),
            "[red]ZNALEZIONO[/red]" if zle_hashe else "[green]czysto[/green]",
        )

        # opisy ofert: dlugie teksty w raw_jsonb sugeruja skopiowana tresc
        dlugie = session.execute(
            text("SELECT count(*) FROM listings WHERE length(coalesce(raw_jsonb::text, '')) > 2000")
        ).scalar_one()
        if dlugie:
            znaleziono = True
        table.add_row(
            "raw_jsonb powyzej 2 kB (podejrzenie opisu)",
            str(dlugie),
            "[red]SPRAWDZ[/red]" if dlugie else "[green]czysto[/green]",
        )

    console.print(table)

    if znaleziono:
        console.print("[red]audyt wykryl dane, ktorych nie powinno tu byc[/red]")
        if fail_on_find:
            sys.exit(1)
    else:
        console.print("[green]brak danych kontaktowych w bazie[/green]")


if __name__ == "__main__":
    app()
