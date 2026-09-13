"""Mnozniki zerujace. Sekcja 5.3.1 dokumentu.

    Score = Gate * suma wazona filarow,  Gate = iloczyn mnoznikow

Kluczowa zasada, ktora odroznia ten scoring od naiwnego: czynniki, ktorych brak
DYSKWALIFIKUJE inwestycje, nie moga wchodzic do sumy wazonej. Suma usrednia,
a te czynniki musza zerowac. Dzialka bez dostepu do drogi publicznej nie jest
"o 10% gorsza", tylko jest niebudowlana, choc bylaby uzbrojona i piekna.

Wartosci mnoznikow z tabeli w sekcji 5.3.1, uzupelnione o powodz z 5.3.7.
Wszystkie sa jawne i konfigurowalne, bo dokument nazywa je "propozycja
startowa do kalibracji".

Funkcje czyste.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Mnozniki startowe (sekcja 5.3.1 i 5.3.7)
BRAK_DOSTEPU_DO_DROGI = 0.35
POZA_OUZ_BEZ_MPZP = 0.40
STREFA_ZALEWOWA_Q1 = 0.55
GRUNT_LESNY_BEZ_ODLESIENIA = 0.30


@dataclass(frozen=True, slots=True)
class Gate:
    nazwa: str
    mnoznik: float
    powod: str

    def to_dict(self) -> dict[str, object]:
        return {"nazwa": self.nazwa, "mnoznik": self.mnoznik, "powod": self.powod}


@dataclass(frozen=True, slots=True)
class GateResult:
    gates: tuple[Gate, ...] = field(default_factory=tuple)

    @property
    def mnoznik(self) -> float:
        """Iloczyn wszystkich mnoznikow. Brak gate'ow daje 1,0."""
        wynik = 1.0
        for gate in self.gates:
            wynik *= gate.mnoznik
        return wynik

    @property
    def aktywne(self) -> tuple[str, ...]:
        return tuple(g.nazwa for g in self.gates)

    @property
    def dyskwalifikujacy(self) -> bool:
        """Czy ktorykolwiek gate obcina wartosc o ponad polowe."""
        return self.mnoznik < 0.5

    def to_dict(self) -> dict[str, object]:
        return {
            "mnoznik": round(self.mnoznik, 3),
            "aktywne": [g.to_dict() for g in self.gates],
        }


def evaluate(
    *,
    road_access: int | None = None,
    plan_status: str | None = None,
    strefy_powodziowe: tuple[str, ...] | list[str] | None = None,
    sposob_uzyt: str | None = None,
    odlesienie_mozliwe: bool | None = None,
) -> GateResult:
    """Zestaw aktywnych mnoznikow dla dzialki.

    road_access w kodowaniu trojstanowym z sekcji 5.3.5:
        2 = bezposredni dostep do drogi publicznej
        1 = przez sluzebnosc albo droge wewnetrzna z udzialem
        0 = brak, konieczna sluzebnosc drogi koniecznej z sadu
        None = nie wiadomo, i wtedy NIE karzemy
    """
    aktywne: list[Gate] = []

    if road_access == 0:
        aktywne.append(
            Gate(
                "brak_dostepu_do_drogi",
                BRAK_DOSTEPU_DO_DROGI,
                "dzialka bez dostepu do drogi publicznej i bez sluzebnosci: "
                "dostep jest warunkiem koniecznym decyzji o warunkach zabudowy",
            )
        )

    if plan_status == "D":
        aktywne.append(
            Gate(
                "poza_ouz",
                POZA_OUZ_BEZ_MPZP,
                "poza Obszarem Uzupelnienia Zabudowy, bez MPZP i bez waznej WZ: "
                "praktycznie brak sciezki do zabudowy",
            )
        )

    strefy = tuple(strefy_powodziowe or ())
    if "q10" in strefy:
        aktywne.append(Gate("powodz_q10", 0.40, "strefa zalewowa raz na 10 lat"))
    elif "q1" in strefy:
        aktywne.append(Gate("powodz_q1", STREFA_ZALEWOWA_Q1, "strefa zalewowa raz na 100 lat"))
    elif "hWZ" in strefy:
        aktywne.append(
            Gate(
                "powodz_morska", 0.60, "scenariusz calkowitego zniszczenia walu przeciwpowodziowego"
            )
        )

    if sposob_uzyt and "lesn" in sposob_uzyt.lower() and odlesienie_mozliwe is False:
        aktywne.append(
            Gate(
                "grunt_lesny",
                GRUNT_LESNY_BEZ_ODLESIENIA,
                "grunt lesny bez sciezki odlesienia",
            )
        )

    return GateResult(gates=tuple(aktywne))
