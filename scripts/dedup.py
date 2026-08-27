"""Deduplikacja cross-portal (faza 5, sekcja 4.3 dokumentu).

uv run python scripts/dedup.py run                # przeliczenie par i klastrow
uv run python scripts/dedup.py run --dry-run      # bez zapisu do bazy
uv run python scripts/dedup.py status             # stan bez przeliczania
uv run python scripts/dedup.py klastry            # ta sama dzialka, rozne ceny
uv run python scripts/dedup.py pary --min 0.5     # material do recznej oceny
uv run python scripts/dedup.py oznacz 12 34 --tak # werdykt czlowieka dla pary
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
from grunt.dedup import pipeline  # noqa: E402

app = typer.Typer(add_completion=False, help="Deduplikacja ofert miedzy portalami")
console = Console()


@app.command()
def run(dry_run: bool = typer.Option(False, "--dry-run", help="Policz, ale nie zapisuj")) -> None:
    with session_scope() as session:
        wynik = pipeline.run(session, zapisz=not dry_run)

    console.print(
        f"[green]{wynik['oferty']}[/green] ofert, "
        f"[green]{wynik['pary']}[/green] par nad progiem "
        f"({wynik['pary_w_klastrze']} sklejajacych, "
        f"{wynik['pary_do_przejrzenia']} do przejrzenia), "
        f"[green]{wynik['klastry']}[/green] klastrow, "
        f"duplikaty {wynik['duplikaty_proc']}%"
    )
    if wynik["etapy"]:
        etapy = ", ".join(f"{etap}: {ile}" for etap, ile in sorted(wynik["etapy"].items()))
        console.print(f"rozstrzygniete na etapie -> {etapy}")
    if dry_run:
        console.print("[yellow]--dry-run: nic nie zapisano[/yellow]")

    for klaster in wynik["klastry_szczegoly"][:10]:
        rozrzut = klaster.rozrzut_cen
        console.print(
            f"  klaster {klaster.cluster_id}: {list(klaster.czlonkowie)} "
            f"({', '.join(klaster.portale)}), kanoniczna {klaster.kanoniczna}"
            + (f", rozrzut cen {rozrzut:.0%}" if rozrzut else "")
        )


@app.command()
def status() -> None:
    with session_scope() as session:
        stan = pipeline.status(session)
    console.print(
        f"aktywne oferty: {stan['oferty']}\n"
        f"w klastrach: {stan['w_klastrach']} w {stan['klastry']} grupach "
        f"(duplikaty {stan['duplikaty_proc']}%)\n"
        f"pary w tabeli: {stan['pary']}, ocenione recznie: {stan['oznakowane']}"
    )
    if stan["oznakowane"] < 20:
        console.print(
            "[yellow]zbior oznakowany jest za maly, zeby stroic progi. "
            "Sekcja 4.3 mowi o 200 parach: uzyj `dedup pary` i `dedup oznacz`.[/yellow]"
        )


@app.command()
def klastry(limit: int = typer.Option(20, help="Ile klastrow pokazac")) -> None:
    with session_scope() as session:
        wiersze = pipeline.klastry_z_bazy(session, limit=limit)

    if not wiersze:
        console.print("[yellow]brak klastrow. Uruchom `dedup run`[/yellow]")
        return

    tabela = Table(title="Klastry duplikatow")
    for kolumna in ("klaster", "ofert", "portale", "cena min", "cena max", "rozrzut", "pow."):
        tabela.add_column(kolumna)
    for row in wiersze:
        cena_min, cena_max = row["cena_min_zl"], row["cena_max_zl"]
        rozrzut = (
            f"{(cena_max - cena_min) / cena_min:.0%}" if cena_min and cena_max and cena_min else "-"
        )
        tabela.add_row(
            str(row["cluster_id"]),
            str(row["oferty"]),
            ", ".join(row["portale"]),
            f"{cena_min:,}".replace(",", " ") if cena_min else "-",
            f"{cena_max:,}".replace(",", " ") if cena_max else "-",
            rozrzut,
            f"{row['area_min']}-{row['area_max']} m2" if row["area_min"] else "-",
        )
    console.print(tabela)


@app.command()
def pary(
    minimum: float = typer.Option(0.5, "--min", help="Prog pewnosci"),
    limit: int = typer.Option(30, help="Ile par pokazac"),
    tylko_nieocenione: bool = typer.Option(True, help="Pomin pary z werdyktem czlowieka"),
) -> None:
    """Pary do recznej oceny. To z nich powstaje zbior testowy z sekcji 4.3."""
    # Warunek jest stalym literalem wybieranym przez flage, nie wejsciem uzytkownika.
    warunek = "AND d.potwierdzone IS NULL" if tylko_nieocenione else ""
    zapytanie = f"""
        SELECT d.listing_a, d.listing_b, d.pewnosc, d.etap, d.w_klastrze, d.powody,
               a.url AS url_a, b.url AS url_b,
               a.portal::text AS portal_a, b.portal::text AS portal_b
        FROM listing_duplicates d
        JOIN listings a ON a.id = d.listing_a
        JOIN listings b ON b.id = d.listing_b
        WHERE d.pewnosc >= :minimum {warunek}
        ORDER BY d.pewnosc DESC, d.listing_a
        LIMIT :limit
    """
    with session_scope() as session:
        wiersze = (
            session.execute(text(zapytanie), {"minimum": minimum, "limit": limit}).mappings().all()
        )

    if not wiersze:
        console.print("[yellow]brak par nad progiem[/yellow]")
        return

    for row in wiersze:
        znacznik = "[green]klaster[/green]" if row["w_klastrze"] else "[yellow]podejrzenie[/yellow]"
        console.print(
            f"\n{znacznik} {row['listing_a']} + {row['listing_b']} "
            f"pewnosc {float(row['pewnosc']):.2f}, etap {row['etap']}"
        )
        console.print(f"  {row['portal_a']}: {row['url_a']}")
        console.print(f"  {row['portal_b']}: {row['url_b']}")
        for powod in row["powody"] or []:
            console.print(f"    - {powod}")


@app.command()
def oznacz(
    listing_a: int = typer.Argument(..., help="Mniejszy identyfikator oferty"),
    listing_b: int = typer.Argument(..., help="Wiekszy identyfikator oferty"),
    tak: bool = typer.Option(False, "--tak/--nie", help="Czy to faktycznie duplikat"),
) -> None:
    """Werdykt czlowieka dla pary. Przebiegi go nie nadpisuja."""
    a, b = min(listing_a, listing_b), max(listing_a, listing_b)
    with session_scope() as session:
        zmienione = session.execute(
            text(
                """
                UPDATE listing_duplicates SET potwierdzone = :tak
                WHERE listing_a = :a AND listing_b = :b
                """
            ),
            {"tak": tak, "a": a, "b": b},
        ).rowcount
    if zmienione:
        console.print(f"[green]zapisano[/green] pare {a}+{b} jako {'duplikat' if tak else 'rozne'}")
    else:
        console.print(f"[red]nie ma pary {a}+{b} w tabeli[/red]")


@app.command()
def precyzja() -> None:
    """Precyzja progow na zbiorze oznakowanym recznie."""
    with session_scope() as session:
        row = (
            session.execute(
                text(
                    """
                    SELECT
                        count(*) FILTER (WHERE w_klastrze AND potwierdzone) AS tp,
                        count(*) FILTER (WHERE w_klastrze AND NOT potwierdzone) AS fp,
                        count(*) FILTER (WHERE NOT w_klastrze AND potwierdzone) AS fn,
                        count(*) FILTER (WHERE NOT w_klastrze AND NOT potwierdzone) AS tn
                    FROM listing_duplicates
                    WHERE potwierdzone IS NOT NULL
                    """
                )
            )
            .mappings()
            .one()
        )

    tp, fp, fn, tn = (int(row[k]) for k in ("tp", "fp", "fn", "tn"))
    if tp + fp + fn + tn == 0:
        console.print("[yellow]zbior oznakowany jest pusty. Uzyj `dedup oznacz`[/yellow]")
        return
    console.print(f"oznakowane pary: {tp + fp + fn + tn} (TP {tp}, FP {fp}, FN {fn}, TN {tn})")
    if tp + fp:
        console.print(f"precyzja: {tp / (tp + fp):.1%}")
    if tp + fn:
        console.print(f"czulosc: {tp / (tp + fn):.1%}")


if __name__ == "__main__":
    app()
