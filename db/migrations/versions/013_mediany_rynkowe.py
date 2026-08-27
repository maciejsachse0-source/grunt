"""Mediany cen per obszar i segment, nazwy TERYT, przypisanie oferty do rynku.

Sekcja 7.1 wymaga na liscie "percentylu w rynku lokalnym z widoczna liczba
obserwacji". Do tej pory system liczyl mediany hierarchiczne w srodku modelu
wyceny i nigdzie ich nie pokazywal, wiec uzytkownik widzial deal score, ale nie
widzial, wobec czego jest liczony.

TRZY TABELE, TRZY ROZNE POWODY

* market_medians: agregat po RCN, jeden wiersz na (poziom, teryt, segment).
  Liczenie mediany z 137 tys. transakcji przy kazdym otwarciu listy byloby
  absurdem, a te liczby zmieniaja sie raz na tydzien, gdy dojdzie nowa paczka.
* teryt_names: "2204042" nic nie znaczy dla czlowieka. Nazwy pochodza z ULDK,
  ktory przy okazji zapytania o dzialke zwraca nazwe gminy i powiatu. Pobieramy
  je raz i trzymamy, zeby nie odpytywac uslugi o to samo.
* listing_market: mediana odpowiednia dla konkretnej oferty (jej gmina, jej
  segment) razem z gotowym odchyleniem. Bez tego kolumna "wzgledem mediany"
  wymagalaby podzapytania przestrzennego na kazdy wiersz listy.

Ceny sa trzymane W POSTACI ZNORMALIZOWANEJ do dzialki 1000 m2, bo tylko takie
wolno porownywac (sekcja 5.2.1). Surowa mediana zostaje obok, do pokazania
w interfejsie, ale nie do liczenia odchylen.

Revision ID: 013
Revises: 012
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market_medians (
            poziom          text NOT NULL,
            teryt           text NOT NULL,
            segment         text NOT NULL,
            n               integer NOT NULL,
            -- ceny za m2 sprowadzone do dzialki 1000 m2 i zindeksowane na dzis
            mediana_norm    numeric(10,2) NOT NULL,
            p25_norm        numeric(10,2) NOT NULL,
            p75_norm        numeric(10,2) NOT NULL,
            -- mediana surowa: do pokazania, nigdy do porownywania ofert
            mediana_surowa  numeric(10,2) NOT NULL,
            okres_od        date NOT NULL,
            okres_do        date NOT NULL,
            computed_at     timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (poziom, teryt, segment),
            CONSTRAINT market_medians_poziom
                CHECK (poziom IN ('gmina', 'powiat', 'wojewodztwo'))
        );

        CREATE INDEX market_medians_segment_idx ON market_medians (segment, poziom, n DESC);

        CREATE TABLE teryt_names (
            teryt       text PRIMARY KEY,
            poziom      text NOT NULL,
            nazwa       text NOT NULL,
            powiat      text,
            zrodlo      text NOT NULL DEFAULT 'uldk',
            fetched_at  timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE listing_market (
            listing_id      bigint PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
            teryt_gmina     text,
            segment         text NOT NULL,
            -- poziom, z ktorego pochodzi mediana: gmina, powiat albo wojewodztwo
            poziom          text NOT NULL,
            teryt_mediany   text NOT NULL,
            mediana_norm    numeric(10,2) NOT NULL,
            n               integer NOT NULL,
            cena_norm       numeric(10,2) NOT NULL,
            -- 0,18 znaczy: oferta o 18% drozsza od mediany swojego rynku
            odchylenie      numeric(6,3) NOT NULL,
            computed_at     timestamptz NOT NULL DEFAULT now()
        );

        CREATE INDEX listing_market_odchylenie_idx ON listing_market (odchylenie);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS listing_market;
        DROP TABLE IF EXISTS teryt_names;
        DROP TABLE IF EXISTS market_medians;
        """
    )
