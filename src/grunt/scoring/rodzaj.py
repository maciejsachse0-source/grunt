"""Rodzaj dzialki w czterech kubelkach, ktorymi mysli kupujacy.

CZTERY, A NIE JEDENASCIE. segments.py dzieli rynek na jedenascie segmentow
slownikiem RCN, bo tego wymaga wycena: mediana ceny liczy sie osobno dla drogi
wewnetrznej i dla dzialki pod blok. Uzytkownik filtruje inaczej. On pyta
"pokaz mi grunty przemyslowe", nie "pokaz mi terenZabudowyUslugowej". Dlatego
ten modul jest osobno, a nie jako mapowanie Segment -> Rodzaj:

    uslugowa_produkcyjna  (jeden segment RCN)
        -> uslugowa    dzialka pod sklep, biuro, warsztat
        -> przemyslowa dzialka pod hale, magazyn, produkcje

RCN sklada te dwie w jedna kategorie, bo dla mediany cenowej roznica jest
niewielka. Dla kupujacego to dwie rozne inwestycje, wiec tutaj sa rozdzielone
wlasnymi regulami, a nie odziedziczone po segmencie.

CZEGO TU NIE MA. Rolna, rekreacyjna, droga i siedlisko zostaja bez rodzaju
(None). To nie jest przeoczenie: uzytkownik wskazal cztery kategorie, a wpisanie
pola uprawnego do kubla "mieszkaniowa" tylko dlatego, ze nie ma lepszego,
bylo by zgadywaniem. None znaczy "nie wiemy albo to nic z tych czterech"
i tak ma byc pokazane w interfejsie (regula NULL to NULL z CLAUDE.md).

DWA ZRODLA, W TEJ KOLEJNOSCI

1. strefa planu ogolnego (le.plan_strefa, prosto z APP GUGiK). Strefa mowi,
   co na tej dzialce wolno postawic, i jest wiazaca. Ma pierwszenstwo.
2. tresc ogloszenia (przeznaczenie_raw, w ostatecznosci tytul). Sprzedajacy
   opisuje, co sprzedaje, ale bywa, ze zycznie.

Zrodlo wraca razem z wynikiem, zeby interfejs mogl pokazac, skad to wie.
Pomiar na bazie 25.08.2026: przeznaczenie_raw rozpoznaje rodzaj dla ok. 1050
z 7300 aktywnych ofert, plan ogolny dla 50. Reszta zostaje bez rodzaju,
i to jest uczciwy stan wiedzy, a nie brak w kodzie.

Funkcje czyste: bez I/O, bez bazy, bez zegara.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

Rodzaj = Literal["mieszkaniowa", "uslugowa", "przemyslowa", "lesna"]
Zrodlo = Literal["plan_ogolny", "ogloszenie"]

RODZAJE: Final[tuple[Rodzaj, ...]] = (
    "mieszkaniowa",
    "uslugowa",
    "przemyslowa",
    "lesna",
)

# Strefy planu ogolnego (rozporzadzenie o planie ogolnym gminy). Wypisane sa
# tylko te, ktore mapuja sie na czterech kubelkach jednoznacznie. SR (produkcja
# rolnicza), SN (zielen i rekreacja), SI, SC, SG, SO, SK swiadomie nie maja
# odpowiednika: to nie sa dzialki z tej listy.
STREFY: Final[dict[str, Rodzaj]] = {
    "SW": "mieszkaniowa",  # wielofunkcyjna z zabudowa mieszkaniowa wielorodzinna
    "SJ": "mieszkaniowa",  # wielofunkcyjna z zabudowa mieszkaniowa jednorodzinna
    "SZ": "mieszkaniowa",  # wielofunkcyjna z zabudowa zagrodowa
    "SU": "uslugowa",  # uslugowa
    "SH": "uslugowa",  # handlu wielkopowierzchniowego
    "SP": "przemyslowa",  # gospodarcza, czyli produkcja i magazyny
}

# Kolejnosc krotki to priorytet przy remisie, gdy dwa slowa stoja w tym samym
# miejscu tekstu. Normalnie rozstrzyga POZYCJA slowa w zdaniu, patrz _dopasuj.
_REGULY: Final[tuple[tuple[re.Pattern[str], Rodzaj], ...]] = (
    (
        re.compile(r"przemyslow|produkcyj|magazyn|logistyczn|skladow"),
        "przemyslowa",
    ),
    (
        re.compile(r"uslugow|handlow|biurow|komercyjn|gastronomiczn|hotelow"),
        "uslugowa",
    ),
    (
        re.compile(
            r"mieszkaniow|budowlan|jednorodzinn|wielorodzinn"
            r"|siedliskow|zagrodow|pod dom"
            # "pod zabudowe" bez dopowiedzenia znaczy dom, ale "pod zabudowe
            # uslugowa" znaczy uslugi, a stalo w zdaniu wczesniej niz slowo
            # "uslugowa" i wygrywalo pozycja. Stad wyjatek na nastepne slowo.
            r"|pod zabudowe(?!\s+(?:uslugow|przemyslow|produkcyj|magazynow|handlow))"
            # Symbole MPZP: "oznaczona symbolem MN1", "43 U/MN, MW". Tylko te
            # dwa, bo reszta jest nie do odroznienia od zwyklego tekstu: "ZL"
            # zlapaloby kazda cene ("220 000 zl"), "U" polski przyimek,
            # a "P" numer punktu. Pomiar na 1 627 ofertach bez rodzaju:
            # MN i MW daja 39 trafien, ZL 115 falszywych.
            r"|\bmn\d*\b|\bmw\d*\b"
        ),
        "mieszkaniowa",
    ),
    # Krotkie "las" i "lesn" celowo z koncowka i granica slowa: bez tego
    # "Lesniewo", "Klasa" i ulica "Lesna" w adresie robily z dzialki budowlanej
    # dzialke lesna. Pomiar: 4 trafienia w przeznaczeniach, 5 pulapek w tytulach.
    (
        re.compile(r"\blesn[aeoy]\b|\blesn(?:ej|ym|ego|ych)\b|zalesion"),
        "lesna",
    ),
)

# Rzeczowniki, po ktorych w tytule ogloszenia idzie opis samej dzialki.
# Tytul poza tym oknem to adres, a w adresach sa ulice Lesne i wsie Lesniewo.
_RZECZOWNIK: Final[re.Pattern[str]] = re.compile(
    r"dzialk\w*|dzialek|grunt\w*|teren\w*|nieruchomosc\w*|parcel\w*"
)
OKNO_TYTULU: Final[int] = 40

# Gdzie konczy sie opis dzialki, a zaczyna adres. Przecinek albo pierwsza cyfra:
# "Dzialka na sprzedaz, 570 m2 Smolno, Lesna" ma ulice Lesna tuz za metrazem,
# wiec bez tego ciecia kazda dzialka przy ulicy Lesnej bylaby dzialka lesna.
_KONIEC_OPISU: Final[re.Pattern[str]] = re.compile(r"[,;|]|\d")


@dataclass(frozen=True, slots=True)
class WynikRodzaju:
    """Rodzaj razem ze zrodlem. Sam rodzaj bez zrodla jest nie do sprawdzenia."""

    rodzaj: Rodzaj | None
    zrodlo: Zrodlo | None

    def to_dict(self) -> dict[str, str | None]:
        return {"rodzaj": self.rodzaj, "zrodlo": self.zrodlo}


def _bez_ogonkow(tekst: str) -> str:
    zamiana = str.maketrans("ąćęłńóśżźĄĆĘŁŃÓŚŻŹ", "acelnoszzACELNOSZZ")
    return tekst.translate(zamiana).lower()


def _dopasuj(tekst: str) -> Rodzaj | None:
    """Pierwsze slowo o przeznaczeniu, ktore pada w tekscie.

    DLACZEGO POZYCJA, A NIE STALY PRIORYTET. Zapis z planu brzmi zwykle
    "teren zabudowy mieszkaniowej jednorodzinnej z uslugami": obie kategorie
    sa w zdaniu, ale wiodaca jest ta wymieniona pierwsza. Staly priorytet
    ("uslugowa zawsze wygrywa") przerobilby kazda dzialke pod dom z gabinetem
    na dzialke uslugowa.
    """
    najlepsze: tuple[int, int] | None = None
    wynik: Rodzaj | None = None
    for priorytet, (wzorzec, rodzaj) in enumerate(_REGULY):
        trafienie = wzorzec.search(tekst)
        if trafienie is None:
            continue
        klucz = (trafienie.start(), priorytet)
        if najlepsze is None or klucz < najlepsze:
            najlepsze, wynik = klucz, rodzaj
    return wynik


def ze_strefy(plan_strefa: str | None) -> Rodzaj | None:
    """Rodzaj ze strefy planu ogolnego. None dla stref spoza czterech kategorii."""
    if not plan_strefa:
        return None
    return STREFY.get(plan_strefa.strip().upper())


def z_przeznaczenia(przeznaczenie_raw: str | None) -> Rodzaj | None:
    """Rodzaj z pola przeznaczenia ogloszenia.

    To pole niesie albo kod portalu ("budowlana", "przemyslowa" z Otodomu),
    albo zdanie o planie wyciete z opisu, wiec szukamy w calej tresci.
    """
    if not przeznaczenie_raw:
        return None
    return _dopasuj(_bez_ogonkow(przeznaczenie_raw))


def z_tytulu(tytul: str | None) -> Rodzaj | None:
    """Rodzaj z tytulu, ale tylko z okna tuz po slowie "dzialka".

    Tytul to w wiekszosci adres ("Dzialka na sprzedaz, 1508 m2 Smoldzinski Las"),
    wiec szukanie po calosci mylilo nazwy miejscowosci z przeznaczeniem.
    Okno konczy sie na pierwszym przecinku albo pierwszej cyfrze, bo tam
    w tytulach z portali konczy sie opis, a zaczyna metraz i adres.
    """
    if not tytul:
        return None
    tekst = _bez_ogonkow(tytul)
    for trafienie in _RZECZOWNIK.finditer(tekst):
        okno = tekst[trafienie.end() : trafienie.end() + OKNO_TYTULU]
        rodzaj = _dopasuj(_KONIEC_OPISU.split(okno)[0])
        if rodzaj is not None:
            return rodzaj
    return None


def okresl(
    *,
    plan_strefa: str | None = None,
    przeznaczenie_raw: str | None = None,
    tytul: str | None = None,
) -> WynikRodzaju:
    """Rodzaj dzialki z najmocniejszego dostepnego zrodla.

    Plan ogolny przed ogloszeniem, bo strefa mowi, co WOLNO na dzialce
    postawic, a ogloszenie tylko, co sprzedajacy chcialby sprzedac.
    """
    ze_stref = ze_strefy(plan_strefa)
    if ze_stref is not None:
        return WynikRodzaju(ze_stref, "plan_ogolny")

    z_ogloszenia = z_przeznaczenia(przeznaczenie_raw) or z_tytulu(tytul)
    if z_ogloszenia is not None:
        return WynikRodzaju(z_ogloszenia, "ogloszenie")

    return WynikRodzaju(None, None)
