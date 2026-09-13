"""Status planistyczny A-E i jego wplyw na wartosc. Sekcja 5.3.3 dokumentu.

To jest najwieksza pojedyncza dzwignia wartosci na polskim rynku gruntow w 2026
roku i wynika wprost z konstrukcji przepisow: po uchwaleniu planu ogolnego typowa
nowa decyzja o warunkach zabudowy wymaga polozenia terenu w Obszarze Uzupelnienia
Zabudowy. Dzialka poza OUZ, bez MPZP i bez waznej WZ praktycznie traci sciezke
do zabudowy.

Stan pomiarowy z 2026-08-21 (pomorskie, 145 gmin po jednym punkcie):
    plan ogolny opublikowany: 14 gmin (9,7%)
    w gminach z planem, na 60 punktach: 16 w OUZ (27%), 44 poza OUZ

Czyli dzis wiekszosc dzialek jest w stanie E (brak planu ogolnego), a to stan
o najszerszym przedziale niepewnosci. Po 31.08.2026 gminy beda przechodzic
do stanow B i D, i wlasnie ta zmiana jest okazja produktowa: przejscie gminy
z E do D obniza wartosc dzialek poza OUZ o kilkadziesiat procent w jeden dzien.

Funkcje czyste: bez sieci, bez bazy, bez dat systemowych.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Status = Literal["A", "B", "C", "D", "E", "?"]

# Symbole MPZP oznaczajace przeznaczenie budowlane
MPZP_BUDOWLANE = frozenset({"MN", "MW", "MU", "MNU", "U", "UM", "RM", "MP", "ML"})

# Strefy planu ogolnego, w ktorych zabudowa jest przewidziana
STREFY_BUDOWLANE = frozenset({"SW", "SJ", "SZ", "SU", "SH", "SP"})

# Mnozniki wartosci wedlug tabeli z sekcji 5.3.3. Przedzial, nie liczba,
# bo dokument podaje widelki, a szerokosc widelek sama w sobie jest informacja.
MNOZNIKI: dict[Status, tuple[float, float]] = {
    "A": (1.00, 1.00),
    "B": (0.90, 1.00),
    "C": (0.85, 0.95),
    "D": (0.30, 0.50),
    "E": (0.50, 0.75),
    "?": (0.50, 1.00),
}

# Przedzial dla dzialki objetej MPZP o nieznanym przeznaczeniu. Dol to plan
# przewidujacy zielen albo teren rolny (gorzej niz brak planu, bo droga do
# zabudowy jest zamknieta), gora to plan budowlany, czyli pelny stan A.
MNOZNIK_MPZP_BEZ_SYMBOLU: tuple[float, float] = (0.45, 1.00)

OPISY: dict[Status, str] = {
    "A": "MPZP z przeznaczeniem budowlanym",
    "B": "plan ogolny uchwalony, dzialka w OUZ",
    "C": "wazna decyzja o warunkach zabudowy",
    "D": "plan ogolny uchwalony, dzialka POZA OUZ, brak MPZP",
    "E": "brak planu ogolnego, brak MPZP, brak WZ",
    "?": "brak danych planistycznych",
}


@dataclass(frozen=True, slots=True)
class PlanningInputs:
    """Wejscie z warstw publicznych. None znaczy "nie wiadomo", nie "nie ma"."""

    mpzp_symbol: str | None = None
    mpzp_budowlane: bool | None = None
    # Dzialka lezy w granicach aktu MPZP, ale przeznaczenia nie znamy.
    # Rejestr Urbanistyczny podaje granice aktow, nie symbole (sources/mpzp.py).
    objeta_mpzp: bool | None = None
    ma_plan_ogolny: bool | None = None
    strefa_symbol: str | None = None
    w_ouz: bool | None = None
    wz_wazna: bool | None = None


@dataclass(frozen=True, slots=True)
class PlanningAssessment:
    status: Status
    opis: str
    mnoznik_min: float
    mnoznik_max: float
    gate: float
    uzasadnienie: str
    pewne: bool

    @property
    def mnoznik(self) -> float:
        """Srodek przedzialu. Do rankingu, nigdy do prezentacji bez widelek."""
        return (self.mnoznik_min + self.mnoznik_max) / 2

    @property
    def szerokosc_przedzialu(self) -> float:
        return self.mnoznik_max - self.mnoznik_min

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "opis": self.opis,
            "mnoznik": round(self.mnoznik, 3),
            "przedzial": [self.mnoznik_min, self.mnoznik_max],
            "gate": self.gate,
            "uzasadnienie": self.uzasadnienie,
            "pewne": self.pewne,
        }


def normalize_mpzp_symbol(symbol: str | None) -> str | None:
    """'12MN/U' albo 'mn' -> 'MN'. Zwraca None dla pustych i nierozpoznanych."""
    if not symbol:
        return None
    litery = "".join(ch for ch in symbol.upper() if ch.isalpha())
    if not litery:
        return None
    for kandydat in sorted(MPZP_BUDOWLANE, key=len, reverse=True):
        if litery.startswith(kandydat):
            return kandydat
    return litery[:3]


def assess(inputs: PlanningInputs) -> PlanningAssessment:
    """Status planistyczny wedlug tabeli z sekcji 5.3.3.

    Kolejnosc rozstrzygania odpowiada siLE tytulu do zabudowy: MPZP jest aktem
    prawa miejscowego i bije wszystko, potem plan ogolny z OUZ, potem wazna WZ.
    """
    symbol = normalize_mpzp_symbol(inputs.mpzp_symbol)
    mpzp_budowlane = inputs.mpzp_budowlane
    if mpzp_budowlane is None and symbol is not None:
        mpzp_budowlane = symbol in MPZP_BUDOWLANE

    # A: MPZP z przeznaczeniem budowlanym
    if mpzp_budowlane:
        return _zbuduj("A", f"MPZP: {symbol or 'przeznaczenie budowlane'}", pewne=True)

    # MPZP jest, ale bez przeznaczenia. To NIE jest stan A: plan moze przewidywac
    # zabudowe mieszkaniowa albo teren zieleni, a to dwie skrajnie rozne wartosci.
    # To tez NIE jest stan E, bo E znaczy "brak MPZP", a plan tu jest. Zostaje
    # stan niepewny z wezszym przedzialem niz czyste "brak danych" i z faktem
    # planu zapisanym w uzasadnieniu, zeby uzytkownik wiedzial, gdzie zajrzec.
    if inputs.objeta_mpzp and symbol is None:
        low, high = MNOZNIK_MPZP_BEZ_SYMBOLU
        return PlanningAssessment(
            status="?",
            opis="dzialka objeta MPZP, przeznaczenie nieznane",
            mnoznik_min=low,
            mnoznik_max=high,
            gate=1.0,
            uzasadnienie=(
                "akt MPZP obejmuje dzialke, ale rejestr podaje tylko granice aktu, "
                "nie przeznaczenie terenu. Symbol trzeba odczytac z rysunku planu"
            ),
            pewne=False,
        )

    # B: plan ogolny, dzialka w OUZ
    if inputs.ma_plan_ogolny and inputs.w_ouz:
        strefa = inputs.strefa_symbol
        if strefa and strefa not in STREFY_BUDOWLANE:
            # W OUZ, ale w strefie nieprzeznaczonej pod zabudowe (np. SO, SN).
            # To sprzecznosc, ktora rozstrzygamy ostroznie.
            return _zbuduj(
                "D",
                f"w OUZ, ale strefa {strefa} nie przewiduje zabudowy",
                pewne=False,
            )
        return _zbuduj("B", f"plan ogolny, OUZ, strefa {strefa or 'nieznana'}", pewne=True)

    # C: wazna decyzja o warunkach zabudowy
    if inputs.wz_wazna:
        return _zbuduj("C", "wazna decyzja o warunkach zabudowy", pewne=True)

    # D: plan ogolny uchwalony, dzialka poza OUZ
    if inputs.ma_plan_ogolny and inputs.w_ouz is False:
        strefa = inputs.strefa_symbol
        if strefa in STREFY_BUDOWLANE:
            # Strefa budowlana bez OUZ: nowa WZ raczej nieosiagalna, ale sam
            # kierunek planistyczny jest korzystny. Gorna granica widelek.
            return _zbuduj(
                "D",
                f"poza OUZ, ale strefa {strefa} przewiduje zabudowe",
                pewne=True,
                gorna_polowa=True,
            )
        return _zbuduj("D", f"poza OUZ, strefa {strefa or 'nieznana'}, brak MPZP", pewne=True)

    # E: brak planu ogolnego
    if inputs.ma_plan_ogolny is False:
        return _zbuduj(
            "E",
            "gmina nie ma jeszcze planu ogolnego, wiec sciezka WZ pozostaje otwarta",
            pewne=True,
        )

    return _zbuduj("?", "brak danych z warstw planistycznych", pewne=False)


def _zbuduj(
    status: Status, uzasadnienie: str, *, pewne: bool, gorna_polowa: bool = False
) -> PlanningAssessment:
    low, high = MNOZNIKI[status]
    if gorna_polowa:
        low = (low + high) / 2
    return PlanningAssessment(
        status=status,
        opis=OPISY[status],
        mnoznik_min=low,
        mnoznik_max=high,
        gate=gate_for(status),
        uzasadnienie=uzasadnienie,
        pewne=pewne,
    )


def gate_for(status: Status) -> float:
    """Mnoznik zerujacy z sekcji 5.3.3.

    Dzialka poza OUZ bez MPZP i bez WZ po uchwaleniu planu ogolnego dostaje 0,40.
    To jest gate, a nie skladnik sumy wazonej: brak sciezki do zabudowy nie da sie
    nadrobic dobrym uzbrojeniem ani ladnym widokiem.
    """
    return 0.40 if status == "D" else 1.0
