"""FastAPI: punkt wejscia aplikacji."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from grunt.api.routers import (
    harmonogram,
    health,
    listings,
    market,
    metodologia,
    saved,
    valuate,
)

app = FastAPI(
    title="GRUNT API",
    version="0.1.0",
    description="Wyszukiwanie i ocena potencjalu dzialek",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# Frontend chodzi na localhost:3000, API na localhost:8000.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Do czasu powstania frontendu (faza 4) korzeniem aplikacji jest dokumentacja API."""
    return RedirectResponse(url="/api/docs")


app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(valuate.router, prefix="/api", tags=["valuation"])
app.include_router(listings.router, prefix="/api", tags=["listings"])
app.include_router(saved.router, prefix="/api", tags=["ulubione"])
app.include_router(market.router, prefix="/api", tags=["ceny w regionach"])
app.include_router(metodologia.router, prefix="/api", tags=["metodologia"])
app.include_router(harmonogram.router, prefix="/api", tags=["harmonogram"])
