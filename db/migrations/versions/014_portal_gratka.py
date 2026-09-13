"""Gratka jako dopuszczalna wartosc enuma portal_t.

Enum portal_t powstal w migracji 001 z szescioma wartosciami: morizon,
nieruchomosci_online, domiporta, gruntguru, otodom, olx. Adapter Gratki powstal
2026-08-25 i nazwy "gratka" w tej liscie nie ma, wiec pierwszy przebieg
scrapera konczyl sie bledem bazy:

    invalid input value for enum portal_t: "gratka"

Dlaczego osobna migracja, a nie poprawka w 001: 001 juz sie wykonala i CLAUDE.md
zabrania edytowania wykonanych migracji. Poza tym historia ma pokazywac, KIEDY
portal doszedl, bo to samo pytanie zada sobie kazdy, kto bedzie patrzyl na daty
pierwszego widzenia ofert.

ADD VALUE nie da sie cofnac zwyklym poleceniem: PostgreSQL nie ma DROP VALUE dla
enuma. Downgrade przepisuje wiec typ od nowa i celowo przewraca sie, gdy w bazie
sa juz oferty z Gratki. Cichy downgrade, ktory kasuje wiersze, bylby gorszy niz
blad: strata danych nie moze byc skutkiem ubocznym cofniecia migracji.

Revision ID: 014
Revises: 013
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS, zeby migracja byla idempotentna takze na bazie, w ktorej
    # ktos dopisal wartosc recznie zanim ta migracja powstala.
    op.execute("ALTER TYPE portal_t ADD VALUE IF NOT EXISTS 'gratka'")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM listings WHERE portal = 'gratka') THEN
                RAISE EXCEPTION
                    'W bazie sa oferty z Gratki. Cofniecie tej migracji '
                    'skasowaloby je, wiec najpierw usun je swiadomie.';
            END IF;
        END $$;

        ALTER TYPE portal_t RENAME TO portal_t_stary;

        CREATE TYPE portal_t AS ENUM (
            'morizon', 'nieruchomosci_online', 'domiporta',
            'gruntguru', 'otodom', 'olx'
        );

        ALTER TABLE listings
            ALTER COLUMN portal TYPE portal_t
            USING portal::text::portal_t;

        DROP TYPE portal_t_stary;
        """
    )
