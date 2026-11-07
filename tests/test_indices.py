import numpy as np
import pytest

from geoflood import indices as ix


def test_reflectance_applies_offset_for_new_baseline():
    dn = np.array([[0, 1000, 2000, 11000]], dtype="uint16")
    old = ix.to_reflectance(dn, "03.01")
    new = ix.to_reflectance(dn, "05.10")
    assert np.isnan(old[0, 0]) and np.isnan(new[0, 0])  # DN 0 is nodata
    assert old[0, 2] == pytest.approx(0.2)
    assert new[0, 2] == pytest.approx(0.1)  # 2000 - 1000 offset
    assert new[0, 1] == 0.0  # clipped, never negative


def test_ndwi_water_positive_vegetation_negative():
    green = np.array([[0.08, 0.05]])
    nir = np.array([[0.02, 0.40]])
    out = ix.ndwi(green, nir)
    assert out[0, 0] > 0  # water
    assert out[0, 1] < 0  # vegetation


def test_ndwi_zero_denominator_is_nan():
    out = ix.ndwi(np.zeros((1, 1)), np.zeros((1, 1)))
    assert np.isnan(out[0, 0])


def test_valid_mask_drops_clouds_and_nan():
    scl = np.array([[4, 8, 6, 4]])
    nd = np.array([[0.1, 0.1, 0.5, np.nan]])
    assert ix.valid_mask(scl, nd).tolist() == [[True, False, True, False]]


def test_classify_flood_all_classes():
    ev = np.array([[0.3, 0.3, -0.4, 0.3]])
    base = np.array([[0.3, -0.4, -0.4, -0.4]])
    ev_valid = np.array([[True, True, True, False]])
    base_valid = np.ones_like(ev_valid)
    out = ix.classify_flood(ev, ev_valid, base, base_valid)
    assert out.tolist() == [[ix.PERMANENT_WATER, ix.FLOOD_WATER, ix.DRY, ix.NODATA]]


def test_classify_flood_shape_mismatch():
    with pytest.raises(ValueError):
        ix.classify_flood(
            np.zeros((2, 2)), np.ones((2, 2), bool), np.zeros((3, 3)), np.ones((3, 3), bool)
        )


def test_summarise_areas():
    classes = np.array([[2, 2, 1, 0], [255, 0, 0, 0]], dtype="uint8")
    s = ix.summarise(classes)
    assert s["flooded_km2"] == pytest.approx(200 / 1e6)
    assert s["permanent_water_km2"] == pytest.approx(100 / 1e6)
    assert s["valid_fraction"] == pytest.approx(7 / 8)
