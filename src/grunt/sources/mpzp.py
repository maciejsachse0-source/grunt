"""Miejscowe plany zagospodarowania przestrzennego z Rejestru Urbanistycznego.

To odpowiedz na otwarte pytanie nr 1 z sekcji 11 dokumentu ("adresow WFS
Rejestru Urbanistycznego nie ma w publicznej dokumentacji, trzeba je odczytac
z zakladki Network"). Adresy sa w zakladce "Uslugi sieciowe" aplikacji, ale
tylko pod przyciskiem kopiujacym do schowka, wiec w DOM ich nie widac.
Odczytane 2026-08-24:

    plany ogolne      WMS  /uslugi-sieciowe/wms-pog/wms
                      WFS  /uslugi-sieciowe/app-pog/wfs
    MPZP              WMS  /uslugi-sieciowe/wms-mpzp/wms
                      WFS  /uslugi-sieciowe/app-mpzp/wfs
    uchwaly krajobr.  WMS  /uslugi-sieciowe/wms-uk/wms
                      WFS  /uslugi-sieciowe/app-uk/wfs
    plany wojewodzkie WMS  /uslugi-sieciowe/wms-pzpw/wms
                      WFS  /uslugi-sieciowe/app-pzpw/wfs
    audyty krajobr.   WMS  /uslugi-sieciowe/wms-ak/wms
                      WFS  /uslugi-sieciowe/app-ak/wfs
    metadane          CSW  /uslugi-sieciowe/csw

REST APLIKACJI, odczytany z ruchu sieciowego 25.08.2026. Sekcja 25.2 dokumentu
zostawila to jako "nadal otwarte", bo z linii polecen widac tylko powloke
Angulara. Przez przegladarke kontrakt jest jednoznaczny:

    GET  /api/public/published/territorial/tree?level=COMMUNE   -> 200, 240 kB
    POST /api/public/published/query                            -> lista aktow

Drzewo jednostek dziala wprost i nie wymaga niczego poza naglowkiem Accept.
POST /query odrzuca puste cialo bledem 3000 ("dane nie spelniaja wymagan"),
a na zgadywane ksztalty odpowiada 5000, wiec pola trzeba odczytac z aplikacji,
zanim ktokolwiek go tu wpisze. Wyszukiwarka MPZP ma pole "Wyszukaj identyfikator
dzialki", wiec ten endpoint UMIE odpowiedziec "ktore akty obejmuja te dzialke".

TO NIE ODBLOKOWUJE STANU A i tu jest sedno. Blokerem nie sa adresy, tylko to,
ze przeznaczenia terenu nie ma w zadnej postaci danych. Sprawdzone 25.08.2026
na obiekcie RysunekAktuPlanowaniaPrzestrzennego: pole "lacze" prowadzi do
GEOREFERENCOWANEGO TIFF-a (przyklad: mhrubieszow.e-mapa.net/wykazplanow/tiff/...),
a "legenda" do strony HTML z objasnieniem znakow. Rozdzielczosc przestrzenna
1000. Symbol MN albo MW jest wiec pikselem na skanie, a nie atrybutem, i zeby
go odczytac trzeba by interpretowac raster.

Dla porownania plan ogolny (app-pog) wystawia StrefaPlanistyczna jako obiekt
z atrybutami, razem ze wskaznikami zabudowy. Stad asymetria: strefe planu
ogolnego znamy co do liczby, a przeznaczenie MPZP tylko z faktu objecia planem.

CO TA USLUGA DAJE, A CZEGO NIE

Daje granice aktu (zasiegPrzestrzenny), tytul, date wejscia w zycie, status
i identyfikator IIP, w ktorym siedzi TERYT gminy. To wystarcza, zeby powiedziec
"dzialka jest objeta MPZP", czyli rozstrzygnac stan A z sekcji 5.3.3.

NIE daje przeznaczenia terenu. W tej usludze sa tylko trzy typy obiektow:
AktPlanowaniaPrzestrzennego, DokumentFormalny i RysunekAktuPlanowaniaPrzestrzennego.
Symbolu przeznaczenia (MN, U, MW) tu nie ma, wiec status A ustalamy na podstawie
objecia planem, a nie na podstawie symbolu. To jest zawezenie, nie oszustwo:
w scoring/planning.py "A" bez symbolu ma inne uzasadnienie niz "A" z symbolem.

POKRYCIE, zmierzone 2026-08-24:
    caly kraj:     524 akty
    pomorskie:     111 aktow, wszystkie z Gdanska (TERYT 226101)

Czyli podobnie jak przy planach ogolnych: brak aktu w rejestrze NIE znaczy, ze
gmina nie ma MPZP. Znaczy tylko tyle, ze go tu jeszcze nie opublikowala. Ta
roznica musi byc widoczna w wyniku, dlatego zwracamy "nie znaleziono", a nie
"nie ma planu".

PULAPKA OSI. BBOX z krotkim kodem (EPSG:2180) ta usluga czyta jako
easting,northing, a z forma urn (urn:ogc:def:crs:EPSG::2180) jako
northing,easting. Sprawdzone na Hrubieszowie: obie kombinacje daja te same
13 obiektow, pomylone daja zero. Geometrie w odpowiedzi maja srsName w formie
starszej, czyli easting northing - odwrotnie niz RCN. Kolejnosc rozstrzyga
gml.kolejnosc_easting_first(), nigdy zalozenie w tym pliku.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Final
from xml.etree import ElementTree as ET

from grunt.sources import _http, geo
from grunt.sources.gml import geometry_to_wkt, text_of

REJESTR = "https://rejestr-urbanistyczny.gov.pl/uslugi-sieciowe"

# REST aplikacji. Nieuzywany w kodzie: drzewo jednostek nie wnosi nic ponad
# TERYT, ktory juz mamy, a /query wymaga kontraktu, ktorego nie znamy. Stoi tu,
# zeby nikt nie szukal tych adresow drugi raz.
REJESTR_API: Final = "https://rejestr-urbanistyczny.gov.pl/api/public/published"
API_DRZEWO_JPT: Final = f"{REJESTR_API}/territorial/tree"
API_QUERY: Final = f"{REJESTR_API}/query"

WFS_MPZP: Final = f"{REJESTR}/app-mpzp/wfs"
WFS_PLAN_OGOLNY: Final = f"{REJESTR}/app-pog/wfs"
WMS_MPZP: Final = f"{REJESTR}/wms-mpzp/wms"

TYP_AKT: Final = "app-mpzp:AktPlanowaniaPrzestrzennego"

APP: Final = "https://www.gov.pl/static/zagospodarowanieprzestrzenne/schemas/app/2.0"

# Promien, w ktorym szukamy aktow wokol punktu. Akt bywa duzy, ale nas
# interesuje ten, ktory punkt zawiera, wiec bierzemy waskie okno i sprawdzamy
# zawieranie dokladnie.
PROMIEN_SZUKANIA_M: Final = 50.0


class MpzpError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AktMpzp:
    """Jeden akt planowania przestrzennego z rejestru."""

    lokalny_id: str
    przestrzen_nazw: str
    tytul: str | None
    obowiazuje_od: dt.date | None
    status: str | None
    typ_planu: str | None
    geometria_wkt: str | None

    @property
    def teryt_gmina(self) -> str | None:
        """TERYT gminy siedzi w przestrzeni nazw: PL.ZIPPZP.2000/226101-MPZP."""
        ogon = self.przestrzen_nazw.rsplit("/", 1)[-1]
        kod = ogon.split("-", 1)[0]
        return kod if kod.isdigit() and len(kod) >= 6 else None

    @property
    def obowiazujacy(self) -> bool:
        """Status INSPIRE "legalForce" znaczy akt prawnie wiazacy."""
        return bool(self.status and "legalForce" in self.status)


def _atrybut_xlink(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    return element.get("{http://www.w3.org/1999/xlink}href")


def _data(wartosc: str | None) -> dt.date | None:
    if not wartosc:
        return None
    try:
        return dt.date.fromisoformat(wartosc[:10])
    except ValueError:
        return None


def parse_akty(xml: str | bytes) -> list[AktMpzp]:
    """Rozbior odpowiedzi WFS GetFeature. Pusta odpowiedz to poprawny wynik."""
    try:
        root = ET.fromstring(xml) if isinstance(xml, str) else ET.fromstring(xml.decode("utf-8"))
    except ET.ParseError as exc:
        raise MpzpError(f"nie da sie sparsowac odpowiedzi WFS: {exc}") from exc

    akty: list[AktMpzp] = []
    for akt in root.iter(f"{{{APP}}}AktPlanowaniaPrzestrzennego"):
        identyfikator = akt.find(f"{{{APP}}}idIIP/{{{APP}}}Identyfikator")
        lokalny = przestrzen = None
        if identyfikator is not None:
            lokalny = text_of(identyfikator.find(f"{{{APP}}}lokalnyId"))
            przestrzen = text_of(identyfikator.find(f"{{{APP}}}przestrzenNazw"))

        zasieg = akt.find(f"{{{APP}}}zasiegPrzestrzenny")
        akty.append(
            AktMpzp(
                lokalny_id=lokalny or "",
                przestrzen_nazw=przestrzen or "",
                tytul=text_of(akt.find(f"{{{APP}}}tytul")),
                obowiazuje_od=_data(text_of(akt.find(f"{{{APP}}}obowiazujeOd"))),
                status=_atrybut_xlink(akt.find(f"{{{APP}}}status")),
                typ_planu=_atrybut_xlink(akt.find(f"{{{APP}}}typPlanu")),
                geometria_wkt=geometry_to_wkt(zasieg) if zasieg is not None else None,
            )
        )
    return akty


def bbox_param(bbox: geo.BBox2180) -> str:
    """BBOX dla tej uslugi: z krotkim kodem EPSG kolejnosc to easting, northing.

    Celowo nie uzywamy geo.wfs_bbox: tamten format (northing pierwszy z krotkim
    kodem) jest poprawny dla uslug GUGiK i zwraca tu zero obiektow.
    """
    return (
        f"{bbox.min_easting:.2f},{bbox.min_northing:.2f},"
        f"{bbox.max_easting:.2f},{bbox.max_northing:.2f},EPSG:{geo.EPSG_PL1992}"
    )


def pobierz_akty(
    bbox: geo.BBox2180,
    *,
    url: str = WFS_MPZP,
    typ: str = TYP_AKT,
    count: int = 20,
    timeout: float = 60.0,
) -> list[AktMpzp]:
    """Akty przecinajace prostokat. Jedyne miejsce w tym pliku robiace HTTP."""
    odpowiedz = _http.get(
        url,
        params={
            "SERVICE": "WFS",
            "VERSION": "2.0.0",
            "REQUEST": "GetFeature",
            "TYPENAMES": typ,
            "SRSNAME": f"EPSG:{geo.EPSG_PL1992}",
            "COUNT": count,
            "BBOX": bbox_param(bbox),
        },
        timeout=timeout,
    )
    return parse_akty(odpowiedz.text)


def akty_w_punkcie(
    punkt: geo.PL1992,
    *,
    promien_m: float = PROMIEN_SZUKANIA_M,
    url: str = WFS_MPZP,
    timeout: float = 60.0,
) -> list[AktMpzp]:
    """Akty, ktorych granica zawiera punkt.

    WFS filtruje po prostokacie, wiec zwraca tez akty lezace obok. Zawieranie
    sprawdzamy sami, geometria po geometrii: akt obok dzialki nie obejmuje jej
    planem i nie wolno go tak zaraportowac.
    """
    from shapely import wkt as shapely_wkt
    from shapely.geometry import Point

    kandydaci = pobierz_akty(geo.bbox_around(punkt, promien_m), url=url, timeout=timeout)
    if not kandydaci:
        return []

    p = Point(punkt.easting, punkt.northing)
    trafione: list[AktMpzp] = []
    for akt in kandydaci:
        if not akt.geometria_wkt:
            continue
        try:
            ksztalt = shapely_wkt.loads(akt.geometria_wkt)
        except Exception:  # geometria z rejestru bywa nieoczywista, to nie blad krytyczny
            continue
        if ksztalt.covers(p):
            trafione.append(akt)
    return trafione


@dataclass(frozen=True, slots=True)
class MpzpInfo:
    """Co rejestr wie o tym punkcie."""

    objeta_mpzp: bool
    akt: AktMpzp | None = None
    liczba_aktow: int = 0
    zrodlo: str = "rejestr-urbanistyczny"

    @property
    def uwaga(self) -> str | None:
        """Brak aktu w rejestrze to nie to samo, co brak MPZP w gminie."""
        if self.objeta_mpzp:
            return None
        return (
            "brak aktu w Rejestrze Urbanistycznym. Rejestr ma dzis 524 akty "
            "w calym kraju, wiec to nie dowod, ze dzialka nie jest objeta MPZP"
        )


def sprawdz_punkt(
    punkt: geo.PL1992, *, promien_m: float = PROMIEN_SZUKANIA_M, timeout: float = 60.0
) -> MpzpInfo:
    """Jedno wywolanie na potrzeby wzbogacania oferty."""
    akty = akty_w_punkcie(punkt, promien_m=promien_m, timeout=timeout)
    obowiazujace = [a for a in akty if a.obowiazujacy] or akty
    if not obowiazujace:
        return MpzpInfo(objeta_mpzp=False)

    # Gdy punkt lezy w kilku aktach (plan zmieniany czesciowo), bierzemy
    # najnowszy: to on obowiazuje dla tego fragmentu.
    najnowszy = max(obowiazujace, key=lambda a: a.obowiazuje_od or dt.date.min)
    return MpzpInfo(objeta_mpzp=True, akt=najnowszy, liczba_aktow=len(obowiazujace))
