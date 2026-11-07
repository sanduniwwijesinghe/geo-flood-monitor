"""Command-line entrypoint: `geoflood run --aoi kelani-lower`."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, date, datetime
from importlib import resources
from pathlib import Path

import yaml
from rasterio.enums import Resampling

from geoflood import indices, raster, stac, storage
from geoflood.metrics import PipelineMetrics

log = logging.getLogger("geoflood")


def load_aois() -> dict:
    custom = os.getenv("GEOFLOOD_AOIS_FILE")
    text = (
        Path(custom).read_text()
        if custom
        else resources.files("geoflood").joinpath("aois.yaml").read_text()
    )
    return yaml.safe_load(text)


def analyse(item, bbox):
    """Read Green/NIR/SCL for one scene on the AOI grid and return (ndwi, valid, grid)."""
    grid = raster.aoi_grid(item.assets["B03"].href, bbox)
    return _analyse_on_grid(item, grid), grid


def _analyse_on_grid(item, grid):
    baseline = item.properties.get("s2:processing_baseline")
    green = indices.to_reflectance(raster.read_on_grid(item.assets["B03"].href, grid), baseline)
    nir = indices.to_reflectance(raster.read_on_grid(item.assets["B08"].href, grid), baseline)
    scl = raster.read_on_grid(item.assets["SCL"].href, grid, Resampling.nearest)
    nd = indices.ndwi(green, nir)
    return nd, indices.valid_mask(scl, nd)


def run(args: argparse.Namespace) -> int:
    aois = load_aois()
    if args.aoi not in aois:
        log.error("Unknown AOI %r. Choose from: %s", args.aoi, ", ".join(aois))
        return 2
    aoi = aois[args.aoi]
    bbox = aoi["bbox"]
    metrics = PipelineMetrics(args.aoi)

    with metrics.run():
        catalog = stac.open_catalog()
        event = stac.find_event_scene(catalog, bbox, args.date, args.lookback_days, args.max_cloud)
        if event is None:
            raise RuntimeError(f"No event scene for {args.aoi} in last {args.lookback_days} days")
        tile = event.properties["s2:mgrs_tile"]
        log.info(
            "Event scene %s (tile %s, cloud %.1f%%)",
            event.id,
            tile,
            event.properties["eo:cloud_cover"],
        )

        base = stac.find_baseline_scene(
            catalog, bbox, tile, args.baseline_start, args.baseline_end, args.max_cloud
        )
        if base is None:
            raise RuntimeError(f"No baseline scene on tile {tile}")
        log.info("Baseline scene %s (cloud %.1f%%)", base.id, base.properties["eo:cloud_cover"])

        (ev_ndwi, ev_valid), grid = analyse(event, bbox)
        base_ndwi, base_valid = _analyse_on_grid(base, grid)

        classes = indices.classify_flood(ev_ndwi, ev_valid, base_ndwi, base_valid, args.threshold)
        stats = indices.summarise(classes)
        log.info("Result: %s", stats)

        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        blob_name = f"{args.aoi}/{event.datetime:%Y-%m-%d}_{event.id}.tif"
        local = out_dir / blob_name.replace("/", "_")
        raster.write_cog(str(local), classes, grid)
        cog_url = storage.upload_blob(str(local), blob_name)

        storage.record_event(
            {
                "aoi": args.aoi,
                "event_scene_id": event.id,
                "event_datetime": event.datetime,
                "baseline_scene_id": base.id,
                "cog_url": cog_url,
                **stats,
            },
            raster.footprint_wgs84(grid),
        )

        metrics.flooded.set(stats["flooded_km2"])
        metrics.valid.set(stats["valid_fraction"])
        metrics.scene_age.set((datetime.now(UTC) - event.datetime).total_seconds())

        print(
            f"{args.aoi}: flooded={stats['flooded_km2']:.2f} km2 "
            f"valid={stats['valid_fraction']:.0%} -> {cog_url}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="geoflood", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="Analyse one AOI")
    r.add_argument("--aoi", required=True)
    r.add_argument(
        "--date",
        type=date.fromisoformat,
        default=date.today(),
        help="Analyse the newest scene on or before this date (default today)",
    )
    r.add_argument("--lookback-days", type=int, default=10)
    r.add_argument(
        "--baseline-start",
        type=date.fromisoformat,
        default=date(2025, 2, 1),
        help="Dry-season baseline window start (Feb-Mar is dry in the west)",
    )
    r.add_argument("--baseline-end", type=date.fromisoformat, default=date(2025, 3, 31))
    r.add_argument("--max-cloud", type=float, default=40.0)
    r.add_argument("--threshold", type=float, default=0.0, help="NDWI water threshold")
    r.add_argument("--output-dir", default=os.getenv("GEOFLOOD_OUTPUT_DIR", "./output"))

    sub.add_parser("list-aois", help="Show configured AOIs")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = build_parser().parse_args(argv)
    if args.command == "list-aois":
        for key, aoi in load_aois().items():
            print(f"{key:24} {aoi['name']}  bbox={aoi['bbox']}")
        return 0
    try:
        return run(args)
    except Exception:
        log.exception("Pipeline failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
