"""Modele ORM. Odpowiadaja DDL z sekcji 16 dokumentu koncepcyjnego.

Wszystkie geometrie w EPSG:2180 (PUWG 1992): w tym ukladzie odleglosci licza sie
w metrach bez transformacji i w nim odpowiadaja uslugi GUGiK. Konwersja na 4326
nastepuje dopiero na wyjsciu API.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    ARRAY,
    CHAR,
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import BIT, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


PORTAL_ENUM = Enum(
    "morizon",
    "nieruchomosci_online",
    "domiporta",
    "gruntguru",
    "otodom",
    "olx",
    "gratka",
    name="portal_t",
    create_type=False,
)


# ============ DZIALKA: rekord kanoniczny ============
class Parcel(Base):
    __tablename__ = "parcels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    uldk_id: Mapped[str | None] = mapped_column(Text, unique=True)
    geom: Mapped[Any] = mapped_column(Geometry("MULTIPOLYGON", srid=2180), nullable=False)
    centroid: Mapped[Any] = mapped_column(
        Geometry("POINT", srid=2180), Computed("ST_Centroid(geom)", persisted=True)
    )
    area_ewid_m2: Mapped[int | None] = mapped_column(Integer)
    teryt_gmina: Mapped[str | None] = mapped_column(CHAR(7))
    teryt_obreb: Mapped[str | None] = mapped_column(Text)
    klasouzytek: Mapped[str | None] = mapped_column(Text)
    klasa_bonitacyjna: Mapped[str | None] = mapped_column(Text)
    sposob_uzytkowania: Mapped[str | None] = mapped_column(Text)
    # geometria wyliczana, sekcja 5.3.6
    front_m: Mapped[float | None] = mapped_column(Numeric(6, 1))
    smuklosc: Mapped[float | None] = mapped_column(Numeric(5, 2))
    zwartosc: Mapped[float | None] = mapped_column(Numeric(4, 3))
    azymut_osi: Mapped[int | None] = mapped_column(SmallInteger)
    spadek_proc: Mapped[float | None] = mapped_column(Numeric(5, 2))
    wysokosc_npm: Mapped[float | None] = mapped_column(Numeric(6, 1))
    road_access: Mapped[int | None] = mapped_column(SmallInteger)  # 0/1/2, sekcja 5.3.5
    enriched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ============ OFERTY ============
class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("portal", "portal_offer_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    parcel_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("parcels.id", ondelete="SET NULL")
    )
    cluster_id: Mapped[int | None] = mapped_column(BigInteger)  # grupa duplikatow
    portal: Mapped[str] = mapped_column(PORTAL_ENUM, nullable=False)
    portal_offer_id: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)  # tylko tytul, NIE pelny opis
    price_grosze: Mapped[int | None] = mapped_column(BigInteger)
    area_m2: Mapped[int | None] = mapped_column(Integer)
    price_per_m2: Mapped[float | None] = mapped_column(
        Numeric(10, 2),
        Computed("CASE WHEN area_m2 > 0 THEN price_grosze/100.0/area_m2 END", persisted=True),
    )
    price_per_m2_norm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    geom: Mapped[Any | None] = mapped_column(Geometry("POINT", srid=2180))
    geom_precision: Mapped[str | None] = mapped_column(Text)  # exact | approx | geocoded
    przeznaczenie_raw: Mapped[str | None] = mapped_column(Text)
    media_raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    phone_sha256: Mapped[str | None] = mapped_column(CHAR(64))  # WYLACZNIE hash, sekcja 8.2
    thumb_url: Mapped[str | None] = mapped_column(Text)
    thumb_phash: Mapped[Any | None] = mapped_column(BIT(64))
    first_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    content_hash: Mapped[str | None] = mapped_column(Text)
    raw_jsonb: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class PriceHistory(Base):
    __tablename__ = "price_history"

    listing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    price_grosze: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )


# ============ WARSTWY REFERENCYJNE ============
class RcnTransaction(Base):
    __tablename__ = "rcn_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    id_dzialki: Mapped[str | None] = mapped_column(Text)
    geom: Mapped[Any | None] = mapped_column(Geometry("MULTIPOLYGON", srid=2180))
    cena_grosze: Mapped[int | None] = mapped_column(BigInteger)
    data_trans: Mapped[dt.date] = mapped_column(Date, nullable=False)
    pow_m2: Mapped[int | None] = mapped_column(Integer)
    przeznaczenie: Mapped[str | None] = mapped_column(Text)
    sposob_uzyt: Mapped[str | None] = mapped_column(Text)
    rodzaj_rynku: Mapped[str | None] = mapped_column(Text)
    rodzaj_trans: Mapped[str | None] = mapped_column(Text)
    teryt_powiat: Mapped[str | None] = mapped_column(CHAR(4))
    source_file: Mapped[str | None] = mapped_column(Text)
    # migracja 003, pola wynikajace z realnego ksztaltu danych RCN
    iip_id: Mapped[str | None] = mapped_column(Text)
    pow_gruntu_m2: Mapped[int | None] = mapped_column(Integer)
    udzial: Mapped[str | None] = mapped_column(Text)
    nier_rodzaj: Mapped[str | None] = mapped_column(Text)
    cena_m2: Mapped[float | None] = mapped_column(
        Numeric(12, 2),
        Computed(
            "CASE WHEN pow_gruntu_m2 > 0 AND cena_grosze IS NOT NULL "
            "THEN cena_grosze / 100.0 / pow_gruntu_m2 END",
            persisted=True,
        ),
    )
    imported_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MpzpZone(Base):
    __tablename__ = "mpzp_zones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    geom: Mapped[Any] = mapped_column(Geometry("MULTIPOLYGON", srid=2180), nullable=False)
    symbol: Mapped[str | None] = mapped_column(Text)
    symbol_norm: Mapped[str | None] = mapped_column(Text)  # MN/MW/U/RM/ZL...
    intensywnosc: Mapped[float | None] = mapped_column(Numeric(4, 2))
    wysokosc_max: Mapped[float | None] = mapped_column(Numeric(5, 1))
    pbc_min: Mapped[float | None] = mapped_column(Numeric(4, 2))
    gmina: Mapped[str | None] = mapped_column(CHAR(7))
    plan_nazwa: Mapped[str | None] = mapped_column(Text)
    uchwala_data: Mapped[dt.date | None] = mapped_column(Date)
    source: Mapped[str | None] = mapped_column(Text)


class PlanOgolny(Base):
    __tablename__ = "plan_ogolny"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    geom: Mapped[Any] = mapped_column(Geometry("MULTIPOLYGON", srid=2180), nullable=False)
    # SW, SJ, SZ, SU, SH, SP, SR, SI, SN, SC, SG, SO, SK
    strefa: Mapped[str | None] = mapped_column(Text)
    is_ouz: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    gmina: Mapped[str | None] = mapped_column(CHAR(7))
    uchwala_data: Mapped[dt.date | None] = mapped_column(Date)


class FloodZone(Base):
    __tablename__ = "flood_zones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    geom: Mapped[Any] = mapped_column(Geometry("MULTIPOLYGON", srid=2180), nullable=False)
    scenariusz: Mapped[str] = mapped_column(Text, nullable=False)  # q10 | q1 | q0_2 | hWZ


class ProtectedArea(Base):
    __tablename__ = "protected_areas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    geom: Mapped[Any] = mapped_column(Geometry("MULTIPOLYGON", srid=2180), nullable=False)
    typ: Mapped[str | None] = mapped_column(Text)
    nazwa: Mapped[str | None] = mapped_column(Text)


class Utility(Base):
    __tablename__ = "utilities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    geom: Mapped[Any] = mapped_column(Geometry("LINESTRING", srid=2180), nullable=False)
    rodzaj: Mapped[str] = mapped_column(Text, nullable=False)  # prad | woda | gaz | kanalizacja


class PowerLine(Base):
    __tablename__ = "power_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    geom: Mapped[Any] = mapped_column(Geometry("LINESTRING", srid=2180), nullable=False)
    voltage_kv: Mapped[int | None] = mapped_column(Integer)


# ============ OCENY ============
class Valuation(Base):
    __tablename__ = "valuations"

    parcel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("parcels.id", ondelete="CASCADE"), primary_key=True
    )
    model_version: Mapped[str] = mapped_column(Text, primary_key=True)
    v_hat_grosze: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sigma_hat: Mapped[float | None] = mapped_column(Numeric(12, 2))
    ci_low: Mapped[int | None] = mapped_column(BigInteger)
    ci_high: Mapped[int | None] = mapped_column(BigInteger)
    # median_shrink | se_knn | hierarchical | residual_land
    method: Mapped[str | None] = mapped_column(Text)
    n_comparables: Mapped[int | None] = mapped_column(SmallInteger)
    comparables: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    computed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Score(Base):
    """Migracja 007: jednostka punktowana to OFERTA, nie dzialka ewidencyjna.

    Powod w enrich/match_parcel.py: wspolrzedne z portali nie identyfikuja
    dzialki, wiec wiekszosc cech liczymy dla punktu oferty.
    """

    __tablename__ = "scores"

    listing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    parcel_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("parcels.id", ondelete="SET NULL")
    )
    score_total: Mapped[float | None] = mapped_column(Numeric(5, 2))
    pillar_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    gates: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    coverage: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    deal_score: Mapped[float | None] = mapped_column(Numeric(6, 3))
    red_flags: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model_version: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ============ UZYTKOWNIK ============
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SavedListing(Base):
    """Migracja 012: jednostka zapisu to oferta, nie dzialka ewidencyjna."""

    __tablename__ = "saved_listings"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    listing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    note: Mapped[str | None] = mapped_column(Text)
    # nowa | obserwuje | kontakt | odrzucona | kupiona
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="obserwuje")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SavedFilter(Base):
    __tablename__ = "saved_filters"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    filter: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    alert_channel: Mapped[str | None] = mapped_column(Text)
    alert_enabled: Mapped[bool | None] = mapped_column(Boolean, server_default="false")
    last_alert_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class AlertLog(Base):
    """Co juz poszlo alertem. Bez tego restart workera powtarza wszystkie alerty."""

    __tablename__ = "alert_log"

    filter_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("saved_filters.id", ondelete="CASCADE"), primary_key=True
    )
    listing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    sent_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Feedback(Base):
    """Kciuk w gore albo w dol dla oferty. Material na proxy z sekcji 5.6."""

    __tablename__ = "feedback"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    listing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    verdict: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # -1 | 0 | 1
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )


# ============ KOLEJKA ZADAN ============
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    run_after: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    # statystyki przebiegu, zeby "co robil system w nocy" czytalo sie z bazy
    wynik: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ============ CACHE ULDK ============
class UldkCache(Base):
    """Odpowiedzi ULDK sa wolne (ok. 0,8 s) i stabilne. Cache jest w bazie, nie w pliku."""

    __tablename__ = "uldk_cache"
    __table_args__ = (Index("uldk_cache_query_idx", "query_kind", "query_key", unique=True),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    query_kind: Mapped[str] = mapped_column(String(16), nullable=False)  # xy | id
    query_key: Mapped[str] = mapped_column(Text, nullable=False)
    uldk_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    geom: Mapped[Any | None] = mapped_column(Geometry("MULTIPOLYGON", srid=2180))
    found: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
