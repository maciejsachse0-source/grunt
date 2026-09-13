"""Warstwa A: wycena. Model 1 z sekcji 5.2.3.

Mediana ceny za m2 znormalizowanej do 1000 m2, per poziom hierarchii TERYT,
z bayesowskim shrinkage'em obreb -> gmina -> powiat -> wojewodztwo.

Dlaczego nie srednia gminy i nie XGBoost, tylko to:

* W 1. polowie 2023 w calej Polsce bylo ok. 15 tys. transakcji gruntowych na
  2 477 gmin, czyli srednio ok. 6 na gmine na polrocze. Mediana z 6 obserwacji
  jest bezuzyteczna, a twardy prog "min. 15 porownywalnych" wywala model
  na wiekszosci Polski.
* Shrinkage rozwiazuje to sam z siebie: lambda = n / (n + k). Obreb z 2
  transakcjami dostaje 17% wlasnych danych i 83% gminy, obreb ze 100 - 91%
  wlasnych. Model nigdy nie wywala sie na braku danych, tylko rozszerza przedzial.
* Przy 500-5000 transakcjach model hierarchiczny wygra dokladnoscia z gradient
  boostingiem, da przedzialy za darmo i bedzie wyjasnialny.

Wszystko liczone na logarytmach cen, bo rozklad cen nieruchomosci jest skosny,
i na statystykach odpornych (mediana, MAD zamiast sredniej i odchylenia), bo RCN
zawiera bledy: ceny 1 zl, powierzchnie 5 mln m2, transakcje rodzinne.

Funkcje czyste: bez bazy, bez sieci, bez datetime.now(). Data wyceny wchodzi
jawnie parametrem as_of.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import numpy as np

from grunt.scoring.normalize_area import (
    LogPriceCurve,
    denormalize_price_per_m2,
    normalize_price_per_m2,
)

if TYPE_CHECKING:
    from grunt.scoring.segments import Segment

# Kolejnosc od najbardziej lokalnego. Shrinkage idzie od gory w dol tej listy.
Level = Literal["obreb", "gmina", "powiat", "wojewodztwo"]
LEVELS: tuple[Level, ...] = ("wojewodztwo", "powiat", "gmina", "obreb")

# k = sigma^2 / tau^2, czyli "liczba obserwacji rownowazna wiedzy wstepnej".
# 10 oznacza: przy 10 wlasnych transakcjach ufamy im w 50%.
DEFAULT_K_SHRINK = 10.0

# Ponizej tylu obserwacji na poziomie nie liczymy z niego wlasnej zmiennosci,
# tylko dziedziczymy ja z poziomu wyzej.
MIN_OBS_FOR_SIGMA = 8

# Odrzucanie odstajacych: 3 * 1.4826 * MAD zamiast 3 sigma (sekcja 5.5).
MAD_TO_SIGMA = 1.4826
OUTLIER_MAD_MULTIPLIER = 3.0

# Podloga na niepewnosc. Nawet przy tysiacu porownywalnych nie udajemy,
# ze wiemy cene z dokladnoscia do 5%. Realistyczne cele: MdAPE 18-30%.
SIGMA_FLOOR_LOG = 0.18

Z_SCORES = {0.80: 1.2816, 0.90: 1.6449, 0.95: 1.9600}

# Powyzej tego rozrzutu wycena przestaje byc informacja. sigma = 0,60 to przedzial
# 80% szeroki mniej wiecej dwukrotnie (od -54% do +116% wzgledem punktu).
# Regula produktowa z sekcji 5.3.9: zly wynik jest gorszy niz brak wyniku,
# wiec zamiast liczby pokazujemy powod, dla ktorego jej nie ma.
MAX_SIGMA_RELIABLE = 0.60

# Prog, powyzej ktorego oferte nazywamy okazja. D = 1,5 znaczy "cena lezy
# poltora odchylenia ponizej wyceny", czyli przy zalozeniu rozkladu normalnego
# mniej wiecej 7. percentyl. Nie jest to prog decyzyjny, tylko prog uwagi:
# polowa tych ofert ma niska cene z powodu, ktorego model nie widzi.
PROG_OKAZJI = 1.5

# Kara doliczana do odleglosci laczonej za transakcje z innego segmentu rynku.
# Wyrazona w tych samych jednostkach co czlon geograficzny (kilometry do kwadratu),
# wiec 25 znaczy "sasiad z innego segmentu liczy sie tak, jakby byl 5 km dalej".
SEGMENT_MISMATCH_PENALTY = 25.0


class ValuationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Comparable:
    """Jedna transakcja RCN uzyta jako porownywalna."""

    price_per_m2: float
    area_m2: float
    date: dt.date
    level: Level
    id_dzialki: str | None = None
    przeznaczenie: str | None = None
    sposob_uzyt: str | None = None
    teryt_gmina: str | None = None
    distance_m: float | None = None

    @property
    def segment(self) -> Segment:
        from grunt.scoring.segments import classify

        return classify(self.przeznaczenie, self.sposob_uzyt)

    def to_dict(self) -> dict[str, object]:
        return {
            "id_dzialki": self.id_dzialki,
            "cena_m2": round(self.price_per_m2, 2),
            "pow_m2": int(self.area_m2),
            "data": self.date.isoformat(),
            "poziom": self.level,
            "przeznaczenie": self.przeznaczenie,
            "sposob_uzyt": self.sposob_uzyt,
            "segment": self.segment,
        }


@dataclass(frozen=True, slots=True)
class LevelStats:
    level: Level
    n: int
    median_log: float
    sigma_log: float
    lam: float
    posterior_log: float

    def to_dict(self) -> dict[str, object]:
        return {
            "poziom": self.level,
            "n": self.n,
            "mediana_cena_m2": round(math.exp(self.median_log), 2),
            "sigma_log": round(self.sigma_log, 4),
            "lambda": round(self.lam, 3),
            "po_shrinkage_cena_m2": round(math.exp(self.posterior_log), 2),
        }


@dataclass(frozen=True, slots=True)
class ValuationResult:
    v_hat_grosze: int
    ci_low_grosze: int
    ci_high_grosze: int
    unit_price_norm: float
    unit_price_for_area: float
    sigma_log: float
    confidence: float
    n_comparables: int
    method: str
    level_used: Level | None
    levels: tuple[LevelStats, ...]
    comparables: tuple[Comparable, ...]
    warnings: tuple[str, ...] = ()
    area_m2: float = 0.0
    area_ref_m2: float = 1000.0
    dropped_outliers: int = 0
    reliable: bool = True
    extras: dict[str, object] = field(default_factory=dict)

    @property
    def v_hat_pln(self) -> float:
        return self.v_hat_grosze / 100.0

    @property
    def mdape_hint(self) -> float:
        """Przyblizony wzgledny rozrzut, przydatny w komunikacie dla uzytkownika."""
        return math.exp(self.sigma_log) - 1.0

    def to_dict(self) -> dict[str, object]:
        return {
            "wycena_pln": round(self.v_hat_pln, 0),
            "przedzial_pln": [
                round(self.ci_low_grosze / 100.0, 0),
                round(self.ci_high_grosze / 100.0, 0),
            ],
            "pewnosc": self.confidence,
            "cena_m2": round(self.unit_price_for_area, 2),
            "cena_m2_znormalizowana": round(self.unit_price_norm, 2),
            "metoda": self.method,
            "poziom": self.level_used,
            "liczba_porownywalnych": self.n_comparables,
            "odrzucone_odstajace": self.dropped_outliers,
            "rozrzut_wzgledny": round(self.mdape_hint, 3),
            "wiarygodna": self.reliable,
            "poziomy": [level.to_dict() for level in self.levels],
            "porownywalne": [c.to_dict() for c in self.comparables],
            "segmenty": self.extras.get("segmenty", []),
            "ostrzezenia": list(self.warnings),
        }


# ------------------------------------------------------------------ statystyki


def _robust_stats(values: np.ndarray) -> tuple[float, float]:
    """Mediana i sigma z MAD. Odporne na ceny 1 zl i inne smieci w RCN."""
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    return median, mad * MAD_TO_SIGMA


def _drop_outliers(values: np.ndarray) -> tuple[np.ndarray, int]:
    if values.size < 5:
        return values, 0
    median, sigma = _robust_stats(values)
    if sigma <= 0:
        return values, 0
    keep = np.abs(values - median) <= OUTLIER_MAD_MULTIPLIER * sigma
    return values[keep], int((~keep).sum())


def time_index(date: dt.date, as_of: dt.date, annual_drift: float) -> float:
    """Korekta czasowa w logarytmie ceny.

    RCN siega 2007 roku, a rynek gruntow w Polsce rosl o kilkanascie procent
    rocznie (pomorskie: grunty orne +54% miedzy 2020 a 2025). Bez indeksacji
    stare transakcje ciagna wycene w dol.
    """
    years = (as_of - date).days / 365.25
    return years * math.log1p(annual_drift)


# --------------------------------------------------------------------- model


def valuate_median_shrinkage(
    area_m2: float,
    comparables: Sequence[Comparable],
    *,
    as_of: dt.date,
    curve: LogPriceCurve | None = None,
    area_ref_m2: float = 1000.0,
    k_shrink: float = DEFAULT_K_SHRINK,
    annual_drift: float = 0.08,
    confidence: float = 0.80,
    max_comparables_shown: int = 12,
    segments_used: Sequence[str] = (),
) -> ValuationResult:
    """Model 1: mediana znormalizowana z hierarchicznym shrinkage'em.

    Zwraca komplet skladnikow wyniku, nie sama liczbe: uzytkownik ma widziec,
    z ilu transakcji i z jakiego poziomu powstala wycena.
    """
    if area_m2 <= 0:
        raise ValuationError("powierzchnia dzialki musi byc dodatnia")
    if confidence not in Z_SCORES:
        raise ValuationError(f"obslugiwane poziomy ufnosci: {sorted(Z_SCORES)}")

    curve = curve or LogPriceCurve.constant()
    warnings: list[str] = []

    # 1. normalizacja efektu skali i indeksacja czasowa, wszystko w logarytmach
    by_level: dict[Level, list[float]] = {level: [] for level in LEVELS}
    usable: list[Comparable] = []
    for comp in comparables:
        if comp.price_per_m2 <= 0 or comp.area_m2 <= 0:
            continue
        normalized = normalize_price_per_m2(
            comp.price_per_m2, comp.area_m2, curve=curve, area_ref_m2=area_ref_m2
        )
        log_price = math.log(normalized) + time_index(comp.date, as_of, annual_drift)
        by_level[comp.level].append(log_price)
        usable.append(comp)

    if not usable:
        raise ValuationError("brak porownywalnych transakcji z dodatnia cena i powierzchnia")

    # 2. statystyki per poziom, z odrzuceniem odstajacych
    dropped_total = 0
    raw_stats: dict[Level, tuple[int, float, float]] = {}
    for level in LEVELS:
        values = np.asarray(by_level[level], dtype=float)
        if values.size == 0:
            continue
        cleaned, dropped = _drop_outliers(values)
        dropped_total += dropped
        median, sigma = _robust_stats(cleaned)
        raw_stats[level] = (int(cleaned.size), median, sigma)

    if not raw_stats:
        raise ValuationError("brak danych na zadnym poziomie hierarchii")

    # 3. shrinkage od najszerszego poziomu w dol
    prior: float | None = None
    prior_sigma: float | None = None
    levels_out: list[LevelStats] = []
    level_used: Level | None = None
    n_local = 0

    for level in LEVELS:
        if level not in raw_stats:
            continue
        n, median, sigma = raw_stats[level]
        if prior is None:
            lam, posterior = 1.0, median
        else:
            lam = n / (n + k_shrink)
            posterior = lam * median + (1.0 - lam) * prior

        if sigma <= 0 or n < MIN_OBS_FOR_SIGMA:
            sigma = prior_sigma if prior_sigma is not None else max(sigma, SIGMA_FLOOR_LOG)

        levels_out.append(LevelStats(level, n, median, sigma, lam, posterior))
        prior, prior_sigma = posterior, sigma
        level_used, n_local = level, n

    assert prior is not None and prior_sigma is not None
    mu = prior
    sigma_level = max(prior_sigma, SIGMA_FLOOR_LOG)

    # 4. niepewnosc rosnie, gdy lokalnych obserwacji jest malo
    n_effective = max(n_local, 1)
    sigma_pred = sigma_level * math.sqrt(1.0 + 1.0 / n_effective)

    total_n = sum(stats[0] for stats in raw_stats.values())

    # 5. routing metody zgodny z rozporzadzeniem o wycenie (sekcja 5.5)
    if n_local >= 15:
        method = "median_shrink/kcs"
    elif n_local >= 3:
        method = "median_shrink/pary"
        sigma_pred *= 1.15
        warnings.append(
            f"tylko {n_local} porownywalnych na poziomie {level_used}, przedzial poszerzony"
        )
    else:
        method = "median_shrink/regionalny"
        sigma_pred *= 1.4
        warnings.append(
            "za malo lokalnych transakcji, wycena oparta na poziomie nadrzednym; "
            "traktuj ja jako orientacyjna"
        )

    if total_n < 3:
        warnings.append("mniej niz 3 transakcje w calej hierarchii, wynik bardzo niepewny")

    # Dobor porownywalnych spoza segmentu docelowego to realne rozmycie wyceny,
    # wiec i przedzial, i komunikat musza to pokazac.
    if len(segments_used) > 1:
        sigma_pred *= 1.0 + 0.10 * (len(segments_used) - 1)
        warnings.append(
            "za malo transakcji w segmencie "
            f"{segments_used[0]}, dobrano takze: {', '.join(segments_used[1:])}"
        )

    # 6. z ceny znormalizowanej z powrotem na konkretna powierzchnie
    unit_norm = math.exp(mu)
    unit_for_area = denormalize_price_per_m2(
        unit_norm, area_m2, curve=curve, area_ref_m2=area_ref_m2
    )

    z = Z_SCORES[confidence]
    v_hat = unit_for_area * area_m2
    low = v_hat * math.exp(-z * sigma_pred)
    high = v_hat * math.exp(z * sigma_pred)

    shown = sorted(
        usable,
        key=lambda c: (
            LEVELS.index(c.level) * -1,  # najpierw najbardziej lokalne
            abs(math.log(c.area_m2 / area_m2)),  # potem najblizsze powierzchnia
            (as_of - c.date).days,  # potem najswiezsze
        ),
    )[:max_comparables_shown]

    if sigma_pred > MAX_SIGMA_RELIABLE:
        warnings.append(
            f"rozrzut cen w okolicy jest zbyt duzy (sigma={sigma_pred:.2f}), "
            "wycena nie jest wiarygodna - potraktuj ja jako rzad wielkosci"
        )

    return ValuationResult(
        v_hat_grosze=int(round(v_hat * 100)),
        ci_low_grosze=int(round(low * 100)),
        ci_high_grosze=int(round(high * 100)),
        unit_price_norm=unit_norm,
        unit_price_for_area=unit_for_area,
        sigma_log=sigma_pred,
        confidence=confidence,
        n_comparables=total_n,
        method=method,
        level_used=level_used,
        levels=tuple(levels_out),
        comparables=tuple(shown),
        warnings=tuple(warnings),
        area_m2=area_m2,
        area_ref_m2=area_ref_m2,
        dropped_outliers=dropped_total,
        reliable=sigma_pred <= MAX_SIGMA_RELIABLE,
        extras={
            "n_lokalnych": n_local,
            "k_shrink": k_shrink,
            "drift_roczny": annual_drift,
            "segmenty": list(segments_used),
        },
    )


def deal_score(
    price_offered_grosze: int,
    valuation: ValuationResult,
    *,
    spread: float = 0.0,
) -> float:
    """Warstwa C: D = (V - cena) / sigma. Sekcja 5.4.

    Dzielenie przez sigma jest kluczowe: bez niego system zalewa uzytkownika
    "okazjami" z gmin, o ktorych model nic nie wie.

    spread to kalibrowana roznica miedzy poziomem cen ofertowych a transakcyjnych
    (sekcja 5.6). V pochodzi z RCN, czyli z cen TRANSAKCYJNYCH, a porownujemy je
    z cena OFERTOWA, wiec bez korekty deal score jest systematycznie ujemny
    i nie oznacza okazji, tylko sam fakt, ze ogloszenia sa drozsze od umow.
    Domyslne 0,0 zachowuje surowe porownanie: to swiadomy wybor, zeby brak
    kalibracji byl widoczny w liczbie, a nie ukryty w zalozeniu.
    """
    if price_offered_grosze <= 0:
        raise ValuationError("cena ofertowa musi byc dodatnia")
    if spread <= -1.0:
        raise ValuationError("spread ponizej -100% nie ma sensu")
    v_ofertowe = valuation.v_hat_grosze * (1.0 + spread)
    sigma_grosze = v_ofertowe * valuation.sigma_log
    if sigma_grosze <= 0:
        raise ValuationError("zerowa niepewnosc, deal score nie ma sensu")
    return (v_ofertowe - price_offered_grosze) / sigma_grosze


# ---------------------------------------------------------- Model 2: SE-KNN


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    values, weights = values[order], weights[order]
    cumulative = np.cumsum(weights) - 0.5 * weights
    cumulative /= weights.sum()
    return float(np.interp(q, cumulative, values))


def valuate_se_knn(
    area_m2: float,
    comparables: Sequence[Comparable],
    *,
    as_of: dt.date,
    curve: LogPriceCurve | None = None,
    area_ref_m2: float = 1000.0,
    k: int = 20,
    lam: float = 0.7,
    bandwidth: float = 1.0,
    annual_drift: float = 0.08,
    confidence: float = 0.80,
    max_distance_m: float = 15_000.0,
    max_comparables_shown: int = 12,
    segments_used: Sequence[str] = (),
    target_segment: str | None = None,
    segment_penalty: float = SEGMENT_MISMATCH_PENALTY,
    prior_log_price: float | None = None,
    prior_weight: float = 6.0,
) -> ValuationResult:
    """Model 2: k najblizszych sasiadow w przestrzeni laczonej geografia + cechy.

        d'_ij = (1 - lam) * ||cechy_i - cechy_j||^2 + lam * ||geografia_i - geografia_j||^2

    lam = 0,7 pochodzi z Chen, Lee i Chun (2026) i mowi wprost: geografia wazy
    wiecej niz cechy. Na naszych danych to samo widac w rozbiciu bledu: przy
    ponad 20 lokalnych transakcjach MdAPE spada z 62% do 28%, a "lokalny" na
    poziomie obrebu bywa oddalony o kilka kilometrow. Odleglosc w metrach jest
    po prostu lepsza definicja sasiedztwa niz granica administracyjna.

    prior_log_price pozwala domieszac wynik Modelu 1 jako kotwice, gdy sasiadow
    jest malo. To ten sam mechanizm shrinkage'u, tylko z innym priorem.
    """
    if area_m2 <= 0:
        raise ValuationError("powierzchnia dzialki musi byc dodatnia")
    if confidence not in Z_SCORES:
        raise ValuationError(f"obslugiwane poziomy ufnosci: {sorted(Z_SCORES)}")
    curve = curve or LogPriceCurve.constant()

    with_distance = [
        c
        for c in comparables
        if c.distance_m is not None
        and c.distance_m <= max_distance_m
        and c.price_per_m2 > 0
        and c.area_m2 > 0
    ]
    if not with_distance:
        raise ValuationError("brak porownywalnych z policzona odlegloscia")

    log_prices: list[float] = []
    distances: list[float] = []
    for comp in with_distance:
        normalized = normalize_price_per_m2(
            comp.price_per_m2, comp.area_m2, curve=curve, area_ref_m2=area_ref_m2
        )
        log_prices.append(math.log(normalized) + time_index(comp.date, as_of, annual_drift))
        distances.append(float(comp.distance_m or 0.0))

    y = np.asarray(log_prices)
    geo_dist = np.asarray(distances)

    # Skale: geografia w kilometrach, powierzchnia i czas w jednostkach naturalnych
    # dla tych zmiennych, zeby lam mialo sens jako waga miedzy dwoma czlonami.
    geo_term = (geo_dist / 1000.0) ** 2
    area_term = np.array([math.log(c.area_m2 / area_m2) ** 2 for c in with_distance])
    time_term = np.array([((as_of - c.date).days / 365.25 / 3.0) ** 2 for c in with_distance])
    feature_term = area_term + time_term

    combined = lam * geo_term + (1.0 - lam) * feature_term

    # Sasiad z innego segmentu rynku jest gorszym porownaniem niz sasiad
    # oddalony o kilka kilometrow. W Gdansku bez tej kary k najblizszych
    # transakcji obejmowalo dzialki od 80 do 1421 zl/m2, bo mieszalo zabudowe
    # jednorodzinna z uslugowa, a przedzial ufnosci robil sie bezuzyteczny.
    if target_segment is not None:
        mismatch = np.array([0.0 if c.segment == target_segment else 1.0 for c in with_distance])
        combined = combined + segment_penalty * mismatch

    keep = np.argsort(combined)[: max(k, 3)]
    y, combined = y[keep], combined[keep]
    neighbours = [with_distance[i] for i in keep]

    clean, dropped = _drop_outliers(y)
    if clean.size >= 3:
        mask = np.isin(y, clean)
        y, combined = y[mask], combined[mask]
        neighbours = [n for n, m in zip(neighbours, mask, strict=True) if m]

    # Jadro gaussowskie na odleglosci laczonej; skala adaptacyjna, zeby na wsi
    # (sasiad o 8 km) nie wyzerowac wszystkich wag.
    scale = max(float(np.median(combined)), 1e-6) * bandwidth
    weights = np.exp(-combined / (2.0 * scale))

    if prior_log_price is not None:
        y = np.append(y, prior_log_price)
        weights = np.append(weights, prior_weight * float(weights.mean()))

    mu = _weighted_quantile(y, weights, 0.5)

    spread = _weighted_quantile(np.abs(y - mu), weights, 0.5) * MAD_TO_SIGMA
    n_used = len(neighbours)
    sigma = max(spread, SIGMA_FLOOR_LOG) * math.sqrt(1.0 + 1.0 / max(n_used, 1))

    if len(segments_used) > 1:
        sigma *= 1.0 + 0.10 * (len(segments_used) - 1)

    warnings: list[str] = []
    if n_used < 6:
        sigma *= 1.25
        warnings.append(f"tylko {n_used} sasiadow w promieniu {max_distance_m / 1000:.0f} km")
    if sigma > MAX_SIGMA_RELIABLE:
        warnings.append(
            f"rozrzut cen w sasiedztwie jest zbyt duzy (sigma={sigma:.2f}), "
            "wycena nie jest wiarygodna - potraktuj ja jako rzad wielkosci"
        )
    median_distance = float(np.median([n.distance_m or 0.0 for n in neighbours]))
    if median_distance > 5000:
        warnings.append(
            f"najblizsze transakcje sa oddalone o {median_distance / 1000:.1f} km, "
            "wycena jest orientacyjna"
        )

    unit_norm = math.exp(mu)
    unit_for_area = denormalize_price_per_m2(
        unit_norm, area_m2, curve=curve, area_ref_m2=area_ref_m2
    )
    z = Z_SCORES[confidence]
    v_hat = unit_for_area * area_m2

    shown = sorted(neighbours, key=lambda c: c.distance_m or 0.0)[:max_comparables_shown]

    return ValuationResult(
        v_hat_grosze=int(round(v_hat * 100)),
        ci_low_grosze=int(round(v_hat * math.exp(-z * sigma) * 100)),
        ci_high_grosze=int(round(v_hat * math.exp(z * sigma) * 100)),
        unit_price_norm=unit_norm,
        unit_price_for_area=unit_for_area,
        sigma_log=sigma,
        confidence=confidence,
        n_comparables=n_used,
        method="se_knn",
        level_used=None,
        levels=(),
        comparables=tuple(shown),
        warnings=tuple(warnings),
        area_m2=area_m2,
        area_ref_m2=area_ref_m2,
        dropped_outliers=dropped,
        reliable=sigma <= MAX_SIGMA_RELIABLE,
        extras={
            "k": k,
            "lambda": lam,
            "mediana_odleglosci_m": round(median_distance),
            "segmenty": list(segments_used),
            "prior_uzyty": prior_log_price is not None,
        },
    )
