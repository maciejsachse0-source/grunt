"""Jednorazowe pobranie warstw fundamentowych (faza 0 z roadmapy).

Na dzis: RCN. Kolejne warstwy (OSM, BDOT10k, GDOS) dokladane sa tu jako osobne
podkomendy, zeby caly bootstrap byl jednym miejscem.

    uv run python scripts/bootstrap_data.py rcn --since 2023-01-01
    uv run python scripts/bootstrap_data.py rcn --powiaty 2261,2205 --since 2024-01-01
    uv run python scripts/bootstrap_data.py status
"""

from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

import typer
from rich.console import Console

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grunt.config import settings  # noqa: E402
from grunt.db import session_scope  # noqa: E402
from grunt.sources import rcn_import  # noqa: E402

app = typer.Typer(add_completion=False, help="Pobranie danych fundamentowych")
console = Console()


@app.command()
def rcn(
    since: str = typer.Option(
        "2023-01-01",
        help="Transakcje od tej daty. Model uczy sie na 24 miesiacach, "
        "starsze przydaja sie do trendu.",
    ),
    powiaty: str = typer.Option(
        "", help="Lista TERYT powiatow po przecinku. Puste = REGION_POWIATY z .env"
    ),
    teryt: str = typer.Option("", help="TERYT wojewodztwa. Puste = REGION_TERYT z .env"),
    delay: float = typer.Option(0.6, help="Odstep miedzy zapytaniami do uslugi, w sekundach"),
    max_minutes: float = typer.Option(0, help="Twardy limit czasu, 0 = bez limitu"),
) -> None:
    """Import Rejestru Cen Nieruchomosci z WFS GUGiK do PostGIS."""
    since_date = dt.date.fromisoformat(since)
    powiat_list = [p.strip() for p in powiaty.split(",") if p.strip()] or None
    region = teryt or settings.region_teryt

    console.print(f"[cyan]RCN[/cyan] wojewodztwo {region}, transakcje od {since_date}")
    console.print(f"powiaty: {powiat_list or settings.region_powiaty}")

    started = time.monotonic()
    tiles_seen = 0

    def progress(message: str) -> None:
        nonlocal tiles_seen
        tiles_seen += 1
        if tiles_seen % 10 == 0 or tiles_seen < 5:
            elapsed = time.monotonic() - started
            console.print(f"  [{elapsed:6.0f}s] {message}")
        if max_minutes and (time.monotonic() - started) > max_minutes * 60:
            raise TimeoutError("osiagnieto limit czasu podany w --max-minutes")

    with session_scope() as session:
        try:
            stats = rcn_import.import_region(
                session,
                teryt=region,
                powiaty=powiat_list,
                since=since_date,
                delay=delay,
                progress=progress,
            )
            console.print(f"[green]gotowe[/green] {stats.as_dict()}")
        except TimeoutError as exc:
            console.print(f"[yellow]przerwano: {exc}[/yellow] (to co pobrane jest juz w bazie)")

    status()


@app.command()
def status() -> None:
    """Co jest w bazie: kryterium akceptacji fazy 0."""
    with session_scope() as session:
        data = rcn_import.summary(session)
    console.print("[cyan]stan rcn_transactions[/cyan]")
    for key, value in data.items():
        console.print(f"  {key}: {value}")

    do_modelu = data.get("do_modelu") or 0
    if int(do_modelu) >= 20_000:
        console.print("[green]kryterium fazy 0 spelnione (>20 000 rekordow do modelu)[/green]")
    else:
        console.print(f"[yellow]do kryterium fazy 0 brakuje {20_000 - int(do_modelu)}[/yellow]")


if __name__ == "__main__":
    app()
