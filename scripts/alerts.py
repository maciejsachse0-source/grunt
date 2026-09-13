"""Alerty i watchdog (faza 3).

    uv run python scripts/alerts.py watchdog
    uv run python scripts/alerts.py top --limit 3        # alert o najlepszych ofertach
    uv run python scripts/alerts.py test                 # sprawdzenie konfiguracji bota

Bez TELEGRAM_BOT_TOKEN i TELEGRAM_CHAT_ID w .env wszystko dziala na sucho:
tresc jest pokazywana zamiast wysylana.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grunt.alerts import saved_filters, telegram, watchdog  # noqa: E402
from grunt.db import session_scope  # noqa: E402

app = typer.Typer(add_completion=False, help="Alerty Telegram i watchdog")
console = Console()


@app.command()
def test() -> None:
    """Czy bot jest skonfigurowany i czy wiadomosc sie sklada."""
    alert = telegram.Alert(
        tytul="Dzialka testowa, Kartuzy",
        url="https://example.invalid/oferta/test",
        cena_zl=250_000,
        powierzchnia_m2=1000,
        score=74.0,
        deal_score=1.8,
        coverage=0.73,
        plan_status="B",
        koszt_mediow_pln=25_500,
        flagi=("waski front (14 m)",),
    )
    wynik = telegram.send(alert)
    console.print(f"[cyan]skonfigurowany:[/cyan] {telegram.skonfigurowany()}")
    console.print(f"[cyan]wyslane:[/cyan] {wynik['wyslane']}")
    console.print("\n[cyan]tresc alertu:[/cyan]\n")
    console.print(wynik["tresc"])
    if not wynik["wyslane"]:
        console.print(
            "\n[yellow]uzupelnij TELEGRAM_BOT_TOKEN i TELEGRAM_CHAT_ID w .env, "
            "zeby alerty naprawde wychodzily[/yellow]"
        )


@app.command()
def watchdog_check() -> None:
    """Sprawdzenie stanu systemu i alarm, gdy portal ucichl."""
    with session_scope() as session:
        wynik = watchdog.powiadom(session)
    console.print(wynik["tresc"])
    console.print(
        f"\n[cyan]alarmy:[/cyan] {wynik['alarmy']}, "
        f"[cyan]uwagi:[/cyan] {wynik['problemy'] - wynik['alarmy']}, "
        f"[cyan]wyslane:[/cyan] {wynik['wyslane']}"
    )


@app.command()
def top(limit: int = typer.Option(3, help="Ile ofert zaalarmowac")) -> None:
    """Alert o najlepiej ocenionych ofertach z bazy."""
    with session_scope() as session:
        rows = (
            session.execute(
                text(
                    """
                SELECT l.title, l.url, l.price_grosze/100 AS cena_zl, l.area_m2,
                       s.score_total, s.deal_score, s.coverage, s.red_flags,
                       le.plan_status, le.media_koszt_pln
                FROM scores s
                JOIN listings l ON l.id = s.listing_id
                LEFT JOIN listing_enrichment le ON le.listing_id = s.listing_id
                WHERE s.score_total IS NOT NULL AND s.coverage >= 0.4
                ORDER BY s.score_total DESC
                LIMIT :limit
                """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )

    if not rows:
        console.print("[yellow]brak ofert z policzonym score'em[/yellow]")
        return

    for row in rows:
        alert = telegram.Alert(
            tytul=row["title"] or "Dzialka",
            url=row["url"],
            cena_zl=int(row["cena_zl"]) if row["cena_zl"] else None,
            powierzchnia_m2=row["area_m2"],
            score=float(row["score_total"]),
            deal_score=float(row["deal_score"]) if row["deal_score"] is not None else None,
            coverage=float(row["coverage"]),
            plan_status=row["plan_status"],
            koszt_mediow_pln=row["media_koszt_pln"],
            flagi=tuple(row["red_flags"] or []),
        )
        wynik = telegram.send(alert)
        console.print(f"\n[cyan]{'wyslane' if wynik['wyslane'] else 'na sucho'}:[/cyan]")
        console.print(wynik["tresc"])


@app.command()
def filtry() -> None:
    """Stan alertow per zapisany filtr."""
    with session_scope() as session:
        wiersze = saved_filters.status(session)

    if not wiersze:
        console.print(
            "[yellow]nie ma zapisanych filtrow[/yellow]. Zapisz filtr w aplikacji "
            "albo przez POST /api/filters"
        )
        return

    tabela = Table(title="Zapisane filtry")
    for kolumna in ("id", "nazwa", "alert", "wyslane", "ostatni przebieg"):
        tabela.add_column(kolumna)
    for row in wiersze:
        tabela.add_row(
            str(row["id"]),
            row["name"],
            "wlaczony" if row["alert_enabled"] else "-",
            str(row["wyslane"]),
            row["last_alert_at"].strftime("%Y-%m-%d %H:%M") if row["last_alert_at"] else "-",
        )
    console.print(tabela)


@app.command()
def filtry_run(
    dry_run: bool = typer.Option(True, "--dry-run/--wyslij", help="Podglad zamiast wysylki"),
) -> None:
    """Przebieg alertow z zapisanych filtrow.

    Pierwszy przebieg kazdego filtru niczego nie wysyla, tylko zapamietuje
    biezace trafienia. Inaczej wlaczenie alertu na pelnej bazie oznaczaloby
    kilkadziesiat powiadomien naraz.
    """
    with session_scope() as session:
        wynik = saved_filters.run(session, dry_run=dry_run)

    console.print(
        f"filtrow: {wynik['filtry']}, wyslanych alertow: [green]{wynik['wyslane']}[/green], "
        f"oznaczonych jako znane: {wynik['oznaczone_jako_znane']}"
    )
    for szczegol in wynik["szczegoly"]:
        znacznik = " (pierwszy przebieg, bez wysylki)" if szczegol["pierwszy_przebieg"] else ""
        console.print(
            f"  {szczegol['filtr']}: {szczegol['trafienia']} trafien, "
            f"{szczegol['wyslane']} wyslanych{znacznik}"
        )
    for blad in wynik["bledy"]:
        console.print(f"  [red]{blad}[/red]")
    if dry_run:
        console.print("[yellow]--dry-run: nic nie poszlo na Telegram[/yellow]")


if __name__ == "__main__":
    app()
