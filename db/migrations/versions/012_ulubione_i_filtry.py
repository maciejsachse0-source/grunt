"""Ulubione, notatki i zapisane filtry: klucz po ofercie, nie po dzialce.

Sekcja 16 kluczuje saved_parcels i feedback po parcel_id, zakladajac, ze kazda
oferta zostanie pewnie zwiazana z dzialka ewidencyjna. Migracja 007 podwazyla
to zalozenie dla tabeli scores i te same argumenty obowiazuja tutaj: pewne
dopasowanie do dzialki mamy dla czesci ofert, a zapisac do obserwowanych chce
sie ogloszenie, ktore sie wlasnie oglada. Uzytkownik zapisuje oferte, nie
parcele.

Obie tabele sa puste, wiec przebudowujemy je wprost, tak jak migracja 007.

Uzytkownik jest jeden (CLAUDE.md: "ten projekt ma jednego uzytkownika"), wiec
zamiast logowania jest jeden wiersz w users i staly identyfikator w API. Kolumna
user_id zostaje, zeby dolozenie drugiej osoby nie wymagalo migracji danych.

Revision ID: 012
Revises: 011
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Adres jest wylacznie kluczem lokalnego uzytkownika, nie danymi kontaktowymi
# ogloszeniodawcy. Zakaz z sekcji 8.2 dotyczy tych drugich.
DOMYSLNY_UZYTKOWNIK = "lokalny@grunt"


def upgrade() -> None:
    op.execute(
        f"""
        DROP TABLE IF EXISTS saved_parcels;
        DROP TABLE IF EXISTS feedback;

        CREATE TABLE saved_listings (
            user_id     bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            listing_id  bigint NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            -- nowa | obserwuje | kontakt | odrzucona | kupiona
            status      text NOT NULL DEFAULT 'obserwuje',
            tags        text[],
            note        text,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, listing_id)
        );

        CREATE INDEX saved_listings_status_idx ON saved_listings (user_id, status);

        CREATE TABLE feedback (
            user_id     bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            listing_id  bigint NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            verdict     smallint NOT NULL CHECK (verdict IN (-1, 0, 1)),
            created_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, listing_id, created_at)
        );

        -- Alert wysylamy raz na oferte i raz na filtr. Bez tej tabeli restart
        -- workera albo zmiana progu oznaczalyby powtorke wszystkich alertow.
        CREATE TABLE alert_log (
            filter_id   bigint NOT NULL REFERENCES saved_filters(id) ON DELETE CASCADE,
            listing_id  bigint NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            sent_at     timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (filter_id, listing_id)
        );

        INSERT INTO users (email) VALUES ('{DOMYSLNY_UZYTKOWNIK}')
        ON CONFLICT (email) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS alert_log;
        DROP TABLE IF EXISTS feedback;
        DROP TABLE IF EXISTS saved_listings;

        CREATE TABLE saved_parcels (
            user_id bigint REFERENCES users(id) ON DELETE CASCADE,
            parcel_id bigint REFERENCES parcels(id) ON DELETE CASCADE,
            tags text[], note text,
            status text,
            created_at timestamptz DEFAULT now(),
            PRIMARY KEY (user_id, parcel_id)
        );

        CREATE TABLE feedback (
            user_id bigint REFERENCES users(id) ON DELETE CASCADE,
            parcel_id bigint REFERENCES parcels(id) ON DELETE CASCADE,
            verdict smallint NOT NULL,
            created_at timestamptz DEFAULT now(),
            PRIMARY KEY (user_id, parcel_id, created_at)
        );
        """
    )
