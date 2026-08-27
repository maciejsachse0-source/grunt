"""Cache odpowiedzi ULDK.

ULDK odpowiada w ok. 0,8 s i jest jedynym mostem miedzy wspolrzedna z ogloszenia
a numerem dzialki ewidencyjnej, wiec kazde zapytanie zapisujemy. Cache trzyma
takze odpowiedzi negatywne (found=false), zeby nie pytac drugi raz o punkt
poza granicami ewidencji.

Revision ID: 002
Revises: 001
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE uldk_cache (
            id          bigserial PRIMARY KEY,
            query_kind  varchar(16) NOT NULL,   -- xy | id
            query_key   text        NOT NULL,
            uldk_id     text,
            payload     jsonb,
            geom        geometry(MultiPolygon, 2180),
            found       boolean NOT NULL DEFAULT true,
            fetched_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX uldk_cache_query_idx ON uldk_cache (query_kind, query_key);
        CREATE INDEX uldk_cache_geom_idx ON uldk_cache USING gist (geom);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS uldk_cache;")
