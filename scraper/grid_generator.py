"""Spatial grid generator reading bounding boxes from config/targets.py."""

from __future__ import annotations

import math
from dataclasses import dataclass

from config.targets import get_bounding_box, get_named_localities


@dataclass(frozen=True)
class GridCell:
    row: int
    col: int
    lat: float
    lon: float
    label: str


def generate_grid(bbox: dict[str, float] | None = None) -> list[GridCell]:
    """Generate centroid coordinates for a bounding-box grid."""
    bbox = bbox or get_bounding_box()
    lat_min = bbox["lat_min"]
    lat_max = bbox["lat_max"]
    lon_min = bbox["lon_min"]
    lon_max = bbox["lon_max"]
    step = bbox["step"]

    cells: list[GridCell] = []
    row = 0
    lat = lat_min + step / 2
    while lat <= lat_max:
        col = 0
        lon = lon_min + step / 2
        while lon <= lon_max:
            cells.append(
                GridCell(
                    row=row,
                    col=col,
                    lat=round(lat, 6),
                    lon=round(lon, 6),
                    label=f"grid_{row}_{col}",
                )
            )
            col += 1
            lon += step
        row += 1
        lat += step
    return cells


def generate_search_targets() -> list[dict[str, str | float]]:
    """Combine named localities and grid centroids into unified search targets."""
    targets: list[dict[str, str | float]] = []

    for name, (lat, lon) in get_named_localities().items():
        targets.append(
            {
                "type": "locality",
                "name": name,
                "lat": lat,
                "lon": lon,
                "query": f"Restaurants in {name} Hyderabad",
            }
        )

    for cell in generate_grid():
        targets.append(
            {
                "type": "grid",
                "name": cell.label,
                "lat": cell.lat,
                "lon": cell.lon,
                "query": f"Restaurants near {cell.lat},{cell.lon}",
            }
        )

    return targets


def cell_count(bbox: dict[str, float] | None = None) -> int:
    return len(generate_grid(bbox))


def centroid(bbox: dict[str, float] | None = None) -> tuple[float, float]:
    bbox = bbox or get_bounding_box()
    lat = (bbox["lat_min"] + bbox["lat_max"]) / 2
    lon = (bbox["lon_min"] + bbox["lon_max"]) / 2
    return round(lat, 6), round(lon, 6)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
