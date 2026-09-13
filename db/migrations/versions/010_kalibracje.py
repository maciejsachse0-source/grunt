"""Wyniki kalibracji: spread oferta-transakcja, elastycznosc b1, wrazliwosc wag.

Sekcja 5.6 wymaga, zeby kalibracja byla powtarzalnym pomiarem, a nie stala
wpisana do kodu. Tabela trzyma kolejne pomiary z data, liczba obserwacji
i zrodlem, wiec widac nie tylko biezaca wartosc, ale i to, jak sie zmieniala
w miare przybywania danych. Stara wartosc nigdy nie jest nadpisywana: to
historia pomiarow, a nie stan.

Kluczowe jest pole zrodlo. "oferty_vs_model" to szacunek zastepczy, liczony
na roznicy miedzy cena ofertowa a wycena modelu. "pary" to wlasciwy pomiar
z sekcji 5.6, mozliwy dopiero wtedy, gdy oferta zniknie z portalu, a jej
dzialka pojawi sie w RCN. Te dwie liczby nie znacza tego samego i nie wolno
ich mieszac.

Revision ID: 010
Revises: 009
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE calibrations (
            id           bigserial PRIMARY KEY,
            -- spread | beta1 | wagi | dyskryminacja
            kind         text NOT NULL,
            -- segment rynku albo profil inwestora; NULL = pomiar globalny
            segment      text,
            wartosc      numeric(12,4),
            n_obs        integer,
            zrodlo       text NOT NULL,
            szczegoly    jsonb NOT NULL DEFAULT '{}'::jsonb,
            computed_at  timestamptz NOT NULL DEFAULT now()
        );

        CREATE INDEX calibrations_aktualne_idx
            ON calibrations (kind, segment, computed_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS calibrations;")
