"""Plany ogolne gmin: strefa planistyczna i Obszar Uzupelnienia Zabudowy.

Dlaczego to jest najwazniejsze zrodlo w calym projekcie (sekcja 5.3.3): po
reformie planistycznej dzialka polozona poza OUZ, bez MPZP i bez waznej decyzji
WZ praktycznie traci sciezke do zabudowy. To najsilniejszy pojedynczy determinant
wartosci gruntu w Polsce w tym momencie.

STAN POKRYCIA, zmierzony 2026-08-21 na 145 gminach pomorskiego, po jednym
punkcie na gmine wzietym z transakcji RCN:

    plan ogolny opublikowany w usludze:  14 gmin (9,7%)
    brak:                               131 gmin

To odpowiedz na otwarte pytanie nr 2 z sekcji 11 dokumentu ("ile gmin faktycznie
uchwalilo plany ogolne, zrodla sa sprzeczne"). Termin ustawowy to 31.08.2026,
czyli dziesiec dni po pomiarze, wiec pokrycie bedzie szybko rosnac i warto
powtarzac ten sondaz (scripts/survey_planning.py).

Konsekwencja projektowa: dla ponad 90% dzialek status planistyczny bedzie dzis
"brak planu ogolnego" i to jest poprawna informacja, a nie brak danych.
Scoring musi to odrozniac.

Pulapki potwierdzone na zywo:
* GetFeatureInfo NIE obsluguje application/json, tylko GML, XML, plain i HTML
* warstwy maja MaxScaleDenominator = 100001, wiec zapytanie z duzego obszaru
  zwraca pusty obraz i pusty wynik. Dokument mowi o granicy 1:5000, ale usluga
  podaje 1:100000
* pusta odpowiedz (212 bajtow) to poprawny wynik: w tym punkcie nic nie ma
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import httpx

from grunt.sources import _http, geo
from grunt.sources.gml import parse_ms_gml_output

POG_WMS = "https://mapy.geoportal.gov.pl/wss/ext/PlanyOgolneGmin"

LAYER_STREFA = "strefaPlanistyczna"
LAYER_OUZ = "obszarUzupelnieniaZabudowy"
LAYER_SRODMIESCIE = "obszarZabSrodmiejskiej"
LAYER_AKT = "aktPlanowaniaprzestrzennego"

# Trzynascie stref planu ogolnego (sekcja 5.3.3 dokumentu)
STREFY: dict[str, str] = {
    "SW": "wielofunkcyjna z zabudowa mieszkaniowa wielorodzinna",
    "SJ": "wielofunkcyjna z zabudowa mieszkaniowa jednorodzinna",
    "SZ": "wielofunkcyjna z zabudowa zagrodowa",
    "SU": "uslugowa",
    "SH": "handlu wielkopowierzchniowego",
    "SP": "gospodarcza",
    "SR": "produkcji rolniczej",
    "SI": "infrastrukturalna",
    "SN": "zieleni i rekreacji",
    "SC": "cmentarzy",
    "SG": "gornictwa",
    "SO": "otwarta",
    "SK": "komunikacyjna",
}

# Strefy, w ktorych zabudowa mieszkaniowa jest przewidziana wprost
STREFY_MIESZKANIOWE = frozenset({"SW", "SJ", "SZ"})
STREFY_BUDOWLANE = STREFY_MIESZKANIOWE | frozenset({"SU", "SH", "SP"})


class PlanOgolnyError(RuntimeError):
    pass


def _liczba(value: str | None) -> float | None:
    """Wartosc liczbowa wskaznika. Pusty string i myslnik to brak, nie zero."""
    if value is None:
        return None
    tekst = value.strip().replace(",", ".")
    if not tekst or tekst in {"-", "brak", "nie dotyczy"}:
        return None
    try:
        return float(tekst)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class WskaznikiZabudowy:
    """Cztery liczby, ktore strefa planistyczna narzuca zabudowie.

    Sprawdzone zywym zapytaniem 25.08.2026: warstwa strefaPlanistyczna oddaje je
    w tym samym GetFeatureInfo, ktorym i tak pytamy o symbol strefy, wiec filar
    chlonnosci nie kosztuje ani jednego zapytania wiecej. Przyklady z Gdyni:
    SJ ma intensywnosc 0,4 / zabudowe 25% / wysokosc 9 m / biologicznie czynne
    50%, a SW odpowiednio 2,5 / 50% / 17 m / 30%.

    Kazde pole moze byc None i to nie jest to samo co zero: strefa gospodarcza
    bez limitu wysokosci ma tu None, a nie 0 m.
    """

    maks_intensywnosc: float | None = None
    maks_udzial_zabudowy_proc: float | None = None
    maks_wysokosc_m: float | None = None
    min_biologicznie_czynne_proc: float | None = None

    @property
    def pusty(self) -> bool:
        return all(
            v is None
            for v in (
                self.maks_intensywnosc,
                self.maks_udzial_zabudowy_proc,
                self.maks_wysokosc_m,
                self.min_biologicznie_czynne_proc,
            )
        )

    def to_dict(self) -> dict[str, float | None]:
        return {
            "maks_intensywnosc": self.maks_intensywnosc,
            "maks_udzial_zabudowy_proc": self.maks_udzial_zabudowy_proc,
            "maks_wysokosc_m": self.maks_wysokosc_m,
            "min_biologicznie_czynne_proc": self.min_biologicznie_czynne_proc,
        }


def wskazniki_ze_strefy(strefa: dict[str, str]) -> WskaznikiZabudowy:
    """Wskazniki wyluskane z surowej odpowiedzi warstwy strefaPlanistyczna."""
    return WskaznikiZabudowy(
        maks_intensywnosc=_liczba(strefa.get("maksNadziemnaIntensywnoscZabudowy")),
        maks_udzial_zabudowy_proc=_liczba(strefa.get("maksUdzialPowierzchniZabudowy")),
        maks_wysokosc_m=_liczba(strefa.get("maksWysokoscZabudowy")),
        min_biologicznie_czynne_proc=_liczba(strefa.get("minUdzialPowierzchniBiologicznieCzynnej")),
    )


@dataclass(frozen=True, slots=True)
class PlanOgolnyInfo:
    """Co usluga wie o tym punkcie."""

    ma_plan: bool
    strefa_symbol: str | None = None
    strefa_oznaczenie: str | None = None
    w_ouz: bool | None = None
    w_srodmiesciu: bool | None = None
    akt_tytul: str | None = None
    obowiazuje_od: dt.date | None = None
    lacze: str | None = None
    wskazniki: WskaznikiZabudowy = field(default_factory=WskaznikiZabudowy)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def strefa_nazwa(self) -> str | None:
        return STREFY.get(self.strefa_symbol or "")

    @property
    def strefa_budowlana(self) -> bool | None:
        if self.strefa_symbol is None:
            return None
        return self.strefa_symbol in STREFY_BUDOWLANE

    def to_dict(self) -> dict[str, Any]:
        return {
            "ma_plan_ogolny": self.ma_plan,
            "strefa": self.strefa_symbol,
            "strefa_nazwa": self.strefa_nazwa,
            "oznaczenie": self.strefa_oznaczenie,
            "w_ouz": self.w_ouz,
            "akt": self.akt_tytul,
            "obowiazuje_od": self.obowiazuje_od.isoformat() if self.obowiazuje_od else None,
            "lacze": self.lacze,
            "wskazniki": self.wskazniki.to_dict(),
        }


def _parse_date(value: str | None) -> dt.date | None:
    """Usluga podaje daty jako '2026/04/17' albo '2026/05/05 07:06:21+00'."""
    if not value:
        return None
    head = value.strip().split(" ")[0].replace("/", "-")
    try:
        return dt.date.fromisoformat(head)
    except ValueError:
        return None


def _query_layer(
    point: geo.PL1992, layer: str, *, radius_m: float, delay: float
) -> list[dict[str, str]]:
    params = geo.wms_getfeatureinfo_params(
        layer, point, radius_m=radius_m, info_format="application/vnd.ogc.gml"
    )
    try:
        response = _http.get(POG_WMS, params=params, delay=delay, timeout=60)
    except httpx.HTTPError as exc:
        raise PlanOgolnyError(f"usluga planow ogolnych niedostepna: {exc}") from exc
    return parse_ms_gml_output(response.text)


def query(point: geo.PL1992, *, radius_m: float = 30.0, delay: float = 0.6) -> PlanOgolnyInfo:
    """Stan planistyczny w punkcie. Trzy zapytania: akt, strefa, OUZ.

    Kolejnosc ma znaczenie ekonomiczne: jesli gmina nie ma aktu, dwa kolejne
    zapytania sa zbedne. Przy pokryciu na poziomie 10% oszczedza to
    dwie trzecie ruchu.
    """
    akty = _query_layer(point, LAYER_AKT, radius_m=max(radius_m, 200), delay=delay)
    if not akty:
        return PlanOgolnyInfo(ma_plan=False)

    akt = akty[0]
    strefy = _query_layer(point, LAYER_STREFA, radius_m=radius_m, delay=delay)
    ouz = _query_layer(point, LAYER_OUZ, radius_m=radius_m, delay=delay)

    strefa = strefy[0] if strefy else {}
    return PlanOgolnyInfo(
        ma_plan=True,
        strefa_symbol=(strefa.get("symbol") or None),
        strefa_oznaczenie=(strefa.get("oznaczenie") or None),
        # Plan istnieje, wiec pusta odpowiedz warstwy OUZ znaczy "poza OUZ",
        # a nie "nie wiadomo". Ta roznica jest warta 60% wartosci dzialki.
        w_ouz=bool(ouz),
        akt_tytul=akt.get("tytul"),
        obowiazuje_od=_parse_date(akt.get("obowiazujeOd")),
        lacze=akt.get("lacze"),
        wskazniki=wskazniki_ze_strefy(strefa),
        raw={"akt": akt, "strefa": strefa, "ouz_obiektow": len(ouz)},
    )
