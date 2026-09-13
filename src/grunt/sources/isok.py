"""Strefy zagrozenia powodziowego z Hydroportalu ISOK.

Sekcja 5.3.7 dokumentu. Dla pomorskiego krytyczny jest scenariusz MORSKI (hWZ):
Zulawy, Mierzeja Wislana, Wyspa Sobieszewska, Stogi, Przerobka, Olszynka.
Znaczna czesc Zulaw lezy ponizej poziomu morza.

Zweryfikowane na zywo 2026-08-21: punkt oferty w Katach Rybackich na Mierzei
Wislanej trafia w warstwe hWZ, a punkt na wysoczyznie w Gdansku Kokoszkach
nie trafia w zadna. Usluga obsluguje GetFeatureInfo w formacie JSON, co jest
wyjatkiem wsrod uslug, z ktorych korzystamy.

Wagi scenariuszy: q10 (raz na 10 lat) to sygnal powazniejszy niz q0_2
(raz na 500 lat), bo dotyczy zdarzen, ktore realnie wystapia w okresie
kredytowania.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx

from grunt.sources import _http, geo

ISOK_WMS = "https://wody.isok.gov.pl/wss/INSPIRE/INSPIRE_NZ_HY_MZPMRP_WMS"

# Scenariusze w kolejnosci od najpowazniejszego
SCENARIUSZE: dict[str, str] = {
    "q10": "NZ.ExposedElement_q10",
    "q1": "NZ.ExposedElement_q1",
    "q0_2": "NZ.ExposedElement_q0_2",
    "hWZ": "NZ.ExposedElement_hWZ",
}

OPISY = {
    "q10": "powodz rzeczna raz na 10 lat",
    "q1": "powodz rzeczna raz na 100 lat",
    "q0_2": "powodz rzeczna raz na 500 lat",
    "hWZ": "powodz morska, scenariusz calkowitego zniszczenia walu",
}

# Mnozniki wartosci. Sekcja 5.3.3 podaje gate 0,55 dla strefy Q1%.
# q10 jest powazniejsze, q0_2 lagodniejsze.
GATE = {"q10": 0.40, "q1": 0.55, "hWZ": 0.60, "q0_2": 0.85}


class IsokError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FloodRisk:
    strefy: tuple[str, ...] = ()
    sprawdzone: tuple[str, ...] = ()
    bledy: tuple[str, ...] = field(default_factory=tuple)

    @property
    def zagrozona(self) -> bool:
        return bool(self.strefy)

    @property
    def najpowazniejsza(self) -> str | None:
        for kod in SCENARIUSZE:
            if kod in self.strefy:
                return kod
        return None

    @property
    def gate(self) -> float:
        """Najmocniejszy mnoznik sposrod trafionych scenariuszy."""
        return min((GATE[k] for k in self.strefy), default=1.0)

    @property
    def kompletne(self) -> bool:
        """Czy udalo sie sprawdzic wszystkie scenariusze."""
        return len(self.sprawdzone) == len(SCENARIUSZE)

    def to_dict(self) -> dict[str, object]:
        return {
            "strefy": list(self.strefy),
            "opisy": [OPISY[k] for k in self.strefy],
            "najpowazniejsza": self.najpowazniejsza,
            "gate": self.gate,
            "sprawdzone": list(self.sprawdzone),
            "kompletne": self.kompletne,
        }


def _ma_obiekty(tresc: str) -> bool:
    tekst = tresc.strip()
    if not tekst:
        return False
    if tekst.startswith("{"):
        try:
            return bool(json.loads(tekst).get("features"))
        except json.JSONDecodeError:
            return False
    # awaryjnie GML: pusty msGMLOutput ma ok. 200 bajtow i zaden element obiektu
    return "<gml:featureMember" in tekst or "ExposedElement" in tekst


def query(point: geo.PL1992, *, radius_m: float = 25.0, delay: float = 0.5) -> FloodRisk:
    """Sprawdzenie czterech scenariuszy powodziowych w punkcie."""
    trafione: list[str] = []
    sprawdzone: list[str] = []
    bledy: list[str] = []

    for kod, warstwa in SCENARIUSZE.items():
        params = geo.wms_getfeatureinfo_params(
            warstwa, point, radius_m=radius_m, info_format="application/json"
        )
        try:
            response = _http.get(ISOK_WMS, params=params, delay=delay, timeout=60)
        except httpx.HTTPError as exc:
            bledy.append(f"{kod}: {exc}")
            continue
        sprawdzone.append(kod)
        if _ma_obiekty(response.text):
            trafione.append(kod)

    if bledy and not sprawdzone:
        raise IsokError(f"ISOK niedostepny: {bledy[0]}")

    return FloodRisk(strefy=tuple(trafione), sprawdzone=tuple(sprawdzone), bledy=tuple(bledy))
