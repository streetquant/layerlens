from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import zarr

from benchmarks.synthetic import layered_phantom
from layerlens.io import OpenedVolume
from layerlens.pipeline import (
    CHANNEL_NAMES,
    analyze_to_ome_zarr,
    estimate_normalization,
    iter_quality_tiles,
    output_shape,
)
from layerlens.quality import compute_quality


def _descriptor(data: np.ndarray) -> OpenedVolume:
    return OpenedVolume(
        data=data,
        source="synthetic",
        axes=("z", "y", "x"),
        voxel_size=(7.91, 7.91, 7.91),
        translation=(10.0, 20.0, 30.0),
        units=("micrometer",) * 3,
    )


def test_tiled_maps_match_whole_volume_without_seams() -> None:
    data = layered_phantom(size=42, angle_degrees=29.0, seed=71)
    bounds = tuple(float(item) for item in np.percentile(data, (1.0, 99.0)))
    full = compute_quality(data, stride=4, normalization=bounds)
    assembled = {
        name: np.empty(full.quality.shape, dtype=np.float32)
        for name in (*CHANNEL_NAMES, "weight")
    }

    for selection, maps in iter_quality_tiles(
        data, normalization=bounds, stride=4, tile_shape=20
    ):
        for name in assembled:
            assembled[name][selection] = maps[name]

    for name in CHANNEL_NAMES:
        np.testing.assert_allclose(assembled[name], getattr(full, name), rtol=2e-5, atol=2e-6)
    np.testing.assert_allclose(assembled["weight"], full.weight, rtol=2e-5, atol=2e-6)


def test_ome_zarr_output_contains_maps_metadata_and_summary(tmp_path) -> None:
    data = layered_phantom(size=36, seed=73)
    destination = tmp_path / "quality.zarr"
    summary = analyze_to_ome_zarr(
        _descriptor(data), destination, stride=4, tile_shape=20
    )

    root = zarr.open_group(destination, mode="r")
    output = root["0"]
    assert output.shape == (len(CHANNEL_NAMES), *output_shape(data.shape, (4, 4, 4)))
    assert output.metadata.dimension_names == ("c", "z", "y", "x")
    ome = root.attrs["ome"]
    assert ome["version"] == "0.5"
    assert [channel["label"] for channel in ome["omero"]["channels"]] == list(CHANNEL_NAMES)
    transforms = ome["multiscales"][0]["datasets"][0]["coordinateTransformations"]
    assert transforms[0]["scale"] == pytest.approx([1.0, 31.64, 31.64, 31.64])
    assert transforms[1]["translation"] == pytest.approx([0.0, 25.82, 35.82, 45.82])
    assert 0.0 <= summary["metrics"]["score"] <= 1.0
    assert summary["runtime"]["tiles"] == 8
    assert summary["metrics"]["score"] == pytest.approx(
        compute_quality(data, stride=4).score, rel=2e-5
    )
    written = json.loads((tmp_path / "quality.zarr.json").read_text())
    assert written["metrics"] == summary["metrics"]
    assert np.isfinite(output[:]).all()

    with pytest.raises(FileExistsError):
        analyze_to_ome_zarr(_descriptor(data), destination)


def test_normalization_sampling_is_deterministic() -> None:
    rng = np.random.default_rng(79)
    data = rng.normal(size=(80, 70, 60)).astype(np.float32)
    first = estimate_normalization(data, max_samples=20_000)
    second = estimate_normalization(data, max_samples=20_000)
    assert first == second
    assert first.strategy == "deterministic_blocks"
    assert first.lower < first.upper


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"gradient_sigma": float("nan")}, "positive and finite"),
        ({"tile_shape": 21, "stride": 4}, "multiple of its stride"),
    ],
)
def test_invalid_configuration_fails_before_creating_output(
    tmp_path: Path, options: dict[str, object], message: str
) -> None:
    data = layered_phantom(size=24, seed=101)
    destination = tmp_path / "must-not-exist.zarr"

    with pytest.raises(ValueError, match=message):
        analyze_to_ome_zarr(_descriptor(data), destination, **options)

    assert not destination.exists()
    assert not Path(f"{destination}.json").exists()
