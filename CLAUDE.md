# GRUNT: instrukcje projektowe

## Czym jest ten projekt
System zbierania ofert dzialek z polskich portali, wzbogacania ich o dane publiczne
(GUGiK, RCN, MPZP, ISOK, GUS, OSM) i oceny potencjalu inwestycyjnego.
Pelna koncepcja: dzialki-system-koncepcja.md w katalogu glownym. Czytaj ja,
gdy pytanie dotyczy "dlaczego tak", a nie "jak to zakodowac".

Aktualny stan i co robic dalej: README.md, sekcje "Audyt 25.08.2026" oraz
"Co dalej, w kolejnosci". Zanim zaczniesz nowy watek, przeczytaj te dwie sekcje:
opisuja, ktore fazy sa domkniete, ktore filary i bramki nie maja jeszcze zrodel
danych i w jakiej kolejnosci warto to usuwac.

## Stack
Python 3.13 (uv), FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL 17 + PostGIS,
httpx + brotli, Next.js 16, Tailwind 4, MapLibre GL JS.
Nie dodawaj nowych zaleznosci bez pytania. Jesli uwazasz, ze biblioteka jest
potrzebna, napisz dlaczego i poczekaj na zgode.

Trzy odstepstwa od dokumentu koncepcyjnego, wszystkie sprawdzone w kodzie
25.08.2026:

* **Crawlee nie jest zaleznoscia.** Petla DIFF w ingest/runner.py robi dokladnie
  to, czego potrzebujemy (kolejka, throttling, retry), a adaptery portali
  z zalozenia nie dotykaja sieci. Jesli kiedys pojawi sie portal wymagajacy JS,
  wracamy do tematu.
* **Nie ma curl-cffi ani selectolax.** Zadania HTTP idzie httpx (curl-cffi byloby
  potrzebne do podszywania sie pod przegladarke, czego i tak zabrania sekcja
  o higienie nizej), a HTML-a nie parsujemy selektorami: wszystkie cztery portale
  oddaja dane jako JSON w tresci strony (JSON-LD, __NUXT_DATA__, __NEXT_DATA__),
  wiec wystarcza json i re. GML czyta stdlibowy ElementTree.
* **Nie ma shadcn/ui.** Frontend to Tailwind 4 i wlasne komponenty; dwanascie
  plikow w web/src/components nie uzasadnia biblioteki komponentow.

## Zasady twarde

### Dane osobowe
NIGDY nie zapisuj do bazy: imion, nazwisk, numerow telefonu, adresow e-mail
ogloszeniodawcow. Numer telefonu wolno przetworzyc wylacznie do SHA-256 i zapisac
jako hash, tylko na potrzeby deduplikacji. Pelne opisy ogloszen nie sa
przechowywane, tylko metadane liczbowe i URL do zrodla. Zdjecia nie sa
przechowywane, tylko URL i pHash miniatury. To decyzje prawne, nie preferencje.
Jesli kod, ktory piszesz, lamie ktoras z nich, zatrzymaj sie i powiedz o tym.

### Braki danych
NULL to NULL. Nigdy nie zastepuj brakujacej wartosci zerem ani wartoscia domyslna
w warstwie danych. Imputacja odbywa sie wylacznie w scoring/ i zawsze zapisuje
flage is_imputed_*. Regula produktowa: coverage < 40% oznacza brak wyniku,
nie niski wynik.

### Uklady wspolrzednych
W bazie wszystkie geometrie w EPSG:2180. Na wyjsciu API zawsze EPSG:4326.
Wszystkie przeliczenia ida przez src/grunt/sources/geo.py. Nigdy nie konstruuj
parametrow xy/BBOX recznie w kliencie uslugi, bo kolejnosc osi rozni sie miedzy
uslugami GUGiK. Szczegoly w sekcji 19 dokumentu koncepcyjnego.

### Mapa i obrys dzialki
Klikniecie wiersza w tabeli ustawia `wybrana` w page.tsx. Mapa reaguje na to
dwuetapowo, zeby uzytkownik nie czekal na siec:

1. natychmiast: pinezka i `flyTo` na punkt oferty z GeoJSON-a, ktory mapa juz ma,
2. po odpowiedzi API: obrys dzialki i `fitBounds` na jej bbox, o ile dopasowanie
   jest pewne (patrz nizej).

Zrodlem obrysu jest tabela `parcels` (geom MULTIPOLYGON 2180) i `listings.parcel_id`.
Obie istnialy w schemacie od migracji 001 i do 25.08.2026 nic ich nie zapisywalo:
wzbogacanie pobieralo geometrie z EGiB, liczylo z niej front i zwartosc, po czym
ja wyrzucalo. Zapisuje ja teraz `enrich/parcel_store.py` (upsert po `uldk_id`).
Pobieranie geometrii z GUGiK przy kazdym kliknieciu byloby zapytaniem do cudzej
uslugi w sciezce zadania API i zlamaniem higieny scrapingu, wiec tego nie robimy.
Migracji nie ma, bo nie ma zmiany schematu.

API: `GET /api/listings/{id}/obrys` zwraca Feature w EPSG:4326 razem z bbox,
punktem oferty i poziomem dopasowania. Brak dzialki to 200 z `obrys: null`,
nie 404: oferta bez dopasowanej dzialki to stan normalny, nie blad. Punkt jest
w odpowiedzi osobno, bo w widoku "zapisane" oferty nie musi byc w GeoJSON-ie
mapy (ten idzie z filtrow) i inaczej nie byloby dokad przyblizyc.

PINEZKA JEST ZAWSZE, OBRYS TYLKO GDY DZIALKA JEST PEWNA. Kazda wybrana oferta
dostaje pinezke we wspolrzednych z ogloszenia, takze wtedy, gdy dzialki nie
udalo sie ustalic. Obrys dochodzi do pinezki wylacznie przy dopasowaniu `high`
albo `medium`, czyli wtedy, gdy powierzchnia dzialki zgadza sie z ogloszeniem.
Przy `low` powierzchnia sie NIE zgadza (match_parcel.py: to zwykle sasiad albo
dzialka-matka), wiec obrysu nie rysujemy wcale: pokazanie cudzego gruntu jako
przedmiotu oferty jest gorsze niz brak obrysu. Zostaje pinezka i podpis mowiacy
wprost, czego nie wiemy. Kadr tez o tym mowi: obrys dostaje `fitBounds` na
swoim bbox, sama pinezka `flyTo` na zoom 16, ktory pokazuje okolice zamiast
sugerowac granice.

Poziom dopasowania i geometria zostaja w odpowiedzi API takze dla `low`.
To klient decyduje, czego nie rysowac, a nie serwer, ktory ukrywa dane.

Backfill dla ofert wzbogaconych wczesniej: `uv run python scripts/parcels.py backfill`.
Idzie przez ULDK po `parcel_uldk_id` (z cache `uldk_cache`), z opoznieniem jak
kazde inne zrodlo.

### Portale
Jeden portal to jeden plik w portals/ implementujacy protokol PortalAdapter
z portals/base.py. Adapter nie dotyka bazy. Zwraca obiekty Pydantic.
Kazdy adapter ma test na zapisanym snapshocie HTML w tests/snapshots/.
Zmieniasz selektor, aktualizujesz snapshot, uruchamiasz testy.

### Scoring
Wszystko w scoring/ to funkcje czyste: bez I/O, bez bazy, bez datetime.now(),
bez losowosci bez jawnego seeda. Wejscie to dict albo dataclass, wyjscie to dict
ze skladnikami wyniku, nie sama liczba. Kazda funkcja ma test z recznie policzonym
oczekiwanym wynikiem.

### Higiena scrapingu
Domyslne opoznienie 2 s miedzy zadaniami do tej samej domeny plus jitter.
Respektuj robots.txt. User-Agent uczciwy, z adresem kontaktowym, bez podszywania
sie pod przegladarke. Zawsze Accept-Encoding: br, gzip. Strategia DIFF:
pobieramy strone detalu tylko dla ofert nowych albo zmienionych.

### Migracje
Kazda zmiana schematu to nowa migracja Alembic. Nigdy nie edytuj istniejacej
migracji, ktora juz sie wykonala. Nigdy nie zmieniaj schematu bezposrednio w SQL.

## Konwencje
- Formatowanie: ruff format. Lintowanie: ruff check. Typy: mypy w trybie strict dla scoring/ i sources/
- Nazwy w kodzie po angielsku, komentarze i komunikaty uzytkownika po polsku
- Wszystkie kwoty w groszach jako integer, nigdy float
- Wszystkie powierzchnie w m2 jako integer
- Wszystkie daty w UTC, konwersja na Europe/Warsaw dopiero w warstwie prezentacji

## Testy
pytest. Przed powiedzeniem "gotowe" uruchom pytest i pokaz wynik.
Nie oznaczaj zadania jako ukonczonego, gdy testy nie przechodza.
Testy sieciowe maja marker @pytest.mark.network i domyslnie nie uruchamiaja sie.

## Uruchamianie lokalnie (Windows, bez Dockera)
    uv sync                              # srodowisko Pythona 3.13
    pwsh scripts/local_pg.ps1 start      # PostgreSQL 17 + PostGIS na porcie 5433
    uv run alembic upgrade head
    uv run uvicorn grunt.api.main:app --reload
Gdy pojawi sie Docker: docker compose up -d db zastepuje local_pg.ps1,
DATABASE_URL bez zmian.

## Czego nie robic
- Nie refaktoruj kodu, o ktory nie pytalem
- Nie dodawaj README ani docstringow do wszystkiego "przy okazji"
- Nie tworz warstw abstrakcji "na przyszlosc". Ten projekt ma jednego uzytkownika
- Nie proponuj przejscia na Kubernetes, Kafke ani mikroserwisy
