"""Silnik i sesja SQLAlchemy oraz drobne helpery PostGIS."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from grunt.config import settings

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            future=True,
            # Bez tego /api/health wisi, gdy baza jeszcze nie stoi, zamiast
            # zwrocic "degraded" w kilka sekund.
            connect_args={"connect_timeout": 3},
        )
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
