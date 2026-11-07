"""Windowed reads of Sentinel-2 COG assets and COG output writing."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds
from rasterio.windows import bounds as window_bounds

from geoflood.indices import NODATA


@dataclass
class Grid:
    """The 10 m pixel grid covering the AOI inside one Sentinel-2 tile."""

    crs: rasterio.crs.CRS
    transform: rasterio.Affine
    bounds: tuple[float, float, float, float]  # in tile CRS
    height: int
    width: int


def aoi_grid(reference_href: str, bbox_wgs84: list[float]) -> Grid:
    """Build the output grid from a 10 m reference band (e.g. B03) and the AOI bbox."""
    with rasterio.open(reference_href) as src:
        utm_bounds = transform_bounds("EPSG:4326", src.crs, *bbox_wgs84, densify_pts=21)
        full = Window(0, 0, src.width, src.height)
        win = from_bounds(*utm_bounds, transform=src.transform)
        win = win.round_offsets().round_lengths().intersection(full)
        exact = window_bounds(win, src.transform)
        return Grid(
            crs=src.crs,
            transform=src.window_transform(win),
            bounds=exact,
            height=int(win.height),
            width=int(win.width),
        )


def read_on_grid(href: str, grid: Grid, resampling: Resampling = Resampling.nearest) -> np.ndarray:
    """Read a band onto the AOI grid, resampling coarser bands (20 m SCL) as needed."""
    with rasterio.open(href) as src:
        if src.crs != grid.crs:
            raise ValueError(f"{href} CRS {src.crs} != grid CRS {grid.crs}; use same MGRS tile")
        win = from_bounds(*grid.bounds, transform=src.transform)
        return src.read(1, window=win, out_shape=(grid.height, grid.width), resampling=resampling)


def write_cog(path: str, data: np.ndarray, grid: Grid) -> None:
    """Write a single-band uint8 classification COG with a colour table for quick viewing."""
    profile = {
        "driver": "COG",
        "dtype": "uint8",
        "count": 1,
        "height": grid.height,
        "width": grid.width,
        "crs": grid.crs,
        "transform": grid.transform,
        "nodata": NODATA,
        "compress": "DEFLATE",
        "blocksize": 512,
        "overview_resampling": "nearest",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)
        dst.write_colormap(
            1,
            {
                0: (0, 0, 0, 0),  # dry: transparent
                1: (30, 90, 200, 255),  # permanent water: blue
                2: (230, 50, 50, 255),  # flood water: red
            },
        )
        dst.update_tags(classes="0=dry,1=permanent_water,2=flood_water,255=nodata")


def footprint_wgs84(grid: Grid) -> dict:
    """GeoJSON polygon of the analysed area, for PostGIS."""
    minx, miny, maxx, maxy = transform_bounds(grid.crs, "EPSG:4326", *grid.bounds)
    ring = [[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]
    return {"type": "Polygon", "coordinates": [ring]}
