"""Testy kluczy deduplikacji. Wszystkie wartosci oczekiwane policzone recznie."""

from __future__ import annotations

from grunt.dedup import keys


def test_tokeny_gubia_ogonki_i_slowa_wystepujace_wszedzie() -> None:
    """Po odrzuceniu stopwordow zostaje to, co faktycznie roznicuje oferty."""
    assert keys.tokeny("Działka budowlana Kokoszki 1115 m2") == frozenset(
        {"budowlana", "kokoszki", "1115"}
    )
    # "Kąty" i "Katy" to ta sama miejscowosc, roznica jest tylko w zapisie
    assert keys.tokeny("Kąty Rybackie") == keys.tokeny("Katy Rybackie")


def test_tokeny_pustego_tytulu() -> None:
    assert keys.tokeny(None) == frozenset()
    assert keys.tokeny("dzialka na sprzedaz") == frozenset()


def test_pokrycie_liczone_wzgledem_krotszego_tytulu() -> None:
    """Krotszy tytul w calosci zawarty w dluzszym to pelne pokrycie, nie polowa."""
    a = keys.tokeny("Kokoszki 1115")
    b = keys.tokeny("Kokoszki 1115, blisko obwodnicy, media w drodze")
    assert keys.pokrycie_tokenow(a, b) == 1.0

    # {budowlana, kokoszki, 1115} vs {kokoszki, warunkami, zabudowy}: 1 z 3
    c = keys.tokeny("Działka budowlana Kokoszki 1115 m2")
    d = keys.tokeny("Kokoszki, działka z warunkami zabudowy")
    assert round(keys.pokrycie_tokenow(c, d), 3) == 0.333


def test_pokrycie_bez_tokenow_to_brak_sygnalu() -> None:
    assert keys.pokrycie_tokenow(frozenset(), keys.tokeny("Kokoszki")) == 0.0


def test_komorka_i_sasiedzi() -> None:
    """Punkt w Gdansku (EPSG:2180) i punkt 100 m dalej trafiaja w sasiedztwo."""
    a = keys.komorka(6_540_100.0, 6_027_300.0)
    b = keys.komorka(6_540_600.0, 6_027_300.0)
    assert a == (13080, 12054)
    assert b != a
    assert b in keys.sasiednie_komorki(a)
    assert len(keys.sasiednie_komorki(a)) == 9


def test_dystans_w_metrach() -> None:
    assert keys.dystans_m((0.0, 0.0), (3.0, 4.0)) == 5.0


def test_powierzchnia_zgodna_w_granicach_trzech_procent() -> None:
    assert keys.powierzchnia_zgodna(1000, 1030) is True  # dokladnie 3% z 1000
    assert keys.powierzchnia_zgodna(1000, 1031) is False
    # brak powierzchni to brak zgody, a nie zgoda domyslna (zasada: NULL to NULL)
    assert keys.powierzchnia_zgodna(1000, None) is False
    assert keys.powierzchnia_zgodna(None, None) is False


def test_cena_zgodna_w_granicach_pieciu_procent() -> None:
    assert keys.cena_zgodna(300_000_00, 315_000_00) is True
    assert keys.cena_zgodna(300_000_00, 316_000_00) is False
    assert keys.cena_zgodna(300_000_00, None) is False


def test_hamming_na_zapisie_bitowym_z_bazy() -> None:
    """BIT(64) wraca z psycopg jako ciag zer i jedynek."""
    a = "0" * 64
    b = "0" * 60 + "1111"
    assert keys.hamming(a, b) == 4
    assert keys.hamming(a, a) == 0
    # brak miniatury po ktorejkolwiek stronie to brak sygnalu, nie odleglosc 64
    assert keys.hamming(a, None) is None
    assert keys.hamming(None, None) is None


# ------------------------------------------------------- klucz z miniatury

# Prawdziwy adres z bazy, skrocony. Base64 rozkodowuje sie do adresu pliku
# na d-gr.cdngr.pl, ktory Morizon i Gratka pokazuja identycznie.
THUMB_GRATKA = (
    "https://img1.staticmorizon.com.pl/thumb/"
    "aHR0cHM6Ly9kLWdyLmNkbmdyLnBsL2thZHJ5L2svci9nci1vZ2wvZmUvMDIvNDg2MTUyNzcuanBn"
)
THUMB_MORIZON = THUMB_GRATKA + "?w=320"


def test_klucz_obrazu_rozkodowuje_przekaznik() -> None:
    assert keys.klucz_obrazu(THUMB_GRATKA) == (
        "https://d-gr.cdngr.pl/kadry/k/r/gr-ogl/fe/02/48615277.jpg"
    )


def test_ten_sam_plik_pod_roznymi_adresami_daje_ten_sam_klucz() -> None:
    """O to w tym kluczu chodzi: dwa portale, jeden plik, jeden klucz."""
    assert keys.klucz_obrazu(THUMB_GRATKA) == keys.klucz_obrazu(THUMB_MORIZON)


def test_klucz_obrazu_spoza_przekaznika_zostaje_adresem() -> None:
    """Portal z wlasnym CDN-em nadal ma klucz, tylko nie sklei sie z zewnetrznym."""
    assert keys.klucz_obrazu("https://i.st-nieruchomosci-online.pl/abc/dzialka.jpg?v=2") == (
        "https://i.st-nieruchomosci-online.pl/abc/dzialka.jpg"
    )


def test_klucz_obrazu_znosi_uciety_padding() -> None:
    """W adresach portalu koncowe "=" bywa ucinane, wiec dokladamy je sami."""
    bez_paddingu = "https://img1.staticmorizon.com.pl/thumb/aHR0cDovL2EucGwvYi5qcGc"
    assert keys.klucz_obrazu(bez_paddingu) == "http://a.pl/b.jpg"


def test_klucz_obrazu_nie_wybucha_na_smieciach() -> None:
    assert keys.klucz_obrazu(None) is None
    assert keys.klucz_obrazu("") is None
    # base64, ktore rozkodowuje sie do czegos, co nie jest adresem
    assert keys.klucz_obrazu("https://img1.staticmorizon.com.pl/thumb/YWJj") == (
        "https://img1.staticmorizon.com.pl/thumb/YWJj"
    )
