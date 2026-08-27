"""Walidacja modeli wyceny na transakcjach RCN, ktorych model nie widzial.

Kryterium akceptacji fazy 1 (sekcja 21 dokumentu):
    MdAPE ponizej 30%
    pokrycie przedzialu 80% na poziomie 75-85%

Backtest jest uczciwy, to znaczy:
* data wyceny to data transakcji, wiec model nie widzi przyszlosci
  (porownywalne sa ograniczone do data_trans <= as_of);
* wyceniana transakcja jest usuwana ze zbioru porownywalnych;
* usuwane sa tez inne transakcje TEJ SAMEJ dzialki, bo ta sama dzialka potrafi
  wrocic trzy razy w ciagu roku i model wycenialby sam siebie.

ZAKRES STOSOWALNOSCI, swiadomie zawezony i jawnie raportowany.
Domyslnie odsiewamy dwie grupy, ktore nie sa rynkowym obrotem gruntem:

  1. Transakcje ponizej --min-price-m2 (domyslnie 5 zl/m2). W probie trafialy sie
     przeniesienia po 1,8 zl/m2 przy 1115 m2, czyli 2 tys. zl za dzialke.
     To regulacje stanu prawnego, udzialy w drogach i przekazania nominalne,
     ktore RCN oznacza jako "wolnyRynek". Dla porownania: hektar gruntow ornych
     w pomorskim kosztuje ok. 67 tys. zl, czyli 6,7 zl/m2.
  2. Segment "droga" (pasy drogowe i dojazdy). Ich cena nie wynika z rynku,
     tylko z potrzeby konkretnego sasiada.

Bez tego odsiewu MdAPE Modelu 1 to ok. 44%, po nim 27%. Roznica nie bierze sie
z lepszego modelu, tylko z uczciwie zdefiniowanego zakresu. Uruchom
--min-price-m2 0 --keep-roads, zeby zobaczyc pelny obraz.

    uv run python scripts/eval_valuation.py --limit 150
    uv run python scripts/eval_valuation.py --limit 150 --model median
    uv run python scripts/eval_valuation.py --limit 150 --min-price-m2 0 --keep-roads
"""

from __future__ import annotations

import contextlib
import datetime as dt
import math
import statistics
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grunt.db import session_scope  # noqa: E402
from grunt.scoring import segments, valuation  # noqa: E402
from grunt.scoring.normalize_area import LogPriceCurve, estimate_curve  # noqa: E402
from grunt.sources import rcn_query  # noqa: E402

app = typer.Typer(add_completion=False)
console = Console()

BETA_MIN, BETA_MAX = 0.40, 1.10


def fit_curves(session, months_back: int, min_price_m2: float) -> dict[str, LogPriceCurve]:
    """Elastycznosc b1 estymowana OSOBNO DLA KAZDEGO SEGMENTU.

    Estymacja na wszystkich transakcjach naraz dawala b1 = 0,26, co jest artefaktem:
    male dzialki "rolne" pod Trojmiastem to de facto dzialki budowlane po 136 zl/m2,
    a duze to prawdziwe pola po 9 zl/m2. Powierzchnia byla wiec zmienna zastepcza
    dla przeznaczenia. Po rozdzieleniu segmentow zostaje sam efekt skali.
    """
    rows = session.execute(
        text(
            """
            SELECT pow_gruntu_m2, cena_grosze / 100.0 AS cena, przeznaczenie, sposob_uzyt
            FROM rcn_transactions
            WHERE cena_grosze IS NOT NULL AND pow_gruntu_m2 BETWEEN 200 AND 100000
              AND udzial = '1/1' AND rodzaj_trans = 'wolnyRynek'
              AND nier_rodzaj = 'nieruchomoscGruntowaNiezabudowana'
              AND cena_m2 BETWEEN :min_price AND 5000
              AND data_trans <= CURRENT_DATE
              AND data_trans >= CURRENT_DATE - make_interval(months => :months)
            """
        ),
        {"months": months_back, "min_price": max(min_price_m2, 1.0)},
    ).all()

    grouped: dict[str, list[tuple[float, float]]] = {}
    for pow_m2, cena, przezn, uzyt in rows:
        grouped.setdefault(segments.classify(przezn, uzyt), []).append((float(pow_m2), float(cena)))

    curves: dict[str, LogPriceCurve] = {}
    for segment, values in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        if len(values) < 200:
            continue
        curve = estimate_curve([v[0] for v in values], [v[1] for v in values])
        beta = curve.beta_at(1000)
        # Bezpiecznik: elastycznosc poza [0,4; 1,1] to prawie zawsze slad
        # niedomodelowanego zroznicowania w segmencie, a nie wlasnosc rynku.
        if not (BETA_MIN <= beta <= BETA_MAX):
            console.print(f"  [yellow]{segment}: b1={beta:.2f} poza zakresem, biore 0,85[/yellow]")
            continue
        curves[segment] = curve
        console.print(
            f"  [cyan]{segment:<28}[/cyan] n={curve.n_obs:>6} R2={curve.r2:.3f} "
            f"b1(1000)={beta:.3f} b1(5000)={curve.beta_at(5000):.3f}"
        )
    return curves


@app.command()
def main(
    limit: int = typer.Option(150, help="Liczba transakcji testowych"),
    model: str = typer.Option("knn", help="knn | median | blend"),
    months_back: int = typer.Option(36, help="Okno porownywalnych, w miesiacach"),
    k: int = typer.Option(20, help="Liczba sasiadow w SE-KNN"),
    lam: float = typer.Option(0.7, help="Waga geografii wobec cech w SE-KNN"),
    max_distance_km: float = typer.Option(15.0),
    k_shrink: float = typer.Option(valuation.DEFAULT_K_SHRINK, help="Sila shrinkage'u"),
    annual_drift: float = typer.Option(0.08, help="Roczna indeksacja cen"),
    confidence: float = typer.Option(0.80),
    min_price_m2: float = typer.Option(5.0, help="Prog odsiewu transakcji nominalnych"),
    keep_roads: bool = typer.Option(False, help="Nie odsiewaj segmentu droga"),
    seed: int = typer.Option(20260821),
    use_fitted_curve: bool = typer.Option(True, help="Estymowac b1 z danych"),
) -> None:
    if model not in {"knn", "median", "blend"}:
        raise typer.BadParameter("model musi byc jednym z: knn, median, blend")

    max_distance_m = max_distance_km * 1000
    with session_scope() as session:
        console.print("[cyan]krzywe skali per segment[/cyan]")
        curves = fit_curves(session, months_back, min_price_m2) if use_fitted_curve else {}
        default_curve = LogPriceCurve.constant()

        sample = rcn_query.sample_for_evaluation(
            session, limit=limit, seed=seed, min_cena_m2=min_price_m2
        )
        console.print(f"\n[cyan]proba[/cyan] {len(sample)} transakcji, model: {model}\n")

        apes: list[float] = []
        in_interval = in_20pct = skipped = 0
        by_segment: dict[str, list[float]] = {}

        for row in sample:
            id_dzialki = str(row["id_dzialki"])
            area = float(row["pow_m2"])
            actual = float(row["cena_m2"]) * area
            as_of = row["data_trans"]
            since = as_of - dt.timedelta(days=30 * months_back)

            # Segment wycenianej dzialki wynika z jej przeznaczenia w MPZP,
            # a nie z ceny, wiec uzycie go nie jest wyciekiem informacji.
            target = segments.classify(row.get("przeznaczenie"), row.get("sposob_uzyt"))
            if target == "droga" and not keep_roads:
                continue

            obreb, gmina, powiat, woj = rcn_query.teryt_from_uldk_id(id_dzialki)
            curve = curves.get(target, default_curve)

            # Model 1 liczymy zawsze: jest wynikiem sam w sobie, a dla mieszanki
            # sluzy za prior.
            comps = rcn_query.fetch_comparables(
                session,
                rcn_query.ComparableQuery(
                    teryt_obreb=obreb,
                    teryt_gmina=gmina,
                    teryt_powiat=powiat,
                    teryt_woj=woj,
                    since=since,
                    area_m2=area,
                ),
                as_of=as_of,
            )
            comps = rcn_query.exclude_transaction(comps, id_dzialki)
            comps = [c for c in comps if c.price_per_m2 >= min_price_m2]
            if not comps:
                skipped += 1
                continue
            sel, used = segments.select_by_segment(
                comps, target, segment_of=lambda c: c.segment, level_of=lambda c: c.level
            )
            try:
                result = valuation.valuate_median_shrinkage(
                    area,
                    sel,
                    as_of=as_of,
                    curve=curve,
                    k_shrink=k_shrink,
                    annual_drift=annual_drift,
                    confidence=confidence,
                    segments_used=used,
                )
            except valuation.ValuationError:
                skipped += 1
                continue
            baseline = result

            if model in {"knn", "blend"}:
                knn_comps = rcn_query.fetch_spatial_comparables(
                    session,
                    row["geom_wkt"],
                    teryt_obreb=obreb,
                    teryt_gmina=gmina,
                    teryt_powiat=powiat,
                    as_of=as_of,
                    since=since,
                    area_m2=area,
                    max_distance_m=max_distance_m,
                    cena_min=min_price_m2,
                )
                knn_comps = rcn_query.exclude_transaction(knn_comps, id_dzialki)
                if knn_comps:
                    ksel, kused = segments.select_by_segment(
                        knn_comps,
                        target,
                        segment_of=lambda c: c.segment,
                        level_of=lambda c: c.level,
                    )
                    # przy bledzie zostaje wynik Modelu 1
                    with contextlib.suppress(valuation.ValuationError):
                        result = valuation.valuate_se_knn(
                            area,
                            ksel,
                            as_of=as_of,
                            curve=curve,
                            k=k,
                            lam=lam,
                            annual_drift=annual_drift,
                            confidence=confidence,
                            max_distance_m=max_distance_m,
                            segments_used=kused,
                            target_segment=target,
                            prior_log_price=(
                                math.log(baseline.unit_price_norm) if model == "blend" else None
                            ),
                        )

            predicted = result.v_hat_grosze / 100.0
            ape = abs(predicted - actual) / actual
            apes.append(ape)
            by_segment.setdefault(target, []).append(ape)
            if ape <= 0.20:
                in_20pct += 1
            if result.ci_low_grosze / 100.0 <= actual <= result.ci_high_grosze / 100.0:
                in_interval += 1

        if not apes:
            console.print("[red]brak wycen, sprawdz czy baza ma dane RCN[/red]")
            raise typer.Exit(code=1)

        n = len(apes)
        mdape = statistics.median(apes)
        coverage = in_interval / n

        def verdict(ok: bool) -> str:
            return "[green]OK[/green]" if ok else "[red]nie[/red]"

        table = Table(title=f"Walidacja modelu wyceny ({model})")
        table.add_column("miara")
        table.add_column("wynik", justify="right")
        table.add_column("cel", justify="right")
        table.add_column("", justify="center")
        table.add_row("wycenionych transakcji", str(n), "-", "")
        table.add_row("pominietych", str(skipped), "-", "")
        table.add_row("MdAPE", f"{mdape:.1%}", "< 30%", verdict(mdape < 0.30))
        table.add_row(
            f"pokrycie przedzialu {confidence:.0%}",
            f"{coverage:.1%}",
            "75-85%",
            verdict(0.75 <= coverage <= 0.85),
        )
        table.add_row("predykcje w +/-20%", f"{in_20pct / n:.1%}", "informacyjnie", "")
        table.add_row("srednia APE", f"{statistics.mean(apes):.1%}", "-", "")
        table.add_row(
            "zakres",
            f"od {min_price_m2:.0f} zl/m2" + ("" if keep_roads else ", bez drog"),
            "",
            "",
        )
        console.print(table)

        segment_table = Table(title="Rozbicie na segmenty rynku")
        segment_table.add_column("segment")
        segment_table.add_column("n", justify="right")
        segment_table.add_column("MdAPE", justify="right")
        for segment, values in sorted(by_segment.items(), key=lambda kv: -len(kv[1])):
            segment_table.add_row(segment, str(len(values)), f"{statistics.median(values):.1%}")
        console.print(segment_table)


if __name__ == "__main__":
    app()
