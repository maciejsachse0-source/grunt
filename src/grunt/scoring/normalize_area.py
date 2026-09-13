"""Korekta efektu skali: sekcja 5.2.1 dokumentu koncepcyjnego.

Cena za metr kwadratowy systematycznie spada wraz z powierzchnia dzialki.
Bitner (2008) na 2 422 transakcjach z Krakowa: wzrost o 1 ar obniza cene
jednostkowa o ok. 0,8%. Ritter i in. (2020) na 80 tys. transakcji: relacja jest
niemonotoniczna, "nie da sie ujac prosta forma funkcyjna".

Konsekwencja operacyjna, powtorzona w dokumencie trzy razy: NIGDY nie porownuj
surowej ceny za m2. Bez tej korekty system systematycznie wskazuje duze dzialki
jako okazje, a male jako przepłacone.

Model: ln(P) = f(ln A), gdzie f jest lamana ciagla o kilku wezlach (linear spline).
Dla f liniowego, f(x) = a + b1*x, wzor sprowadza sie do wersji z dokumentu:

    cena_m2_norm = cena_m2_obs * (A_obs / A_ref)^(1 - b1)

Wersja z wezlami robi to samo lokalnie, ale pozwala, zeby elastycznosc rozniła sie
miedzy dzialkami 500 m2 a 5 ha, i nie tworzy skoku na granicy przedzialow, bo
lamana jest ciagla. To odpowiedz na zastrzezenie Rittera bez wchodzenia
w pelne splajny naturalne.

Wszystko tutaj to funkcje czyste: bez bazy, bez sieci, bez czasu.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

# Wartosc startowa przed kalibracja na wlasnych danych (sekcja 5.2.3: b1 = 0,80-0,90).
DEFAULT_BETA1 = 0.85

# Wezly domyslne odpowiadaja przedzialom z dokumentu: ponizej 800 m2,
# 800-3000 m2, powyzej 3000 m2, plus 10 000 m2 jako granica dzialek rolnych.
DEFAULT_KNOTS_M2 = (800.0, 3000.0, 10000.0)


class NormalizationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LogPriceCurve:
    """f(ln A) = intercept + slope0*x + sum_j delta_j * max(0, x - ln(knot_j)).

    slope0 to elastycznosc dla najmniejszych dzialek, kazda delta_j to jej zmiana
    powyzej kolejnego wezla. Suma slope0 + delta_0..j to elastycznosc w przedziale j.
    """

    intercept: float
    slope0: float
    deltas: tuple[float, ...] = ()
    knots_m2: tuple[float, ...] = ()
    n_obs: int = 0
    r2: float = float("nan")

    def __post_init__(self) -> None:
        if len(self.deltas) != len(self.knots_m2):
            raise NormalizationError("liczba wezlow musi odpowiadac liczbie wspolczynnikow")

    @classmethod
    def constant(cls, beta1: float = DEFAULT_BETA1) -> LogPriceCurve:
        """Krzywa o stalej elastycznosci, czyli dokladnie wzor z dokumentu."""
        return cls(intercept=0.0, slope0=beta1)

    def f(self, area_m2: float) -> float:
        if area_m2 <= 0:
            raise NormalizationError("powierzchnia musi byc dodatnia")
        x = math.log(area_m2)
        value = self.intercept + self.slope0 * x
        for delta, knot in zip(self.deltas, self.knots_m2, strict=True):
            value += delta * max(0.0, x - math.log(knot))
        return value

    def beta_at(self, area_m2: float) -> float:
        """Lokalna elastycznosc ceny calkowitej wzgledem powierzchni."""
        if area_m2 <= 0:
            raise NormalizationError("powierzchnia musi byc dodatnia")
        beta = self.slope0
        for delta, knot in zip(self.deltas, self.knots_m2, strict=True):
            if area_m2 > knot:
                beta += delta
        return beta


def normalize_price_per_m2(
    price_per_m2: float,
    area_m2: float,
    *,
    curve: LogPriceCurve | None = None,
    area_ref_m2: float = 1000.0,
) -> float:
    """Cena za m2 sprowadzona do dzialki referencyjnej.

    Ogolna postac: p_norm = p_obs * exp(f(A_ref) - f(A_obs)) * (A_obs / A_ref).
    Dla krzywej o stalej elastycznosci upraszcza sie do (A_obs/A_ref)^(1-b1).
    """
    if price_per_m2 <= 0:
        raise NormalizationError("cena za m2 musi byc dodatnia")
    if area_m2 <= 0 or area_ref_m2 <= 0:
        raise NormalizationError("powierzchnia musi byc dodatnia")

    curve = curve or LogPriceCurve.constant()
    factor = math.exp(curve.f(area_ref_m2) - curve.f(area_m2)) * (area_m2 / area_ref_m2)
    return price_per_m2 * factor


def denormalize_price_per_m2(
    price_per_m2_norm: float,
    area_m2: float,
    *,
    curve: LogPriceCurve | None = None,
    area_ref_m2: float = 1000.0,
) -> float:
    """Odwrotnosc: z ceny znormalizowanej z powrotem na dzialke o danej powierzchni."""
    if price_per_m2_norm <= 0:
        raise NormalizationError("cena za m2 musi byc dodatnia")
    curve = curve or LogPriceCurve.constant()
    factor = math.exp(curve.f(area_ref_m2) - curve.f(area_m2)) * (area_m2 / area_ref_m2)
    return price_per_m2_norm / factor


def _design_matrix(areas: np.ndarray, knots: Sequence[float]) -> np.ndarray:
    x = np.log(areas)
    columns = [np.ones_like(x), x]
    for knot in knots:
        columns.append(np.maximum(0.0, x - math.log(knot)))
    return np.column_stack(columns)


def estimate_curve(
    areas_m2: Sequence[float],
    prices: Sequence[float],
    *,
    knots_m2: Sequence[float] | None = DEFAULT_KNOTS_M2,
    min_obs_per_segment: int = 30,
) -> LogPriceCurve:
    """Regresja ln(P) ~ lamana(ln A) metoda najmniejszych kwadratow.

    prices to ceny CALKOWITE transakcji, nie ceny za m2. Wezly bez wystarczajacej
    liczby obserwacji sa usuwane, zeby nie dopasowywac odcinka do trzech punktow.
    """
    areas = np.asarray(areas_m2, dtype=float)
    total = np.asarray(prices, dtype=float)
    if areas.shape != total.shape:
        raise NormalizationError("areas_m2 i prices musza miec ta sama dlugosc")

    mask = (areas > 0) & (total > 0) & np.isfinite(areas) & np.isfinite(total)
    areas, total = areas[mask], total[mask]
    if areas.size < 10:
        raise NormalizationError(f"za malo obserwacji do estymacji: {areas.size}")

    knots = [k for k in (knots_m2 or ()) if k > 0]
    # wezel ma sens tylko wtedy, gdy po obu jego stronach cos jest
    knots = [
        k
        for k in knots
        if (areas > k).sum() >= min_obs_per_segment and (areas <= k).sum() >= min_obs_per_segment
    ]

    design = _design_matrix(areas, knots)
    y = np.log(total)
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)

    residuals = y - design @ coef
    ss_res = float((residuals**2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    return LogPriceCurve(
        intercept=float(coef[0]),
        slope0=float(coef[1]),
        deltas=tuple(float(c) for c in coef[2:]),
        knots_m2=tuple(float(k) for k in knots),
        n_obs=int(areas.size),
        r2=r2,
    )


@dataclass(frozen=True, slots=True)
class NormalizationCheck:
    """Wynik testu walidacyjnego z sekcji 5.2.1."""

    corr_raw: float
    corr_normalized: float
    n: int
    passed: bool
    threshold: float = 0.10
    details: dict[str, float] = field(default_factory=dict)


def check_normalization(
    areas_m2: Sequence[float],
    prices_per_m2: Sequence[float],
    *,
    curve: LogPriceCurve | None = None,
    area_ref_m2: float = 1000.0,
    threshold: float = 0.10,
) -> NormalizationCheck:
    """Po normalizacji korelacja ceny za m2 z ln(A) powinna byc bliska zeru.

    To prosty i mocny test: jesli nie jest, elastycznosc jest zle dobrana.
    Zwraca tez korelacje przed normalizacja, zeby bylo widac, ile korekta zalatwila.
    """
    areas = np.asarray(areas_m2, dtype=float)
    unit = np.asarray(prices_per_m2, dtype=float)
    mask = (areas > 0) & (unit > 0) & np.isfinite(areas) & np.isfinite(unit)
    areas, unit = areas[mask], unit[mask]
    if areas.size < 10:
        raise NormalizationError(f"za malo obserwacji do walidacji: {areas.size}")

    curve = curve or LogPriceCurve.constant()
    normalized = np.array(
        [
            normalize_price_per_m2(u, a, curve=curve, area_ref_m2=area_ref_m2)
            for u, a in zip(unit, areas, strict=True)
        ]
    )

    log_area = np.log(areas)
    corr_raw = float(np.corrcoef(log_area, np.log(unit))[0, 1])
    corr_norm = float(np.corrcoef(log_area, np.log(normalized))[0, 1])

    return NormalizationCheck(
        corr_raw=corr_raw,
        corr_normalized=corr_norm,
        n=int(areas.size),
        passed=abs(corr_norm) <= threshold,
        threshold=threshold,
        details={"beta_1000": curve.beta_at(1000.0), "r2": curve.r2},
    )
