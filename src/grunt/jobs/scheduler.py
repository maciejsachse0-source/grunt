"""Harmonogram: co i jak czesto ma sie samo uruchamiac.

Decyzja "co jest do zaplanowania" to funkcja czysta (do_zaplanowania), zeby dalo
sie ja przetestowac bez bazy i bez czekania na zegar. Zapis do kolejki jest
osobno, w zaplanuj().

Interwaly wynikaja z tego, jak szybko zmieniaja sie dane, a nie z tego, jak
czesto da sie odpytac:

* portale: nowa oferta dzialki pojawia sie w skali godzin, nie minut, a strategia
  DIFF i tak pobiera detale tylko dla zmienionych. 6 godzin to cztery przebiegi
  na dobe przy zerowym ryzyku, ze ktos uzna nas za natretnych;
* wzbogacanie: jedna oferta to ok. 20 zapytan do uslug publicznych, wiec chodzi
  czesto i malymi porcjami, zamiast raz na dobe zalac GUGiK setkami zapytan;
* scoring i deduplikacja: to tylko liczenie na wlasnych danych, ale bez sensu
  jest je uruchamiac czesciej niz przybywa danych;
* alerty co godzine: scraping chodzi co szesc godzin, ale wzbogacanie i scoring
  koncza sie pozniej, wiec oferta staje sie warta alertu dopiero po nich;
* watchdog raz na dobe, bo alarm "portal ucichl" ma sens dopiero po dniu ciszy;
* dynamika rynku i kalibracja raz na tydzien: to pomiary na calej bazie,
  a ich wynik zmienia sie dopiero wtedy, gdy przybedzie ofert albo transakcji.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy.orm import Session

from grunt.jobs import queue


@dataclass(frozen=True, slots=True)
class Zadanie:
    kind: str
    interwal: dt.timedelta
    opis: str
    payload: dict[str, Any] = field(default_factory=dict)


HARMONOGRAM: Final[tuple[Zadanie, ...]] = (
    Zadanie(
        kind="scrape",
        interwal=dt.timedelta(hours=6),
        opis="przebieg DIFF po wlaczonych portalach",
    ),
    Zadanie(
        kind="enrich",
        interwal=dt.timedelta(hours=1),
        # Porcja urosla z 20 do 60 25.08.2026, gdy dojscie Gratki i Otodomu
        # podnioslo baze z 723 do ponad 7 000 ofert. Przy 20 na godzine samo
        # nadgonienie zaleglosci zajeloby ponad dwa tygodnie, czyli scoring
        # opisywalby rynek sprzed dwoch tygodni.
        # Skad akurat 60: jedna oferta to ok. 20 zapytan i ok. 12 sekund, wiec
        # 60 ofert zajmuje ok. 12 minut z godziny i daje 1 200 zapytan na
        # godzine do uslug GUGiK, czyli srednio jedno na trzy sekundy. To nadal
        # jest ruch, ktorego nie widac w ich statystykach, a zaleglosc schodzi
        # w piec dni zamiast w pietnascie.
        opis="wzbogacenie kolejnej porcji ofert danymi publicznymi",
        payload={"limit": 60},
    ),
    Zadanie(
        kind="score",
        interwal=dt.timedelta(hours=3),
        opis="przeliczenie score'u i deal score'u",
        payload={"limit": 500},
    ),
    Zadanie(
        kind="dedup",
        interwal=dt.timedelta(hours=12),
        opis="deduplikacja cross-portal",
    ),
    Zadanie(
        kind="kategorie",
        # Rodzaj i gmina licza sie z tego, co juz jest w bazie: zero zapytan
        # do uslug zewnetrznych, kilka sekund na 7 tysiacach ofert. Interwal
        # wynika wiec nie z kosztu, tylko z tego, kiedy zmienia sie wejscie:
        # po scrapingu (nowe oferty) i po wzbogaceniu (strefa planu ogolnego).
        interwal=dt.timedelta(hours=3),
        opis="rodzaj dzialki i gmina dla kazdej aktywnej oferty",
    ),
    Zadanie(
        kind="alerty",
        interwal=dt.timedelta(hours=1),
        opis="powiadomienia z zapisanych filtrow",
    ),
    Zadanie(
        kind="rynek",
        interwal=dt.timedelta(days=7),
        opis="dynamika i mediany cen per obszar, przypisanie ofert do rynku",
        payload={"okres_lat": 4},
    ),
    Zadanie(
        kind="kalibracja",
        interwal=dt.timedelta(days=7),
        opis="spread, elastycznosc b1, stabilnosc wag, dyskryminacja",
        payload={"limit": 500},
    ),
    Zadanie(
        kind="watchdog",
        interwal=dt.timedelta(hours=24),
        opis="sprawdzenie, czy portal nie ucichl",
    ),
    Zadanie(
        kind="sprzatanie",
        interwal=dt.timedelta(hours=24),
        opis="usuniecie historii zadan starszej niz 30 dni",
        payload={"starsze_niz_dni": 30},
    ),
)


def do_zaplanowania(
    teraz: dt.datetime,
    ostatnie_udane: Mapping[str, dt.datetime],
    w_kolejce: Iterable[str] = (),
    harmonogram: Iterable[Zadanie] = HARMONOGRAM,
) -> list[Zadanie]:
    """Zadania, ktorym uplynal interwal i ktorych nie ma juz w kolejce.

    Zadanie nigdy jeszcze nie uruchomione jest wymagalne od razu: pierwszy start
    workera ma zrobic wszystko, a nie czekac dobe na watchdoga.
    """
    czekajace = set(w_kolejce)
    wynik: list[Zadanie] = []
    for zadanie in harmonogram:
        if zadanie.kind in czekajace:
            continue
        ostatnie = ostatnie_udane.get(zadanie.kind)
        if ostatnie is None or teraz - ostatnie >= zadanie.interwal:
            wynik.append(zadanie)
    return wynik


def zaplanuj(session: Session, *, teraz: dt.datetime | None = None) -> list[str]:
    """Dopisanie do kolejki tego, co jest wymagalne. Zwraca rodzaje zadan."""
    teraz = teraz or dt.datetime.now(dt.UTC)
    zadania = do_zaplanowania(
        teraz,
        queue.ostatnie_udane(session),
        queue.w_kolejce(session),
    )
    for zadanie in zadania:
        queue.enqueue(session, zadanie.kind, zadanie.payload)
    return [zadanie.kind for zadanie in zadania]


def opis_harmonogramu() -> list[dict[str, Any]]:
    return [
        {
            "kind": zadanie.kind,
            "co": zadanie.opis,
            "co_ile_godzin": zadanie.interwal.total_seconds() / 3600,
            "payload": zadanie.payload,
        }
        for zadanie in HARMONOGRAM
    ]
