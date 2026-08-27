"""Centroid transakcji RCN z indeksem GiST.

Model 2 (SE-KNN) dobiera porownywalne po odleglosci w metrach, nie po granicy
administracyjnej. Zapytanie "k najblizszych" opiera sie na operatorze <->,
ktory potrzebuje indeksu na punkcie, a nie na wielokacie: liczenie odleglosci
miedzy wielokatami jest kilkanascie razy drozsze i nic tu nie wnosi.

Powod merytoryczny: w rozbiciu bledu Modelu 1 MdAPE spada z 62% (ponizej 5
lokalnych transakcji) do 28% (ponad 20). Obreb ewidencyjny bywa duzy, wiec
"lokalny" w sensie administracyjnym potrafi znaczyc 6 km. Metr jest lepsza
miara sasiedztwa niz granica obrebu.

Revision ID: 005
Revises: 004
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE rcn_transactions
            ADD COLUMN centroid_2180 geometry(Point, 2180)
            GENERATED ALWAYS AS (ST_Centroid(geom)) STORED;

        CREATE INDEX rcn_centroid_idx ON rcn_transactions USING gist (centroid_2180);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS rcn_centroid_idx;
        ALTER TABLE rcn_transactions DROP COLUMN IF EXISTS centroid_2180;
        """
    )
