"""Hierarchia TERYT wyliczana z numeru dzialki.

Model 1 (sekcja 5.2.2) potrzebuje shrinkage'u obreb -> gmina -> powiat ->
wojewodztwo. RCN podaje wprost tylko powiat, ale numer dzialki niesie cala reszte:

    226101_1.0089.433/2
    ^^^^^^ ^ ^^^^  ^^^^
    gmina  | obreb numer
           rodzaj gminy

Kolumny generowane zamiast obliczen w zapytaniu: dzieki temu da sie je zaindeksowac,
a mediana per obreb liczy sie ze skanu indeksu, nie z parsowania tekstu w kazdym wierszu.

Revision ID: 004
Revises: 003
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE rcn_transactions
            ADD COLUMN teryt_gmina char(7) GENERATED ALWAYS AS (
                CASE WHEN id_dzialki ~ '^[0-9]{6}_[0-9]'
                     THEN substr(replace(split_part(id_dzialki, '.', 1), '_', ''), 1, 7)
                END) STORED,
            ADD COLUMN teryt_obreb text GENERATED ALWAYS AS (
                CASE WHEN id_dzialki ~ '^[0-9]{6}_[0-9]\\.'
                     THEN split_part(id_dzialki, '.', 1) || '.' || split_part(id_dzialki, '.', 2)
                END) STORED;

        CREATE INDEX rcn_gmina_idx ON rcn_transactions (teryt_gmina, data_trans DESC);
        CREATE INDEX rcn_obreb_idx ON rcn_transactions (teryt_obreb, data_trans DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS rcn_obreb_idx;
        DROP INDEX IF EXISTS rcn_gmina_idx;
        ALTER TABLE rcn_transactions
            DROP COLUMN IF EXISTS teryt_obreb,
            DROP COLUMN IF EXISTS teryt_gmina;
        """
    )
