"""Watchdog systemu. Sekcja 4.2 i 7.4 dokumentu.

Alert do administratora, gdy portal przestaje zwracac dane. Kluczowa mysl
z dokumentu: cisza po portalu NIE znaczy, ze rynek stanal, tylko ze zmienil sie
HTML albo ze nas zablokowano. Bez tego czujnika scraper moze przez tygodnie
"dzialac poprawnie", nie przynoszac niczego.

Sprawdzamy cztery rzeczy:
  1. portale, ktore od dwoch dni nie przyniosly zadnej nowej oferty
  2. portale wlaczone w konfiguracji, ktore nie maja ani jednej oferty w bazie
  3. oferty bez wspolrzednych, bo bez nich nie da sie ich wzbogacic
  4. wzbogacenia, ktore zwrocily bledy zrodel
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.config import settings
from grunt.portals import registry

DNI_CISZY = 2


@dataclass(frozen=True, slots=True)
class Problem:
    waga: str  # "alarm" albo "uwaga"
    kod: str
    opis: str
    szczegoly: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        znak = "‼" if self.waga == "alarm" else "•"
        return f"{znak} {self.opis}"


def check(session: Session, *, dni_ciszy: int = DNI_CISZY) -> list[Problem]:
    problemy: list[Problem] = []

    # 1. portale, ktore ucichly
    ciche = (
        session.execute(
            text(
                """
            SELECT portal::text AS portal,
                   max(first_seen_at)::date AS ostatnia_nowa,
                   count(*) AS ofert
            FROM listings
            GROUP BY portal
            HAVING max(first_seen_at) < now() - make_interval(days => :dni)
            """
            ),
            {"dni": dni_ciszy},
        )
        .mappings()
        .all()
    )
    for row in ciche:
        problemy.append(
            Problem(
                "alarm",
                "portal_milczy",
                f"{row['portal']}: zadnej nowej oferty od {row['ostatnia_nowa']}. "
                "Sprawdz, czy nie zmienil sie HTML albo czy nie zostalismy zablokowani",
                {"portal": row["portal"], "ofert_w_bazie": row["ofert"]},
            )
        )

    # 2. portale wlaczone, ale bez ani jednej oferty
    obecne = {
        r[0] for r in session.execute(text("SELECT DISTINCT portal::text FROM listings")).all()
    }
    for adapter in registry.enabled():
        if adapter.name not in obecne:
            problemy.append(
                Problem(
                    "uwaga",
                    "portal_bez_ofert",
                    f"{adapter.name}: wlaczony w konfiguracji, ale nie ma ani jednej oferty",
                )
            )

    for nazwa in registry.skipped():
        problemy.append(
            Problem(
                "uwaga",
                "portal_bez_adaptera",
                f"{nazwa}: wpisany w PORTALS_ENABLED, ale nie ma dla niego adaptera",
            )
        )

    # 3. oferty bez wspolrzednych
    bez_geom = (
        session.execute(
            text(
                """
            SELECT count(*) FILTER (WHERE geom IS NULL) AS bez,
                   count(*) AS wszystkie
            FROM listings WHERE is_active
            """
            )
        )
        .mappings()
        .one()
    )
    if bez_geom["wszystkie"] and bez_geom["bez"]:
        udzial = bez_geom["bez"] / bez_geom["wszystkie"]
        problemy.append(
            Problem(
                "alarm" if udzial > 0.5 else "uwaga",
                "brak_wspolrzednych",
                f"{bez_geom['bez']} z {bez_geom['wszystkie']} aktywnych ofert nie ma "
                "wspolrzednych, wiec nie da sie ich wzbogacic ani wycenic",
                {"udzial": round(udzial, 3)},
            )
        )

    # 4. bledy zrodel przy wzbogacaniu
    bledy = (
        session.execute(
            text(
                """
            SELECT unnest(zrodla_bledy) AS blad, count(*) AS ile
            FROM listing_enrichment
            WHERE zrodla_bledy IS NOT NULL AND array_length(zrodla_bledy, 1) > 0
            GROUP BY 1 ORDER BY 2 DESC LIMIT 3
            """
            )
        )
        .mappings()
        .all()
    )
    for row in bledy:
        problemy.append(
            Problem(
                "uwaga",
                "zrodlo_z_bledem",
                f"wzbogacanie zglosilo blad {row['ile']} razy: {str(row['blad'])[:90]}",
            )
        )

    return problemy


def raport(problemy: list[Problem]) -> str:
    if not problemy:
        return "GRUNT: wszystko dziala, brak uwag."
    alarmy = [p for p in problemy if p.waga == "alarm"]
    naglowek = (
        f"GRUNT: {len(alarmy)} alarm(ow), {len(problemy) - len(alarmy)} uwag."
        if alarmy
        else f"GRUNT: {len(problemy)} uwag."
    )
    return "\n".join([naglowek, *(str(p) for p in problemy)])


def powiadom(session: Session, *, dry_run: bool | None = None) -> dict[str, Any]:
    """Sprawdzenie i wyslanie raportu, gdy sa alarmy."""
    from grunt.alerts import telegram

    problemy = check(session)
    tresc = raport(problemy)
    alarmy = [p for p in problemy if p.waga == "alarm"]

    if not alarmy:
        return {"problemy": len(problemy), "alarmy": 0, "wyslane": False, "tresc": tresc}

    wynik = telegram.send_text(tresc, dry_run=dry_run)
    return {
        "problemy": len(problemy),
        "alarmy": len(alarmy),
        "wyslane": wynik.get("wyslane", False),
        "tresc": tresc,
        "skonfigurowany": telegram.skonfigurowany(),
        "region": settings.region_teryt,
    }
