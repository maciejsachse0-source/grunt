"""Testy doboru par i oceny duplikatu. Punktacja policzona recznie z pairing.py."""

from __future__ import annotations

from grunt.dedup import pairing

# Punkt odniesienia: Gdansk Kokoszki w EPSG:2180
E0, N0 = 6_540_100.0, 6_027_300.0


def oferta(listing_id: int, **kwargs: object) -> pairing.Oferta:
    dane: dict[str, object] = {
        "portal": "morizon",
        "easting": E0,
        "northing": N0,
        "area_m2": 1000,
        "price_grosze": 300_000_00,
        "tytul": None,
    }
    dane.update(kwargs)
    return pairing.Oferta(id=listing_id, **dane)  # type: ignore[arg-type]


def test_ta_sama_dzialka_ewidencyjna_rozstrzyga_mimo_odleglosci() -> None:
    """Wspolrzedne z portali potrafia sie roznic o kilometr dla tej samej dzialki."""
    a = oferta(1, uldk_id="226101_1.0089.433/2", uldk_pewny=True)
    b = oferta(2, easting=E0 + 1200, uldk_id="226101_1.0089.433/2", uldk_pewny=True)

    werdykt = pairing.porownaj(a, b)
    assert werdykt is not None
    assert werdykt.pewnosc == 1.0
    assert werdykt.etap == "uldk"
    assert werdykt.do_klastra is True


def test_niepewne_dopasowanie_do_dzialki_nie_jest_twardym_kluczem() -> None:
    """parcel_match ponizej "high" to kandydat z ULDK, nie identyfikacja."""
    a = oferta(1, uldk_id="226101_1.0089.433/2", uldk_pewny=False)
    b = oferta(2, easting=E0 + 1200, uldk_id="226101_1.0089.433/2", uldk_pewny=False)

    assert pairing.porownaj(a, b) is None


def test_sam_telefon_nie_wystarcza_do_sklejenia() -> None:
    """Ten sam hash telefonu to ta sama agencja, a agencja ma wiele dzialek.

    Punktacja: powierzchnia 0,35 + telefon 0,25 = 0,60. Nad progiem zapisu
    (0,50), pod progiem klastra (0,70): para trafia do przejrzenia, nie do
    sklejenia.
    """
    telefon = "a" * 64
    a = oferta(1, phone_sha256=telefon)
    b = oferta(2, easting=E0 + 200, area_m2=1010, price_grosze=340_000_00, phone_sha256=telefon)

    werdykt = pairing.porownaj(a, b)
    assert werdykt is not None
    assert werdykt.pewnosc == 0.6
    assert werdykt.do_klastra is False
    assert werdykt.etap == "telefon"


def test_powierzchnia_tytul_i_bliskosc_daja_klaster() -> None:
    """0,35 (powierzchnia) + 0,30 (tytul >= 75%) + 0,10 (do 50 m) = 0,75."""
    a = oferta(1, tytul="Działka budowlana Kokoszki 1115 m2", price_grosze=300_000_00)
    b = oferta(
        2,
        portal="nieruchomosci-online",
        easting=E0 + 40,
        area_m2=1010,
        tytul="Kokoszki 1115 budowlana, media",
        price_grosze=340_000_00,  # ponad 5% roznicy, wiec bez punktu za cene
    )

    werdykt = pairing.porownaj(a, b)
    assert werdykt is not None
    assert werdykt.pewnosc == 0.75
    assert werdykt.etap == "tytul"
    assert werdykt.do_klastra is True


def test_identyczna_miniatura_jest_najsilniejszym_sygnalem() -> None:
    """0,35 (powierzchnia) + 0,55 (pHash 0) + 0,10 (do 50 m) = 1,00."""
    phash = "1010" * 16
    a = oferta(1, thumb_phash=phash)
    b = oferta(
        2,
        portal="nieruchomosci-online",
        easting=E0 + 30,
        price_grosze=340_000_00,
        thumb_phash=phash,
    )

    werdykt = pairing.porownaj(a, b)
    assert werdykt is not None
    assert werdykt.pewnosc == 1.0
    assert werdykt.etap == "phash"


def test_rozne_dzialki_w_tej_samej_okolicy_nie_sa_para() -> None:
    """Sasiednie dzialki o innej powierzchni i innym tytule: brak podejrzenia."""
    a = oferta(1, area_m2=1000, tytul="Działka budowlana Kokoszki")
    b = oferta(2, easting=E0 + 250, area_m2=3000, tytul="Grunt rolny Otomin, bez mediow")

    assert pairing.porownaj(a, b) is None


def test_daleko_od_siebie_nie_wchodzi_nawet_do_porownania() -> None:
    a = oferta(1, tytul="Kokoszki 1115 budowlana")
    b = oferta(2, easting=E0 + 400, tytul="Kokoszki 1115 budowlana")

    assert pairing.porownaj(a, b) is None
    assert pairing.znajdz([a, b]) == []


def test_werdykt_ma_zawsze_mniejszy_identyfikator_pierwszy() -> None:
    a = oferta(7, thumb_phash="0" * 64)
    b = oferta(3, easting=E0 + 20, thumb_phash="0" * 64)

    werdykt = pairing.porownaj(a, b)
    assert werdykt is not None
    assert (werdykt.a_id, werdykt.b_id) == (3, 7)


def test_blocking_nie_gubi_par_na_granicy_komorki() -> None:
    """Dwie oferty po dwoch stronach granicy siatki nadal trafiaja do pary."""
    lewa = 13080 * pairing.keys.ROZMIAR_KOMORKI_M  # koniec komorki 13080
    a = oferta(1, easting=float(lewa + 499), thumb_phash="0" * 64)
    b = oferta(2, easting=float(lewa + 501), thumb_phash="0" * 64)

    assert pairing.keys.komorka(a.easting, a.northing) != pairing.keys.komorka(
        b.easting, b.northing
    )
    assert len(pairing.znajdz([a, b])) == 1


def test_znajdz_sortuje_od_najpewniejszej() -> None:
    a = oferta(1, thumb_phash="0" * 64)
    b = oferta(2, easting=E0 + 20, thumb_phash="0" * 64)
    c = oferta(3, easting=E0 + 200, area_m2=1005, phone_sha256="b" * 64)
    d = oferta(4, easting=E0 + 220, area_m2=1005, phone_sha256="b" * 64)

    werdykty = pairing.znajdz([a, b, c, d])
    pewnosci = [w.pewnosc for w in werdykty]
    assert pewnosci == sorted(pewnosci, reverse=True)
    assert werdykty[0].pewnosc == 1.0


def test_dwie_sasiednie_dzialki_z_jednego_podzialu_nie_sklejaja_sie() -> None:
    """Tywezy 1409 m2 i 1387 m2 przy tej samej ulicy: tytul z Morizona jest
    generowany ze wzorca, wiec sam nie odroznia dzialki od sasiadki."""
    a = oferta(1, area_m2=1409, price_grosze=97_221_00, tytul="Działka na sprzedaż, Tywęzy")
    b = oferta(
        2,
        easting=E0 + 30,
        area_m2=1387,
        price_grosze=95_703_00,
        tytul="Działka na sprzedaż, Tywęzy",
    )

    werdykt = pairing.porownaj(a, b)
    assert werdykt is not None
    assert werdykt.pewnosc >= pairing.PROG_KLASTRA
    assert werdykt.do_klastra is False  # trafia do przejrzenia, nie do klastra
    assert werdykt.blokada is not None


def test_ta_sama_powierzchnia_co_do_metra_na_jednym_portalu_skleja() -> None:
    """Duplikat w obrebie portalu to to samo ogloszenie drugi raz, czyli ta sama liczba."""
    a = oferta(1, area_m2=1001, tytul="Działka na sprzedaż, 1001 m² Wodnica")
    b = oferta(2, easting=E0 + 10, area_m2=1001, tytul="Działka na sprzedaż, 1001 m² Wodnica")

    werdykt = pairing.porownaj(a, b)
    assert werdykt is not None
    assert werdykt.do_klastra is True
    assert werdykt.blokada is None


# ---------------------------------------------- twardy klucz z miniatury

OBRAZ = "https://d-gr.cdngr.pl/kadry/k/r/gr-ogl/fe/02/48615277_1551752063_dzialka.jpg"


def test_ta_sama_miniatura_rozstrzyga_mimo_odleglosci() -> None:
    """Morizon i Gratka podaja dla jednej oferty dwa rozne, przyblizone punkty.

    Roznica potrafi przekroczyc PROMIEN_M, wiec bez twardego klucza para nie
    powstalaby wcale. Ten sam plik na tym samym serwerze jest tozsamoscia,
    nie podobienstwem, wiec rozstrzyga sam.
    """
    a = oferta(1, portal="morizon", obraz_klucz=OBRAZ)
    b = oferta(2, portal="gratka", easting=E0 + 1200, obraz_klucz=OBRAZ)

    werdykt = pairing.porownaj(a, b)
    assert werdykt is not None
    assert werdykt.pewnosc == 1.0
    assert werdykt.etap == "obraz"
    assert werdykt.do_klastra is True


def test_rozne_miniatury_nie_daja_twardego_klucza() -> None:
    a = oferta(1, obraz_klucz=OBRAZ)
    b = oferta(2, easting=E0 + 1200, obraz_klucz=OBRAZ.replace("48615277", "48615278"))

    assert pairing.porownaj(a, b) is None


def test_brak_miniatury_nie_skleja_dwoch_ofert() -> None:
    """None == None jest prawda w Pythonie i to jest tu pulapka."""
    a = oferta(1, obraz_klucz=None)
    b = oferta(2, easting=E0 + 1200, obraz_klucz=None)

    assert pairing.porownaj(a, b) is None


def test_para_po_miniaturze_powstaje_mimo_blockingu() -> None:
    """Twardy klucz musi omijac siatke, tak samo jak ULDK."""
    oferty = [
        oferta(1, portal="morizon", obraz_klucz=OBRAZ),
        oferta(2, portal="gratka", easting=E0 + 5000, northing=N0 + 5000, obraz_klucz=OBRAZ),
    ]

    werdykty = pairing.znajdz(oferty)
    assert [w.etap for w in werdykty] == ["obraz"]


def test_dzialka_ewidencyjna_ma_pierwszenstwo_przed_miniatura() -> None:
    """Oba klucze daja 1.0, ale etap ma nazywac mocniejsza przeslanke."""
    a = oferta(1, uldk_id="226101_1.0089.433/2", uldk_pewny=True, obraz_klucz=OBRAZ)
    b = oferta(2, uldk_id="226101_1.0089.433/2", uldk_pewny=True, obraz_klucz=OBRAZ)

    werdykt = pairing.porownaj(a, b)
    assert werdykt is not None
    assert werdykt.etap == "uldk"
