"""Harmonogram zadan: znacznik zakonczenia, wynik i indeks kolejki.

Tabela jobs z sekcji 16 wiedziala, kiedy zadanie ma sie uruchomic, ale nie
wiedziala, kiedy sie skonczylo. Bez finished_at harmonogram nie ma jak
odpowiedziec na pytanie "czy minelo 6 godzin od ostatniego udanego przebiegu",
a to jedyne pytanie, ktore scheduler zadaje.

Kolumna wynik trzyma statystyki przebiegu (ile ofert, ile bledow). Dzieki temu
"co robil system w nocy" czyta sie z bazy, a nie z logu terminala, ktory po
zamknieciu okna przestaje istniec.

Revision ID: 009
Revises: 008
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE jobs
            ADD COLUMN IF NOT EXISTS finished_at timestamptz,
            ADD COLUMN IF NOT EXISTS wynik jsonb;

        -- Zapytanie workera: pierwsze gotowe zadanie wedlug run_after.
        CREATE INDEX IF NOT EXISTS jobs_kolejka_idx ON jobs (run_after, id)
            WHERE status = 'pending';

        -- Zapytanie harmonogramu: ostatnie udane uruchomienie per rodzaj.
        CREATE INDEX IF NOT EXISTS jobs_ostatnie_udane_idx ON jobs (kind, finished_at DESC)
            WHERE status = 'done';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS jobs_ostatnie_udane_idx;
        DROP INDEX IF EXISTS jobs_kolejka_idx;
        ALTER TABLE jobs DROP COLUMN IF EXISTS wynik;
        ALTER TABLE jobs DROP COLUMN IF EXISTS finished_at;
        """
    )
