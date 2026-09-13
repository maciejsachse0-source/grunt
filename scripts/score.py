"""Policzenie score'u potencjalu dla wzbogaconych ofert (faza 3).

uv run python scripts/score.py run
uv run python scripts/score.py run --profil deweloper
uv run python scripts/score.py top --limit 15
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
from grunt.enrich import score_listings  # noqa: E402

app = typer.Typer(add_completion=False, help="Scoring potencjalu inwestycyjnego")
console = Console()


@app.command()
def run(
    limit: int = typer.Option(500, help="Ile ofert przeliczyc"),
    profil: str = typer.Option("detaliczny", help="detaliczny albo deweloper"),
    bez_wyceny: bool = typer.Option(False, help="Pomin deal score (szybciej)"),
) -> None:
    if profil not in ("detaliczny", "deweloper"):
        raise typer.BadParameter("profil musi byc detaliczny albo deweloper")

    with session_scope() as session:
        stats = score_listings.run(
            session,
            limit=limit,
            profil=profil,  # type: ignore[arg-type]
            z_wycena=not bez_wyceny,
        )

    console.print(
        f"[green]policzone[/green] {stats['policzone']} ofert: "
        f"z wynikiem {stats['z_wynikiem']}, bez danych {stats['bez_danych']}, "
        f"z deal score {stats['z_deal_score']}"
    )


@app.command()
def top(limit: int = typer.Option(15, help="Ile pozycji pokazac")) -> None:
    """Ranking wedlug score'u, tylko oferty o wystarczajacej kompletnosci."""
    with session_scope() as session:
        rows = (
            session.execute(
                text(
                    """
                SELECT s.score_total, s.coverage, s.deal_score, s.red_flags,
                       le.plan_status, le.media_koszt_pln,
                       l.area_m2, l.price_grosze/100 AS cena_zl, l.url, l.portal::text AS portal
                FROM scores s
                JOIN listings l ON l.id = s.listing_id
                LEFT JOIN listing_enrichment le ON le.listing_id = s.listing_id
                WHERE s.score_total IS NOT NULL AND s.coverage >= 0.4
                ORDER BY s.score_total DESC NULLS LAST
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

    table = Table(title="Ranking potencjalu")
    for kolumna in ("score", "kompl.", "deal", "plan", "pow.", "cena", "media", "flagi", "portal"):
        table.add_column(kolumna, justify="right" if kolumna != "portal" else "left")

    for row in rows:
        flagi = row["red_flags"] or []
        table.add_row(
            f"{float(row['score_total']):.1f}",
            f"{float(row['coverage']):.0%}",
            f"{float(row['deal_score']):.2f}" if row["deal_score"] is not None else "-",
            row["plan_status"] or "-",
            f"{row['area_m2']} m2" if row["area_m2"] else "-",
            f"{row['cena_zl']:,}".replace(",", " ") if row["cena_zl"] else "-",
            f"{row['media_koszt_pln'] // 1000}k" if row["media_koszt_pln"] else "-",
            str(len(flagi)),
            row["portal"][:12],
        )
    console.print(table)

    console.print("\n[cyan]czerwone flagi pierwszej oferty:[/cyan]")
    for flaga in (rows[0]["red_flags"] or [])[:4]:
        console.print(f"  - {flaga}")


if __name__ == "__main__":
    app()
