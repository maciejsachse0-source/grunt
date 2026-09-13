"""Wyciaganie numeru dzialki z tresci ogloszenia.

Dlaczego to jest potrzebne mimo istnienia ULDK i EGiB: wspolrzedne z portali sa
przyblizone, a powierzchnia nie rozstrzyga. Pomiar na ofercie z Gdanska: w
promieniu 150 m lezy SZESNASCIE dzialek o powierzchni zgodnej z ogloszeniem
(+/-10%), a najlepsza z nich ma 1113 m2 przy deklarowanych 1115. W typowej
zabudowie podmiejskiej sasiednie parcele maja podobny rozmiar, wiec sama
powierzchnia to za slaby sygnal.

Numer dzialki podany w opisie jest sygnalem mocniejszym niz wspolrzedne
i powierzchnia razem wziete, bo pozwala odpytac ULDK po identyfikatorze
i dostac konkretna geometrie zamiast kandydata.

CO WOLNO ZAPISAC: sam numer dzialki i obrebu. To atrybut nieruchomosci
z rejestru publicznego, nie dana osobowa. Opis ogloszenia jest tylko czytany
w pamieci i nigdy nie trafia do bazy (sekcja 8.2).

Funkcje czyste.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# "dzialka nr 129/3", "dz. nr 208/25", "numer dzialki: 12", "dzialki nr 273"
_NUMER = re.compile(
    r"(?:dz(?:\.|ialk\w*)?)\s*(?:ewid\w*\s*)?(?:nr\.?|numer|o\s+numerze)?\s*[:.]?\s*"
    r"(\d{1,4}(?:/\d{1,4})?)",
    re.I,
)

# "obreb 63", "obreb ewidencyjny 0036", "obrebie Kielpino Gorne"
_OBREB_NUMER = re.compile(r"obr[ęe]b\w*\s*(?:ewidencyjn\w*)?\s*[:.]?\s*(\d{1,4})\b", re.I)
_OBREB_NAZWA = re.compile(r"obr[ęe]b\w*\s*[:.]?\s*([A-ZŁŚŻĆÓ][\w-]+(?:\s+[A-ZŁŚŻĆÓ][\w-]+)?)")

# Konteksty, w ktorych liczba po slowie "dzialka" NIE jest numerem ewidencyjnym
_PULAPKI = re.compile(
    r"dzialk\w*\s+(?:o\s+)?(?:pow\.|powierzchni\w*|wielkosci|ma|liczy)\b|"
    r"dzialk\w*\s*\d+\s*(?:m2|m²|ar|ha)",
    re.I,
)


@dataclass(frozen=True, slots=True)
class ParcelRef:
    numery: tuple[str, ...] = ()
    obreb_numer: str | None = None
    obreb_nazwa: str | None = None

    def __bool__(self) -> bool:
        return bool(self.numery)

    @property
    def pewny(self) -> bool:
        """Jeden numer w calym opisie to sygnal jednoznaczny.

        Kilka numerow zwykle znaczy, ze ogloszenie dotyczy zestawu dzialek albo
        wspomina sasiednie. Wtedy nie zgadujemy, ktora z nich jest przedmiotem
        oferty.
        """
        return len(self.numery) == 1

    def to_dict(self) -> dict[str, object]:
        return {
            "numery": list(self.numery),
            "obreb_numer": self.obreb_numer,
            "obreb_nazwa": self.obreb_nazwa,
        }


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def extract(text: str | None) -> ParcelRef:
    """Numery dzialek i obreb z tresci ogloszenia."""
    if not text:
        return ParcelRef()

    plain = re.sub(r"\s+", " ", _strip_html(text))

    numery: list[str] = []
    for match in _NUMER.finditer(plain):
        kontekst = plain[max(0, match.start() - 40) : match.end() + 12]
        if _PULAPKI.search(kontekst):
            continue
        numer = match.group(1)
        # Numer bez ukosnika i wiekszy niz 4 cyfry to prawie zawsze powierzchnia
        # albo cena, ktora przeciekla przez filtr kontekstu.
        if "/" not in numer and len(numer) > 4:
            continue
        if numer not in numery:
            numery.append(numer)

        # "dzialki nr 12/3 oraz 12/4" - drugi numer nie ma juz przedrostka,
        # a ogloszenie dotyczy DWOCH dzialek. Przeoczenie tego dawaloby
        # falszywe poczucie jednoznacznosci (pole pewny).
        ogon = plain[match.end() : match.end() + 60]
        for dodatkowy in re.findall(r"(\d{1,4}/\d{1,4})", ogon):
            if dodatkowy not in numery:
                numery.append(dodatkowy)

    obreb_numer = None
    if (m := _OBREB_NUMER.search(plain)) is not None:
        obreb_numer = m.group(1).zfill(4)

    obreb_nazwa = None
    if obreb_numer is None and (m := _OBREB_NAZWA.search(plain)) is not None:
        obreb_nazwa = m.group(1).strip()

    return ParcelRef(
        numery=tuple(numery[:5]),
        obreb_numer=obreb_numer,
        obreb_nazwa=obreb_nazwa,
    )


def build_uldk_id(teryt_gmina_prefix: str, obreb_numer: str, numer_dzialki: str) -> str:
    """Zlozenie identyfikatora ULDK z czesci, np. 226101_1.0036.208/25.

    teryt_gmina_prefix to poczatek identyfikatora w formacie ULDK (226101_1),
    czyli TERYT gminy z cyfra rodzaju oddzielona podkreslnikiem.
    """
    return f"{teryt_gmina_prefix}.{obreb_numer.zfill(4)}.{numer_dzialki}"
