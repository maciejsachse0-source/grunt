# GRUNT: system wyszukiwania i oceny potencjału działek

**Dokument koncepcyjny i architektoniczny**
Wersja 1.1, 20 sierpnia 2026
Część I (sekcje 0-12): co budujemy i dlaczego
Część II (sekcje 13-23): jak, na poziomie gotowym do przekazania Claude Code
Zakres startowy: województwo pomorskie, docelowo cała Polska
Nazwa robocza projektu: GRUNT (do zmiany)

---

## 0. TL;DR na jedną stronę

Jeśli masz przeczytać tylko jedną sekcję, to tę.

**Co budujemy:** aplikację webową dla Ciebie i kilku osób, która codziennie zbiera oferty działek z polskich portali, wzbogaca je o dane publiczne (granice działki, przeznaczenie, uzbrojenie, ryzyka), wycenia je modelem opartym na **realnych cenach transakcyjnych**, i sortuje po scoringu potencjału inwestycyjnego.

**Pięć ustaleń z researchu, które zmieniają ten projekt:**

| # | Ustalenie | Konsekwencja |
|---|---|---|
| 1 | **Rejestr Cen Nieruchomości jest bezpłatny od 13.02.2026.** WFS `mapy.geoportal.gov.pl/wss/service/rcn` zwraca cenę transakcyjną, geometrię, numer działki, przeznaczenie w MPZP. Zweryfikowane na 5 lokalizacjach w pomorskim | To fundament projektu, nie scraping. Masz dostęp do danych, za które jeszcze rok temu płaciło się 9-12 zł za rekord |
| 2 | **Otodom i OLX zwracają 403 z każdego IP datacenter**, łącznie z `/robots.txt`. Gratka, Morizon, Nieruchomosci-online, Domiporta, GruntGuru działają normalnie | Portale dzielą się na tanie i drogie. Drogie kupujesz gotowe, nie walczysz z nimi |
| 3 | **Gratka i Morizon mają identyczny zasób** (4 953 działki w pomorskim w obu). To jedna grupa | Scrapujesz jeden, nie dwa |
| 4 | **Żaden duży gracz nie robi AVM dla gruntów niezabudowanych.** Ani Zillow, ani Redfin (wprost się ogranicza do budynków), ani Cenatorium, ani SonarHome | To jest realna luka, nie tylko Twoje narzędzie do własnych poszukiwań |
| 5 | **Reforma planistyczna: plany ogólne gmin do 31.08.2026.** Działka poza Obszarem Uzupełnienia Zabudowy, bez MPZP, praktycznie traci ścieżkę do zabudowy | To najsilniejszy pojedynczy determinant wartości działki w Polsce w tym momencie i najsłabiej pokryty przez konkurencję |

**Rekomendowany stack:** Python + Crawlee + PostgreSQL/PostGIS + FastAPI + Next.js, cały kod pisany przez AI. Otodom i OLX kupowane jako gotowe aktory Apify.

**Koszt:** **0 zł w wariancie lokalnym** (wszystko na Twoim komputerze, sekcja 13), ok. 45 zł miesięcznie gdy chcesz, żeby chodziło 24/7 bez Ciebie, ok. 350 zł z Otodomem i bazą w chmurze. Startujemy lokalnie.

**Dlaczego nie no-code, mimo Twojej preferencji:** szczegółowo w sekcji 4.1. Skrót: narzędzia no-code kosztują tu 4 do 8 razy więcej, nie obejdą blokady Otodomu, a scoring geoprzestrzenny (spatial join z MPZP, ULDK, strefami zalewowymi) jest w nich niewykonalny. Airtable ma sufit 125 tys. rekordów i zero geografii. Ale "kod" w 2026 nie znaczy "piszesz go sam", tylko "prowadzisz AI po architekturze", czyli dokładnie to, jak pracujesz.

**Trzy rzeczy, które podniosą jakość scoringu najbardziej:**
1. Normalizacja ceny za m2 do referencyjnej powierzchni (cena za m2 systematycznie spada z wielkością działki, potwierdzone badaniami PL, DE i USA)
2. Hierarchiczny shrinkage bayesowski zamiast twardych progów "min. 15 porównywalnych"
3. Status planistyczny jako mnożnik zerujący, nie jako składnik sumy ważonej

---

## 1. Co ten program ma robić

### 1.1. Trzy pętle

Cały system to trzy pętle działające w różnym rytmie:

```
PĘTLA DZIENNA (nocny cron, 02:00 - 05:00)
  scraping portali -> deduplikacja -> wzbogacenie danymi publicznymi
  -> przeliczenie scoringu -> alerty o nowych trafieniach

PĘTLA MIESIĘCZNA
  odświeżenie warstw referencyjnych (RCN, MPZP, plany ogólne, BDOT10k)
  -> rekalibracja modelu wyceny

PĘTLA UŻYTKOWNIKA (ciągła)
  przeglądanie, filtry, sortowanie, zapisywanie działek, notatki,
  feedback ("to trafienie" / "to pudło") -> uczenie rankingu
```

### 1.2. Funkcje, które musi mieć

| Obszar | Funkcja |
|---|---|
| **Zbieranie** | Codzienne skanowanie portali, wykrywanie nowych ofert i zmian ceny, historia cen każdej oferty |
| **Deduplikacja** | Ta sama działka na 4 portalach = jeden rekord z 4 źródłami i widocznym rozrzutem cen |
| **Wzbogacanie** | Numer działki ewidencyjnej, geometria, powierzchnia ewidencyjna, przeznaczenie, klasa gruntu, uzbrojenie, ryzyka, odległości |
| **Wycena** | Szacunkowa wartość rynkowa z przedziałem niepewności, oparta na transakcjach |
| **Scoring** | Ocena potencjału 0-100 z rozbiciem na czynniki i wyjaśnieniem |
| **Filtry** | Powierzchnia, cena, cena za m2, przeznaczenie, uzbrojenie, odległość od punktu, czas dojazdu, wykluczenie stref zalewowych, klasa bonitacyjna, obecność MPZP |
| **Sortowanie** | Po score, po deal score, po dacie dodania, po cenie za m2 znormalizowanej, po zmianie ceny |
| **Zapisywanie** | Ulubione per użytkownik, tagi, notatki, statusy (do sprawdzenia / dzwoniłem / odrzucone) |
| **Alerty** | Telegram natychmiastowy przy trafieniu w zapisany filtr, dzienny digest mailem |
| **Mapa** | Wszystkie oferty na mapie z warstwami: MPZP, strefy zalewowe, uzbrojenie, granice działek |

### 1.3. Czego świadomie nie robimy w wersji 1

- Nie przechowujemy danych kontaktowych sprzedających (powód prawny, sekcja 8)
- Nie hostujemy zdjęć, tylko linkujemy do oryginału
- Nie robimy własnej wyszukiwarki zastępującej portal, tylko warstwę analityczną z linkiem do źródła
- Nie robimy aplikacji mobilnej, PWA wystarczy

---

## 2. Źródła danych

### 2.1. Warstwa fundamentowa: dane publiczne (darmowe, bez ryzyka prawnego)

To jest najważniejsza część i tu leży cała przewaga projektu. Wszystkie poniższe zostały zweryfikowane na żywo w trakcie researchu.

| Źródło | Co daje | Endpoint | Status |
|---|---|---|---|
| **RCN (Rejestr Cen Nieruchomości)** | Ceny transakcyjne z aktów notarialnych, geometria, numer działki, przeznaczenie w MPZP, rodzaj rynku, data | `https://mapy.geoportal.gov.pl/wss/service/rcn` (WMS + WFS), eksport GeoParquet i GeoPackage | Zweryfikowane, 5 lokalizacji pomorskich zwróciło dane |
| **ULDK (GUGiK)** | Współrzędne na numer działki i geometrię WKT, oraz odwrotnie | `https://uldk.gugik.gov.pl/?request=GetParcelByXY&xy=...` | Zweryfikowane, ok. 0,8 s na zapytanie, bez klucza |
| **EGiB WFS** | Atrybuty działki, klasoużytki, powierzchnia ewidencyjna | `https://mapy.geoportal.gov.pl/wss/service/PZGIK/EGIB/WFS/UslugaZbiorcza` | Zweryfikowane, dane z 18.08.2026 |
| **KIUT (uzbrojenie)** | Warstwy: przewód elektroenergetyczny, wodociągowy, gazowy, kanalizacyjny | `https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaUzbrojeniaTerenu` | Zweryfikowane |
| **KIUG (klasy bonitacyjne)** | Klasoużytki, klasa gruntu rolnego | `https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaUzytkowGruntowych` | Zweryfikowane, ale najsłabsze pokrycie ze wszystkich usług |
| **Plany ogólne gmin** | Strefa planistyczna, **Obszar Uzupełnienia Zabudowy** | `https://mapy.geoportal.gov.pl/wss/ext/PlanyOgolneGmin` | Zweryfikowane, uruchomione 19.01.2026, pokrycie rośnie |
| **Rejestr Urbanistyczny** | Docelowe źródło MPZP i planów ogólnych, deklaruje WMS/WFS/CSW | `https://rejestr-urbanistyczny.gov.pl/published` | Serwis działa (uruchomiony 01.07.2026), **adresy API do ustalenia z zakładki Network w przeglądarce** |
| **KIMPZP** | Przeznaczenie w MPZP | `https://mapy.geoportal.gov.pl/wss/ext/KrajowaIntegracjaMiejscowychPlanowZagospodarowaniaPrzestrzennego` | Działa, ale to proxy do usług gminnych. Dla Gdańska zwróciło "brak serwisu dla wskazanego obszaru" |
| **Mapy zagrożenia powodziowego** | Strefy Q10%, Q1%, Q0,2% oraz **scenariusz morski hWZ** | `https://wody.isok.gov.pl/wss/INSPIRE/INSPIRE_NZ_HY_MZPMRP_WMS` | Zweryfikowane |
| **SOPO (osuwiska)** | Osuwiska, istotne dla klifów nadmorskich i Kaszub | `https://cbdgmapa.pgi.gov.pl/arcgis/services/geozagrozenia/sopo_obszary/MapServer/WMSServer` | Zweryfikowane |
| **NMT (wysokość)** | Wysokość n.p.m., podstawa do liczenia spadku | `https://services.gugik.gov.pl/nmt/?request=GetHByXY&x=...&y=...` | Zweryfikowane (Gdańsk 4,9 m, Kartuzy 215 m) |
| **BDOT10k** | Drogi z klasyfikacją, budynki, lasy, wody, linie energetyczne | pobranie per powiat z `opendata.geoportal.gov.pl` | Zweryfikowane |
| **GUS BDL API** | Demografia gminy, migracje, pozwolenia na budowę, ceny gruntów rolnych | `https://bdl.stat.gov.pl/api/v1/` | Zweryfikowane, pomorskie: grunty orne 66 920 zł/ha w 2025, +54% od 2020 |
| **GDOŚ (obszary chronione)** | Natura 2000, parki krajobrazowe, otuliny | `https://sdi.gdos.gov.pl/wfs` lub pobranie shapefile per województwo | Blokada Incapsula z IP datacenter, **pobieraj offline** |
| **OSM / Geofabrik** | POI, drogi, linia brzegowa, linie WN, lasy | `https://download.geofabrik.de/europe/poland/pomorskie-latest.osm.pbf` | Pobierz ekstrakt, licz lokalnie w PostGIS |
| **GTFS Gdańsk** | Częstotliwość kursów z przystanku | `https://ckan.multimediagdansk.pl/dataset/tristar` | Zweryfikowane |
| **Valhalla / OSRM** | Izochrony i czas dojazdu | postaw własną instancję na ekstrakcie Geofabrik | Publiczne instancje zweryfikowane, ale nie do produkcji |

**Pułapka, która zje Ci najwięcej czasu: kolejność osi.** Trzy usługi GUGiK, których będziesz używał obok siebie, mają trzy różne konwencje:

- ULDK: `xy=easting,northing`
- NMT: `x=northing&y=easting` (odwrotnie)
- WMS 1.3.0 dla EPSG:2180: `BBOX=northing,easting,...`

Przy odwrotnej kolejności usługi nie zgłaszają błędu w oczywisty sposób, tylko zwracają dane z zupełnie innego miejsca w Polsce. Owiń to w jedną funkcję pomocniczą na pierwszy dzień projektu. Dodatkowo MapServer w usługach GUGiK wymaga parametru `STYLES`, nawet pustego.

### 2.2. Warstwa ofertowa: portale

| Portal | Działki w pomorskim | Dostępność z serwera | Format danych | Priorytet |
|---|---|---|---|---|
| **Morizon** | 4 953 | Cloudflare, ale przepuszcza | SSR, `__NUXT_DATA__` + JSON-LD, **dokładne współrzędne (7 miejsc)**, POI z odległościami | **1** |
| **Nieruchomosci-online** | 343 w samym Gdańsku | Bez WAF, lekki (14,6 KB) | JSON-LD, **najbogatsze pola dla działek: MPZP, Kształt, Dojazd, Media, Forma własności** | **1** |
| Gratka | 4 953 (identyczne z Morizon) | Cloudflare, przepuszcza | Nuxt | Pomiń, duplikat |
| Domiporta | 3 249 | Bez WAF, ale blokuje UA "Scrapy" | JSON-LD, brak współrzędnych na listingu | 2 |
| **GruntGuru** | ok. 1 128 | Bez WAF | Next.js, **jedno żądanie zwraca komplet 8 571 punktów lat/lng dla całej Polski** | 2 |
| Adresowo | brak poziomu wojewódzkiego dla działek | Bez WAF | JSON-LD | 3 |
| **Otodom** | niepotwierdzone | **403 CloudFront z każdego IP datacenter** | XML feed dla agencji zawiera: typ działki (w tym siedliskowa), media, dojazd, ogrodzenie, sąsiedztwo, GeoMarker | Przez Apify |
| **OLX** | niepotwierdzone | **403 CloudFront** | Partner API zwraca tylko własne ogłoszenia użytkownika, bezużyteczne | Przez Apify |

**Gotowe aktory Apify (zweryfikowane w Store API):**

| Aktor | Cena | Kondycja |
|---|---|---|
| `trev0n/otodom-scraper` | 0,002-0,004 USD za rekord | 109 użytkowników, 963/988 udanych runów |
| `solidcode/olx-pl-scraper` | 0,003 USD + 0,00005 za start | 90/90 udanych |
| `trev0n/polish-real-estate-aggregator` | 0,00999 USD za rekord | 7 portali naraz, ma `clusterId` do dedupu cross-portal |

**Czego nie ma nigdzie w portalach:** numeru działki ewidencyjnej. Rozwiązanie: współrzędne z ogłoszenia trafiają do ULDK `GetParcelByXY`, dostajesz `idDzialki`, po nim robisz join z RCN. To jest kluczowa operacja całego systemu, spinająca warstwę ofertową z fundamentową.

**Portale specjalistyczne od działek praktycznie nie istnieją.** Sprawdzone: grunt24.pl przekierowuje na inną branżę, landsale.pl i dzialki.pl są martwe (DNS istnieje, połączenie resetowane), najlepszedzialki.pl ma ok. 12 ofert, nocnyagent.pl nie ma rekordu DNS. Jedyny sensowny to GruntGuru.

---

## 3. Architektura systemu

```
┌─────────────────────────────────────────────────────────────────┐
│  ŹRÓDŁA                                                          │
│  Portale (Morizon, N-O, Domiporta, GruntGuru)  │  Apify (Otodom, │
│                                                 │         OLX)    │
│  Dane publiczne (RCN, ULDK, EGiB, MPZP, ISOK, BDOT10k, GUS, OSM) │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│  INGEST                                                          │
│  Crawlee (Python) + curl-cffi + selectolax                       │
│  Strategia DIFF: skan listingów -> detal tylko dla zmian         │
│  Adapter per portal: fetch_listings() / parse_detail()           │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│  NORMALIZACJA + DEDUPLIKACJA                                     │
│  ULDK -> id działki  │  pHash zdjęć  │  geohash blocking         │
│  pg_trgm  │  Union-Find -> rekord kanoniczny + lista źródeł      │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│  WZBOGACANIE (spatial join w PostGIS)                            │
│  geometria │ przeznaczenie │ OUZ │ klasa gruntu │ uzbrojenie     │
│  spadek │ powódź │ osuwiska │ ochrona │ odległości │ izochrona   │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│  SILNIK OCENY  (sekcja 5, serce systemu)                         │
│  Warstwa A: wycena V̂ + σ̂   (uczona na RCN)                      │
│  Warstwa B: potencjał P     (MCDA ekspercki, 6 filarów)          │
│  Warstwa C: deal score D    (V̂ - cena) / σ̂                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│  APLIKACJA                                                       │
│  FastAPI  │  Next.js + shadcn/ui + TanStack Table + MapLibre     │
│  Ulubione, notatki, zapisane filtry, alerty Telegram + e-mail    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Stack technologiczny

### 4.1. Dlaczego nie no-code (mimo Twojej preferencji)

Sprawdziłem tę ścieżkę uczciwie, z realnymi cennikami. Odpada z czterech powodów:

| Problem | Szczegół |
|---|---|
| **Koszt** | Najlepszy realny wariant no-code (Octoparse + Baserow + Appsmith) to ok. 369 USD miesięcznie. Wariant Apify + Airtable + Softr to 715 USD. Wariant z pełnym odświeżaniem: 3 025 USD. Ścieżka z kodem: 86 USD |
| **Otodom i OLX** | Wszystkie narzędzia no-code hostowane są w chmurze, czyli wychodzą z datacenter, czyli dostają 403. Musisz kupić unblocker, a jak już kupujesz, to równie dobrze możesz mieć własny kod |
| **Sufit rekordów** | Airtable 50-125 tys., Baserow 50-250 tys., NocoDB 50-300 tys. Cała Polska to 80-120 tys. unikalnych działek plus historia cen. Dobijasz do sufitu w pierwszym roku |
| **Scoring jest niewykonalny** | Zapytanie typu "działki z przeznaczeniem MN, do 800 m od drogi publicznej, poza strefą zalewową, w izochronie 30 min od Gdańska, cena poniżej 80% mediany lokalnej" to jedno zapytanie PostGIS i zero zapytań w Airtable. Bez tego to jest Otodom z gorszym UI |

**Ale:** ścieżka z kodem nie oznacza, że piszesz go sam. Oznacza, że prowadzisz Claude Code po architekturze, którą ten dokument definiuje. Przy dobrze podzielonym repo (jeden portal = jeden moduł z tym samym interfejsem) naprawa po zmianie HTML na portalu to prompt na jeden plik, 10-20 minut. W Browse AI albo Octoparse to 2-4 godziny przeklikiwania robota od zera. **Ścieżka z kodem jest dziś także szybsza w budowie, nie tylko tańsza.**

### 4.2. Rekomendowany stack

```
BAZA
  PostgreSQL 17 + PostGIS + pg_trgm + pgvector
  Wariant A: Supabase Pro, 25 USD/mies. (bonus: Auth, pg_cron, REST)
  Wariant B: własny Postgres na VPS, 0 zł (backup pg_dump do B2)

SCRAPER
  Python 3.13 + Crawlee for Python 1.9
  ├─ curl-cffi (impersonate="chrome") + selectolax
  │     dla: Morizon, Nieruchomosci-online, Domiporta, GruntGuru
  │     proxy: niepotrzebne
  └─ Apify API: trev0n/otodom-scraper, solidcode/olx-pl-scraper
        plan Starter 29 USD + ok. 30-60 USD w rekordach

  Strategia DIFF, nie pełne odświeżanie.
  Skan listingu posortowanego po dacie -> hash listy ID ->
  pobranie detalu tylko dla nowych i zmienionych.
  Różnica w koszcie transferu: 14 GB vs 81 GB miesięcznie.

HARMONOGRAM
  APScheduler + tabela zadań w Postgresie
  (SELECT ... FOR UPDATE SKIP LOCKED)
  Koszt: 0. Przy 5 tys. zadań dziennie nie kupuj Inngest ani Trigger.dev.
  Dramatiq dopiero gdy zaboli.

BACKEND
  FastAPI (ten sam Python co scraper, jeden model Pydantic)
  NIE Supabase Edge Functions: limit 2 s CPU, 256 MB RAM, do scrapingu bezużyteczne

FRONTEND
  Next.js 15 + shadcn/ui + TanStack Table (server-side pagination)
  Mapa: MapLibre GL JS + kafle PMTiles (Protomaps), koszt 0
  Pierwszą wersję UI wygeneruj w v0 lub Lovable, potem eksport i Claude Code

ALERTY
  Telegram Bot API (natychmiastowe, 0 zł, przyciski inline)
  Resend Free (3 000 maili/mies., dzienny digest)
  Watchdog: alert gdy portal zwraca 0 nowych ofert przez 2 dni
  (to nie znaczy, że rynek stanął, tylko że Cię zablokowali)

HOSTING
  Hetzner CX33 (4 vCPU, 8 GB, 80 GB), 9,99 EUR/mies.
  + Coolify (darmowy, deploy z gita, SSL, backupy)
  Uwaga: po podwyżce z 15.06.2026 linie CCX i CPX podrożały o 140-170%.
  Linie CX i CAX pozostały tanie. Nie bierz CCX.
```

### 4.3. Deduplikacja: pipeline

Ta sama działka pojawia się na Otodom, OLX, Gratce i Morizonie, wystawiona przez tę samą agencję, często z inną ceną. Kolejność etapów jest od najtańszego do najdroższego.

```
0. Normalizacja
   cena -> integer PLN (Morizon używa \xa0 jako separatora)
   powierzchnia -> m2 (uwaga na ary i hektary)
   współrzędne -> jeśli brak, geokodowanie przez Nominatim

1. Twarde klucze (ok. 40% dopasowań, deterministyczne)
   ULDK GetParcelByXY -> idDzialki. Dwa ogłoszenia z tym samym ID = jedna działka
   Hash SHA-256 numeru telefonu (nie plaintext, powód w sekcji 8)

2. Blocking (redukcja par z O(n²) do O(n))
   geohash precyzji 7 (ok. 150 m) + bucket powierzchni ±3%
   Bez tego przy 100 tys. ofert masz 5 mld par. Z tym: kilkaset tysięcy

3. pHash zdjęć (najsilniejszy sygnał cross-portal)
   Agencje wrzucają identyczne pliki JPEG na wszystkie portale.
   Opisy przepisują, zdjęć nie.
   Hamming distance <= 8, przechowuj jako bit(64)

4. Fuzzy text
   pg_trgm similarity > 0,55 lub RapidFuzz token_set_ratio

5. Embeddingi (tylko jako tie-breaker, NIE zaczynaj od tego)
   pgvector + paraphrase-multilingual-MiniLM (lokalnie, CPU)
   Etapy 1-3 załatwiają 85% przypadków taniej i deterministycznie

6. Klastrowanie
   Union-Find na parach powyżej progu -> rekord kanoniczny + tabela źródeł
   Pokazuj użytkownikowi: "ta sama działka, Otodom 320 tys., OLX 299 tys."
   Rozrzut cen między portalami sam w sobie jest sygnałem
```

Trzymaj ręcznie oznakowany zbiór 200 par (100 duplikatów, 100 nie) i mierz precyzję po każdej zmianie progów. Bez tego stroisz na ślepo.

**Uzupełnienie z 25.08.2026: etap 3 ma tańszy wariant, którego ten dokument nie
przewidział.** Punkt 3 zakłada, że skoro agencje wrzucają te same pliki JPEG na
wszystkie portale, to trzeba je pobrać i porównać pHashem. Pomiar na własnych
danych pokazał, że w przypadku Morizona i Gratki nie trzeba: oba portale
serwują miniatury przez ten sam przekaźnik `img1.staticmorizon.com.pl/thumb/`,
w którym adres pliku źródłowego jest zapisany base64. Po rozkodowaniu obie
oferty wskazują **ten sam plik na tym samym serwerze**, więc mamy tożsamość, a
nie podobieństwo — i to bez pobierania obrazu oraz bez biblioteki do obrazów.

Klucz jest z tego powodu **twardy** (etap 1, pewność 1,0, omija blocking), a nie
składnikiem punktacji. Podstawa decyzji, na 3 298 kluczach z bazy: ani jednej
kolizji w obrębie jednego portalu (czyli obawa o „ten sam baner agencji na
każdym ogłoszeniu" się nie zmaterializowała) oraz 654 klucze wspólne dla dwóch
portali, z czego **654/654 z identyczną ceną co do grosza** i 650/654 także
z identyczną powierzchnią.

Skala zjawiska: ponad połowa ofert Gratki ma identyczne zdjęcie na Morizonie,
a udział ten rośnie w miarę uzupełniania detali Morizona. Pierwszy pomiar, na
323 z 1 195 ofert Gratki, dał 96,6% — i był błędny nie z powodu kodu, tylko
próbki: uzupełnianie szło po identyfikatorach, a najstarsze oferty Gratki to
dokładnie te, które były już wcześniej widziane na Morizonie. Udział policzony
na częściowo załadowanym zbiorze nie jest udziałem.

Reguła ogólniejsza, warta zapamiętania poza tym projektem: **zanim sięgniesz po
miarę podobieństwa, sprawdź, czy nie masz gdzieś tożsamości.** pHash zostaje
w planie dla portali z osobnymi CDN-ami (Otodom, Nieruchomości-online), gdzie
adres pliku faktycznie nic nie łączy.

---

## 5. System oceny potencjału

To jest sedno projektu i najdłuższa sekcja dokumentu.

### 5.1. Architektura trójwarstwowa

Najczęstszy błąd projektowy w takich systemach to wrzucenie wszystkiego do jednej sumy ważonej. Wycena i potencjał to dwie różne rzeczy o różnej naturze:

- **Wycena ma etykiety** (RCN zawiera realne ceny), więc może się uczyć
- **Potencjał nie ma etykiet** (nikt nie mierzy "potencjału"), więc musi być ekspercki

```
WARSTWA A: WYCENA               V̂ ± σ̂
  model uczony na transakcjach RCN
  odpowiada na pytanie: ile ta działka jest warta

WARSTWA B: POTENCJAŁ            P ∈ [0, 100]
  scoring wielokryterialny (MCDA), ekspercki
  odpowiada na pytanie: czy warto się nią zajmować

WARSTWA C: DEAL SCORE           D = (V̂ − cena_ofertowa) / σ̂
  pochodna obu
  odpowiada na pytanie: czy jest tania względem tego, co sobą reprezentuje
```

**Prezentacja dla użytkownika: macierz 2x2**, oś X to deal score, oś Y to potencjał. Prawy górny kwadrant (tania plus wysoki potencjał) to okazje. To znacznie lepszy UX niż jedna liczba i jest odporne na krytykę, bo użytkownik widzi oba wymiary.

---

### 5.2. Warstwa A: wycena

#### 5.2.1. Fundament: normalizacja efektu skali

**To jest najczęściej pomijany i najbardziej kosztowny błąd w naiwnych porównywarkach cen za m2.** Cena za metr kwadratowy systematycznie spada wraz z powierzchnią działki. Dowody:

| Badanie | Rynek | Wynik |
|---|---|---|
| Bitner (2008), Acta Sci. Pol. | Kraków, 2 422 transakcje z aktów notarialnych | **Wzrost powierzchni o 1 ar obniża cenę jednostkową o ok. 0,8%.** Model wykładniczy, współczynnik 1,38 × 10⁻⁴ m⁻² |
| Ritter i in. (2020), Land Use Policy | Saksonia-Anhalt, ponad 80 tys. transakcji | Relacja jest **niemonotoniczna**: ujemna dla bardzo małych i bardzo dużych, dodatnia dla średnich. "Nie da się ująć prostą formą funkcyjną" |
| Clauretie & Li (2019), JREFE | Nevada, aukcje BLM | Cena za akr najpierw rośnie, potem spada, maksimum ok. 14 akrów. Efekt plottage ok. 60 tys. USD za akr |
| Davis i in. (2019), FHFA | USA, 6,7 mln wycen | Wszystkie ceny skalowane do jednolitej działki 0,25 akra właśnie po to, by usunąć ten efekt |

**Reguła operacyjna:** nigdy nie porównuj surowej ceny za m2.

```
cena_m2_znormalizowana = cena_m2_obserwowana × (A_obs / A_ref)^(1 − β₁)

A_ref = 1000 m2   (dla działek budowlanych w PL, blisko mediany)
β₁    = elastyczność ceny całkowitej względem powierzchni z regresji ln(P) ~ ln(A)
        startowo 0,80-0,90 dla działek 500-3000 m2
```

Estymuj β₁ na własnych danych, osobno dla przedziałów powierzchni (poniżej 800 m2, 800-3000, powyżej 3000), a najlepiej splajnem naturalnym o 4-5 węzłach, żeby uwzględnić niemonotoniczność Rittera.

**Test walidacyjny, prosty i mocny:** po normalizacji korelacja `cena_m2_znormalizowana` z `ln(A)` w każdej gminie powinna być bliska zeru. Jeśli nie jest, β₁ jest źle dobrane.

#### 5.2.2. Problem rzadkich danych i jego rozwiązanie

W 1. połowie 2023 w całej Polsce zarejestrowano ok. 11,5 tys. aktów notarialnych dotyczących gruntów poza miastami i 3,8 tys. w miastach. Przy 2 477 gminach to **średnio ok. 6 transakcji gruntowych na gminę na półrocze**, licząc wszystko: rolne, budowlane, przemysłowe.

Wniosek: gmina to zła jednostka agregacji dla większości Polski. Mediana z 6 obserwacji jest bezużyteczna.

**Rozwiązanie: hierarchiczny shrinkage bayesowski (partial pooling).**

```
ln(P_ij) = μ + α_j + Xβ + ε_ij
α_j ~ Normal(0, τ²)          efekt gminy / obrębu j

α̂_j = λ_j · ȳ_j + (1 − λ_j) · ȳ_global
λ_j = n_j / (n_j + σ²/τ²)
```

Interpretacja: `σ²/τ²` to "liczba obserwacji równoważna wiedzy wstępnej". Przy σ²/τ² = 10 gmina z 10 transakcjami dostaje wagę 50% własnych danych, gmina z 2 transakcjami 17%, gmina ze 100 transakcjami 91%. **To jest automatyczny, samoregulujący się fallback.**

Zagnieżdżenie trzypoziomowe `(1 | województwo/powiat/gmina/obręb)` sprawia, że gmina bez danych pożycza od powiatu, powiat od województwa. **Model nigdy nie wywala się na braku danych, tylko rozszerza przedział niepewności.** Dokładnie to zachowanie, którego chcesz w produkcie.

Tania wersja bez Stana i brms, jeśli wolisz gradient boosting: **smoothed target encoding**, `enc(gmina) = (n_j·ȳ_j + m·ȳ_global) / (n_j + m)` z m rzędu 10-30. To dosłownie empiryczny Bayes w jednej linijce. Licz wewnątrz foldów walidacji, inaczej masz wyciek.

#### 5.2.3. Trzy modele, w tej kolejności

```
Model 1 (tydzień 1): mediana ceny/m2 znormalizowanej do 1000 m2,
        per (gmina × przeznaczenie), z shrinkage do powiatu i województwa
        To już jest użyteczne. Nie czekaj z uruchomieniem na model 3.

Model 2 (tydzień 3): SE-KNN, k najbliższych sąsiadów w przestrzeni łączonej
        geografia + cechy
        d'_ij = (1−λ)·||x_i − x_j||² + λ·||μ_i − μ_j||²
        Optimum z literatury (Franklin County, Ohio): λ = 0,7, K = 6
        λ=0,7 mówi wprost: geografia waży więcej niż cechy
        To jest sformalizowana metoda porównawcza, działa od kilkudziesięciu obserwacji
        i daje gotową listę porównywalnych do pokazania użytkownikowi

Model 3 (miesiąc 2): hierarchiczny ln(P) ~ ln(A) + cechy + (1|woj/pow/gmina)
        + lokalnie ważona predykcja konforemna dla przedziałów
```

**Nie zaczynaj od XGBoost.** Przy 500-5000 transakcjach model hierarchiczny wygra dokładnością, da przedziały wiarygodności za darmo, będzie wyjaśnialny i nie wywali się na nowej gminie. Gradient boosting dokładaj dopiero powyżej ok. 20 tys. obserwacji, i to jako komponent (booster na resztach), nie zamiast.

#### 5.2.4. Niepewność jest funkcją, nie defektem

Zamiast liczby "412 000 zł" pokazuj **"355-480 tys. zł, pewność 80%"**. Przy działce w gminie bez danych przedział zrobi się szeroki automatycznie, zamiast udawać precyzję.

Technika: lokalnie ważona predykcja konforemna (Hjort i in., 2023). Wagi `w_i = exp(−d²/η)` na non-conformity scores. Działa bez założeń rozkładowych i daje gwarancję pokrycia.

Skopiuj też wzorzec branżowy **FSD plus eskalacja**: gdy odchylenie prognozy przekracza próg, system mówi "nie wiem, wymaga oceny człowieka" zamiast zgadywać. Cenatorium robi to jako wskaźnik pewności A-F.

**Realistyczne cele dokładności dla gruntów w Polsce:** MdAPE 18-30%, odsetek predykcji w ±20% rzędu 50-65% dla działek budowlanych w miastach, gorzej na wsi. Dla kontekstu: Zillow ma medianę błędu 7,49% dla domów poza rynkiem, Redfin 7,26%, ale to domy, gdzie danych jest o dwa rzędy wielkości więcej. Badanie cen gruntów w Seulu (XGBoost, 24 cechy) dało 80% predykcji w ±10%, ale przy gęstych danych i z urzędową wyceną jako cechą.

**Nie obiecuj sobie 5%.**

#### 5.2.5. Metoda pozostałościowa jako druga ścieżka wyceny

Dla działek inwestycyjnych, gdzie brak porównywalnych, jest ścieżka niewymagająca transakcji gruntowych, tylko cen mieszkań i kosztów budowy (dane znacznie łatwiej dostępne). To polska metoda pozostałościowa, `WR = WK − (KR + ZI)`.

```
PUM_max     = A_działki × wskaźnik_intensywności_nadziemnej × η_PUM
GDV         = PUM_max × cena_m2_PUM_lokalna
RLV_brutto  = GDV × (1 − m_dev) − PUM_max × koszt_budowy_m2_PUM − K_stałe
RLV/m2      = RLV_brutto / A_działki
```

Parametry:
- **η_PUM** (przelicznik powierzchni całkowitej na użytkową mieszkalną): ok. **0,70** dla wielorodzinnej, 0,80 dla jednorodzinnej szeregowej
- **m_dev** (zysk inwestora): **15-20% GDV** dla projektów standardowych, 20-25% dla ryzykownych (bez MPZP, do odrolnienia). Kontekst: deweloperzy z GPW osiągnęli 17,1% marży netto w 2025
- **Sanity check:** PKO BP raportuje udział gruntu w koszcie na m2 PUM: Warszawa 23,8%, Łódź 14,7%. Jeśli Twój RLV implikuje udział powyżej 30% w Warszawie albo 20% w małym mieście, coś jest nie tak

Przeliczenie parametrów planistycznych na chłonność:

```
z intensywności:      PC_max = A × I_nadziemna
z pow. zabudowy:      PC_alt = A × U_zabudowy × liczba_kondygnacji
z pow. biol. czynnej: A_zabudowalna ≤ A × (1 − PBC_min)
z wysokości:          liczba_kondygnacji ≤ floor(H_max / 3,2 m)

PUM_efektywne = min(wszystkich ograniczeń) × η_PUM
```

3,2 m to typowa wysokość kondygnacji mieszkalnej (2,5-2,6 m w świetle plus strop). Dla usług przyjmij 3,8-4,2 m.

---

### 5.3. Warstwa B: scoring potencjału

#### 5.3.1. Konstrukcja ogólna

```
Score = Gate × Σ_k w_k · z_k

Gate = Π_g m_g        gdzie m_g ∈ [0, 1]
```

**Kluczowa zasada:** czynniki, których brak dyskwalifikuje inwestycję, nie mogą wchodzić do sumy ważonej. Suma ważona uśrednia, a te czynniki muszą zerować.

**Gate'y (mnożniki), propozycja startowa do kalibracji:**

| Warunek | Mnożnik |
|---|---|
| Brak dostępu do drogi publicznej i brak służebności | **×0,35** |
| Poza OUZ, brak MPZP, brak ważnej WZ (po uchwaleniu planu ogólnego) | **×0,40** |
| W strefie zalewowej Q1% (raz na 100 lat) | ×0,55 |
| Grunt leśny bez ścieżki odlesienia | ×0,30 |

#### 5.3.2. Sześć filarów

Grupowanie w filary rozwiązuje problem korelacji między cechami. Uzbrojenie, dostęp do drogi, bliskość centrum i MPZP są silnie skorelowane, więc naiwna suma ważona liczyłaby ten sam sygnał cztery razy. Przy filarach korelacja wewnątrz filaru jest nieszkodliwa, bo filar ma jedną wagę.

| Filar | Waga (inwestor detaliczny) | Waga (deweloper) | Uzasadnienie |
|---|---|---|---|
| **1. Planistyka i dopuszczalność zabudowy** | **35%** | **45%** | Po reformie 2026 to dominujący czynnik ryzyka w Polsce |
| **2. Lokalizacja i dostępność** | 22% | 18% | Trwały, niezmienialny nośnik wartości |
| **3. Infrastruktura** | 18% | 12% | W polskiej praktyce rzeczoznawczej uzbrojenie miało wagę 0,58 z 1,00 w przykładzie dla działki budowlanej |
| **4. Fizyka działki** | 10% | 8% | Ważne, ale częściowo naprawialne |
| **5. Ryzyka środowiskowe** | 10% | 7% | Rzadko aktywne, ale gdy aktywne to silnie |
| **6. Dynamika rynku gminy** | 5% | 5% | Sygnał, nie fundament |
| *(dla dewelopera dodatkowo)* Chłonność / PUM | - | 5% | |

Wagi filarów wyznacz metodą AHP z 2-3 ekspertami (rzeczoznawca, deweloper, pośrednik), z kontrolą spójności `CR < 0,10`. Przy 6 filarach to 15 porównań parami, robota na 20 minut. **Nie stosuj AHP do 30 pojedynczych cech**, bo to 435 porównań i gwarantowana niespójność.

#### 5.3.3. Filar 1: Planistyka (35%)

To jest największa pojedyncza dźwignia wartości na polskim rynku gruntów w 2026 roku, wynikająca wprost z konstrukcji przepisów.

Kontekst: nowelizacja z 30.04.2026 przesunęła termin uchwalenia planów ogólnych gmin na **31.08.2026**. Plan ogólny jest aktem prawa miejscowego (studium nim nie było). Kluczowy element to **Obszar Uzupełnienia Zabudowy**, element fakultatywny planu. Po jego uchwaleniu typowa nowa decyzja o warunkach zabudowy wymaga położenia terenu w OUZ. Działki poza OUZ, bez MPZP, praktycznie tracą ścieżkę do zabudowy.

**Stan planistyczny jako główny wskaźnik:**

| Stan | Opis | Mnożnik wartości (propozycja) |
|---|---|---|
| A | MPZP z przeznaczeniem budowlanym | 1,00 (baza) |
| B | Plan ogólny uchwalony, działka w OUZ, strefa SJ/SW/SU | 0,90-1,00 |
| C | Ważna decyzja WZ wydana przed reformą | 0,85-0,95 |
| D | Plan ogólny uchwalony, działka **poza OUZ**, brak MPZP | **0,30-0,50** |
| E | Plan ogólny nieuchwalony, brak MPZP, brak WZ | 0,50-0,75, bardzo szeroki przedział |

13 stref planistycznych planu ogólnego: SW (wielofunkcyjna z zabudową wielorodzinną), SJ (jednorodzinną), SZ (zagrodową), SU (usługowa), SH (handel wielkopowierzchniowy), SP (gospodarcza), SR (produkcja rolnicza), SI (infrastrukturalna), SN (zieleń i rekreacja), SC (cmentarze), SG (górnictwo), SO (otwarta), SK (komunikacyjna).

**Symulacja analizy urbanistycznej dla WZ.** To jest realna funkcjonalność, w całości do zbudowania z darmowych danych, i moim zdaniem jedna z najmocniejszych rzeczy w tym projekcie.

Nowe zasady wyznaczania obszaru analizowanego: odległość równa **trzykrotności szerokości frontu działki, minimum 50 m, maksimum 200 m** (wcześniej brak górnego limitu, co pozwalało naciągać obszar aż do znalezienia pasującej zabudowy). Nowa definicja frontu: część granicy przylegająca do drogi publicznej, wewnętrznej lub służebności z głównym wjazdem.

```
1. Wylicz szerokość frontu z geometrii ULDK (najdłuższy odcinek granicy przy drodze)
2. r = clamp(3 × front, 50, 200)
3. Bufor r wokół działki
4. Policz budynki mieszkalne w buforze (BDOT10k), ich powierzchnie i wysokości
5. Sprawdź, czy któryś jest na działce bezpośrednio przylegającej
6. Oszacuj wynikowe parametry: średni wskaźnik pow. zabudowy, średnia szerokość elewacji
   -> "prawdopodobieństwo uzyskania WZ"
```

Nie zastąpi to decyzji urzędu, ale odsiewa 80% przypadków beznadziejnych.

**Wskaźniki filaru 1:**

| Wskaźnik | Źródło danych |
|---|---|
| Stan planistyczny A-E | Rejestr Urbanistyczny, PlanyOgolneGmin, KIMPZP, geoportal gminny |
| Symbol przeznaczenia w MPZP | RCN (`dzi_przezn_wmpzp`), KIMPZP |
| Wskaźnik intensywności zabudowy, wysokość, PBC | dane APP z MPZP lub planu ogólnego |
| Prawdopodobieństwo WZ (symulacja) | ULDK + BDOT10k |
| Klasa bonitacyjna i koszt wyłączenia z produkcji rolnej | EGiB `KLASOUZYTKI_EGIB`, KIUG |
| Próg UKUR (0,3 ha, 1 ha) | powierzchnia + rodzaj użytku |

**Ważna nieciągłość:** ustawa o kształtowaniu ustroju rolnego tworzy twarde progi. Poniżej 0,3 ha bez prawa pierwokupu KOWR. Od 0,3 ha prawo pierwokupu. Do 1 ha nierolnik może nabyć, powyżej 1 ha potrzebna zgoda KOWR. Przy 0,3-1 ha dla nierolnika obowiązuje 5-letni zakaz zbycia. Działka 0,29 ha i 0,31 ha, poza tym identyczne, mają inny krąg nabywców i inną płynność. To musi być osobna zmienna z flagami progowymi, nie tylko `ln(A)`.

#### 5.3.4. Filar 2: Lokalizacja i dostępność (22%)

| Wskaźnik | Jak liczony | Źródło |
|---|---|---|
| Czas dojazdu do rdzenia aglomeracji | izochrona Valhalla na ekstrakcie OSM | własna instancja |
| Odległość do centrum gminy i miasta powiatowego | PostGIS `ST_Distance` | OSM/BDOT10k |
| Odległość do węzła S/A | j.w. | BDOT10k |
| Dostępność transportu publicznego | **liczba kursów w szczycie z najbliższego przystanku** (lepszy predyktor niż sama odległość) | GTFS |
| Odległość do linii brzegowej, jeziora, lasu | PostGIS | OSM `natural=coastline` |
| POI w buforze 2 km (szkoła, sklep, przedszkole) | Overpass lub lokalny ekstrakt | OSM |
| **Impuls infrastrukturalny** | `Δt_dojazdu × exp(−lata_do_oddania / 3)` | plany GDDKiA (S6, obwodnice) |

W pomorskim odległość do linii brzegowej i do Trójmiasta to prawdopodobnie dwa najsilniejsze wskaźniki w tym filarze.

#### 5.3.5. Filar 3: Infrastruktura (18%)

**Dostęp do drogi publicznej: kodowanie trójstanowe, nie binarne.**

```
2 = bezpośredni dostęp do drogi publicznej
1 = przez służebność wpisaną w KW lub drogę wewnętrzną z udziałem
0 = brak (działka ślepa), konieczność ustanowienia służebności drogi koniecznej w sądzie
```

Stan 0 to nie "minus 10%", to gate (×0,35), bo dostęp do drogi publicznej jest warunkiem koniecznym wydania decyzji o warunkach zabudowy.

**Uzbrojenie: zamień flagę na funkcję kosztową w złotówkach.** Zamiast "uzbrojona: tak/nie" licz realny koszt doprowadzenia mediów na podstawie odległości do sieci (KIUT plus BDOT10k):

| Media | do 50 m | 50-200 m | powyżej 200 m |
|---|---|---|---|
| Prąd napowietrzny | 1,5-3 tys. zł | 3-8 tys. zł | - |
| Prąd kablowy | 3-6 tys. zł | 6-15 tys. zł | - |
| Woda | 6-10 tys. zł | 10-25 tys. zł | 25-80+ tys. zł |
| Kanalizacja | 5-10 tys. zł | 10-25 tys. zł | 25-60+ tys. zł |
| Gaz | 3-8 tys. zł | 8-20 tys. zł | 20-50+ tys. zł |

Alternatywy: studnia głębinowa 12-30 tys., szambo 5-10 tys., oczyszczalnia przydomowa 8-25 tys. **Łącznie cztery media: od 20 tys. do ponad 150 tys. zł.**

```
koszt_uzbrojenia = Σ_media f_media(odległość_do_sieci)
korekta_wartości = − koszt_uzbrojenia × (1 + narzut_ryzyka)
```

To jest znacznie lepszy sygnał niż flaga i tłumaczy się użytkownikowi w złotówkach, a nie w punktach.

**Zastrzeżenie:** KIUT pokaże, czy przewód przebiega w pobliżu. Nie powie, czy operator ma dostępną moc przyłączeniową ani ile kosztuje przyłącze. Zawsze sprawdzaj warstwę `gesut` (które powiaty są włączone do usługi), bo brak przewodu na mapie może znaczyć "brak danych", a nie "brak sieci".

#### 5.3.6. Filar 4: Fizyka działki (10%)

Wszystko liczalne z geometrii ULDK w jednym zapytaniu PostGIS.

```
front_m                  = długość granicy stykającej się z drogą
smukłość                 = dł_max / szer_min              > 4 = problematyczna
zwartość                 = 4π·A / P²                      1 = koło, 0,785 = kwadrat, < 0,5 = zła
azymut osi długiej       = wpływa na nasłonecznienie
odchylenie_od_prostokąta = A / A_bounding_box
spadek terenu            = gradient z NMT w siatce 5-10 m wokół centroidu
```

Reguły kciuka: front poniżej 18 m przy zabudowie wolnostojącej to problem (przepisy o odległości 3 i 4 m od granicy). Smukłość powyżej 5 mocno ogranicza projektowanie. Zwartość poniżej 0,45 zwykle oznacza działkę po podziale rodzinnym i realny dyskont.

#### 5.3.7. Filar 5: Ryzyka środowiskowe (10%)

| Ryzyko | Źródło | Uwaga dla pomorskiego |
|---|---|---|
| Powódź rzeczna Q10%, Q1%, Q0,2% | Hydroportal ISOK | Q10% to sygnał znacznie poważniejszy niż Q0,2% |
| **Powódź morska (scenariusz hWZ)** | Hydroportal ISOK | **Krytyczne**: Żuławy, Mierzeja Wiślana, Wyspa Sobieszewska, Stogi, Przeróbka, Olszynka. Znaczna część Żuław leży poniżej poziomu morza |
| Osuwiska | SOPO / PGI | W pomorskim ryzyko niższe niż w Karpatach, ale realne na klifach (Jastrzębia Góra, Rozewie, Gdynia Orłowo, Chłapowo). Klify cofają się o 0,1-1,0 m rocznie |
| Obszary chronione | GDOŚ (pobierz shapefile offline) | Pomorskie ma bardzo wysoki udział: Słowiński PN, Bory Tucholskie, parki krajobrazowe, liczne Natura 2000. Otulina nie blokuje zabudowy automatycznie, ale wymusza ocenę oddziaływania |
| Pas techniczny i ochronny brzegu morskiego | Urzędy Morskie, poza otwartymi API | Ograniczenia ostrzejsze niż w GDOŚ |
| Linie wysokiego napięcia | BDOT10k klasa `SULN`, OSM `power=line` | Pas technologiczny: 400 kV ok. 70 m, 220 kV ok. 50 m, 110 kV ok. 40 m. W pasie zabudowa mieszkaniowa wykluczona lub silnie ograniczona |
| Hałas lotniczy | brak ogólnopolskiego API | Obszar Ograniczonego Użytkowania wokół lotniska Gdańsk-Rębiechowo: Matarnia, Klukowo, Osowa, Barniewice, Żukowo, Banino. Trzeba wyciągnąć ręcznie z uchwały sejmiku |

#### 5.3.8. Filar 6: Dynamika rynku gminy (5%)

```
dynamika_cen_3y    = (mediana_t / mediana_t-12kw)^(1/3) − 1        RCN
płynność           = liczba transakcji gruntowych / 1000 mieszk.   RCN + GUS
presja_zabudowy    = pozwolenia na budowę / 1000 mieszkańców       GUS BDL
saldo_migracji_5y  = suma sald / liczba ludności                   GUS BDL
konkurencja        = liczba aktywnych ofert podobnych w 5 km       własna baza
czas_ekspozycji    = mediana dni na rynku w segmencie              własna baza
```

#### 5.3.9. Braki danych: obowiązkowa dyscyplina

To rozstrzyga o tym, czy użytkownik zaufa systemowi.

1. **Nigdy nie traktuj braku jako zera.** Działka bez informacji o uzbrojeniu nie jest nieuzbrojona
2. **Renormalizuj wagi na dostępne cechy:** `S = Σ_dostępne w_k·z_k / Σ_dostępne w_k`
3. **Pokaż kompletność osobno i jawnie:** `coverage = Σ_dostępne w_k / Σ_wszystkie w_k`. Wyświetlaj "Score 74/100, kompletność danych 61%". To buduje zaufanie znacznie bardziej niż udawanie pełnej informacji
4. **Imputuj z hierarchii przestrzennej** (obręb, gmina, powiat), nie średnią globalną
5. **Flaguj imputację jako cechę.** `is_imputed_uzbrojenie` bywa samo w sobie predyktywne, bo brak danych koreluje z peryferyjnością
6. **Twarda zasada produktowa:** jeśli `coverage < 40%` albo brakuje którejkolwiek cechy gate'owej, nie pokazuj liczby, pokaż "Za mało danych" plus listę tego, czego brakuje. **Zły score jest gorszy niż brak score'u**

---

### 5.4. Warstwa C: deal score i wykrywanie okazji

```
D_i = (V̂_i − cena_ofertowa_i) / σ̂_i
```

**Dzielenie przez σ̂ jest kluczowe.** Bez tego system zaleje Cię "okazjami" z gmin, gdzie model nic nie wie i strzela losowo.

Progi: `D > 1,5` potencjalna okazja, `D > 2,5` alert, `D < −1,5` przeszacowana.

#### Krytyczna pułapka

**Duża dodatnia reszta najczęściej nie oznacza okazji, tylko brakującą cechę.** Działka "o 40% tańsza od modelu" to zwykle:

- brak dostępu do drogi, którego nie masz w danych
- służebność przesyłu przez środek
- współwłasność w częściach ułamkowych
- teren zalewowy
- nieuregulowany stan prawny lub roszczenia

Obowiązkowy filtr przed pokazaniem okazji:

```
if D > 2,5 and coverage < 0,75:
    pokaż jako "wymaga weryfikacji", NIE jako okazję
```

#### Rola Isolation Forest

Częsty błąd: używanie Isolation Forest jako detektora okazji. IF izoluje anomalie w przestrzeni **cech**, nie **ceny**, więc wykryje działki dziwne (bardzo duże, bardzo wąskie, w nietypowej lokalizacji), a nie tanie.

Dwa dobre zastosowania:
1. **Kontrola jakości danych.** IF wykrywa błędy w RCN: cena 1 zł, powierzchnia 5 mln m2, transakcja rodzinna. To realnie czyści dane treningowe
2. **Wykrywanie ekstrapolacji.** Wysoki anomaly score oznacza działkę niepodobną do niczego w zbiorze treningowym, czyli predykcję niewiarygodną

#### Pełny pipeline wykrywania okazji

```
1. Isolation Forest    odrzuć anomalie w danych i ekstrapolacje
2. Model wyceny        V̂ + σ̂ (konforemne, lokalnie ważone)
3. Deal score          D = (V̂ − P) / σ̂
4. Filtr coverage      odrzuć okazje na niepełnych danych
5. Gate'y ryzyka       odrzuć te, gdzie tanio ma oczywisty powód
6. Prezentacja         macierz 2x2: deal score × potencjał
```

---

### 5.5. Wyjaśnialność: dlaczego nie SHAP (albo nie tylko SHAP)

Badanie AVM dla Santiago de Chile wykazało, że interpretacje SHAP z LightGBM były bliższe naiwnemu OLS niż poprawnemu przestrzennie modelowi SAR. Autorzy wprost ostrzegają przed używaniem tego do wnioskowania przyczynowego.

Praktyczna konsekwencja: jeśli pokażesz "SHAP: bliskość szkoły plus 45 000 zł", a naprawdę to jest efekt dzielnicy skorelowany ze szkołami, to skłamiesz. **Zanim policzysz SHAP, wyczyść model z autokorelacji przestrzennej**, a komponent przestrzenny pokaż osobno jako "premia lokalizacyjna".

**Lepsza alternatywa dla polskiego użytkownika: rozkład w formacie metody korygowania ceny średniej.** Zamiast wartości Shapleya pokaż tabelę:

| Cecha | Ta działka | Rynek lokalny | Korekta |
|---|---|---|---|
| Powierzchnia | 1 800 m2 | 900 m2 | −38 zł/m2 |
| Uzbrojenie | prąd + woda | pełne | −34 zł/m2 |
| Dostęp | droga gminna asfalt | droga gminna | 0 |
| Przeznaczenie | MN w MPZP | MN | 0 |
| **Razem** | | **239 zł/m2** | **167 zł/m2** |

To wyjaśnienie polski inwestor i rzeczoznawca rozumieją natychmiast, jest zgodne z rozporządzeniem o wycenie nieruchomości i nie wymaga tłumaczenia, czym są wartości Shapleya.

Kontekst metodologiczny: rozporządzenie przewiduje trzy metody w podejściu porównawczym, z progami liczby porównywalnych: porównywanie parami od 3 nieruchomości, korygowanie ceny średniej od 15, analiza statystyczna dla zbioru reprezentatywnego. **To jest gotowa reguła routingu dla systemu:**

```
n >= 15  ->  korygowanie ceny średniej lub model statystyczny
n = 3-14 ->  porównywanie parami
n < 3    ->  model regionalny + shrinkage + wyraźny komunikat o niepewności
```

Drobne ulepszenie nad standardem branżowym: w metodzie korygowania ceny średniej wzór używa `3σ` jako podstawienia za półrozstęp. Użyj `3 × 1,4826 × MAD` zamiast `3σ`, żeby uodpornić na wartości odstające.

---

### 5.6. Kalibracja i walidacja

Nie masz etykiety "dobra działka". Masz substytuty:

**Proxy rynkowe (najlepsze):**
- **Sprzedaż jako etykieta:** zmatchuj oferty do transakcji RCN po numerze działki i oknie czasowym (oferta znika, transakcja pojawia się w ciągu 0-6 miesięcy). Etykieta: `y = 1[dni_na_rynku < mediana]` albo `y = cena_transakcyjna / cena_ofertowa`
- **Premia cenowa:** `y = reszta z modelu wyceny`. Jeśli score potencjału jest sensowny, powinien dodatnio korelować z resztą, bo rynek płaci za potencjał, którego model wyceny nie widzi. **To jednocześnie test scoringu i mechanizm wykrywania okazji**

**Kalibracja spreadu oferta-transakcja.** Dane NBP dla mieszkań (2 kw. 2025): Warszawa ok. 11,0%, Poznań 11,7%, Gdańsk 9,5%, Kraków 9,4%, Wrocław 7,5%. **Dla gruntów spread jest prawdopodobnie większy**, bo grunty są mniej płynne, sprzedający często nie ma presji czasu (grunt odziedziczony), a asymetria informacji o statusie planistycznym jest większa. Robocze założenie: 12-20% dla budowlanych, 20-35% dla rolnych i "z potencjałem". **Zweryfikuj natychmiast po zmatchowaniu ofert z RCN.**

Model kalibracyjny: `ln(P_trans) = α + β·ln(P_ofert) + γ·DOM + δ·segment + ε`, gdzie DOM to dni na rynku. Daje haircut zależny od czasu ekspozycji, znacznie lepszy niż stała.

**Walidacja bez etykiet:**
- **Analiza wrażliwości wag:** perturbuj wagi o ±30%, sprawdź stabilność top-100. Jeśli ranking się rozpada, scoring jest niestabilny
- **Test zgodności z ekspertami:** daj 3-5 osobom 50 działek do ręcznej oceny, licz korelację Spearmana. Cel `ρ > 0,6`. Poniżej 0,4 scoring nie odzwierciedla wiedzy domenowej
- **Test dyskryminacji:** rozkład score'ów powinien być zbliżony do jednostajnego. Jeśli 80% działek dostaje 60-70 punktów, scoring nic nie rozróżnia

**Sekwencja czasowa:**
```
miesiąc 0     MCDA ekspercki, wagi z AHP
miesiąc 3-6   walidacja przez proxy (dni na rynku, premia cenowa)
miesiąc 6     rekalibracja wag przez regresję na proxy
miesiąc 12+   learning to rank na feedbacku użytkowników
              (LambdaMART, uwaga na position bias, potrzebna korekta IPS)
```

**Dlaczego nie TOPSIS do głównego rankingu:** TOPSIS jest wrażliwy na skład zbioru alternatyw (rank reversal), więc score działki zmienia się, gdy do bazy dojdą nowe oferty. To fatalne, gdy użytkownik zapisuje działkę i wraca do niej za tydzień. Ważona suma z absolutnymi punktami odniesienia jest stabilna. TOPSIS jest natomiast dobry do rankingu **krótkiej, zamkniętej listy**: "porównaj te 5 działek, które zapisałem".

---

### 5.7. Podsumowanie: co odróżnia ten scoring od naiwnego

| Naiwne podejście | To, co proponuję |
|---|---|
| Surowa cena za m2 vs mediana gminy | Cena znormalizowana do 1000 m2 vs shrinkowana mediana hierarchiczna, z widoczną liczbą obserwacji |
| Mediana gminy, nawet gdy n=3 | Automatyczny shrinkage do powiatu i województwa, przedział rośnie zamiast liczby udawać precyzję |
| Jedna suma ważona wszystkiego | Trzy warstwy: wycena uczona, potencjał ekspercki, deal score jako pochodna |
| Flagi "uzbrojona: tak/nie" | Funkcja kosztowa w złotówkach na podstawie odległości do sieci |
| "MPZP: tak/nie" | Pięciostanowy status planistyczny z OUZ jako gate, plus symulacja analizy urbanistycznej dla WZ |
| Brak danych = 0 punktów | Renormalizacja wag plus jawny wskaźnik kompletności, blokada score'u poniżej 40% |
| Suma ważona wszystkich czynników | Gate'y jako mnożniki zerujące dla czynników dyskwalifikujących |
| Ceny ofertowe traktowane jak transakcyjne | Kalibrowany spread zależny od czasu ekspozycji |
| Jedna liczba "score" | Macierz 2x2 plus tabela rozkładu na czynniki w formacie zrozumiałym dla rzeczoznawcy |

---

## 6. Model danych (szkic)

```sql
-- Rekord kanoniczny działki
parcels(
  id, uldk_id, geom (PostGIS), area_ewid_m2, teryt_gmina, teryt_obreb,
  klasouzytek, klasa_bonitacyjna, sposob_uzytkowania,
  front_m, smuklosc, zwartosc, spadek_proc, wysokosc_npm,
  enriched_at
)

-- Oferty (wiele na jedną działkę)
listings(
  id, parcel_id, portal, portal_offer_id, url, title,
  price_pln, area_m2, price_per_m2, price_per_m2_norm,
  first_seen_at, last_seen_at, is_active, raw_jsonb
)

price_history(listing_id, price_pln, observed_at)

-- Warstwy referencyjne (spatial join)
mpzp_zones(geom, symbol, intensywnosc, wysokosc_max, pbc_min, gmina)
plan_ogolny(geom, strefa, is_ouz)
flood_zones(geom, scenariusz)          -- q10, q1, q02, hWZ
protected_areas(geom, typ, nazwa)
utilities(geom, rodzaj)                -- z KIUT
rcn_transactions(geom, id_dzialki, cena, data, pow, przezn, rodzaj_rynku)

-- Oceny
valuations(parcel_id, model_version, v_hat, sigma_hat, ci_low, ci_high,
           comparables_jsonb, computed_at)
scores(parcel_id, score_total, pillar_scores_jsonb, gates_jsonb,
       coverage, deal_score, computed_at)

-- Użytkownicy
users(id, email)
saved_parcels(user_id, parcel_id, tags[], note, status, created_at)
saved_filters(user_id, name, filter_jsonb, alert_channel, alert_enabled)
feedback(user_id, parcel_id, verdict, created_at)   -- do learning to rank
```

---

## 7. Funkcje aplikacji

### 7.1. Widok listy

Kolumny: miniatura (link, nie kopia), lokalizacja, powierzchnia, cena, cena za m2, **cena za m2 znormalizowana**, percentyl w rynku lokalnym z widoczną liczbą obserwacji, score, deal score, kompletność danych, źródła (ikony portali), data dodania.

Sortowanie po każdej kolumnie, domyślnie po `score × deal_score`.

### 7.2. Filtry

Podstawowe: cena, powierzchnia, cena za m2, przeznaczenie, województwo/powiat/gmina.
Zaawansowane: **czas dojazdu z zadanego punktu** (izochrona), obecność MPZP, status planistyczny A-E, klasa bonitacyjna, media (z progiem kosztu doprowadzenia), min. szerokość frontu, max. spadek terenu, wykluczenie stref zalewowych, wykluczenie obszarów chronionych, próg UKUR.

Zapisane filtry z alertem: każdy zapisany filtr może mieć włączone powiadomienie Telegram przy nowym trafieniu.

### 7.3. Karta działki

- Mapa z granicami działki (ULDK) i warstwami przełączanymi
- Wycena z przedziałem i listą porównywalnych transakcji z RCN
- Rozkład score na filary z tabelą korekt
- Lista czerwonych flag
- Historia ceny oferty
- Wszystkie źródła, jeśli oferta jest zduplikowana, z rozrzutem cen
- Notatki, tagi, status, przypisanie do użytkownika

### 7.4. Alerty

- Telegram: natychmiastowy przy trafieniu w zapisany filtr, z przyciskami inline (Zapisz, Ukryj, Otwórz)
- E-mail: dzienny digest z podsumowaniem
- Watchdog systemowy: alert do administratora, gdy portal przestaje zwracać dane

---

## 8. Prawo i ryzyko

**To nie jest porada prawna.** Poniżej zestawienie ustaleń z researchu prawnego, do zweryfikowania z prawnikiem przed jakimkolwiek użyciem komercyjnym.

### 8.1. Gdzie naprawdę leży ryzyko

Wbrew intuicji, największym ryzykiem nie jest prawo autorskie do pojedynczego ogłoszenia.

| Ryzyko | Poziom | Dlaczego |
|---|---|---|
| Prawo sui generis do baz danych | **Wysokie** | Portale niemal na pewno je mają, a ciągły scraping kumuluje się w "istotną część" |
| RODO (dane kontaktowe sprzedających) | **Wysokie** | Obowiązek informacyjny z art. 14 jest realny, a wyjątek "niewspółmiernego wysiłku" wąski (sprawa Bisnode) |
| Naruszenie regulaminu | Średnie, niepewne | Zależy, czy w ogóle doszło do zawarcia umowy z osobą bez konta (TSUE Ryanair v PR Aviation) |
| Ustawa o zwalczaniu nieuczciwej konkurencji | Średnie | Tylko gdy jesteś przedsiębiorcą budującym produkt konkurencyjny |
| Prawo autorskie do zdjęć | Średnie | Zdjęcia to zwykle utwory, ich kopiowanie to osobne naruszenie |
| Prawo autorskie do tekstu ogłoszenia | Niskie | Typowy opis nie ma cechy indywidualnej twórczości |
| **Dzwonienie do ogłoszeniodawców** | **Bardzo wysokie** | Art. 398 Prawa komunikacji elektronicznej, kary do 3% przychodu. Samodzielny delikt, często pomijany |

Kluczowe orzecznictwo: **C-202/12 Innoweb v Wegener** (meta-wyszukiwarka replikująca formularz portalu narusza prawo sui generis) oraz **C-762/19 CV-Online v Melons** (test wyważenia: czy agregator pozbawia portal możliwości amortyzacji inwestycji).

### 8.2. Decyzje projektowe obniżające ryzyko

Wbudowane w architekturę od początku:

1. **Nie zbieramy danych kontaktowych.** Ani imion, ani telefonów, ani e-maili. Telefon tylko jako SHA-256 do deduplikacji, nigdy w postaci jawnej. **Ta jedna decyzja usuwa większość ryzyka RODO**
2. **Nie hostujemy zdjęć**, tylko linkujemy do oryginału. Miniatury pobieramy wyłącznie do policzenia pHash i nie przechowujemy plików
3. **Nie przechowujemy pełnych opisów.** Tylko metadane liczbowe plus link. Nie parafrazujemy też opisów, bo parafraza może być opracowaniem utworu, co jest gorsze niż cytat
4. **Linkujemy do źródła i kierujemy ruch do portalu.** To centralny argument obronny z CV-Online
5. **Nie replikujemy wyszukiwarki portalu.** Dodajemy warstwę, której portale nie mają: wycenę, scoring, dane publiczne. Wartość dodana jest podstawą argumentacji z wyważenia interesów
6. **Respektujemy robots.txt i limitujemy tempo.** Wolniej niż człowiek przeglądający serwis. Nieruchomosci-online ustawia Crawl-delay 1 s, Morizon nie ustawia, więc przyjmij konserwatywnie 2-5 s
7. **Uczciwy User-Agent z kontaktem.** Podszywanie się pod przeglądarkę jest okolicznością obciążającą
8. **Nie zakładamy kont na portalach.** Założenie konta to jednoznaczne zawarcie umowy i akceptacja regulaminu
9. **Narzędzie prywatne, bez publicznego udostępniania i redystrybucji treści**

### 8.3. Punkt do przemyślenia: Otodom i OLX

Blokada CloudFront jest zabezpieczeniem technicznym. Obchodzenie jej rotacją proxy rezydencjalnych to **inna kategoria ryzyka** niż zwykły scraping niezabezpieczonego serwisu, bo niszczy przesłankę "dostępu zgodnie z prawem" wymaganą przez wyjątek dla eksploracji tekstów i danych.

Zakup danych przez pośrednika (aktor Apify) przenosi część operacji na podmiot trzeci, ale **nie zdejmuje z Ciebie odpowiedzialności za to, co robisz z danymi**. To jest miejsce, gdzie warto porozmawiać z prawnikiem, jeśli projekt ma wyjść poza użytek prywatny.

Alternatywa najbezpieczniejsza: uruchomić wersję 1 bez Otodomu i OLX. Morizon (4 953 działki w pomorskim), Nieruchomosci-online, Domiporta i GruntGuru dają solidną bazę do sprawdzenia, czy cały koncept działa.

---

## 9. Roadmapa

| Faza | Czas | Zakres | Koszt/mies. |
|---|---|---|---|
| **0. Fundament danych** | tydzień 1-2 | Pobranie RCN dla pomorskiego (GeoParquet), ULDK, ekstrakt OSM, BDOT10k. PostGIS lokalnie. **Zbadaj Rejestr Urbanistyczny przez zakładkę Network w przeglądarce i ustal adresy WFS.** Cel: mieć bazę transakcyjną i geometrie | 0 zł |
| **1. Pierwsza wycena** | tydzień 3-4 | Model 1 (mediana znormalizowana z shrinkage) i Model 2 (SE-KNN). Walidacja na 100 losowych działkach. Cel: sprawdzić, czy wyceny mają sens, zanim zbudujesz cokolwiek innego | 0 zł |
| **2. Scraper** | tydzień 5-6 | Morizon plus Nieruchomosci-online, curl-cffi plus selectolax, tylko pomorskie. Harmonogram. Eksport do CSV. Bez frontendu | 0 zł |
| **3. Wzbogacanie i scoring** | tydzień 7-9 | Pipeline ULDK, MPZP, plan ogólny, KIUT, ISOK, izochrony. MCDA z 6 filarami, wagi z AHP. Alerty Telegram | 0 zł |
| **4. Aplikacja** | tydzień 10-12 | Next.js, MapLibre, filtry, sortowanie, ulubione, notatki. Wszystko na localhost | 0 zł |
| **5. Otodom i OLX** | tydzień 13 | Apify Free na start, deduplikacja etapy 1-3. Cel: sprawdzić realny odsetek duplikatów (spodziewam się 30-45%) | 0 zł, potem ok. 200 zł przy większym wolumenie |
| **6. Kalibracja** | tydzień 14-16 | Kalibracja β₁ na własnych danych, kalibracja spreadu oferta-transakcja, analiza wrażliwości wag, test zgodności z ekspertami | bez zmian |
| **6b. Wyprowadzka na serwer** | gdy zaboli brak 24/7 | `docker compose up` na VPS, zmiana jednej zmiennej środowiskowej, dostęp z telefonu i dla pozostałych osób | ok. 45 zł |
| **7. Cała Polska** | opcjonalnie | Skalowanie na CX43, przejście na Dramatiq | ok. 900 zł |

**Zasada dla vibe codingu przy tym projekcie:** jeden portal to jeden moduł z tym samym interfejsem (`fetch_listings() -> list[RawListing]`, `parse_detail(html) -> Listing`). Wtedy zmiana HTML na jednym portalu to prompt na jeden plik, a nie refaktor całości. Napisz też testy na zapisanych snapshotach HTML, wtedy AI naprawia selektory samodzielnie i weryfikuje, że nic nie zepsuło.

**Nie odwracaj kolejności faz 0-2.** Kuszące jest zacząć od scrapera, bo to najbardziej widoczna część. Ale scraper bez modelu wyceny daje Ci listę ofert, czyli to samo, co Otodom. Model wyceny bez scrapera daje Ci już realną wartość: możesz sprawdzić dowolną działkę, którą znajdziesz ręcznie.

---

## 10. Koszty

### Wariant startowy: lokalnie, 0 zł

Wszystko na Twoim komputerze. Żaden element stacka nie ma opłat licencyjnych, wszystkie dane publiczne są bezpłatne, bot Telegram jest darmowy. Płacisz dopiero za pracę 24/7 bez Twojego udziału i za dostęp do Otodomu. Szczegóły i lista braków w sekcji 13.

Darmowe furtki, gdyby zabrakło: Oracle Cloud Always Free (od lipca 2026 obcięty do 2 rdzeni i 12 GB, nadal wystarczy) jako serwer, Apify Free (5 USD kredytu miesięcznie, ok. 1 500 rekordów) na Otodom, Supabase Free (500 MB, usypia po tygodniu bezczynności), Vercel Hobby, Resend 3 000 maili miesięcznie.

### Wariant rekomendowany, pomorskie (faza 5-6)

| Pozycja | USD/mies. | PLN/mies. |
|---|---|---|
| Hetzner CX33 (4 vCPU, 8 GB) | 11 | 45 |
| Supabase Pro (opcjonalnie, można na własnym Postgresie) | 25 | 100 |
| Apify Starter plus rekordy (Otodom, OLX) | 50 | 200 |
| Vercel Hobby (frontend) | 0 | 0 |
| Telegram, Resend Free, PMTiles, dane publiczne | 0 | 0 |
| Backup S3/B2 | 1 | 4 |
| **Razem** | **ok. 87** | **ok. 350** |

### Dla porównania: ścieżka no-code

| Wariant | USD/mies. |
|---|---|
| Octoparse + Baserow + Appsmith | ok. 369 |
| Bright Data + NocoDB + Softr | ok. 480 |
| Apify (odświeżanie różnicowe) + Airtable + Retool | ok. 715 |
| Apify (pełne odświeżanie) + Airtable + Softr | ok. 3 025 |

Każdy z nich bez PostGIS, bez deduplikacji cross-portal, bez scoringu geoprzestrzennego, z sufitem rekordów.

### Skalowanie na całą Polskę

Hetzner CX43 (18,49 EUR), Apify ok. 100 USD, proxy 25 GB ok. 65 USD, Vercel Pro 20 USD. Razem ok. 230 USD, czyli ok. 900 zł miesięcznie.

---

## 11. Otwarte pytania i rzeczy do zweryfikowania

Uczciwie: to są rzeczy, których research nie domknął.

**Do sprawdzenia przed startem (każde zajmuje minuty):**

1. **Adresy WFS Rejestru Urbanistycznego.** Otwórz `https://rejestr-urbanistyczny.gov.pl/published` z zakładką Network i odczytaj rzeczywiste wywołania XHR. To aplikacja Angular, adresów nie ma w publicznej dokumentacji. Ta jedna informacja zdecyduje o architekturze całego modułu planistycznego
2. **Ile gmin faktycznie uchwaliło plany ogólne** na dziś. Źródła są sprzeczne, a to fundament wskaźnika ryzyka planistycznego
3. **Czy decyzje WZ mają rzeczywiście 5-letni termin ważności** po reformie. Widziałem wzmianki, nie potwierdziłem w tekście ustawy
4. **Stawki opłat za wyłączenie gruntów z produkcji rolnej 2026.** Sprawdź w ustawie o ochronie gruntów rolnych i leśnych, nie w kalkulatorach komercyjnych
5. **Próg UKUR dla nierolnika.** Jeden blog podaje 5 ha, art. 2a ustawy i KOWR wskazują 1 ha. Przyjmuję 1 ha, ale sprawdź w tekście ustawy przed zakodowaniem

**Decyzje produktowe do podjęcia:**

6. **Czy Otodom i OLX w ogóle wchodzą do wersji 1?** Argument za pominięciem: profil ryzyka prawnego (blokada techniczna), dodatkowe 200 zł miesięcznie, i to, że Morizon plus Nieruchomosci-online plus GruntGuru dają ok. 6 tys. działek w pomorskim, czyli dość, by zweryfikować cały koncept
7. **Profil inwestora.** Wagi filarów różnią się mocno między "szukam działki pod własny dom" a "szukam gruntu inwestycyjnego pod podział lub zabudowę wielorodzinną". Sugeruję dwa przełączalne profile od początku, bo to tanie na etapie projektowania i drogie do dorobienia później
8. **Czy chcesz też grunty rolne i leśne**, czy tylko budowlane i inwestycyjne. To wpływa na model danych i na to, czy trzeba obsłużyć logikę odrolnienia
9. **Kto jeszcze będzie z tego korzystał.** Jeśli osoby z branży (pośrednik, rzeczoznawca), warto ich wciągnąć do wyznaczania wag AHP i do testu zgodności eksperckiej

---

## 12. Źródła

### Dane publiczne
- Rejestr Cen Nieruchomości, usługa GUGiK: https://mapy.geoportal.gov.pl/wss/service/rcn
- RCN w geoportalu, komunikat GUGiK: https://www.gov.pl/web/gugik/w-serwisie-wwwgeoportalgovpl-sprawdzisz-dane-z-rejestru-cen-nieruchomosci
- RCN bezpłatny od lutego 2026: https://www.rp.pl/nieruchomosci/art43810951-ceny-transakcyjne-nieruchomosci-juz-jawne-rcn-otwarty-dla-wszystkich
- Repozytorium RCN per powiat: https://rcn.geoforum.pl/
- ULDK, opis usługi: https://uldk.gugik.gov.pl/opis.html
- Katalog usług Krajowej Integracji GUGiK: https://integracja.gugik.gov.pl/
- EGiB WFS: https://mapy.geoportal.gov.pl/wss/service/PZGIK/EGIB/WFS/UslugaZbiorcza
- Plany ogólne gmin, WMS: https://mapy.geoportal.gov.pl/wss/ext/PlanyOgolneGmin
- Rejestr Urbanistyczny: https://rejestr-urbanistyczny.gov.pl/published
- KIMPZP: https://mapy.geoportal.gov.pl/wss/ext/KrajowaIntegracjaMiejscowychPlanowZagospodarowaniaPrzestrzennego
- Hydroportal ISOK, mapy zagrożenia powodziowego: https://wody.isok.gov.pl/hydroportal.html
- SOPO, osuwiska: https://mapa.osuwiska.pgi.gov.pl/
- NMT, usługa punktowa: https://services.gugik.gov.pl/nmt/
- Ortofotomapa WMTS: https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMTS/StandardResolution
- GUS BDL API: https://bdl.stat.gov.pl/api/v1/
- dane.gov.pl API: https://api.dane.gov.pl/1.4/ (wymaga nagłówka `Accept: application/vnd.api+json`)
- GDOŚ, dostęp do danych geoprzestrzennych: https://www.gov.pl/web/gdos/dostep-do-danych-geoprzestrzennych
- Geofabrik, ekstrakt pomorskiego: https://download.geofabrik.de/europe/poland/pomorskie-latest.osm.pbf
- GTFS Gdańsk (CKAN): https://ckan.multimediagdansk.pl/dataset/tristar

### Metodologia wyceny
- Bitner A. (2008), Zależność cena a pole powierzchni dla nieruchomości gruntowych, Acta Sci. Pol. Administratio Locorum 7(1): https://bazhum.muzhp.pl/media/texts/acta-scientiarum-polonorum-administratio-locorum/2008-tom-7-numer-1/acta_scientiarum_polonorum_administratio_locorum-r2008-t7-n1-s41-53.pdf
- Ritter M. i in. (2020), Revisiting the relationship between land price and parcel size, Land Use Policy 97: https://ideas.repec.org/p/zbw/forlwp/082019.html
- Clauretie T.M., Li H. (2019), Land Values: Size Matters, JREFE: https://link.springer.com/article/10.1007/s11146-017-9628-x
- Davis M.A. i in. (2019), The price of residential land, FHFA WP19-01: https://www.fhfa.gov/sites/default/files/documents/wp1901-1028.pdf
- Chen M., Lee C., Chun Y. (2026), Spatially Explicit K-Nearest Neighbors for House Price Predictions, ISPRS IJGI 15(1):46: https://www.mdpi.com/2220-9964/15/1/46
- Hjort A. i in. (2023), Uncertainty quantification in AVMs with locally weighted conformal prediction: https://arxiv.org/html/2312.06531v1
- Machine-Learning-Based Prediction of Land Prices in Seoul, Sustainability 2021, 13(23):13088: https://www.mdpi.com/2071-1050/13/23/13088
- Comparing AVMs, Santiago Metropolitan Region, PLOS ONE 2025: https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0318701
- AGH, Praktyczna ilustracja metod wyceny w podejściu porównawczym (wzory MPP i KCŚ): https://home.agh.edu.pl/~jasiolek/files/Praktyczna-ilustracja-metod-wyceny-w-podej-ciu-porownawczym.pdf
- Rozporządzenie w sprawie wyceny nieruchomości, par. 8: https://lexlege.pl/wycena-nieruch/paragraf-8/
- PFSRM, nota interpretacyjna, metoda pozostałościowa: https://wycena.net.pl/standardy/NI-Zastosowanie.metody.pozostalosciowej.pdf
- OECD/JRC (2008), Handbook on Constructing Composite Indicators: https://www.oecd.org/content/dam/oecd/en/publications/reports/2008/08/handbook-on-constructing-composite-indicators-methodology-and-user-guide_g1gh9301/9789264043466-en.pdf
- Diakoulaki i in., metoda CRITIC: https://reformship.github.io/pages/1capacity/1model/11evaluation/Determining%20objective%20weights%20in%20multiple%20criteria%20problems%20The%20CRITIC%20method.pdf
- Gelman & Pardoe, Bayesian Measures of Explained Variance and Pooling: https://sites.stat.columbia.edu/gelman/research/published/rsquared.pdf
- Zillow, Building the Neural Zestimate: https://www.zillow.com/news/building-the-neural-zestimate/
- Redfin Estimate, dokładność: https://www.redfin.com/redfin-estimate
- Cenatorium AVM: https://cenatorium.pl/produkty/wyceny/wycena-automatyczna-avm-cenatorium/

### Kontekst rynkowy i prawny
- Reforma planowania przestrzennego, MRiT: https://www.gov.pl/web/rozwoj-technologia/reforma-planowania-przestrzennego-2
- Plan ogólny gminy, termin 31.08.2026: https://blog.ongeo.pl/plan-ogolny-gminy-sejm-uchwalil-termin-sierpien-2026
- 13 stref planistycznych i OUZ: https://dzialkopedia.pl/poradnik/plan-ogolny-gminy
- Nowe zasady wyznaczania obszaru analizowanego dla WZ: https://jarzpartner.pl/en/nowe-zasady-wyznaczania-obszaru-analizowanego/
- UKUR, art. 2a: https://przepisy.gofin.pl/przepisy,6,29,158,976,425879,20240321,art-2a-ustawa-z-dnia-11042003-r-o-ksztaltowaniu-ustroju.html
- KOWR, FAQ o zgodach na nabycie: https://www.kowr.gov.pl/ukur/zgody-na-nabycie-nieruchomosci-rolnych/czesto-zadawane-pytania
- Ceny transakcyjne działek budowlanych, 1 kw. 2026: https://www.bankier.pl/wiadomosc/Ceny-transakcyjne-dzialek-budowlanych-I-kw-2026-Raport-9149669.html
- PKO BP, Puls Nieruchomości, ziemia w cenie: https://centrumanaliz.pkobp.pl/nieruchomosci/puls-nieruchomosci-ziemia-w-cenie
- NBP, ceny ofertowe vs transakcyjne, 2 kw. 2025: https://www.money.pl/gospodarka/rozstrzal-miedzy-cenami-ofertowymi-i-transakcyjnymi-mozna-przeplacic-bez-negocjacji-7198703003024288a.html
- Koszty uzbrojenia działki 2026: https://gruntownie.eu/blog/uzbrojenie-dzialki-koszty-2026
- Marża deweloperów z GPW w 2025: https://www.pap.pl/mediaroom/171-proc-taka-marze-netto-osiagnely-firmy-deweloperskie-notowane-na-gpw-w-2025-r
- OnGeo, Raport o Terenie (benchmark produktowy): https://ongeo.pl/

### Narzędzia i infrastruktura
- Apify, cennik: https://apify.com/pricing
- Apify, aktor Otodom: https://apify.com/trev0n/otodom-scraper
- Apify, agregator polskich portali: https://apify.com/trev0n/polish-real-estate-aggregator
- Supabase, cennik i limity funkcji: https://supabase.com/pricing , https://supabase.com/docs/guides/functions/limits
- Hetzner, korekta cen z 15.06.2026: https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/
- Coolify: https://coolify.io/pricing
- Webshare, proxy rezydencjalne: https://www.webshare.io/residential-proxy
- Bright Data, cennik: https://brightdata.com/pricing
- Resend, cennik: https://resend.com/pricing

---

*Dokument opracowany na podstawie równoległego researchu w pięciu obszarach: portale i dostępność danych, publiczne źródła geoprzestrzenne, stack technologiczny, metodologia wyceny i scoringu, stan prawny scrapingu. Wszystkie endpointy oznaczone jako zweryfikowane były wywołane na żywo 20 sierpnia 2026. Sekcja prawna nie jest poradą prawną.*

---

# CZĘŚĆ II. ZAŁĄCZNIK IMPLEMENTACYJNY

Sekcje 1-12 opisują **co** budujemy i **dlaczego**. Ta część opisuje **jak**, na poziomie, z którego Claude Code może pracować bez dopytywania o podstawy. Wszystko poniżej zakłada wariant lokalny (sekcja 13).

---

## 13. Wariant lokalny: start za 0 zł

Cały system działa na Twoim komputerze. Nic z rekomendowanego stacka nie ma opłat licencyjnych. Płacisz dopiero za dwie rzeczy: żeby działało 24/7 bez Twojego kompa, i za dostęp do Otodomu z OLX.

### 13.1. Co się zmienia względem wariantu serwerowego

| Element | Wariant serwerowy | Wariant lokalny |
|---|---|---|
| Baza | Supabase Pro albo Postgres na VPS | kontener `postgis/postgis` na localhost |
| Harmonogram | APScheduler jako usługa systemd | `python -m grunt.jobs run-daily` ręcznie albo cron/Harmonogram zadań |
| Frontend | Vercel albo ten sam serwer | `npm run dev` na `localhost:3000` |
| Backend | uvicorn za nginx | `uvicorn` na `localhost:8000` |
| Logowanie | Supabase Auth | jeden użytkownik w `.env`, bez logowania |
| Otodom i OLX | Apify Starter | Apify Free (5 USD kredytu miesięcznie, ok. 1 500 rekordów) albo pomijamy |
| Alerty | Telegram plus e-mail | Telegram (działa tak samo, bot wysyła z Twojego kompa) |
| Koszt | ok. 350 zł/mies. | **0 zł** |

### 13.2. Czego lokalnie nie masz

Trzy rzeczy, i to dokładnie te, za które później płacisz 45 zł miesięcznie:

1. **Codziennego automatu niezależnego od Ciebie.** Scraper chodzi tylko gdy komputer chodzi. Przy działkach to mniejszy problem niż przy mieszkaniach, bo oferta gruntowa wisi tygodniami, nie godzinami
2. **Dostępu z telefonu**
3. **Dostępu dla pozostałych osób**

Przenosiny na serwer to `docker compose up` na VPS plus zmiana jednej zmiennej środowiskowej. Projektując lokalnie nic nie tracisz, o ile trzymasz się zasady "wszystko w kontenerach, żadnych ścieżek absolutnych z Twojego dysku w kodzie".

### 13.3. Wymagania wstępne

| Narzędzie | Wersja | Po co |
|---|---|---|
| Docker Desktop | dowolna aktualna | Postgres z PostGIS jednym poleceniem, plus Valhalla do izochron |
| Python | 3.13 | scraper, wzbogacanie, modele |
| `uv` | aktualna | zarządzanie zależnościami Pythona, szybsze i prostsze niż poetry |
| Node | 22 LTS | frontend |
| DBeaver albo TablePlus | dowolna | oglądanie bazy oczami, kluczowe na etapie fazy 0-1 |
| Miejsce na dysku | **min. 30 GB wolnego** | patrz niżej |

**Budżet dysku dla pomorskiego:**

| Zbiór | Rozmiar |
|---|---|
| RCN, 20 jednostek pomorskiego (GML spakowany plus rozpakowany do importu) | 8-12 GB przejściowo, ok. 1,5 GB w bazie |
| Ekstrakt OSM pomorskie (Geofabrik `.osm.pbf`) | ok. 250 MB |
| BDOT10k dla powiatów pomorskich | ok. 2 GB |
| Kafle Valhalla dla Polski (izochrony) | ok. 3 GB |
| Kafle PMTiles do mapy | ok. 1 GB |
| Baza po zapełnieniu (oferty, historia cen, warstwy) | 3-6 GB |

Rozpakowane GML-e RCN kasuj po imporcie. To największy pojedynczy pożeracz miejsca.

---

## 14. Struktura repozytorium

Podział wynika z jednej zasady: **każdy moduł da się naprawić osobno, bez czytania reszty**. To jest warunek sensownego vibe codingu przy projekcie tej wielkości.

```
grunt/
├── CLAUDE.md                    # instrukcje projektowe dla Claude Code, sekcja 15
├── README.md                    # jak uruchomić, dla człowieka
├── docker-compose.yml           # postgis + valhalla + (opcjonalnie) pgadmin
├── .env.example                 # wzór konfiguracji, sekcja 17
├── pyproject.toml               # zależności Pythona, zarządzane przez uv
│
├── db/
│   ├── migrations/              # Alembic, jedna migracja = jedna zmiana
│   └── seed/                    # słowniki: symbole MPZP, klasy bonitacyjne, TERYT
│
├── src/grunt/
│   ├── config.py                # Pydantic Settings, jedyne miejsce czytania .env
│   ├── db.py                    # sesja SQLAlchemy, silnik, helpery PostGIS
│   ├── models.py                # modele ORM, odpowiadają DDL z sekcji 16
│   │
│   ├── portals/                 # JEDEN PORTAL = JEDEN PLIK
│   │   ├── base.py              # protokół PortalAdapter, sekcja 18
│   │   ├── morizon.py
│   │   ├── nieruchomosci_online.py
│   │   ├── domiporta.py
│   │   ├── gruntguru.py
│   │   ├── apify_otodom.py      # nie scraper, tylko klient API Apify
│   │   └── registry.py          # mapa nazwa -> adapter, jedyne miejsce rejestracji
│   │
│   ├── ingest/
│   │   ├── runner.py            # pętla DIFF: listing -> hash -> detal tylko dla zmian
│   │   ├── normalize.py         # cena, powierzchnia, jednostki, współrzędne
│   │   └── dedupe.py            # etapy 1-6 z sekcji 4.3
│   │
│   ├── sources/                 # KLIENCI DANYCH PUBLICZNYCH, jeden plik na usługę
│   │   ├── geo.py               # WSPÓLNE przeliczenia układów, sekcja 19. Czytaj to najpierw
│   │   ├── uldk.py
│   │   ├── rcn.py               # import GML/GeoParquet do PostGIS
│   │   ├── egib.py
│   │   ├── mpzp.py              # kaskada: Rejestr Urbanistyczny -> KIMPZP -> geoportal gminny
│   │   ├── plan_ogolny.py
│   │   ├── kiut.py              # uzbrojenie
│   │   ├── nmt.py               # wysokość i spadek
│   │   ├── isok.py              # strefy powodziowe
│   │   ├── gdos.py              # obszary chronione, import shapefile offline
│   │   ├── gus_bdl.py
│   │   ├── osm.py               # import ekstraktu pbf, zapytania POI
│   │   └── routing.py           # Valhalla, izochrony
│   │
│   ├── enrich/
│   │   └── pipeline.py          # kolejność wzbogacania, sekcja 6 dokumentu
│   │
│   ├── scoring/                 # SERCE. Funkcje czyste, wejście dict, wyjście dict
│   │   ├── normalize_area.py    # korekta efektu skali, sekcja 5.2.1
│   │   ├── valuation.py         # modele 1-3, sekcja 5.2.3
│   │   ├── pillars.py           # 6 filarów, sekcja 5.3
│   │   ├── gates.py             # mnożniki zerujące, sekcja 5.3.3
│   │   ├── deal.py              # deal score, sekcja 5.4
│   │   └── explain.py           # rozkład wyniku na składniki, sekcja 5.5
│   │
│   ├── jobs/
│   │   ├── scheduler.py         # APScheduler plus tabela zadań
│   │   └── tasks.py             # daily_ingest, weekly_enrich, monthly_retrain
│   │
│   ├── alerts/
│   │   ├── telegram.py
│   │   └── watchdog.py          # alert gdy portal zwraca 0 nowych przez 2 dni
│   │
│   └── api/
│       ├── main.py              # FastAPI
│       └── routers/             # parcels, listings, saved, filters, stats
│
├── web/                         # Next.js 15
│   ├── app/
│   ├── components/
│   └── lib/api.ts               # jeden klient API, typy generowane z OpenAPI
│
├── tests/
│   ├── snapshots/               # zapisane HTML-e portali, sekcja 18.3
│   ├── fixtures/                # przykładowe odpowiedzi ULDK, RCN, KIUT
│   ├── test_portals/            # jeden plik testów na portal
│   ├── test_scoring/            # testy funkcji czystych, najważniejsze w projekcie
│   └── test_geo.py              # przeliczenia układów, sekcja 19
│
└── scripts/
    ├── bootstrap_data.py        # jednorazowe pobranie RCN, OSM, BDOT10k, GDOŚ
    └── eval_valuation.py        # walidacja modelu, sekcja 5.6
```

**Trzy zasady, z których wynika ten podział:**

1. Zmiana HTML na portalu dotyka **jednego pliku** w `portals/`. Nic więcej
2. Cała logika oceny to **funkcje czyste** w `scoring/`. Bez bazy, bez sieci, bez czasu. Dzięki temu da się je testować i tłumaczyć
3. Każde źródło publiczne ma **jednego klienta** w `sources/`. Gdy GUGiK zmieni endpoint, poprawiasz jeden plik

---

## 15. CLAUDE.md do wklejenia do repo

To jest plik, który Claude Code czyta automatycznie na starcie każdej sesji. Bez niego będzie zgadywał konwencje.

```markdown
# GRUNT: instrukcje projektowe

## Czym jest ten projekt
System zbierania ofert działek z polskich portali, wzbogacania ich o dane publiczne
(GUGiK, RCN, MPZP, ISOK, GUS, OSM) i oceny potencjału inwestycyjnego.
Pełna koncepcja: dzialki-system-koncepcja.md w katalogu głównym. Czytaj ją,
gdy pytanie dotyczy "dlaczego tak", a nie "jak to zakodować".

## Stack
Python 3.13 (uv), FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL 17 + PostGIS,
Crawlee for Python, curl-cffi, selectolax, Next.js 15, shadcn/ui, MapLibre GL JS.
Nie dodawaj nowych zależności bez pytania. Jeśli uważasz, że biblioteka jest
potrzebna, napisz dlaczego i poczekaj na zgodę.

## Zasady twarde

### Dane osobowe
NIGDY nie zapisuj do bazy: imion, nazwisk, numerów telefonu, adresów e-mail
ogłoszeniodawców. Numer telefonu wolno przetworzyć wyłącznie do SHA-256 i zapisać
jako hash, tylko na potrzeby deduplikacji. Pełne opisy ogłoszeń nie są
przechowywane, tylko metadane liczbowe i URL do źródła. Zdjęcia nie są
przechowywane, tylko URL i pHash miniatury. To decyzje prawne, nie preferencje.
Jeśli kod, który piszesz, łamie którąś z nich, zatrzymaj się i powiedz o tym.

### Braki danych
NULL to NULL. Nigdy nie zastępuj brakującej wartości zerem ani wartością domyślną
w warstwie danych. Imputacja odbywa się wyłącznie w scoring/ i zawsze zapisuje
flagę is_imputed_*. Reguła produktowa: coverage < 40% oznacza brak wyniku,
nie niski wynik.

### Układy współrzędnych
W bazie wszystkie geometrie w EPSG:2180. Na wyjściu API zawsze EPSG:4326.
Wszystkie przeliczenia idą przez src/grunt/sources/geo.py. Nigdy nie konstruuj
parametrów xy/BBOX ręcznie w kliencie usługi, bo kolejność osi różni się między
usługami GUGiK. Szczegóły w sekcji 19 dokumentu koncepcyjnego.

### Portale
Jeden portal to jeden plik w portals/ implementujący protokół PortalAdapter
z portals/base.py. Adapter nie dotyka bazy. Zwraca obiekty Pydantic.
Każdy adapter ma test na zapisanym snapshocie HTML w tests/snapshots/.
Zmieniasz selektor, aktualizujesz snapshot, uruchamiasz testy.

### Scoring
Wszystko w scoring/ to funkcje czyste: bez I/O, bez bazy, bez datetime.now(),
bez losowości bez jawnego seeda. Wejście to dict albo dataclass, wyjście to dict
ze składnikami wyniku, nie sama liczba. Każda funkcja ma test z ręcznie policzonym
oczekiwanym wynikiem.

### Higiena scrapingu
Domyślne opóźnienie 2 s między żądaniami do tej samej domeny plus jitter.
Respektuj robots.txt. User-Agent uczciwy, z adresem kontaktowym, bez podszywania
się pod przeglądarkę. Zawsze Accept-Encoding: br, gzip. Strategia DIFF:
pobieramy stronę detalu tylko dla ofert nowych albo zmienionych.

### Migracje
Każda zmiana schematu to nowa migracja Alembic. Nigdy nie edytuj istniejącej
migracji, która już się wykonała. Nigdy nie zmieniaj schematu bezpośrednio w SQL.

## Konwencje
- Formatowanie: ruff format. Lintowanie: ruff check. Typy: mypy w trybie strict dla scoring/ i sources/
- Nazwy w kodzie po angielsku, komentarze i komunikaty użytkownika po polsku
- Wszystkie kwoty w groszach jako integer, nigdy float
- Wszystkie powierzchnie w m2 jako integer
- Wszystkie daty w UTC, konwersja na Europe/Warsaw dopiero w warstwie prezentacji

## Testy
pytest. Przed powiedzeniem "gotowe" uruchom pytest i pokaż wynik.
Nie oznaczaj zadania jako ukończonego, gdy testy nie przechodzą.

## Czego nie robić
- Nie refaktoruj kodu, o który nie pytałem
- Nie dodawaj README ani docstringów do wszystkiego "przy okazji"
- Nie twórz warstw abstrakcji "na przyszłość". Ten projekt ma jednego użytkownika
- Nie proponuj przejścia na Kubernetes, Kafkę ani mikroserwisy
```

---

## 16. Schemat bazy: konkretne DDL

Sekcja 6 dokumentu podaje szkic. To jest wersja gotowa do migracji. Wszystkie geometrie w EPSG:2180 (PUWG 1992), bo w tym układzie liczą się odległości w metrach bez transformacji i w nim odpowiadają usługi GUGiK.

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

-- ============ DZIAŁKA: rekord kanoniczny ============
CREATE TABLE parcels (
    id                  bigserial PRIMARY KEY,
    uldk_id             text UNIQUE,               -- np. 226101_1.0089.433/2
    geom                geometry(MultiPolygon, 2180) NOT NULL,
    centroid            geometry(Point, 2180) GENERATED ALWAYS AS (ST_Centroid(geom)) STORED,
    area_ewid_m2        integer,
    teryt_gmina         char(7),
    teryt_obreb         text,
    klasouzytek         text,
    klasa_bonitacyjna   text,
    sposob_uzytkowania  text,
    -- geometria wyliczana, sekcja 5.3.6
    front_m             numeric(6,1),
    smuklosc            numeric(5,2),
    zwartosc            numeric(4,3),
    azymut_osi          smallint,
    spadek_proc         numeric(5,2),
    wysokosc_npm        numeric(6,1),
    road_access         smallint,                  -- 0/1/2, sekcja 5.3.5
    enriched_at         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX parcels_geom_idx     ON parcels USING gist (geom);
CREATE INDEX parcels_centroid_idx ON parcels USING gist (centroid);
CREATE INDEX parcels_gmina_idx    ON parcels (teryt_gmina);

-- ============ OFERTY ============
CREATE TYPE portal_t AS ENUM ('morizon','nieruchomosci_online','domiporta','gruntguru','otodom','olx');

CREATE TABLE listings (
    id                bigserial PRIMARY KEY,
    parcel_id         bigint REFERENCES parcels(id) ON DELETE SET NULL,
    cluster_id        bigint,                      -- grupa duplikatów, sekcja 4.3 etap 6
    portal            portal_t NOT NULL,
    portal_offer_id   text NOT NULL,
    url               text NOT NULL,
    title             text,                        -- tylko tytuł, NIE pełny opis
    price_grosze      bigint,
    area_m2           integer,
    price_per_m2      numeric(10,2) GENERATED ALWAYS AS
                          (CASE WHEN area_m2 > 0 THEN price_grosze/100.0/area_m2 END) STORED,
    price_per_m2_norm numeric(10,2),               -- po korekcie skali, sekcja 5.2.1
    geom              geometry(Point, 2180),
    geom_precision    text,                        -- exact | approx | geocoded
    przeznaczenie_raw text,
    media_raw         jsonb,
    phone_sha256      char(64),                    -- WYŁĄCZNIE hash, sekcja 8.2
    thumb_url         text,
    thumb_phash       bit(64),
    first_seen_at     timestamptz NOT NULL DEFAULT now(),
    last_seen_at      timestamptz NOT NULL DEFAULT now(),
    is_active         boolean NOT NULL DEFAULT true,
    content_hash      text,                        -- do wykrywania zmian w DIFF
    raw_jsonb         jsonb,
    UNIQUE (portal, portal_offer_id)
);
CREATE INDEX listings_geom_idx    ON listings USING gist (geom);
CREATE INDEX listings_active_idx  ON listings (is_active, first_seen_at DESC);
CREATE INDEX listings_cluster_idx ON listings (cluster_id);
CREATE INDEX listings_title_trgm  ON listings USING gin (title gin_trgm_ops);

CREATE TABLE price_history (
    listing_id   bigint NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    price_grosze bigint NOT NULL,
    observed_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (listing_id, observed_at)
);

-- ============ WARSTWY REFERENCYJNE ============
CREATE TABLE rcn_transactions (
    id            bigserial PRIMARY KEY,
    id_dzialki    text,
    geom          geometry(MultiPolygon, 2180),
    cena_grosze   bigint,
    data_trans    date NOT NULL,
    pow_m2        integer,
    przeznaczenie text,
    sposob_uzyt   text,
    rodzaj_rynku  text,
    rodzaj_trans  text,
    teryt_powiat  char(4),
    source_file   text
);
CREATE INDEX rcn_geom_idx  ON rcn_transactions USING gist (geom);
CREATE INDEX rcn_data_idx  ON rcn_transactions (data_trans);
-- indeks częściowy: model uczy się wyłącznie na rekordach z ceną
CREATE INDEX rcn_usable_idx ON rcn_transactions (teryt_powiat, data_trans)
    WHERE cena_grosze IS NOT NULL AND pow_m2 > 0;

CREATE TABLE mpzp_zones (
    id bigserial PRIMARY KEY,
    geom geometry(MultiPolygon,2180) NOT NULL,
    symbol text, symbol_norm text,   -- symbol_norm: znormalizowane MN/MW/U/RM/ZL...
    intensywnosc numeric(4,2), wysokosc_max numeric(5,1), pbc_min numeric(4,2),
    gmina char(7), plan_nazwa text, uchwala_data date, source text
);
CREATE INDEX mpzp_geom_idx ON mpzp_zones USING gist (geom);

CREATE TABLE plan_ogolny (
    id bigserial PRIMARY KEY,
    geom geometry(MultiPolygon,2180) NOT NULL,
    strefa text,                     -- SW, SJ, SZ, SU, SH, SP, SR, SI, SN, SC, SG, SO, SK
    is_ouz boolean NOT NULL DEFAULT false,
    gmina char(7), uchwala_data date
);
CREATE INDEX plan_ogolny_geom_idx ON plan_ogolny USING gist (geom);

CREATE TABLE flood_zones     (id bigserial PRIMARY KEY, geom geometry(MultiPolygon,2180) NOT NULL, scenariusz text NOT NULL);
CREATE TABLE protected_areas (id bigserial PRIMARY KEY, geom geometry(MultiPolygon,2180) NOT NULL, typ text, nazwa text);
CREATE TABLE utilities       (id bigserial PRIMARY KEY, geom geometry(LineString,2180)   NOT NULL, rodzaj text NOT NULL);
CREATE TABLE power_lines     (id bigserial PRIMARY KEY, geom geometry(LineString,2180)   NOT NULL, voltage_kv integer);
CREATE INDEX flood_geom_idx     ON flood_zones     USING gist (geom);
CREATE INDEX protected_geom_idx ON protected_areas USING gist (geom);
CREATE INDEX utilities_geom_idx ON utilities       USING gist (geom);
CREATE INDEX power_geom_idx     ON power_lines     USING gist (geom);

-- ============ OCENY ============
CREATE TABLE valuations (
    parcel_id     bigint NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    model_version text   NOT NULL,
    v_hat_grosze  bigint NOT NULL,
    sigma_hat     numeric(12,2),
    ci_low        bigint, ci_high bigint,
    method        text,          -- median_shrink | se_knn | hierarchical | residual_land
    n_comparables smallint,
    comparables   jsonb,
    computed_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (parcel_id, model_version)
);

CREATE TABLE scores (
    parcel_id     bigint PRIMARY KEY REFERENCES parcels(id) ON DELETE CASCADE,
    score_total   numeric(5,2),
    pillar_scores jsonb NOT NULL,   -- {"planistyka": 82.1, "lokalizacja": 64.0, ...}
    gates         jsonb NOT NULL,   -- {"road_access": 1.0, "flood_q1": 0.4, ...}
    coverage      numeric(4,3) NOT NULL,
    deal_score    numeric(6,3),
    red_flags     jsonb,
    model_version text,
    computed_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX scores_rank_idx ON scores (score_total DESC, deal_score DESC)
    WHERE coverage >= 0.4;

-- ============ UŻYTKOWNIK ============
CREATE TABLE users (id bigserial PRIMARY KEY, email text UNIQUE NOT NULL, created_at timestamptz DEFAULT now());

CREATE TABLE saved_parcels (
    user_id bigint REFERENCES users(id) ON DELETE CASCADE,
    parcel_id bigint REFERENCES parcels(id) ON DELETE CASCADE,
    tags text[], note text,
    status text,        -- nowa | obserwuje | kontakt | odrzucona | kupiona
    created_at timestamptz DEFAULT now(),
    PRIMARY KEY (user_id, parcel_id)
);

CREATE TABLE saved_filters (
    id bigserial PRIMARY KEY,
    user_id bigint REFERENCES users(id) ON DELETE CASCADE,
    name text NOT NULL, filter jsonb NOT NULL,
    alert_channel text, alert_enabled boolean DEFAULT false,
    last_alert_at timestamptz
);

CREATE TABLE feedback (
    user_id bigint REFERENCES users(id) ON DELETE CASCADE,
    parcel_id bigint REFERENCES parcels(id) ON DELETE CASCADE,
    verdict smallint NOT NULL,   -- -1 zła, 0 obojętna, 1 dobra. Do learning to rank
    created_at timestamptz DEFAULT now(),
    PRIMARY KEY (user_id, parcel_id, created_at)
);

-- ============ KOLEJKA ZADAŃ ============
CREATE TABLE jobs (
    id bigserial PRIMARY KEY,
    kind text NOT NULL, payload jsonb,
    status text NOT NULL DEFAULT 'pending',   -- pending | running | done | failed
    attempts smallint NOT NULL DEFAULT 0,
    run_after timestamptz NOT NULL DEFAULT now(),
    locked_at timestamptz, last_error text,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX jobs_pick_idx ON jobs (status, run_after) WHERE status = 'pending';
```

Pobieranie zadania bez broker'a i bez wyścigów:

```sql
UPDATE jobs SET status='running', locked_at=now(), attempts=attempts+1
WHERE id = (SELECT id FROM jobs
            WHERE status='pending' AND run_after <= now()
            ORDER BY run_after LIMIT 1
            FOR UPDATE SKIP LOCKED)
RETURNING *;
```

---

## 17. Konfiguracja: .env.example

```bash
# --- baza ---
DATABASE_URL=postgresql+psycopg://grunt:grunt@localhost:5433/grunt
# port 5433 celowo, żeby nie kolidować z lokalnym Postgresem, jeśli już go masz

# --- zakres pracy ---
REGION_TERYT=22            # pomorskie. Zmiana na 14 to mazowieckie itd.
REGION_POWIATY=2201,2202,2203,2204,2205,2206,2207,2208,2209,2210,2211,2212,2213,2214,2215,2216,2261,2262,2263,2264

# --- scraping ---
SCRAPER_USER_AGENT="GRUNT/0.1 (prywatne narzedzie analityczne; kontakt: TWOJ@EMAIL)"
SCRAPER_DELAY_SECONDS=2.0
SCRAPER_MAX_PAGES_PER_RUN=50
PORTALS_ENABLED=morizon,nieruchomosci_online,domiporta,gruntguru

# --- Apify, opcjonalnie. Bez tokena portale otodom/olx są po prostu pomijane ---
APIFY_TOKEN=
APIFY_OTODOM_ACTOR=trev0n/otodom-scraper
APIFY_MAX_ITEMS_PER_RUN=300

# --- alerty ---
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# --- usługi lokalne ---
VALHALLA_URL=http://localhost:8002
NOMINATIM_URL=https://nominatim.openstreetmap.org

# --- ścieżki danych, wszystko względne do katalogu repo ---
DATA_DIR=./data

# --- scoring ---
SCORING_MODEL_VERSION=v1
AREA_REF_M2=1000           # powierzchnia referencyjna, sekcja 5.2.1
COVERAGE_MIN=0.40          # poniżej tego nie pokazujemy score'u
```

Zasada: **żadnego klucza w kodzie, żadnej ścieżki absolutnej**. `config.py` z Pydantic Settings jest jedynym miejscem, które czyta środowisko.

---

## 18. Protokół adaptera portalu

To jest najczęściej modyfikowany fragment systemu, więc ma najostrzejszy kontrakt.

### 18.1. Interfejs

```python
# src/grunt/portals/base.py
from typing import Protocol, Iterable
from pydantic import BaseModel, HttpUrl
from datetime import datetime

class ListingStub(BaseModel):
    """Co widać na stronie wyników. Tanie, pobierane przy każdym przebiegu."""
    portal_offer_id: str
    url: HttpUrl
    price_grosze: int | None = None
    area_m2: int | None = None
    posted_at: datetime | None = None
    content_hash: str            # hash pól ze stuba, do wykrywania zmian

class ListingDetail(BaseModel):
    """Strona oferty. Droga, pobierana tylko dla nowych i zmienionych."""
    portal_offer_id: str
    title: str | None = None
    price_grosze: int | None = None
    area_m2: int | None = None
    lat: float | None = None
    lon: float | None = None
    geom_precision: str | None = None     # exact | approx | geocoded
    przeznaczenie_raw: str | None = None
    media_raw: dict | None = None
    road_access_raw: str | None = None
    ksztalt_raw: str | None = None
    thumb_url: HttpUrl | None = None
    phone_raw: str | None = None          # NIE ZAPISYWANE. Runner robi z tego SHA-256 i wyrzuca
    raw: dict                             # surowe pola do debugowania

class PortalAdapter(Protocol):
    name: str
    delay_seconds: float
    requires_js: bool

    def list_urls(self, region_teryt: str) -> Iterable[str]:
        """Adresy stron wyników, posortowane od najnowszych."""

    def parse_listing_page(self, html: str) -> list[ListingStub]: ...

    def parse_detail(self, html: str) -> ListingDetail: ...
```

Adapter **nie robi żądań HTTP i nie dotyka bazy**. Dostaje HTML, zwraca obiekty. Cała sieć i persystencja są w `ingest/runner.py`. To jedyny powód, dla którego testy snapshotowe w ogóle działają.

### 18.2. Pętla DIFF w runnerze

```
dla każdego aktywnego adaptera:
    dla każdej strony wyników (do SCRAPER_MAX_PAGES_PER_RUN):
        pobierz HTML, parse_listing_page -> lista stubów
        porównaj content_hash z bazą:
            nowy ID            -> kolejkuj detal
            zmieniony hash     -> kolejkuj detal, dopisz do price_history
            bez zmian          -> tylko last_seen_at = now()
        jeśli cała strona bez zmian i to nie pierwsza strona -> przerwij paginację
    oznacz jako is_active=false oferty niewidziane od 14 dni
```

Warunek wczesnego przerwania jest tym, co robi różnicę 14 GB kontra 81 GB transferu miesięcznie.

### 18.3. Testy snapshotowe

```
tests/snapshots/morizon/listing_2026-08-20.html
tests/snapshots/morizon/detail_dzialka_kartuzy.html
tests/test_portals/test_morizon.py
```

Test sprawdza konkretne, ręcznie odczytane ze snapshota wartości, nie "czy się nie wywaliło":

```python
def test_morizon_detail():
    html = load_snapshot("morizon/detail_dzialka_kartuzy.html")
    d = MorizonAdapter().parse_detail(html)
    assert d.price_grosze == 28_000_000        # 280 000 zł
    assert d.area_m2 == 519
    assert d.lat == pytest.approx(54.3325, abs=1e-4)
    assert d.media_raw["prad"] is True
```

**Procedura naprawy po zmianie HTML na portalu** (napisz ją do README, bo będzie potrzebna kilka razy w roku):
1. Zapisz nowy HTML do `tests/snapshots/<portal>/`
2. Uruchom testy, zobacz co się rozjechało
3. Popraw selektory w jednym pliku adaptera
4. Testy zielone, koniec

Sam Claude Code przechodzi ten cykl bez Twojego udziału, jeśli dasz mu nowy snapshot.

---

## 19. Ściąga: endpointy i pułapki

Skopiuj to do `sources/geo.py` jako docstring modułu. Wszystko poniżej zostało zweryfikowane na żywo w sierpniu 2026.

### 19.1. Trzy różne kolejności osi. To zje więcej czasu niż wszystko inne

| Usługa | Format | Uwaga |
|---|---|---|
| ULDK | `xy=easting,northing` | np. `xy=477471,720567` |
| NMT `GetHByXY` | `x=northing&y=easting` | **odwrotnie niż ULDK** |
| WMS 1.3.0, EPSG:2180 | `BBOX=northing,easting,northing,easting` | |
| WFS 2.0.0 z `BBOX=...,EPSG:2180` | `northing,easting,...` | |

Przy złej kolejności usługi nie zgłaszają czytelnego błędu, tylko zwracają "brak wyników" albo dane z zupełnie innego miejsca w Polsce. To drugie jest znacznie gorsze, bo wygląda na poprawną odpowiedź. Dlatego: jedna funkcja pomocnicza na każdą konwencję, plus test w `tests/test_geo.py`, który sprawdza znany punkt w Gdańsku przez wszystkie trzy.

### 19.2. Endpointy

```
ULDK po współrzędnych (EPSG:2180)
https://uldk.gugik.gov.pl/?request=GetParcelByXY&xy=477471,720567
  &result=id,voivodeship,county,commune,region,parcel,geom_wkt
Odpowiedź: pierwsza linia to status (0 = OK, -1 = brak), potem pola rozdzielone |

ULDK po WGS84 (trzeci element to SRID)
https://uldk.gugik.gov.pl/?request=GetParcelByXY&xy=18.6533,54.3487,4326&result=id,geom_wkt

ULDK po numerze działki
https://uldk.gugik.gov.pl/?request=GetParcelByIdOrNr&id=226101_1.0001.1&result=id,geom_wkt

RCN, ceny transakcyjne (WFS)
https://mapy.geoportal.gov.pl/wss/service/rcn?SERVICE=WFS&VERSION=2.0.0
  &REQUEST=GetFeature&TYPENAMES=ms:dzialki&COUNT=100&SRSNAME=EPSG:2180
  &BBOX=719000,476000,722000,479000,EPSG:2180
Masowy import: rcn.geoforum.pl/download.php?teryt=2204 (ZIP z GML per powiat)
Pola: nier_cena_brutto, dzi_id_dzialki, dzi_przezn_wmpzp, dzi_pow_ewid,
      dok_data, tran_rodzaj_rynku, ms:msGeometry

EGiB, atrybuty działki (WFS)
https://mapy.geoportal.gov.pl/wss/service/PZGIK/EGIB/WFS/UslugaZbiorcza?SERVICE=WFS
  &VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=ms:dzialki&SRSNAME=EPSG:2180&BBOX=...
Pola: ID_DZIALKI, POLE_EWIDENYJNE, KLASOUZYTKI_EGIB, NAZWA_GMINY

Uzbrojenie (WMS GetFeatureInfo)
https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaUzbrojeniaTerenu
Warstwy: przewod_elektroenergetyczny, przewod_wodociagowy, przewod_gazowy,
         przewod_kanalizacyjny, oraz gesut (które powiaty są w usłudze)

Klasa bonitacyjna
https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaUzytkowGruntowych
Warstwa: klasouzytki. Uwaga: najsłabsze pokrycie ze wszystkich usług

MPZP (agregator, nie baza)
https://mapy.geoportal.gov.pl/wss/ext/KrajowaIntegracjaMiejscowychPlanowZagospodarowaniaPrzestrzennego

Plany ogólne gmin
https://mapy.geoportal.gov.pl/wss/ext/PlanyOgolneGmin
Warstwy: strefaPlanistyczna, obszarUzupelnieniaZabudowy, obszarZabSrodmiejskiej
Uwaga: warstwy 2-4 widoczne dopiero w skali 1:5000 i większej

Wysokość n.p.m.
https://services.gugik.gov.pl/nmt/?request=GetHByXY&x=720567&y=477471
Spadek: odpytaj 8 punktów w siatce 5-10 m wokół centroidu i policz gradient

Strefy powodziowe (WMS INSPIRE)
https://wody.isok.gov.pl/wss/INSPIRE/INSPIRE_NZ_HY_MZPMRP_WMS
Warstwy: NZ.ExposedElement_q10, _q1, _q0_2, oraz _hWZ (morski, krytyczny w pomorskim)

Osuwiska
https://cbdgmapa.pgi.gov.pl/arcgis/services/geozagrozenia/sopo_obszary/MapServer/WMSServer

Obszary chronione (GDOŚ)
https://sdi.gdos.gov.pl/wfs
Uwaga: blokuje IP datacenter przez Incapsula. Pobierz shapefile per województwo
i importuj offline. Granice i tak zmieniają się rzadko

GUS BDL
https://bdl.stat.gov.pl/api/v1/data/by-unit/042200000000?var-id=4899&format=json
Zarejestruj darmowy klucz X-ClientId, podnosi limity

dane.gov.pl
WYMAGA nagłówka Accept: application/vnd.api+json. Bez niego odpowiedź się nie parsuje

Routing i izochrony
Publiczne: https://valhalla1.openstreetmap.de/route
Produkcyjnie: własna instancja Valhalli w Dockerze na ekstrakcie Geofabrik
https://download.geofabrik.de/europe/poland/pomorskie-latest.osm.pbf
```

### 19.3. Pozostałe pułapki

| Pułapka | Objaw | Rozwiązanie |
|---|---|---|
| WMS GUGiK bez `STYLES` | `MissingParameterValue` | zawsze wysyłaj `STYLES=`, nawet puste |
| RCN, puste ceny | w 3 z 5 testowych rekordów `nier_cena_brutto` było puste | filtruj `WHERE cena_grosze IS NOT NULL`, indeks częściowy jest już w DDL |
| RCN, bardzo stare rekordy | znaleziono transakcję z 2007 | do modelu bierz ostatnie 24 miesiące, starsze indeksuj trendem |
| KIMPZP dla Gdańska | "brak serwisu dla wskazanego obszaru" | KIMPZP to proxy do usług gminnych, nie baza. Kaskada źródeł w `mpzp.py` |
| Morizon, separator ceny | `\xa0` zamiast spacji | normalizacja w `normalize.py`, test na tym konkretnym znaku |
| Powierzchnia w arach i hektarach | 1,5 ha zapisane jako 1,5 | parser jednostek plus test na "1,5 ha", "15 a", "1500 m2" |
| Otodom i OLX z serwera | 403 na wszystkim, łącznie z robots.txt | nie próbuj obchodzić, użyj Apify albo pomiń |
| Rejestr Urbanistyczny | adresy WFS nieudokumentowane | otwórz `rejestr-urbanistyczny.gov.pl/published` z zakładką Network i odczytaj XHR |

---

## 20. Kontrakt API

FastAPI generuje OpenAPI automatycznie, frontend bierze z niego typy. Lista endpointów wersji 1:

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/api/parcels` | lista z filtrami, paginacja serwerowa, sortowanie |
| GET | `/api/parcels/{id}` | pełna karta: geometria, wycena, score, filary, flagi, źródła |
| GET | `/api/parcels/{id}/comparables` | transakcje RCN użyte do wyceny |
| GET | `/api/parcels/{id}/explain` | rozkład score'u na składniki, sekcja 5.5 |
| GET | `/api/parcels/geojson` | te same filtry, wynik jako GeoJSON dla mapy (EPSG:4326) |
| POST | `/api/parcels/{id}/save` | zapis do ulubionych, tagi, notatka, status |
| DELETE | `/api/parcels/{id}/save` | |
| POST | `/api/parcels/{id}/feedback` | ocena -1/0/1, do learning to rank |
| GET/POST/DELETE | `/api/filters` | zapisane filtry z alertem |
| POST | `/api/valuate` | wycena dowolnej działki po `uldk_id` albo współrzędnych, **bez oferty** |
| GET | `/api/stats/gmina/{teryt}` | mediana ceny za m2, liczba obserwacji, trend |
| GET | `/api/health` | status ostatnich przebiegów per portal, dla watchdoga |

**Model parametrów filtra** (jeden obiekt, używany też jako `filter_jsonb` w `saved_filters`):

```json
{
  "price_min": 100000, "price_max": 600000,
  "area_min": 800, "area_max": 5000,
  "price_per_m2_norm_max": 250,
  "przeznaczenie": ["MN", "MNU"],
  "status_planistyczny": ["A", "B"],
  "teryt_gmina": ["2204032"],
  "isochrone": {"from": [54.35, 18.65], "minutes": 30, "mode": "auto"},
  "media_cost_max": 40000,
  "front_min": 18, "spadek_max": 8,
  "exclude_flood": ["q10", "q1", "hWZ"],
  "exclude_protected": true,
  "score_min": 60, "deal_score_min": 0.5,
  "coverage_min": 0.4
}
```

`POST /api/valuate` jest ważniejszy, niż wygląda. To ten endpoint sprawia, że system ma wartość **od fazy 1**, zanim powstanie jakikolwiek scraper: wklejasz numer działki, którą znalazłeś sam, dostajesz wycenę z przedziałem i listą porównywalnych transakcji.

---

## 21. Kryteria akceptacji per faza

Roadmapa z sekcji 9 mówi, co robimy. To mówi, kiedy to jest skończone. Bez tego faza nigdy się nie kończy, tylko rozmywa.

| Faza | Skończona, gdy |
|---|---|
| **0. Fundament** | `docker compose up` stawia PostGIS. `scripts/bootstrap_data.py` importuje RCN dla 20 jednostek pomorskiego, ekstrakt OSM i granice GDOŚ. `SELECT count(*) FROM rcn_transactions WHERE cena_grosze IS NOT NULL` zwraca **ponad 20 000**. `tests/test_geo.py` przechodzi dla znanego punktu w Gdańsku przez wszystkie trzy konwencje osi |
| **1. Wycena** | `POST /api/valuate` dla 20 losowych działek z RCN, których model nie widział, daje MdAPE **poniżej 30%** i pokrycie przedziału 80% na poziomie **75-85%**. Każda wycena zwraca listę porównywalnych i liczbę obserwacji. Dla gminy bez danych zwraca szeroki przedział, nie błąd |
| **2. Scraper** | Morizon i Nieruchomosci-online, pomorskie. Dwa kolejne przebiegi: drugi pobiera **mniej niż 10%** stron detalu co pierwszy (dowód, że DIFF działa). Testy snapshotowe zielone. Zero pól z danymi kontaktowymi w bazie, zweryfikowane zapytaniem |
| **3. Wzbogacanie i scoring** | Ponad **80%** działek ma `coverage >= 0.4`. Ręcznie sprawdzasz 10 działek, dla których znasz teren, i zgadzasz się z kierunkiem score'u w co najmniej 7. Alert Telegram przychodzi na telefon |
| **4. Aplikacja** | Filtrowanie, sortowanie, mapa, ulubione, notatki działają na `localhost`. Lista 5 tys. ofert renderuje się poniżej 1 s. Karta działki pokazuje rozkład score'u na filary |
| **5. Otodom i OLX** | Deduplikacja daje zmierzony odsetek duplikatów. Ręcznie oznaczony zbiór 200 par: precyzja **powyżej 0,95**, czułość powyżej 0,80 |
| **6. Kalibracja** | β₁ policzone na własnych danych zamiast domyślnego 0,85. Spread oferta kontra transakcja policzony na dopasowanych parach. Analiza wrażliwości wag: zmiana wagi filaru o ±20% nie zmienia pierwszej dziesiątki o więcej niż 3 pozycje |

#### 21.1. Doprecyzowanie kryterium fazy 6 (decyzja z 25.08.2026)

Zdanie „nie zmienia pierwszej dziesiątki o więcej niż 3 pozycje" da się czytać dwojako i na realnych danych **te odczyty się rozjeżdżają**: przy 124 ofertach jedna oferta przesuwała się o 8 pozycji, a skład czołówki zmieniał się o 1 ofertę. Obowiązuje odczyt przez **skład czołówki**: najwyżej 3 z 10 ofert wymieniają się na inne. Najdalsze przesunięcie pojedynczej oferty jest nadal liczone i raportowane, ale jako diagnostyka.

Trzy powody, w kolejności wagi:

1. **Przesunięcie w pozycjach nie skaluje się z N.** Ta sama zmiana wyniku o 0,3 punktu przerzuca ofertę o 8 miejsc przy 126 ofertach i o kilkaset przy 4 000. Kryterium, które staje się trudniejsze wyłącznie dlatego, że przybyło danych, mierzy liczność bazy, a nie jakość scoringu. Wymiana składu jest ograniczona przez `top_n` i zachowuje sens niezależnie od N.
2. **Liczyłby dwa razy tę samą wadę.** Duże przesunięcia biorą się z gęstego środka stawki, a gęstość rozkładu mierzy już osobno test dyskryminacji z sekcji 5.6. Ta sama wada raportowana jako dwa niezależne błędy każe naprawiać ją w złym miejscu.
3. **Odpowiada temu, co widzi użytkownik.** Aplikacja pokazuje listę ofert, nie numery miejsc. Pytanie „czy przy innych wagach zobaczyłbym na górze inne działki" to dokładnie odczyt przez skład.

Uzasadnienie jest powtórzone przy stałej `MAX_ZMIANA_CZOLOWKI` w `scoring/calibration.py`, a test `test_prog_dotyczy_skladu_a_nie_pozycji` pilnuje, żeby nikt nie zmienił znaczenia kryterium po cichu.

---

## 22. Kolejność promptów dla Claude Code

Każdy punkt to jedna sesja, jeden zamknięty zakres, jeden weryfikowalny wynik. Nie łącz ich, bo im dłuższa sesja, tym więcej zgadywania.

**Przygotowanie:** wrzuć do repo `dzialki-system-koncepcja.md` i `CLAUDE.md` z sekcji 15, zanim napiszesz pierwszy prompt.

```
 1. Szkielet: pyproject.toml (uv), docker-compose.yml z postgis/postgis,
    config.py z Pydantic Settings, .env.example, Alembic zainicjowany,
    pusty FastAPI z /api/health. Weryfikacja: docker compose up i health zwraca 200

 2. Migracja 001: pełne DDL z sekcji 16, wszystkie rozszerzenia i indeksy.
    Modele SQLAlchemy w models.py odpowiadające tabelom

 3. sources/geo.py: przeliczenia 2180 <-> 4326, trzy funkcje budujące parametry
    dla ULDK, NMT i WMS. tests/test_geo.py na znanym punkcie w Gdańsku.
    TO ZRÓB PRZED KTÓRYMKOLWIEK KLIENTEM USŁUGI

 4. sources/rcn.py plus scripts/bootstrap_data.py: pobranie ZIP-ów per powiat,
    parsowanie GML, import do rcn_transactions. Raport: ile rekordów, ile z ceną

 5. sources/uldk.py: GetParcelByXY, GetParcelByIdOrNr, cache w bazie,
    throttling. Testy na zapisanych odpowiedziach z tests/fixtures/

 6. scoring/normalize_area.py: korekta efektu skali z sekcji 5.2.1.
    Estymacja β₁ z danych RCN plus test z ręcznie policzonym wynikiem

 7. scoring/valuation.py: Model 1 (mediana znormalizowana z hierarchicznym
    shrinkage). Endpoint POST /api/valuate. scripts/eval_valuation.py
    liczący MdAPE i pokrycie przedziału

 8. scoring/valuation.py: Model 2 (SE-KNN, λ=0,7, K=6). Porównanie z Modelem 1
    w eval_valuation.py, wybór lepszego per segment

 9. portals/base.py plus portals/morizon.py plus test snapshotowy.
    Sam adapter, bez runnera

10. ingest/runner.py plus normalize.py: pętla DIFF, zapis do listings
    i price_history, wykrywanie zniknięcia oferty

11. portals/nieruchomosci_online.py (najbogatsze pola: MPZP, kształt, dojazd, media),
    portals/domiporta.py, portals/gruntguru.py

12. sources/mpzp.py, plan_ogolny.py, kiut.py, nmt.py, isok.py, gdos.py, osm.py
    plus enrich/pipeline.py w kolejności z sekcji 6 dokumentu

13. scoring/pillars.py plus gates.py: 6 filarów i mnożniki zerujące.
    Komplet testów jednostkowych z ręcznie policzonymi wynikami

14. scoring/deal.py plus explain.py

15. jobs/: APScheduler, kolejka na tabeli jobs, zadania daily_ingest
    i weekly_enrich

16. alerts/telegram.py plus watchdog.py

17. ingest/dedupe.py: etapy 1-3 (ULDK, hash telefonu, pHash).
    Zbiór ewaluacyjny 200 par, raport precyzji i czułości

18. api/routers/: pełny kontrakt z sekcji 20

19. web/: Next.js, lista z TanStack Table, filtry, mapa MapLibre,
    karta działki, ulubione
```

Punkty 1-8 to faza 0-1 z roadmapy i **tu jest cała wartość na starcie**. Po punkcie 7 masz działający system wyceny działek, zanim zescrapujesz choć jedną ofertę.

---

## 23. Trzy rzeczy, które najłatwiej zepsuć

1. **Odwrócenie kolejności faz.** Kuszące jest zacząć od scrapera, bo to najbardziej widoczna część. Ale scraper bez modelu wyceny daje listę ofert, czyli to samo, co Otodom. Model wyceny bez scrapera daje realną wartość od pierwszego dnia
2. **Traktowanie braku danych jako zera.** Działka bez informacji o uzbrojeniu nie jest nieuzbrojona. Ten jeden błąd zamienia scoring w generator fałszywych okazji, bo działki z najgorszym pokryciem danych wypłyną na górę listy
3. **Porównywanie surowej ceny za m2.** Bez normalizacji efektu skali system będzie systematycznie wskazywał duże działki jako okazje, a małe jako przepłacone. To nie jest niuans statystyczny, to jest różnica między narzędziem a zabawką

---

# CZĘŚĆ III. WERYFIKACJA IMPLEMENTACYJNA

**Dopisane 21 sierpnia 2026, po zbudowaniu faz 0–4.**

Ta część nie zastępuje poprzednich. Opisuje, co się zmieniło, gdy plan zetknął się z żywymi usługami i danymi: które założenia się potwierdziły, które trzeba było odwrócić i na jakie pytania z sekcji 11 znamy już odpowiedź. Każda liczba poniżej pochodzi z pomiaru, nie z szacunku.

---

## 24. Stan realizacji i wyniki kryteriów akceptacji

> Liczby w tej sekcji pochodzą z 21 sierpnia 2026. Świeższy pomiar i weryfikacja
> domknięcia faz: **sekcja 31**.

| Faza | Kryterium z sekcji 21 | Wynik |
|---|---|---|
| **0. Fundament** | ponad 20 000 rekordów RCN z ceną, testy osi zielone | **137 298 rekordów, 29 800 do modelu, 20 powiatów** |
| **1. Wycena** | MdAPE < 30%, pokrycie przedziału 80% w granicach 75–85% | **MdAPE 19,7%, pokrycie 77,2%, 51% predykcji w ±20%** (n=197) |
| **2. Scraper** | drugi przebieg poniżej 10% detali, zero danych kontaktowych | **41 detali w pierwszym przebiegu, 0 w drugim; audyt PII czysty** |
| **3. Wzbogacanie i scoring** | ponad 80% działek z kompletnością od 40% | **99% (102 ze 103), średnia kompletność 94%** |
| **4. Aplikacja** | filtry, sortowanie, mapa, karta działki na localhost | **działa, lista renderuje się w 152 ms** |

Stan bazy po sesji: 723 oferty (662 Morizon, 61 Nieruchomosci-online), 103 wzbogacone, 101 z policzonym score'em, 137 298 transakcji RCN.

Rozkład statusów planistycznych na 103 wzbogaconych ofertach: **E — 66, B — 19, D — 16**. To znaczy, że co szósta oceniona działka leży już dziś poza Obszarem Uzupełnienia Zabudowy w gminie, która ma plan ogólny, czyli w stanie, który dokument wycenia na 0,30–0,50 wartości.

---

## 25. Odpowiedzi na otwarte pytania z sekcji 11

### 25.1. Ile gmin faktycznie uchwaliło plany ogólne (pytanie 2)

**Zmierzone: 14 ze 145 gmin pomorskiego, czyli 9,7%** (21.08.2026, dziesięć dni przed terminem ustawowym).

Metoda: jeden punkt na gminę, wzięty ze współrzędnych transakcji RCN, zapytanie GetFeatureInfo do warstwy strefaPlanistyczna. W gminach, które plan mają, sprawdzono dodatkowo 60 punktów: **16 leży w OUZ (27%)**, 44 poza. Rozkład stref: SJ 30, SO 13, SU 5, SW 4, SN 3, SP 2, SZ/SK/SI po jednym.

Konsekwencja: dziś przytłaczająca większość działek jest w stanie E, a nie D. Stan E ma najszerszy przedział niepewności (0,50–0,75), więc **wskaźnik ryzyka planistycznego jest dziś przede wszystkim miarą niewiedzy, a nie miarą ryzyka**. To się zmieni w ciągu tygodni i właśnie ta zmiana jest okazją produktową: przejście gminy z E do D obniża wartość działek poza OUZ o kilkadziesiąt procent z dnia na dzień.

Sondaż warto powtarzać. Kosztuje 145 zapytań, czyli około dwóch minut.

### 25.2. Adresy API Rejestru Urbanistycznego (pytanie 1) — zamknięte 25.08.2026

Próba z linii poleceń nie powiodła się. Serwis to aplikacja Angulara, która na każdą nieznaną ścieżkę zwraca własną powłokę (22 KB HTML ze statusem 200), a bundla main-*.js nie udało się odczytać. Jeden ślad: ścieżka /api/public/plans zwraca **500 zamiast powłoki**, więc API pod /api/ istnieje, tylko nie znamy kontraktu.

Zadanie wykonane przez przeglądarkę. Kontrakt odczytany z ruchu sieciowego:

```
GET  /api/public/published/territorial/tree?level=COMMUNE    200, 240 kB
POST /api/public/published/query                             lista aktów
```

Drzewo jednostek działa wprost. `POST /query` odrzuca puste ciało błędem 3000, a zgadywane kształty ciała błędem 5000, więc kontrakt pól wymaga jeszcze jednego przejścia. Wyszukiwarka MPZP ma pole „Wyszukaj identyfikator działki", więc endpoint umie odpowiedzieć, które akty obejmują daną działkę. Adresy są zapisane w `sources/mpzp.py`.

**Ale to nie odblokowuje stanu A**, i to jest właściwy wynik tego zadania: blokerem nigdy nie były adresy. WFS rejestru (`app-mpzp`) ma tylko trzy typy obiektów: `AktPlanowaniaPrzestrzennego`, `DokumentFormalny` i `RysunekAktuPlanowaniaPrzestrzennego`. W tym ostatnim pole `lacze` prowadzi do **georeferencowanego TIFF-a**, a `legenda` do strony HTML. Symbol MN albo MW jest więc pikselem na skanie, nie atrybutem.

Dla porównania plan ogólny (`app-pog`) wystawia `StrefaPlanistyczna` jako obiekt z atrybutami, razem z kompletem wskaźników zabudowy — i to właśnie odblokowało filar chłonności (sekcja 5.2.5). Stąd asymetria całego systemu: strefę planu ogólnego znamy co do liczby, a przeznaczenie MPZP tylko z faktu objęcia planem.

### 25.3. Czy Otodom i OLX wchodzą do wersji 1 (pytanie 6) — rozstrzygnięte 25.08.2026

Pierwotna odpowiedź brzmiała „nie weszły, decyzja pozostaje otwarta". Po ponownym sprawdzeniu obu serwisów odpowiedź rozdziela się na dwie różne.

**Otodom wszedł i nic nie kosztuje.** Sekcje 2.2 i 8.3 twierdzą, że serwis zwraca 403 i że jedyną drogą jest płatny aktor Apify. Zapytanie uczciwym nagłówkiem z adresem kontaktowym daje **200 i megabajt HTML-a**, a `robots.txt` kończy się na `Allow: /` i nie zabrania ścieżki wyników. Co więcej, `robots.txt` Otodomu **nie ogranicza paginacji**, w przeciwieństwie do Morizona i Gratki, więc jedno zapytanie wojewódzkie plus strony wystarczają zamiast dwudziestu zapytań per powiat.

Otodom okazał się przy okazji najlepszym źródłem cech w projekcie: strona detalu podaje `target.Access_types` i `target.Media_types` jako **pola**, a nie jako zdania w opisie. To pierwsze zasila bramkę `brak_dostepu_do_drogi`, która do tej pory nie miała żadnego wejścia.

**OLX nie wszedł i nie wejdzie bez pieniędzy.** Zwraca 403 na stronę wyników **oraz na sam `robots.txt`**, więc nie da się nawet ustalić, na co pozwala. RFC 9309 pozwala potraktować niedostępny `robots.txt` jako pełny zakaz i tak go traktujemy. Zostają dwa wyjścia: aktor Apify albo podszycie się pod przeglądarkę — a tego drugiego zabrania sekcja 8.2 i `CLAUDE.md`.

**Przy okazji doszła Gratka**, o którą dokument nie pytał. Okazała się Morizonem z innymi slugami: ta sama konstrukcja `robots.txt`, ten sam układ `__NUXT_DATA__`, ten sam CDN obrazków. Dała 1 195 ofert w pomorskim i jest zarazem pierwszym realnym materiałem dla deduplikacji cross-portal, bo te same oferty mogą stać na obu serwisach jednej grupy.

Wniosek metodyczny wart zapisania: **stwierdzenie o cudzym serwerze ma datę ważności.** Notatka „portal odmawia" kształtowała plan wydatków przez kilka dni, a jej obalenie zajęło jedno zapytanie.

---

## 26. Poprawki do ustaleń z części I i II

Poniższe punkty korygują konkretne zdania z dokumentu. Nie są to niuanse — każdy z nich zmieniał kod.

### 26.1. Współrzędne z portali nie identyfikują działki

Sekcja 2.2 nazywa ścieżkę „współrzędne, ULDK GetParcelByXY, idDzialki" **kluczową operacją całego systemu**. W praktyce jest to generator kandydata, nie identyfikacja:

| Oferta | Deklarowana powierzchnia | Działka pod punktem wg ULDK | Rozbieżność |
|---|---|---|---|
| Morizon, Gdańsk ul. Wiecka | 1 115 m² | 886 m² | 21% |
| N-O, Kąty Rybackie | 835 m² | 18 983 m² | 2173% |

Drugi przypadek to działka-matka: ogłoszenie mówi wprost, że działka „powstanie z podziału działki nr 273".

Próba obejścia przez pobranie **wszystkich** działek z promienia (EGiB, jedno zapytanie) i wybór tej o zgodnej powierzchni też nie rozstrzyga: w promieniu 150 m od oferty w Gdańsku leży **16 działek o powierzchni zgodnej z ogłoszeniem z tolerancją 10%**, w Kątach Rybackich 12. W podmiejskiej zabudowie sąsiednie parcele mają podobny rozmiar, więc powierzchnia nie jest cechą rozróżniającą.

Druga droga — numer działki w treści ogłoszenia — okazała się rzadka: **na 16 losowych ofert żadna go nie podała**. Morizon w opisie o długości 2834 znaków wymienia numer planu MPZP, nie numer działki.

**Wniosek architektoniczny.** Cechy dzielą się na dwie klasy:

- **liczone dla punktu**: plan ogólny, OUZ, strefy powodziowe, wysokość, spadek, uzbrojenie, odległości. Te warstwy są większe niż działka, więc błąd rzędu 100 m nie zmienia wyniku. To większość scoringu, w tym cały filar 1;
- **wymagające pewnej działki**: front, smukłość, zwartość, azymut. Te liczymy tylko przy dopasowaniu o pewności wysokiej albo średniej, a w pozostałych przypadkach zostają puste i obniżają kompletność.

Ratuje nas to, że Nieruchomosci-online podaje wymiary działki wprost (pole Land dimensions, np. „24m x 25m"), więc front bierzemy z ogłoszenia zamiast z geometrii.

### 26.2. Strategii DIFF z sekcji 18.2 nie da się zrealizować na Morizonie

Sekcja 18.2 przewiduje skan listingu **posortowanego po dacie** i przerwanie paginacji na pierwszej niezmienionej stronie. Plik robots.txt Morizona tego zabrania: sortowanie jest wyłączone regułami dla parametru sort i ścieżek typu /najnowsze/, a paginacja ma zakaz ogólny z wyjątkami tylko dla stron od 2 do 10.

W pomorskim jest **4 952 działki na 142 stronach po 35**, więc jedno zapytanie wojewódzkie daje legalnie najwyżej 350 ofert.

**Rozwiązanie**: 20 wąskich zapytań per powiat zamiast głębokiej paginacji. Oszczędność DIFF zostaje nienaruszona, bo bierze się z niepobierania stron detalu (439 KB), a nie z sortowania.

**Pułapka odkryta przy okazji**: parser robots.txt z biblioteki standardowej Pythona **nie obsługuje wildcardów ani kotwicy końca adresu**. Przepuszczał stronę 11 i sortowanie, czyli dokładnie odwrotnie do intencji serwisu. Potrzebny był własny parser zgodny z RFC 9309, w tym scalanie grup — Morizon ma **dwie osobne sekcje dla User-agent gwiazdka**, a branie tylko jednej gubi połowę zakazów.

### 26.3. Podszywanie się pod przeglądarkę jest niepotrzebne

Sekcja 4.2 zaleca curl-cffi z impersonate="chrome", a sekcja 8.2 punkt 7 wymaga uczciwego User-Agenta i nazywa podszywanie się okolicznością obciążającą. Ta sprzeczność znika: **wszystkie cztery portale wpuszczają uczciwy nagłówek** z nazwą narzędzia i adresem kontaktowym. Morizon przepuszcza mimo Cloudflare, Nieruchomosci-online nie ma nawet grupy dla User-agent gwiazdka w robots.txt, a Gratka i Otodom (sprawdzone 25.08.2026) odpowiadają normalnie.

Jedynym wyjątkiem jest OLX, który odmawia nawet wydania `robots.txt`. To jest właśnie ten przypadek, w którym podszycie się byłoby technicznie skuteczne — i dlatego zasada z sekcji 8.2 ma tu wartość: portalu, który wprost odmawia, nie obchodzimy, tylko zostawiamy.

Projekt nie używa więc curl-cffi ani Crawlee. Pętla DIFF na httpx z throttlingiem wystarcza.

**Osobna pułapka**: dokument każe wysyłać Accept-Encoding z brotli i ma rację (Morizon: 72 KB zamiast 759 KB), ale bez zainstalowanej biblioteki brotli klient HTTP zwraca **nierozpakowane bajty udające tekst**. Parser dostaje śmieci, a wygląda to na blokadę portalu. Nagłówek trzeba składać z faktycznie dostępnych kodeków.

### 26.4. Elastyczności beta 1 nie wolno estymować na wymieszanych danych

Sekcja 5.2.1 podaje wartość startową 0,80–0,90 i każe skalibrować ją na własnych danych. Estymacja na całym zbiorze RCN dała **0,26**, co jest artefaktem, nie właściwością rynku: mała działka „rolna" pod Trójmiastem to de facto działka budowlana po 136 zł/m², a duża to prawdziwe pole po 9 zł/m². Powierzchnia była zmienną zastępczą dla przeznaczenia.

Po rozdzieleniu segmentów elastyczność wraca do sensownych wartości (0,61–0,84 zależnie od segmentu). Estymacja bez podziału musi mieć bezpiecznik: wartość poza przedziałem od 0,4 do 1,1 to prawie zawsze ślad niedomodelowanego zróżnicowania.

### 26.5. Segmentacja po przeznaczeniu jest najsilniejszą pojedynczą dźwignią dokładności

Sekcja 5.2.3 definiuje Model 1 jako „medianę per (gmina razy **przeznaczenie**)". Ten drugi człon łatwo pominąć, a kosztuje on 30 punktów MdAPE. Mediany na danych pomorskich (RCN 2023–2026, n około 21 tys.):

| Przeznaczenie w MPZP | Mediana |
|---|---|
| terenDrogWewnetrznych | 12,6 zł/m² |
| terenRolniczy | 16,6 zł/m² |
| gruntyLesne | 25,7 zł/m² |
| brakMPZPLubWZ | 83,7 zł/m² |
| decyzjaWarunkiZabudowy | 132,4 zł/m² |
| budownictwoMieszkanioweJednorodzinne | 158,2 zł/m² |
| terenZabudowyUslugowej | 248,1 zł/m² |

**Bez segmentacji MdAPE wynosiło 50%, z segmentacją 20%.** Uwaga: pole dzi_przezn_wmpzp jest puste w około jednej trzeciej rekordów, więc worek „nieokreślona" trzeba dodatkowo dzielić po klasyfikacji ewidencyjnej.

### 26.6. Model 2 wygrywa z Modelem 1, ale nie parametrami z literatury

Porównanie na tej samej próbie (n=147, backtest bez wycieku):

| Model | MdAPE | Predykcje w ±20% | Pokrycie przedziału |
|---|---|---|---|
| Model 1, mediana z shrinkage | 27,4% | 36,7% | 82,3% |
| **Model 2, SE-KNN** | **18,3%** | **54,4%** | 76,2% |
| Mieszanka (Model 1 jako prior) | 21,6% | 47,6% | 73,5% |

Mieszanka okazała się **gorsza** od czystego SE-KNN, więc jej nie używamy.

Parametry: lambda 0,7 z literatury jest dobra, ale w praktyce prawie nie ma znaczenia (0,5 / 0,7 / 0,9 dają 18,3 / 18,3 / 18,4%). Znaczenie ma **K**: literatura sugeruje 6, u nas optimum to **20** (K=10 daje 18,6%, K=40 daje 21,5%).

Konieczna okazała się **kara za niezgodność segmentu w metryce odległości**. Bez niej w Gdańsku k najbliższych sąsiadów obejmowało działki od 80 do 1421 zł/m², bo mieszało zabudowę jednorodzinną z usługową, a przedział ufności wychodził bezużyteczny (100 tys. do 21,7 mln zł dla działki wartej około 360 tys.).

### 26.7. Zakres stosowalności modelu trzeba zadeklarować wprost

RCN oznacza jako wolnyRynek transakcje, które obrotem rynkowym nie są: przeniesienia po **1,8 zł/m²**, udziały **1/222** przy powierzchni 1 m², daty transakcji w przyszłości (widziano rok **3517**). Sekcja 5.4 wspomina o tym przy okazji Isolation Forest, ale to zasługuje na regułę produktową.

Przyjęty zakres: transakcje od 5 zł/m² (hektar gruntów ornych w pomorskim to około 67 tys. zł, czyli 6,7 zł/m²), bez pasów drogowych, udziały wyłącznie 1/1, data nie z przyszłości. **Bez tego odsiewu MdAPE Modelu 1 to 44%, po nim 27%** — i różnica nie bierze się z lepszego modelu, tylko z uczciwie zdefiniowanego zakresu. Skrypt walidacyjny ma przełącznik pokazujący pełny obraz.

### 26.8. Deal score wymaga kalibracji spreadu, zanim zacznie znaczyć „okazja"

Model uczy się na cenach **transakcyjnych** z RCN, a porównuje z **ofertowymi**. Efekt: deal score wychodzi systematycznie ujemny (obserwowany zakres od minus 0,6 do minus 13). To nie jest błąd, to spread opisany w sekcji 5.6, którego nikt jeszcze nie policzył.

Do czasu kalibracji na dopasowanych parach **deal score jest miarą względną, nie bezwzględną**: nadaje się do rankingu ofert między sobą, nie do stwierdzenia, że coś jest tanie.

---

## 27. Poprawki do ściągi z sekcji 19

| Ustalenie z dokumentu | Co jest naprawdę |
|---|---|
| ULDK zwraca status 0 przy powodzeniu | GetParcelByXY zwraca 0, ale GetParcelByIdOrNr zwraca **liczbę znalezionych obiektów** (1, 2 i tak dalej). Traktowanie 1 jako błędu kosztowało jedno fałszywe 502 |
| Warstwy planów ogólnych „widoczne dopiero w skali 1:5000" | Usługa deklaruje MaxScaleDenominator równy 100001, czyli renderuje do 1:100000 |
| POLE_EWIDENYJNE i KLASOUZYTKI_EGIB w EGiB WFS | Przychodzą **puste**, mimo że są w schemacie. Powierzchnię trzeba liczyć z geometrii, klasy bonitacyjne brać z KIUG |
| Geometria w odpowiedziach WFS to ms:msGeometry | RCN tak, ale **EGiB używa ms:geom**. Bezpieczniej szukać gml:Polygon w głąb całego obiektu |
| KIMPZP jako proxy do usług gminnych | Potwierdzone. Dla Gdańska „brak serwisu dla wskazanego obszaru", dla Kartuz i Sztutowa „brak wyniku" |
| KIUT: GetFeatureInfo do sprawdzania uzbrojenia | **Bezużyteczny.** Dla każdej warstwy, promienia i formatu zwraca ten sam komunikat „Usługa nie udostępnia danych opisowych". Obecność sieci wykrywamy przez GetMap i rozmiar PNG: 237 B to pusto, 114 B to odmowa ze względu na skalę, powyżej 2 kB to trafienie |
| — | Warstwy przewodów KIUT mają MaxScaleDenominator 1000 (renderują się z bliska), a warstwa zasięgu kgesut ma MinScaleDenominator 50000 (pokazuje się po oddaleniu). Zapytanie z niewłaściwej odległości zwraca pusty obraz, co łatwo wziąć za „nic tu nie ma" |
| ISOK: warstwy q10, q1, q0_2, hWZ | Potwierdzone, plus qWZ, h1, h0_2, BP. Jako jedyna z używanych usług **obsługuje INFO_FORMAT application/json** |
| RCN: filtr po bbox | Działa też **filtr OGC** po dacie i rodzaju nieruchomości. Tnie wolumen około 50-krotnie: bbox 3 na 3 km w Gdańsku to 50 851 rekordów bez filtra i 989 z filtrem |
| RCN: nier_cena_brutto | Dotyczy **całej transakcji**, tak samo nier_pow_gruntu. Cena za m² liczona z dzi_pow_ewid pojedynczej działki jest błędna |
| — | TERYT gminy i obrębu **da się wyprowadzić z dzi_id_dzialki**, więc hierarchia do shrinkage'u nie wymaga dodatkowego źródła |

---

## 28. Zmiany w modelu danych względem sekcji 16

1. **rcn_transactions** — dodane iip_id (jedyny stabilny identyfikator transakcji, bez niego ponowny import duplikuje rekordy), pow_gruntu_m2, udzial, nier_rodzaj, wyliczana cena_m2, wyliczane teryt_gmina i teryt_obreb oraz centroid_2180 z indeksem GiST pod zapytania KNN.
2. **listing_enrichment** — nowa tabela. Powód w punkcie 26.1: większość cech liczymy dla punktu oferty, nie dla działki, więc to oferta jest jednostką wzbogacania.
3. **scores** — kluczowana po listing_id, nie po parcel_id. Pole parcel_id zostaje jako opcjonalne, wypełniane przy pewnym dopasowaniu.
4. **uldk_cache** — cache odpowiedzi ULDK razem z odpowiedziami negatywnymi.
5. **Rozszerzenie vector nie jest instalowane.** Nie ma go w użytej dystrybucji PostgreSQL, a potrzebne będzie dopiero na etapie 5 deduplikacji, który dokument sam odradza na start.

---

## 29. Uzupełnienia procesu

**Snapshoty portali zawierają dane kontaktowe.** Sekcja 18.3 każe je trzymać, sekcja 8.2 zabrania trzymać numery telefonu. Do testu selektorów potrzebna jest sama struktura, więc każdy snapshot przechodzi przez skrypt czyszczący (podmiana na wartości zastępcze, tryb kontrolny do CI).

**Pętla DIFF zostawia dziurę przy pierwszym uruchomieniu.** Detal pobierany jest tylko dla ofert nowych i zmienionych, więc oferty zapisane wcześniej albo pominięte limitem zostają bez współrzędnych **na zawsze**, bo przy każdym kolejnym przebiegu są „bez zmian". Potrzebny jest osobny tryb uzupełniania, który bierze aktywne oferty bez geometrii.

**Watchdog zarabia na siebie od pierwszego uruchomienia.** Wykrył brak współrzędnych u 659 z 703 ofert, dwa portale wpisane w konfigurację bez adapterów i przejściowe błędy DNS przy wzbogacaniu.

**User-Agent wymaga bramki, nie zalecenia.** Placeholder z pliku przykładowego jest gorszy niż brak deklaracji, bo wygląda jak bot udający, że się przedstawia. Scraper odmawia startu, gdy nagłówek nie zawiera adresu kontaktowego albo nazwy narzędzia.

---

## 30. Czego nadal nie ma

> **Nieaktualne od 25 sierpnia 2026.** Cztery pozycje z tej tabeli zostały domknięte.
> Aktualna lista braków jest w `README.md`, uzasadnienie w sekcji 31.6.

| Brak | Skutek | Czego wymaga |
|---|---|---|
| **MPZP** | stan planistyczny A niedostępny, działki z planem miejscowym klasyfikowane jako E, czyli zaniżane | adresów API Rejestru Urbanistycznego z zakładki Network |
| **Filar 2, lokalizacja (22% wagi)** | filar niedostępny, wagi renormalizowane na pozostałe | izochron z własnej instancji Valhalli i ekstraktu OSM |
| **Filar 6, dynamika rynku (5%)** | jak wyżej | GUS BDL i własnych szeregów czasowych |
| **Kalibracja spreadu oferta–transakcja** | deal score systematycznie zaniża oceny | dopasowania ofert do transakcji RCN po numerze działki i oknie czasowym |
| **Harmonogram i deduplikacja** | scraping, wzbogacanie i scoring uruchamiane ręcznie, duplikaty między portalami niewykryte | fazy 5 z roadmapy |
| **Ulubione, notatki, zapisane filtry** | tabele są w schemacie, brak endpointów i ekranu | dopisania warstwy użytkownika |

Ostatnia uwaga, wynikająca z całej sesji: **najwięcej czasu zabrało nie pisanie kodu, tylko sprawdzanie, co usługi naprawdę zwracają.** Większość poprawek w tej części wyszła z jednego zapytania wykonanego na żywo, zanim powstała linijka kodu opartego na założeniu. Ta kolejność — najpierw pomiar, potem implementacja — jest najtańszą rzeczą w tym projekcie.

---

# CZĘŚĆ IV. AUDYT

**Dopisane 25 sierpnia 2026, cztery dni po części III.**

## 31. Audyt 25 sierpnia 2026

Część III opisywała, co zbudowano. Ta sekcja odpowiada na inne pytanie: **czy to,
co zbudowano, faktycznie działa i czy fazy są domknięte wobec kryteriów z sekcji 21.**
Pełne liczby, tabele stanu bazy i lista zadań w kolejności są w `README.md`
w sekcji „Audyt 25.08.2026". Tutaj zostaje tylko to, co zmienia rozumienie systemu.

### 31.1. Wynik: system działa, dwie fazy nie są domknięte

Wszystkie kontrole automatyczne przechodzą (396 testów, ruff, mypy strict na
`scoring/` i `sources/`, TypeScript, build frontendu, jedna głowa Alembica).
Kryteria faz 0, 1, 3 i 4 zostały przeliczone na żywo i są spełnione — wycena daje
MdAPE 19,7% przy pokryciu przedziału 77,2% na próbie 197 transakcji.

Otwarte pozostają dwa kryteria:

- **Faza 5** (Otodom i OLX, 200 oznakowanych par) — nie rozpoczęta, czeka na decyzję
  kosztową, nie na kod.
- **Faza 6**, trzecia składowa — **analiza wrażliwości wag nie istnieje**. β₁ i spread
  są policzone na własnych danych, wrażliwość nie. To jedyne kryterium z całej listy,
  które da się domknąć bez sięgania po nowe źródło danych.

### 31.2. Kompletność mierzy dostępność danych, nie jakość oceny

Średnia kompletność spadła z 94% na **76%** między częścią III a tym audytem, mimo że
nie ubyło ani jednego źródła. Powód: doszedł siódmy filar (chłonność), który nie ma
jeszcze skąd brać danych, a kompletność jest udziałem filarów z danymi.

To nie jest regres, tylko poprawne zachowanie reguły „NULL to NULL" z `CLAUDE.md`.
Warto jednak zapamiętać konsekwencję: **każdy nowy filar obniża kompletność w dniu
dodania i podnosi ją dopiero po podłączeniu źródła.** Kryterium fazy 3 (ponad 80%
ofert z kompletnością od 40%) jest nadal spełnione — 101 ofert ze 103 — bo dotyczy
rozkładu, a nie średniej.

### 31.3. Bramka bez wejścia jest nieodróżnialna od bramki, która nie występuje

Trzy z sześciu bramek nie włączyły się ani razu na 103 ocenionych ofertach:
`brak_dostepu_do_drogi`, `powodz_q10`, `grunt_lesny`. Wszystkie mają testy jednostkowe
i wszystkie działają.

Rozróżnienie jest istotne i nie widać go z samego wyniku:

- `brak_dostepu_do_drogi` i `grunt_lesny` to **zera z braku wejścia** — dostęp do drogi
  i sposób użytkowania nie są dziś zbierane. Bramka nie ma czego sprawdzać.
- `powodz_q10` to prawdopodobnie **zero z prawdy o próbce** — żadna z tych 103 działek
  nie leży w strefie zalewowej raz na dziesięć lat.

Pierwszy przypadek jest luką i zaniża ryzyko, drugi jest poprawnym wynikiem.
Dlatego zakładka metodologii pokazuje przy każdej bramce licznik `aktywny_w_ofertach`:
bez niego obie sytuacje wyglądają identycznie i system wygląda na łagodniejszy,
niż jest w rzeczywistości. Ta sama uwaga dotyczy filarów — stąd kolumna „ma dane".

### 31.4. Zbudowane i nigdy nieuruchomione

Zadania `scrape`, `enrich` i `watchdog` nie wykonały się ani razu, mimo że kolejka
`jobs`, harmonogram i worker są gotowe i przetestowane. `alert_log` ma zero wierszy
przy udanym przebiegu zadania `alerty`. Cała zawartość bazy pochodzi z ręcznych
uruchomień skryptów.

To jest najtańsza do usunięcia luka w całym projekcie i jednocześnie ta, która blokuje
resztę: przy 103 wzbogaconych ofertach każda kolejna praca nad scoringiem opiera się
o próbkę za małą, żeby cokolwiek na niej zweryfikować. **Uruchomienie workera na stałe
jest pozycją numer jeden** na liście dalszych kroków w `README.md`.

### 31.5. Śmieci w RCN są, ale nie wchodzą do wyników

Dziewięć rekordów `rcn_transactions` ma datę transakcji w przyszłości, najdalsza to rok
3517. To literówki w źródle, nie błąd importu. Każde zapytanie modelu, median i historii
cen ma już górne ograniczenie `data_trans <= :as_of` albo `<= current_date`, więc rekordy
te nie wchodzą do żadnego wyniku.

Wniosek do zapamiętania: **górne ograniczenie daty w zapytaniu nie jest kosmetyką.**
Bez niego jedna transakcja z 2027 roku dostałaby ujemny wiek i indeksacja cofnęłaby jej
cenę zamiast ją podnieść.

### 31.6. Sekcja 30 jest nieaktualna

Tabela „Czego nadal nie ma" z sekcji 30 pochodzi z 21 sierpnia. Od tego czasu domknięte
zostały: kalibracja spreadu oferta–transakcja (0,2431 przy n=50), harmonogram
i deduplikacja cross-portal (47 par, 12 klastrów, 4,4%), oraz ulubione, notatki
i zapisane filtry (router `saved.py` plus ekran we froncie). Aktualna lista braków
znajduje się w `README.md` w sekcji „Czego jeszcze nie ma", a kolejność ich usuwania
w sekcji „Co dalej, w kolejnosci".
