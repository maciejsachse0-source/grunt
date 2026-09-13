"""Import RCN do PostGIS: zasieg wojewodztwa, quadtree, zapis idempotentny.

Oddzielone od rcn.py celowo: rcn.py rozmawia z usluga i parsuje, ten modul
dotyka bazy. Dzieki temu parser da sie testowac bez Postgresa.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from grunt.config import REPO_ROOT, settings
from grunt.sources import geo, rcn

BBOX_SEED = REPO_ROOT / "db" / "seed" / "wojewodztwa_bbox.json"

INSERT_SQL = text(
    """
    INSERT INTO rcn_transactions (
        iip_id, id_dzialki, geom, cena_grosze, data_trans, pow_m2, pow_gruntu_m2,
        przeznaczenie, sposob_uzyt, rodzaj_rynku, rodzaj_trans, nier_rodzaj,
        udzial, teryt_powiat, source_file
    ) VALUES (
        :iip_id, :id_dzialki,
        -- CAST, a nie skladnia :param::text - ta druga rozjezdza sie z parserem
        -- parametrow w SQLAlchemy text() i parametr znika z zapytania
        ST_Multi(ST_GeomFromText(CAST(:geom_wkt AS text), 2180)),
        :cena_grosze, :data_trans, :pow_m2, :pow_gruntu_m2,
        :przeznaczenie, :sposob_uzyt, :rodzaj_rynku, :rodzaj_trans, :nier_rodzaj,
        :udzial, :teryt_powiat, :source_file
    )
    ON CONFLICT (iip_id, id_dzialki)
        WHERE iip_id IS NOT NULL AND id_dzialki IS NOT NULL
        DO NOTHING
    """
)


@dataclass
class ImportStats:
    fetched: int = 0
    skipped_no_date: int = 0
    skipped_out_of_region: int = 0
    inserted: int = 0
    usable: int = 0
    tiles: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "pobrane": self.fetched,
            "kafle": self.tiles,
            "pominiete_bez_daty": self.skipped_no_date,
            "pominiete_spoza_regionu": self.skipped_out_of_region,
            "zapisane": self.inserted,
            "nadaje_sie_do_modelu": self.usable,
        }


def region_bbox(teryt: str) -> geo.BBox2180:
    """Zasieg wojewodztwa jako punkt startowy quadtree."""
    data = json.loads(BBOX_SEED.read_text(encoding="utf-8"))
    entry = data.get(teryt)
    if entry is None:
        raise KeyError(f"brak zasiegu dla wojewodztwa {teryt} w {BBOX_SEED.name}")
    lat_min, lat_max = entry["lat"]
    lon_min, lon_max = entry["lon"]
    # Cztery rogi, bo prostokat w WGS84 nie jest prostokatem w EPSG:2180.
    corners = [
        geo.wgs84_to_pl1992(lat, lon) for lat in (lat_min, lat_max) for lon in (lon_min, lon_max)
    ]
    return geo.BBox2180(
        min_easting=min(c.easting for c in corners),
        min_northing=min(c.northing for c in corners),
        max_easting=max(c.easting for c in corners),
        max_northing=max(c.northing for c in corners),
    )


def store(
    session: Session,
    records: Iterable[rcn.RcnRecord],
    *,
    powiaty: set[str] | None = None,
    source_file: str = "wfs:rcn",
    batch_size: int = 500,
    stats: ImportStats | None = None,
) -> ImportStats:
    """Zapis wsadowy z pominieciem duplikatow po (iip_id, id_dzialki)."""
    stats = stats or ImportStats()
    batch: list[dict[str, object]] = []

    def flush() -> None:
        if not batch:
            return
        # rowcount jest na CursorResult, a Session.execute deklaruje Result.
        wstawione = session.execute(INSERT_SQL, batch).rowcount  # type: ignore[attr-defined]
        stats.inserted += wstawione if wstawione and wstawione > 0 else 0
        session.commit()
        batch.clear()

    for record in records:
        stats.fetched += 1
        if record.data_trans is None:
            stats.skipped_no_date += 1
            continue
        if powiaty and record.teryt_powiat not in powiaty:
            stats.skipped_out_of_region += 1
            continue
        if record.is_usable_for_model:
            stats.usable += 1

        batch.append(
            {
                "iip_id": record.iip_id,
                "id_dzialki": record.id_dzialki,
                "geom_wkt": record.geom_wkt,
                "cena_grosze": record.cena_grosze,
                "data_trans": record.data_trans,
                "pow_m2": record.pow_m2,
                "pow_gruntu_m2": record.pow_gruntu_m2,
                "przeznaczenie": record.przeznaczenie,
                "sposob_uzyt": record.sposob_uzyt,
                "rodzaj_rynku": record.rodzaj_rynku,
                "rodzaj_trans": record.rodzaj_trans,
                "nier_rodzaj": record.nier_rodzaj,
                "udzial": record.udzial,
                "teryt_powiat": record.teryt_powiat,
                "source_file": source_file,
            }
        )
        if len(batch) >= batch_size:
            flush()

    flush()
    return stats


def import_region(
    session: Session,
    *,
    teryt: str | None = None,
    powiaty: Iterable[str] | None = None,
    since: dt.date | None = None,
    delay: float = 0.6,
    bbox: geo.BBox2180 | None = None,
    progress: Callable[[str], None] | None = None,
) -> ImportStats:
    """Pelny import: quadtree po wojewodztwie, filtr powiatow, zapis wsadowy."""
    teryt = teryt or settings.region_teryt
    allowed = set(powiaty or settings.region_powiaty)
    area = bbox or region_bbox(teryt)
    stats = ImportStats()

    def on_tile(tile: geo.BBox2180, total: int) -> None:
        stats.tiles += 1
        if progress is not None and total:
            width_km = (tile.max_easting - tile.min_easting) / 1000
            progress(f"kafel {width_km:.1f} km: {total} rekordow")

    records: Iterator[rcn.RcnRecord] = rcn.iter_region(
        area, since=since, delay=delay, on_tile=on_tile
    )
    return store(session, records, powiaty=allowed or None, stats=stats)


def summary(session: Session) -> dict[str, object]:
    """Raport po imporcie: liczby, ktore decyduja o kryterium akceptacji fazy 0."""
    row = (
        session.execute(
            text(
                """
            SELECT count(*) AS wszystkie,
                   count(*) FILTER (WHERE cena_grosze IS NOT NULL) AS z_cena,
                   count(*) FILTER (WHERE cena_grosze IS NOT NULL
                                      AND pow_gruntu_m2 > 0
                                      AND udzial = '1/1'
                                      AND rodzaj_trans = 'wolnyRynek') AS do_modelu,
                   count(DISTINCT teryt_powiat) AS powiaty,
                   min(data_trans) AS od,
                   max(data_trans) AS do
            FROM rcn_transactions
            """
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


def data_dir() -> Path:
    return settings.data_subdir("rcn")
