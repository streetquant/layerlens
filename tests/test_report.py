from __future__ import annotations

import numpy as np
import pytest

from benchmarks.synthetic import layered_phantom
from layerlens.io import OpenedVolume
from layerlens.pipeline import analyze_to_ome_zarr
from layerlens.report import render_report


def _volume(data: np.ndarray) -> OpenedVolume:
    axes = ("y", "x") if data.ndim == 2 else ("z", "y", "x")
    return OpenedVolume(
        data=data,
        source="synthetic",
        axes=axes,
        voxel_size=(1.0,) * data.ndim,
        translation=(0.0,) * data.ndim,
        units=(None,) * data.ndim,
    )


def test_report_is_self_contained_and_refuses_overwrite(tmp_path) -> None:
    y, x = np.mgrid[:48, :64]
    data = (2000.0 + 800.0 * np.sin((x + 0.2 * y) / 3.0)).astype(np.float32)
    volume = _volume(data)
    analysis = tmp_path / "quality.zarr"
    output = tmp_path / "report.html"
    analyze_to_ome_zarr(volume, analysis, stride=4, tile_shape=32)

    view = render_report(volume, analysis, output)
    document = output.read_text(encoding="utf-8")

    assert view == {
        "output": str(output),
        "axis": None,
        "map_index": None,
        "input_index": None,
    }
    assert document.count("data:image/png;base64,") == 3
    assert "LayerLens score" in document
    assert "Reference-free CT quality control" in document
    assert "https://" not in document
    with pytest.raises(FileExistsError):
        render_report(volume, analysis, output)
    render_report(volume, analysis, output, overwrite=True)


def test_report_maps_explicit_3d_plane_to_input_coordinates(tmp_path) -> None:
    volume = _volume(layered_phantom(size=28, seed=89))
    analysis = tmp_path / "quality.zarr"
    output = tmp_path / "report.html"
    analyze_to_ome_zarr(volume, analysis, stride=4, tile_shape=20)

    view = render_report(volume, analysis, output, axis="z", index=18)

    assert view["axis"] == 0
    assert view["map_index"] == 4
    assert view["input_index"] == 18
    with pytest.raises(ValueError, match="explicit --axis"):
        render_report(volume, analysis, tmp_path / "auto.html", index=12)
    with pytest.raises(ValueError, match="outside"):
        render_report(volume, analysis, tmp_path / "bad.html", axis="z", index=99)


def test_report_cannot_replace_its_inputs(tmp_path) -> None:
    volume = _volume(layered_phantom(size=24, seed=97))
    analysis = tmp_path / "quality.zarr"
    analyze_to_ome_zarr(volume, analysis, stride=4, tile_shape=20)

    with pytest.raises(ValueError, match="analysis and report"):
        render_report(volume, analysis, analysis, overwrite=True)

    source = tmp_path / "source.tif"
    source.write_bytes(b"source sentinel")
    source_volume = OpenedVolume(
        data=volume.data,
        source=str(source),
        axes=volume.axes,
        voxel_size=volume.voxel_size,
        translation=volume.translation,
        units=volume.units,
    )
    with pytest.raises(ValueError, match="input and report"):
        render_report(source_volume, analysis, source, overwrite=True)
    assert source.read_bytes() == b"source sentinel"
