"""Geometrie dzialek dla mapy (obrysy).

    uv run python scripts/parcels.py status
    uv run python scripts/parcels.py backfill --limit 200

Wzbogacanie od 25.08.2026 zapisuje geometrie dopasowanej dzialki samo
(enrich/parcel_store.py). Ten skrypt jest dla ofert wzbogaconych WCZESNIEJ:
maja w listing_enrichment identyfikator dzialki, ale geometria zostala
wyrzucona, bo nie bylo jej gdzie zapisac.

Geometrie dociagamy z ULDK po identyfikatorze, a nie ponownym pelnym
wzbogacaniem: to jedno zapytanie zamiast dwudziestu i nie rusza dopasowania,
ktore juz zostalo policzone. Odpowiedzi ULDK wpadaja do uldk_cache, wiec
powtorny przebieg nie generuje ruchu.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grunt.db import session_scope  # noqa: E402
from grunt.enrich import parcel_store  # noqa: E402
from grunt.sources import uldk  # noqa: E402

app = typer.Typer(add_completion=False, help="Obrysy dzialek dla mapy")
console = Console()

DO_UZUPELNIENIA = text(
    """
    SELECT l.id AS listing_id, le.parcel_uldk_id, le.parcel_match, le.parcel_area_m2
    FROM listings l
    JOIN listing_enrichment le ON le.listing_id = l.id
    WHERE l.parcel_id IS NULL
      AND le.parcel_uldk_id IS NOT NULL
    ORDER BY l.first_seen_at DESC
    LIMIT :limit
    """
)


@app.command()
def backfill(
    limit: int = typer.Option(200, help="Ile ofert w tym przebiegu"),
    delay: float = typer.Option(0.5, help="Odstep miedzy zapytaniami do ULDK"),
) -> None:
    with session_scope() as session:
        rows = session.execute(DO_UZUPELNIENIA, {"limit": limit}).mappings().all()
        console.print(f"[cyan]obrysy[/cyan] do uzupelnienia: {len(rows)}")

        klient = uldk.UldkClient(session, delay=delay)
        uzupelnione = bez_geometrii = bledy = 0

        for row in rows:
            uldk_id = row["parcel_uldk_id"]
            # Dzialke mogla juz zapisac inna oferta z tego samego klastra.
            parcel_id = session.execute(
                text("SELECT id FROM parcels WHERE uldk_id = :uldk_id"),
                {"uldk_id": uldk_id},
            ).scalar_one_or_none()

            if parcel_id is None:
                try:
                    dzialka = klient.by_id(uldk_id)
                except uldk.UldkError as exc:
                    console.print(f"  [red]blad[/red] {uldk_id}: {exc}")
                    bledy += 1
                    continue
                if dzialka is None or not dzialka.geom_wkt:
                    bez_geometrii += 1
                    continue
                parcel_id = parcel_store.upsert(
                    session,
                    uldk_id=uldk_id,
                    geom_wkt=dzialka.geom_wkt,
                    area_ewid_m2=row["parcel_area_m2"],
                    teryt_gmina=dzialka.teryt_gmina,
                    teryt_obreb=dzialka.teryt_obreb,
                )
                if parcel_id is None:
                    bez_geometrii += 1
                    continue

            parcel_store.link(session, listing_id=row["listing_id"], parcel_id=parcel_id)
            uzupelnione += 1
            console.print(f"  {row['listing_id']} -> {uldk_id} ({row['parcel_match']})")

    console.print(
        f"[green]gotowe[/green] uzupelnione={uzupelnione} "
        f"bez_geometrii={bez_geometrii} bledy={bledy}"
    )


@app.command()
def status() -> None:
    """Ile ofert ma obrys, w rozbiciu na pewnosc dopasowania."""
    with session_scope() as session:
        wiersze = (
            session.execute(
                text(
                    """
                SELECT COALESCE(le.parcel_match, 'brak dopasowania') AS pewnosc,
                       count(*) AS ofert,
                       count(l.parcel_id) AS z_obrysem
                FROM listings l
                JOIN listing_enrichment le ON le.listing_id = l.id
                GROUP BY 1
                ORDER BY 1
                """
                )
            )
            .mappings()
            .all()
        )
        dzialek = session.execute(text("SELECT count(*) FROM parcels")).scalar_one()

    for w in wiersze:
        console.print(f"  {w['pewnosc']:<18} ofert={w['ofert']:<5} z obrysem={w['z_obrysem']}")
    console.print(f"[cyan]dzialek w bazie:[/cyan] {dzialek}")


if __name__ == "__main__":
    app()
