"""Jedyne miejsce w projekcie, ktore czyta srodowisko.

Zasada z CLAUDE.md: zadnego klucza w kodzie, zadnej sciezki absolutnej.
Wszystkie sciezki sa wzgledne do katalogu repozytorium (REPO_ROOT).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- baza ---
    database_url: str = "postgresql+psycopg://grunt:grunt@localhost:5433/grunt"

    # --- zakres pracy ---
    region_teryt: str = "22"
    # NoDecode: listy podajemy jako CSV, nie jako JSON. Dekoduje _split_csv nizej.
    region_powiaty: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- scraping ---
    scraper_user_agent: str = "GRUNT/0.1 (prywatne narzedzie analityczne)"
    scraper_delay_seconds: float = 2.0
    scraper_max_pages_per_run: int = 50
    portals_enabled: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Apify (opcjonalnie) ---
    apify_token: str | None = None
    apify_otodom_actor: str = "trev0n/otodom-scraper"
    apify_max_items_per_run: int = 300

    # --- alerty ---
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # --- uslugi lokalne ---
    valhalla_url: str = "http://localhost:8002"
    nominatim_url: str = "https://nominatim.openstreetmap.org"

    # --- dane ---
    data_dir: Path = Path("./data")

    # --- scoring ---
    scoring_model_version: str = "v1"
    area_ref_m2: int = 1000
    coverage_min: float = 0.40

    @field_validator("region_powiaty", "portals_enabled", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """Listy podajemy w .env jako wartosci rozdzielone przecinkiem."""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("apify_token", "telegram_bot_token", "telegram_chat_id", mode="before")
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @property
    def data_path(self) -> Path:
        """DATA_DIR rozwiniete do sciezki bezwzglednej wzgledem repo."""
        p = self.data_dir
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    def data_subdir(self, *parts: str) -> Path:
        p = self.data_path.joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
