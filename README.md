# GRUNT

System wyszukiwania i oceny potencjalu dzialek. Pelna koncepcja i uzasadnienie
decyzji: [`dzialki-system-koncepcja.md`](dzialki-system-koncepcja.md).
Instrukcje dla Claude Code: [`CLAUDE.md`](CLAUDE.md).

Ten plik opisuje **stan faktyczny**: co dziala, na jakich liczbach i czego nie
ma. Kazda liczba nizej jest zmierzona 25.08.2026, nie przepisana z poprzedniej
sesji. Rzeczy, ktore juz sie wydarzyly i nie zmieniaja niczego w kodzie, sa
z tego pliku usuwane - historia jest w dokumencie koncepcyjnym i w migracjach.

## Stan faz

| Faza | Zakres | Kryterium akceptacji | Wynik |
|---|---|---|---|
| **0. Fundament danych** | PostGIS, import RCN, ULDK, przeliczenia ukladow | ponad 20 000 transakcji do modelu | **137 298 rekordow, 104 148 z cena, 20 powiatow** |
| **1. Pierwsza wycena** | Model 1 (mediana z shrinkage), Model 2 (SE-KNN), `POST /api/valuate` | MdAPE < 30%, pokrycie przedzialu 75-85% | **MdAPE 19,7%, pokrycie 77,2%** (n=197) |
| **2. Scraper** | Morizon, Nieruchomosci-online, Otodom, Gratka; petla DIFF, robots.txt | drugi przebieg < 10% detali, zero PII | **0% detali w drugim przebiegu; audyt PII 6/6 czysto na 7 300 ofertach** |
| **3. Wzbogacanie i scoring** | plan ogolny + OUZ, powodz, teren, uzbrojenie, filary, alerty | ponad 80% ofert z kompletnoscia >= 40% | **98% (124 ze 126), srednia kompletnosc 76%** |
| **4. Aplikacja** | API listy z filtrami, Next.js: lista, filtry, mapa, karta | dziala na localhost, lista 5 tys. ponizej 1 s | **48 ms przy 7 300 ofertach w bazie** |
| **5. Deduplikacja i harmonogram** | etapy sekcji 4.3, kolejka `jobs` z backoffem, worker | zmierzony odsetek duplikatow, zadania bez czlowieka | **19,8% duplikatow, 701 klastrow; worker planuje i wykonuje sam** |
| **6. Kalibracja** | spread, `b1` na wlasnych danych, wrazliwosc wag, dyskryminacja | deal score przestaje byc systematycznie ujemny | **spread +24,3%, mediana deal score'u z -0,62 na +0,14; wrazliwosc: wymiana czolowki 1 z 10 przy progu 3** |

Faza 5 jest jedyna niedomknieta i **nie z powodu kodu**: brakuje zbioru 200
recznie oznakowanych par (praca reczna) i OLX-a (decyzja o pieniadzach).

## Liczby

### Kontrole automatyczne

```
pytest              525 passed, 11 deselected (sieciowe)
ruff check          All checks passed
ruff format         119 files already formatted
mypy strict         Success (scoring/ + sources/ + portals/, 33 pliki)
tsc --noEmit        exit 0
eslint src          exit 0
next build          Compiled successfully (Next.js 16.3.2)
alembic             015 (head), jedna glowa, 15 migracji
audit_pii.py        6/6 czysto
```

Postgres 17.6, PostGIS 3.6. Pomiar `curl` (razem z nawiazaniem polaczenia):
`/api/health` 22 ms, `/api/listings?limit=200` 44 ms i 178 kB,
`/api/listings/geojson?limit=5000` 48 ms i 885 kB, `/api/metodologia` 48 ms.
Wzrost bazy z 5 332 do 7 300 ofert nie ruszyl czasow, bo zapytania listy chodza
po indeksach i limitach, a nie po calej tabeli.

Poza `scoring/`, `sources/` i `portals/` mypy w trybie domyslnym pokazuje 17
bledow (`api/`, `enrich/`, `jobs/`, `ingest/`, `dedup/`). `CLAUDE.md` wymaga
trybu strict tylko dla trzech pierwszych katalogow i tam jest czysto.

### Stan bazy

| Tabela | Wierszy | Uwaga |
|---|---|---|
| `rcn_transactions` | 137 298 | 104 148 z cena, 73 745 powyzej progu 5 zl/m2 |
| `listings` | **7 300** | Morizon 3 974, N-online 2 050, Gratka 1 195, Otodom 81 |
| `listing_duplicates` | 1 247 par | 701 klastrow, 19,8% duplikatow, 362 pary do recznej oceny |
| `listing_enrichment` | 133 | rosnie: worker bierze porcje po 60 co godzine |
| `listing_category` | 7 300 | rodzaj dzialki dla 1 301 ofert, gmina dla 4 205 |
| `parcels` | 40 | obrysy dzialek dla mapy, dociagane `scripts/parcels.py` |
| `scores` | 126 | 124 z wynikiem, 2 ponizej progu kompletnosci |
| `market_medians` | 504 | gmina 393, powiat 102, wojewodztwo 9 |
| `market_dynamics` | 93 | trend policzony dla 57 obszarow, reszta niemierzalna |
| `teryt_names` | 139 | zero duplikatow nazw gmin po doprecyzowaniu rodzaju |
| `saved_filters` | 1 | jeden filtr testowy, `alert_log` ma 10 wpisow |

Deal score policzony dla 64 ofert ze 126, z czego **13 przekracza prog uwagi 1,5**.

Dziewiec rekordow RCN ma date transakcji w przyszlosci (najdalsza: rok 3517), co
jest literowka w zrodle. Kazde zapytanie modelu i mediany ma gorne ograniczenie
`data_trans <= :as_of`, wiec te rekordy nie wchodza do zadnego wyniku.

### Pokrycie filarow: jeden z siedmiu jest pusty

| Filar | Ma dane | Dlaczego tyle |
|---|---|---|
| ryzyka | 125 / 126 | |
| planistyka | 124 / 126 | |
| fizyka | 123 / 126 | ogranicza je dopasowanie do dzialki ewidencyjnej |
| infrastruktura | 122 / 126 | |
| rynek | 111 / 126 | |
| **chlonnosc** | **17 / 126** | tylko gminy z uchwalonym planem ogolnym |
| **lokalizacja** | **0 / 126** | wymaga izochron z wlasnej Valhalli |

Waga niedostepnego filaru jest renormalizowana na pozostale, a nie zastepowana
wartoscia srodkowa. Ponizej 40% kompletnosci system nie zwraca liczby, tylko
powod.

### Cztery bramki z szesciu nigdy nie zadzialaly

| Bramka | Aktywna w ofertach |
|---|---|
| `poza_ouz` | 32 |
| `powodz_morska` | 1 |
| `brak_dostepu_do_drogi`, `powodz_q10`, `powodz_q1`, `grunt_lesny` | **0** |

Bramki dzialaja i maja testy jednostkowe. Zera oznaczaja brak **wejscia**:
dostep do drogi i sposob uzytkowania nie sa dzis zbierane z zadnego zrodla poza
Otodomem, ktory ma na razie 81 ofert. Strefy Q1 i Q10 to inny przypadek - tam
zero moze byc po prostu prawda o tej probce.

## Uruchomienie od zera

Wymagania: Python 3.13 (instaluje `uv`), Node 22, ok. 5 GB dysku.

```bash
uv sync                                                    # srodowisko Pythona
powershell -ExecutionPolicy Bypass -File scripts/local_pg.ps1 setup
uv run alembic upgrade head                                # schemat bazy
uv run python scripts/bootstrap_data.py rcn --since 2023-01-01
uv run uvicorn grunt.api.main:app --reload                 # :8000/api/docs
cd web && npm install && npm run dev                       # :3000
```

Baza stoi lokalnie na porcie 5433 (PostgreSQL 17 + PostGIS 3.6 z binariow, bez
Dockera i bez uprawnien administratora). Gdy pojawi sie Docker,
`docker compose up -d db` zastepuje `local_pg.ps1` przy niezmienionym
`DATABASE_URL`. Import calego pomorskiego od 2023 trwa ok. 40 minut.

```bash
powershell -File scripts/local_pg.ps1 start|stop|status|psql|reset
```

**Ustaw swoj adres w `SCRAPER_USER_AGENT` w `.env`** - domyslny zawiera placeholder.

## Wdrozenie: Supabase i Vercel

Podzial wynika z ksztaltu projektu, nie z upodoban do dostawcow:

| co | gdzie | dlaczego akurat tam |
| --- | --- | --- |
| baza | Supabase | PostGIS wlacza sie przelacznikiem, bez wlasnego serwera |
| API | Vercel, funkcja Pythona | 21 endpointow, kazdy krotki i bezstanowy |
| frontend | Vercel, Next.js | i tak jest statyczny, `next build` daje dwie trasy |
| scraping, wzbogacanie, scoring | twoj komputer | 2 s przerwy miedzy zadaniami razy tysiace stron |

Ostatni wiersz jest tu najwazniejszy. Petla DIFF chodzi godzinami i celowo sie
nie spieszy (sekcja o higienie w CLAUDE.md), wiec nie ma czego szukac
w srodowisku, ktore liczy czas dzialania funkcji. Pipeline zostaje lokalnie
i pisze do Supabase. Skutek uboczny jest taki, ze **dane w chmurze odswiezaja
sie wtedy, gdy odpalisz zadania u siebie**, a nie same z siebie.

### 1. Baza

Nowy projekt w Supabase, region europejski. Zanim ruszysz migracje, w panelu
`Database` -> `Extensions` wlacz `postgis` i `pg_trgm`. Kolejnosc ma znaczenie:
migracja 001 robi `CREATE EXTENSION IF NOT EXISTS`, wiec przy wlaczonych
wczesniej rozszerzeniach nie zrobi nic, a przy wylaczonych zainstaluje je
w `public` zamiast w `extensions`, gdzie Supabase trzyma cala reszte.

Migracje ida **polaczeniem bezposrednim na porcie 5432**, nie poolerem. DDL
przerwane w polowie to najgorszy stan, w jakim moze byc schemat:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:<haslo>@db.<ref>.supabase.co:5432/postgres"
uv run alembic upgrade head
Remove-Item Env:DATABASE_URL
```

Dane przenosisz osobno. Schemat masz juz z Alembica, wiec z lokalnej bazy
wystarczy sama zawartosc:

```powershell
pg_dump --data-only --schema=public --exclude-table=spatial_ref_sys `
        --host localhost --port 5433 --username grunt grunt > dane.sql
```

Jesli przy wgrywaniu klucze obce zaprotestuja na kolejnosc tabel, nie walcz
z dumpem: `bootstrap_data.py`, `scrape`, `enrich` i `score` sa idempotentne
i odtworza wszystko od zera. Import calego pomorskiego z RCN to ok. 40 minut.

Darmowy plan Supabase konczy sie na 500 MB. Lokalny katalog `pgdata` ma
262 MB razem z WAL-em i indeksami, wiec zmiescisz sie albo otrzesz o limit,
zaleznie od tego, ile ofert zdazyles zebrac.

### 2. API

Osobny projekt na Vercelu, `Root Directory` ustawiony na korzen repozytorium.
Framework wykrywa sie sam po zaleznosciach z `pyproject.toml`, a `[tool.vercel]`
w tym samym pliku wskazuje `grunt.api.main:app`, bo `src/grunt/api/main.py` nie
jest zadna ze sciezek, ktorych Vercel szuka domyslnie. Wersje Pythona bierze
z `requires-python`, czyli 3.13.

Zmienne srodowiskowe projektu:

```
DATABASE_URL=postgresql+psycopg://postgres.<ref>:<haslo>@aws-1-<region>.pooler.supabase.com:6543/postgres
DB_SEARCH_PATH=public,extensions
API_CORS_ORIGINS=https://<domena-frontendu>.vercel.app
API_WRITE_TOKEN=<python -c "import secrets; print(secrets.token_urlsafe(32))">
```

Tu adres jest juz poolerem (port 6543), bo funkcja moze wstac w wielu
egzemplarzach naraz. `grunt/db.py` rozpoznaje go po porcie i sam wylacza pule
po stronie klienta oraz prepared statements, ktorych pooler transakcyjny nie
obsluguje. `DB_POOLER` jest po to, zeby przy nietypowym adresie dalo sie to
wymusic recznie.

`DB_SEARCH_PATH` jest obowiazkowe: bez `extensions` na sciezce geoalchemy2 nie
rozwiaze typu `geometry` i padnie kazde zapytanie o geometrie.

### 3. Frontend

Drugi projekt na Vercelu, `Root Directory` ustawiony na `web`. Zmienne:

```
NEXT_PUBLIC_API_URL=https://<domena-api>.vercel.app
NEXT_PUBLIC_API_TOKEN=<to samo, co API_WRITE_TOKEN>
```

Kolejnosc: najpierw API, potem frontend, a na koniec wroc do projektu API
i dopisz prawdziwa domene frontendu w `API_CORS_ORIGINS`. Bez tego przegladarka
utnie kazde zapytanie, zanim dojdzie do serwera.

### 4. Co zostaje u ciebie

`.env` na twoim komputerze wskazuje na Supabase (pooler albo polaczenie
bezposrednie, obojetne) i wszystko chodzi jak dotad:

```powershell
uv run python scripts/scrape.py
uv run python scripts/enrich.py
uv run python scripts/score.py
```

### Czego to nie zalatwia

**Token jest jawny.** `NEXT_PUBLIC_API_TOKEN` laduje w paczce przegladarki
i zobaczy go kazdy, kto otworzy narzedzia deweloperskie. Zatrzymuje roboty
i przypadkowe wejscia, nie zatrzyma czlowieka, ktoremu zalezy. Jesli to za
malo, sa dwa wyjscia: wlaczyc Deployment Protection na obu projektach
(wtedy do aplikacji wchodzi tylko twoje konto Vercela) albo przepuscic API
przez wlasny endpoint Next.js, gdzie sekret zostaje po stronie serwera.
Drugie jest solidniejsze i kosztuje jeden plik, ale nikt go jeszcze nie napisal.

**Reszta API jest otwarta.** Token pilnuje wylacznie `/api/saved`
i `/api/filters`, czyli tego, co jest twoje. Oferty, wyceny i metodologia
pochodza ze zrodel publicznych i stoja otworem, razem z `POST /api/valuate`,
ktory liczy najdluzej ze wszystkich endpointow.

**Nic nie chodzi samo.** Harmonogram z `scripts/jobs.py` to proces, ktory musi
gdzies stac. Na Vercelu nie stanie.

## Wycena: `POST /api/valuate`

Wycenia dowolna dzialke, takze taka, ktorej nie ma w zadnym ogloszeniu. To ten
endpoint sprawia, ze system ma wartosc niezaleznie od scrapera.

```bash
curl -X POST http://localhost:8000/api/valuate -H "Content-Type: application/json" -d '{
  "uldk_id": "226101_1.0089.433/2",
  "przeznaczenie": "budownictwoMieszkanioweJednorodzinne",
  "price_pln": 300000
}'
```

Odpowiedz: wycena z przedzialem, cena za m2 znormalizowana do 1000 m2, lista
porownywalnych transakcji z RCN, uzyte segmenty rynku, deal score wzgledem
podanej ceny i jawne ostrzezenia (odleglosc sasiadow, rozrzut, dobor spoza
segmentu). Bez `przeznaczenia` wycena nadal dziala, ale segment jest
"nieokreslona" i przedzial jest wyraznie szerszy - tak ma byc.

Trzy warstwy oceny (sekcja 5 dokumentu):

* **A, wycena** - `scoring/valuation.py`. Model 1: mediana ceny/m2
  znormalizowanej, z shrinkage'em `obreb -> gmina -> powiat -> wojewodztwo`,
  `lambda = n / (n + 10)`. Model 2: SE-KNN, `k = 20`, `lambda = 0,7`, z kara za
  niezgodnosc segmentu; domyslny w API, lepszy od Modelu 1 o 8 punktow MdAPE;
* **B, potencjal** - `scoring/pillars.py`, siedem filarow z wagami dla dwoch
  profili inwestora, bramki jako mnozniki (`scoring/gates.py`), status
  planistyczny A-E (`scoring/planning.py`);
* **C, deal score** - `D = (V - cena) / sigma`, progi 1,5 i 2,5 z sekcji 5.4.

## Scraper portali

```bash
uv run python scripts/scrape.py robots                     # co wolno wedlug robots.txt
uv run python scripts/scrape.py run --portal morizon --max-pages 1 --max-details 3
uv run python scripts/scrape.py run                        # wszystkie wlaczone portale
uv run python scripts/scrape.py backfill --portal gratka --limit 500
uv run python scripts/scrape.py status                     # stan bazy plus watchdog
uv run python scripts/audit_pii.py                         # dowod braku danych kontaktowych
```

| Portal | Adapter | Ofert | Jak pobieramy |
|---|---|---|---|
| Morizon | jest | 3 974 | JSON-LD, per powiat, strony 1-10 |
| Nieruchomosci-online | jest | 2 050 | HTML, 41 ofert na strone |
| Gratka | jest | 1 195 | JSON-LD, per powiat, strony 1-10 |
| Otodom | jest | 81 | `__NEXT_DATA__`, jeden adres wojewodzki plus paginacja |
| **OLX** | **brak** | 0 | zwraca 403 nawet na robots.txt |

**Otodom nie wymaga Apify i nie kosztuje 200 zl miesiecznie.** Dokument (sekcje
2.2 i 8.3) spisal go na straty. Sprawdzone ponownie 25.08.2026 uczciwym
naglowkiem: listing zwraca 200 i megabajt HTML-a, a robots.txt konczy sie na
`Allow: /`. Adapter dziala bez posrednika.

**Otodom jest najlepszym zrodlem cech w calym projekcie.** Strona detalu podaje
`target.Access_types` (np. `["hard_surfaced"]`) i `target.Media_types` (np.
`["water", "electricity"]`) jako POLA, a nie jako zdania w opisie. Morizon
i Gratka wymagaja wylapywania tego regexem z tresci ogloszenia. `Access_types`
jest jedynym istniejacym wejsciem bramki `brak_dostepu_do_drogi`.

**OLX zostaje poza systemem i to nie jest kwestia wysilku.** Serwis zwraca 403
na strone wynikow **i na sam plik robots.txt**, wiec nie da sie nawet sprawdzic,
na co pozwala; RFC 9309 pozwala potraktowac to jako pelny zakaz i tak robimy.
Zostaja dwa wyjscia: platny aktor Apify albo podszycie sie pod przegladarke.
Drugiego `CLAUDE.md` zabrania wprost, wiec OLX czeka na decyzje o pieniadzach.

**Higiena jest wbudowana i nie ma przelacznika, ktory ja wylacza**: uczciwy
User-Agent z adresem kontaktowym, 2 s odstepu na domene plus jitter, sprawdzanie
robots.txt przed kazdym adresem, zakaz zapisywania danych kontaktowych.

Jeden portal to jeden plik w `portals/`, ktory dostaje HTML i zwraca obiekty
Pydantic. Adapter nie robi zadan HTTP i nie dotyka bazy, wiec testy dzialaja na
zapisanych stronach bez internetu. Po zmianie HTML na portalu: zapisz nowy
snapshot, przepusc przez `scripts/scrub_snapshot.py`, uruchom testy, popraw
selektory w jednym pliku.

**Cztery rzeczy, ktore ta czesc kosztowala i ktore warto pamietac:**

* **Gratka i Morizon to ten sam dom.** Identyczna konstrukcja robots.txt
  (`Disallow: *page=*` z wyjatkami `Allow: *page=2$`..`*page=10$`), ten sam
  uklad `__NUXT_DATA__`, ten sam CDN obrazkow. Adapter Gratki to w duzej czesci
  Morizon z innymi slugami - dopiero to uzasadnilo `portals/_shared.py`;
* **slug powiatu Gratki ma dwa ksztalty**: powiaty ziemskie jako
  `powiat-gdanski`, miasta na prawach powiatu jako `gdansk`. Pomylka daje 404,
  wiec wszystkie 20 slugow jest sprawdzonych zapytaniem i pilnowanych testem;
* **404 na kolejnej stronie to koniec wynikow, nie awaria.** Sopot ma w Gratce
  15 ofert, czyli jedna strone, a adapter i tak proponuje `?page=2`. Runner
  rozroznia oba przypadki: 404 na stronie 1 zostaje bledem, na dalszych konczy
  paginacje po cichu. Bez tego kazdy maly powiat dokladal falszywy blad
  dokladnie tam, gdzie patrzy watchdog szukajacy portalu, ktory ucichl;
* **oferta bez detalu wracala do kolejki dopiero po zmianie ceny, czyli czasem
  nigdy.** Petla DIFF pobierala detal tylko dla ofert nowych i zmienionych, wiec
  oferta zapisana pod `--max-details` zostawala bez wspolrzednych na zawsze:
  przy drugim widzeniu hash sie zgadzal i szla do "bez zmian". Teraz
  `_upsert_stub` sprawdza takze obecnosc `raw_jsonb` i oddaje status
  `bez_detalu`, ktory wraca do kolejki; widac to w kolumnie `zalegle`. Ta luka
  byla dziura we wlasnym kryterium fazy 2: liczylismy odsetek pobranych detali,
  a nie odsetek ofert, ktore detal maja.

## Deduplikacja cross-portal

```bash
uv run python scripts/dedup.py run                 # przeliczenie par i klastrow
uv run python scripts/dedup.py klastry             # ta sama dzialka, rozne ceny
uv run python scripts/dedup.py pary --min 0.5      # material do recznej oceny
uv run python scripts/dedup.py oznacz 361 668 --tak
uv run python scripts/dedup.py precyzja            # progi na zbiorze oznakowanym
```

Etapy sekcji 4.3 od najtanszego: **twarde klucze** (ta sama dzialka ewidencyjna
z ULDK, ten sam plik miniatury), blocking po siatce metrycznej 500 m, pHash
miniatury, pokrycie tokenow tytulu. Powyzej 0,70 oferty skleja sie w klaster,
miedzy 0,50 a 0,70 para trafia do `listing_duplicates` jako podejrzenie do
recznej oceny. Werdykt czlowieka (`dedup oznacz`) przetrwa kazde przeliczenie,
bo bez zbioru oznakowanego progi stroi sie na slepo.

Klaster niczego nie kasuje. Filtr **bez duplikatow** w aplikacji pokazuje
z grupy jedna oferte, a karta wymienia pozostale zrodla i rozrzut cen.

### Adres miniatury jako twardy klucz

Najwiekszy pojedynczy zysk w deduplikacji nie kosztowal ani jednego zapytania
i ani jednej nowej zaleznosci. Miniatury Morizona i Gratki chodza przez ten sam
przekaznik `img1.staticmorizon.com.pl/thumb/<base64 adresu zrodlowego>`, a po
rozkodowaniu base64 oba portale pokazuja **ten sam plik** na `d-gr.cdngr.pl`.

To nie jest pHash z sekcji 4.3. pHash pyta "czy te dwa obrazy wygladaja
podobnie" i wymaga pobrania obu plikow oraz biblioteki do obrazow. Tu
porownujemy adres tego samego pliku na tym samym serwerze, czyli **tozsamosc,
a nie podobienstwo**. Stad decyzja, ze to klucz twardy (pewnosc 1,0, omija
blocking), oparta na pomiarze 3 298 kluczy z bazy:

* **ani razu** ten sam klucz nie wystapil w dwoch ofertach tego samego portalu -
  obawa sekcji 4.3 o agencje wrzucajaca ten sam baner sie nie zmaterializowala;
* 654 klucze wystapily na dwoch portalach naraz i w **654 przypadkach na 654**
  cena byla identyczna co do grosza, a w 650 na 654 takze powierzchnia.

Wynik: duplikaty skoczyly z 4,4% na **19,8%**, klastrow jest 701 zamiast 12,
a etap `obraz` rozstrzyga 653 pary wobec 230 z tytulu i 2 z ULDK. Udzial ofert
sklejonych w klaster, po portalach (pomiar w trakcie uzupelniania detali
Morizona, wiec jego mianownik jeszcze rosnie):

| Portal | Ofert ze wspolrzednymi | W klastrze | Udzial |
|---|---|---|---|
| Gratka | 1 194 | 692 | **58,0%** |
| Morizon | 2 516 | 785 | 31,2% |
| Nieruchomosci-online | 154 | 5 | 3,2% |
| Otodom | 81 | 0 | **0,0%** |

**To sa dolne granice, nie wyniki koncowe**, i tu kryje sie pomylka warta
zapisania. Pierwszy pomiar, na 323 ofertach Gratki, dal 96,6% i wygladal na
wniosek produktowy: "Gratka nie dodaje nic". Po uzupelnieniu detali dla calej
Gratki (1 194 zamiast 323) ten sam pomiar daje 58%. Roznica nie wzieta sie
z bledu w kodzie, tylko stad, ze pierwsze 323 oferty **nie byly losowa probka**:
uzupelnianie szlo po identyfikatorach, a najstarsze oferty Gratki to dokladnie
te, ktore byly juz wczesniej widziane na Morizonie. Udzial policzony na czesciowo
zaladowanym zbiorze nie jest udzialem.

Liczba nadal bedzie rosla, bo Morizon ma detale dla 2 516 z 3 974 ofert, a oferta
bez pobranego detalu nie ma miniatury i nie moze sie z niczym skleic. Pomiar
niezalezny od geometrii, na samych miniaturach: 55,0% kluczy Gratki wystepuje
takze na Morizonie (654 z 1 189).

**Wniosek produktowy zostaje, tylko slabszy:** ponad polowa Gratki to Morizon,
wiec podaz nalezy liczyc w klastrach, a nie w wierszach `listings`. Odwrotnie
z Otodomem: **zero duplikatow na 81 ofert**, czyli kazda jego oferta to nowa
dzialka w bazie.

Dwa odstepstwa od dokumentu, oba wymuszone przez dane:

* zamiast geohasha precyzji 7 blokujemy po siatce metrycznej, bo geometrie
  trzymamy w EPSG:2180, a nie w stopniach. Zamiana ukladow tam i z powrotem
  tylko po to, zeby policzyc klucz blokujacy, to okazja do pomylki bez zysku;
* hash telefonu, ktory dokument stawia w etapie 1 razem z ULDK, u nas nie
  rozstrzyga sam: ten sam numer to ta sama agencja, a agencja ma kilkadziesiat
  ofert w jednym powiecie.

## Aplikacja

Aplikacja: **http://localhost:3000**, dokumentacja API: http://localhost:8000/api/docs

Ekran laczy cztery rzeczy z sekcji 7 dokumentu: filtry (cena, powierzchnia,
rodzaj dzialki, gmina lub powiat po TERYT, portal, status planistyczny, koszt
mediow, front, strefy zalewowe, duplikaty), mape
MapLibre z kolorem punktu wedlug score'u i obrysem kliknietej dzialki, liste
z sortowaniem po score i deal score oraz karte dzialki z rozbiciem na filary, mnoznikami dyskwalifikujacymi
i czerwonymi flagami. Oferta z duplikatem jest oznaczona na liscie, a na karcie
ma sekcje z pozostalymi zrodlami, ich cenami i powodem sklejenia. Obok listy sa
zakladki **zapisane** (obserwowane oferty ze statusem, notatka i ocena),
**ceny w regionach** i **jak to liczymy**.

Dwie decyzje widoczne w interfejsie:

* oferta bez policzonego score'u pokazuje myslnik i powod, a nie zero. Zero
  sugerowaloby ocene, ktorej nie ma (sekcja 5.3.9);
* kompletnosc danych stoi obok score'u, nie w szczegolach, zeby bylo od razu
  widac, na ilu danych opiera sie ocena.

### Zakladka "jak to liczymy"

Sluzy do weryfikacji, nie do prezentacji. Zasada, na ktorej stoi: **zadna liczba
na tej stronie nie jest przepisana recznie**. `api/routers/metodologia.py`
importuje progi i wagi wprost z modulow `scoring/`, a pokrycie, rozklady
i liczby obserwacji bierze z biezacych zapytan do bazy. Zmiana stalej w kodzie
zmienia strone w tej samej sekundzie. Testy w `tests/test_api_metodologia.py`
porownuja wystawione wartosci z modulami zrodlowymi.

Dlatego strona jest uczciwa tam, gdzie system jest niekompletny: pokazuje wprost
zerowe pokrycie filaru lokalizacji, niskie pokrycie chlonnosci, bramki bez
wejscia i brak jakiegokolwiek statusu planistycznego A.

Audyt danych osobowych nie sprawdza deklaracji, tylko schemat bazy: kolumna
o nazwie wskazujacej na dane osobowe albo ma jawne uzasadnienie w
`DOZWOLONE_OSOBOWE` (dwa wpisy: hash telefonu do deduplikacji i adres
wlasciciela systemu do alertow), albo jest raportowana jako naruszenie. Test
`test_audyt_danych_osobowych_nie_znajduje_naruszen` wywali sie, gdy ktos doda
kolumne `telefon`, i o to chodzi.

## Harmonogram zadan

```bash
uv run python scripts/jobs.py worker               # petla, dziala do Ctrl+C
uv run python scripts/jobs.py tick                 # jeden obrot i wyjscie
uv run python scripts/jobs.py harmonogram          # co i jak czesto
uv run python scripts/jobs.py lista --status failed
uv run python scripts/jobs.py enqueue enrich --payload '{"limit": 500}'
```

Worker sam planuje: scraping co 6 h, wzbogacanie co 1 h porcjami po 60 ofert,
scoring co 3 h, rodzaj i gmina co 3 h, alerty co godzine, deduplikacja co 12 h,
dynamika rynku i kalibracja raz na tydzien, watchdog i sprzatanie historii raz
na dobe.
Interwal liczy sie od ostatniego **udanego** przebiegu, wiec zadanie, ktore sie
wywalilo, nie udaje wykonanego.

Porcja wzbogacania urosla z 20 do 60, bo dojscie Gratki i Otodomu podnioslo baze
z 723 do ponad 7 000 ofert i przy starej porcji nadgonienie zaleglosci trwaloby
ponad dwa tygodnie. Jedna oferta to ok. 20 zapytan i ok. 12 sekund, wiec 60
ofert zajmuje ok. 12 minut z godziny i daje srednio jedno zapytanie na trzy
sekundy do uslug GUGiK.

Zadanie z bledem wraca do kolejki z opoznieniem 5, 10, 20, 40 minut, do szesciu
godzin, i poddaje sie po piatej probie. Zadanie przerwane razem z procesem
zostaje w statusie `running` i wraca po godzinie (`queue.ODBLOKUJ_PO_MINUTACH`);
`queue.odblokuj_zawieszone(session, po_minutach=0)` odblokowuje je recznie, gdy
wiadomo, ze proces nie zyje. Stan jest w tabeli `jobs`, nie w pamieci procesu,
wiec restart komputera niczego nie gubi, a wyniki przebiegow zostaja w kolumnie
`jobs.wynik`: "co system robil w nocy" czyta sie z bazy.

Dlatego nie ma tu APScheduler ani Celery: caly stan, ktory musialyby trzymac,
jest juz w tabeli `jobs`, a `SELECT ... FOR UPDATE SKIP LOCKED` daje potrzebne
gwarancje w jednym zapytaniu.

## Ulubione, notatki i alerty

```bash
uv run python scripts/alerts.py filtry            # stan alertow per filtr
uv run python scripts/alerts.py filtry-run        # przebieg, domyslnie na sucho
uv run python scripts/alerts.py filtry-run --wyslij
uv run python scripts/alerts.py watchdog-check    # czy portal nie ucichl
```

Sekcje 7.3 i 7.4 dokumentu. W aplikacji: gwiazdka na karcie oferty, status
(nowa, obserwuje, kontakt, odrzucona, kupiona), notatka, ocena kciukiem
i zakladka **zapisane**. W panelu filtrow: zapisanie biezacego filtru pod nazwa
i przelacznik alertu na Telegram. Endpointy: `GET/PUT/DELETE /api/saved/{id}`,
`POST /api/saved/{id}/ocena`, `GET/POST/PATCH/DELETE /api/filters`.

Trzy decyzje widoczne w zachowaniu:

* **zapisujemy oferte, nie dzialke ewidencyjna.** Migracja 012 przebudowuje
  `saved_parcels` na `saved_listings` z tego samego powodu, dla ktorego migracja
  007 przebudowala `scores`: pewne dopasowanie do dzialki mamy dla czesci ofert,
  a zapisac chce sie to, co sie wlasnie oglada;
* **zapisany filtr to dokladnie ten sam obiekt, co filtr listy.** Alert nie ma
  wlasnej logiki dopasowania, tylko sklada z niego to samo zapytanie SQL. Filtr,
  ktory pokazuje co innego niz alert, bylby gorszy niz brak alertu. Nieznane
  pole w filtrze to blad 422, a nie ciche pominiecie;
* **pierwszy przebieg alertu niczego nie wysyla.** Filtr wlaczony na duzej bazie
  pasuje od razu do kilkudziesieciu ofert. Pierwszy przebieg zapamietuje je jako
  znane, a alarmuje o tym, co pojawi sie pozniej. Interfejs mowi o tym wprost,
  zeby cisza po wlaczeniu nie wygladala na awarie.

Oferta zapisana zostaje w obserwowanych takze wtedy, gdy ogloszenie zniknie
z portalu; lista pokazuje wtedy, ze jest nieaktywna, zamiast ja ukryc -
znikniecie oferty samo w sobie jest informacja.

Alert sklada sie poprawnie i zatrzymuje na ostatnim kroku, bo w `.env` nie ma
`TELEGRAM_BOT_TOKEN` ani `TELEGRAM_CHAT_ID`. Modul dziala wtedy w trybie sucho:
formatuje tresc i zwraca ja zamiast wysylac, wiec brak konfiguracji nie wywala
harmonogramu. Tresc alertu nie zawiera zadnych danych kontaktowych sprzedajacego
- jest link do oferty i liczby, nie ma czlowieka. **Zalozenie bota jest jedynym
krokiem, ktorego nie da sie zrobic za uzytkownika.**

## Ceny w regionach i dynamika rynku

```bash
uv run python scripts/market.py run     # mediany, nazwy TERYT, przypisanie ofert
uv run python scripts/market.py status  # ile obszarow ma dynamike
uv run python scripts/market.py top     # gdzie ceny rosna najszybciej
curl "http://localhost:8000/api/market?poziom=gmina&segment=mieszkaniowa_jednorodzinna&min_n=30"
```

Mediany cen transakcyjnych per obszar i rodzaj gruntu, z kwartylami, liczba
transakcji i dynamika roczna. Na liscie ofert kolumna **vs rynek** pokazuje,
o ile procent oferta lezy powyzej albo ponizej mediany swojego rynku.
Klikniecie w wiersz rozwija wykres mediany kwartalnej z pasmem
miedzykwartylowym; wykres jest rysowany inline w SVG, bez biblioteki wykresow.

Przyklad (gminy, zabudowa jednorodzinna, n >= 30):

| obszar | mediana zl/m2 | surowa | kwartyle | transakcji | rocznie |
|---|---:|---:|---:|---:|---:|
| Gdynia (miasto) | 569 | 635 | 355-738 | 131 | -6,3% |
| Kosakowo | 554 | 467 | 364-814 | 153 | +12,3% |
| Wladyslawowo | 546 | 479 | 310-863 | 37 | +9,9% |
| Reda (miasto) | 390 | 374 | 316-527 | 58 | +7,0% |

**Decyzje, bez ktorych te liczby bylyby ozdoba:**

* **to wylacznie grunty niezabudowane.** Sprawdzone na wszystkich 137 298
  rekordach: `nier_rodzaj` ma jedna wartosc. Odfiltrowane sa sprzedaze
  z bonifikata i na cel publiczny (748 rekordow), bo to ceny administracyjne;
* **mediana jest znormalizowana do dzialki 1000 m2** (sekcja 5.2.1: nigdy nie
  porownuj surowej ceny za m2). Kolumna "surowa" stoi obok, zeby bylo widac, ile
  robi korekta: w Kosakowie 467 wobec 554 zl/m2;
* **mediana zawsze w jednym segmencie rynku.** Mieszanie gruntow rolnych
  z budowlanymi bylo pojedyncza przyczyna MdAPE 50% w pierwszej walidacji;
* **transakcje sa indeksowane na dzis** dynamika swojego obszaru. Okno to 24
  miesiace, a rynek rosnie 8-10% rocznie;
* **poziomow nie mieszamy.** Mediana ma byc prawdziwa mediana konkretnego
  obszaru; gmina bez 10 transakcji ustepuje powiatowi, a interfejs mowi ktory
  to poziom;
* **wykres rysujemy na terenie gminy, nie powiatu.** Powiat nie jest jednym
  rynkiem: w wejherowskim mediana idzie od 78 zl/m2 w gminie Linia do 488
  w Rumi, a udzial gmin w transakcjach zmienia sie z kwartalu na kwartal, wiec
  usredniony powiat pokazywalby zmiany struktury zamiast zmian cen;
* **ceny na wykresie NIE sa indeksowane na dzis**, inaczej niz w tabeli median.
  Indeksacja splaszczylaby dokladnie to, co wykres ma pokazac;
* **kwartal z mniej niz pieciu transakcjami nie dostaje punktu** i nie jest
  interpolowany; kwartal niepelny jest pusty w srodku i wylaczony z trendu
  (RCN konczy sie 30.07.2026, wiec 2026 Q3 ma 109 transakcji wobec ok. 1 700);
* **liczba transakcji ma wlasny pasek, nie druga os.** Dwie skale na jednym
  wykresie pozwalaja pokazac dowolna korelacje przez dobor zakresow;
* **trend roczny albo jest mierzalny, albo go nie ma.** Liczy go Theil-Sen tylko
  przy szesciu pelnych kwartalach, dwoch latach okna i medianie dziesieciu
  transakcji na kwartal. Na 106 gmin trend ma 57 - reszta pokazuje "trend
  niemierzalny" zamiast liczby.

Filar 6 (dynamika) omija dwie pulapki: **efekt skladu** - dynamike liczymy
osobno w kazdym segmencie i dopiero potem usredniamy wazac liczba transakcji,
czyli indeks o stalym koszyku; oraz **efekt skali** - ceny sa najpierw
normalizowane do 1000 m2 elastycznoscia `b1` z fazy 6. Gmina jest mieszana
z powiatem i wojewodztwem tak samo jak w Modelu 1 (`lambda = n / (n + 30)`),
a karta oferty pokazuje rozbicie na segmenty i udzial poziomow. Plynnosc
(transakcje na 1000 mieszkancow) wymaga liczby ludnosci, ktorej w RCN nie ma -
to jedyne miejsce, gdzie GUS BDL jest naprawde potrzebny.

## Kalibracja

```bash
uv run python scripts/calibrate.py run             # wszystkie pomiary i zapis
uv run python scripts/calibrate.py spread          # oferta vs wycena, per segment
uv run python scripts/calibrate.py pary            # wlasciwy pomiar: oferta -> RCN
uv run python scripts/calibrate.py beta1           # elastycznosc per segment
uv run python scripts/calibrate.py wrazliwosc      # +/-20% na jednym filarze
uv run python scripts/calibrate.py dyskryminacja   # czy scoring cokolwiek rozroznia
uv run python scripts/calibrate.py historia        # kolejne pomiary w czasie
```

Kazdy przebieg dopisuje wiersz do `calibrations`: to historia pomiarow, a nie
stan, wiec widac, jak liczby zmieniaja sie w miare przybywania danych.

**Spread oferta-transakcja.** Wlasciwy pomiar wymaga par "oferta zniknela
z portalu, jej dzialka pojawila sie w RCN". Takich par jest dzis zero i tak ma
byc: RCN konczy sie 30.07.2026, a oferty zbieramy od 21.08.2026. Zapytanie jest
gotowe i zacznie zwracac wynik samo. Do tego czasu liczymy szacunek zastepczy:
iloraz ceny ofertowej do wyceny modelu. **To nie jest ta sama liczba** i ma
w kodzie inne `zrodlo`, bo miesza prawdziwy spread z bledem modelu.

**Deal score dostal sens.** Przed kalibracja: mediana -0,62, zero ofert powyzej
progu okazji. Po korekcie o zmierzone +24,3%: mediana +0,14, powyzej progu 1,5
jest 13 ofert. Bez kalibracji `aktualny_spread` zwraca 0,0 i deal score zostaje
surowy: brak pomiaru ma byc widoczny w liczbie, a nie zalatany zalozeniem
z literatury.

**Wrazliwosc na wage pojedynczego filaru.** Kryterium fazy 6: zmiana wagi filaru
o +/-20% nie moze przesunac pierwszej dziesiatki o wiecej niz 3. Pomiar bierze
po kolei kazdy filar, mnozy jego wage przez 1,2 albo 0,8, renormalizuje reszte
i przelicza caly ranking - bez losowosci. Kryterium da sie czytac na dwa
sposoby i **oba daja przeciwne odpowiedzi**:

| Odczyt | Zmierzone | Prog | |
|---|---|---|---|
| (a) najdalszy ruch pojedynczej oferty | 8 pozycji | 3 | nie przeszedlby |
| **(b) wymiana skladu czolowki** | **1 z 10 ofert** | **3** | **przechodzi** |

**Obowiazuje (b).** Uzasadnienie jest w sekcji 21.1 dokumentu koncepcyjnego,
powtorzone przy stalej `MAX_ZMIANA_CZOLOWKI` i pilnowane testem
`test_prog_dotyczy_skladu_a_nie_pozycji`. Skrocone: (a) skaluje sie z liczba
ofert, wiec robi sie trudniejsze wylacznie od przybycia danych; (a) liczylby
drugi raz gestosc rozkladu, ktora mierzy juz osobno test dyskryminacji; (b)
odpowiada temu, co widzi uzytkownik, bo aplikacja pokazuje liste, nie numery
miejsc. Kontrargument zostaje w mocy: skoro numer miejsca zalezy od 20% wagi,
numeru miejsca nie wolno pokazywac jako twardej informacji - dlatego (a) nie
znikl, tylko zszedl do diagnostyki.

Pomiar raportuje takze flage `rozstrzygajacy`. Przy 101 ofertach dawal
przesuniecie 0 we wszystkich dwunastu przypadkach, ale sam siebie oznaczal jako
nierozstrzygajacy, bo w czolowce roznil sie tylko jeden filar. Bez tej flagi
zielone kryterium fazy 6 zostaloby zapisane i nikt by do niego nie wrocil.

## Chlonnosc i PUM

Filar 7, tylko w profilu dewelopera (5% wagi). Warstwa `strefaPlanistyczna`
planu ogolnego oddaje komplet wskaznikow zabudowy **w tym samym
`GetFeatureInfo`, ktorym i tak pytamy o symbol strefy**, wiec filar nie kosztuje
ani jednego zapytania wiecej. Wskazniki ida do `listing_enrichment.features` pod
`planistyka.wskazniki`, wiec nie byla potrzebna zadna migracja.

Co przychodzi (przyklad z Gdyni, dwie rozne strefy):

```
                                        SJ      SW
maksNadziemnaIntensywnoscZabudowy       0,4     2,5
maksUdzialPowierzchniZabudowy            25%     50%
maksWysokoscZabudowy                      9 m    17 m
minUdzialPowierzchniBiologicznieCzynnej  50%     30%
```

Rachunek jest w `scoring/chlonnosc.py`, wprost za sekcja 5.2.5. Ograniczenia
liczone niezaleznie, wiazace jest najostrzejsze:

```
kondygnacje = floor(H_max / 3,2 m)

z intensywnosci       PC = A * I
z udzialu zabudowy    PC = A * U * kondygnacje
z biol. czynnej       PC = A * (1 - PBC) * kondygnacje

PUM = min(dostepnych) * eta
```

Dzialka 1000 m2 w strefie SJ: wiaze intensywnosc (400 m2 calkowitej), eta 0,80,
czyli **320 m2 PUM**. Ta sama dzialka w SW: 2 500 m2 calkowitej, eta 0,70, czyli
**1 750 m2 PUM**.

Trzy decyzje, zanim ktos zacznie sie klocic z liczbami:

* **wysokosc nie jest osobnym ograniczeniem powierzchni.** Wchodzi do dwoch
  pozostalych przez liczbe kondygnacji. Strefa podajaca udzial zabudowy bez
  wysokosci nie ogranicza wiec powierzchni calkowitej niczym poza
  intensywnoscia;
* **wynik mowi, KTORE ograniczenie zawazylo.** "800 m2" nic nie znaczy, a
  "800 m2, bo minimalny udzial biologicznie czynny to 50%" da sie obronic. Pole
  `wiazace_ograniczenie` jest w `pillar_scores`;
* **brak wskaznika to nie zero.** Strefa bez limitu wysokosci ma tu `None` i nie
  wnosi ograniczenia. Gdy nie ma zadnego, filar jest niedostepny i wchodzi do
  renormalizacji wag.

Punktacja jest w PUM na metr dzialki, bo tylko ta postac da sie porownac miedzy
dzialkami roznej wielkosci; skala 0,2-1,5 obejmuje rozpietosc planu ogolnego.
Filar celowo premiuje wysoka intensywnosc, bo profil deweloperski kupuje grunt
pod PUM. W profilu detalicznym tego filaru nie ma w ogole.

## MPZP z Rejestru Urbanistycznego

Adresy uslug sa w zakladce **Uslugi sieciowe** samej aplikacji, ale nie w tresci
strony, tylko pod przyciskiem kopiujacym do schowka - w DOM ich nie ma, bo
mikrofrontend doczytuje je w locie. Odczytane i zapisane w `sources/mpzp.py`:

```
MPZP           WMS  https://rejestr-urbanistyczny.gov.pl/uslugi-sieciowe/wms-mpzp/wms
               WFS  https://rejestr-urbanistyczny.gov.pl/uslugi-sieciowe/app-mpzp/wfs
plany ogolne   WMS  .../wms-pog/wms          WFS  .../app-pog/wfs
REST           GET  /api/public/published/territorial/tree?level=COMMUNE
               POST /api/public/published/query
```

**Co daje.** Granice aktu, tytul, date wejscia w zycie, status prawny
i identyfikator IIP z TERYT-em gminy. To wystarcza, zeby powiedziec "dzialka
jest objeta MPZP".

**Czego nie daje: przeznaczenia terenu.** Symbolu MN, U czy MW nie ma w zadnym
z trzech typow obiektow. Dowod jest w obiekcie
`RysunekAktuPlanowaniaPrzestrzennego`: rysunek planu to **georeferencowany
TIFF**, a legenda strona HTML, wiec symbol jest pikselem na skanie, nie
atrybutem. Dzialka objeta planem nie dostaje wiec stanu A, tylko stan posredni
**"objeta MPZP, przeznaczenie nieznane"** z przedzialem mnoznika 0,45-1,00.

Stad asymetria calego systemu: strefe planu ogolnego znamy co do liczby,
a przeznaczenie MPZP tylko z faktu objecia planem. `POST /query` odrzuca puste
cialo bledem 3000, a na zgadywane ksztalty odpowiada 5000, wiec kontrakt pol
trzeba jeszcze odczytac z aplikacji - ale to nie odblokuje stanu A.

```bash
uv run pytest tests/test_mpzp.py -m network    # kontrola, czy usluga nadal odpowiada
```

## Wzbogacanie i scoring

```bash
uv run python scripts/enrich.py run --limit 10     # dociagniecie danych publicznych
uv run python scripts/enrich.py status             # kryterium akceptacji fazy 3
uv run python scripts/enrich.py show --listing-id 663
uv run python scripts/score.py run                 # score i deal score
uv run python scripts/score.py top --limit 15      # ranking
```

Jedna oferta to ok. 20 zapytan do uslug publicznych (EGiB, plan ogolny, ISOK,
NMT, KIUT), czyli kilkanascie sekund. Wzbogacanie jest przyrostowe: bierze
oferty bez wzbogacenia albo starsze niz 30 dni. Cechy dzielimy na dwie klasy:
dla **punktu** (plan ogolny, OUZ, powodz, wysokosc, spadek, uzbrojenie - warstwy
wieksze niz dzialka, wiec blad 100 m nie zmienia wyniku) i dla **dzialki**
(front, smuklosc, zwartosc, azymut - wymagaja pewnego dopasowania, a bez niego
zostaja puste i obnizaja coverage, zamiast byc zmyslone).

## Czego nauczyly nas dane

Rzeczy, ktorych nie dalo sie przewidziec przed dotknieciem zrodel. Kazda kosztowala
osobne dochodzenie, wiec sa tu po to, zeby nie kosztowaly go drugi raz.

**O modelu i rynku**

1. **Przeznaczenie decyduje o wszystkim.** `terenRolniczy` to mediana 16,6 zl/m2,
   `budownictwoMieszkanioweJednorodzinne` 158,2 zl/m2, `terenZabudowyUslugowej`
   248,1 zl/m2. Model bez segmentacji mial MdAPE 50%, z segmentacja 20%.
2. **Elastycznosci `b1` nie da sie estymowac na wymieszanych danych.** Wychodzi
   0,26 zamiast 0,85, bo powierzchnia jest wtedy zmienna zastepcza dla
   przeznaczenia: mala dzialka "rolna" pod Trojmiastem to dzialka budowlana.
   Po podziale na segmenty (104 tys. transakcji): jednorodzinna 0,756, uslugowa
   i produkcyjna 0,855, drogi 0,822, wielorodzinna 1,136. Segmenty, ktore nadal
   sa mieszanka, widac po niskiej wartosci: rolna 0,523 i budowlana z WZ 0,496
   przy `R2` 0,11. Z wezlami elastycznosc jest wyraznie niemonotoniczna
   (w pasmie 800-3000 m2 spada do ok. 0,22), dokladnie jak opisuje Ritter.
3. **Odleglosc bije granice administracyjna.** Blad rosnie z 28% do 62%, gdy
   lokalnych transakcji jest mniej niz piec, a obreb ewidencyjny bywa
   szescio-kilometrowy. Stad Model 2 i indeks GiST na centroidzie.
4. **RCN zawiera transakcje, ktore nie sa obrotem rynkowym**: przeniesienia po
   1,8 zl/m2, udzialy 1/222, daty w przyszlosci (rok 3517). Zakres stosowalnosci
   modelu jest zawezony jawnie i opisany w `scripts/eval_valuation.py`.
5. **Deal score jest niemal zawsze ujemny** i tak ma byc do czasu kalibracji:
   model uczy sie na cenach TRANSAKCYJNYCH, a porownuje z OFERTOWYMI.
6. **Dynamika cen gruntow w pomorskim to mediana +10% rocznie na poziomie
   gminy** (76 gmin, 30 tys. transakcji), przy sredniej +6,0% po zmieszaniu.
   Prog "co jest jeszcze rynkiem" trzeba bylo obnizyc z 60% do 40% rocznie na
   segment: przy 60% przechodzil przypadek "-42% rocznie", czyli dzialki
   w miescie w 2023 i na obrzezach w 2026.

**O scoringu i o mierzeniu wlasnej roboty**

7. **Test, ktory nie ma czego zmierzyc, wyglada dokladnie jak test zdany.**
   Analiza wrazliwosci przy 101 ofertach dala przesuniecie 0 we wszystkich
   dwunastu przypadkach, czyli kryterium fazy 6 formalnie spelnione. Powod byl
   inny: w czolowce roznil sie jeden filar, wiec ranking byl posortowaniem
   jednej liczby i zaden dobor wag nie mogl go odwrocic. Kazda miara
   walidacyjna musi raportowac nie tylko wynik, ale i to, czy miala szanse
   wypasc inaczej - stad flaga `rozstrzygajacy` obok `spelnione`.
8. **Miara, ktora rosnie razem z baza, nie mierzy jakosci.** Ta sama zmiana
   wyniku o 0,3 punktu daje 8 miejsc przy 126 ofertach i kilkaset przy 4 000.
   Kryterium, ktore robi sie trudniejsze wylacznie od przybycia danych, karze za
   rozwoj projektu - dlatego faze 6 czytamy przez sklad czolowki.
9. **Scoring slabo rozroznia dzialki: 43% ofert w przedziale 60-70 punktow**,
   przy progu 35% z sekcji 5.6. Ten sam powod co wszedzie: kilka filarow
   z siedmiu i bramka `poza_ouz` robia wiekszosc roboty.
10. **Dolozenie filaru pogorszylo test dyskryminacji** (38% -> 43%). To nie blad
   filaru, tylko wlasnosc sredniej wazonej: im wiecej skladnikow, tym bardziej
   wynik sciaga sie do srodka. Odpowiedzia nie jest ukrycie miary, tylko macierz
   2x2 z sekcji 5.7 zamiast jednej liczby.
11. **Sukces zadania nie znaczy, ze cos sie stalo.** `alert_log` byl pusty przy
   udanych przebiegach zadania `alerty`, co wygladalo na zepsuta sciezke
   powiadomien. Przyczyna: zero zapisanych filtrow, wiec zadanie konczylo sie
   sukcesem po zeru dopasowan.

**O uslugach publicznych**

12. **Wspolrzedne z portali nie identyfikuja dzialki.** Dla oferty z Morizona
   ULDK zwraca dzialke 886 m2 przy deklarowanych 1115 m2, dla oferty z N-O
   18 983 m2 przy 835 m2. ULDK po wspolrzednych to generator kandydata, nie
   identyfikacja, i wzbogacanie musi weryfikowac dopasowanie powierzchnia.
13. **Puste pole w schemacie usluga potrafi oddac jako string `'None'`.** EGiB
   WFS ma w schemacie `KLASOUZYTKI_EGIB` i `POLE_EWIDENYJNE`, i oba wracaja
   z doslowna trescia `None`. Kod sprawdzajacy tylko obecnosc elementu zapisalby
   tekst "None" jako sposob uzytkowania. Ta sama pulapka jest w KIUG, gdzie
   "Oznaczenie uzytku" wraca jako pusty string. Sprawdzone w miescie, w lesie
   i na wsi, bo pierwsza hipoteza brzmiala "to tylko Gdansk".
14. **KIUT nie ma uzytecznego GetFeatureInfo** - zwraca staly komunikat dla
   kazdej warstwy i promienia. Obecnosc sieci wykrywamy przez GetMap i rozmiar
   PNG (237 B to pusto, 114 B to odmowa ze wzgledu na skale).
15. **To samo GetFeatureInfo nioslo dane, o ktore nikt nie pytal.** Filar
   chlonnosci mial zero na 103 oferty i byl zapisany jako "wymaga sprawdzenia,
   czy usluga w ogole zwraca wskazniki". Zwraca, i to w odpowiedzi, ktora juz
   pobieralismy. Warto czasem wypisac cala odpowiedz uslugi, a nie tylko pola,
   ktore sie parsuje.
16. **Plan ogolny ma 14 ze 145 gmin pomorskiego (9,7%)**, a w gminach z planem
   na 60 punktach 16 lezy w OUZ. Termin ustawowy to 31.08.2026, wiec pokrycie
   bedzie szybko rosnac, a przejscie gminy ze stanu E do D obniza wartosc
   dzialek poza OUZ o kilkadziesiat procent w jeden dzien.
17. **Rejestr Urbanistyczny ma 524 akty MPZP w calym kraju**, z czego 111
   w pomorskim i wszystkie z Gdanska. Sprawdzenie 30 losowych ofert: zero
   objetych; czterech ofert w samym Gdansku: tez zero, bo miasto opublikowalo
   kilkadziesiat najnowszych z setek. Mechanizm jest gotowy, ale dzis nie
   zmienia ani jednej oferty.
18. **Trzecia konwencja osi w czwartej usludze.** Rejestr Urbanistyczny czyta
   `BBOX` z krotkim kodem `EPSG:2180` jako easting,northing, a z forma urn
   odwrotnie. Pomylona kombinacja nie zwraca bledu, tylko zero obiektow, co
   wyglada jak "nie ma planu". Od teraz kolejnosc osi wynika z formy `srsName`
   (`gml.kolejnosc_easting_first`), a nie z zalozenia w kodzie wolajacego.

**O portalach**

19. **"Portal odmawia" bywa nieaktualne po kilku dniach.** Dokument spisal
   Otodom na straty (403, jedyna droga to platny Apify) i ta notatka
   ksztaltowala plan wydatkow. Sprawdzenie zajelo jedno zapytanie i wyszlo 200
   plus `Allow: /`. Wniosek nie brzmi "dokument klamal", tylko: **stwierdzenie
   o cudzym serwerze ma date waznosci**, wiec zanim zaplaci sie za obejscie,
   trzeba je powtorzyc.
20. **Ten sam wlasciciel to ta sama konstrukcja.** Gratka okazala sie Morizonem
   z innymi slugami. Przy dwoch portalach kopia byla tansza niz abstrakcja,
   przy czterech juz nie - dopiero to uzasadnilo `portals/_shared.py`.
21. **Zanim siegniesz po miare podobienstwa, sprawdz, czy nie masz gdzies
   tozsamosci.** Dwa z trzech najsilniejszych sygnalow deduplikacji sa puste
   (`phone_sha256`, bo telefonu nie zbieramy; `thumb_phash`, bo wymagalby
   biblioteki do obrazow), a mimo to deduplikacja dziala - bo sam adres pliku
   miniatury jest wspolny dla Morizona i Gratki. Duplikatow bylo 4,4%, dopoki
   portale byly dwa; po dojsciu Gratki jest 19,8%. Przeszacowana byla nie
   prognoza z sekcji 9 (30-45%), tylko nasza liczba portali.
22. **Udzial policzony na czesciowo zaladowanym zbiorze nie jest udzialem.**
   Pierwszy pomiar duplikatow Gratki, na 323 z 1 195 ofert, dal 96,6% i wygladal
   jak gotowy wniosek produktowy. Po uzupelnieniu calej Gratki wyszlo 58%.
   Kod byl poprawny; bledna byla probka, bo uzupelnianie szlo po
   identyfikatorach, a najstarsze oferty Gratki to dokladnie te, ktore byly juz
   wczesniej widziane na Morizonie. Kazda liczba typu "ile procent X to Y" ma
   miec obok siebie licznik i mianownik, a jesli mianownik rosnie w trakcie
   pomiaru, ma byc opisana jako dolna granica.
23. **W obrebie jednego portalu, bez sygnalu tozsamosci, powierzchnia musi
   zgadzac sie co do metra.** Tytuly na Morizonie sa generowane ze wzorca
   "Dzialka na sprzedaz, {powierzchnia} m2 {miejscowosc}", wiec dwie sasiednie
   dzialki z jednego podzialu maja ten sam tytul, ten sam punkt i podobna
   powierzchnie. Bez tej reguly Tywezy 1409 m2 i 1387 m2 przy tej samej ulicy
   sklejaly sie w jedna dzialke.
24. **Portale nie mowia, jakiego rodzaju jest dzialka.** `przeznaczenie_raw`
   wyglada jak klasyfikacja, ale to strzepy opisu: na 723 ofertach najczestsze
   wartosci to "budowlana" (26 razy), "Planem Zagospodarowania" (17) i "mpzp"
   (4). Podanie tego klasyfikatorowi ze slownikiem RCN wrzucalo 351 z 361 ofert
   do kubla "nieokreslona", a ten kubel to glownie tanie grunty rolne - wiec
   kazda oferta wygladala na 87% powyzej rynku. Po rozpoznaniu rodzaju z tresci
   ogloszenia mediana odchylenia spadla do +34%, co zgadza sie ze zmierzonym
   niezaleznie spreadem +24%.
25. **Pole "powierzchnia" bywa powierzchnia budynku.** Oferta "Gospodarstwo
   rolne, 150 m2 za 4,29 mln zl" dawala 14 512 zl/m2 i udawala 161-krotnosc
   mediany. Znormalizowana cena poza zakresem 1-5000 zl/m2 to blad danych, nie
   okazja, i takich ofert nie porownujemy wcale.
26. **robots.txt Morizona zabrania sortowania i stron powyzej 10**, wiec
   strategia "skanuj listing po dacie i przerwij na pierwszej niezmienionej
   stronie" z sekcji 18.2 jest niewykonalna; zamiast tego 20 waskich zapytan per
   powiat. Do tego `urllib.robotparser` ze stdliba nie zna wildcardow
   i przepuszczal te zakazy - stad wlasny parser w `ingest/robots.py`.

**O samym projekcie**

27. **Zadeklarowana zaleznosc to nie uzyta zaleznosc.** `pyproject.toml`
   wymienial `curl-cffi`, `selectolax`, `pyarrow` i `pyogrio`, a `CLAUDE.md`
   podawal dwie pierwsze jako stack. Zaden z tych pakietow nie byl importowany
   w ani jednym pliku: HTTP idzie przez httpx, HTML-a nie parsujemy selektorami
   (wszystkie cztery portale oddaja dane jako JSON w tresci strony), a GML czyta
   stdlibowy ElementTree. Cztery zaleznosci usuniete 25.08.2026, testy bez
   zmian. Warto sprawdzac to samo przy kazdym audycie: opis stacku ma opisywac
   kod, a nie plan sprzed poltora roku.

## Ukladu wspolrzednych nie ruszaj bez `sources/geo.py`

Uslugi, ktorych uzywamy obok siebie, maja cztery rozne konwencje osi: ULDK
`easting,northing`, NMT `x=northing&y=easting`, WMS 1.3.0 i GML z RCN
`northing easting`, Rejestr Urbanistyczny zaleznie od formy `srsName`. Przy
zamianie nie ma bledu, tylko dane z innego miejsca w Polsce. Wszystkie
przeliczenia ida przez `sources/geo.py`, a `tests/test_geo.py` sprawdza znany
punkt w Gdansku przez wszystkie konwencje.

W bazie wszystkie geometrie sa w EPSG:2180, na wyjsciu API zawsze EPSG:4326.

## Testy

```bash
uv run pytest                 # 525 testow, bez sieci
uv run pytest -m network      # 11 testow odpytujacych uslugi publiczne na zywo
```

Testy sieciowe sa oznaczone markerem i domyslnie wylaczone, ale warto je
uruchamiac po zmianach w `sources/`: sprawdzaja, czy uslugi GUGiK nadal
odpowiadaja tak samo.

## Struktura

```
src/grunt/
  config.py            jedyne miejsce czytajace .env
  models.py            ORM, odpowiada DDL z sekcji 16
  sources/             jeden plik na zrodlo danych
    geo.py             przeliczenia ukladow, CZYTAJ NAJPIERW
    uldk.py            wspolrzedne -> numer dzialki (most miedzy warstwami)
    rcn.py             parser WFS Rejestru Cen Nieruchomosci
    rcn_import.py      quadtree + zapis do PostGIS
    rcn_query.py       dobor porownywalnych, w tym KNN przestrzenny
    mpzp.py            MPZP z Rejestru Urbanistycznego, adresy uslug i REST
    plan_ogolny.py     strefa planistyczna, OUZ, wskazniki zabudowy
    egib.py isok.py kiut.py nmt.py gml.py
  portals/             jeden portal = jeden plik
    base.py            protokol PortalAdapter (sekcja 18.1)
    _shared.py         to, co naprawde wspolne: JSON-LD, ceny, flagi mediow
    morizon.py         JSON-LD listingu, wspolrzedne z __NUXT_DATA__
    gratka.py          jak Morizon (ta sama grupa), inne slugi powiatow
    otodom.py          __NEXT_DATA__, dostep do drogi i media jako POLA
    nieruchomosci_online.py  wymiary dzialki wprost z ogloszenia
    registry.py        jedyne miejsce rejestracji adapterow
  ingest/
    normalize.py       cena, powierzchnia, jednostki, hash telefonu
    robots.py          wlasna interpretacja robots.txt z wildcardami
    runner.py          petla DIFF, jedyne miejsce robiace zadania HTTP
  enrich/
    match_parcel.py    wiazanie oferty z dzialka, z poziomem pewnosci
    parcel_ref.py      numer dzialki z tresci ogloszenia
    parcel_store.py    zapis geometrii dzialki do parcels (obrys na mapie)
    kategoria.py       rodzaj i gmina oferty, bez ani jednego zapytania HTTP
    geometry.py        front, smuklosc, zwartosc, azymut
    pipeline.py        orkiestracja wzbogacania
    score_listings.py  zapis score'ow do bazy
    calibrate.py       pomiary kalibracyjne na danych z bazy
    market.py          dynamika i mediany z RCN, nazwy TERYT z ULDK
  scoring/             funkcje czyste, bez bazy i sieci
    normalize_area.py  korekta efektu skali
    segments.py        segmentacja rynku po przeznaczeniu (11 kubelkow, wycena)
    rodzaj.py          rodzaj dzialki (4 kubelki, filtr uzytkownika)
    valuation.py       Model 1, Model 2, deal score
    pillars.py         siedem filarow
    gates.py           bramki jako mnozniki
    planning.py        status planistyczny A-E
    chlonnosc.py       PUM z wskaznikow zabudowy (sekcja 5.2.5)
    calibration.py     spread, korelacja rang, wrazliwosc wag, dyskryminacja
    market.py          dynamika cen, mediany rynku, odchylenie oferty
  dedup/               deduplikacja cross-portal (sekcja 4.3)
    keys.py            klucz z miniatury, siatka blokujaca, tokeny, Hamming
    pairing.py         dobor par i punktacja przeslanek
    cluster.py         union-find, rekord kanoniczny, rozrzut cen
    pipeline.py        jedyne miejsce w dedup/ dotykajace SQL
  alerts/
    telegram.py        alerty z przyciskami inline, tryb sucho bez tokena
    watchdog.py        alarm, gdy portal ucichl albo zrodlo pada
    saved_filters.py   powiadomienia z zapisanych filtrow, bez powtorek
  jobs/                harmonogram bez dodatkowej biblioteki
    queue.py           tabela jobs, SKIP LOCKED, backoff
    scheduler.py       co i jak czesto, decyzja jako funkcja czysta
    handlers.py        rodzaj zadania -> pipeline
    worker.py          petla, osobna transakcja na kazdy krok
  api/                 FastAPI: listings (+ geojson, kategorie, obrys), market,
                       valuate, saved, metodologia, harmonogram, health, stats
db/migrations/         Alembic, 15 migracji
web/src/               Next.js 16, Tailwind 4, MapLibre; 12 komponentow
scripts/               local_pg.ps1, bootstrap_data.py, eval_valuation.py,
                       scrape.py, scrub_snapshot.py, audit_pii.py, dedup.py,
                       jobs.py, calibrate.py, market.py, enrich.py, score.py,
                       alerts.py, parcels.py
```

## Czego nie ma i co to blokuje

Kolejnosc wedlug stosunku wartosci do kosztu. Zadna z tych pozycji nie jest
zablokowana na kod - kazda czeka na zrodlo danych, decyzje albo prace reczna.

**Wymagaja decyzji o zrodle danych**

* **Dostep do drogi i sposob uzytkowania.** Bramki `brak_dostepu_do_drogi`
  i `grunt_lesny` nigdy sie nie wlaczaja poza ofertami z Otodomu. Sprawdzone
  25.08.2026: ani EGiB, ani KIUG nie oddaja sposobu uzytkowania (pola sa
  w schemacie, wracaja puste), a sieci drog nie ma w bezplatnej usludze
  **zapytaniowej** - WMS BDOT10k pod `PobieranieBDOT10k` wystawia wylacznie
  granice administracyjne, `G2_BDOT10k_WMS` zwraca 401, a
  `KrajowaIntegracjaBDOT10k` nie istnieje. Zostaja trzy drogi i kazda jest
  decyzja: import BDOT10k jako GML per powiat (parser GML jest, ale to 20 paczek
  i nowa tabela), ekstrakt OSM (nowa zaleznosc do PBF) albo Overpass API (bez
  nowej zaleznosci, ale to zapytanie na oferte do serwisu spolecznosciowego).
* **Filar lokalizacji (22% wagi).** Jedyny filar bez ani jednej wartosci.
  Wymaga wlasnej instancji Valhalli i ekstraktu OSM, czyli decyzji
  infrastrukturalnej. Najwiekszy pojedynczy brak w scoringu.
* **Przeznaczenie terenu w MPZP** (symbol MN, U, MW), a wiec status planistyczny
  A. Nie ma go w zadnej postaci danych: rysunek planu to georeferencowany TIFF
  plus legenda HTML, wiec odczytanie symbolu wymagaloby interpretacji rastra.
* **Plynnosc rynku** jako druga skladowa filaru 6: transakcje na 1000
  mieszkancow wymagaja liczby ludnosci gminy, ktorej w RCN nie ma. To jedyne
  miejsce, gdzie GUS BDL jest naprawde potrzebny.

**Wymagaja pieniedzy albo pracy recznej**

* **OLX.** Jedyny portal, ktorego nie da sie pobrac uczciwie. Zostaje platny
  aktor Apify (ok. 200 zl miesiecznie) albo podszycie sie pod przegladarke,
  a tego `CLAUDE.md` zabrania wprost.
* **Zbior 200 recznie oznakowanych par** do strojenia progow deduplikacji.
  Narzedzia sa (`dedup pary`, `dedup oznacz`, `dedup precyzja`), oznakowanych
  par jest zero. To ostatnia rzecz brakujaca do domkniecia fazy 5.
* **pHash miniatur.** Kolumna `listings.thumb_phash` czeka. Dla Morizona
  i Gratki nie jest juz potrzebny (klucz z adresu miniatury), ale dla Otodomu
  i Nieruchomosci-online, ktore maja wlasne CDN-y, byloby to jedyne wejscie
  etapu 3. Wymaga biblioteki do obrazow, czyli zgody.
* **Test zgodnosci z ekspertami** (`rho > 0,6`). Korelacja rang jest policzona
  i przetestowana, brakuje ludzi z branzy i 50 ocenionych dzialek.
* **Alert dostarczony na telefon.** Cala sciezka dziala i sklada poprawna
  wiadomosc. Brakuje `TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID` w `.env`, czyli
  konta bota, ktorego nie zakladam za uzytkownika.

**Zaobserwowane, niewyjasnione**

* **Filtr listy raz zniknal bez sladu.** 25.08.2026 test
  `test_filtr_ceny_dziala` wywalil sie trzy razy z rzedu: `/api/listings`
  z `price_max=200000` oddalo **7 300 ofert zamiast 2 415**, w tym oferte za
  2 240 000 zl, czyli zapytanie poszlo bez warunku `price_grosze <= :price_max`.
  Po kilkunastu minutach objaw znikl i nie udalo sie go odtworzyc ani w tescie,
  ani osobnym skryptem (po trzy przebiegi kazdego), mimo nietknietego kodu.
  Podejrzenie pada na te sama przyczyne, ktora opisuje docstring
  `ListingFilter`: FastAPI 0.141 przy `Depends()` potrafi po cichu zgubic pola
  modelu. Dotad wygladalo to na problem wylacznie pol listowych, a ten przypadek
  sugeruje, ze moze dotknac takze pola skalarnego. Test zostaje jako detektor:
  filtr, ktory nic nie filtruje, jest gorszy niz jego brak, wiec awaria musi byc
  glosna. Gdy objaw wroci, nastepny krok to zdjecie `Depends()` z tego endpointu
  i jawne wypisanie wszystkich pol w sygnaturze.

**Zostaje otwarte swiadomie**

* **Spread liczony na parach oferta-transakcja** (sekcja 5.6). Mechanizm jest
  gotowy i wlaczy sie sam, gdy oferty zaczna znikac z portali, a ich dzialki
  pojawiac sie w RCN. Dzis deal score stoi na szacunku zastepczym.
* **Gestosc rozkladu wynikow.** 43% ofert siedzi w jednym przedziale
  dziesieciopunktowym. To nie wada wag, tylko konstrukcji wyniku, i odpowiedzia
  jest macierz 2x2 z sekcji 5.7, a nie strojenie wag.
* **Czestotliwosc Gratki.** Ponad polowa jej ofert to duplikaty Morizona
  i udzial ten wciaz rosnie, wiec warto sie zastanowic, czy jej przebieg ma
  dalej chodzic co 6 godzin. Decyzje warto podjac po domknieciu uzupelniania
  detali Morizona, bo dopiero wtedy liczba przestanie sie ruszac.
* **Typy poza `scoring/`, `sources/` i `portals/`**: 17 bledow mypy w trybie
  domyslnym. `CLAUDE.md` wymaga trybu strict tylko dla tych trzech katalogow.
* **Wiecej niz jeden uzytkownik.** Kolumny `user_id` sa w schemacie, ale nie ma
  logowania: jeden wiersz w `users` i staly identyfikator w API. Dolozenie
  drugiej osoby to uwierzytelnianie, nie migracja danych.
