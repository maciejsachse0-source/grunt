"""FastAPI: punkt wejscia aplikacji."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from grunt.api.auth import wymagaj_tokenu
from grunt.api.routers import (
    harmonogram,
    health,
    listings,
    market,
    metodologia,
    saved,
    valuate,
)
from grunt.config import settings

app = FastAPI(
    title="GRUNT API",
    version="0.1.0",
    description="Wyszukiwanie i ocena potencjalu dzialek",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# Lokalnie frontend chodzi na localhost:3000, API na localhost:8000. Po
# wdrozeniu lista pochodzi z API_CORS_ORIGINS, bo domena z Vercela nie jest
# znana w momencie pisania kodu.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_cors_origins,
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
# Jedyny router z danymi uzytkownika, wiec jedyny za tokenem. Reszta to
# oferty i liczby, ktore i tak pochodza z publicznych zrodel.
app.include_router(
    saved.router,
    prefix="/api",
    tags=["ulubione"],
    dependencies=[Depends(wymagaj_tokenu)],
)
app.include_router(market.router, prefix="/api", tags=["ceny w regionach"])
app.include_router(metodologia.router, prefix="/api", tags=["metodologia"])
app.include_router(harmonogram.router, prefix="/api", tags=["harmonogram"])
