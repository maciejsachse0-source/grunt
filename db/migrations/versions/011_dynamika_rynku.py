"""Filar 6: dynamika cen per obszar, liczona z wlasnych transakcji RCN.

Dynamika jest cecha obszaru, nie oferty, i liczy sie ja na calej bazie
transakcji. Trzymanie jej obok oferty oznaczaloby powtarzanie tego samego
rachunku dla kazdej dzialki w gminie, a przeliczanie jej przy kazdym scoringu
oznaczaloby jedno ciezkie zapytanie na oferte. Stad osobna tabela, odswiezana
raz na tydzien przez zadanie "rynek".

Klucz to para (poziom, teryt), bo ten sam kod TERYT ma inna dlugosc na kazdym
poziomie: 7 znakow gmina, 4 powiat, 2 wojewodztwo.

Revision ID: 011
Revises: 010
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market_dynamics (
            poziom       text NOT NULL,
            teryt        text NOT NULL,
            -- srednioroczna zmiana cen, wazona liczba transakcji w segmentach
            cagr         numeric(6,4) NOT NULL,
            n_obs        integer NOT NULL,
            rok_od       smallint NOT NULL,
            rok_do       smallint NOT NULL,
            -- dynamika osobno w kazdym segmencie rynku, zeby bylo widac,
            -- czy srednia nie stoi na jednym segmencie
            segmenty     jsonb NOT NULL DEFAULT '{}'::jsonb,
            computed_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (poziom, teryt),
            CONSTRAINT market_dynamics_poziom
                CHECK (poziom IN ('gmina', 'powiat', 'wojewodztwo'))
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market_dynamics;")
