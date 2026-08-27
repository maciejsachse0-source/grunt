"""Dynamika rynku per gmina (filar 6, sekcja 5.3.6).

uv run python scripts/market.py run                # przeliczenie z transakcji RCN
uv run python scripts/market.py status             # ile obszarow ma dynamike
uv run python scripts/market.py top                # gdzie ceny rosna najszybciej
uv run python scripts/market.py pokaz 2211011      # jedna gmina ze szczegolami
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
from grunt.enrich import market  # noqa: E402

app = typer.Typer(add_completion=False, help="Dynamika cen gruntow per obszar")
console = Console()


@app.command()
def run(okres_lat: int = typer.Option(4, help="Ile lat kalendarzowych wziac pod uwage")) -> None:
    with session_scope() as session:
        wynik = market.run(session, okres_lat=okres_lat)

    obszary = wynik["obszary"]
    console.print(
        f"[green]{wynik['transakcje']}[/green] transakcji od {wynik['od_roku']} roku -> "
        f"{obszary['gmina']} gmin, {obszary['powiat']} powiatow, "
        f"{obszary['wojewodztwo']} wojewodztw"
    )
    if wynik["bez_dynamiki"]:
        console.print(
            f"[yellow]{wynik['bez_dynamiki']} obszarow bez dynamiki[/yellow]: "
            "zaden segment nie ma dwoch lat z wystarczajaca liczba transakcji. "
            "Filar 6 zostanie tam niedostepny, zamiast dostac zmyslona wartosc."
        )


@app.command()
def status() -> None:
    with session_scope() as session:
        stan = market.status(session)
    if not stan["gminy"]:
        console.print("[yellow]brak danych. Uruchom `market run`[/yellow]")
        return
    console.print(
        f"gminy: {stan['gminy']}, powiaty: {stan['powiaty']}, "
        f"wojewodztwa: {stan['wojewodztwa']}\n"
        f"srednia dynamika gmin: {float(stan['srednia_gmin']):+.1%} rocznie\n"
        f"ostatnie przeliczenie: {stan['ostatnie']:%Y-%m-%d %H:%M}"
    )


@app.command()
def top(
    limit: int = typer.Option(15, help="Ile pozycji"),
    poziom: str = typer.Option("gmina", help="gmina | powiat | wojewodztwo"),
    min_obs: int = typer.Option(30, help="Minimum transakcji, zeby ufac liczbie"),
) -> None:
    """Ranking obszarow po srednirocznej zmianie cen."""
    with session_scope() as session:
        wiersze = (
            session.execute(
                text(
                    """
                    SELECT teryt, cagr, n_obs, rok_od, rok_do, segmenty
                    FROM market_dynamics
                    WHERE poziom = :poziom AND n_obs >= :min_obs
                    ORDER BY cagr DESC LIMIT :limit
                    """
                ),
                {"poziom": poziom, "min_obs": min_obs, "limit": limit},
            )
            .mappings()
            .all()
        )

    if not wiersze:
        console.print("[yellow]brak obszarow spelniajacych warunki[/yellow]")
        return

    tabela = Table(title=f"Dynamika cen, poziom {poziom} (min. {min_obs} transakcji)")
    for kolumna in ("TERYT", "rocznie", "transakcje", "okres", "segmenty"):
        tabela.add_column(kolumna, justify="right" if kolumna != "segmenty" else "left")
    for row in wiersze:
        segmenty = ", ".join(f"{k}: {v:+.0%}" for k, v in sorted((row["segmenty"] or {}).items()))
        tabela.add_row(
            row["teryt"],
            f"{float(row['cagr']):+.1%}",
            str(row["n_obs"]),
            f"{row['rok_od']}-{row['rok_do']}",
            segmenty[:60],
        )
    console.print(tabela)


@app.command()
def pokaz(teryt: str = typer.Argument(..., help="TERYT gminy, np. 2211011")) -> None:
    """Dynamika dla jednej gminy razem z tym, co wnosi shrinkage."""
    gmina = teryt if len(teryt) >= 7 else None
    powiat = teryt[:4]
    wojewodztwo = teryt[:2]

    with session_scope() as session:
        wynik = market.dla_terytu(session, gmina=gmina, powiat=powiat, wojewodztwo=wojewodztwo)

    if wynik is None:
        console.print(f"[yellow]brak dynamiki dla {teryt}[/yellow]")
        return

    console.print(
        f"dynamika: [green]{wynik.cagr:+.1%}[/green] rocznie, okres {wynik.rok_od}-{wynik.rok_do}\n"
        f"najlokalniejsze zrodlo: {wynik.poziom} ({wynik.n_obs} transakcji)\n"
        f"udzial poziomow po shrinkage'u: {wynik.wagi_poziomow}"
    )
    for segment, zmiana in sorted(wynik.segmenty.items()):
        console.print(f"  {segment}: {zmiana:+.1%}")


if __name__ == "__main__":
    app()
