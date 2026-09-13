"""Silnik i sesja SQLAlchemy oraz drobne helpery PostGIS."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from grunt.config import settings

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _tryb_poolera(url: str) -> bool:
    """Czy adres wskazuje na pooler transakcyjny (Supabase, port 6543).

    DB_POOLER ustawione jawnie zawsze wygrywa. Bez niego zgadujemy z adresu,
    bo pomylka nie boli przy pierwszym zapytaniu, tylko przy drugim, i to
    komunikatem o juz istniejacym prepared statement. To godzina zastanawiania
    sie, dlaczego API dziala raz na dwa razy, w zamian za jedna linijke tutaj.
    """
    if settings.db_pooler is not None:
        return settings.db_pooler
    return ":6543/" in url or "pooler.supabase.com" in url


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = settings.database_url
        # Bez connect_timeout /api/health wisi, gdy baza jeszcze nie stoi,
        # zamiast zwrocic "degraded" w kilka sekund.
        connect_args: dict[str, Any] = {"connect_timeout": 3}
        if settings.db_search_path:
            # PostGIS poza schematem public (Supabase trzyma go w extensions)
            # jest niewidoczny dla geoalchemy2, dopoki nie ma go na sciezce.
            connect_args["options"] = f"-c search_path={settings.db_search_path}"
        if _tryb_poolera(url):
            # Pooler prowadzi wlasna pule. Druga pula w tym procesie tylko
            # okupowalaby jego polaczenia, a prepared statements nie przezywaja
            # przelaczenia sesji miedzy jednym zapytaniem a drugim.
            connect_args["prepare_threshold"] = None
            _engine = create_engine(url, future=True, poolclass=NullPool, connect_args=connect_args)
        else:
            _engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Sesja z commitem na wyjsciu i rollbackiem przy wyjatku."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """Zaleznosc dla FastAPI."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def ping() -> dict[str, str | bool]:
    """Sprawdzenie polaczenia i obecnosci PostGIS. Uzywane przez /api/health."""
    try:
        with get_engine().connect() as conn:
            postgis = conn.execute(text("SELECT postgis_version()")).scalar_one()
            version = conn.execute(text("SHOW server_version")).scalar_one()
        return {"ok": True, "postgres": str(version), "postgis": str(postgis)}
    except Exception as exc:  # baza moze jeszcze nie stac, to nie jest blad krytyczny
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
