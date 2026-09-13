"""Harmonogram i kolejka zadan (faza 5).

uv run python scripts/jobs.py worker                 # petla, dziala do Ctrl+C
uv run python scripts/jobs.py tick                   # jeden obrot i wyjscie
uv run python scripts/jobs.py harmonogram            # co i jak czesto
uv run python scripts/jobs.py enqueue enrich --payload '{"limit": 5}'
uv run python scripts/jobs.py lista --status failed
uv run python scripts/jobs.py ponow 12               # zepsute zadanie jeszcze raz
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grunt.db import session_scope  # noqa: E402
from grunt.jobs import handlers, queue, scheduler  # noqa: E402
from grunt.jobs import worker as worker_modul  # noqa: E402

app = typer.Typer(add_completion=False, help="Harmonogram i kolejka zadan")
console = Console()


def _pokaz_wykonane(wynik: dict[str, object]) -> None:
    if "zaplanowane" in wynik:
        console.print(f"[cyan]zaplanowane:[/cyan] {', '.join(wynik['zaplanowane'])}")  # type: ignore[arg-type]
        return
    kolor = "green" if wynik["status"] == "done" else "red"
    console.print(
        f"[{kolor}]{wynik['status']}[/{kolor}] {wynik['kind']} "
        f"(zadanie {wynik['id']}, {wynik['czas_s']} s)"
    )
    if wynik.get("blad"):
        console.print(f"  [red]{wynik['blad']}[/red]")
    elif wynik.get("wynik"):
        console.print(f"  {json.dumps(wynik['wynik'], ensure_ascii=False)[:300]}")


@app.command()
def worker(
    odstep: float = typer.Option(30.0, help="Sekundy snu, gdy kolejka jest pusta"),
    max_obrotow: int | None = typer.Option(None, help="Zakoncz po tylu obrotach"),
) -> None:
    """Petla workera. Bez tego nic nie uruchamia sie samo."""
    console.print(
        "[cyan]worker wystartowal[/cyan] (Ctrl+C konczy). "
        f"Rodzaje zadan: {', '.join(handlers.HANDLERY)}"
    )
    podsumowanie = worker_modul.pracuj(
        odstep_s=odstep, max_obrotow=max_obrotow, progress=_pokaz_wykonane
    )
    console.print(
        f"\nobrotow: {podsumowanie['obroty']}, wykonanych zadan: {podsumowanie['wykonane']}, "
        f"bledow: {podsumowanie['bledy']}"
        + (" [yellow](przerwane)[/yellow]" if podsumowanie.get("przerwane") else "")
    )


@app.command()
def tick() -> None:
    """Jeden obrot petli: harmonogram plus jedno zadanie."""
    wynik = worker_modul.tick()
    if wynik["odzyskane"]:
        console.print(f"[yellow]odzyskane zawieszone zadania: {wynik['odzyskane']}[/yellow]")
    if wynik["zaplanowane"]:
        console.print(f"[cyan]zaplanowane:[/cyan] {', '.join(wynik['zaplanowane'])}")
    if wynik["wykonane"]:
        _pokaz_wykonane(wynik["wykonane"])
    else:
        console.print("kolejka pusta, nic do zrobienia")


@app.command()
def harmonogram() -> None:
    """Co uruchamia sie samo i kiedy bylo ostatnio."""
    with session_scope() as session:
        ostatnie = queue.ostatnie_udane(session)
        czekaja = queue.w_kolejce(session)

    tabela = Table(title="Harmonogram")
    for kolumna in ("zadanie", "co ile", "ostatnie udane", "w kolejce", "co robi"):
        tabela.add_column(kolumna)
    for wpis in scheduler.opis_harmonogramu():
        kind = str(wpis["kind"])
        znacznik = ostatnie.get(kind)
        tabela.add_row(
            kind,
            f"{wpis['co_ile_godzin']:.0f} h",
            znacznik.strftime("%Y-%m-%d %H:%M") if znacznik else "-",
            "tak" if kind in czekaja else "-",
            str(wpis["co"]),
        )
    console.print(tabela)


@app.command()
def enqueue(
    kind: str = typer.Argument(..., help=f"Rodzaj zadania: {', '.join(handlers.HANDLERY)}"),
    payload: str = typer.Option("{}", help="Parametry zadania jako JSON"),
) -> None:
    if kind not in handlers.HANDLERY:
        raise typer.BadParameter(f"znane rodzaje: {', '.join(handlers.HANDLERY)}")
    dane = json.loads(payload)
    with session_scope() as session:
        job_id = queue.enqueue(session, kind, dane)
    console.print(f"[green]dodane[/green] zadanie {job_id}: {kind} {dane or ''}")


@app.command()
def lista(
    limit: int = typer.Option(20, help="Ile pozycji"),
    status: str | None = typer.Option(None, help="pending | running | done | failed"),
) -> None:
    if status and status not in queue.STATUSY:
        raise typer.BadParameter(f"status musi byc jednym z: {', '.join(queue.STATUSY)}")
    with session_scope() as session:
        wiersze = queue.lista(session, limit=limit, status=status)

    if not wiersze:
        console.print("[yellow]kolejka jest pusta[/yellow]")
        return

    tabela = Table(title="Zadania")
    for kolumna in ("id", "rodzaj", "status", "prob", "kiedy", "wynik / blad"):
        tabela.add_column(kolumna)
    for row in wiersze:
        kiedy = row["finished_at"] or row["run_after"]
        opis = row["last_error"] or (
            json.dumps(row["wynik"], ensure_ascii=False) if row["wynik"] else ""
        )
        tabela.add_row(
            str(row["id"]),
            row["kind"],
            row["status"],
            str(row["attempts"]),
            kiedy.strftime("%Y-%m-%d %H:%M") if kiedy else "-",
            opis[:70],
        )
    console.print(tabela)


@app.command()
def ponow(job_id: int = typer.Argument(..., help="Identyfikator zadania")) -> None:
    """Zepsute zadanie wraca do kolejki z wyzerowanymi probami."""
    with session_scope() as session:
        zmienione = session.execute(
            text(
                """
                UPDATE jobs SET status = 'pending', attempts = 0, run_after = now(),
                                locked_at = NULL, finished_at = NULL
                WHERE id = :id
                """
            ),
            {"id": job_id},
        ).rowcount
    if zmienione:
        console.print(f"[green]zadanie {job_id} wraca do kolejki[/green]")
    else:
        console.print(f"[red]nie ma zadania {job_id}[/red]")


@app.command()
def sprzataj(dni: int = typer.Option(30, help="Usun historie starsza niz tyle dni")) -> None:
    with session_scope() as session:
        usuniete = queue.sprzataj(session, starsze_niz_dni=dni)
    console.print(f"usuniete zakonczone zadania: {usuniete}")


if __name__ == "__main__":
    app()
