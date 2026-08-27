"""Schemat poczatkowy: pelne DDL z sekcji 16 dokumentu koncepcyjnego.

Revision ID: 001
Revises:
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DDL = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============ DZIALKA: rekord kanoniczny ============
CREATE TABLE parcels (
    id                  bigserial PRIMARY KEY,
    uldk_id             text UNIQUE,
    geom                geometry(MultiPolygon, 2180) NOT NULL,
    centroid            geometry(Point, 2180) GENERATED ALWAYS AS (ST_Centroid(geom)) STORED,
    area_ewid_m2        integer,
    teryt_gmina         char(7),
    teryt_obreb         text,
    klasouzytek         text,
    klasa_bonitacyjna   text,
    sposob_uzytkowania  text,
    front_m             numeric(6,1),
    smuklosc            numeric(5,2),
    zwartosc            numeric(4,3),
    azymut_osi          smallint,
    spadek_proc         numeric(5,2),
    wysokosc_npm        numeric(6,1),
    road_access         smallint,
    enriched_at         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX parcels_geom_idx     ON parcels USING gist (geom);
CREATE INDEX parcels_centroid_idx ON parcels USING gist (centroid);
CREATE INDEX parcels_gmina_idx    ON parcels (teryt_gmina);

-- ============ OFERTY ============
CREATE TYPE portal_t AS ENUM
    ('morizon','nieruchomosci_online','domiporta','gruntguru','otodom','olx');

CREATE TABLE listings (
    id                bigserial PRIMARY KEY,
    parcel_id         bigint REFERENCES parcels(id) ON DELETE SET NULL,
    cluster_id        bigint,
    portal            portal_t NOT NULL,
    portal_offer_id   text NOT NULL,
    url               text NOT NULL,
    title             text,
    price_grosze      bigint,
    area_m2           integer,
    price_per_m2      numeric(10,2) GENERATED ALWAYS AS
                          (CASE WHEN area_m2 > 0 THEN price_grosze/100.0/area_m2 END) STORED,
    price_per_m2_norm numeric(10,2),
    geom              geometry(Point, 2180),
    geom_precision    text,
    przeznaczenie_raw text,
    media_raw         jsonb,
    phone_sha256      char(64),
    thumb_url         text,
    thumb_phash       bit(64),
    first_seen_at     timestamptz NOT NULL DEFAULT now(),
    last_seen_at      timestamptz NOT NULL DEFAULT now(),
    is_active         boolean NOT NULL DEFAULT true,
    content_hash      text,
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
CREATE INDEX rcn_usable_idx ON rcn_transactions (teryt_powiat, data_trans)
    WHERE cena_grosze IS NOT NULL AND pow_m2 > 0;

CREATE TABLE mpzp_zones (
    id bigserial PRIMARY KEY,
    geom geometry(MultiPolygon,2180) NOT NULL,
    symbol text, symbol_norm text,
    intensywnosc numeric(4,2), wysokosc_max numeric(5,1), pbc_min numeric(4,2),
    gmina char(7), plan_nazwa text, uchwala_data date, source text
);
CREATE INDEX mpzp_geom_idx ON mpzp_zones USING gist (geom);

CREATE TABLE plan_ogolny (
    id bigserial PRIMARY KEY,
    geom geometry(MultiPolygon,2180) NOT NULL,
    strefa text,
    is_ouz boolean NOT NULL DEFAULT false,
    gmina char(7), uchwala_data date
);
CREATE INDEX plan_ogolny_geom_idx ON plan_ogolny USING gist (geom);

CREATE TABLE flood_zones (
    id bigserial PRIMARY KEY,
    geom geometry(MultiPolygon,2180) NOT NULL,
    scenariusz text NOT NULL
);
CREATE TABLE protected_areas (
    id bigserial PRIMARY KEY,
    geom geometry(MultiPolygon,2180) NOT NULL,
    typ text, nazwa text
);
CREATE TABLE utilities (
    id bigserial PRIMARY KEY,
    geom geometry(LineString,2180) NOT NULL,
    rodzaj text NOT NULL
);
CREATE TABLE power_lines (
    id bigserial PRIMARY KEY,
    geom geometry(LineString,2180) NOT NULL,
    voltage_kv integer
);
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
    method        text,
    n_comparables smallint,
    comparables   jsonb,
    computed_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (parcel_id, model_version)
);

CREATE TABLE scores (
    parcel_id     bigint PRIMARY KEY REFERENCES parcels(id) ON DELETE CASCADE,
    score_total   numeric(5,2),
    pillar_scores jsonb NOT NULL,
    gates         jsonb NOT NULL,
    coverage      numeric(4,3) NOT NULL,
    deal_score    numeric(6,3),
    red_flags     jsonb,
    model_version text,
    computed_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX scores_rank_idx ON scores (score_total DESC, deal_score DESC)
    WHERE coverage >= 0.4;

-- ============ UZYTKOWNIK ============
CREATE TABLE users (
    id bigserial PRIMARY KEY,
    email text UNIQUE NOT NULL,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE saved_parcels (
    user_id bigint REFERENCES users(id) ON DELETE CASCADE,
    parcel_id bigint REFERENCES parcels(id) ON DELETE CASCADE,
    tags text[], note text,
    status text,
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
    verdict smallint NOT NULL,
    created_at timestamptz DEFAULT now(),
    PRIMARY KEY (user_id, parcel_id, created_at)
);

-- ============ KOLEJKA ZADAN ============
CREATE TABLE jobs (
    id bigserial PRIMARY KEY,
    kind text NOT NULL, payload jsonb,
    status text NOT NULL DEFAULT 'pending',
    attempts smallint NOT NULL DEFAULT 0,
    run_after timestamptz NOT NULL DEFAULT now(),
    locked_at timestamptz, last_error text,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX jobs_pick_idx ON jobs (status, run_after) WHERE status = 'pending';
"""

DROP = """
DROP TABLE IF EXISTS jobs, feedback, saved_filters, saved_parcels, users,
    scores, valuations, power_lines, utilities, protected_areas, flood_zones,
    plan_ogolny, mpzp_zones, rcn_transactions, price_history, listings, parcels CASCADE;
DROP TYPE IF EXISTS portal_t;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute(DROP)
