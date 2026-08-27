"""Wyniki wzbogacania per oferta.

Dlaczego osobna tabela, a nie kolumny w parcels: wiazanie oferty z dzialka
ewidencyjna okazalo sie zawodne (pomiar: w promieniu 150 m od oferty w Gdansku
lezy 16 dzialek o zgodnej powierzchni). Wiekszosc cech liczymy wiec dla PUNKTU
oferty, a nie dla dzialki, i tu jest ich miejsce. Kolumny w parcels zostaja
dla dzialek, ktore uda sie dopasowac pewnie.

Kolumny wyciagniete z jsonb na wierzch to te, po ktorych filtruje uzytkownik
(sekcja 7.2) albo ktore wchodza do gate'ow. Reszta zostaje w features.

Revision ID: 006
Revises: 005
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE listing_enrichment (
            listing_id       bigint PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
            enriched_at      timestamptz NOT NULL DEFAULT now(),
            zrodla_ok        text[],
            zrodla_bledy     text[],

            -- planistyka (filar 1, 35% wagi)
            plan_status      char(1),
            plan_strefa      text,
            plan_w_ouz       boolean,
            plan_akt         text,
            mpzp_symbol      text,

            -- ryzyka srodowiskowe (filar 5)
            strefy_powodziowe text[],

            -- fizyka terenu (filar 4)
            wysokosc_npm     numeric(6,1),
            spadek_proc      numeric(5,2),
            front_m          numeric(6,1),
            front_zrodlo     text,
            smuklosc         numeric(5,2),
            zwartosc         numeric(4,3),

            -- infrastruktura (filar 3)
            media            jsonb,
            media_koszt_pln  integer,

            -- dopasowanie do dzialki ewidencyjnej
            parcel_uldk_id   text,
            parcel_match     text,
            parcel_area_m2   integer,

            coverage         numeric(4,3),
            features         jsonb NOT NULL DEFAULT '{}'::jsonb
        );

        CREATE INDEX listing_enrichment_status_idx ON listing_enrichment (plan_status);
        CREATE INDEX listing_enrichment_coverage_idx ON listing_enrichment (coverage DESC);
        CREATE INDEX listing_enrichment_swiezosc_idx ON listing_enrichment (enriched_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS listing_enrichment;")
