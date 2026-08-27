"""Chlonnosc dzialki: ile powierzchni uzytkowej wolno na niej postawic.

Sekcja 5.2.5 dokumentu. Plan ogolny nie mowi wprost "tu zmiesci sie 800 m2
mieszkan", tylko naklada cztery niezalezne ograniczenia. Wiazace jest
NAJOSTRZEJSZE z nich, a nie to, ktore akurat znamy:

    z intensywnosci:       PC = A * I_nadziemna
    z pow. zabudowy:       PC = A * U_zabudowy * kondygnacje
    z pow. biol. czynnej:  PC = A * (1 - PBC_min) * kondygnacje
    z wysokosci:           kondygnacje = floor(H_max / 3,2 m)

    PUM = min(dostepnych ograniczen) * eta_PUM

Wysokosc nie jest osobnym ograniczeniem powierzchni, tylko wchodzi do dwoch
pozostalych przez liczbe kondygnacji. Dlatego sama wysokosc bez udzialu
zabudowy albo bez udzialu biologicznie czynnego niczego nie ogranicza.

3,2 m to typowa kondygnacja mieszkalna: 2,5-2,6 m w swietle plus strop.

eta_PUM przelicza powierzchnie calkowita na uzytkowa mieszkalna, bo klatki,
scian i szachtow nikt nie sprzedaje. 0,70 dla wielorodzinnej, 0,80 dla
jednorodzinnej: w niskiej zabudowie komunikacja pionowa zjada mniej.

BRAK WSKAZNIKA TO NIE ZERO. Strefa gospodarcza bez limitu wysokosci ma tu None
i po prostu nie wnosi ograniczenia. Gdy nie ma ANI JEDNEGO wskaznika, chlonnosc
jest niedostepna i filar wchodzi do renormalizacji wag, zamiast dostawac zero.

Funkcje czyste: bez sieci, bez bazy, bez czasu systemowego.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final

# Typowa wysokosc kondygnacji mieszkalnej w metrach (sekcja 5.2.5)
WYSOKOSC_KONDYGNACJI_M: Final = 3.2

# Przelicznik powierzchni calkowitej na uzytkowa mieszkalna
ETA_PUM_WIELORODZINNA: Final = 0.70
ETA_PUM_JEDNORODZINNA: Final = 0.80

# Strefy planu ogolnego, w ktorych zabudowa jest niska (sekcja 5.3.3)
STREFY_NISKIE: Final = frozenset({"SJ", "SZ"})


class ChlonnoscError(ValueError):
    pass


def eta_pum(strefa_symbol: str | None) -> float:
    """Przelicznik dla strefy. Domyslnie wielorodzinny, bo jest ostrozniejszy."""
    if strefa_symbol in STREFY_NISKIE:
        return ETA_PUM_JEDNORODZINNA
    return ETA_PUM_WIELORODZINNA


def liczba_kondygnacji(maks_wysokosc_m: float | None) -> int | None:
    """Ile kondygnacji miesci sie w dopuszczalnej wysokosci.

    Zaokraglenie w dol, bo pol kondygnacji nie da sie sprzedac. Wysokosc
    ponizej jednej kondygnacji daje 0 i to nie jest blad: strefa z limitem
    2 m nie dopuszcza budynku.
    """
    if maks_wysokosc_m is None:
        return None
    if maks_wysokosc_m < 0:
        raise ChlonnoscError("wysokosc nie moze byc ujemna")
    return int(math.floor(maks_wysokosc_m / WYSOKOSC_KONDYGNACJI_M))


@dataclass(frozen=True, slots=True)
class Chlonnosc:
    """Ile PUM wychodzi z dzialki i ktore ograniczenie o tym zdecydowalo."""

    pum_m2: float | None
    pc_m2: float | None
    kondygnacje: int | None
    eta: float
    wiazace: str | None
    ograniczenia: dict[str, float]
    area_m2: float

    @property
    def dostepna(self) -> bool:
        return self.pum_m2 is not None

    @property
    def pum_na_m2_dzialki(self) -> float | None:
        """PUM na metr dzialki: jedyna postac porownywalna miedzy dzialkami."""
        if self.pum_m2 is None or self.area_m2 <= 0:
            return None
        return self.pum_m2 / self.area_m2

    def to_dict(self) -> dict[str, Any]:
        return {
            "pum_m2": round(self.pum_m2, 1) if self.pum_m2 is not None else None,
            "pc_m2": round(self.pc_m2, 1) if self.pc_m2 is not None else None,
            "pum_na_m2_dzialki": (
                round(self.pum_na_m2_dzialki, 3) if self.pum_na_m2_dzialki is not None else None
            ),
            "kondygnacje": self.kondygnacje,
            "eta_pum": self.eta,
            "wiazace_ograniczenie": self.wiazace,
            "ograniczenia_m2": {k: round(v, 1) for k, v in self.ograniczenia.items()},
        }


def oblicz(
    area_m2: float,
    *,
    maks_intensywnosc: float | None = None,
    maks_udzial_zabudowy_proc: float | None = None,
    maks_wysokosc_m: float | None = None,
    min_biologicznie_czynne_proc: float | None = None,
    strefa_symbol: str | None = None,
) -> Chlonnosc:
    """Powierzchnia uzytkowa mieszkalna mozliwa na dzialce.

    Zwraca rowniez, KTORE ograniczenie okazalo sie wiazace. Bez tego liczba
    jest nie do obrony przed uzytkownikiem: "800 m2" nic nie znaczy, a
    "800 m2, bo minimalny udzial biologicznie czynny to 50%" juz tak.
    """
    if area_m2 <= 0:
        raise ChlonnoscError("powierzchnia dzialki musi byc dodatnia")

    kondygnacje = liczba_kondygnacji(maks_wysokosc_m)
    ograniczenia: dict[str, float] = {}

    if maks_intensywnosc is not None:
        ograniczenia["intensywnosc"] = area_m2 * maks_intensywnosc

    # Udzial zabudowy i udzial biologicznie czynny ograniczaja RZUT budynku.
    # Na powierzchnie calkowita przekladaja sie dopiero przez kondygnacje,
    # wiec bez znanej wysokosci nie wnosza nic.
    if kondygnacje is not None:
        if maks_udzial_zabudowy_proc is not None:
            ograniczenia["udzial_zabudowy"] = (
                area_m2 * (maks_udzial_zabudowy_proc / 100.0) * kondygnacje
            )
        if min_biologicznie_czynne_proc is not None:
            ograniczenia["biologicznie_czynne"] = (
                area_m2 * (1.0 - min_biologicznie_czynne_proc / 100.0) * kondygnacje
            )

    if not ograniczenia:
        return Chlonnosc(
            pum_m2=None,
            pc_m2=None,
            kondygnacje=kondygnacje,
            eta=eta_pum(strefa_symbol),
            wiazace=None,
            ograniczenia={},
            area_m2=area_m2,
        )

    wiazace = min(ograniczenia, key=lambda k: ograniczenia[k])
    pc = ograniczenia[wiazace]
    eta = eta_pum(strefa_symbol)
    return Chlonnosc(
        pum_m2=pc * eta,
        pc_m2=pc,
        kondygnacje=kondygnacje,
        eta=eta,
        wiazace=wiazace,
        ograniczenia=ograniczenia,
        area_m2=area_m2,
    )
