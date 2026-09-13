"""Klastrowanie par w grupy duplikatow (etap 6 sekcji 4.3).

Union-Find na parach powyzej progu. Identyfikatorem klastra jest najmniejszy
identyfikator oferty w grupie: nie potrzeba sekwencji, a ten sam zbior ofert
zawsze daje ten sam numer, wiec dwa przebiegi po tych samych danych nie
przemielaja bazy bez powodu.

Oferta bez pary nie dostaje klastra. cluster_id zostaje NULL, bo "sama sobie
jest klastrem" trzeba by potem wszedzie odfiltrowywac, a NULL czyta sie wprost:
nie znaleziono duplikatu.
"""

from __future__ import annotations

from dataclasses import dataclass

from grunt.dedup.pairing import Oferta, Werdykt


class UnionFind:
    """Zbiory rozlaczne z kompresja sciezki. Kilkaset elementow, wiec bez rangi."""

    def __init__(self) -> None:
        self._rodzic: dict[int, int] = {}

    def znajdz(self, x: int) -> int:
        self._rodzic.setdefault(x, x)
        korzen = x
        while self._rodzic[korzen] != korzen:
            korzen = self._rodzic[korzen]
        while self._rodzic[x] != korzen:
            self._rodzic[x], x = korzen, self._rodzic[x]
        return korzen

    def polacz(self, a: int, b: int) -> None:
        # Mniejszy identyfikator zostaje korzeniem, zeby numer klastra byl
        # powtarzalny niezaleznie od kolejnosci par.
        ka, kb = self.znajdz(a), self.znajdz(b)
        if ka == kb:
            return
        if kb < ka:
            ka, kb = kb, ka
        self._rodzic[kb] = ka

    def grupy(self) -> dict[int, list[int]]:
        wynik: dict[int, list[int]] = {}
        for element in self._rodzic:
            wynik.setdefault(self.znajdz(element), []).append(element)
        return {korzen: sorted(czlonkowie) for korzen, czlonkowie in wynik.items()}


@dataclass(frozen=True, slots=True)
class Klaster:
    """Grupa ofert opisujacych te sama dzialke."""

    cluster_id: int
    czlonkowie: tuple[int, ...]
    kanoniczna: int
    portale: tuple[str, ...]
    cena_min_grosze: int | None
    cena_max_grosze: int | None

    @property
    def rozrzut_cen(self) -> float | None:
        """Rozrzut cen miedzy portalami sam w sobie jest sygnalem (sekcja 4.3)."""
        if not self.cena_min_grosze or not self.cena_max_grosze:
            return None
        return (self.cena_max_grosze - self.cena_min_grosze) / self.cena_min_grosze


def przypisz(werdykty: list[Werdykt]) -> dict[int, int]:
    """Mapa listing_id -> cluster_id dla par uznanych za duplikaty."""
    uf = UnionFind()
    for werdykt in werdykty:
        if werdykt.do_klastra:
            uf.polacz(werdykt.a_id, werdykt.b_id)

    przypisanie: dict[int, int] = {}
    for korzen, czlonkowie in uf.grupy().items():
        if len(czlonkowie) < 2:
            continue
        for czlonek in czlonkowie:
            przypisanie[czlonek] = korzen
    return przypisanie


def _kompletnosc(oferta: Oferta) -> int:
    return sum(
        1
        for pole in (oferta.area_m2, oferta.price_grosze, oferta.thumb_phash, oferta.uldk_id)
        if pole
    )


def kanoniczna(oferty: list[Oferta]) -> int:
    """Rekord kanoniczny klastra: najbogatszy w dane, przy remisie najtanszy.

    Najbogatszy, a nie najtanszy wprost, bo to on trafia na liste i to jego
    braki widac. Cena i tak jest pokazywana jako zakres po wszystkich zrodlach.
    """
    return min(
        oferty,
        key=lambda o: (
            -_kompletnosc(o),
            o.price_grosze if o.price_grosze else 1 << 62,
            o.id,
        ),
    ).id


def podsumuj(oferty: list[Oferta], przypisanie: dict[int, int]) -> list[Klaster]:
    """Opis kazdego klastra: sklad, rekord kanoniczny, rozrzut cen."""
    po_id = {oferta.id: oferta for oferta in oferty}
    grupy: dict[int, list[Oferta]] = {}
    for listing_id, cluster_id in przypisanie.items():
        if listing_id in po_id:
            grupy.setdefault(cluster_id, []).append(po_id[listing_id])

    klastry: list[Klaster] = []
    for cluster_id, czlonkowie in sorted(grupy.items()):
        ceny = sorted(o.price_grosze for o in czlonkowie if o.price_grosze)
        klastry.append(
            Klaster(
                cluster_id=cluster_id,
                czlonkowie=tuple(sorted(o.id for o in czlonkowie)),
                kanoniczna=kanoniczna(czlonkowie),
                portale=tuple(sorted({o.portal for o in czlonkowie})),
                cena_min_grosze=ceny[0] if ceny else None,
                cena_max_grosze=ceny[-1] if ceny else None,
            )
        )
    return klastry
