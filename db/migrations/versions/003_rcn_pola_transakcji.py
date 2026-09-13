"""Pola transakcyjne RCN, ktorych nie ma w szkicu z sekcji 16.

Powod, sprawdzony na zywych danych z uslugi WFS:

1. iip_id (tran_lokalny_id_iip) - jedyny stabilny identyfikator transakcji.
   Bez niego ponowny import duplikuje rekordy, bo ta sama dzialka wraca
   z sasiednich kafli quadtree.
2. pow_gruntu_m2 (nier_pow_gruntu) - powierzchnia CALEJ transakcji. Cena
   nier_cena_brutto tez dotyczy calej transakcji, wiec cena za m2 musi byc
   liczona z tej pary, a nie z dzi_pow_ewid pojedynczej dzialki.
3. udzial (nier_udzial) - w RCN sa transakcje udzialow ulamkowych (widziano
   1/222 przy powierzchni 1 m2). Do modelu wchodzi wylacznie 1/1.
4. nier_rodzaj - zabudowana / niezabudowana / lokalowa. Model gruntowy uczy sie
   tylko na niezabudowanych.

Revision ID: 003
Revises: 002
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE rcn_transactions
            ADD COLUMN iip_id        text,
            ADD COLUMN pow_gruntu_m2 integer,
            ADD COLUMN udzial        text,
            ADD COLUMN nier_rodzaj   text,
            ADD COLUMN cena_m2       numeric(12,2) GENERATED ALWAYS AS (
                CASE WHEN pow_gruntu_m2 > 0 AND cena_grosze IS NOT NULL
                     THEN cena_grosze / 100.0 / pow_gruntu_m2 END) STORED,
            ADD COLUMN imported_at   timestamptz NOT NULL DEFAULT now();

        -- klucz idempotentnego importu
        CREATE UNIQUE INDEX rcn_iip_dzialka_idx
            ON rcn_transactions (iip_id, id_dzialki)
            WHERE iip_id IS NOT NULL AND id_dzialki IS NOT NULL;

        -- indeks pod zapytania modelu: transakcje nadajace sie do uczenia
        CREATE INDEX rcn_model_idx ON rcn_transactions (teryt_powiat, data_trans DESC)
            WHERE cena_grosze IS NOT NULL
              AND pow_gruntu_m2 > 0
              AND udzial = '1/1'
              AND rodzaj_trans = 'wolnyRynek';

        CREATE INDEX rcn_id_dzialki_idx ON rcn_transactions (id_dzialki);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS rcn_id_dzialki_idx;
        DROP INDEX IF EXISTS rcn_model_idx;
        DROP INDEX IF EXISTS rcn_iip_dzialka_idx;
        ALTER TABLE rcn_transactions
            DROP COLUMN IF EXISTS imported_at,
            DROP COLUMN IF EXISTS cena_m2,
            DROP COLUMN IF EXISTS nier_rodzaj,
            DROP COLUMN IF EXISTS udzial,
            DROP COLUMN IF EXISTS pow_gruntu_m2,
            DROP COLUMN IF EXISTS iip_id;
        """
    )
