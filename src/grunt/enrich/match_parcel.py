"""Wiazanie oferty z dzialka ewidencyjna.

Dokument (sekcja 2.2) nazywa te operacje kluczowa: wspolrzedne z ogloszenia ->
ULDK -> numer dzialki -> join z RCN. Pomiar na zywych ofertach pokazal jednak,
ze samo pytanie ULDK o punkt nie wystarcza:

    Morizon, Gdansk ul. Wiecka   oferta 1115 m2, dzialka pod punktem 886 m2
    N-O, Katy Rybackie           oferta  835 m2, dzialka pod punktem 18 983 m2

Wspolrzedne z portali wskazuja OKOLICE, nie dzialke. Wiazanie na slepo
przypisaloby ofercie cechy cudzego gruntu, a potem wycene i score liczone
z tych cech. Dlatego:

1. pobieramy wszystkie dzialki w promieniu (EGiB, jedno zapytanie),
2. wybieramy te, ktorej POWIERZCHNIA zgadza sie z ogloszeniem,
3. zapisujemy poziom pewnosci i nigdy nie udajemy, ze jest wyzszy.

Poziomy pewnosci i ich konsekwencje:

    high    punkt lezy w dzialce i powierzchnia zgadza sie do 10%
            -> wolno liczyc cechy dzialki i wiazac z RCN
    medium  powierzchnia zgadza sie do 10%, ale punkt jest obok
            -> cechy liczymy, ale oznaczamy do weryfikacji
    low     punkt lezy w dzialce, powierzchnia sie nie zgadza
            -> uzywamy WYLACZNIE jako lokalizacji (gmina, obreb), nie cech
    none    nie ma sensownego kandydata

To jest realizacja reguly z sekcji 5.3.9: brak danych jest lepszy niz dane
zmyslone, bo zly wynik jest gorszy niz brak wyniku.

choose_parcel() jest funkcja czysta i tak jest testowana.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from grunt.sources.egib import EgibParcel

Confidence = Literal["high", "medium", "low", "none"]

# Powierzchnia ogloszenia bywa zaokraglana ("ok. 1100 m2"), a geometria
# ewidencyjna liczona z dokladnoscia do metra. 10% to margines na te roznice,
# ale juz nie na inna dzialke.
AREA_TOLERANCE = 0.10

# Dalej niz to od punktu z ogloszenia nie szukamy: wspolrzedne sa przyblizone,
# ale nie az tak.
MAX_DISTANCE_M = 250.0


@dataclass(frozen=True, slots=True)
class Candidate:
    parcel: EgibParcel
    contains_point: bool
    distance_m: float
    area_ratio: float | None  # 1.0 = idealna zgodnosc powierzchni

    @property
    def area_matches(self) -> bool:
        return self.area_ratio is not None and self.area_ratio >= 1 - AREA_TOLERANCE


@dataclass(frozen=True, slots=True)
class MatchResult:
    confidence: Confidence
    reason: str
    parcel: EgibParcel | None = None
    distance_m: float | None = None
    area_ratio: float | None = None
    alternatives: tuple[str, ...] = field(default_factory=tuple)

    @property
    def usable_for_features(self) -> bool:
        """Czy wolno liczyc cechy dzialki (front, spadek, uzbrojenie) dla tej oferty."""
        return self.confidence in ("high", "medium")

    def to_dict(self) -> dict[str, object]:
        return {
            "pewnosc": self.confidence,
            "powod": self.reason,
            "id_dzialki": self.parcel.id_dzialki if self.parcel else None,
            "odleglosc_m": round(self.distance_m, 1) if self.distance_m is not None else None,
            "zgodnosc_powierzchni": (
                round(self.area_ratio, 3) if self.area_ratio is not None else None
            ),
            "alternatywy": list(self.alternatives),
        }


def area_ratio(declared_m2: float | None, actual_m2: float | None) -> float | None:
    """Symetryczna miara zgodnosci: 1,0 to identyczne, 0,5 to dwukrotna roznica."""
    if not declared_m2 or not actual_m2 or declared_m2 <= 0 or actual_m2 <= 0:
        return None
    return min(declared_m2, actual_m2) / max(declared_m2, actual_m2)


def build_candidates(
    parcels: list[EgibParcel],
    *,
    point_easting: float,
    point_northing: float,
    declared_area_m2: float | None,
) -> list[Candidate]:
    """Kandydaci z odlegloscia i zgodnoscia powierzchni. Wymaga shapely."""
    from shapely import wkt as shapely_wkt
    from shapely.geometry import Point

    punkt = Point(point_easting, point_northing)
    candidates: list[Candidate] = []

    for parcel in parcels:
        if not parcel.geom_wkt:
            continue
        try:
            geometry = shapely_wkt.loads(parcel.geom_wkt)
        except Exception:
            continue
        candidates.append(
            Candidate(
                parcel=parcel,
                contains_point=bool(geometry.contains(punkt)),
                distance_m=float(geometry.distance(punkt)),
                area_ratio=area_ratio(declared_area_m2, parcel.area_m2),
            )
        )
    return candidates


def choose_parcel(
    parcels: list[EgibParcel],
    *,
    point_easting: float,
    point_northing: float,
    declared_area_m2: float | None,
    max_distance_m: float = MAX_DISTANCE_M,
) -> MatchResult:
    """Wybor dzialki dla oferty. Funkcja czysta.

    Kolejnosc rozstrzygania odzwierciedla sile dowodu: najpierw zgoda obu
    sygnalow naraz, potem sama powierzchnia, na koncu sam punkt.
    """
    candidates = [
        c
        for c in build_candidates(
            parcels,
            point_easting=point_easting,
            point_northing=point_northing,
            declared_area_m2=declared_area_m2,
        )
        if c.distance_m <= max_distance_m
    ]
    if not candidates:
        return MatchResult(confidence="none", reason="brak dzialek w promieniu")

    containing = [c for c in candidates if c.contains_point]

    # 1. punkt w dzialce i zgodna powierzchnia: najmocniejszy dowod
    best_inside = next(
        (c for c in sorted(containing, key=lambda c: -(c.area_ratio or 0)) if c.area_matches),
        None,
    )
    if best_inside is not None:
        return MatchResult(
            confidence="high",
            reason="punkt lezy w dzialce, powierzchnia zgodna",
            parcel=best_inside.parcel,
            distance_m=best_inside.distance_m,
            area_ratio=best_inside.area_ratio,
        )

    # 2. sama zgodnosc powierzchni, punkt obok
    matching_area = sorted(
        (c for c in candidates if c.area_matches),
        key=lambda c: (-(c.area_ratio or 0), c.distance_m),
    )
    if matching_area:
        best = matching_area[0]
        inne = tuple(c.parcel.id_dzialki for c in matching_area[1:4])
        # Kilka dzialek o tej samej powierzchni obok siebie to typowa sytuacja
        # w nowym podziale. Wtedy nie wiemy, ktora to, i mowimy o tym wprost.
        if (
            len(matching_area) > 1
            and abs(matching_area[0].distance_m - matching_area[1].distance_m) < 20
        ):
            return MatchResult(
                confidence="low",
                reason=f"kilka dzialek o pasujacej powierzchni w poblizu ({len(matching_area)})",
                parcel=best.parcel,
                distance_m=best.distance_m,
                area_ratio=best.area_ratio,
                alternatives=inne,
            )
        return MatchResult(
            confidence="medium",
            reason="powierzchnia zgodna, punkt poza dzialka",
            parcel=best.parcel,
            distance_m=best.distance_m,
            area_ratio=best.area_ratio,
            alternatives=inne,
        )

    # 3. tylko punkt, powierzchnia sie nie zgadza: znamy okolice, nie dzialke
    if containing:
        best = containing[0]
        return MatchResult(
            confidence="low",
            reason=(
                "punkt lezy w dzialce, ale powierzchnia sie nie zgadza "
                f"(oferta {declared_area_m2 or '?'} m2, dzialka {best.parcel.area_m2:.0f} m2)"
                if best.parcel.area_m2
                else "punkt lezy w dzialce, brak powierzchni do porownania"
            ),
            parcel=best.parcel,
            distance_m=best.distance_m,
            area_ratio=best.area_ratio,
        )

    return MatchResult(
        confidence="none",
        reason="zaden kandydat nie pasuje ani powierzchnia, ani polozeniem",
        alternatives=tuple(c.parcel.id_dzialki for c in candidates[:3]),
    )
