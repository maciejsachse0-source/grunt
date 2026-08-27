"""Segmentacja rynku: przeznaczenie dzialki jako pierwszy wymiar porownania.

Model 1 z dokumentu to "mediana ceny/m2 znormalizowanej per (gmina x PRZEZNACZENIE)".
Bez drugiego czlonu model porownuje pole uprawne do dzialki budowlanej.
Skala roznicy na danych pomorskich (RCN, 2023-2026, n=21 tys.):

    terenRolniczy                          16,6 zl/m2
    terenDrogWewnetrznych                  12,6 zl/m2
    gruntyLesne                            25,7 zl/m2
    brakMPZPLubWZ                          83,7 zl/m2
    decyzjaWarunkiZabudowy                132,4 zl/m2
    budownictwoMieszkanioweJednorodzinne  158,2 zl/m2
    terenZabudowyUslugowej                248,1 zl/m2

To rzad wielkosci, nie niuans. Mieszanie tych kategorii bylo pojedyncza przyczyna
MdAPE 50% w pierwszej walidacji.

Uwaga na pulapke: pole sposob_uzyt (klasyfikacja ewidencyjna) NIE zastepuje
przeznaczenia. "gruntyRolne" o powierzchni 900 m2 pod Gdanskiem to zwykle dzialka
budowlana czekajaca na odrolnienie i kosztuje 136 zl/m2, a te same "gruntyRolne"
o powierzchni 2 ha to pole za 9 zl/m2. Dlatego klasyfikacja idzie najpierw
po przeznaczeniu, a ewidencja jest tylko awaryjna.

Funkcje czyste.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Final, Literal

Segment = Literal[
    "mieszkaniowa_wielorodzinna",
    "mieszkaniowa_jednorodzinna",
    "uslugowa_produkcyjna",
    "rekreacyjna",
    "rolna",
    "lesna",
    "droga",
    "budowlana_wz",
    # Ponizsze trzy to worek "RCN nie podal przeznaczenia". Rozdzielamy go po
    # klasyfikacji ewidencyjnej, bo ta niesie realny sygnal cenowy (grunty
    # zurbanizowane 222 zl/m2 wobec rolnych 104 zl/m2), choc slabszy niz MPZP.
    "nieokreslona_zurbanizowana",
    "nieokreslona_rolna",
    "nieokreslona",
]

# Fragmenty nazw przeznaczen z RCN, w kolejnosci rozstrzygania.
# Pierwszy pasujacy wygrywa, dlatego wielorodzinna stoi przed jednorodzinna.
_RULES: Final[tuple[tuple[str, Segment], ...]] = (
    ("budownictwomieszkaniowewielorodzinne", "mieszkaniowa_wielorodzinna"),
    ("budownictwomieszkaniowejednorodzinne", "mieszkaniowa_jednorodzinna"),
    ("zabudowazagrodowa", "mieszkaniowa_jednorodzinna"),
    ("terenzabudowyuslugowej", "uslugowa_produkcyjna"),
    ("produkcyj", "uslugowa_produkcyjna"),
    ("przemysl", "uslugowa_produkcyjna"),
    ("skladow", "uslugowa_produkcyjna"),
    ("sportuirekreacji", "rekreacyjna"),
    ("rekreacyj", "rekreacyjna"),
    ("letnisk", "rekreacyjna"),
    ("terendrog", "droga"),
    ("komunikacj", "droga"),
    ("terenrolnicz", "rolna"),
    ("terenlesn", "lesna"),
    ("lasow", "lesna"),
    ("decyzjawarunkizabudowy", "budowlana_wz"),
)

_UZYTEK_RULES: Final[tuple[tuple[str, Segment], ...]] = (
    ("gruntylesne", "lesna"),
    ("terenykomunikacyjne", "droga"),
    ("gruntyzabudowaneizurbanizowane", "nieokreslona_zurbanizowana"),
    ("gruntyrolne", "nieokreslona_rolna"),
)

# Kogo wolno dobrac, gdy w segmencie docelowym brakuje transakcji.
# Kolejnosc ma znaczenie: schodzimy do coraz dalszych sasiadow.
FALLBACKS: Final[dict[Segment, tuple[Segment, ...]]] = {
    "mieszkaniowa_wielorodzinna": ("mieszkaniowa_jednorodzinna", "uslugowa_produkcyjna"),
    "mieszkaniowa_jednorodzinna": (
        "budowlana_wz",
        "mieszkaniowa_wielorodzinna",
        "uslugowa_produkcyjna",
    ),
    "budowlana_wz": ("mieszkaniowa_jednorodzinna", "uslugowa_produkcyjna"),
    "uslugowa_produkcyjna": ("mieszkaniowa_jednorodzinna", "budowlana_wz"),
    "rekreacyjna": ("mieszkaniowa_jednorodzinna", "rolna"),
    "rolna": ("lesna", "rekreacyjna"),
    "lesna": ("rolna",),
    "droga": ("rolna", "nieokreslona"),
    # Worek bez przeznaczenia: najpierw jego wlasne podzbiory, dopiero potem
    # segmenty z MPZP. Kolejnosc nie jest przypadkowa - dzialka bez wpisu
    # przypomina inne dzialki bez wpisu bardziej niz te z planem.
    "nieokreslona_zurbanizowana": ("nieokreslona", "mieszkaniowa_jednorodzinna"),
    "nieokreslona_rolna": ("nieokreslona", "rolna"),
    "nieokreslona": ("nieokreslona_zurbanizowana", "nieokreslona_rolna"),
}


def classify(przeznaczenie: str | None, sposob_uzyt: str | None = None) -> Segment:
    """Segment rynku dla pary (przeznaczenie w MPZP, sposob uzytkowania w ewidencji).

    Przeznaczenie bywa lista rozdzielona srednikiem, np.
    "budownictwoMieszkanioweJednorodzinne;terenZabudowyUslugowej".
    """
    text = (przeznaczenie or "").lower().replace(" ", "")
    if text and text not in {"brakmpzplubwz", "innyniewymieniony"}:
        for needle, segment in _RULES:
            if needle in text:
                return segment

    uzytek = (sposob_uzyt or "").lower().replace(" ", "")
    if uzytek:
        for needle, segment in _UZYTEK_RULES:
            if needle in uzytek:
                return segment

    return "nieokreslona"


def select_by_segment[T](
    items: Sequence[T],
    target: Segment,
    *,
    segment_of: Callable[[T], Segment],
    level_of: Callable[[T], str],
    min_total: int = 12,
    min_local: int = 5,
    local_levels: tuple[str, ...] = ("obreb", "gmina"),
) -> tuple[list[T], tuple[Segment, ...]]:
    """Dobor porownywalnych z segmentu, z kontrolowanym rozszerzaniem.

    Najpierw sam segment docelowy. Jesli za malo danych (globalnie albo lokalnie),
    dokladamy kolejne segmenty z FALLBACKS, jeden po drugim. Zwracamy takze liste
    faktycznie uzytych segmentow, zeby uzytkownik widzial, na czym stoi wycena.
    """
    used: list[Segment] = [target]
    selected = [item for item in items if segment_of(item) == target]

    def enough(chosen: list[T]) -> bool:
        if len(chosen) < min_total:
            return False
        local = sum(1 for item in chosen if level_of(item) in local_levels)
        return local >= min_local

    for candidate in FALLBACKS.get(target, ()):
        if enough(selected):
            break
        extra = [item for item in items if segment_of(item) == candidate]
        if extra:
            selected.extend(extra)
            used.append(candidate)

    if not selected:
        # Ostatnia deska ratunku: cokolwiek, ale wywolujacy dostanie informacje,
        # ze segment sie nie zgadza, i moze poszerzyc przedzial.
        return list(items), (target, "nieokreslona")

    return selected, tuple(used)


# ---------------------------------------------- segment z tresci ogloszenia

# Slowa, po ktorych portal daje sie zaklasyfikowac. Kolejnosc ma znaczenie:
# "dzialka rolno-budowlana" to dla kupujacego dzialka budowlana, wiec budowlane
# rozstrzyga przed rolnym.
_REGULY_OGLOSZENIA: Final[tuple[tuple[str, Segment], ...]] = (
    ("wielorodzinn", "mieszkaniowa_wielorodzinna"),
    ("budowlan", "mieszkaniowa_jednorodzinna"),
    ("pod zabudowe", "mieszkaniowa_jednorodzinna"),
    ("pod dom", "mieszkaniowa_jednorodzinna"),
    ("siedliskow", "mieszkaniowa_jednorodzinna"),
    ("uslugow", "uslugowa_produkcyjna"),
    ("przemyslow", "uslugowa_produkcyjna"),
    ("inwestycyjn", "uslugowa_produkcyjna"),
    ("magazynow", "uslugowa_produkcyjna"),
    ("rekreacyjn", "rekreacyjna"),
    ("letnisk", "rekreacyjna"),
    ("siedlisko", "mieszkaniowa_jednorodzinna"),
    ("gospodarstwo", "rolna"),
    ("roln", "rolna"),
    ("orn", "rolna"),
    ("lesn", "lesna"),
    ("las ", "lesna"),
)


def _bez_ogonkow(tekst: str) -> str:
    zamiana = str.maketrans("ąćęłńóśżźĄĆĘŁŃÓŚŻŹ", "acelnoszzACELNOSZZ")
    return tekst.translate(zamiana).lower()


def z_ogloszenia(przeznaczenie_raw: str | None, tytul: str | None = None) -> Segment | None:
    """Segment odczytany z tresci ogloszenia. None, gdy portal nic nie mowi.

    POWOD ISTNIENIA: pole przeznaczenie_raw z portali to nie klasyfikacja, tylko
    strzepy opisu. Na 723 ofertach najczestsze wartosci to "budowlana" (26 razy),
    "Planem Zagospodarowania" (17) i "mpzp" (4). Podanie tego wprost do classify()
    (ktory zna slownik RCN) wrzucalo 351 z 361 ofert do kubla "nieokreslona",
    a ten kubel w RCN to glownie tanie grunty rolne. Efekt: kazda oferta
    wygladala na 87% powyzej rynku, co bylo artefaktem, a nie obserwacja.

    None jest tu wazniejsze niz zgadywanie: oferta bez rozpoznanego przeznaczenia
    ma byc porownana do calego rynku gminy i tak opisana, a nie dopasowana
    do przypadkowego segmentu.
    """
    tekst = " ".join(_bez_ogonkow(t) for t in (przeznaczenie_raw or "", tytul or "") if t)
    if not tekst.strip():
        return None
    for fragment, segment in _REGULY_OGLOSZENIA:
        if fragment in tekst:
            return segment
    return None
