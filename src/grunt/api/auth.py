"""Jeden token na dane uzytkownika.

CLAUDE.md mowi: jeden uzytkownik, zero logowania. Na localhoscie to koniec
tematu. Publiczny adres zmienia dokladnie jedna rzecz: ulubione, notatki, oceny
i zapisane filtry przestaja byc osiagalne wylacznie z tego komputera. Stad
naglowek X-Grunt-Token sprawdzany przy calym routerze `saved`.

CZEGO TEN TOKEN NIE ROBI

Frontend jest statyczny, wiec token dociera do przegladarki i zobaczy go kazdy,
kto otworzy narzedzia deweloperskie. To zapora na roboty i przypadkowe wejscia,
nie na czlowieka, ktoremu zalezy. Prawdziwy zamek to Deployment Protection po
stronie Vercela albo przepuszczenie API przez wlasny endpoint Next.js, gdzie
sekret nie opuszcza serwera. README opisuje oba warianty.

Pusty API_WRITE_TOKEN znaczy brak kontroli. Tak chodzi srodowisko lokalne
i tak chodza testy.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from grunt.config import settings

NAGLOWEK = "X-Grunt-Token"


def wymagaj_tokenu(x_grunt_token: str | None = Header(default=None)) -> None:
    """Zaleznosc FastAPI. Bez skonfigurowanego tokenu przepuszcza wszystko."""
    oczekiwany = settings.api_write_token
    if not oczekiwany:
        return
    if x_grunt_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"brak naglowka {NAGLOWEK}",
        )
    # compare_digest, a nie ==, zeby czas porownania nie zdradzal prefiksu.
    if not hmac.compare_digest(x_grunt_token, oczekiwany):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="niepoprawny token",
        )
