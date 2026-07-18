from __future__ import annotations

import numpy as np
import pytest
import tifffile
import zarr

from layerlens.io import open_volume, override_calibration


def test_open_ome_zarr_discovers_level_and_calibration(tmp_path) -> None:
    path = tmp_path / "input.zarr"
    root = zarr.open_group(path, mode="w", zarr_format=3)
    data = np.arange(24 * 20 * 16, dtype=np.uint16).reshape(24, 20, 16)
    root.create_array("s0", data=data, chunks=(12, 10, 8), dimension_names=("z", "y", "x"))
    root.attrs["ome"] = {
        "version": "0.5",
        "multiscales": [
            {
                "axes": [
                    {"name": "z", "type": "space", "unit": "micrometer"},
                    {"name": "y", "type": "space", "unit": "micrometer"},
                    {"name": "x", "type": "space", "unit": "micrometer"},
                ],
                "datasets": [
                    {
                        "path": "s0",
                        "coordinateTransformations": [
                            {"type": "scale", "scale": [7.91, 7.91, 7.91]},
                            {"type": "translation", "translation": [10.0, 20.0, 30.0]},
                        ],
                    }
                ],
            }
        ],
    }

    opened = open_volume(path)
    assert opened.shape == data.shape
    assert opened.array_path == "s0"
    assert opened.axes == ("z", "y", "x")
    assert opened.voxel_size == (7.91, 7.91, 7.91)
    assert opened.translation == (10.0, 20.0, 30.0)
    assert opened.units == ("micrometer",) * 3
    np.testing.assert_array_equal(opened.data[0, :2, :3], data[0, :2, :3])


def test_tiff_defaults_and_calibration_override(tmp_path) -> None:
    path = tmp_path / "input.tif"
    data = np.arange(12 * 10, dtype=np.uint8).reshape(12, 10)
    tifffile.imwrite(path, data)

    opened = open_volume(path)
    assert opened.axes == ("y", "x")
    assert opened.voxel_size == (1.0, 1.0)
    calibrated = override_calibration(opened, voxel_size=(2.4, 2.4), unit="micrometer")
    assert calibrated.voxel_size == (2.4, 2.4)
    assert calibrated.units == ("micrometer", "micrometer")
    with pytest.raises(ValueError):
        override_calibration(opened, voxel_size=(2.4,))


def test_compressed_multipage_tiff_remains_lazy(tmp_path) -> None:
    path = tmp_path / "volume.tif"
    data = np.arange(9 * 12 * 10, dtype=np.uint16).reshape(9, 12, 10)
    tifffile.imwrite(path, data, compression="deflate", photometric="minisblack")

    opened = open_volume(path)

    assert isinstance(opened.data, zarr.Array)
    assert opened.data.chunks[0] <= data.shape[0]
    np.testing.assert_array_equal(opened.data[2:4, :3, :5], data[2:4, :3, :5])
