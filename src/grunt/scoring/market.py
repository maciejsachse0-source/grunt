"""Filar 6: dynamika rynku liczona z wlasnych transakcji RCN. Sekcja 5.3.6.

Dokument przewidywal tu GUS BDL i wlasne szeregi czasowe. Okazalo sie, ze
szeregi juz mamy: 104 tys. transakcji z lat 2023-2026 z data i TERYT-em gminy.
GUS bedzie potrzebny dopiero do plynnosci (transakcje na 1000 mieszkancow),
bo liczby ludnosci nie da sie wyprowadzic z RCN.

DWIE PULAPKI, KTORE TA IMPLEMENTACJA OMIJA

1. **Efekt skladu.** Mediana ceny za m2 w gminie potrafi spasc miedzy latami
   tylko dlatego, ze w drugim roku sprzedano wiecej gruntow rolnych. Dlatego
   dynamike liczymy OSOBNO w kazdym segmencie rynku, a dopiero potem usredniamy
   wazac liczba transakcji. To wersja indeksu o stalym koszyku, nie zmiana
   surowej mediany.
2. **Efekt skali.** Ceny za m2 sa najpierw normalizowane do dzialki 1000 m2
   (normalize_area), bo inaczej rok z przewaga malych dzialek wyglada na rok
   drozszy. Normalizacja dzieje sie po stronie wolajacego, tutaj przychodza juz
   mediany.

Wszystko to funkcje czyste: bez bazy, bez sieci, bez zegara. Dane zbiera
enrich/market.py.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

# Ponizej tylu transakcji w roku mediana segmentu jest szumem, a nie pomiarem.
# Piec bylo za malo: przy tym progu wychodzily gminy z dynamika -28% i +53%
# rocznie, czyli liczby, ktorych rynek gruntow nie robi.
MIN_OBS_ROK: Final = 10

# Roczna zmiana powyzej tego progu to prawie zawsze artefakt skladu albo
# pojedyncza duza transakcja, a nie rynek. Takie segmenty odrzucamy. Prog 0,60
# przepuszczal przypadki w rodzaju "uslugowa i produkcyjna w jednej gminie:
# -42% rocznie", gdzie w 2023 sprzedano dzialki w miescie, a w 2026 na obrzezach.
# 14 ze 158 zmierzonych zmian segmentowych przekraczalo 40%, wiec tam jest prog.
MAX_ROCZNA_ZMIANA: Final = 0.40

POZIOMY: Final = ("gmina", "powiat", "wojewodztwo")

# Ponizej tylu transakcji mediana lokalna nie jest mediana, tylko przypadkiem.
# Uzywamy jej wtedy jako tla, ale oznaczamy jako niewiarygodna.
MIN_OBS_MEDIANY: Final = 10

# Sufit indeksacji: gmina z dynamika +52% rocznie (a takie wyszly przy niskim
# progu) po trzech latach dawalaby mnoznik 3,5. Realny rynek gruntow tego nie
# robi, wiec indeksacje przycinamy.
MAX_INDEKSACJA: Final = 0.25

# Stala shrinkage'u: przy K transakcjach poziom lokalny wazy polowe. Model 1
# uzywa K=10 dla median cen; tutaj 30, bo dynamika to roznica dwoch median
# i dziedziczy blad obu.
K_SHRINKAGE: Final = 30


class MarketError(ValueError):
    pass


def cagr(wartosc_poczatkowa: float, wartosc_koncowa: float, lata: float) -> float:
    """Srednioroczna zmiana skladana. 100 -> 121 przez 2 lata to 0,10."""
    if wartosc_poczatkowa <= 0 or wartosc_koncowa <= 0:
        raise MarketError("ceny musza byc dodatnie")
    if lata <= 0:
        raise MarketError("okres musi byc dodatni")
    return float((wartosc_koncowa / wartosc_poczatkowa) ** (1.0 / lata) - 1.0)


@dataclass(frozen=True, slots=True)
class Dynamika:
    """Dynamika cen dla jednego obszaru, z informacja, skad sie wziela."""

    cagr: float
    poziom: str
    n_obs: int
    rok_od: int
    rok_do: int
    segmenty: dict[str, float] = field(default_factory=dict)
    # Udzial poziomow w wyniku po shrinkage'u. Pusty przed zmieszaniem.
    wagi_poziomow: dict[str, float] = field(default_factory=dict)

    @property
    def lata(self) -> int:
        return self.rok_do - self.rok_od

    def to_dict(self) -> dict[str, object]:
        return {
            "cagr": round(self.cagr, 4),
            "poziom": self.poziom,
            "n_obs": self.n_obs,
            "okres": f"{self.rok_od}-{self.rok_do}",
            "segmenty": {k: round(v, 4) for k, v in sorted(self.segmenty.items())},
            "wagi_poziomow": self.wagi_poziomow,
        }


def dynamika_z_median(
    mediany: Mapping[str, Mapping[int, tuple[float, int]]],
    *,
    poziom: str,
    min_obs_rok: int = MIN_OBS_ROK,
    max_roczna_zmiana: float = MAX_ROCZNA_ZMIANA,
) -> Dynamika | None:
    """Srednioroczna zmiana cen, liczona per segment i wazona liczba transakcji.

    mediany: segment -> rok -> (mediana znormalizowanej ceny za m2, liczba transakcji).
    None, gdy zaden segment nie ma dwoch lat z wystarczajaca liczba obserwacji.
    Brak wyniku jest tu poprawna odpowiedzia: filar zostanie niedostepny
    i wejdzie do renormalizacji wag, zamiast dostac wartosc srodkowa.
    """
    if poziom not in POZIOMY:
        raise MarketError(f"nieznany poziom: {poziom}")

    wklady: list[tuple[float, int]] = []
    per_segment: dict[str, float] = {}
    rok_min: int | None = None
    rok_max: int | None = None

    for segment, lata in mediany.items():
        uzyteczne = sorted(
            (rok, cena, n) for rok, (cena, n) in lata.items() if n >= min_obs_rok and cena > 0
        )
        if len(uzyteczne) < 2:
            continue

        (rok_od, cena_od, n_od) = uzyteczne[0]
        (rok_do, cena_do, n_do) = uzyteczne[-1]
        zmiana = cagr(cena_od, cena_do, rok_do - rok_od)
        if abs(zmiana) > max_roczna_zmiana:
            continue

        waga = min(n_od, n_do)
        wklady.append((zmiana, waga))
        per_segment[segment] = zmiana
        rok_min = rok_od if rok_min is None else min(rok_min, rok_od)
        rok_max = rok_do if rok_max is None else max(rok_max, rok_do)

    if not wklady or rok_min is None or rok_max is None:
        return None

    suma_wag = sum(waga for _, waga in wklady)
    srednia = sum(zmiana * waga for zmiana, waga in wklady) / suma_wag

    return Dynamika(
        cagr=srednia,
        poziom=poziom,
        n_obs=suma_wag,
        rok_od=rok_min,
        rok_do=rok_max,
        segmenty=per_segment,
    )


def shrinkage(kandydaci: Mapping[str, Dynamika | None], *, k: int = K_SHRINKAGE) -> Dynamika | None:
    """Zmieszanie poziomow jak w Modelu 1, z waga lambda = n / (n + k).

    Twardy wybor "gmina, jesli ma 20 transakcji, inaczej powiat" ma dwie wady:
    gmina z 21 transakcjami dostaje pelne zaufanie, a z 19 zerowe, i wynik skacze
    na progu. Shrinkage robi to plynnie: im mniej transakcji w gminie, tym
    mocniej jej dynamika sciaga sie do powiatu, a powiatu do wojewodztwa.

    Zwracana Dynamika ma cagr po zmieszaniu, a poziom, n_obs i segmenty
    z najbardziej lokalnego dostepnego zrodla. wagi_poziomow pokazuje, ile
    z wyniku pochodzi z ktorego poziomu.
    """
    dostepne: list[tuple[str, Dynamika]] = [
        (poziom, kandydat) for poziom in POZIOMY if (kandydat := kandydaci.get(poziom)) is not None
    ]
    if not dostepne:
        return None

    # Od najogolniejszego do najbardziej lokalnego: kazdy kolejny poziom
    # przyciaga wynik do siebie tym mocniej, im wiecej ma obserwacji.
    # Najogolniejszy poziom jest punktem wyjscia, wiec startuje z waga 1,0,
    # a kazdy nastepny zabiera pozostalym dokladnie lambda.
    od_ogolu = list(reversed(dostepne))
    wartosc = od_ogolu[0][1].cagr
    wagi: dict[str, float] = {od_ogolu[0][0]: 1.0}

    for poziom, dynamika in od_ogolu[1:]:
        lam = dynamika.n_obs / (dynamika.n_obs + k)
        wartosc = lam * dynamika.cagr + (1 - lam) * wartosc
        for wczesniejszy in wagi:
            wagi[wczesniejszy] *= 1 - lam
        wagi[poziom] = lam

    najlokalniejszy = dostepne[0][1]
    return Dynamika(
        cagr=wartosc,
        poziom=najlokalniejszy.poziom,
        n_obs=najlokalniejszy.n_obs,
        rok_od=najlokalniejszy.rok_od,
        rok_do=najlokalniejszy.rok_do,
        segmenty=najlokalniejszy.segmenty,
        wagi_poziomow={p: round(w, 3) for p, w in wagi.items()},
    )


# --------------------------------------------------- porownanie z rynkiem lokalnym


def indeksuj_do_dzis(cena: float, cagr: float | None, lata: float) -> float:
    """Cena transakcji sprzed `lata` przeliczona na dzisiejszy poziom cen.

    Mediana z ostatnich dwoch lat bez indeksacji zaniza sie o tyle, ile rynek
    urosl w tym czasie: przy zmierzonych 8-10% rocznie to kilkanascie procent
    bledu wbudowanego w kazde porownanie. Dynamika spoza [-25%, +25%] rocznie
    to artefakt malej proby, wiec ja przycinamy.
    """
    if cena <= 0:
        raise MarketError("cena musi byc dodatnia")
    if lata < 0:
        raise MarketError("liczba lat nie moze byc ujemna")
    tempo = 0.08 if cagr is None else max(-MAX_INDEKSACJA, min(MAX_INDEKSACJA, cagr))
    return float(cena * (1.0 + tempo) ** lata)


def odchylenie_od_mediany(cena_norm: float, mediana_norm: float | None) -> float | None:
    """O ile procent oferta jest drozsza (+) albo tansza (-) od mediany rynku.

    None, gdy mediany nie ma. Zero znaczyloby "dokladnie w medianie", a to co
    innego niz "nie wiadomo" (zasada z CLAUDE.md).
    """
    if mediana_norm is None or mediana_norm <= 0 or cena_norm <= 0:
        return None
    return cena_norm / mediana_norm - 1.0


@dataclass(frozen=True, slots=True)
class Mediana:
    """Mediana rynku lokalnego dla jednego segmentu i jednego obszaru."""

    poziom: str
    teryt: str
    segment: str
    mediana_norm: float
    p25_norm: float
    p75_norm: float
    n: int

    @property
    def wiarygodna(self) -> bool:
        return self.n >= MIN_OBS_MEDIANY

    @property
    def rozrzut(self) -> float:
        """Rozstep miedzykwartylowy wzgledem mediany. Miara, jak ostry jest rynek."""
        return (self.p75_norm - self.p25_norm) / self.mediana_norm if self.mediana_norm else 0.0


def wybierz_mediane(
    kandydatki: Mapping[str, Mediana | None], *, min_obs: int = MIN_OBS_MEDIANY
) -> Mediana | None:
    """Najbardziej lokalna mediana, ktora ma dosc obserwacji.

    Tu, inaczej niz przy dynamice, NIE mieszamy poziomow. Uzytkownik czyta
    "mediana w gminie X, n=142" i musi to byc prawdziwa mediana tej gminy,
    a nie liczba powstala ze sklejenia gminy z powiatem. Gdy gmina nie ma dosc
    transakcji, pokazujemy powiat i mowimy o tym wprost.
    """
    for poziom in POZIOMY:
        kandydatka = kandydatki.get(poziom)
        if kandydatka is not None and kandydatka.n >= min_obs:
            return kandydatka
    dostepne = [m for m in kandydatki.values() if m is not None]
    return max(dostepne, key=lambda m: m.n) if dostepne else None


# ------------------------------------------------- trend szeregu kwartalnego

# Ponizej tylu pelnych kwartalow nie podajemy trendu wcale. Nie chodzi o
# estetyke: przy czterech punktach nachylenie prostej mowi wiecej o tym, ktory
# kwartal wypadl skrajnie, niz o rynku.
MIN_KWARTALOW_TRENDU: Final = 6

# Drugi prog, na liczbe transakcji w typowym kwartale. Sam warunek na liczbe
# kwartalow nie wystarcza: Wejherowo (miasto) ma 11 kwartalow, ale po 5-15
# transakcji kazdy, czyli szereg jedenastu przypadkow. Mediana kwartalu musi
# miec tyle obserwacji, ile MIN_OBS_ROK wymaga od mediany rocznej.
MIN_MEDIANA_N_TRENDU: Final = MIN_OBS_ROK

# Trzeci prog, na dlugosc okna. Roczna zmiana wyliczona z pieciu kwartalow to
# ekstrapolacja, nie pomiar: gmina Kobylnica ma szesc kwartalow z lat 2025-2026,
# w tym jeden ze skokiem mediany, i wychodzilo z tego "+102% rocznie". Dwa lata
# to minimum, przy ktorym roczne tempo jest w ogole obserwowane, a nie zgadywane.
MIN_LATA_TRENDU: Final = 2.0


def _mediana(wartosci: list[float]) -> float:
    posortowane = sorted(wartosci)
    srodek = len(posortowane) // 2
    if len(posortowane) % 2:
        return posortowane[srodek]
    return (posortowane[srodek - 1] + posortowane[srodek]) / 2.0


def trend_szeregu(
    punkty: Sequence[tuple[float, float, int]],
    *,
    min_punktow: int = MIN_KWARTALOW_TRENDU,
    min_mediana_n: int = MIN_MEDIANA_N_TRENDU,
    min_lata: float = MIN_LATA_TRENDU,
) -> float | None:
    """Sredni roczny przyrost cen w szeregu, odporny na pojedynczy dziki kwartal.

    punkty: (lata od poczatku szeregu, mediana ceny za m2, liczba transakcji).

    Estymator to Theil-Sen po logarytmie ceny: mediana nachylen wszystkich par
    punktow. Logarytm, bo interesuje nas zmiana procentowa. Mediana nachylen,
    bo srednia (zwykla regresja) daje pojedynczemu skrajnemu punktowi na brzegu
    szeregu wplyw, ktorego on nie zasluguje.

    DLACZEGO NIE ROZNICA KONCOW ANI ZWYKLA REGRESJA. Gmina Wejherowo (miasto):
    pierwszy kwartal wypadl na 10 zl/m2 przy pieciu transakcjach, ostatni na 621.
    Iloraz koncow dawal "+295% rocznie", regresja wazona "+91%", a szereg na oko
    rosnie kilkanascie procent. Na poziomie powiatu ten problem byl niewidoczny,
    bo kwartal mial 300 transakcji; na poziomie gminy miewa piec.

    None, gdy pelnych kwartalow jest za malo, gdy typowy kwartal ma za malo
    transakcji, gdy szereg jest krotszy niz min_lata albo gdy wszystkie punkty
    sa z jednej daty. Brak trendu to poprawna odpowiedz, zero byloby falszywa.
    """
    dane = [(x, math.log(y), n) for x, y, n in punkty if y > 0 and n > 0]
    if len(dane) < min_punktow:
        return None
    if _mediana([float(n) for _, _, n in dane]) < min_mediana_n:
        return None
    if max(x for x, _, _ in dane) - min(x for x, _, _ in dane) < min_lata:
        return None

    nachylenia = [
        (y2 - y1) / (x2 - x1)
        for i, (x1, y1, _) in enumerate(dane)
        for x2, y2, _ in dane[i + 1 :]
        if x2 != x1
    ]
    if not nachylenia:
        return None

    return float(math.exp(_mediana(nachylenia)) - 1.0)
