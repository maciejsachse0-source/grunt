"""Dobor par kandydatow i ocena, czy to ta sama dzialka.

Kolejnosc etapow jest ta z sekcji 4.3: od najtanszego i deterministycznego do
najdrozszego. Etap 1 (twarde klucze) rozstrzyga sam. Twarde klucze sa dwa:
dzialka ewidencyjna z ULDK i adres pliku miniatury (keys.klucz_obrazu). Etapy 2-4 skladaja sie
w punktacje, bo zaden z nich osobno nie jest dowodem:

* sam hash telefonu oznacza te sama agencje, nie te sama dzialke. Agencja ma
  kilkadziesiat ofert w jednym powiecie, wiec telefon bez geometrii to fabryka
  falszywych duplikatow. W dokumencie stoi on w etapie 1 razem z ULDK i to
  jedyne miejsce, w ktorym swiadomie odchodzimy od jego ukladu;
* sam pHash lapie agencje wrzucajaca ten sam baner na kazde ogloszenie;
* sam tytul lapie dwie sasiednie dzialki z tego samego osiedla.

Dopiero razem, w jednym miejscu i przy zgodnej powierzchni, znacza duplikat.
Progi sa jawne i wszystkie skladniki wchodza do powodu, zeby dalo sie
zobaczyc, dlaczego para zostala uznana.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Final

from grunt.dedup import keys

PROMIEN_M: Final = 300.0
TOLERANCJA_POWIERZCHNI: Final = 0.03
TOLERANCJA_CENY: Final = 0.05
PROG_PHASH: Final = 8
PROG_PHASH_PEWNY: Final = 2
PROG_TYTULU_WYSOKI: Final = 0.75
PROG_TYTULU: Final = 0.55

# Ponizej PROG_ZAPISU para nie trafia nawet do tabeli. Miedzy PROG_ZAPISU
# a PROG_KLASTRA para jest zapisana jako podejrzenie, ale nie skleja ofert:
# to material do recznego przejrzenia, nie decyzja.
PROG_ZAPISU: Final = 0.50
PROG_KLASTRA: Final = 0.70

PEWNOSC_ULDK: Final = 1.0
# Ten sam plik miniatury na tym samym serwerze. Uzasadnienie pomiarem
# jest w keys.klucz_obrazu(): zero kolizji w obrebie portalu, 238 na 238
# par miedzyportalowych z identyczna cena.
PEWNOSC_OBRAZU: Final = 1.0


@dataclass(frozen=True, slots=True)
class Oferta:
    """Minimum potrzebne do porownania. Zadnych danych kontaktowych poza hashem."""

    id: int
    portal: str
    easting: float
    northing: float
    area_m2: int | None = None
    price_grosze: int | None = None
    tytul: str | None = None
    phone_sha256: str | None = None
    thumb_phash: str | int | None = None
    obraz_klucz: str | None = None
    uldk_id: str | None = None
    uldk_pewny: bool = False

    @property
    def punkt(self) -> tuple[float, float]:
        return (self.easting, self.northing)


@dataclass(frozen=True, slots=True)
class Werdykt:
    """Ocena jednej pary. a_id jest zawsze mniejsze od b_id."""

    a_id: int
    b_id: int
    pewnosc: float
    etap: str
    powody: tuple[str, ...] = field(default_factory=tuple)
    # Powod, dla ktorego para mimo wysokiej punktacji nie skleja ofert.
    blokada: str | None = None

    @property
    def do_klastra(self) -> bool:
        return self.pewnosc >= PROG_KLASTRA and self.blokada is None


def bloki(oferty: list[Oferta]) -> dict[tuple[int, int], list[int]]:
    """Indeks komorka siatki -> pozycje ofert. Etap 2 z sekcji 4.3."""
    wynik: dict[tuple[int, int], list[int]] = {}
    for i, oferta in enumerate(oferty):
        wynik.setdefault(keys.komorka(oferta.easting, oferta.northing), []).append(i)
    return wynik


def pary_kandydatow(oferty: list[Oferta]) -> Iterator[tuple[Oferta, Oferta]]:
    """Pary do porownania: z tej samej komorki, z sasiednich i po tym samym ULDK.

    Twardy klucz omija blocking celowo. Wspolrzedne z portali potrafia sie
    roznic o kilkaset metrow dla tej samej dzialki (punkt 5 sekcji "Czego
    nauczyly nas dane"), wiec dwie oferty z tym samym idDzialki musza trafic
    do pary nawet wtedy, gdy siatka je rozdzielila.
    """
    indeks = bloki(oferty)
    widziane: set[tuple[int, int]] = set()

    for i, oferta in enumerate(oferty):
        for sasiad in keys.sasiednie_komorki(keys.komorka(oferta.easting, oferta.northing)):
            for j in indeks.get(sasiad, ()):
                if j <= i:
                    continue
                para = (i, j)
                if para in widziane:
                    continue
                widziane.add(para)
                yield oferty[i], oferty[j]

    po_uldk: dict[str, list[int]] = {}
    for i, oferta in enumerate(oferty):
        if oferta.uldk_id and oferta.uldk_pewny:
            po_uldk.setdefault(oferta.uldk_id, []).append(i)

    # Drugi twardy klucz: ten sam plik miniatury. Blocking omija z tego samego
    # powodu co ULDK - Morizon i Gratka podaja dla jednej oferty dwa rozne
    # punkty, wiec siatka potrafi je rozdzielic mimo identycznego zdjecia.
    po_obrazie: dict[str, list[int]] = {}
    for i, oferta in enumerate(oferty):
        if oferta.obraz_klucz:
            po_obrazie.setdefault(oferta.obraz_klucz, []).append(i)

    for indeks_twardy in (po_uldk, po_obrazie):
        for pozycje in indeks_twardy.values():
            for a in range(len(pozycje)):
                for b in range(a + 1, len(pozycje)):
                    para = (min(pozycje[a], pozycje[b]), max(pozycje[a], pozycje[b]))
                    if para in widziane:
                        continue
                    widziane.add(para)
                    yield oferty[para[0]], oferty[para[1]]


def _blokada(a: Oferta, b: Oferta, etapy: list[tuple[float, str]]) -> str | None:
    """Kiedy wysoka punktacja mimo wszystko nie wystarcza do sklejenia ofert.

    Pomiar na wlasnych danych (364 aktywne oferty, sierpien 2026): tytuly na
    Morizonie sa generowane ze wzorca "Dzialka na sprzedaz, {powierzchnia} m2
    {miejscowosc}". Dwie sasiednie dzialki z jednego podzialu maja wiec
    identyczny tytul, ten sam punkt na mapie i powierzchnie roznia sie o kilka
    procent. Punktacja nie odroznia ich od prawdziwego duplikatu, bo nie ma
    czym: pHash i hash telefonu sa dzis w bazie puste dla wszystkich ofert.

    W obrebie jednego portalu duplikat to zwykle to samo ogloszenie wystawione
    drugi raz, wiec deklarowana powierzchnia jest identyczna co do metra.
    Roznica w granicach tolerancji oznacza tam raczej dwie rozne dzialki
    (przyklad: Tywezy 1409 m2 i 1387 m2 przy tej samej ulicy). Miedzy portalami
    tolerancja zostaje, bo kazdy portal zaokragla po swojemu.
    """
    if a.portal != b.portal:
        return None
    if any(etap in ("phash", "telefon") for _, etap in etapy):
        return None
    if a.area_m2 and b.area_m2 and a.area_m2 == b.area_m2:
        return None
    return (
        "ten sam portal, rozna deklarowana powierzchnia i brak sygnalu tozsamosci "
        "(pHash, telefon): to moga byc dwie sasiednie dzialki z jednego podzialu"
    )


def porownaj(a: Oferta, b: Oferta) -> Werdykt | None:
    """Ocena jednej pary. None, gdy nie ma nawet podejrzenia."""
    if a.id > b.id:
        a, b = b, a

    if a.uldk_id and a.uldk_id == b.uldk_id and a.uldk_pewny and b.uldk_pewny:
        return Werdykt(
            a_id=a.id,
            b_id=b.id,
            pewnosc=PEWNOSC_ULDK,
            etap="uldk",
            powody=(f"ta sama dzialka ewidencyjna {a.uldk_id}",),
        )

    if a.obraz_klucz and a.obraz_klucz == b.obraz_klucz:
        return Werdykt(
            a_id=a.id,
            b_id=b.id,
            pewnosc=PEWNOSC_OBRAZU,
            etap="obraz",
            powody=("ta sama miniatura: " + a.obraz_klucz,),
        )

    dystans = keys.dystans_m(a.punkt, b.punkt)
    if dystans > PROMIEN_M:
        return None

    punkty = 0.0
    powody: list[str] = [f"odleglosc {dystans:.0f} m"]
    etapy: list[tuple[float, str]] = []

    if keys.powierzchnia_zgodna(a.area_m2, b.area_m2, TOLERANCJA_POWIERZCHNI):
        punkty += 0.35
        powody.append(f"powierzchnia {a.area_m2} m2 vs {b.area_m2} m2")

    odleglosc_phash = keys.hamming(a.thumb_phash, b.thumb_phash)
    if odleglosc_phash is not None and odleglosc_phash <= PROG_PHASH:
        waga = 0.55 if odleglosc_phash <= PROG_PHASH_PEWNY else 0.45
        punkty += waga
        powody.append(f"pHash miniatury, odleglosc Hamminga {odleglosc_phash}")
        etapy.append((waga, "phash"))

    if a.phone_sha256 and a.phone_sha256 == b.phone_sha256:
        punkty += 0.25
        powody.append("ten sam hash telefonu (ten sam wystawiajacy)")
        etapy.append((0.25, "telefon"))

    pokrycie = keys.pokrycie_tokenow(keys.tokeny(a.tytul), keys.tokeny(b.tytul))
    if pokrycie >= PROG_TYTULU_WYSOKI:
        punkty += 0.30
        powody.append(f"pokrycie tytulow {pokrycie:.0%}")
        etapy.append((0.30, "tytul"))
    elif pokrycie >= PROG_TYTULU:
        punkty += 0.15
        powody.append(f"pokrycie tytulow {pokrycie:.0%}")
        etapy.append((0.15, "tytul"))

    if keys.cena_zgodna(a.price_grosze, b.price_grosze, TOLERANCJA_CENY):
        punkty += 0.10
        powody.append("cena w granicach 5%")

    if dystans <= 50.0:
        punkty += 0.10

    if punkty < PROG_ZAPISU:
        return None

    blokada = _blokada(a, b, etapy)
    if blokada:
        powody.append(blokada)

    # Etap nazywa przeslanke, ktora rozstrzygnela. Zgodna powierzchnia
    # i bliskosc to blocking (etap 2), czyli warunek wstepny kazdej pary,
    # wiec same z siebie niczego nie rozstrzygaja.
    etap = max(etapy)[1] if etapy else "geometria"
    return Werdykt(
        a_id=a.id,
        b_id=b.id,
        pewnosc=min(1.0, round(punkty, 3)),
        etap=etap,
        powody=tuple(powody),
        blokada=blokada,
    )


def znajdz(oferty: list[Oferta]) -> list[Werdykt]:
    """Wszystkie pary powyzej progu zapisu, posortowane od najpewniejszej."""
    werdykty = [w for w in (porownaj(a, b) for a, b in pary_kandydatow(oferty)) if w is not None]
    werdykty.sort(key=lambda w: (-w.pewnosc, w.a_id, w.b_id))
    return werdykty
