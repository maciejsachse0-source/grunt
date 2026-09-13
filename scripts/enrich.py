"""Wzbogacanie ofert danymi publicznymi (faza 3).

    uv run python scripts/enrich.py run --limit 10
    uv run python scripts/enrich.py status
    uv run python scripts/enrich.py show --listing-id 123

Jedna oferta to ok. 20 zapytan do uslug publicznych, czyli kilkanascie sekund.
Domyslny limit jest maly celowo.
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
from grunt.enrich import pipeline  # noqa: E402

app = typer.Typer(add_completion=False, help="Wzbogacanie ofert danymi publicznymi")
console = Console()


@app.command()
def run(
    limit: int = typer.Option(10, help="Ile ofert wzbogacic w tym przebiegu"),
    delay: float = typer.Option(0.5, help="Odstep miedzy zapytaniami do uslug"),
    max_wiek_dni: int = typer.Option(30, help="Powyzej tego wieku wzbogacamy ponownie"),
) -> None:
    console.print(f"[cyan]wzbogacanie[/cyan] do {limit} ofert, odstep {delay}s")

    with session_scope() as session:
        stats = pipeline.run(
            session,
            limit=limit,
            max_wiek_dni=max_wiek_dni,
            delay=delay,
            progress=lambda msg: console.print(f"  {msg}"),
        )

    console.print(
        f"[green]gotowe[/green] przetworzone={stats['przetworzone']} "
        f"bledy={stats['bledy']} sredni coverage={stats.get('coverage_sredni', 0):.0%}"
    )


@app.command()
def status() -> None:
    """Ile ofert wzbogacono i jak wypada kryterium akceptacji fazy 3."""
    with session_scope() as session:
        podsumowanie = (
            session.execute(
                text(
                    """
                SELECT count(*) AS wzbogacone,
                       count(*) FILTER (WHERE coverage >= 0.4) AS nad_progiem,
                       round(avg(coverage), 3) AS sredni_coverage,
                       count(*) FILTER (WHERE parcel_match IN ('high','medium')) AS pewna_dzialka,
                       count(*) FILTER (WHERE media_koszt_pln IS NOT NULL) AS z_kosztem_mediow,
                       count(*) FILTER (WHERE array_length(strefy_powodziowe, 1) > 0) AS zalewowe
                FROM listing_enrichment
                """
                )
            )
            .mappings()
            .one()
        )

        statusy = (
            session.execute(
                text(
                    """
                SELECT coalesce(plan_status, '-') AS status, count(*) AS ile
                FROM listing_enrichment GROUP BY 1 ORDER BY 2 DESC
                """
                )
            )
            .mappings()
            .all()
        )

        do_zrobienia = session.execute(
            text(
                """
                SELECT count(*) FROM listings l
                LEFT JOIN listing_enrichment le ON le.listing_id = l.id
                WHERE l.geom IS NOT NULL AND l.is_active AND le.listing_id IS NULL
                """
            )
        ).scalar_one()

    if not podsumowanie["wzbogacone"]:
        console.print("[yellow]nic jeszcze nie wzbogacono[/yellow]")
        return

    table = Table(title="Stan wzbogacania")
    table.add_column("miara")
    table.add_column("wartosc", justify="right")
    table.add_row("wzbogacone oferty", str(podsumowanie["wzbogacone"]))
    table.add_row("czekaja w kolejce", str(do_zrobienia))
    table.add_row("sredni coverage", f"{float(podsumowanie['sredni_coverage'] or 0):.0%}")
    udzial = podsumowanie["nad_progiem"] / podsumowanie["wzbogacone"]
    table.add_row(
        "coverage >= 40% (kryterium fazy 3: ponad 80%)",
        f"{podsumowanie['nad_progiem']} ({udzial:.0%})",
    )
    table.add_row("z pewnym dopasowaniem dzialki", str(podsumowanie["pewna_dzialka"]))
    table.add_row("z policzonym kosztem mediow", str(podsumowanie["z_kosztem_mediow"]))
    table.add_row("w strefie powodziowej", str(podsumowanie["zalewowe"]))
    console.print(table)

    statusy_table = Table(title="Status planistyczny (sekcja 5.3.3)")
    statusy_table.add_column("status")
    statusy_table.add_column("opis")
    statusy_table.add_column("ile", justify="right")
    from grunt.scoring.planning import OPISY

    for row in statusy:
        statusy_table.add_row(row["status"], OPISY.get(row["status"], ""), str(row["ile"]))
    console.print(statusy_table)


@app.command()
def show(listing_id: int = typer.Option(..., help="Identyfikator oferty")) -> None:
    """Pelne wzbogacenie jednej oferty."""
    import json

    with session_scope() as session:
        row = (
            session.execute(
                text(
                    """
                SELECT l.url, l.area_m2, l.price_grosze/100 AS cena_zl, le.*
                FROM listing_enrichment le
                JOIN listings l ON l.id = le.listing_id
                WHERE le.listing_id = :id
                """
                ),
                {"id": listing_id},
            )
            .mappings()
            .one_or_none()
        )

    if row is None:
        console.print(f"[red]brak wzbogacenia dla oferty {listing_id}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[cyan]{row['url']}[/cyan]")
    console.print(f"cena {row['cena_zl']} zl, powierzchnia {row['area_m2']} m2")
    console.print(
        f"coverage {float(row['coverage'] or 0):.0%}, "
        f"zrodla ok: {row['zrodla_ok']}, bledy: {row['zrodla_bledy']}"
    )
    console.print_json(json.dumps(row["features"], ensure_ascii=False, default=str))


if __name__ == "__main__":
    app()
