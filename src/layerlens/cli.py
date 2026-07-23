"""Generate seam-safe LayerLens quality maps from TIFF or OME-Zarr volumes."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Sequence

from .io import open_volume, override_calibration
from .pipeline import analyze_to_ome_zarr


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive finite number")
    return parsed


def _integer_tuple(value: str) -> int | tuple[int, ...]:
    try:
        parsed = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an integer or comma-separated integers") from error
    if not parsed or any(item < 1 for item in parsed):
        raise argparse.ArgumentTypeError("all values must be positive")
    return parsed[0] if len(parsed) == 1 else parsed


def _float_tuple(value: str) -> tuple[float, ...]:
    try:
        parsed = tuple(float(item.strip()) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected comma-separated numbers") from error
    if not parsed or any(not math.isfinite(item) or item <= 0 for item in parsed):
        raise argparse.ArgumentTypeError("all values must be positive and finite")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="TIFF path, local Zarr path, or s3:// Zarr URL")
    parser.add_argument("output", type=Path, help="new OME-Zarr v3 output directory")
    parser.add_argument("--array-path", help="array path inside a non-OME Zarr group")
    parser.add_argument("--level", type=int, default=0, help="OME-Zarr resolution level")
    parser.add_argument("--stride", type=_integer_tuple, default=4)
    parser.add_argument("--tile-shape", type=_integer_tuple, default=128)
    parser.add_argument("--gradient-sigma", type=_positive_float, default=0.6)
    parser.add_argument("--tensor-sigma", type=_positive_float, default=2.5)
    parser.add_argument(
        "--scan-axis",
        type=int,
        default=0,
        help="array-axis index along which persistent structure is measured",
    )
    parser.add_argument("--persistence-sigma", type=_positive_float, default=8.0)
    parser.add_argument(
        "--voxel-size",
        type=_float_tuple,
        help="spatial voxel sizes in array-axis order, for example 7.91,7.91,7.91",
    )
    parser.add_argument("--unit", help="OME physical unit, for example micrometer")
    parser.add_argument("--summary", type=Path, help="JSON summary path")
    parser.add_argument(
        "--normalization-samples",
        type=_positive_int,
        default=1_000_000,
        help="maximum voxels sampled to estimate global p1/p99 bounds",
    )
    parser.add_argument(
        "--authenticated-s3",
        action="store_true",
        help="use ambient S3 credentials instead of anonymous access",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def run(arguments: Sequence[str] | None = None) -> dict[str, object]:
    args = _parser().parse_args(arguments)
    volume = open_volume(
        args.input,
        array_path=args.array_path,
        level=args.level,
        anonymous_s3=not args.authenticated_s3,
    )
    volume = override_calibration(volume, voxel_size=args.voxel_size, unit=args.unit)
    summary = analyze_to_ome_zarr(
        volume,
        args.output,
        stride=args.stride,
        tile_shape=args.tile_shape,
        gradient_sigma=args.gradient_sigma,
        tensor_sigma=args.tensor_sigma,
        scan_axis=args.scan_axis,
        persistence_sigma=args.persistence_sigma,
        max_normalization_samples=args.normalization_samples,
        summary_path=args.summary,
        overwrite=args.overwrite,
    )
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    run()


if __name__ == "__main__":
    main()
