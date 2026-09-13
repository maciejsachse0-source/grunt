"""Uruchomienie scrapera portali (faza 2).

    uv run python scripts/scrape.py run --portal morizon --max-pages 1 --max-details 3
    uv run python scripts/scrape.py run                 # wszystkie wlaczone portale
    uv run python scripts/scrape.py status
    uv run python scripts/scrape.py robots              # co wolno wedlug robots.txt

Higiena z sekcji 8.2 jest wbudowana i nie da sie jej wylaczyc przelacznikiem:
odstep miedzy zadaniami, uczciwy User-Agent z kontaktem i sprawdzanie robots.txt
przed kazdym adresem.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grunt.config import settings  # noqa: E402
from grunt.db import session_scope  # noqa: E402
from grunt.ingest import runner  # noqa: E402
from grunt.portals import registry  # noqa: E402

app = typer.Typer(add_completion=False, help="Scraper portali z ofertami dzialek")
console = Console()


@app.command()
def run(
    portal: str = typer.Option("", help="Nazwa portalu. Puste = wszystkie z PORTALS_ENABLED"),
    max_pages: int = typer.Option(0, help="Limit stron wynikow na adres. 0 = z .env"),
    max_details: int = typer.Option(-1, help="Limit stron detalu. -1 = bez limitu, 0 = wcale"),
    region: str = typer.Option("", help="TERYT wojewodztwa. Puste = REGION_TERYT z .env"),
) -> None:
    adapters = [registry.get(portal)] if portal else registry.enabled()
    if not adapters:
        console.print("[red]brak wlaczonych portali (PORTALS_ENABLED)[/red]")
        raise typer.Exit(code=1)

    pominiete = registry.skipped()
    if pominiete:
        console.print(f"[yellow]bez adaptera, pomijam: {', '.join(pominiete)}[/yellow]")

    try:
        runner.assert_honest_user_agent()
    except runner.ScraperConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    console.print(
        f"[cyan]user-agent:[/cyan] {settings.scraper_user_agent}\n"
        f"[cyan]odstep:[/cyan] {settings.scraper_delay_seconds}s"
    )

    # Przy 2 s odstepu kazde 1800 zadan to godzina. Bez tego ostrzezenia
    # "scrape.py run" bez parametrow startuje wielogodzinny przebieg w ciszy.
    if max_details < 0 and max_pages == 0:
        console.print(
            "[yellow]uwaga: brak limitow, przebieg moze trwac wiele godzin. "
            "Na probe uzyj --max-pages 1 --max-details 5[/yellow]"
        )

    def progress(message: str) -> None:
        console.print(f"  {message}")

    with session_scope() as session:
        results = runner.run_all(
            session,
            adapters,
            region_teryt=region or None,
            max_pages=max_pages or None,
            max_details=None if max_details < 0 else max_details,
            fetch_details=max_details != 0,
            progress=progress,
        )

    # "zalegle" to oferty, ktore juz byly w bazie, ale nigdy nie dostaly detalu
    # (np. bo poprzedni przebieg mial --max-details). Petla DIFF sama wciaga je
    # z powrotem do kolejki, wiec ta kolumna powinna z czasem schodzic do zera.
    table = Table(title="Przebieg scrapera")
    for column in (
        "portal",
        "strony",
        "oferty",
        "nowe",
        "zmienione",
        "bez zmian",
        "detale",
        "zalegle",
        "wygaszone",
    ):
        table.add_column(column, justify="right" if column != "portal" else "left")
    for stats in results:
        table.add_row(
            stats.portal,
            str(stats.pages_fetched),
            str(stats.stubs_seen),
            str(stats.new),
            str(stats.changed),
            str(stats.unchanged),
            str(stats.details_fetched),
            str(stats.missing_detail),
            str(stats.deactivated),
        )
    console.print(table)

    for stats in results:
        if stats.errors:
            console.print(f"[yellow]{stats.portal}: {stats.errors[:3]}[/yellow]")
        if stats.robots_blocked:
            console.print(
                f"[yellow]{stats.portal}: robots.txt zablokowal "
                f"{stats.robots_blocked} adresow[/yellow]"
            )


@app.command()
def backfill(
    portal: str = typer.Option(..., help="Nazwa portalu"),
    limit: int = typer.Option(100, help="Ile ofert uzupelnic w tym przebiegu"),
) -> None:
    """Pobranie detali dla ofert, ktore nigdy ich nie dostaly (brak wspolrzednych).

    Petla DIFF pobiera detal tylko dla ofert nowych i zmienionych, wiec oferty
    zapisane wczesniej zostaja bez geometrii. Ten tryb to domyka.
    """
    adapter = registry.get(portal)
    try:
        runner.assert_honest_user_agent()
    except runner.ScraperConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    console.print(
        f"[cyan]uzupelnianie detali[/cyan] {portal}, do {limit} ofert (ok. {limit * 2 // 60} min)"
    )
    with session_scope() as session:
        stats = runner.backfill_details(
            session, adapter, limit=limit, progress=lambda m: console.print(f"  {m}")
        )
    console.print(
        f"[green]gotowe[/green] pobrane={stats.details_fetched} "
        f"bledy={stats.details_failed} zablokowane={stats.robots_blocked}"
    )
    if stats.errors:
        console.print(f"[yellow]{stats.errors[:2]}[/yellow]")


@app.command()
def status() -> None:
    """Co jest w bazie per portal plus alarm watchdoga."""
    with session_scope() as session:
        rows = runner.last_run_summary(session)
        stale = runner.stale_portals(session)

    if not rows:
        console.print("[yellow]tabela listings jest pusta[/yellow]")
        return

    table = Table(title="Oferty w bazie")
    for column in (
        "portal",
        "aktywne",
        "wszystkie",
        "ze wspolrzednymi",
        "nowe 24h",
        "ostatnio widziane",
    ):
        table.add_column(column)
    for row in rows:
        table.add_row(
            str(row["portal"]),
            str(row["aktywne"]),
            str(row["wszystkie"]),
            str(row["ze_wspolrzednymi"]),
            str(row["nowe_24h"]),
            str(row["ostatnio_widziane"])[:19],
        )
    console.print(table)

    if stale:
        console.print(
            f"[red]watchdog: {', '.join(stale)} nie przyniosly nic nowego od 2 dni. "
            "To zwykle nie znaczy, ze rynek stanal, tylko ze zmienil sie HTML albo "
            "nas zablokowano[/red]"
        )


@app.command()
def robots(portal: str = typer.Option("", help="Nazwa portalu. Puste = wszystkie")) -> None:
    """Sprawdzenie, na co pozwala robots.txt. Uruchom przed pierwszym scrapowaniem."""
    guard = runner.RobotsGuard(settings.scraper_user_agent)
    adapters = [registry.get(portal)] if portal else registry.enabled()

    for adapter in adapters:
        console.print(f"\n[cyan]{adapter.name}[/cyan]")
        first = next(iter(adapter.list_urls(settings.region_teryt)), None)
        if first is None:
            continue
        probes = [first]
        for page in (2, 10, 11, 50):
            candidate = adapter.next_page_url(first, page)
            probes.append(candidate or f"(adapter nie generuje strony {page})")

        for probe in probes:
            if probe.startswith("("):
                console.print(f"  [green]OK[/green]  {probe}")
                continue
            verdict = "[green]wolno[/green]" if guard.allowed(probe) else "[red]ZABRONIONE[/red]"
            console.print(f"  {verdict}  {probe}")


if __name__ == "__main__":
    app()
