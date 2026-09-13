"""Testy segmentacji rynku. Nazwy przeznaczen sa dokladnie takie, jak zwraca RCN."""

from __future__ import annotations

from dataclasses import dataclass

from grunt.scoring import segments


def test_przeznaczenie_ma_pierwszenstwo_przed_ewidencja() -> None:
    """Dzialka "rolna" w ewidencji, ale budowlana w MPZP, to dzialka budowlana."""
    assert (
        segments.classify("budownictwoMieszkanioweJednorodzinne", "gruntyRolne")
        == "mieszkaniowa_jednorodzinna"
    )


def test_lista_przeznaczen_rozstrzygana_po_kolejnosci_regul() -> None:
    """Wielorodzinna wygrywa z jednorodzinna, bo jest wyzej w regulach."""
    assert (
        segments.classify("budownictwoMieszkanioweJednorodzinne;terenZabudowyUslugowej")
        == "mieszkaniowa_jednorodzinna"
    )
    assert (
        segments.classify(
            "budownictwoMieszkanioweWielorodzinne;budownictwoMieszkanioweJednorodzinne"
        )
        == "mieszkaniowa_wielorodzinna"
    )


def test_teren_rolniczy_to_nie_to_samo_co_grunty_rolne() -> None:
    """terenRolniczy w MPZP (16,6 zl/m2) to pewna informacja.

    gruntyRolne w ewidencji (104 zl/m2) to informacja niepewna, bo pod
    Trojmiastem oznacza czesto dzialke budowlana przed odrolnieniem.
    """
    assert segments.classify("terenRolniczy", None) == "rolna"
    assert segments.classify(None, "gruntyRolne") == "nieokreslona_rolna"
    assert segments.classify("", "gruntyZabudowaneIZurbanizowane") == "nieokreslona_zurbanizowana"


def test_brak_mpzp_nie_jest_traktowany_jak_przeznaczenie() -> None:
    """brakMPZPLubWZ to informacja o braku planu, a nie o funkcji terenu."""
    assert segments.classify("brakMPZPLubWZ", "gruntyRolne") == "nieokreslona_rolna"
    assert segments.classify("innyNiewymieniony", None) == "nieokreslona"


def test_bez_zadnej_informacji_wychodzi_nieokreslona() -> None:
    assert segments.classify(None, None) == "nieokreslona"


def test_drogi_i_lasy_rozpoznawane_z_obu_zrodel() -> None:
    assert segments.classify("terenDrogWewnetrznych") == "droga"
    assert segments.classify(None, "terenyKomunikacyjne") == "droga"
    assert segments.classify("terenLesny") == "lesna"
    assert segments.classify(None, "gruntyLesne") == "lesna"


@dataclass(frozen=True)
class Item:
    segment: str
    level: str


def select(items: list[Item], target: str, **kwargs):
    return segments.select_by_segment(
        items,
        target,  # type: ignore[arg-type]
        segment_of=lambda i: i.segment,
        level_of=lambda i: i.level,
        **kwargs,
    )


def test_wystarczajaco_danych_w_segmencie_nie_rozszerza_doboru() -> None:
    items = [Item("mieszkaniowa_jednorodzinna", "obreb") for _ in range(20)]
    items += [Item("rolna", "obreb") for _ in range(20)]
    selected, used = select(items, "mieszkaniowa_jednorodzinna")
    assert len(selected) == 20
    assert used == ("mieszkaniowa_jednorodzinna",)


def test_za_malo_danych_dobiera_segmenty_pokrewne() -> None:
    items = [Item("mieszkaniowa_jednorodzinna", "obreb") for _ in range(3)]
    items += [Item("budowlana_wz", "gmina") for _ in range(15)]
    selected, used = select(items, "mieszkaniowa_jednorodzinna")
    assert len(selected) == 18
    assert used == ("mieszkaniowa_jednorodzinna", "budowlana_wz")


def test_dobor_wymaga_takze_danych_lokalnych() -> None:
    """20 transakcji z poziomu wojewodztwa to nie jest lokalny rynek."""
    items = [Item("rolna", "wojewodztwo") for _ in range(20)]
    items += [Item("lesna", "obreb") for _ in range(6)]
    selected, used = select(items, "rolna")
    assert "lesna" in used


def test_pusty_segment_docelowy_zwraca_wszystko_z_ostrzezeniem() -> None:
    items = [Item("uslugowa_produkcyjna", "gmina") for _ in range(5)]
    selected, used = select(items, "lesna")
    assert len(selected) == 5
    assert used[0] == "lesna"
    assert len(used) > 1  # wywolujacy wie, ze dobrano spoza segmentu


def test_nieokreslona_dobiera_swoje_podzbiory_przed_mpzp() -> None:
    """Dzialka bez wpisu przypomina inne dzialki bez wpisu bardziej niz te z planem."""
    assert segments.FALLBACKS["nieokreslona_rolna"][0] == "nieokreslona"
    assert segments.FALLBACKS["nieokreslona_zurbanizowana"][0] == "nieokreslona"
