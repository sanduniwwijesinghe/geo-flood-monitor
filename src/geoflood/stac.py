"""Scene discovery against the Microsoft Planetary Computer STAC API."""

from __future__ import annotations

import logging
from datetime import date, timedelta

import planetary_computer
import pystac
from pystac_client import Client

log = logging.getLogger(__name__)

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"


def open_catalog(url: str = STAC_URL) -> Client:
    # sign_inplace attaches short-lived SAS tokens so assets can be read directly
    return Client.open(url, modifier=planetary_computer.sign_inplace)


def _search(
    catalog: Client,
    bbox: list[float],
    start: date,
    end: date,
    max_cloud: float,
    mgrs_tile: str | None = None,
) -> list[pystac.Item]:
    query: dict = {"eo:cloud_cover": {"lt": max_cloud}}
    if mgrs_tile:
        query["s2:mgrs_tile"] = {"eq": mgrs_tile}
    search = catalog.search(
        collections=[COLLECTION],
        bbox=bbox,
        datetime=f"{start.isoformat()}/{end.isoformat()}",
        query=query,
    )
    items = list(search.items())
    log.info("STAC search %s..%s tile=%s -> %d items", start, end, mgrs_tile, len(items))
    return items


def find_event_scene(
    catalog: Client, bbox: list[float], on_or_before: date, lookback_days: int, max_cloud: float
) -> pystac.Item | None:
    """Most recent scene within the lookback window (ties broken by lower cloud cover)."""
    items = _search(
        catalog, bbox, on_or_before - timedelta(days=lookback_days), on_or_before, max_cloud
    )
    if not items:
        return None
    return sorted(items, key=lambda i: (i.datetime, -i.properties["eo:cloud_cover"]))[-1]


def find_baseline_scene(
    catalog: Client,
    bbox: list[float],
    mgrs_tile: str,
    start: date,
    end: date,
    max_cloud: float,
) -> pystac.Item | None:
    """Clearest dry-season scene on the *same MGRS tile* so pixel grids line up."""
    items = _search(catalog, bbox, start, end, max_cloud, mgrs_tile=mgrs_tile)
    if not items:
        return None
    return min(items, key=lambda i: i.properties["eo:cloud_cover"])
