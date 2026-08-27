"""Score liczony dla oferty, nie tylko dla dzialki ewidencyjnej.

Sekcja 16 dokumentu kluczuje tabele scores po parcel_id, zakladajac, ze kazda
oferta zostanie pewnie zwiazana z dzialka. Pomiar to podwazyl: wspolrzedne
z portali sa przyblizone, a w promieniu 150 m potrafi lezec kilkanascie dzialek
o zgodnej powierzchni (szczegoly w enrich/match_parcel.py).

Wiekszosc cech i tak liczymy dla punktu oferty, wiec to oferta jest jednostka,
ktora punktujemy. parcel_id zostaje, ale jako pole opcjonalne: wypelnia sie
wtedy, gdy dopasowanie ma pewnosc high albo medium.

Tabela jest pusta, wiec przebudowujemy ja wprost.

Revision ID: 007
Revises: 006
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS scores;

        CREATE TABLE scores (
            listing_id    bigint PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
            parcel_id     bigint REFERENCES parcels(id) ON DELETE SET NULL,
            score_total   numeric(5,2),
            pillar_scores jsonb NOT NULL,
            gates         jsonb NOT NULL,
            coverage      numeric(4,3) NOT NULL,
            deal_score    numeric(6,3),
            red_flags     jsonb,
            model_version text,
            computed_at   timestamptz NOT NULL DEFAULT now()
        );

        -- ranking pokazuje wylacznie wyniki o wystarczajacej kompletnosci
        CREATE INDEX scores_rank_idx ON scores (score_total DESC, deal_score DESC)
            WHERE coverage >= 0.4 AND score_total IS NOT NULL;
        CREATE INDEX scores_deal_idx ON scores (deal_score DESC)
            WHERE deal_score IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS scores;

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
        """
    )
