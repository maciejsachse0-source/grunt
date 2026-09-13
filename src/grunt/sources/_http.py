"""Wspolny klient HTTP dla uslug publicznych (GUGiK, ISOK, GUS, PGI).

Uczciwy User-Agent z kontaktem, throttling per domena, retry z backoffem.
Portale ofertowe maja wlasna sciezke (curl-cffi w portals/), bo tam liczy sie
kompatybilnosc TLS, a nie kultura odpytywania administracji.
"""

from __future__ import annotations

import importlib.util
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from grunt.config import settings

_last_request: dict[str, float] = {}
_lock = threading.Lock()


def _supported_encodings() -> str:
    """Deklarujemy wylacznie to, co potrafimy rozpakowac.

    Dokument kaze wysylac "Accept-Encoding: br, gzip" i ma racje - brotli tnie
    transfer dziesieciokrotnie. Ale gdy biblioteki brotli zabraknie, httpx nie
    zglasza bledu, tylko oddaje nierozpakowane bajty, ktore wygladaja jak tekst.
    Parser dostaje wtedy smieci i wyglada to na blokade portalu. Naglowek
    skladamy wiec z faktycznie dostepnych kodekow.
    """
    encodings = []
    if importlib.util.find_spec("brotli") or importlib.util.find_spec("brotlicffi"):
        encodings.append("br")
    if importlib.util.find_spec("zstandard"):
        encodings.append("zstd")
    encodings.extend(["gzip", "deflate"])
    return ", ".join(encodings)


ACCEPT_ENCODING = _supported_encodings()


def _throttle(url: str, delay: float) -> None:
    """Minimalny odstep miedzy zadaniami do tej samej domeny."""
    host = urlsplit(url).netloc
    with _lock:
        previous = _last_request.get(host)
        now = time.monotonic()
        if previous is not None:
            wait = delay - (now - previous)
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
        _last_request[host] = now


class PublicServiceError(RuntimeError):
    """Usluga publiczna odpowiedziala, ale nie tym, czego oczekiwalismy."""


@retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def get(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = 30.0,
    delay: float | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    _throttle(url, settings.scraper_delay_seconds if delay is None else delay)
    base_headers = {
        "User-Agent": settings.scraper_user_agent,
        "Accept-Encoding": ACCEPT_ENCODING,
    }
    if headers:
        base_headers.update(headers)
    response = httpx.get(
        url,
        params=params,
        timeout=timeout,
        headers=base_headers,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response


def download(url: str, dest: Any, *, timeout: float = 300.0, delay: float | None = None) -> Any:
    """Pobranie duzego pliku strumieniowo (paczki RCN, ekstrakty OSM)."""
    from pathlib import Path

    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    _throttle(url, settings.scraper_delay_seconds if delay is None else delay)
    tmp = path.with_suffix(path.suffix + ".part")
    with httpx.stream(
        "GET",
        url,
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": settings.scraper_user_agent},
    ) as response:
        response.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in response.iter_bytes(chunk_size=1 << 20):
                fh.write(chunk)
    tmp.replace(path)
    return path
