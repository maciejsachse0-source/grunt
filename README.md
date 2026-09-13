# GRUNT

A system for finding land plots on Polish real estate portals and scoring their
investment potential using public data (GUGiK, RCN, MPZP, ISOK, GUS, OSM).
Full concept and rationale behind the decisions:
[`dzialki-system-koncepcja.md`](dzialki-system-koncepcja.md) (Polish).
Instructions for Claude Code: [`CLAUDE.md`](CLAUDE.md) (Polish).

This file describes the **actual state**: what works, on what numbers, and
what's missing. Every number below was measured on 2026-08-25, not copied
over from a previous session. Things that already happened and no longer
change anything in the code are removed from this file — history lives in
the concept document and in the migrations.

## Phase status

| Phase | Scope | Acceptance criterion | Result |
|---|---|---|---|
| **0. Data foundation** | PostGIS, RCN import, ULDK, coordinate-system conversions | over 20,000 transactions for the model | **137,298 records, 104,148 with a price, 20 counties** |
| **1. First valuation** | Model 1 (median with shrinkage), Model 2 (SE-KNN), `POST /api/valuate` | MdAPE < 30%, interval coverage 75-85% | **MdAPE 19.7%, coverage 77.2%** (n=197) |
| **2. Scraper** | Morizon, Nieruchomosci-online, Otodom, Gratka; DIFF loop, robots.txt | second pass < 10% detail fetches, zero PII | **0% detail fetches on second pass; PII audit clean 6/6 across 7,300 listings** |
| **3. Enrichment and scoring** | general plan + OUZ (infill zone), flooding, terrain, utilities, pillars, alerts | over 80% of listings with completeness >= 40% | **98% (124 of 126), average completeness 76%** |
| **4. Application** | listings API with filters, Next.js: list, filters, map, detail card | works on localhost, list of 5k renders under 1 s | **48 ms with 7,300 listings in the database** |
| **5. Deduplication and scheduling** | stages from concept section 4.3, `jobs` queue with backoff, worker | measured duplicate rate, jobs run unattended | **19.8% duplicates, 701 clusters; the worker schedules and runs itself** |
| **6. Calibration** | spread, `b1` on our own data, weight sensitivity, discrimination | deal score stops being systematically negative | **spread +24.3%, median deal score from -0.62 to +0.14; sensitivity: 1 of 10 top listings swapped at threshold 3** |

Phase 5 is the only one still open, and **not because of the code**: it's
missing a set of 200 manually labeled pairs (manual work) and OLX (a money
decision).

## Numbers

### Automated checks

```
pytest              525 passed, 11 deselected (network)
ruff check          All checks passed
ruff format         119 files already formatted
mypy strict         Success (scoring/ + sources/ + portals/, 33 files)
tsc --noEmit        exit 0
eslint src          exit 0
next build          Compiled successfully (Next.js 16.3.2)
alembic             015 (head), one head, 15 migrations
audit_pii.py        6/6 clean
```

Postgres 17.6, PostGIS 3.6. `curl` measurements (including connection setup):
`/api/health` 22 ms, `/api/listings?limit=200` 44 ms and 178 kB,
`/api/listings/geojson?limit=5000` 48 ms and 885 kB, `/api/metodologia`
48 ms. Growing the database from 5,332 to 7,300 listings didn't move these
numbers, because list queries hit indexes and limits, not the whole table.

Outside `scoring/`, `sources/` and `portals/`, mypy in default mode reports
17 errors (`api/`, `enrich/`, `jobs/`, `ingest/`, `dedup/`). `CLAUDE.md`
requires strict mode only for the first three directories, and those are
clean.

### Database state

| Table | Rows | Note |
|---|---|---|
| `rcn_transactions` | 137,298 | 104,148 with a price, 73,745 above the 5 PLN/m2 threshold |
| `listings` | **7,300** | Morizon 3,974, N-online 2,050, Gratka 1,195, Otodom 81 |
| `listing_duplicates` | 1,247 pairs | 701 clusters, 19.8% duplicates, 362 pairs awaiting manual review |
| `listing_enrichment` | 133 | growing: the worker takes batches of 60 every hour |
| `listing_category` | 7,300 | parcel type for 1,301 listings, municipality for 4,205 |
| `parcels` | 40 | parcel outlines for the map, backfilled by `scripts/parcels.py` |
| `scores` | 126 | 124 with a score, 2 below the completeness threshold |
| `market_medians` | 504 | municipality 393, county 102, voivodeship 9 |
| `market_dynamics` | 93 | trend computed for 57 areas, the rest not measurable |
| `teryt_names` | 139 | zero duplicate municipality names after disambiguating the type |
| `saved_filters` | 1 | one test filter, `alert_log` has 10 entries |

Deal score computed for 64 of 126 listings, of which **13 exceed the 1.5
attention threshold**.

Nine RCN records have a transaction date in the future (the furthest: year
3517), which is a typo in the source. Every model query and median has an
upper bound `data_trans <= :as_of`, so these records never enter any
result.

### Pillar coverage: one of seven is empty

| Pillar | Has data | Why so much / so little |
|---|---|---|
| risk | 125 / 126 | |
| planning | 124 / 126 | |
| physical | 123 / 126 | limited by the match to a cadastral parcel |
| infrastructure | 122 / 126 | |
| market | 111 / 126 | |
| **capacity** | **17 / 126** | only municipalities with an adopted general plan |
| **location** | **0 / 126** | requires isochrones from our own Valhalla instance |

The weight of an unavailable pillar is renormalized across the rest, not
replaced with a midpoint value. Below 40% completeness the system returns
no number at all, only a reason.

### Four gates out of six have never fired

| Gate | Active on listings |
|---|---|
| `poza_ouz` (outside the infill zone) | 32 |
| `powodz_morska` (sea flooding) | 1 |
| `brak_dostepu_do_drogi` (no road access), `powodz_q10`, `powodz_q1` (flood return periods), `grunt_lesny` (forest land) | **0** |

The gates work and have unit tests. Zeros mean no **input**: road access
and land use aren't collected today from any source other than Otodom,
which so far has 81 listings. Flood zones Q1 and Q10 are a different case —
there, zero may simply be true for this sample.

## Running it from scratch

Requirements: Python 3.13 (installs `uv`), Node 22, ~5 GB of disk space.

```bash
uv sync                                                    # Python environment
powershell -ExecutionPolicy Bypass -File scripts/local_pg.ps1 setup
uv run alembic upgrade head                                # database schema
uv run python scripts/bootstrap_data.py rcn --since 2023-01-01
uv run uvicorn grunt.api.main:app --reload                 # :8000/api/docs
cd web && npm install && npm run dev                       # :3000
```

The database runs locally on port 5433 (PostgreSQL 17 + PostGIS 3.6 from
binaries, no Docker, no admin rights needed). Once Docker is available,
`docker compose up -d db` replaces `local_pg.ps1` with `DATABASE_URL`
unchanged. Importing the whole Pomeranian dataset since 2023 takes about
40 minutes.

```bash
powershell -File scripts/local_pg.ps1 start|stop|status|psql|reset
```

**Set your own address in `SCRAPER_USER_AGENT` in `.env`** — the default
contains a placeholder.

## Deployment: Supabase and Vercel

The split follows the shape of the project, not a preference for vendors:

| what | where | why there specifically |
| --- | --- | --- |
| database | Supabase | PostGIS turns on with a toggle, no server to run yourself |
| API | Vercel, Python function | 21 endpoints, each short and stateless |
| frontend | Vercel, Next.js | already static; `next build` produces two routes |
| scraping, enrichment, scoring | your own machine | a 2 s gap between requests times thousands of pages |

The last row matters most here. The DIFF loop runs for hours and is
deliberately unhurried (see the scraping-hygiene section in `CLAUDE.md`),
so there's nothing to gain from an environment that bills you for function
runtime. The pipeline stays local and writes to Supabase. The side effect
is that **the data in the cloud only refreshes when you run the jobs on
your own machine**, not on its own.

### 1. Database

New Supabase project, European region. Before running the migrations,
enable `postgis` and `pg_trgm` in the `Database` -> `Extensions` panel.
Order matters: migration 001 does `CREATE EXTENSION IF NOT EXISTS`, so with
the extensions already enabled it does nothing, and with them disabled it
installs them into `public` instead of `extensions`, where Supabase keeps
everything else.

Migrations go over a **direct connection on port 5432**, not the pooler.
DDL interrupted halfway through is the worst state a schema can be in:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:<password>@db.<ref>.supabase.co:5432/postgres"
uv run alembic upgrade head
Remove-Item Env:DATABASE_URL
```

Data is moved separately. The schema already comes from Alembic, so from
the local database you only need the content itself:

```powershell
pg_dump --data-only --schema=public --exclude-table=spatial_ref_sys `
        --host localhost --port 5433 --username grunt grunt > data.sql
```

If foreign keys complain about table order on import, don't fight the
dump: `bootstrap_data.py`, `scrape`, `enrich` and `score` are idempotent
and will rebuild everything from scratch. Importing the whole Pomeranian
RCN dataset takes about 40 minutes.

Supabase's free plan caps out at 500 MB. The local `pgdata` directory is
262 MB including WAL and indexes, so you'll either fit or brush up
against the limit depending on how many listings you've collected by
then.

### 2. API

A separate Vercel project, `Root Directory` set to the repo root. The
framework is auto-detected from the dependencies in `pyproject.toml`, and
`[tool.vercel]` in the same file points to `grunt.api.main:app`, since
`src/grunt/api/main.py` isn't one of the paths Vercel looks for by
default. The Python version comes from `requires-python`, i.e. 3.13.

Project environment variables:

```
DATABASE_URL=postgresql+psycopg://postgres.<ref>:<password>@aws-1-<region>.pooler.supabase.com:6543/postgres
DB_SEARCH_PATH=public,extensions
API_CORS_ORIGINS=https://<frontend-domain>.vercel.app
API_WRITE_TOKEN=<python -c "import secrets; print(secrets.token_urlsafe(32))">
```

Here the address is already the pooler (port 6543), because the function
can spin up in many instances at once. `grunt/db.py` recognizes it by port
and automatically disables client-side pooling and prepared statements,
which the transaction pooler doesn't support. `DB_POOLER` exists so this
can be forced manually for an unusual address.

`DB_SEARCH_PATH` is mandatory: without `extensions` on the path,
geoalchemy2 can't resolve the `geometry` type and every geometry query
fails.

### 3. Frontend

A second Vercel project, `Root Directory` set to `web`. Variables:

```
NEXT_PUBLIC_API_URL=https://<api-domain>.vercel.app
NEXT_PUBLIC_API_TOKEN=<same as API_WRITE_TOKEN>
```

Order: API first, then frontend, then back to the API project to add the
real frontend domain to `API_CORS_ORIGINS`. Without this the browser
blocks every request before it reaches the server.

### 4. What stays on your machine

`.env` on your machine points at Supabase (pooler or direct connection,
doesn't matter) and everything runs as before:

```powershell
uv run python scripts/scrape.py
uv run python scripts/enrich.py
uv run python scripts/score.py
```

### What this doesn't solve

**The token is exposed.** `NEXT_PUBLIC_API_TOKEN` ends up in the browser
bundle, and anyone who opens dev tools can see it. It stops bots and
accidental visitors, not a determined person. If that's not enough, there
are two options: turn on Deployment Protection on both projects (then
only your Vercel account can reach the app), or proxy the API through
your own Next.js endpoint, keeping the secret server-side. The second
option is more solid and costs one file, but nobody has written it yet.

**The rest of the API is open.** The token only guards `/api/saved` and
`/api/filters`, i.e. your own data. Listings, valuations and the
methodology come from public sources and stay open, along with
`POST /api/valuate`, which is the slowest endpoint of all.

**Nothing runs by itself.** The scheduler in `scripts/jobs.py` is a
process that has to run somewhere. It won't run on Vercel.

## Valuation: `POST /api/valuate`

Values any parcel, even one that isn't in any listing. This endpoint is
what gives the system value independent of the scraper.

```bash
curl -X POST http://localhost:8000/api/valuate -H "Content-Type: application/json" -d '{
  "uldk_id": "226101_1.0089.433/2",
  "przeznaczenie": "budownictwoMieszkanioweJednorodzinne",
  "price_pln": 300000
}'
```

Response: a valuation with an interval, price per m2 normalized to
1000 m2, a list of comparable RCN transactions, the market segments used,
a deal score against the given price, and explicit warnings (neighbor
distance, spread, picks from outside the segment). Without
`przeznaczenie` (land use) the valuation still works, but the segment is
"undetermined" and the interval is noticeably wider — that's intentional.

Three layers of scoring (concept document, section 5):

* **A, valuation** — `scoring/valuation.py`. Model 1: median normalized
  price/m2, with shrinkage `precinct -> municipality -> county ->
  voivodeship`, `lambda = n / (n + 10)`. Model 2: SE-KNN, `k = 20`,
  `lambda = 0.7`, with a penalty for segment mismatch; the API default,
  8 MdAPE points better than Model 1;
* **B, potential** — `scoring/pillars.py`, seven pillars weighted for two
  investor profiles, gates as multipliers (`scoring/gates.py`), planning
  status A-E (`scoring/planning.py`);
* **C, deal score** — `D = (V - price) / sigma`, thresholds 1.5 and 2.5
  from concept section 5.4.

## Portal scraper

```bash
uv run python scripts/scrape.py robots                     # what's allowed per robots.txt
uv run python scripts/scrape.py run --portal morizon --max-pages 1 --max-details 3
uv run python scripts/scrape.py run                        # all enabled portals
uv run python scripts/scrape.py backfill --portal gratka --limit 500
uv run python scripts/scrape.py status                     # database state plus watchdog
uv run python scripts/audit_pii.py                         # proof of no contact data
```

| Portal | Adapter | Listings | How we fetch |
|---|---|---|---|
| Morizon | done | 3,974 | JSON-LD, per county, pages 1-10 |
| Nieruchomosci-online | done | 2,050 | HTML, 41 listings per page |
| Gratka | done | 1,195 | JSON-LD, per county, pages 1-10 |
| Otodom | done | 81 | `__NEXT_DATA__`, one voivodeship endpoint plus pagination |
| **OLX** | **none** | 0 | returns 403 even on robots.txt |

**Otodom doesn't need Apify and doesn't cost 200 PLN a month.** The
concept document (sections 2.2 and 8.3) had written it off. Re-checked on
2026-08-25 with an honest header: the listing returns 200 and a megabyte
of HTML, and robots.txt ends with `Allow: /`. The adapter works without a
middleman.

**Otodom is the best source of features in the whole project.** The
detail page exposes `target.Access_types` (e.g. `["hard_surfaced"]`) and
`target.Media_types` (e.g. `["water", "electricity"]`) as FIELDS, not
sentences buried in a description. Morizon and Gratka require pulling
this out of the listing text with a regex. `Access_types` is the only
existing input for the `brak_dostepu_do_drogi` (no road access) gate.

**OLX stays outside the system, and it's not a matter of effort.** The
site returns 403 on the results page **and on robots.txt itself**, so
there's no way to even check what's allowed; RFC 9309 lets us treat that
as a full prohibition, and that's what we do. Two options remain: a paid
Apify actor, or impersonating a browser. `CLAUDE.md` explicitly forbids
the second, so OLX is waiting on a money decision.

**Hygiene is built in and there's no switch to turn it off**: an honest
User-Agent with a contact address, a 2 s gap per domain plus jitter,
checking robots.txt before every request, a ban on storing contact data.

One portal is one file in `portals/`, which takes HTML and returns
Pydantic objects. The adapter makes no HTTP requests and never touches
the database, so tests run against saved pages with no internet. After a
portal's HTML changes: save a new snapshot, run it through
`scripts/scrub_snapshot.py`, run the tests, fix the selectors in one
file.

**Four things this part cost us, worth remembering:**

* **Gratka and Morizon are the same company.** Identical robots.txt
  structure (`Disallow: *page=*` with exceptions `Allow: *page=2$`..
  `*page=10$`), the same `__NUXT_DATA__` layout, the same image CDN.
  Gratka's adapter is mostly Morizon with different slugs — this is what
  justified `portals/_shared.py`;
* **Gratka's county slug has two shapes**: rural counties as
  `powiat-gdanski`, cities with county rights as `gdansk`. Getting it
  wrong gives a 404, so all 20 slugs are verified by query and guarded by
  a test;
* **A 404 on the next page is the end of the results, not a failure.**
  Sopot has 15 listings on Gratka, i.e. one page, and the adapter still
  proposes `?page=2`. The runner distinguishes both cases: a 404 on page
  1 is still an error, on later pages it silently ends pagination.
  Without this, every small county added a false error exactly where the
  watchdog looks for a portal that's gone quiet;
* **A listing without a detail page only went back into the queue after
  its price changed, which sometimes meant never.** The DIFF loop only
  fetched the detail page for new or changed listings, so a listing saved
  under `--max-details` stayed without coordinates forever: on the second
  sighting the hash matched and it was marked "unchanged". Now
  `_upsert_stub` also checks for the presence of `raw_jsonb` and returns
  a "no detail" status, which goes back into the queue; this is visible
  in the "backlog" column. This gap was a hole in our own phase-2
  criterion: we were measuring the share of detail pages fetched, not
  the share of listings that actually have one.

## Cross-portal deduplication

```bash
uv run python scripts/dedup.py run                 # recompute pairs and clusters
uv run python scripts/dedup.py klastry             # same parcel, different prices
uv run python scripts/dedup.py pary --min 0.5      # candidates for manual review
uv run python scripts/dedup.py oznacz 361 668 --tak
uv run python scripts/dedup.py precyzja            # thresholds on the labeled set
```

Stages from concept section 4.3, cheapest first: **hard keys** (same
cadastral parcel from ULDK, same thumbnail file), blocking on a 500 m
metric grid, thumbnail pHash, title token overlap. Above 0.70 listings
merge into a cluster; between 0.50 and 0.70 a pair goes into
`listing_duplicates` as a suspected match for manual review. A human
verdict (`dedup oznacz`) survives every recomputation, because without a
labeled set the thresholds would be tuned blind.

A cluster never deletes anything. The **no duplicates** filter in the app
shows one listing per group, and the detail card lists the remaining
sources and the price spread.

### The thumbnail address as a hard key

The single biggest win in deduplication cost zero extra requests and zero
new dependencies. Morizon's and Gratka's thumbnails go through the same
proxy, `img1.staticmorizon.com.pl/thumb/<base64 of the source address>`,
and once base64-decoded, both portals point at **the same file** on
`d-gr.cdngr.pl`.

This isn't the pHash from concept section 4.3. pHash asks "do these two
images look similar" and requires downloading both files plus an image
library. Here we're comparing the address of the same file on the same
server, i.e. **identity, not similarity**. Hence the decision to treat it
as a hard key (confidence 1.0, bypasses blocking), based on measuring
3,298 keys from the database:

* the same key **never once** appeared in two listings on the same
  portal — the concept document's concern about an agency reusing the
  same banner image never materialized;
* 654 keys appeared on both portals at once, and in **654 out of 654
  cases** the price matched to the penny, and in 650 of 654 the area
  matched too.

Result: duplicates jumped from 4.4% to **19.8%**, there are 701 clusters
instead of 12, and the "image" stage resolves 653 pairs versus 230 from
the title and 2 from ULDK. Share of listings merged into a cluster, by
portal (measured while Morizon's detail backfill was still in progress,
so its denominator is still growing):

| Portal | Listings with coordinates | In a cluster | Share |
|---|---|---|---|
| Gratka | 1,194 | 692 | **58.0%** |
| Morizon | 2,516 | 785 | 31.2% |
| Nieruchomosci-online | 154 | 5 | 3.2% |
| Otodom | 81 | 0 | **0.0%** |

**These are lower bounds, not final results**, and there's a mistake
worth recording here. The first measurement, on 323 Gratka listings, gave
96.6% and looked like a product conclusion: "Gratka adds nothing." After
backfilling details for all of Gratka (1,194 instead of 323), the same
measurement gives 58%. The difference wasn't a code bug — it was that
the first 323 listings **weren't a random sample**: the backfill went by
ID, and Gratka's oldest listings are exactly the ones already seen on
Morizon. A share computed on a partially loaded set isn't a share.

The number will keep rising, because Morizon has details for 2,516 of
3,974 listings, and a listing without a fetched detail page has no
thumbnail and can't merge with anything. A measurement independent of
geometry, on thumbnails alone: 55.0% of Gratka's keys also appear on
Morizon (654 of 1,189).

**The product conclusion still holds, just weaker:** more than half of
Gratka is Morizon, so supply should be counted in clusters, not in
`listings` rows. The opposite is true for Otodom: **zero duplicates out
of 81 listings**, meaning every one of its listings is a new parcel in
the database.

Two deviations from the concept document, both forced by the data:

* instead of a geohash at precision 7 we block on a metric grid, because
  geometries are stored in EPSG:2180, not in degrees. Converting
  coordinate systems back and forth just to compute a blocking key is an
  opportunity for a mistake with no upside;
* the phone hash, which the concept document places in stage 1 alongside
  ULDK, doesn't decide anything by itself for us: the same number is the
  same agency, and an agency has dozens of listings in a single county.

## Application

App: **http://localhost:3000**, API docs: http://localhost:8000/api/docs

The screen combines four things from concept section 7: filters (price,
area, parcel type, municipality or county by TERYT code, portal, planning
status, utility cost, frontage, flood zones, duplicates), a MapLibre map
with point color by score and the outline of the selected parcel, a list
sortable by score and deal score, and a parcel detail card broken down by
pillar, with disqualifying multipliers and red flags. A listing with a
duplicate is flagged in the list, and its card has a section listing the
other sources, their prices, and the reason they were merged. Next to the
list are tabs for **saved** (watched listings with a status, note and
rating), **regional prices**, and **how we calculate it**.

Two decisions visible in the UI:

* a listing without a computed score shows a dash and a reason, not a
  zero. A zero would imply a rating that doesn't exist (concept section
  5.3.9);
* data completeness sits next to the score, not buried in the details, so
  it's immediately clear how much data the rating is based on.

### The "how we calculate it" tab

For verification, not presentation. The rule it stands on: **no number on
this page is copied in by hand**. `api/routers/metodologia.py` imports
thresholds and weights directly from the `scoring/` modules, and takes
coverage, distributions and observation counts from live database
queries. Changing a constant in the code changes the page in the same
second. Tests in `tests/test_api_metodologia.py` compare the exposed
values against the source modules.

That's why the page is honest about where the system is incomplete: it
plainly shows zero coverage for the location pillar, low coverage for the
capacity pillar, gates with no input, and the total absence of planning
status A.

The PII audit doesn't check declarations, only the database schema: a
column whose name suggests personal data either has an explicit
justification in `DOZWOLONE_OSOBOWE` ("allowed personal data" — two
entries: phone hash for deduplication, and the system owner's address for
alerts), or it's reported as a violation. The test
`test_audyt_danych_osobowych_nie_znajduje_naruszen` ("PII audit finds no
violations") fails the moment someone adds a `telefon` (phone) column,
and that's the point.

## Job scheduling

```bash
uv run python scripts/jobs.py worker               # loop, runs until Ctrl+C
uv run python scripts/jobs.py tick                 # one cycle and exit
uv run python scripts/jobs.py harmonogram          # what runs and how often
uv run python scripts/jobs.py lista --status failed
uv run python scripts/jobs.py enqueue enrich --payload '{"limit": 500}'
```

The worker schedules itself: scraping every 6 h, enrichment every 1 h in
batches of 60 listings, scoring every 3 h, parcel type and municipality
every 3 h, alerts every hour, deduplication every 12 h, market dynamics
and calibration once a week, watchdog and history cleanup once a day. The
interval is counted from the last **successful** run, so a job that
failed doesn't count as done.

The enrichment batch size grew from 20 to 60, because adding Gratka and
Otodom took the database from 723 to over 7,000 listings, and at the old
batch size catching up on the backlog would have taken over two weeks.
One listing takes about 20 requests and about 12 seconds, so 60 listings
take about 12 minutes out of the hour and average one request every three
seconds to GUGiK's services.

A failed job goes back into the queue with a delay of 5, 10, 20, 40
minutes, up to six hours, and gives up after the fifth attempt. A job
interrupted along with its process stays in `running` status and comes
back after an hour (`queue.ODBLOKUJ_PO_MINUTACH`, "unlock after N
minutes"); `queue.odblokuj_zawieszone(session, po_minutach=0)` ("unlock
stuck jobs") unlocks it manually when you know the process is dead. State
lives in the `jobs` table, not in process memory, so a computer restart
loses nothing, and run results stay in the `jobs.wynik` ("result")
column: "what the system did overnight" is something you read from the
database.

That's why there's no APScheduler or Celery here: all the state they'd
need to keep is already in the `jobs` table, and
`SELECT ... FOR UPDATE SKIP LOCKED` provides the guarantees needed in a
single query.

## Favorites, notes and alerts

```bash
uv run python scripts/alerts.py filtry            # alert state per filter
uv run python scripts/alerts.py filtry-run        # run, dry-run by default
uv run python scripts/alerts.py filtry-run --wyslij
uv run python scripts/alerts.py watchdog-check    # whether a portal has gone quiet
```

Concept sections 7.3 and 7.4. In the app: a star on the listing card, a
status (new, watching, contacted, rejected, bought), a note, a thumbs
rating, and a **saved** tab. In the filter panel: saving the current
filter under a name and a Telegram alert toggle. Endpoints:
`GET/PUT/DELETE /api/saved/{id}`, `POST /api/saved/{id}/ocena` ("rating"),
`GET/POST/PATCH/DELETE /api/filters`.

Three decisions visible in behavior:

* **we save the listing, not the cadastral parcel.** Migration 012
  rebuilds `saved_parcels` into `saved_listings` for the same reason
  migration 007 rebuilt `scores`: we have a confident parcel match for
  some listings, but what you want to save is what you're actually
  looking at;
* **a saved filter is exactly the same object as the list filter.** An
  alert has no matching logic of its own — it just builds the same SQL
  query from it. A filter that shows something different from its alert
  would be worse than no alert at all. An unknown filter field is a 422
  error, not a silent no-op;
* **an alert's first run sends nothing.** A filter turned on against a
  large database matches dozens of listings right away. The first run
  remembers them as known and only raises an alarm about what shows up
  afterward. The UI says this explicitly, so silence right after enabling
  it doesn't look like a failure.

A saved listing stays in your watch list even after it disappears from
the portal; the list then shows it as inactive instead of hiding it — a
listing disappearing is itself information.

An alert assembles correctly and stops at the last step, because `.env`
has no `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID`. The module then runs
in dry-run mode: it formats the content and returns it instead of
sending it, so missing configuration doesn't break the scheduler. Alert
content contains no contact data about the seller at all — there's a
link to the listing and numbers, no person. **Setting up the bot is the
one step that can't be done for the user.**

## Regional prices and market dynamics

```bash
uv run python scripts/market.py run     # medians, TERYT names, listing assignment
uv run python scripts/market.py status  # how many areas have a dynamics figure
uv run python scripts/market.py top     # where prices are rising fastest
curl "http://localhost:8000/api/market?poziom=gmina&segment=mieszkaniowa_jednorodzinna&min_n=30"
```

Median transaction prices per area and land type, with quartiles,
transaction counts, and year-over-year dynamics. In the listing list, the
**vs market** column shows how many percent a listing sits above or
below its market's median. Clicking a row expands a quarterly median
chart with an interquartile band; the chart is drawn inline in SVG, with
no charting library.

Example (municipalities, single-family residential, n >= 30):

| area | median PLN/m2 | raw | quartiles | transactions | yearly |
|---|---:|---:|---:|---:|---:|
| Gdynia (city) | 569 | 635 | 355-738 | 131 | -6.3% |
| Kosakowo | 554 | 467 | 364-814 | 153 | +12.3% |
| Wladyslawowo | 546 | 479 | 310-863 | 37 | +9.9% |
| Reda (city) | 390 | 374 | 316-527 | 58 | +7.0% |

**Decisions without which these numbers would just be decoration:**

* **only undeveloped land.** Checked across all 137,298 RCN records:
  `nier_rodzaj` has a single value. Sales at a discount and sales for
  public purposes are filtered out (748 records), because those are
  administrative prices, not market prices;
* **the median is normalized to a 1000 m2 parcel** (concept section
  5.2.1: never compare raw price per m2). The "raw" column sits next to
  it to show how big the correction is: in Kosakowo, 467 vs 554 PLN/m2;
* **the median is always within a single market segment.** Mixing
  agricultural land with building land was the single cause of a 50%
  MdAPE in the first validation;
* **transactions are indexed to today's** dynamics for their own area.
  The window is 24 months, and the market grows 8-10% a year;
* **levels aren't mixed.** A median is meant to be a true median for a
  specific area; a municipality with fewer than 10 transactions falls
  back to its county, and the UI shows which level that is;
* **the chart is drawn at the municipality level, not the county
  level.** A county isn't one market: in Wejherowo county the median
  ranges from 78 PLN/m2 in Linia municipality to 488 in Rumia, and
  municipalities' share of transactions shifts quarter to quarter, so an
  averaged county would show structural shifts instead of price changes;
* **prices on the chart are NOT indexed to today**, unlike in the median
  table. Indexing would flatten exactly what the chart is meant to show;
* **a quarter with fewer than five transactions gets no point** and
  isn't interpolated; an incomplete quarter is left blank and excluded
  from the trend (RCN data ends 2026-07-30, so Q3 2026 has 109
  transactions versus about 1,700 in a full quarter);
* **transaction count gets its own bar, not a second axis.** Two scales
  on one chart can be made to show any correlation you want by picking
  the ranges;
* **the yearly trend is either measurable, or it doesn't exist.** It's
  computed with Theil-Sen only with six full quarters, a two-year
  window, and a median of ten transactions per quarter. Out of 106
  municipalities, 57 have a trend — the rest show "trend not
  measurable" instead of a number.

Pillar 6 (dynamics) avoids two traps: **composition effect** — dynamics
are computed separately within each segment and only then averaged
weighted by transaction count, i.e. a fixed-basket index; and **scale
effect** — prices are first normalized to 1000 m2 using the `b1`
elasticity from phase 6. A municipality is blended with its county and
voivodeship the same way as in Model 1 (`lambda = n / (n + 30)`), and the
listing card shows the breakdown by segment and level share. Liquidity
(transactions per 1000 residents) requires municipal population figures,
which aren't in RCN — this is the one place where GUS BDL (the national
statistics office's local-data bank) is genuinely needed.

## Calibration

```bash
uv run python scripts/calibrate.py run             # all measurements, and save
uv run python scripts/calibrate.py spread          # listing vs valuation, per segment
uv run python scripts/calibrate.py pary            # the real measurement: listing -> RCN
uv run python scripts/calibrate.py beta1           # elasticity per segment
uv run python scripts/calibrate.py wrazliwosc      # +/-20% on a single pillar
uv run python scripts/calibrate.py dyskryminacja   # whether the scoring distinguishes anything at all
uv run python scripts/calibrate.py historia        # successive measurements over time
```

Every run appends a row to `calibrations`: it's a history of
measurements, not a state, so you can see how the numbers change as more
data comes in.

**Listing-to-transaction spread.** A proper measurement needs pairs of "a
listing disappeared from the portal, its parcel showed up in RCN." There
are zero such pairs today, and that's expected: RCN data ends
2026-07-30, and we've been collecting listings since 2026-08-21. The
query is ready and will start returning results on its own. Until then
we compute a proxy estimate: the ratio of the listing price to the
model's valuation. **This is not the same number**, and it has its own
`zrodlo` ("source") tag in the code, because it mixes the real spread
with the model's error.

**The deal score now means something.** Before calibration: median
-0.62, zero listings above the deal threshold. After correcting for the
measured +24.3%: median +0.14, 13 listings above threshold 1.5. Without
calibration, `aktualny_spread` ("current spread") returns 0.0 and the
deal score stays raw: a missing measurement should be visible in the
number, not patched over with an assumption from the literature.

**Sensitivity to a single pillar's weight.** Phase 6 criterion: changing
a pillar's weight by +/-20% must not move the top 10 by more than 3. The
measurement takes each pillar in turn, multiplies its weight by 1.2 or
0.8, renormalizes the rest, and recomputes the whole ranking — no
randomness involved. The criterion can be read two ways, and **both give
opposite answers**:

| Reading | Measured | Threshold | |
|---|---|---|---|
| (a) furthest move of a single listing | 8 positions | 3 | would fail |
| **(b) turnover in the top-10 set** | **1 of 10** | **3** | **passes** |

**(b) is the one that applies.** The rationale is in concept section
21.1, restated next to the `MAX_ZMIANA_CZOLOWKI` ("max top-list
turnover") constant and guarded by the test
`test_prog_dotyczy_skladu_a_nie_pozycji` ("threshold applies to
composition, not position"). In short: (a) scales with the number of
listings, so it only ever gets harder as more data arrives; (a) would
double-count the density of the score distribution, which the
discrimination test already measures separately; (b) matches what the
user actually sees, since the app shows a list, not rank numbers. The
counterargument still stands: since a rank number can move on a 20%
weight change, a rank number must not be shown as a hard fact — which is
why (a) didn't disappear, it just moved into diagnostics.

The measurement also reports a `rozstrzygajacy` ("decisive") flag. At
101 listings it reported a shift of 0 in all twelve cases, but flagged
itself as non-decisive, because only one pillar differed among the top
listings. Without this flag, phase 6's green checkmark would have been
recorded and nobody would ever have revisited it.

## Capacity and usable floor area (PUM)

Pillar 7, developer profile only (5% weight). The general plan's
`strefaPlanistyczna` ("planning zone") layer returns the full set of
development indicators **in the same `GetFeatureInfo` call we already use
to ask for the zone symbol**, so this pillar costs no extra requests at
all. The indicators go into `listing_enrichment.features` under
`planistyka.wskazniki` ("planning.indicators"), so no migration was
needed.

What comes back (example from Gdynia, two different zones):

```
                                        SJ      SW
maksNadziemnaIntensywnoscZabudowy       0.4     2.5
maksUdzialPowierzchniZabudowy           25%     50%
maksWysokoscZabudowy                    9 m     17 m
minUdzialPowierzchniBiologicznieCzynnej 50%     30%
```

The math is in `scoring/chlonnosc.py`, following concept section 5.2.5
directly. Constraints are computed independently; the binding one is the
strictest:

```
floors = floor(H_max / 3.2 m)

from intensity                PC = A * I
from building-footprint ratio PC = A * U * floors
from biologically active area PC = A * (1 - PBC) * floors

PUM = min(available) * eta
```

A 1000 m2 parcel in zone SJ: the binding constraint is intensity (400 m2
total floor area), eta 0.80, i.e. **320 m2 of usable floor area (PUM)**.
The same parcel in SW: 2,500 m2 total floor area, eta 0.70, i.e.
**1,750 m2 PUM**.

Three decisions before anyone argues with the numbers:

* **height isn't a separate area constraint on its own.** It feeds into
  the other two through the number of floors. A zone that gives a
  building-footprint ratio without a height doesn't constrain total
  floor area beyond the intensity limit;
* **the result says WHICH constraint was binding.** "800 m2" means
  nothing on its own; "800 m2, because the minimum biologically active
  area share is 50%" can be defended. The `wiazace_ograniczenie`
  ("binding constraint") field is in `pillar_scores`;
* **a missing indicator isn't a zero.** A zone with no height limit has
  `None` here and contributes no constraint. When there's no indicator
  at all, the pillar is unavailable and goes into weight
  renormalization.

Scoring is expressed as PUM per m2 of parcel, since only that form is
comparable across parcels of different sizes; the 0.2-1.5 scale spans
the range seen across general plans. The pillar deliberately rewards
high intensity, since the developer profile is buying land for its
buildable floor area. The retail-buyer profile doesn't include this
pillar at all.

## MPZP from the Urban Planning Registry

Service endpoints are in the app's own **Network services** tab, but not
in the page's markup — only behind a copy-to-clipboard button, since the
microfrontend loads them dynamically and they never land in the DOM.
Read and saved in `sources/mpzp.py`:

```
MPZP           WMS  https://rejestr-urbanistyczny.gov.pl/uslugi-sieciowe/wms-mpzp/wms
               WFS  https://rejestr-urbanistyczny.gov.pl/uslugi-sieciowe/app-mpzp/wfs
general plans  WMS  .../wms-pog/wms          WFS  .../app-pog/wfs
REST           GET  /api/public/published/territorial/tree?level=COMMUNE
               POST /api/public/published/query
```

**What it gives us.** The act's boundary, its title, effective date,
legal status, and an IIP identifier tied to the municipality's TERYT
code. Enough to say "this parcel is covered by an MPZP (local zoning
plan)."

**What it doesn't give us: land-use designation.** The MN/U/MW zoning
symbol isn't in any of the three object types. The proof is in the
`RysunekAktuPlanowaniaPrzestrzennego` ("zoning-plan drawing") object: the
plan's drawing is a **georeferenced TIFF**, and its legend is an HTML
page, so the symbol is a pixel on a scan, not an attribute. So a parcel
covered by an MPZP doesn't get planning status A — it gets the
intermediate status **"covered by an MPZP, land use unknown,"** with a
multiplier range of 0.45-1.00.

Hence the asymmetry in the whole system: we know the general plan's zone
as an exact number, but an MPZP's land use only as the fact of being
covered by one. `POST /query` rejects an empty body with error 3000, and
returns 5000 for guessed field shapes, so the field contract still needs
to be reverse-engineered from the app — but that won't unlock status A.

```bash
uv run pytest tests/test_mpzp.py -m network    # check whether the service still responds
```

## Enrichment and scoring

```bash
uv run python scripts/enrich.py run --limit 10     # pull in public data
uv run python scripts/enrich.py status             # phase 3 acceptance criterion
uv run python scripts/enrich.py show --listing-id 663
uv run python scripts/score.py run                 # score and deal score
uv run python scripts/score.py top --limit 15      # ranking
```

One listing takes about 20 requests to public services (EGiB, general
plan, ISOK, NMT, KIUT), i.e. a dozen or so seconds. Enrichment is
incremental: it picks up listings that are unenriched or older than 30
days. Features fall into two classes: for the **point** (general plan,
OUZ, flooding, elevation, slope, utilities — layers larger than a parcel,
so a 100 m error doesn't change the result) and for the **parcel**
(frontage, slenderness, compactness, azimuth — these require a confident
match, and without one they're left blank and lower the completeness
score instead of being made up).

## What the data taught us

Things that couldn't have been predicted before actually touching the
sources. Each one cost a separate investigation, so they're recorded
here so they don't cost one twice.

**About the model and the market**

1. **Land use decides everything.** `terenRolniczy` (agricultural land)
   has a median of 16.6 PLN/m2, `budownictwoMieszkanioweJednorodzinne`
   (single-family residential) 158.2 PLN/m2, `terenZabudowyUslugowej`
   (commercial/service land) 248.1 PLN/m2. The model without
   segmentation had a 50% MdAPE, with segmentation 20%.
2. **The `b1` elasticity can't be estimated on mixed data.** It comes out
   to 0.26 instead of 0.85, because area then acts as a proxy for land
   use: a small "agricultural" parcel near the Tri-City is really a
   building plot. After splitting into segments (104k transactions):
   single-family 0.756, commercial/industrial 0.855, roads 0.822,
   multi-family 1.136. Segments that are still a mix show up as low
   values: agricultural 0.523 and building-permit-pending land 0.496,
   with `R2` of 0.11. With knots, elasticity is clearly non-monotonic
   (it drops to about 0.22 in the 800-3000 m2 band), exactly as Ritter
   describes.
3. **Distance beats administrative boundaries.** Error rises from 28% to
   62% when there are fewer than five local transactions, and a
   cadastral precinct can span six kilometers. Hence Model 2 and the
   GiST index on the centroid.
4. **RCN contains transactions that aren't market trades**: transfers at
   1.8 PLN/m2, 1/222 shares, dates in the future (year 3517). The
   model's scope of validity is explicitly narrowed and documented in
   `scripts/eval_valuation.py`.
5. **The deal score is almost always negative**, and that's expected
   until calibration: the model learns from TRANSACTION prices but is
   compared against LISTING prices.
6. **Land-price dynamics in Pomerania run at a median of +10% a year at
   the municipality level** (76 municipalities, 30k transactions),
   against a +6.0% average once blended. The "is this still the market"
   threshold had to be lowered from 60% to 40% a year per segment: at
   60% a "-42% a year" case slipped through — a parcel in the city in
   2023 compared with one on the outskirts in 2026.

**About scoring, and about measuring our own work**

7. **A test with nothing to measure looks exactly like a test that
   passed.** The sensitivity analysis at 101 listings reported a shift
   of 0 in all twelve cases — formally satisfying the phase 6 criterion.
   The real reason was different: only one pillar differed among the
   top listings, so the ranking was just a sort on a single number, and
   no choice of weights could have reversed it. Every validation metric
   has to report not just its result, but whether it had any chance of
   coming out differently — hence the `rozstrzygajacy` ("decisive") flag
   alongside `spelnione` ("met").
8. **A metric that grows with the database doesn't measure quality.**
   The same 0.3-point score change produces an 8-position swing at 126
   listings and several hundred at 4,000. A criterion that only gets
   harder as data grows punishes the project for growing — that's why
   phase 6 is read through top-10 composition instead.
9. **The scoring barely distinguishes between parcels: 43% of listings
   fall in the 60-70 point range**, against a 35% threshold from concept
   section 5.6. Same reason as everywhere else: a handful of the seven
   pillars and the `poza_ouz` gate do most of the work.
10. **Adding a pillar made the discrimination test worse** (38% -> 43%).
    That's not a bug in the pillar, it's a property of a weighted
    average: the more components, the more the result gets pulled
    toward the middle. The answer isn't to hide the metric, it's the
    2x2 matrix from concept section 5.7 instead of a single number.
11. **A job succeeding doesn't mean anything happened.** `alert_log` was
    empty after successful runs of the alerts job, which looked like a
    broken notification path. The cause: zero saved filters, so the job
    succeeded after matching nothing.

**About public services**

12. **Coordinates from portals don't identify a parcel.** For a Morizon
    listing, ULDK returns an 886 m2 parcel against a declared 1,115 m2;
    for an N-O listing, 18,983 m2 against 835 m2. ULDK-by-coordinates is
    a candidate generator, not identification, and enrichment has to
    verify the match by area.
13. **An empty field in a service's schema can come back as the literal
    string `'None'`.** The EGiB WFS schema has `KLASOUZYTKI_EGIB` and
    `POLE_EWIDENYJNE`, and both come back with the literal text `None`.
    Code that only checks whether the element is present would store
    the text "None" as a land-use type. The same trap is in KIUG, where
    "land-use designation" comes back as an empty string. Checked in a
    city, a forest, and a village, because the first hypothesis was
    "this is just Gdansk."
14. **KIUT has no usable GetFeatureInfo** — it returns a fixed message
    for every layer and radius. We detect network presence via GetMap
    and PNG size instead (237 B means empty, 114 B means refused due to
    scale).
15. **The same GetFeatureInfo carried data nobody had asked for.** The
    capacity pillar was zero for 103 listings and had been logged as
    "needs checking whether the service returns indicators at all." It
    does, and in a response we were already fetching. It's worth
    printing a service's full response sometimes, not just the fields
    you parse.
16. **The general plan exists for 14 of 145 Pomeranian municipalities
    (9.7%)**, and in municipalities with a plan, 16 of 60 points fall
    inside the OUZ (infill zone). The statutory deadline is 2026-08-31,
    so coverage will grow fast, and a municipality moving from status E
    to D cuts land value outside the OUZ by several dozen percent in a
    single day.
17. **The Urban Planning Registry has 524 MPZP acts nationwide**, of
    which 111 are in Pomerania, all from Gdansk. Checking 30 random
    listings: zero covered; four listings in Gdansk itself: also zero,
    because the city has published only a few dozen of the most recent
    out of hundreds. The mechanism is ready, but today it doesn't change
    a single listing.
18. **A third axis-order convention, in a fourth service.** The Urban
    Planning Registry reads a `BBOX` with the short code `EPSG:2180` as
    easting,northing, and with the urn form, the reverse. Getting the
    combination wrong doesn't return an error, just zero objects, which
    looks like "no plan here." From now on, axis order is derived from
    the `srsName` form (`gml.kolejnosc_easting_first`, "axis order:
    easting first"), not assumed by the caller.

**About the portals**

19. **"The portal refuses" can go stale within a few days.** The concept
    document had written off Otodom (403, the only route being a paid
    Apify) and that note shaped the budget plan. Checking it again took
    one request and came back 200 plus `Allow: /`. The lesson isn't "the
    document was wrong," it's that **a claim about someone else's server
    has an expiration date**, so it should be re-checked before paying
    to work around it.
20. **Same owner, same architecture.** Gratka turned out to be Morizon
    with different slugs. With two portals, copy-paste was cheaper than
    an abstraction; with four, it wasn't — that's what justified
    `portals/_shared.py`.
21. **Before reaching for a similarity metric, check whether you already
    have identity somewhere.** Two of the three strongest deduplication
    signals are empty (`phone_sha256`, because we don't collect phone
    numbers; `thumb_phash`, because it would need an image library), and
    yet deduplication still works — because the thumbnail file's own
    address is shared between Morizon and Gratka. Duplicates were 4.4%
    while there were two portals; after adding Gratka it's 19.8%. What
    was overestimated wasn't the concept document's forecast (30-45%),
    it was our own portal count.
22. **A share computed on a partially loaded set isn't a share.** The
    first Gratka duplicate measurement, on 323 of 1,195 listings, gave
    96.6% and looked like a finished product conclusion. After
    backfilling all of Gratka it came out to 58%. The code was correct;
    the sample was biased, because the backfill went by ID, and Gratka's
    oldest listings are exactly the ones already seen on Morizon. Any
    "what percent of X is Y" number needs its numerator and denominator
    shown next to it, and if the denominator is still growing
    mid-measurement, it needs to be labeled a lower bound.
23. **Within a single portal, without an identity signal, area has to
    match to the meter.** Morizon's titles are generated from the
    template "Land for sale, {area} m2 {town}", so two adjacent parcels
    from the same subdivision get the same title, the same point, and a
    similar area. Without this rule, 1,409 m2 and 1,387 m2 parcels on
    the same street in Tywezy were merging into one.
24. **Portals don't say what type of parcel it is.** `przeznaczenie_raw`
    (raw land-use text) looks like a classification, but it's scraps of
    description: across 723 listings the most common values were
    "budowlana" (buildable, 26 times), "Planem Zagospodarowania"
    (zoning plan, 17) and "mpzp" (4). Feeding this into a classifier
    with the RCN dictionary dumped 351 of 361 listings into
    "undetermined," a bucket that's mostly cheap agricultural land — so
    every listing looked 87% above market. After detecting the type
    from the listing text instead, the median deviation dropped to
    +34%, which matches the independently measured +24% spread.
25. **The "area" field is sometimes the building's floor area.** A
    listing "Farm, 150 m2 for 4.29M PLN" produced 14,512 PLN/m2 and
    looked like 161x the median. A normalized price outside the
    1-5000 PLN/m2 range is a data error, not a deal, and such listings
    aren't compared at all.
26. **Morizon's robots.txt forbids sorting and pages beyond 10**, so the
    "scan the listing by date and stop at the first unchanged page"
    strategy from concept section 18.2 is unworkable; instead, 20
    narrow per-county queries. On top of that, the stdlib's
    `urllib.robotparser` doesn't understand wildcards and was letting
    these prohibitions through — hence the custom parser in
    `ingest/robots.py`.

**About the project itself**

27. **A declared dependency isn't a used dependency.** `pyproject.toml`
    listed `curl-cffi`, `selectolax`, `pyarrow` and `pyogrio`, and
    `CLAUDE.md` named the first two as part of the stack. None of these
    packages were imported anywhere: HTTP goes through httpx, HTML isn't
    parsed with selectors (all four portals return data as JSON embedded
    in the page), and GML is read by the stdlib's ElementTree. Four
    dependencies removed on 2026-08-25, tests unchanged. Worth checking
    the same thing at every audit: the stack description should
    describe the code, not a plan from a year and a half ago.

## Don't touch coordinate systems without going through `sources/geo.py`

The services we use side by side have four different axis conventions:
ULDK `easting,northing`, NMT `x=northing&y=easting`, WMS 1.3.0 and RCN's
GML `northing easting`, the Urban Planning Registry depends on the
`srsName` form. Getting the conversion wrong never raises an error — it
just returns data from somewhere else in Poland. All conversions go
through `sources/geo.py`, and `tests/test_geo.py` checks a known point in
Gdansk against every convention.

In the database all geometries are in EPSG:2180; on the API's way out,
always EPSG:4326.

## Tests

```bash
uv run pytest                 # 525 tests, no network
uv run pytest -m network      # 11 tests querying public services live
```

Network tests are marked and disabled by default, but worth running
after changes to `sources/`: they check whether GUGiK's services still
respond the same way.

## Structure

```
src/grunt/
  config.py            the only place that reads .env
  models.py            ORM, matches the DDL from concept section 16
  sources/             one file per data source
    geo.py             coordinate-system conversions, READ THIS FIRST
    uldk.py            coordinates -> parcel number (bridge between layers)
    rcn.py             WFS parser for the Real Estate Transaction Register (RCN)
    rcn_import.py      quadtree + write to PostGIS
    rcn_query.py       comparable-transaction selection, including spatial KNN
    mpzp.py            MPZP from the Urban Planning Registry, service and REST endpoints
    plan_ogolny.py     planning zone, OUZ, development indicators
    egib.py isok.py kiut.py nmt.py gml.py
  portals/             one portal = one file
    base.py            the PortalAdapter protocol (concept section 18.1)
    _shared.py         what's genuinely shared: JSON-LD, prices, utility flags
    morizon.py         listing JSON-LD, coordinates from __NUXT_DATA__
    gratka.py          same as Morizon (same company), different county slugs
    otodom.py          __NEXT_DATA__, road access and utilities as FIELDS
    nieruchomosci_online.py  parcel dimensions straight from the listing
    registry.py         the only place adapters are registered
  ingest/
    normalize.py       price, area, units, phone hash
    robots.py          our own robots.txt interpretation with wildcards
    runner.py          the DIFF loop, the only place making HTTP requests
  enrich/
    match_parcel.py    linking a listing to a parcel, with a confidence level
    parcel_ref.py       parcel number extracted from the listing text
    parcel_store.py    saves parcel geometry into parcels (outline on the map)
    kategoria.py       listing type and municipality, with zero HTTP requests
    geometry.py        frontage, slenderness, compactness, azimuth
    pipeline.py        enrichment orchestration
    score_listings.py  writes scores to the database
    calibrate.py       calibration measurements on database data
    market.py           dynamics and medians from RCN, TERYT names from ULDK
  scoring/             pure functions, no database, no network
    normalize_area.py  scale-effect correction
    segments.py        market segmentation by land use (11 buckets, valuation)
    rodzaj.py            parcel type (4 buckets, user-facing filter)
    valuation.py       Model 1, Model 2, deal score
    pillars.py          the seven pillars
    gates.py             gates as multipliers
    planning.py         planning status A-E
    chlonnosc.py         usable floor area (PUM) from development indicators (concept section 5.2.5)
    calibration.py       spread, rank correlation, weight sensitivity, discrimination
    market.py             price dynamics, market medians, listing deviation
  dedup/               cross-portal deduplication (concept section 4.3)
    keys.py             thumbnail-based key, blocking grid, tokens, Hamming distance
    pairing.py           pair selection and evidence scoring
    cluster.py            union-find, canonical record, price spread
    pipeline.py          the only place in dedup/ that touches SQL
  alerts/
    telegram.py         alerts with inline buttons, dry-run mode without a token
    watchdog.py          alarm when a portal goes quiet or a source fails
    saved_filters.py    notifications from saved filters, no repeats
  jobs/                scheduling with no extra library
    queue.py            the jobs table, SKIP LOCKED, backoff
    scheduler.py         what runs and how often, decided as a pure function
    handlers.py          job type -> pipeline
    worker.py             the loop, a separate transaction per step
  api/                 FastAPI: listings (+ geojson, categories, outline), market,
                       valuate, saved, methodology, schedule, health, stats
db/migrations/         Alembic, 15 migrations
web/src/               Next.js 16, Tailwind 4, MapLibre; 12 components
scripts/               local_pg.ps1, bootstrap_data.py, eval_valuation.py,
                       scrape.py, scrub_snapshot.py, audit_pii.py, dedup.py,
                       jobs.py, calibrate.py, market.py, enrich.py, score.py,
                       alerts.py, parcels.py
```

## What's missing, and what it blocks

Ordered by value-to-cost ratio. None of these items are blocked on code
— each is waiting on a data source, a decision, or manual work.

**Need a data-source decision**

* **Road access and land use.** The `brak_dostepu_do_drogi` (no road
  access) and `grunt_lesny` (forest land) gates never fire outside
  Otodom listings. Checked on 2026-08-25: neither EGiB nor KIUG return
  land-use type (the fields exist in the schema, but come back empty),
  and there's no road network in a free **query** service — the BDOT10k
  WMS under `PobieranieBDOT10k` only exposes administrative boundaries,
  `G2_BDOT10k_WMS` returns 401, and `KrajowaIntegracjaBDOT10k` doesn't
  exist. Three paths remain, each a decision: importing BDOT10k as GML
  per county (the GML parser exists, but that's 20 packages and a new
  table), an OSM extract (a new PBF dependency), or the Overpass API (no
  new dependency, but one request per listing to a community-run
  service).
* **The location pillar (22% of the weight).** The only pillar with
  zero values. Needs its own Valhalla instance and an OSM extract, i.e.
  an infrastructure decision. The single biggest gap in the scoring.
* **MPZP land-use designation** (the MN, U, MW symbol), and with it
  planning status A. It doesn't exist in any data form: the plan's
  drawing is a georeferenced TIFF plus an HTML legend, so reading the
  symbol would require raster interpretation.
* **Market liquidity** as pillar 6's second component: transactions per
  1000 residents needs municipal population figures, which aren't in
  RCN. The one place where GUS BDL is genuinely needed.

**Need money or manual work**

* **OLX.** The only portal that can't be scraped honestly. The options
  are a paid Apify actor (~200 PLN/month) or impersonating a browser,
  which `CLAUDE.md` explicitly forbids.
* **A set of 200 manually labeled pairs** for tuning deduplication
  thresholds. The tools exist (`dedup pary`, `dedup oznacz`,
  `dedup precyzja`), zero pairs are labeled. The last thing standing
  between phase 5 and done.
* **Thumbnail pHash.** The `listings.thumb_phash` column is waiting. No
  longer needed for Morizon and Gratka (the thumbnail-address key covers
  it), but for Otodom and Nieruchomosci-online, which run their own
  CDNs, it would be the only input for that stage. Needs an image
  library, i.e. approval.
* **Expert-agreement test** (`rho > 0.6`). Rank correlation is
  implemented and tested; missing industry experts and 50 rated
  parcels.
* **Alerts delivered to a phone.** The whole path works and assembles a
  correct message. Missing `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
  in `.env`, i.e. a bot account, which isn't something to set up on the
  user's behalf.

**Observed, unexplained**

* **The listing filter once vanished without a trace.** On 2026-08-25,
  `test_filtr_ceny_dziala` ("price filter works") failed three times in
  a row: `/api/listings` with `price_max=200000` returned **7,300
  listings instead of 2,415**, including one at 2,240,000 PLN, meaning
  the query ran without the `price_grosze <= :price_max` condition.
  After a dozen or so minutes the symptom disappeared and couldn't be
  reproduced, either in the test or in a separate script (three runs
  each), despite the code being untouched. Suspicion falls on the same
  cause described in the `ListingFilter` docstring: FastAPI 0.141 can
  silently drop model fields with `Depends()`. So far this looked like
  it only affected list-type fields; this case suggests it might affect
  a scalar field too. The test stays as a detector: a filter that
  filters nothing is worse than no filter at all, so a failure here has
  to be loud. If the symptom returns, the next step is removing
  `Depends()` from this endpoint and listing every field explicitly in
  the signature.

**Left open on purpose**

* **Spread computed on listing-to-transaction pairs** (concept section
  5.6). The mechanism is ready and will switch on by itself once
  listings start disappearing from portals and their parcels start
  showing up in RCN. Today the deal score relies on a proxy estimate
  instead.
* **Score-distribution density.** 43% of listings sit in a single
  ten-point band. This isn't a weighting flaw, it's a property of how
  the score is constructed, and the answer is the 2x2 matrix from
  concept section 5.7, not weight tuning.
* **Gratka's scrape frequency.** More than half its listings are
  Morizon duplicates, and that share keeps growing, so it's worth
  reconsidering whether it should keep running every 6 hours. Best
  decided once Morizon's detail backfill is done, since only then will
  the number stop moving.
* **Types outside `scoring/`, `sources/` and `portals/`**: 17 mypy
  errors in default mode. `CLAUDE.md` requires strict mode only for
  those three directories.
* **More than one user.** `user_id` columns exist in the schema, but
  there's no login: one row in `users` and a fixed identifier in the
  API. Adding a second person is an authentication problem, not a data
  migration.
