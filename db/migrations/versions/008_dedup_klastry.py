"""Deduplikacja cross-portal: pary duplikatow i indeks klastra.

Kolumna listings.cluster_id i jej indeks istnieja od migracji 001 (sekcja 16),
ale nigdzie nie bylo zapisane, skad klaster sie bierze. Tabela
listing_duplicates trzyma pary wraz z powodem: bez niej klaster jest decyzja
bez sladu, ktorej nie da sie przejrzec ani zestroic. Sekcja 4.3 wymaga wprost recznie oznakowanego zbioru par
i mierzenia precyzji po kazdej zmianie progow, a to wymaga historii par.

Revision ID: 008
Revises: 007
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE listing_duplicates (
            listing_a   bigint NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            listing_b   bigint NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            pewnosc     numeric(4,3) NOT NULL,
            etap        text NOT NULL,
            w_klastrze  boolean NOT NULL DEFAULT false,
            powody      jsonb NOT NULL DEFAULT '[]'::jsonb,
            -- werdykt czlowieka: NULL = nieprzejrzane, true/false = zbior oznakowany
            potwierdzone boolean,
            computed_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (listing_a, listing_b),
            CONSTRAINT listing_duplicates_kolejnosc CHECK (listing_a < listing_b)
        );

        CREATE INDEX listing_duplicates_pewnosc_idx ON listing_duplicates (pewnosc DESC);
        CREATE INDEX listing_duplicates_b_idx ON listing_duplicates (listing_b);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS listing_duplicates;
        """
    )
