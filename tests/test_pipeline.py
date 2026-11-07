"""End-to-end pipeline test on synthetic Sentinel-2-like rasters (no network needed)."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

from geoflood import cli, indices, stac

# A 2 km x 2 km UTM 44N patch near Kaduwela
ORIGIN_X, ORIGIN_Y = 380_000.0, 770_000.0
CRS = "EPSG:32644"
SIZE_10M = 200


def _write(path, data, res):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs=CRS,
        transform=from_origin(ORIGIN_X, ORIGIN_Y, res, res),
    ) as dst:
        dst.write(data, 1)


def _scene(tmp_path, name, water_cols, cloud_rows=0):
    """River of `water_cols` columns on the left; optional cloud band across the top."""
    green = np.full((SIZE_10M, SIZE_10M), 1000 + 600, dtype="uint16")  # vegetation
    nir = np.full((SIZE_10M, SIZE_10M), 1000 + 3500, dtype="uint16")
    green[:, :water_cols] = 1000 + 800  # water: green > nir
    nir[:, :water_cols] = 1000 + 200
    scl = np.full((SIZE_10M // 2, SIZE_10M // 2), 4, dtype="uint8")
    if cloud_rows:
        scl[: cloud_rows // 2, :] = 9
    hrefs = {}
    for band, arr, res in (("B03", green, 10), ("B08", nir, 10), ("SCL", scl, 20)):
        p = tmp_path / f"{name}_{band}.tif"
        _write(p, arr, res)
        hrefs[band] = SimpleNamespace(href=str(p))
    return SimpleNamespace(
        id=name,
        datetime=datetime(2025, 11, 20, 5, tzinfo=UTC),
        assets=hrefs,
        properties={
            "s2:processing_baseline": "05.11",
            "s2:mgrs_tile": "44NMN",
            "eo:cloud_cover": 12.0,
        },
    )


def test_end_to_end(tmp_path, monkeypatch, capsys):
    baseline = _scene(tmp_path, "S2_base", water_cols=20)
    event = _scene(tmp_path, "S2_event", water_cols=60, cloud_rows=40)

    monkeypatch.setattr(stac, "open_catalog", lambda: None)
    monkeypatch.setattr(stac, "find_event_scene", lambda *a, **k: event)
    monkeypatch.setattr(stac, "find_baseline_scene", lambda *a, **k: baseline)
    for var in (
        "AZURE_STORAGE_ACCOUNT_URL",
        "AZURE_STORAGE_CONNECTION_STRING",
        "DATABASE_URL",
        "PUSHGATEWAY_URL",
    ):
        monkeypatch.delenv(var, raising=False)

    # bbox covering the whole synthetic patch (converted from UTM 44N)
    aoi_bbox = list(
        transform_bounds(CRS, "EPSG:4326", ORIGIN_X, ORIGIN_Y - 2000, ORIGIN_X + 2000, ORIGIN_Y)
    )
    monkeypatch.setattr(cli, "load_aois", lambda: {"test": {"name": "t", "bbox": aoi_bbox}})

    args = cli.build_parser().parse_args(
        [
            "run",
            "--aoi",
            "test",
            "--date",
            date(2025, 11, 21).isoformat(),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert cli.run(args) == 0

    out = list((tmp_path / "out").glob("*.tif"))
    assert len(out) == 1
    with rasterio.open(out[0]) as ds:
        assert ds.driver == "GTiff" and ds.overviews(1) is not None
        assert ds.nodata == indices.NODATA
        classes = ds.read(1)

    clear = classes[40:, :]  # below the cloud band
    assert (clear[:, :20] == indices.PERMANENT_WATER).all()
    assert (clear[:, 20:60] == indices.FLOOD_WATER).all()
    assert (clear[:, 60:] == indices.DRY).all()
    assert (classes[:40, :] == indices.NODATA).all()

    stdout = capsys.readouterr().out
    # 160 clear rows * 40 flood cols * 100 m^2 = 0.64 km^2 (allow edge pixels from reprojection)
    flooded = float(stdout.split("flooded=")[1].split()[0])
    assert 0.55 < flooded < 0.70
