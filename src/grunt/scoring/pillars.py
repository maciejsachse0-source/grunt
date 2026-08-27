"""Szesc filarow scoringu potencjalu. Sekcja 5.3.2 dokumentu.

    Score = Gate * suma(waga_filaru * ocena_filaru)

Dlaczego filary, a nie plaska lista cech: uzbrojenie, dostep do drogi, bliskosc
centrum i MPZP sa silnie skorelowane, wiec naiwna suma wazona liczylaby ten sam
sygnal cztery razy. Wewnatrz filaru korelacja jest nieszkodliwa, bo filar ma
jedna wage.

Wagi z tabeli w sekcji 5.3.2, w dwoch profilach. Dokument zaleca dwa profile
od poczatku, bo dorobienie ich pozniej jest drogie:

                              detaliczny  deweloper
    1. planistyka                 35%        45%
    2. lokalizacja                22%        18%
    3. infrastruktura             18%        12%
    4. fizyka dzialki             10%         8%
    5. ryzyka srodowiskowe        10%         7%
    6. dynamika rynku              5%         5%
    (deweloper dodatkowo chlonnosc 5%)

BRAKI DANYCH, sekcja 5.3.9. Renormalizujemy wagi na dostepne filary:

    S = suma(w_k * z_k po dostepnych) / suma(w_k po dostepnych)

i osobno raportujemy kompletnosc. Ponizej 40% kompletnosci nie zwracamy liczby
w ogole, tylko powod. Zly score jest gorszy niz brak score'u.

Funkcje czyste: bez sieci, bez bazy, bez czasu systemowego.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from grunt.scoring import chlonnosc as chlonnosc_mod
from grunt.scoring import gates as gates_mod

Profil = Literal["detaliczny", "deweloper"]

WAGI: dict[Profil, dict[str, float]] = {
    "detaliczny": {
        "planistyka": 0.35,
        "lokalizacja": 0.22,
        "infrastruktura": 0.18,
        "fizyka": 0.10,
        "ryzyka": 0.10,
        "rynek": 0.05,
    },
    "deweloper": {
        "planistyka": 0.45,
        "lokalizacja": 0.18,
        "infrastruktura": 0.12,
        "fizyka": 0.08,
        "ryzyka": 0.07,
        "rynek": 0.05,
        "chlonnosc": 0.05,
    },
}

NAZWY = {
    "planistyka": "Planistyka i dopuszczalnosc zabudowy",
    "lokalizacja": "Lokalizacja i dostepnosc",
    "infrastruktura": "Infrastruktura",
    "fizyka": "Fizyka dzialki",
    "ryzyka": "Ryzyka srodowiskowe",
    "rynek": "Dynamika rynku gminy",
    "chlonnosc": "Chlonnosc i PUM",
}

# Ponizej tej kompletnosci nie pokazujemy wyniku (sekcja 5.3.9)
COVERAGE_MIN = 0.40

# Punktacja statusow planistycznych, przelozona z mnoznikow wartosci
PUNKTY_STATUSU = {"A": 100.0, "B": 88.0, "C": 80.0, "D": 20.0, "E": 55.0, "?": 50.0}


@dataclass(frozen=True, slots=True)
class PillarScore:
    klucz: str
    punkty: float | None
    skladniki: dict[str, Any] = field(default_factory=dict)

    @property
    def dostepny(self) -> bool:
        return self.punkty is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "filar": NAZWY.get(self.klucz, self.klucz),
            "punkty": round(self.punkty, 1) if self.punkty is not None else None,
            "skladniki": self.skladniki,
        }


@dataclass(frozen=True, slots=True)
class Score:
    profil: Profil
    punkty: float | None
    coverage: float
    gate: gates_mod.GateResult
    filary: tuple[PillarScore, ...]
    powod_braku: str | None = None
    czerwone_flagi: tuple[str, ...] = field(default_factory=tuple)

    @property
    def wiarygodny(self) -> bool:
        return self.punkty is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profil": self.profil,
            "score": round(self.punkty, 1) if self.punkty is not None else None,
            "kompletnosc": round(self.coverage, 3),
            "wiarygodny": self.wiarygodny,
            "powod_braku": self.powod_braku,
            "gate": self.gate.to_dict(),
            "filary": [f.to_dict() for f in self.filary],
            "czerwone_flagi": list(self.czerwone_flagi),
        }


def _skaluj(
    wartosc: float | None, dolny: float, gorny: float, *, odwrotnie: bool = False
) -> float | None:
    """Liniowe przelozenie wartosci na 0-100 z obcieciem na koncach."""
    if wartosc is None:
        return None
    if gorny == dolny:
        return 50.0
    udzial = (wartosc - dolny) / (gorny - dolny)
    udzial = max(0.0, min(1.0, udzial))
    return round((1 - udzial if odwrotnie else udzial) * 100, 1)


def pillar_planistyka(status: str | None, w_ouz: bool | None) -> PillarScore:
    if status is None:
        return PillarScore("planistyka", None)
    punkty = PUNKTY_STATUSU.get(status)
    return PillarScore(
        "planistyka",
        punkty,
        {"status": status, "w_ouz": w_ouz},
    )


def pillar_infrastruktura(koszt_mediow_pln: int | None, road_access: int | None) -> PillarScore:
    """Sekcja 5.3.5: uzbrojenie liczone kosztem w zlotowkach, nie flaga.

    0 zl to 100 punktow, 150 tys. zl to 0 punktow, bo tyle wynosi gorna granica
    kosztu doprowadzenia czterech mediow.
    """
    if koszt_mediow_pln is None and road_access is None:
        return PillarScore("infrastruktura", None)

    czesci: list[float] = []
    skladniki: dict[str, Any] = {}

    if koszt_mediow_pln is not None:
        punkty_media = _skaluj(float(koszt_mediow_pln), 0, 150_000, odwrotnie=True)
        if punkty_media is not None:
            czesci.append(punkty_media)
        skladniki["koszt_mediow_pln"] = koszt_mediow_pln

    if road_access is not None:
        punkty_droga = {0: 0.0, 1: 60.0, 2: 100.0}.get(road_access)
        if punkty_droga is not None:
            czesci.append(punkty_droga)
        skladniki["dostep_do_drogi"] = road_access

    return PillarScore(
        "infrastruktura",
        round(sum(czesci) / len(czesci), 1) if czesci else None,
        skladniki,
    )


def pillar_fizyka(
    front_m: float | None, spadek_proc: float | None, zwartosc: float | None
) -> PillarScore:
    """Sekcja 5.3.6. Progi: front 18 m, spadek do 8%, zwartosc od 0,45."""
    czesci: list[float] = []
    skladniki: dict[str, Any] = {}

    if front_m is not None:
        punkty = _skaluj(front_m, 10, 30)
        if punkty is not None:
            czesci.append(punkty)
        skladniki["front_m"] = front_m
    if spadek_proc is not None:
        punkty = _skaluj(spadek_proc, 0, 15, odwrotnie=True)
        if punkty is not None:
            czesci.append(punkty)
        skladniki["spadek_proc"] = spadek_proc
    if zwartosc is not None:
        punkty = _skaluj(zwartosc, 0.35, 0.78)
        if punkty is not None:
            czesci.append(punkty)
        skladniki["zwartosc"] = zwartosc

    return PillarScore("fizyka", round(sum(czesci) / len(czesci), 1) if czesci else None, skladniki)


def pillar_ryzyka(
    strefy_powodziowe: tuple[str, ...] | list[str] | None,
    *,
    sprawdzone: bool = True,
    obszar_chroniony: bool | None = None,
) -> PillarScore:
    if not sprawdzone:
        return PillarScore("ryzyka", None)

    strefy = tuple(strefy_powodziowe or ())
    punkty = 100.0
    if "q10" in strefy:
        punkty = 10.0
    elif "q1" in strefy:
        punkty = 30.0
    elif "hWZ" in strefy:
        punkty = 45.0
    elif "q0_2" in strefy:
        punkty = 75.0

    if obszar_chroniony:
        punkty = min(punkty, 60.0)

    return PillarScore(
        "ryzyka", punkty, {"strefy": list(strefy), "obszar_chroniony": obszar_chroniony}
    )


def pillar_lokalizacja(
    czas_do_rdzenia_min: float | None = None,
    odleglosc_do_morza_m: float | None = None,
    wysokosc_npm: float | None = None,
) -> PillarScore:
    """Filar 2. Na razie dziala na tym, co mamy bez izochron (faza 3 dokumentu).

    Izochrony Valhalli sa dopiero planowane, wiec bez nich filar zostaje
    niedostepny i renormalizacja wag to uwzglednia. To lepsze niz wpisanie
    wartosci srodkowej i udawanie, ze cos wiemy.
    """
    czesci: list[float] = []
    skladniki: dict[str, Any] = {}

    if czas_do_rdzenia_min is not None:
        punkty = _skaluj(czas_do_rdzenia_min, 10, 60, odwrotnie=True)
        if punkty is not None:
            czesci.append(punkty)
        skladniki["czas_dojazdu_min"] = czas_do_rdzenia_min
    if odleglosc_do_morza_m is not None:
        punkty = _skaluj(odleglosc_do_morza_m, 500, 20_000, odwrotnie=True)
        if punkty is not None:
            czesci.append(punkty)
        skladniki["odleglosc_do_morza_m"] = odleglosc_do_morza_m

    if not czesci:
        return PillarScore("lokalizacja", None, skladniki)
    return PillarScore("lokalizacja", round(sum(czesci) / len(czesci), 1), skladniki)


def pillar_chlonnosc(chlonnosc: chlonnosc_mod.Chlonnosc | None) -> PillarScore:
    """Filar 7, tylko w profilu dewelopera. Sekcja 5.2.5.

    Skala jest w PUM na metr dzialki, bo tylko ta postac da sie porownac miedzy
    dzialkami o roznej wielkosci. Progi 0,2 i 1,5 wziete z rozpietosci, ktora
    daje plan ogolny: strefa jednorodzinna z intensywnoscia 0,4 wychodzi ok.
    0,32, a wielorodzinna z intensywnoscia 2,5 ok. 1,75.

    Ten filar celowo premiuje wysoka intensywnosc, bo profil deweloperski kupuje
    grunt pod PUM. W profilu detalicznym filaru nie ma w ogole i tak ma byc:
    kupujacy dzialke pod wlasny dom nie chce maksymalnej chlonnosci.
    """
    if chlonnosc is None or not chlonnosc.dostepna:
        return PillarScore("chlonnosc", None)

    na_m2 = chlonnosc.pum_na_m2_dzialki
    punkty = _skaluj(na_m2, 0.2, 1.5)
    return PillarScore(
        "chlonnosc",
        punkty,
        {
            "pum_m2": round(chlonnosc.pum_m2, 1) if chlonnosc.pum_m2 is not None else None,
            "pum_na_m2_dzialki": round(na_m2, 3) if na_m2 is not None else None,
            "kondygnacje": chlonnosc.kondygnacje,
            "wiazace_ograniczenie": chlonnosc.wiazace,
        },
    )


def pillar_rynek(
    dynamika_cen_3y: float | None = None, plynnosc: float | None = None
) -> PillarScore:
    czesci: list[float] = []
    skladniki: dict[str, Any] = {}
    if dynamika_cen_3y is not None:
        punkty = _skaluj(dynamika_cen_3y, -0.05, 0.20)
        if punkty is not None:
            czesci.append(punkty)
        skladniki["dynamika_cen_3y"] = dynamika_cen_3y
    if plynnosc is not None:
        punkty = _skaluj(plynnosc, 0, 10)
        if punkty is not None:
            czesci.append(punkty)
        skladniki["plynnosc"] = plynnosc
    if not czesci:
        return PillarScore("rynek", None, skladniki)
    return PillarScore("rynek", round(sum(czesci) / len(czesci), 1), skladniki)


def combine(
    filary: list[PillarScore],
    gate: gates_mod.GateResult,
    *,
    profil: Profil = "detaliczny",
    czerwone_flagi: tuple[str, ...] = (),
    coverage_min: float = COVERAGE_MIN,
) -> Score:
    """Suma wazona z renormalizacja na dostepne filary (sekcja 5.3.9)."""
    wagi = WAGI[profil]
    dostepne = [f for f in filary if f.dostepny and f.klucz in wagi]

    waga_dostepnych = sum(wagi[f.klucz] for f in dostepne)
    waga_wszystkich = sum(wagi.values())
    coverage = round(waga_dostepnych / waga_wszystkich, 3) if waga_wszystkich else 0.0

    if coverage < coverage_min or not dostepne:
        brakujace = sorted(NAZWY.get(k, k) for k in wagi if k not in {f.klucz for f in dostepne})
        return Score(
            profil=profil,
            punkty=None,
            coverage=coverage,
            gate=gate,
            filary=tuple(filary),
            powod_braku=(
                f"za malo danych (kompletnosc {coverage:.0%}, prog {coverage_min:.0%}). "
                f"Brakuje: {', '.join(brakujace[:4])}"
            ),
            czerwone_flagi=czerwone_flagi,
        )

    surowy = sum(wagi[f.klucz] * (f.punkty or 0) for f in dostepne) / waga_dostepnych
    return Score(
        profil=profil,
        punkty=round(surowy * gate.mnoznik, 1),
        coverage=coverage,
        gate=gate,
        filary=tuple(filary),
        czerwone_flagi=czerwone_flagi,
    )
