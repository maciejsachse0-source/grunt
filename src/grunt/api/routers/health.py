"""GET /api/health: stan bazy i konfiguracji. Docelowo takze stan przebiegow per portal."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from grunt import db
from grunt.config import settings

router = APIRouter()


@router.get("/health")
def health() -> dict[str, Any]:
    database = db.ping()
    return {
        "status": "ok" if database.get("ok") else "degraded",
        "version": "0.1.0",
        "region_teryt": settings.region_teryt,
        "model_version": settings.scoring_model_version,
        "database": database,
    }
