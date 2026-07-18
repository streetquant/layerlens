"""Seam-safe tiled analysis and OME-Zarr output."""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import zarr

from . import __version__
from .io import OpenedVolume
from .quality import QualityMap, compute_quality


CHANNEL_NAMES = ("quality", "coherence", "sharpness", "scale_sharpness", "confidence")
CHANNEL_COLORS = ("00FF66", "00BFFF", "FFD700", "FF6600", "A000FF")


@dataclass(frozen=True)
class NormalizationEstimate:
    lower: float
    upper: float
    sample_count: int
    strategy: str


def _as_tuple(value: int | Sequence[int], ndim: int, name: str) -> tuple[int, ...]:
    if isinstance(value, int):
        result = (value,) * ndim
    else:
        result = tuple(int(item) for item in value)
    if len(result) != ndim or any(item < 1 for item in result):
        raise ValueError(f"{name} must contain {ndim} positive integers")
    return result


def _full_slice(ndim: int) -> tuple[slice, ...]:
    return (slice(None),) * ndim


def estimate_normalization(
    source: Any, *, max_samples: int = 1_000_000, seed: int = 20260717
) -> NormalizationEstimate:
    """Estimate global p1/p99 bounds from full data or deterministic spatial blocks."""

    shape = tuple(int(item) for item in source.shape)
    if len(shape) not in (2, 3) or any(item < 1 for item in shape):
        raise ValueError(f"expected a non-empty 2D or 3D input, got {shape}")
    if max_samples < 1024:
        raise ValueError("max_samples must be at least 1024")

    total = math.prod(shape)
    if total <= max_samples:
        values = np.asarray(source[_full_slice(len(shape))]).ravel()
        strategy = "full"
    else:
        edge = 128 if len(shape) == 2 else 32
        block_shape = tuple(min(edge, item) for item in shape)
        block_size = math.prod(block_shape)
        block_count = max(1, min(32, max_samples // block_size))
        rng = np.random.default_rng(seed)
        blocks: list[np.ndarray] = []
        for index in range(block_count):
            starts = []
            for axis, (length, block) in enumerate(zip(shape, block_shape, strict=True)):
                maximum = length - block
                if index == 0:
                    start = maximum // 2
                elif maximum == 0:
                    start = 0
                else:
                    start = int(rng.integers(0, maximum + 1))
                starts.append(start)
            selection = tuple(
                slice(start, start + block)
                for start, block in zip(starts, block_shape, strict=True)
            )
            blocks.append(np.asarray(source[selection]).ravel())
        values = np.concatenate(blocks)
        strategy = "deterministic_blocks"

    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("input contains no finite values in the normalization sample")
    lower, upper = np.percentile(finite.astype(np.float32, copy=False), (1.0, 99.0))
    if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
        # A constant volume is valid and should produce zero quality.  Give it
        # a finite unit-width normalization interval instead of failing.
        center = float(lower) if np.isfinite(lower) else 0.0
        lower, upper = center, center + 1.0
    return NormalizationEstimate(float(lower), float(upper), int(finite.size), strategy)


def required_halo(
    gradient_sigma: float, tensor_sigma: float, stride: Sequence[int]
) -> tuple[int, ...]:
    """Return a conservative Gaussian support halo aligned to the output grid."""

    if (
        not math.isfinite(gradient_sigma)
        or not math.isfinite(tensor_sigma)
        or gradient_sigma <= 0
        or tensor_sigma <= 0
    ):
        raise ValueError("gradient_sigma and tensor_sigma must be positive and finite")
    stride_tuple = tuple(int(step) for step in stride)
    if not stride_tuple or any(step < 1 for step in stride_tuple):
        raise ValueError("stride must contain positive integers")
    coarse_sigma = max(1.5, 2.5 * gradient_sigma)
    additional_sigma = math.sqrt(coarse_sigma**2 - gradient_sigma**2)
    radius = math.ceil(4.0 * gradient_sigma)
    radius += math.ceil(4.0 * additional_sigma) + math.ceil(4.0 * tensor_sigma)
    return tuple(math.ceil(radius / step) * step for step in stride_tuple)


def output_shape(shape: Sequence[int], stride: Sequence[int]) -> tuple[int, ...]:
    return tuple(
        max(0, math.ceil((length - step // 2) / step))
        for length, step in zip(shape, stride, strict=True)
    )


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def _core_starts(shape: Sequence[int], tile_shape: Sequence[int]) -> Any:
    return product(*(range(0, length, tile) for length, tile in zip(shape, tile_shape, strict=True)))


def _crop_result(result: QualityMap, selection: tuple[slice, ...]) -> dict[str, np.ndarray]:
    return {
        "quality": result.quality[selection],
        "coherence": result.coherence[selection],
        "sharpness": result.sharpness[selection],
        "scale_sharpness": result.scale_sharpness[selection],
        "confidence": result.confidence[selection],
        "weight": result.weight[selection],
    }


def iter_quality_tiles(
    source: Any,
    *,
    normalization: tuple[float, float],
    stride: int | Sequence[int] = 4,
    tile_shape: int | Sequence[int] = 128,
    gradient_sigma: float = 0.6,
    tensor_sigma: float = 2.5,
) -> Any:
    """Yield global output slices and halo-cropped quality tiles."""

    shape = tuple(int(item) for item in source.shape)
    stride_tuple = _as_tuple(stride, len(shape), "stride")
    tile_tuple = _as_tuple(tile_shape, len(shape), "tile shape")
    if any(tile % step for tile, step in zip(tile_tuple, stride_tuple, strict=True)):
        raise ValueError("every tile dimension must be a multiple of its stride")
    halo = required_halo(gradient_sigma, tensor_sigma, stride_tuple)
    result_shape = output_shape(shape, stride_tuple)

    for start in _core_starts(shape, tile_tuple):
        stop = tuple(min(origin + tile, length) for origin, tile, length in zip(start, tile_tuple, shape, strict=True))
        extended_start = tuple(max(0, origin - pad) for origin, pad in zip(start, halo, strict=True))
        extended_stop = tuple(min(length, end + pad) for end, pad, length in zip(stop, halo, shape, strict=True))
        input_selection = tuple(
            slice(begin, end)
            for begin, end in zip(extended_start, extended_stop, strict=True)
        )
        tile_data = np.asarray(source[input_selection])
        result = compute_quality(
            tile_data,
            gradient_sigma=gradient_sigma,
            tensor_sigma=tensor_sigma,
            stride=stride_tuple,
            normalization=normalization,
        )

        global_begin = tuple(
            max(0, _ceil_div(origin - step // 2, step))
            for origin, step in zip(start, stride_tuple, strict=True)
        )
        global_end = tuple(
            min(size, _ceil_div(end - step // 2, step))
            for end, step, size in zip(stop, stride_tuple, result_shape, strict=True)
        )
        local_begin = tuple(
            begin - extended // step
            for begin, extended, step in zip(global_begin, extended_start, stride_tuple, strict=True)
        )
        local_end = tuple(
            end - extended // step
            for end, extended, step in zip(global_end, extended_start, stride_tuple, strict=True)
        )
        output_selection = tuple(
            slice(begin, end) for begin, end in zip(global_begin, global_end, strict=True)
        )
        local_selection = tuple(
            slice(begin, end) for begin, end in zip(local_begin, local_end, strict=True)
        )
        yield output_selection, _crop_result(result, local_selection)


def _axis_metadata(volume: OpenedVolume) -> list[dict[str, str]]:
    axes: list[dict[str, str]] = [{"name": "c", "type": "channel"}]
    for name, unit in zip(volume.axes, volume.units, strict=True):
        axis = {"name": name, "type": "space"}
        if unit is not None:
            axis["unit"] = unit
        axes.append(axis)
    return axes


def _ome_metadata(volume: OpenedVolume, stride: tuple[int, ...]) -> dict[str, Any]:
    scale = [1.0, *[value * step for value, step in zip(volume.voxel_size, stride, strict=True)]]
    offset = [
        origin + value * (step // 2)
        for origin, value, step in zip(
            volume.translation, volume.voxel_size, stride, strict=True
        )
    ]
    transforms: list[dict[str, Any]] = [{"type": "scale", "scale": scale}]
    if any(value != 0.0 for value in offset):
        transforms.append({"type": "translation", "translation": [0.0, *offset]})
    channels = [
        {
            "active": index == 0,
            "coefficient": 1,
            "color": color,
            "family": "linear",
            "inverted": False,
            "label": name,
            "window": {"min": 0.0, "max": 1.0, "start": 0.0, "end": 1.0},
        }
        for index, (name, color) in enumerate(zip(CHANNEL_NAMES, CHANNEL_COLORS, strict=True))
    ]
    return {
        "version": "0.5",
        "multiscales": [
            {
                "name": "LayerLens local layer separability",
                "axes": _axis_metadata(volume),
                "datasets": [{"path": "0", "coordinateTransformations": transforms}],
            }
        ],
        "omero": {
            "name": "LayerLens metrics",
            "channels": channels,
            "rdefs": {"defaultT": 0, "defaultZ": 0, "model": "color"},
        },
    }


def _histogram_quantile(histogram: np.ndarray, probability: float) -> float:
    target = probability * int(histogram.sum())
    index = int(np.searchsorted(np.cumsum(histogram), target, side="left"))
    return min(index, len(histogram) - 1) / len(histogram)


def analyze_to_ome_zarr(
    volume: OpenedVolume,
    output: str | Path,
    *,
    stride: int | Sequence[int] = 4,
    tile_shape: int | Sequence[int] = 128,
    gradient_sigma: float = 0.6,
    tensor_sigma: float = 2.5,
    max_normalization_samples: int = 1_000_000,
    summary_path: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Analyze one spatial volume into a channel-first OME-Zarr quality map."""

    output_path = Path(output)
    if "://" not in volume.source and Path(volume.source).resolve() == output_path.resolve():
        raise ValueError("input and output paths must be different")
    resolved_summary = (
        Path(summary_path) if summary_path is not None else Path(f"{output_path}.json")
    )
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {output_path}")
    if resolved_summary.exists() and not overwrite:
        raise FileExistsError(f"summary already exists: {resolved_summary}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ndim = len(volume.shape)
    stride_tuple = _as_tuple(stride, ndim, "stride")
    tile_tuple = _as_tuple(tile_shape, ndim, "tile shape")
    if any(tile % step for tile, step in zip(tile_tuple, stride_tuple, strict=True)):
        raise ValueError("every tile dimension must be a multiple of its stride")
    halo = required_halo(gradient_sigma, tensor_sigma, stride_tuple)
    estimate = estimate_normalization(volume.data, max_samples=max_normalization_samples)
    spatial_shape = output_shape(volume.shape, stride_tuple)
    spatial_chunks = tuple(
        max(1, min(size, math.ceil(tile / step)))
        for size, tile, step in zip(spatial_shape, tile_tuple, stride_tuple, strict=True)
    )

    root = zarr.open_group(output_path, mode="w", zarr_format=3)
    output_array = root.create_array(
        "0",
        shape=(len(CHANNEL_NAMES), *spatial_shape),
        chunks=(1, *spatial_chunks),
        dtype="float32",
        fill_value=0.0,
        dimension_names=("c", *volume.axes),
    )

    started = time.monotonic()
    numerator = 0.0
    denominator = 0.0
    quality_sum = 0.0
    quality_count = 0
    poor_count = 0
    good_count = 0
    histogram = np.zeros(1000, dtype=np.int64)
    tile_count = 0
    for selection, maps in iter_quality_tiles(
        volume.data,
        normalization=(estimate.lower, estimate.upper),
        stride=stride_tuple,
        tile_shape=tile_tuple,
        gradient_sigma=gradient_sigma,
        tensor_sigma=tensor_sigma,
    ):
        for channel, name in enumerate(CHANNEL_NAMES):
            output_array[(channel, *selection)] = maps[name]
        quality = maps["quality"]
        weight = maps["weight"]
        numerator += float(np.sum(quality * weight, dtype=np.float64))
        denominator += float(np.sum(weight, dtype=np.float64))
        quality_sum += float(np.sum(quality, dtype=np.float64))
        quality_count += quality.size
        poor_count += int(np.count_nonzero(quality < 0.25))
        good_count += int(np.count_nonzero(quality >= 0.75))
        histogram += np.histogram(quality, bins=1000, range=(0.0, 1.0))[0]
        tile_count += 1

    score = numerator / denominator if denominator > 1e-12 else 0.0
    elapsed = time.monotonic() - started
    summary: dict[str, Any] = {
        "schema": "layerlens-summary-v1",
        "layerlens_version": __version__,
        "input": {
            "source": volume.source,
            "array_path": volume.array_path,
            "shape": list(volume.shape),
            "axes": list(volume.axes),
            "voxel_size": list(volume.voxel_size),
            "translation": list(volume.translation),
            "units": list(volume.units),
        },
        "output": {
            "path": str(output_path),
            "shape": [len(CHANNEL_NAMES), *spatial_shape],
            "channels": list(CHANNEL_NAMES),
            "ome_zarr_version": "0.5",
            "zarr_format": 3,
        },
        "parameters": {
            "gradient_sigma": gradient_sigma,
            "tensor_sigma": tensor_sigma,
            "stride": list(stride_tuple),
            "tile_shape": list(tile_tuple),
            "halo": list(halo),
            "normalization": asdict(estimate),
        },
        "metrics": {
            "score": score,
            "mean_quality": quality_sum / quality_count if quality_count else 0.0,
            "quality_p10": _histogram_quantile(histogram, 0.10),
            "quality_p50": _histogram_quantile(histogram, 0.50),
            "quality_p90": _histogram_quantile(histogram, 0.90),
            "poor_fraction": poor_count / quality_count if quality_count else 0.0,
            "good_fraction": good_count / quality_count if quality_count else 0.0,
        },
        "runtime": {"tiles": tile_count, "seconds": elapsed},
    }
    root.attrs.update({"ome": _ome_metadata(volume, stride_tuple), "layerlens": summary})

    resolved_summary.parent.mkdir(parents=True, exist_ok=True)
    resolved_summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
