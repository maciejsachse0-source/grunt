"""Rodzaj dzialki i gmina oferty jako osobna, tania warstwa.

DLACZEGO OSOBNA TABELA, A NIE KOLUMNY W listings
listings to zapis tego, co powiedzial portal. Rodzaj i gmina sa wyliczone:
rodzaj z planu ogolnego albo z tresci ogloszenia (scoring/rodzaj.py), gmina
z dopasowanej dzialki ewidencyjnej albo z najblizszej transakcji RCN. Wyliczone
dane maja w tym schemacie wlasne tabele (listing_enrichment, listing_market,
scores), zeby dalo sie je przeliczyc od zera bez dotykania rekordu zrodlowego.

DLACZEGO NIE listing_market, KTORA JUZ MA teryt_gmina I segment
listing_market powstaje TYLKO dla ofert, dla ktorych udalo sie znalezc mediane
rynku: 345 wierszy na 7 300 aktywnych ofert (pomiar 25.08.2026). Filtr po gminie
oparty na tej tabeli ukrywalby 95% bazy. Ta tabela liczy sie dla kazdej oferty
i nie wymaga ani ceny, ani powierzchni, ani transakcji porownawczych.

DLACZEGO KOLUMNY MOGA BYC NULL
Rodzaj znamy dla ok. 15% ofert, gmine dla tych ze wspolrzednymi. Reszta zostaje
pusta i tak ma byc pokazana. Wpisanie "mieszkaniowa" tam, gdzie nie wiadomo,
byloby zgadywaniem (regula NULL to NULL z CLAUDE.md).

Revision ID: 015
Revises: 014
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE listing_category (
            listing_id      bigint PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
            -- mieszkaniowa | uslugowa | przemyslowa | lesna, NULL = nierozpoznany
            rodzaj          text,
            -- plan_ogolny | ogloszenie: skad wiemy, zeby dalo sie to pokazac
            rodzaj_zrodlo   text,
            teryt_gmina     text,
            -- dzialka | rcn: z dopasowanej dzialki czy z najblizszej transakcji
            gmina_zrodlo    text,
            computed_at     timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT listing_category_rodzaj CHECK (
                rodzaj IS NULL
                OR rodzaj IN ('mieszkaniowa', 'uslugowa', 'przemyslowa', 'lesna')
            ),
            CONSTRAINT listing_category_rodzaj_zrodlo CHECK (
                (rodzaj IS NULL) = (rodzaj_zrodlo IS NULL)
            ),
            CONSTRAINT listing_category_gmina CHECK (
                teryt_gmina IS NULL OR length(teryt_gmina) = 7
            )
        );

        CREATE INDEX listing_category_rodzaj_idx ON listing_category (rodzaj);
        CREATE INDEX listing_category_gmina_idx ON listing_category (teryt_gmina);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS listing_category;")
