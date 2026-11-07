"""Pure-numpy water index and flood classification logic (no I/O, fully unit tested)."""

from __future__ import annotations

import numpy as np

# Output classes written to the flood COG
DRY = 0
PERMANENT_WATER = 1
FLOOD_WATER = 2
NODATA = 255

# Sentinel-2 Scene Classification Layer (SCL) values treated as unusable
# 0 no data, 1 saturated/defective, 3 cloud shadow, 8 cloud medium prob,
# 9 cloud high prob, 10 thin cirrus
SCL_INVALID = (0, 1, 3, 8, 9, 10)

# Since processing baseline 04.00 (Jan 2022) L2A digital numbers carry a +1000 offset
BOA_ADD_OFFSET = -1000
QUANTIFICATION_VALUE = 10_000.0


def to_reflectance(dn: np.ndarray, processing_baseline: str | float | None) -> np.ndarray:
    """Convert Sentinel-2 L2A digital numbers to surface reflectance (0..1).

    DN == 0 is nodata and becomes NaN.
    """
    dn = dn.astype("float32")
    nodata = dn == 0
    offset = 0.0
    if processing_baseline is not None and float(processing_baseline) >= 4.0:
        offset = BOA_ADD_OFFSET
    refl = np.clip((dn + offset) / QUANTIFICATION_VALUE, 0.0, None)
    refl[nodata] = np.nan
    return refl


def ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """McFeeters NDWI = (Green - NIR) / (Green + NIR). Water is typically > 0."""
    green = green.astype("float32")
    nir = nir.astype("float32")
    denom = green + nir
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (green - nir) / denom
    out[~np.isfinite(out)] = np.nan
    return out


def valid_mask(scl: np.ndarray, index: np.ndarray) -> np.ndarray:
    """Pixels that are cloud-free according to SCL and have a finite index value."""
    return ~np.isin(scl, SCL_INVALID) & np.isfinite(index)


def classify_flood(
    event_ndwi: np.ndarray,
    event_valid: np.ndarray,
    base_ndwi: np.ndarray,
    base_valid: np.ndarray,
    threshold: float = 0.0,
) -> np.ndarray:
    """Compare an event scene against a dry-season baseline.

    Returns a uint8 array: 0 dry, 1 permanent water, 2 new (flood) water, 255 nodata.
    """
    if event_ndwi.shape != base_ndwi.shape:
        raise ValueError(f"shape mismatch: event {event_ndwi.shape} vs baseline {base_ndwi.shape}")

    both = event_valid & base_valid
    event_water = (event_ndwi > threshold) & both
    base_water = (base_ndwi > threshold) & both

    out = np.full(event_ndwi.shape, NODATA, dtype="uint8")
    out[both] = DRY
    out[base_water] = PERMANENT_WATER
    out[event_water & ~base_water] = FLOOD_WATER
    return out


def summarise(classes: np.ndarray, pixel_area_m2: float = 100.0) -> dict[str, float]:
    """Area statistics for a classified raster (10 m Sentinel-2 pixel = 100 m^2)."""
    total = classes.size
    valid = int(np.count_nonzero(classes != NODATA))
    flood = int(np.count_nonzero(classes == FLOOD_WATER))
    perm = int(np.count_nonzero(classes == PERMANENT_WATER))
    return {
        "flooded_km2": flood * pixel_area_m2 / 1e6,
        "permanent_water_km2": perm * pixel_area_m2 / 1e6,
        "valid_fraction": valid / total if total else 0.0,
    }
