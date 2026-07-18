from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import zarr

from benchmarks.synthetic import layered_phantom
from layerlens.io import OpenedVolume
from layerlens.pipeline import analyze_to_ome_zarr
from layerlens.vc3d import export_vc3d_overlay, run, write_vc3d_project


def _analysis(tmp_path: Path, *, size: int = 33, stride: int | tuple[int, ...] = 4) -> Path:
    data = layered_phantom(size=size, seed=20260719)
    descriptor = OpenedVolume(
        data=data,
        source="synthetic",
        axes=("z", "y", "x"),
        voxel_size=(7.91, 7.91, 7.91),
        translation=(0.0, 0.0, 0.0),
        units=("micrometer",) * 3,
    )
    path = tmp_path / "analysis.zarr"
    analyze_to_ome_zarr(descriptor, path, stride=stride, tile_shape=20)
    return path


def test_export_is_sparse_vc3d_pyramid_with_padded_edge(tmp_path) -> None:
    analysis = _analysis(tmp_path)
    output = tmp_path / "quality-risk.ome.zarr"
    result = export_vc3d_overlay(analysis, output, chunk_shape=8)

    root = zarr.open_group(output, mode="r")
    assert result["physical_level"] == 2
    assert tuple(root["0"].shape) == (33, 33, 33)
    assert tuple(root["1"].shape) == (17, 17, 17)
    assert tuple(root["2"].shape) == (9, 9, 9)
    assert root["2"].dtype == np.dtype("uint8")

    source = zarr.open_group(analysis, mode="r")["0"][0]
    expected = np.asarray(np.rint((1.0 - source[:]) * 255.0), dtype=np.uint8)
    exported = np.asarray(root["2"][:])
    np.testing.assert_array_equal(exported[:8, :8, :8], expected)
    np.testing.assert_array_equal(exported[8, :, :], exported[7, :, :])
    np.testing.assert_array_equal(exported[:, 8, :], exported[:, 7, :])
    np.testing.assert_array_equal(exported[:, :, 8], exported[:, :, 7])

    # The metadata-only fine levels contain no chunk payloads. VC3D treats
    # those missing chunks as a request to fall back to physical level 2.
    metadata_files = {".zarray", ".zattrs"}
    assert not any(path.is_file() for path in (output / "0").iterdir() if path.name not in metadata_files)
    assert not any(path.is_file() for path in (output / "1").iterdir() if path.name not in metadata_files)

    zarray = json.loads((output / "2" / ".zarray").read_text())
    assert zarray["zarr_format"] == 2
    assert zarray["dtype"] == "|u1"
    assert zarray["compressor"]["id"] == "blosc"
    assert zarray["dimension_separator"] == "."

    meta = json.loads((output / "meta.json").read_text())
    assert meta == {
        "type": "vol",
        "uuid": "layerlens-quality-risk",
        "name": "LayerLens low-quality risk",
        "format": "zarr",
        "width": 33,
        "height": 33,
        "slices": 33,
        "voxelsize": 7.91,
        "min": 0.0,
        "max": 255.0,
        "layerlens_channel": "quality",
        "layerlens_inverted": True,
        "layerlens_physical_level": 2,
    }
    datasets = root.attrs["multiscales"][0]["datasets"]
    assert [item["path"] for item in datasets] == ["0", "1", "2"]
    assert datasets[0]["coordinateTransformations"][0]["scale"] == [1.0, 1.0, 1.0]
    assert datasets[2]["coordinateTransformations"][0]["scale"] == [4.0, 4.0, 4.0]
    assert root.attrs["multiscales"][0]["axes"] == [
        {"name": "z", "type": "space"},
        {"name": "y", "type": "space"},
        {"name": "x", "type": "space"},
    ]


def test_export_rejects_non_dyadic_or_overlapping_output(tmp_path) -> None:
    analysis = _analysis(tmp_path, stride=(2, 4, 4))
    with pytest.raises(ValueError, match="isotropic"):
        export_vc3d_overlay(analysis, tmp_path / "bad.zarr")

    dyadic = tmp_path / "dyadic"
    dyadic.mkdir()
    analysis = _analysis(dyadic)
    with pytest.raises(ValueError, match="must not contain"):
        export_vc3d_overlay(analysis, analysis / "overlay.zarr")


def test_export_refuses_existing_output_without_overwrite(tmp_path) -> None:
    analysis = _analysis(tmp_path)
    output = tmp_path / "overlay.zarr"
    export_vc3d_overlay(analysis, output)
    with pytest.raises(FileExistsError):
        export_vc3d_overlay(analysis, output)

    result = export_vc3d_overlay(analysis, output, invert=False, overwrite=True)
    assert result["inverted"] is False
    assert json.loads((output / "meta.json").read_text())["layerlens_inverted"] is False


def test_project_contains_relative_base_and_overlay_with_matching_coordinate_tag(tmp_path) -> None:
    analysis = _analysis(tmp_path)
    base = tmp_path / "base.ome.zarr"
    base.mkdir()
    overlay = tmp_path / "qc" / "overlay.ome.zarr"
    export_vc3d_overlay(analysis, overlay)
    project = tmp_path / "review.volpkg.json"
    write_vc3d_project(
        project,
        base_volume=base,
        overlay_volume=overlay,
        coordinate_space="PHerc1451/example@L0",
    )

    document = json.loads(project.read_text())
    assert document["version"] == 1
    assert document["volumes"][0]["location"] == "base.ome.zarr"
    assert document["volumes"][1]["location"] == "qc/overlay.ome.zarr"
    coordinate_tag = "vc-open-data-coordinate-space:PHerc1451/example@L0"
    assert coordinate_tag in document["volumes"][0]["tags"]
    assert coordinate_tag in document["volumes"][1]["tags"]
    assert "layerlens-overlay" in document["volumes"][1]["tags"]


def test_cli_can_export_overlay_and_project(tmp_path) -> None:
    analysis = _analysis(tmp_path)
    base = tmp_path / "base.ome.zarr"
    base.mkdir()
    output = tmp_path / "overlay.ome.zarr"
    project = tmp_path / "review.volpkg.json"
    result = run(
        [
            str(analysis),
            str(output),
            "--project",
            str(project),
            "--base-volume",
            str(base),
        ]
    )
    assert output.is_dir()
    assert project.is_file()
    assert result["project"]["project"] == str(project)
