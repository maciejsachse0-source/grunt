"""Petla DIFF: pobieranie ofert z portali. Sekcja 18.2 dokumentu.

    dla kazdego wlaczonego adaptera:
        dla kazdej strony wynikow (do SCRAPER_MAX_PAGES_PER_RUN):
            pobierz HTML, parse_listing_page -> lista stubow
            porownaj content_hash z baza:
                nowy ID        -> kolejkuj detal
                zmieniony hash -> kolejkuj detal, dopisz do price_history
                bez zmian      -> tylko last_seen_at = now()
        pobierz detale wylacznie dla zakolejkowanych
        oznacz jako is_active=false oferty niewidziane od 14 dni

ODSTEPSTWO OD DOKUMENTU, wymuszone przez robots.txt Morizona.
Sekcja 18.2 przewiduje skan listingu POSORTOWANEGO PO DACIE i przerwanie
paginacji na pierwszej niezmienionej stronie. Morizon zabrania sortowania
("Disallow: *sort=*", "Disallow: */najnowsze/*") i stron powyzej 10., wiec
wczesne przerwanie po dacie jest niewykonalne. Zamiast tego skanujemy komplet
stron wynikow (tanich) i tniemy koszt tam, gdzie on naprawde jest: na stronach
detalu. Oszczednosc transferu zostaje, bo detal wazy kilkaset kilobajtow,
a strona wynikow kilkadziesiat.

Runner jest jedynym miejscem, ktore robi zadania HTTP i pisze do bazy.
Adaptery dostaja gotowy HTML (sekcja 18.1).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.config import settings
from grunt.ingest import normalize
from grunt.ingest.robots import Robots
from grunt.portals.base import ListingDetail, ListingStub, PortalAdapter
from grunt.sources import _http, geo

log = logging.getLogger(__name__)

# Po tylu dniach bez zobaczenia oferty uznajemy ja za zdjeta.
STALE_AFTER_DAYS = 14

# Wzorce swiadczace o tym, ze User-Agent zostal skopiowany z .env.example
# i nie ma w nim prawdziwego adresu kontaktowego.
UA_PLACEHOLDERS = ("TWOJ@EMAIL", "TWOJEMAIL", "example.com", "twoj@")


class ScraperConfigError(RuntimeError):
    pass


def assert_honest_user_agent(user_agent: str | None = None) -> str:
    """Bez prawdziwego kontaktu w User-Agencie nie ruszamy.

    Sekcja 8.2 punkt 7: uczciwy User-Agent z adresem kontaktowym jest jednym
    z filarow obrony prawnej projektu, a podszywanie sie jest okolicznoscia
    obciazajaca. Placeholder z .env.example jest gorszy niz brak deklaracji,
    bo wyglada jak bot udajacy, ze sie przedstawia. Dlatego to blad twardy,
    a nie ostrzezenie w logu.
    """
    ua = (user_agent or settings.scraper_user_agent).strip()

    if any(marker.lower() in ua.lower() for marker in UA_PLACEHOLDERS):
        raise ScraperConfigError(
            f"SCRAPER_USER_AGENT wciaz zawiera placeholder z .env.example (jest: {ua!r}). "
            "Wpisz prawdziwy adres kontaktowy w .env."
        )
    if "@" not in ua:
        raise ScraperConfigError(
            f"SCRAPER_USER_AGENT nie zawiera adresu kontaktowego (jest: {ua!r})."
        )
    if "/" not in ua:
        # Sam adres e-mail to za malo: naglowek ma powiedziec, CZYM jest klient,
        # a nie tylko do kogo pisac. Format zgodny z RFC 9110: produkt/wersja
        # plus komentarz z kontaktem.
        raise ScraperConfigError(
            f"SCRAPER_USER_AGENT nie identyfikuje narzedzia (jest: {ua!r}). "
            'Uzyj postaci: "GRUNT/0.1 (prywatne narzedzie analityczne; kontakt: adres@domena)"'
        )
    return ua


def _koniec_stron(exc: httpx.HTTPError, page: int) -> bool:
    """Czy ten blad to po prostu koniec listy wynikow, a nie awaria.

    Adapter nie zna z gory liczby stron, wiec proponuje kolejna i dopiero
    odpowiedz portalu mowi, czy cos tam jest. 404 na stronie DRUGIEJ albo
    dalszej znaczy "tyle bylo", a na PIERWSZEJ znaczy zly adres i wtedy to jest
    prawdziwy blad, ktory ma trafic do wyniku zadania.

    Powod z zycia: Gratka ma w Sopocie 15 ofert, czyli jedna strone, a adapter
    i tak proponuje ?page=2. Bez tego rozroznienia kazdy maly powiat dokladalby
    falszywy blad do wyniku zadania i mylil watchdoga.
    """
    if page < 2 or not isinstance(exc, httpx.HTTPStatusError):
        return False
    return exc.response.status_code == 404


@dataclass
class RunStats:
    portal: str = ""
    pages_fetched: int = 0
    stubs_seen: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    missing_detail: int = 0
    details_fetched: int = 0
    details_failed: int = 0
    deactivated: int = 0
    robots_blocked: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "portal": self.portal,
            "stron_wynikow": self.pages_fetched,
            "ofert_na_listingu": self.stubs_seen,
            "nowe": self.new,
            "zmienione": self.changed,
            "bez_zmian": self.unchanged,
            "zalegle_detale": self.missing_detail,
            "pobrane_detale": self.details_fetched,
            "detale_z_bledem": self.details_failed,
            "wygaszone": self.deactivated,
            "zablokowane_przez_robots": self.robots_blocked,
            "bledy": self.errors[:5],
        }


class RobotsGuard:
    """Sprawdzanie robots.txt przed kazdym zadaniem, z cache per host.

    Adaptery same pilnuja swoich limitow (Morizon zatrzymuje sie na stronie 10.),
    ale to jest druga, niezalezna bramka. Regula z sekcji 8.2 nie jest
    preferencja, tylko elementem obrony prawnej projektu.

    Uzywamy wlasnego parsera (ingest/robots.py), bo urllib.robotparser nie zna
    wildcardow i przepuszczal adresy, ktorych Morizon zabrania wprost.
    """

    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self._parsers: dict[str, Robots | None] = {}

    def _parser(self, url: str) -> Robots | None:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._parsers:
            try:
                response = _http.get(f"{host}/robots.txt", timeout=20, delay=1.0)
                self._parsers[host] = Robots.from_text(response.text, self.user_agent)
            except httpx.HTTPError as exc:
                # Brak robots.txt oznacza brak ograniczen, ale blad sieci to co innego:
                # w obu przypadkach wolimy nie zgadywac i zapisac to w logu.
                log.warning("nie udalo sie pobrac robots.txt dla %s: %s", host, exc)
                self._parsers[host] = None
        return self._parsers[host]

    def allowed(self, url: str) -> bool:
        parser = self._parser(url)
        return True if parser is None else parser.can_fetch(url)

    def crawl_delay(self, url: str) -> float | None:
        parser = self._parser(url)
        return parser.crawl_delay if parser else None


UPSERT_STUB = text(
    """
    INSERT INTO listings (
        portal, portal_offer_id, url, title, price_grosze, area_m2,
        content_hash, first_seen_at, last_seen_at, is_active
    ) VALUES (
        CAST(:portal AS portal_t), :offer_id, :url, :title, :price, :area,
        :content_hash, now(), now(), true
    )
    ON CONFLICT (portal, portal_offer_id) DO UPDATE SET
        last_seen_at = now(),
        is_active    = true,
        url          = EXCLUDED.url,
        title        = COALESCE(EXCLUDED.title, listings.title),
        price_grosze = COALESCE(EXCLUDED.price_grosze, listings.price_grosze),
        area_m2      = COALESCE(EXCLUDED.area_m2, listings.area_m2),
        content_hash = EXCLUDED.content_hash
    RETURNING id,
              (xmax = 0) AS wstawiony,
              content_hash
    """
)

SELECT_EXISTING = text(
    """
    SELECT id, content_hash, price_grosze,
           (raw_jsonb IS NULL) AS bez_detalu
    FROM listings
    WHERE portal = CAST(:portal AS portal_t) AND portal_offer_id = :offer_id
    """
)

INSERT_PRICE_HISTORY = text(
    """
    INSERT INTO price_history (listing_id, price_grosze, observed_at)
    VALUES (:listing_id, :price, now())
    ON CONFLICT DO NOTHING
    """
)

UPDATE_DETAIL = text(
    """
    UPDATE listings SET
        title             = COALESCE(:title, title),
        price_grosze      = COALESCE(:price, price_grosze),
        area_m2           = COALESCE(:area, area_m2),
        -- Rzutowania na double precision sa konieczne, a nie ozdobne. Gdy oferta
        -- nie ma wspolrzednych, sterownik wysyla NULL bez typu, a PostgreSQL
        -- nie umie go wywnioskowac z samego "IS NULL" i przewraca sie bledem
        -- "could not determine data type of parameter". Trafialo to wylacznie
        -- w oferty bez wspolrzednych, czyli w Nieruchomosci-online, i wywalalo
        -- caly przebieg uzupelniania detali dla tego portalu.
        geom              = CASE WHEN CAST(:easting AS double precision) IS NULL THEN geom
                                 ELSE ST_SetSRID(
                                     ST_MakePoint(
                                         CAST(:easting AS double precision),
                                         CAST(:northing AS double precision)
                                     ), 2180) END,
        geom_precision    = COALESCE(:geom_precision, geom_precision),
        przeznaczenie_raw = COALESCE(:przeznaczenie, przeznaczenie_raw),
        media_raw         = COALESCE(CAST(:media AS jsonb), media_raw),
        phone_sha256      = COALESCE(:phone_hash, phone_sha256),
        thumb_url         = COALESCE(:thumb_url, thumb_url),
        raw_jsonb         = CAST(:raw AS jsonb),
        last_seen_at      = now()
    WHERE id = :listing_id
    """
)

DEACTIVATE = text(
    """
    UPDATE listings SET is_active = false
    WHERE portal = CAST(:portal AS portal_t)
      AND is_active
      AND last_seen_at < now() - make_interval(days => :days)
    """
)


def run_portal(
    session: Session,
    adapter: PortalAdapter,
    *,
    region_teryt: str | None = None,
    max_pages: int | None = None,
    max_details: int | None = None,
    fetch_details: bool = True,
    progress: object = None,
) -> RunStats:
    assert_honest_user_agent()
    region_teryt = region_teryt or settings.region_teryt
    max_pages = max_pages or settings.scraper_max_pages_per_run
    stats = RunStats(portal=adapter.name)
    guard = RobotsGuard(settings.scraper_user_agent)
    to_fetch: list[tuple[int, str]] = []

    for list_url in adapter.list_urls(region_teryt):
        page = 1
        url = list_url
        while page <= max_pages:
            if not guard.allowed(url):
                stats.robots_blocked += 1
                log.info("robots.txt nie pozwala na %s", url)
                break
            try:
                response = _http.get(url, delay=adapter.delay_seconds, timeout=60)
            except httpx.HTTPError as exc:
                if _koniec_stron(exc, page):
                    # 404 na stronie 2 i dalszej to koniec wynikow, nie awaria.
                    # Gratka zwraca tak dla malych miast: Sopot ma 15 ofert,
                    # czyli jedna strone, a adapter i tak proponuje ?page=2, bo
                    # nie zna z gory liczby wynikow. Zapisywanie tego jako bledu
                    # zasmiecaloby wynik zadania i mylilo watchdoga, ktory ma
                    # alarmowac o portalu, ktory naprawde ucichl.
                    break
                stats.errors.append(f"{url}: {exc}")
                break

            stats.pages_fetched += 1
            stubs = adapter.parse_listing_page(response.text)
            if not stubs:
                # Zero ofert na pierwszej stronie to sygnal dla watchdoga:
                # albo region jest pusty, albo portal zmienil HTML.
                if page == 1:
                    stats.errors.append(f"{url}: zero ofert na stronie wynikow")
                break

            for stub in stubs:
                stats.stubs_seen += 1
                listing_id, status = _upsert_stub(session, adapter.name, stub)
                if status == "new":
                    stats.new += 1
                    to_fetch.append((listing_id, str(stub.url)))
                elif status == "changed":
                    stats.changed += 1
                    to_fetch.append((listing_id, str(stub.url)))
                elif status == "bez_detalu":
                    # Nadrobienie zaleglosci po przerwanym albo ograniczonym
                    # przebiegu. Nie liczymy tego jako zmiany oferty, bo oferta
                    # sie nie zmienila - to my jej nie dokonczylismy.
                    stats.missing_detail += 1
                    to_fetch.append((listing_id, str(stub.url)))
                else:
                    stats.unchanged += 1
            session.commit()

            if progress is not None:
                progress(f"{adapter.name}: {url} -> {len(stubs)} ofert")

            page += 1
            next_url = adapter.next_page_url(list_url, page)
            if next_url is None:
                break
            url = next_url

    if fetch_details:
        limit = max_details if max_details is not None else len(to_fetch)
        for listing_id, detail_url in to_fetch[:limit]:
            if not guard.allowed(detail_url):
                stats.robots_blocked += 1
                continue
            try:
                response = _http.get(detail_url, delay=adapter.delay_seconds, timeout=60)
                detail = adapter.parse_detail(response.text)
            except (httpx.HTTPError, ValueError) as exc:
                stats.details_failed += 1
                stats.errors.append(f"{detail_url}: {exc}")
                continue
            _save_detail(session, listing_id, detail)
            stats.details_fetched += 1
        session.commit()

    result = session.execute(DEACTIVATE, {"portal": adapter.name, "days": STALE_AFTER_DAYS})
    stats.deactivated = result.rowcount or 0
    session.commit()
    return stats


def _upsert_stub(session: Session, portal: str, stub: ListingStub) -> tuple[int, str]:
    """Zwraca (id_oferty, status): new | changed | bez_detalu | unchanged.

    "bez_detalu" to oferta, ktora jest juz w bazie i ma ten sam content_hash,
    ale nigdy nie doczekala sie pobrania strony detalu. Bez tego stanu taka
    oferta zostawalaby "bez zmian" na zawsze i **nigdy** nie dostalaby
    wspolrzednych ani przeznaczenia. Zdarza sie to za kazdym razem, gdy
    przebieg zostal przerwany albo ograniczony (--max-details), bo stub zapisuje
    sie od razu, a detale pobierane sa dopiero po calym listingu.

    Znacznikiem jest raw_jsonb: UPDATE_DETAIL ustawia je bezwarunkowo przy
    kazdym pobraniu detalu, wiec NULL znaczy "detalu nie bylo".
    """
    existing = (
        session.execute(SELECT_EXISTING, {"portal": portal, "offer_id": stub.portal_offer_id})
        .mappings()
        .one_or_none()
    )

    row = (
        session.execute(
            UPSERT_STUB,
            {
                "portal": portal,
                "offer_id": stub.portal_offer_id,
                "url": str(stub.url),
                "title": stub.title,
                "price": stub.price_grosze,
                "area": stub.area_m2,
                "content_hash": stub.content_hash,
            },
        )
        .mappings()
        .one()
    )

    listing_id = int(row["id"])

    if existing is None:
        if stub.price_grosze:
            session.execute(
                INSERT_PRICE_HISTORY, {"listing_id": listing_id, "price": stub.price_grosze}
            )
        return listing_id, "new"

    if existing["content_hash"] != stub.content_hash:
        if stub.price_grosze and stub.price_grosze != existing["price_grosze"]:
            session.execute(
                INSERT_PRICE_HISTORY, {"listing_id": listing_id, "price": stub.price_grosze}
            )
        return listing_id, "changed"

    if existing["bez_detalu"]:
        return listing_id, "bez_detalu"

    return listing_id, "unchanged"


def _save_detail(session: Session, listing_id: int, detail: ListingDetail) -> None:
    """Zapis detalu. Telefon zamieniany na hash i wyrzucany JESZCZE PRZED baza."""
    import json

    czysty = detail.bez_danych_kontaktowych()
    phone_hash = normalize.hash_phone(detail.phone_raw)

    easting = northing = None
    if normalize.coords_ok(detail.lat, detail.lon):
        punkt = geo.wgs84_to_pl1992(detail.lat, detail.lon)  # type: ignore[arg-type]
        easting, northing = punkt.easting, punkt.northing

    session.execute(
        UPDATE_DETAIL,
        {
            "listing_id": listing_id,
            "title": czysty.title,
            "price": czysty.price_grosze,
            "area": czysty.area_m2,
            "easting": easting,
            "northing": northing,
            "geom_precision": czysty.geom_precision,
            "przeznaczenie": czysty.przeznaczenie_raw,
            "media": json.dumps(czysty.media_raw) if czysty.media_raw else None,
            "phone_hash": phone_hash,
            "thumb_url": czysty.thumb_url,
            "raw": json.dumps(
                {
                    **czysty.raw,
                    "ksztalt": czysty.ksztalt_raw,
                    "dojazd": czysty.road_access_raw,
                    "forma_wlasnosci": czysty.forma_wlasnosci_raw,
                },
                ensure_ascii=False,
            ),
        },
    )


def run_all(
    session: Session,
    adapters: list[PortalAdapter],
    **kwargs: object,
) -> list[RunStats]:
    results = []
    for adapter in adapters:
        try:
            results.append(run_portal(session, adapter, **kwargs))  # type: ignore[arg-type]
        except Exception as exc:  # jeden zepsuty portal nie moze zatrzymac reszty
            log.exception("portal %s wywalil sie", adapter.name)
            stats = RunStats(portal=adapter.name)
            stats.errors.append(str(exc))
            results.append(stats)
    return results


def last_run_summary(session: Session) -> list[dict[str, object]]:
    """Stan per portal dla /api/health i watchdoga (sekcja 7.4)."""
    rows = (
        session.execute(
            text(
                """
            SELECT portal::text AS portal,
                   count(*) FILTER (WHERE is_active) AS aktywne,
                   count(*) AS wszystkie,
                   count(*) FILTER (WHERE geom IS NOT NULL) AS ze_wspolrzednymi,
                   max(last_seen_at) AS ostatnio_widziane,
                   count(*) FILTER (WHERE first_seen_at > now() - interval '1 day') AS nowe_24h
            FROM listings
            GROUP BY portal
            ORDER BY portal
            """
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def stale_portals(session: Session, days: int = 2) -> list[str]:
    """Portale, ktore od kilku dni nie przyniosly nic nowego.

    Sekcja 4.2: to nie znaczy, ze rynek stanal, tylko ze nas zablokowali.
    """
    rows = (
        session.execute(
            text(
                """
            SELECT portal::text AS portal
            FROM listings
            GROUP BY portal
            HAVING max(first_seen_at) < now() - make_interval(days => :days)
            """
            ),
            {"days": days},
        )
        .scalars()
        .all()
    )
    return list(rows)


def today() -> dt.date:
    return dt.date.today()


SELECT_BEZ_DETALU = text(
    """
    SELECT id, url FROM listings
    WHERE portal = CAST(:portal AS portal_t)
      AND is_active
      AND geom IS NULL
    ORDER BY first_seen_at DESC
    LIMIT :limit
    """
)


def backfill_details(
    session: Session,
    adapter: PortalAdapter,
    *,
    limit: int = 100,
    progress: object = None,
) -> RunStats:
    """Uzupelnienie detali dla ofert, ktore ich nigdy nie dostaly.

    Petla DIFF z zalozenia pobiera detal tylko dla ofert nowych i zmienionych.
    To jest poprawne przy codziennym dzialaniu, ale zostawia dziure: oferty
    zapisane zanim detale byly pobierane (albo pominiete limitem --max-details)
    zostaja bez wspolrzednych na zawsze, bo przy kazdym kolejnym przebiegu sa
    "bez zmian".

    Ta funkcja domyka dziure: bierze aktywne oferty bez geometrii i pobiera
    dla nich strone oferty. Watchdog wykrywa ten stan i o niego wola.
    """
    assert_honest_user_agent()
    stats = RunStats(portal=adapter.name)
    guard = RobotsGuard(settings.scraper_user_agent)

    rows = (
        session.execute(SELECT_BEZ_DETALU, {"portal": adapter.name, "limit": limit})
        .mappings()
        .all()
    )

    for row in rows:
        url = row["url"]
        if not guard.allowed(url):
            stats.robots_blocked += 1
            continue
        try:
            response = _http.get(url, delay=adapter.delay_seconds, timeout=60)
            detail = adapter.parse_detail(response.text)
        except (httpx.HTTPError, ValueError) as exc:
            stats.details_failed += 1
            stats.errors.append(f"{url}: {exc}")
            continue

        _save_detail(session, int(row["id"]), detail)
        stats.details_fetched += 1
        if stats.details_fetched % 10 == 0:
            session.commit()
            if progress:
                progress(f"{adapter.name}: uzupelniono {stats.details_fetched} detali")

    session.commit()
    return stats
