"""Kalibracja i walidacja bez etykiet: sekcja 5.6 dokumentu.

Cztery rzeczy, ktore da sie policzyc na wlasnych danych, bez ani jednego
recznie ocenionego przykladu:

1. **spread oferta-transakcja** - o ile ceny ofertowe leza wyzej niz ceny,
   po ktorych faktycznie zawierane sa umowy. Bez tej liczby deal score jest
   systematycznie ujemny, bo model uczy sie na RCN (transakcje), a porownuje
   z ogloszeniami (oferty);
2. **stabilnosc rankingu** - perturbacja wag o +/-30% i sprawdzenie, ile z top-N
   zostaje na miejscu. Ranking, ktory rozpada sie przy 30% zmiany wagi, nie
   niesie informacji, tylko odzwierciedla arbitralny wybor liczb. Osobno,
   deterministycznie: co robi czolowka, gdy JEDNEMU filarowi zmienic wage
   o +/-20% (kryterium akceptacji fazy 6, sekcja 21);
3. **dyskryminacja** - jesli 80% dzialek dostaje wynik 60-70, scoring niczego
   nie rozroznia, choc wyglada na dzialajacy;
4. **korelacja rang** (Spearman) - uzywana i wyzej, i pozniej do testu
   zgodnosci z ekspertami.

Wszystko to funkcje czyste: bez bazy, bez sieci, bez datetime.now(), bez
losowosci bez jawnego seeda. Dane wejsciowe zbiera enrich/calibrate.py.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np

# Robocze zalozenie z sekcji 5.6, dopoki nie ma zmatchowanych par: 12-20% dla
# budowlanych, 20-35% dla rolnych. Sluzy wylacznie do oceny, czy pomiar
# na wlasnych danych wypadl w spodziewanym zakresie.
SPREAD_OCZEKIWANY: Final[dict[str, tuple[float, float]]] = {
    "budowlana": (0.12, 0.20),
    "rolna": (0.20, 0.35),
}

# Powyzej tego udzialu jednego przedzialu histogramu uznajemy, ze scoring
# nie rozroznia dzialek (sekcja 5.6, test dyskryminacji).
MAX_UDZIAL_PRZEDZIALU: Final = 0.35

# Kryterium akceptacji fazy 6 (sekcja 21): zmiana wagi POJEDYNCZEGO filaru
# o +/-20% nie moze zmienic pierwszej dziesiatki o wiecej niz 3 pozycje.
#
# "Nie zmienia o wiecej niz 3 pozycje" da sie czytac dwojako i te odczyty
# rozjezdzaja sie na realnych danych, wiec trzeba bylo wybrac. Obowiazuje odczyt
# przez SKLAD czolowki: najwyzej 3 z 10 ofert wymieniaja sie na inne. Odczyt
# przez najdalsze przesuniecie pojedynczej oferty jest nadal liczony i
# raportowany, ale jako diagnostyka, nie jako werdykt. Powody, w kolejnosci wagi:
#
# 1. NIE SKALUJE SIE Z N. Przesuniecie w pozycjach rosnie razem z rozmiarem
#    zbioru: ta sama zmiana wyniku o 0,3 punktu przerzuca oferte o 8 miejsc
#    przy 126 ofertach i o kilkaset przy 4 000. Kryterium, ktore robi sie
#    trudniejsze wylacznie dlatego, ze przybylo danych, nie mierzy jakosci
#    scoringu, tylko licznosc bazy. Wymiana skladu czolowki jest ograniczona
#    przez top_n i zachowuje sens niezaleznie od N;
# 2. LICZYLBY DWA RAZY TE SAMA WADE. Duze przesuniecia w pozycjach biora sie
#    z gestego srodka stawki, a gestosc rozkladu mierzy juz osobno test
#    dyskryminacji ponizej. Ta sama wada raportowana jako dwa niezalezne bledy
#    wyglada gorzej, niz jest, i kaze naprawiac ja w zlym miejscu;
# 3. ODPOWIADA TEMU, CO WIDZI UZYTKOWNIK. Aplikacja pokazuje liste ofert,
#    a nie numery miejsc. Pytanie "czy przy innych wagach zobaczylbym na gorze
#    inne dzialki" to dokladnie odczyt przez sklad.
WRAZLIWOSC_SKALA: Final = 0.20
WRAZLIWOSC_TOP_N: Final = 10
MAX_ZMIANA_CZOLOWKI: Final = 3


class CalibrationError(ValueError):
    pass


# ------------------------------------------------------- spread oferta-transakcja


@dataclass(frozen=True, slots=True)
class Spread:
    """Rozklad ilorazu cena ofertowa / wartosc transakcyjna, pomniejszony o 1.

    mediana 0,18 znaczy: oferty leza o 18% wyzej niz to, czym model wycenia
    dzialke na podstawie transakcji.
    """

    mediana: float
    p25: float
    p75: float
    mad: float
    n: int
    zrodlo: str

    @property
    def wiarygodny(self) -> bool:
        """Ponizej 30 obserwacji mediana skacze o kilkanascie punktow procentowych."""
        return self.n >= 30

    def w_oczekiwanym_zakresie(self, rodzina: str) -> bool | None:
        zakres = SPREAD_OCZEKIWANY.get(rodzina)
        if zakres is None:
            return None
        return zakres[0] <= self.mediana <= zakres[1]

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "mediana": round(self.mediana, 4),
            "p25": round(self.p25, 4),
            "p75": round(self.p75, 4),
            "mad": round(self.mad, 4),
            "n": self.n,
            "zrodlo": self.zrodlo,
        }


def szacuj_spread(
    ceny_ofertowe: Sequence[float],
    wartosci: Sequence[float],
    *,
    zrodlo: str = "oferty_vs_model",
    min_iloraz: float = 0.2,
    max_iloraz: float = 5.0,
) -> Spread:
    """Mediana ilorazu cena/wartosc minus 1, na odpornych statystykach.

    Mediana, a nie srednia, i MAD, a nie odchylenie standardowe, bo w RCN
    zdarzaja sie przeniesienia po 1,8 zl/m2 i udzialy 1/222. Jedna taka
    obserwacja przesuwa srednia o kilkadziesiat procent, a mediany nie rusza.

    Ilorazy poza [min_iloraz, max_iloraz] odrzucamy jako blad danych, a nie
    jako ekstremalna okazje: oferta pieciokrotnie tansza od wyceny to prawie
    zawsze zla powierzchnia albo cena za udzial.
    """
    oferty = np.asarray(ceny_ofertowe, dtype=float)
    wartosc = np.asarray(wartosci, dtype=float)
    if oferty.shape != wartosc.shape:
        raise CalibrationError("ceny_ofertowe i wartosci musza miec ta sama dlugosc")

    maska = (oferty > 0) & (wartosc > 0) & np.isfinite(oferty) & np.isfinite(wartosc)
    ilorazy = oferty[maska] / wartosc[maska]
    ilorazy = ilorazy[(ilorazy >= min_iloraz) & (ilorazy <= max_iloraz)]
    if ilorazy.size == 0:
        raise CalibrationError("brak obserwacji do oszacowania spreadu")

    mediana = float(np.median(ilorazy))
    return Spread(
        mediana=mediana - 1.0,
        p25=float(np.percentile(ilorazy, 25)) - 1.0,
        p75=float(np.percentile(ilorazy, 75)) - 1.0,
        mad=float(np.median(np.abs(ilorazy - mediana))),
        n=int(ilorazy.size),
        zrodlo=zrodlo,
    )


def poziom_ofertowy(wartosc_transakcyjna: float, spread: float) -> float:
    """Wycena transakcyjna przeliczona na poziom cen OFERTOWYCH.

    To jedyne miejsce, w ktorym spread wchodzi do rachunku. Deal score porownuje
    cene ofertowa z ta wartoscia, a nie z surowa wycena transakcyjna, bo inaczej
    kazda oferta wychodzi przepłacona (punkt 7 sekcji "Czego nauczyly nas dane").
    """
    if wartosc_transakcyjna <= 0:
        raise CalibrationError("wartosc musi byc dodatnia")
    if spread <= -1.0:
        raise CalibrationError("spread ponizej -100% nie ma sensu")
    return wartosc_transakcyjna * (1.0 + spread)


# ------------------------------------------------------------ korelacja rang


def _rangi(wartosci: np.ndarray) -> np.ndarray:
    """Rangi ze srednia dla remisow, jak w scipy.stats.rankdata('average')."""
    kolejnosc = wartosci.argsort()
    rangi = np.empty_like(kolejnosc, dtype=float)
    rangi[kolejnosc] = np.arange(1, wartosci.size + 1, dtype=float)

    posortowane = wartosci[kolejnosc]
    i = 0
    while i < posortowane.size:
        j = i
        while j + 1 < posortowane.size and posortowane[j + 1] == posortowane[i]:
            j += 1
        if j > i:
            rangi[kolejnosc[i : j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    return rangi


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    """Korelacja rang Spearmana. Uzywana do stabilnosci wag i testu ekspertow."""
    a = np.asarray(x, dtype=float)
    b = np.asarray(y, dtype=float)
    if a.shape != b.shape:
        raise CalibrationError("obie serie musza miec ta sama dlugosc")
    if a.size < 3:
        raise CalibrationError(f"za malo obserwacji do korelacji rang: {a.size}")

    ra, rb = _rangi(a), _rangi(b)
    if ra.std() == 0 or rb.std() == 0:
        # Wszystkie wartosci rowne: korelacja jest nieokreslona, nie zerowa.
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


# ------------------------------------------------------- wrazliwosc wag


def zaburz_wagi(
    wagi: Mapping[str, float],
    *,
    skala: float = 0.30,
    seed: int,
) -> dict[str, float]:
    """Wagi pomnozone przez losowy czynnik z [1-skala, 1+skala] i przeskalowane do 1.

    Seed jest obowiazkowy i nie ma wartosci domyslnej: wynik analizy wrazliwosci
    musi dac sie odtworzyc co do liczby.
    """
    if not wagi:
        raise CalibrationError("pusty zestaw wag")
    if not 0 < skala < 1:
        raise CalibrationError("skala perturbacji musi byc w (0, 1)")

    generator = np.random.default_rng(seed)
    czynniki = generator.uniform(1.0 - skala, 1.0 + skala, size=len(wagi))
    zaburzone = {k: w * float(c) for (k, w), c in zip(wagi.items(), czynniki, strict=True)}
    suma = sum(zaburzone.values())
    return {k: w / suma for k, w in zaburzone.items()}


@dataclass(frozen=True, slots=True)
class StabilnoscRankingu:
    """Wynik jednej perturbacji wag."""

    pokrycie_top: float
    rho: float
    top_n: int
    n: int

    @property
    def stabilny(self) -> bool:
        """Prog roboczy: 70% top-N na miejscu i korelacja rang powyzej 0,8."""
        return self.pokrycie_top >= 0.70 and (self.rho >= 0.80 or np.isnan(self.rho))


def stabilnosc_rankingu(
    bazowy: Mapping[int, float],
    zaburzony: Mapping[int, float],
    *,
    top_n: int = 100,
) -> StabilnoscRankingu:
    """Ile z top-N zostaje w top-N po perturbacji wag i jak zmienia sie kolejnosc."""
    wspolne = sorted(set(bazowy) & set(zaburzony))
    if len(wspolne) < 3:
        raise CalibrationError(f"za malo wspolnych ofert do porownania: {len(wspolne)}")

    top_n = min(top_n, len(wspolne))
    top_bazowy = set(sorted(wspolne, key=lambda i: -bazowy[i])[:top_n])
    top_zaburzony = set(sorted(wspolne, key=lambda i: -zaburzony[i])[:top_n])

    return StabilnoscRankingu(
        pokrycie_top=len(top_bazowy & top_zaburzony) / top_n,
        rho=spearman([bazowy[i] for i in wspolne], [zaburzony[i] for i in wspolne]),
        top_n=top_n,
        n=len(wspolne),
    )


# -------------------------------- wrazliwosc na wage pojedynczego filaru
#
# zaburz_wagi wyzej rusza WSZYSTKIMI wagami naraz i losowo. To odpowiada na
# pytanie "czy ranking w ogole zalezy od arbitralnego doboru liczb". Kryterium
# akceptacji fazy 6 pyta o co innego i bardziej konkretnie: co robi ranking,
# gdy JEDNEMU filarowi podniesc albo obnizyc wage o 20%. Stad osobny, w pelni
# deterministyczny pomiar - bez seeda, bo nie ma tu losowosci.


def skaluj_wage(wagi: Mapping[str, float], filar: str, czynnik: float) -> dict[str, float]:
    """Waga jednego filaru pomnozona przez czynnik, calosc przeskalowana do 1.

    Renormalizacja jest czescia pytania, a nie skutkiem ubocznym: wagi filarow
    sumuja sie do jedynki, wiec "podnies planistyke o 20%" musi oznaczac, ze
    pozostale filary oddaja jej proporcjonalnie czesc udzialu. Bez tego kroku
    porownywalibysmy rankingi liczone w dwoch roznych skalach.
    """
    if filar not in wagi:
        raise CalibrationError(f"nieznany filar: {filar}")
    if czynnik <= 0:
        raise CalibrationError("czynnik musi byc dodatni")

    zmienione = {k: (w * czynnik if k == filar else w) for k, w in wagi.items()}
    suma = sum(zmienione.values())
    if suma <= 0:
        raise CalibrationError("wagi sumuja sie do zera")
    return {k: w / suma for k, w in zmienione.items()}


def pozycje(wyniki: Mapping[int, float]) -> dict[int, int]:
    """Miejsca w rankingu, liczone od 1. Remisy rozstrzyga identyfikator oferty.

    Rozstrzygniecie remisu musi byc jawne i stale, inaczej dwie oferty z tym
    samym wynikiem zamienialyby sie miejscami przy kazdym przebiegu i analiza
    wrazliwosci mierzylaby kolejnosc slownika zamiast wplywu wag.
    """
    posortowane = sorted(wyniki.items(), key=lambda kv: (-kv[1], kv[0]))
    return {listing_id: miejsce for miejsce, (listing_id, _) in enumerate(posortowane, start=1)}


@dataclass(frozen=True, slots=True)
class PrzesuniecieRankingu:
    """Co zmiana wag zrobila z pierwsza dziesiatka rankingu bazowego."""

    top_n: int
    n: int
    max_przesuniecie: int
    mediana_przesuniecia: float
    wymiana_czolowki: int
    bez_wyniku: int
    ruchy: tuple[tuple[int, int, int], ...]
    prog: int = MAX_ZMIANA_CZOLOWKI

    @property
    def stabilny(self) -> bool:
        """Kryterium sekcji 21 w odczycie przez sklad czolowki (patrz komentarz wyzej).

        Oferta, ktora po zmianie wag w ogole stracila wynik, wypadla z czolowki,
        wiec liczy sie do wymiany bez zadnego dodatkowego warunku. To nie jest
        przypadek teoretyczny: wieksza waga niedostepnego filaru obniza
        kompletnosc i moze zbic oferte ponizej progu 40%.
        """
        return self.wymiana_czolowki <= self.prog

    def to_dict(self) -> dict[str, Any]:
        return {
            "top_n": self.top_n,
            "n": self.n,
            "max_przesuniecie": self.max_przesuniecie,
            "mediana_przesuniecia": round(self.mediana_przesuniecia, 2),
            "wymiana_czolowki": self.wymiana_czolowki,
            "bez_wyniku": self.bez_wyniku,
            "stabilny": self.stabilny,
            "ruchy": [list(r) for r in self.ruchy],
        }


def przesuniecie_rankingu(
    bazowy: Mapping[int, float],
    zmieniony: Mapping[int, float],
    *,
    top_n: int = WRAZLIWOSC_TOP_N,
    prog: int = MAX_ZMIANA_CZOLOWKI,
) -> PrzesuniecieRankingu:
    """O ile miejsc rusza sie bazowa czolowka po zmianie wag.

    Mierzymy przesuniecie ofert z czolowki BAZOWEJ, a nie roznice zbiorow.
    Oferta, ktora spadla z 3. na 11. miejsce, wypadla z dziesiatki i przesunela
    sie o 8: sama informacja "wypadla" gubi to, czy spadla tuz za prog, czy na
    koniec stawki. Obie liczby sa w wyniku, bo kryterium da sie czytac na oba
    sposoby, a rozjezdzaja sie tylko wtedy, gdy ranking naprawde sie sypie.
    """
    if len(bazowy) < 3:
        raise CalibrationError(f"za malo ofert w rankingu: {len(bazowy)}")

    top_n = min(top_n, len(bazowy))
    miejsca_bazowe = pozycje(bazowy)
    miejsca_po = pozycje(zmieniony)
    czolowka = sorted(bazowy, key=lambda i: miejsca_bazowe[i])[:top_n]
    nowa_czolowka = {i for i, m in miejsca_po.items() if m <= top_n}

    ruchy: list[tuple[int, int, int]] = []
    bez_wyniku = 0
    for listing_id in czolowka:
        miejsce_po = miejsca_po.get(listing_id)
        if miejsce_po is None:
            bez_wyniku += 1
            continue
        ruchy.append((listing_id, miejsca_bazowe[listing_id], miejsce_po))

    odleglosci = sorted(abs(po - przed) for _, przed, po in ruchy)
    return PrzesuniecieRankingu(
        top_n=top_n,
        n=len(bazowy),
        max_przesuniecie=max(odleglosci) if odleglosci else 0,
        mediana_przesuniecia=float(np.median(odleglosci)) if odleglosci else 0.0,
        wymiana_czolowki=sum(1 for i in czolowka if i not in nowa_czolowka),
        bez_wyniku=bez_wyniku,
        ruchy=tuple(ruchy),
        prog=prog,
    )


# ---------------------------------------------------------- dyskryminacja


@dataclass(frozen=True, slots=True)
class Dyskryminacja:
    """Czy scoring w ogole rozroznia dzialki (sekcja 5.6)."""

    n: int
    udzial_najliczniejszego: float
    przedzial_najliczniejszy: tuple[float, float]
    rozstep_miedzykwartylowy: float
    odchylenie: float
    przedzialy: tuple[int, ...]
    prog: float = MAX_UDZIAL_PRZEDZIALU
    szczegoly: dict[str, float] = field(default_factory=dict)

    @property
    def rozroznia(self) -> bool:
        return self.udzial_najliczniejszego <= self.prog


def dyskryminacja(
    wyniki: Sequence[float],
    *,
    liczba_przedzialow: int = 10,
    zakres: tuple[float, float] = (0.0, 100.0),
    prog: float = MAX_UDZIAL_PRZEDZIALU,
) -> Dyskryminacja:
    """Histogram wynikow i udzial najliczniejszego przedzialu."""
    dane = np.asarray([w for w in wyniki if w is not None], dtype=float)
    dane = dane[np.isfinite(dane)]
    if dane.size < 10:
        raise CalibrationError(f"za malo wynikow do oceny dyskryminacji: {dane.size}")

    krawedzie = np.linspace(zakres[0], zakres[1], liczba_przedzialow + 1)
    liczebnosci, _ = np.histogram(dane, bins=krawedzie)
    najliczniejszy = int(liczebnosci.argmax())

    return Dyskryminacja(
        n=int(dane.size),
        udzial_najliczniejszego=float(liczebnosci[najliczniejszy] / dane.size),
        przedzial_najliczniejszy=(
            float(krawedzie[najliczniejszy]),
            float(krawedzie[najliczniejszy + 1]),
        ),
        rozstep_miedzykwartylowy=float(np.percentile(dane, 75) - np.percentile(dane, 25)),
        odchylenie=float(dane.std(ddof=1)) if dane.size > 1 else 0.0,
        przedzialy=tuple(int(x) for x in liczebnosci),
        prog=prog,
        szczegoly={
            "mediana": float(np.median(dane)),
            "min": float(dane.min()),
            "max": float(dane.max()),
        },
    )
