"""Kalibracja i walidacja bez etykiet (faza 6, sekcja 5.6 dokumentu).

uv run python scripts/calibrate.py run             # wszystkie pomiary i zapis
uv run python scripts/calibrate.py spread          # oferta vs wycena, per segment
uv run python scripts/calibrate.py pary            # wlasciwy pomiar: oferta -> RCN
uv run python scripts/calibrate.py beta1           # elastycznosc per segment
uv run python scripts/calibrate.py wagi            # stabilnosc top-100 przy +/-30%
uv run python scripts/calibrate.py wrazliwosc      # +/-20% na jednym filarze, top-10
uv run python scripts/calibrate.py dyskryminacja   # czy scoring cokolwiek rozroznia
uv run python scripts/calibrate.py historia        # kolejne pomiary w czasie
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
from grunt.enrich import calibrate  # noqa: E402

app = typer.Typer(add_completion=False, help="Kalibracja modelu na wlasnych danych")
console = Console()


@app.command()
def run(
    limit: int = typer.Option(500, help="Ile ofert wycenic do szacunku spreadu"),
    profil: str = typer.Option("detaliczny", help="detaliczny albo deweloper"),
) -> None:
    """Wszystkie cztery pomiary sekcji 5.6 i zapis do tabeli calibrations."""
    if profil not in ("detaliczny", "deweloper"):
        raise typer.BadParameter("profil musi byc detaliczny albo deweloper")

    with session_scope() as session:
        wynik = calibrate.run(session, limit=limit, profil=profil)  # type: ignore[arg-type]

    if wynik["spread_pary"]:
        console.print(f"[green]spread z par:[/green] {wynik['spread_pary']}")
    else:
        console.print(
            "[yellow]brak par oferta-transakcja[/yellow] - wlasciwy pomiar spreadu "
            "bedzie mozliwy dopiero, gdy oferta zniknie z portalu, a jej dzialka "
            "pojawi sie w RCN (0-6 miesiecy)"
        )

    for segment, dane in (wynik["spread_oferty"] or {}).items():
        console.print(
            f"spread (szacunek zastepczy) {segment}: mediana {dane['mediana']:+.1%}, "
            f"kwartyle {dane['p25']:+.1%} / {dane['p75']:+.1%}, n={dane['n']}"
        )

    if wynik["beta1"]:
        console.print(f"[cyan]beta1 per segment:[/cyan] {wynik['beta1']}")
    if wynik["wagi"].get("pokrycie_mediana") is not None:
        console.print(
            f"[cyan]stabilnosc wag:[/cyan] top-{wynik['wagi']['top_n']} pokrycie "
            f"{wynik['wagi']['pokrycie_mediana']:.0%} (min {wynik['wagi']['pokrycie_min']:.0%}), "
            f"rho {wynik['wagi']['rho_mediana']:.3f}"
        )
    if "pomiary" in wynik["wrazliwosc"]:
        w = wynik["wrazliwosc"]
        console.print(
            f"[cyan]wrazliwosc na wage filaru:[/cyan] top-{w['top_n']} przesuwa sie najwyzej "
            f"o {w['max_przesuniecie']} pozycji przy +/-{w['skala']:.0%} (prog {w['prog']}), "
            f"kryterium {'spelnione' if w['spelnione'] else 'NIESPELNIONE'}"
            + ("" if w["rozstrzygajacy"] else "; pomiar nierozstrzygajacy, patrz `wrazliwosc`")
        )
    if wynik["dyskryminacja"]:
        console.print(f"[cyan]dyskryminacja:[/cyan] {wynik['dyskryminacja']}")


@app.command()
def spread(limit: int = typer.Option(500, help="Ile ofert wycenic")) -> None:
    """Iloraz ceny ofertowej do wyceny modelu, globalnie i per segment."""
    with session_scope() as session:
        spready = calibrate.spread_z_ofert(session, limit=limit)

    if not spready:
        console.print("[yellow]zadnej oferty nie da sie wycenic[/yellow]")
        return

    tabela = Table(title="Spread oferta - wycena transakcyjna (szacunek zastepczy)")
    for kolumna in ("segment", "mediana", "p25", "p75", "MAD", "n", "wiarygodny"):
        tabela.add_column(kolumna, justify="right")
    for segment, wynik in sorted(spready.items()):
        tabela.add_row(
            segment or "(globalny)",
            f"{wynik.mediana:+.1%}",
            f"{wynik.p25:+.1%}",
            f"{wynik.p75:+.1%}",
            f"{wynik.mad:.3f}",
            str(wynik.n),
            "tak" if wynik.wiarygodny else "nie",
        )
    console.print(tabela)
    console.print(
        "\n[yellow]Uwaga:[/yellow] to nie jest spread z sekcji 5.6. Miesza rzeczywista "
        "roznice oferta-transakcja z bledem modelu wyceny. Po jego zastosowaniu mediana "
        "deal score'u siada blisko zera z definicji, wiec deal score znaczy wtedy "
        '"tansza niz typowa oferta", a nie "tansza niz wartosc".'
    )


@app.command()
def pary(
    okno_dni: int = typer.Option(200, help="Okno miedzy pierwszym widzeniem a transakcja"),
) -> None:
    """Wlasciwy pomiar: oferta z portalu, ktorej dzialka pojawila sie potem w RCN."""
    with session_scope() as session:
        znalezione = calibrate.pary_oferta_transakcja(session, okno_dni=okno_dni)
        wynik = calibrate.spread_z_par(session, okno_dni=okno_dni)

    if not znalezione:
        console.print(
            "[yellow]zero par[/yellow]\n"
            "Tak ma byc na tym etapie: RCN publikuje transakcje z opoznieniem, "
            "a oferty zbieramy od niedawna. Ten pomiar zacznie dzialac sam, "
            "gdy w bazie beda oferty starsze niz kilka miesiecy."
        )
        return

    tabela = Table(title="Pary oferta - transakcja")
    for kolumna in ("oferta", "portal", "cena ofertowa", "cena transakcji", "dni", "spread"):
        tabela.add_column(kolumna, justify="right")
    for para in znalezione[:30]:
        cena_of = para["price_grosze"] / 100
        cena_tr = para["cena_grosze"] / 100
        tabela.add_row(
            str(para["listing_id"]),
            para["portal"],
            f"{cena_of:,.0f}".replace(",", " "),
            f"{cena_tr:,.0f}".replace(",", " "),
            str(para["dni_do_transakcji"]),
            f"{cena_of / cena_tr - 1:+.1%}" if cena_tr else "-",
        )
    console.print(tabela)
    if wynik:
        console.print(f"\nmediana spreadu: {wynik.mediana:+.1%} (n={wynik.n})")


@app.command()
def beta1(
    min_obs: int = typer.Option(200, help="Minimum transakcji na segment"),
    wezly: bool = typer.Option(
        False, "--wezly", help="Lamana zamiast stalej elastycznosci (pasma powierzchni)"
    ),
) -> None:
    """Elastycznosc ceny wzgledem powierzchni, osobno w kazdym segmencie rynku."""
    with session_scope() as session:
        krzywe = calibrate.beta1_per_segment(session, min_obs=min_obs, z_wezlami=wezly)

    if not krzywe:
        console.print("[yellow]zaden segment nie ma dosc transakcji[/yellow]")
        return

    # Przy stalej elastycznosci trzy kolumny mialyby te sama liczbe, wiec pokazujemy jedna.
    kolumny = (
        ("segment", "500 m2", "1500 m2", "5000 m2", "R2", "n")
        if wezly
        else ("segment", "b1", "R2", "n")
    )
    tabela = Table(
        title="Elastycznosc b1 (ln cena ~ ln powierzchnia)"
        + (", lamana wedlug pasm powierzchni" if wezly else ", stala")
    )
    for kolumna in kolumny:
        tabela.add_column(kolumna, justify="right", no_wrap=True)
    for segment, krzywa in sorted(krzywe.items(), key=lambda kv: -kv[1].n_obs):
        wiersz = (
            (
                segment,
                f"{krzywa.beta_at(500.0):.3f}",
                f"{krzywa.beta_at(1500.0):.3f}",
                f"{krzywa.beta_at(5000.0):.3f}",
            )
            if wezly
            else (segment, f"{krzywa.slope0:.3f}")
        )
        tabela.add_row(*wiersz, f"{krzywa.r2:.3f}", str(krzywa.n_obs))
    console.print(tabela)
    console.print(
        "\nWartosc oczekiwana z literatury to 0,80-0,90 (sekcja 5.2.3). "
        "Wyraznie nizsza oznacza, ze w segmencie nadal siedzi mieszanka przeznaczen."
    )


@app.command()
def wagi(
    profil: str = typer.Option("detaliczny", help="detaliczny albo deweloper"),
    powtorzenia: int = typer.Option(20, help="Ile perturbacji"),
    skala: float = typer.Option(0.30, help="Zakres perturbacji, np. 0.3 to +/-30%"),
    top_n: int = typer.Option(100, help="Rozmiar sprawdzanej czolowki"),
) -> None:
    """Analiza wrazliwosci: co zostaje z rankingu po perturbacji wag."""
    with session_scope() as session:
        wynik = calibrate.wrazliwosc_wag(
            session,
            profil=profil,  # type: ignore[arg-type]
            powtorzenia=powtorzenia,
            skala=skala,
            top_n=top_n,
        )

    if "pokrycie_mediana" not in wynik:
        console.print(f"[yellow]{wynik.get('powod', 'brak danych')}[/yellow]")
        return

    kontrola = wynik["kontrola_rekonstrukcji"]
    console.print(
        f"ofert w rankingu: {wynik['n']}, czolowka: top-{wynik['top_n']}, "
        f"perturbacji: {wynik['powtorzenia']} po +/-{wynik['skala']:.0%} (seed {wynik['seed']})\n"
        f"pokrycie czolowki: mediana {wynik['pokrycie_mediana']:.0%}, "
        f"najgorsze {wynik['pokrycie_min']:.0%}\n"
        f"korelacja rang: mediana {wynik['rho_mediana']:.3f}, "
        f"najgorsza {wynik['rho_min']:.3f}\n"
        f"kontrola rekonstrukcji: {kontrola['niezgodne']} niezgodnych "
        f"na {kontrola['sprawdzone']} sprawdzonych"
    )
    if not wynik["miarodajny"]:
        brakujace = sorted(set(wynik["filary_wszystkie"]) - set(wynik["filary_dostepne"]))
        console.print(
            "\n[yellow]test nie jest dzis miarodajny:[/yellow] dostepne sa tylko filary "
            f"{', '.join(wynik['filary_dostepne'])}, a brakuje {', '.join(brakujace)}. "
            f"Wzorcow dostepnosci: {wynik['wzorce_dostepnosci']}. Gdy w kazdej ofercie "
            "wypelniony jest ten sam podzbior filarow, wagi renormalizuja sie identycznie "
            "i ranking nie ma jak sie rozjechac."
        )

    if wynik["stabilny"]:
        console.print("[green]ranking stabilny[/green] wzgledem doboru wag")
    else:
        console.print(
            "[red]ranking niestabilny[/red]: wagi decyduja o czolowce bardziej "
            "niz dane. Sekcja 5.6 mowi, ze wtedy scoring nie niesie informacji."
        )


@app.command()
def wrazliwosc(
    profil: str = typer.Option("detaliczny", help="detaliczny albo deweloper"),
    skala: float = typer.Option(0.20, help="O ile zmieniamy wage filaru, np. 0.2 to +/-20%"),
    top_n: int = typer.Option(10, help="Rozmiar sprawdzanej czolowki"),
    prog: int = typer.Option(3, help="Dopuszczalne przesuniecie w pozycjach"),
    zapisz: bool = typer.Option(False, "--zapisz", help="Dopisz pomiar do tabeli calibrations"),
) -> None:
    """Kryterium fazy 6: +/-20% wagi jednego filaru kontra pierwsza dziesiatka."""
    if profil not in ("detaliczny", "deweloper"):
        raise typer.BadParameter("profil musi byc detaliczny albo deweloper")

    with session_scope() as session:
        wynik = calibrate.analiza_wrazliwosci(
            session,
            profil=profil,  # type: ignore[arg-type]
            skala=skala,
            top_n=top_n,
            prog=prog,
        )
        if zapisz and "pomiary" in wynik:
            calibrate.zapisz(
                session,
                kind="wrazliwosc",
                segment=profil,
                wartosc=float(wynik["max_przesuniecie"]),
                n_obs=int(wynik["n"]),
                zrodlo="filar_pm20",
                szczegoly=wynik,
            )

    if "pomiary" not in wynik:
        console.print(f"[yellow]{wynik.get('powod', 'brak danych')}[/yellow]")
        return

    console.print(
        f"ofert w rankingu: {wynik['n']}, czolowka: top-{wynik['top_n']}, "
        f"zmiana wagi: +/-{wynik['skala']:.0%}, prog: {wynik['prog']} wymienione oferty\n"
    )

    tabela = Table(title=f"Wrazliwosc rankingu na wage filaru ({wynik['profil']})")
    # Kolumna rozstrzygajaca idzie przed diagnostyczna, zeby nie sugerowac,
    # ze werdykt bierze sie z przesuniecia w pozycjach.
    for kolumna in ("filar", "kierunek", "waga", "wymiana top", "max przesun.", "mediana", ""):
        tabela.add_column(kolumna, justify="right")
    for pomiar in wynik["pomiary"]:
        bez_danych = not pomiar["ma_dane"]
        stan = (
            "brak danych"
            if bez_danych
            else ("[green]ok[/green]" if pomiar["stabilny"] else "[red]przekroczony[/red]")
        )
        przesuniecie = ("-" if bez_danych else f"{pomiar['max_przesuniecie']}") + (
            f" (+{pomiar['bez_wyniku']} bez wyniku)" if pomiar["bez_wyniku"] else ""
        )
        tabela.add_row(
            pomiar["filar"],
            pomiar["kierunek"],
            f"{pomiar['waga_bazowa']:.3f} -> {pomiar['waga_po']:.3f}",
            "-" if bez_danych else str(pomiar["wymiana_czolowki"]),
            przesuniecie,
            "-" if bez_danych else f"{pomiar['mediana_przesuniecia']:.1f}",
            stan,
        )
    console.print(tabela)

    if wynik["filary_bez_danych"]:
        console.print(
            "\n[yellow]Filary bez ani jednej wartosci:[/yellow] "
            f"{', '.join(wynik['filary_bez_danych'])}. Ich waga wypada w renormalizacji, "
            "wiec przesuniecie zawsze wynosi zero. To brak danych, nie stabilnosc, "
            "i dlatego nie liczy sie do werdyktu."
        )

    if not wynik["rozstrzygajacy"]:
        rozniace = wynik["filary_rozniacace_czolowke"]
        console.print(
            "\n[yellow]pomiar nie jest dzis rozstrzygajacy:[/yellow] w czolowce rozni sie "
            f"tylko {'jeden filar' if len(rozniace) == 1 else 'zaden filar'}"
            f"{' (' + ', '.join(rozniace) + ')' if rozniace else ''}, a reszta ma we wszystkich "
            "tych ofertach te sama wartosc. Kolejnosc jest wtedy posortowaniem tego jednego "
            "filaru i zaden dobor wag jej nie odwroci: kazda oferta przesuwa sie o tyle samo. "
            f"Do tego {wynik['top_n']} ofert czolowki dzieli miedzy siebie tylko "
            f"{wynik['top_n'] - wynik['remisy_w_czolowce']} roznych wynikow, wiec o czesci "
            "miejsc decyduje identyfikator oferty, a nie liczby."
        )

    if wynik["spelnione"]:
        najgorszy = wynik["najgorszy"]
        kolor = "green" if wynik["rozstrzygajacy"] else "yellow"
        console.print(
            f"\n[{kolor}]kryterium fazy 6 spelnione[/{kolor}]: wymiana skladu czolowki "
            f"najwyzej {wynik['max_wymiana_czolowki']} z {wynik['top_n']} ofert "
            f"(prog {wynik['prog']}), najgorszy przypadek to "
            f"{najgorszy['filar']} {najgorszy['kierunek']}"
            + ("" if wynik["rozstrzygajacy"] else " - ale patrz uwaga wyzej")
        )
    else:
        najgorszy = wynik["najgorszy"]
        console.print(
            f"\n[red]kryterium fazy 6 niespelnione[/red]: wymiana skladu czolowki "
            f"{wynik['max_wymiana_czolowki']} z {wynik['top_n']} ofert "
            f"(prog {wynik['prog']}), najgorszy przypadek to "
            f"{najgorszy['filar']} {najgorszy['kierunek']}."
        )

    # Diagnostyka, nie werdykt. Duze przesuniecie przy malej wymianie znaczy,
    # ze srodek stawki jest gesty, a nie ze ranking sie sypie - i te wade mierzy
    # osobno test dyskryminacji. Uzasadnienie wyboru miary jest przy stalej
    # MAX_ZMIANA_CZOLOWKI w scoring/calibration.py.
    console.print(
        f"Diagnostyka: najdalszy ruch pojedynczej oferty to {wynik['max_przesuniecie']} pozycji. "
        + (
            "Rozbieznosc z werdyktem bierze sie z gestego srodka stawki: jedna oferta "
            "przechodzaca przez grupe o niemal rownym wyniku przeskakuje wiele miejsc, "
            "choc czolowka niemal sie nie zmienia. Sprawdz `calibrate.py dyskryminacja`."
            if int(wynik["max_przesuniecie"]) > int(wynik["prog"])
            else "Zgodna z werdyktem."
        )
    )


@app.command()
def dyskryminacja() -> None:
    """Rozklad wynikow. Jesli 80% dzialek dostaje 60-70 punktow, scoring nic nie mowi."""
    with session_scope() as session:
        wynik = calibrate.dyskryminacja(session)

    if wynik is None:
        console.print("[yellow]za malo ocenionych ofert[/yellow]")
        return

    console.print(
        f"ocenionych ofert: {wynik.n}, mediana {wynik.szczegoly['mediana']:.1f}, "
        f"rozstep miedzykwartylowy {wynik.rozstep_miedzykwartylowy:.1f}, "
        f"odchylenie {wynik.odchylenie:.1f}"
    )
    for i, liczba in enumerate(wynik.przedzialy):
        udzial = liczba / wynik.n
        console.print(f"  {i * 10:3d}-{(i + 1) * 10:3d} {'#' * round(udzial * 50):50s} {liczba}")
    if wynik.rozroznia:
        console.print("[green]rozklad rozroznia dzialki[/green]")
    else:
        console.print(
            f"[red]{wynik.udzial_najliczniejszego:.0%} ofert w jednym przedziale[/red] "
            f"{wynik.przedzial_najliczniejszy}: scoring slabo rozroznia"
        )


@app.command()
def historia(limit: int = typer.Option(20, help="Ile pomiarow pokazac")) -> None:
    """Kolejne pomiary w czasie. Historia, nie stan: nic nie jest nadpisywane."""
    with session_scope() as session:
        wiersze = (
            session.execute(
                text(
                    """
                    SELECT kind, segment, wartosc, n_obs, zrodlo, computed_at
                    FROM calibrations ORDER BY computed_at DESC, id DESC LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )

    if not wiersze:
        console.print("[yellow]brak pomiarow. Uruchom `calibrate run`[/yellow]")
        return

    tabela = Table(title="Historia kalibracji")
    for kolumna in ("pomiar", "segment", "wartosc", "n", "zrodlo", "kiedy"):
        tabela.add_column(kolumna)
    for row in wiersze:
        tabela.add_row(
            row["kind"],
            row["segment"] or "-",
            f"{float(row['wartosc']):.4f}" if row["wartosc"] is not None else "-",
            str(row["n_obs"]),
            row["zrodlo"],
            row["computed_at"].strftime("%Y-%m-%d %H:%M"),
        )
    console.print(tabela)


if __name__ == "__main__":
    app()
