"""Export a LayerLens channel as a compact VC3D volume overlay."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import uuid as uuid_module
from itertools import product
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import zarr
from numcodecs import Blosc

from .pipeline import output_shape


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


def _power_of_two_level(stride: Sequence[int]) -> int:
    values = tuple(int(value) for value in stride)
    if len(values) != 3 or len(set(values)) != 1:
        raise ValueError("VC3D export requires one isotropic 3D stride")
    value = values[0]
    if value < 1 or value & (value - 1):
        raise ValueError("VC3D export requires a power-of-two stride")
    return value.bit_length() - 1


def _require_int_tuple(value: Any, *, name: str, length: int = 3) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"LayerLens metadata field {name!r} must contain {length} integers")
    parsed = tuple(int(item) for item in value)
    if any(item < 1 for item in parsed):
        raise ValueError(f"LayerLens metadata field {name!r} must be positive")
    return parsed


def _require_float_tuple(value: Any, *, name: str, length: int = 3) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"LayerLens metadata field {name!r} must contain {length} numbers")
    parsed = tuple(float(item) for item in value)
    if any(not math.isfinite(item) or item <= 0 for item in parsed):
        raise ValueError(f"LayerLens metadata field {name!r} must be positive and finite")
    return parsed


def _voxel_size_micrometers(summary: dict[str, Any], override: float | None) -> float:
    if override is not None:
        if not math.isfinite(override) or override <= 0:
            raise ValueError("voxel_size_um must be positive and finite")
        return float(override)

    input_metadata = summary["input"]
    voxel_size = _require_float_tuple(input_metadata.get("voxel_size"), name="input.voxel_size")
    if not np.allclose(voxel_size, voxel_size[0], rtol=1e-6, atol=1e-9):
        raise ValueError("VC3D export requires isotropic voxels; pass --voxel-size-um to override")

    units = input_metadata.get("units")
    if not isinstance(units, (list, tuple)) or len(units) != 3:
        raise ValueError("LayerLens metadata field 'input.units' must contain three values")
    normalized = tuple(str(item).lower() if item is not None else None for item in units)
    if len(set(normalized)) != 1:
        raise ValueError("VC3D export requires one spatial unit; pass --voxel-size-um to override")

    unit = normalized[0]
    factors = {
        "nanometer": 1e-3,
        "nanometre": 1e-3,
        "nm": 1e-3,
        "micrometer": 1.0,
        "micrometre": 1.0,
        "um": 1.0,
        "µm": 1.0,
        "millimeter": 1e3,
        "millimetre": 1e3,
        "mm": 1e3,
        "meter": 1e6,
        "metre": 1e6,
        "m": 1e6,
    }
    if unit is None or unit == "pixel":
        return float(voxel_size[0])
    if unit not in factors:
        raise ValueError(f"cannot convert spatial unit {unit!r} to micrometers; pass --voxel-size-um")
    return float(voxel_size[0] * factors[unit])


def _safe_identifier(value: str) -> str:
    identifier = "".join(character if character.isalnum() or character in "-_" else "-" for character in value)
    identifier = "-".join(part for part in identifier.split("-") if part)
    return identifier or "layerlens-overlay"


def _paths_overlap(first: Path, second: Path) -> bool:
    resolved_first = first.resolve()
    resolved_second = second.resolve()
    return (
        resolved_first == resolved_second
        or resolved_first in resolved_second.parents
        or resolved_second in resolved_first.parents
    )


def _read_padded_chunk(
    source: zarr.Array,
    channel: int,
    starts: tuple[int, int, int],
    stops: tuple[int, int, int],
) -> np.ndarray:
    source_shape = tuple(int(value) for value in source.shape[1:])
    read_starts = tuple(min(start, size - 1) for start, size in zip(starts, source_shape, strict=True))
    read_stops = tuple(min(stop, size) for stop, size in zip(stops, source_shape, strict=True))
    selection = (channel,) + tuple(
        slice(start, stop) for start, stop in zip(read_starts, read_stops, strict=True)
    )
    block = np.asarray(source[selection], dtype=np.float32)
    for axis, (start, stop, read_start, size) in enumerate(
        zip(starts, stops, read_starts, source_shape, strict=True)
    ):
        indices = np.clip(np.arange(start, stop), 0, size - 1) - read_start
        block = np.take(block, indices, axis=axis)
    if not np.isfinite(block).all():
        raise ValueError("LayerLens channel contains non-finite values")
    return block


def export_vc3d_overlay(
    analysis: str | Path,
    output: str | Path,
    *,
    channel: str = "quality",
    invert: bool = True,
    chunk_shape: int = 64,
    voxel_size_um: float | None = None,
    name: str | None = None,
    uuid: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write one LayerLens channel as a VC3D-compatible sparse OME-Zarr pyramid.

    Metadata-only finer levels let VC3D fall back to the physical LayerLens
    stride level. This preserves source voxel coordinates without expanding a
    stride-4 map into 64 times as many stored voxels.
    """

    analysis_path = Path(analysis)
    output_path = Path(output)
    if _paths_overlap(analysis_path, output_path):
        raise ValueError("analysis and VC3D output paths must not contain one another")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {output_path}")
    if chunk_shape < 1:
        raise ValueError("chunk_shape must be positive")

    root = zarr.open_group(analysis_path, mode="r")
    attributes = root.attrs.asdict()
    summary = attributes.get("layerlens")
    if not isinstance(summary, dict) or summary.get("schema") != "layerlens-summary-v1":
        raise ValueError("analysis has no embedded layerlens-summary-v1 metadata")
    input_metadata = summary.get("input")
    parameters = summary.get("parameters")
    output_metadata = summary.get("output")
    if not all(isinstance(item, dict) for item in (input_metadata, parameters, output_metadata)):
        raise ValueError("LayerLens summary is missing input, parameters, or output metadata")

    axes = tuple(str(item) for item in input_metadata.get("axes", []))
    if axes != ("z", "y", "x"):
        raise ValueError(f"VC3D export requires ZYX input axes, got {axes}")
    full_shape = _require_int_tuple(input_metadata.get("shape"), name="input.shape")
    stride = _require_int_tuple(parameters.get("stride"), name="parameters.stride")
    physical_level = _power_of_two_level(stride)
    stride_value = stride[0]

    channels = output_metadata.get("channels")
    if not isinstance(channels, list) or not all(isinstance(item, str) for item in channels):
        raise ValueError("LayerLens output channel metadata is invalid")
    if channel not in channels:
        raise ValueError(f"unknown LayerLens channel {channel!r}; choose from {', '.join(channels)}")
    channel_index = channels.index(channel)

    source = root["0"]
    if not isinstance(source, zarr.Array) or source.ndim != 4:
        raise ValueError("LayerLens analysis array must have layout (c,z,y,x)")
    expected_analysis_shape = output_shape(full_shape, stride)
    if tuple(int(value) for value in source.shape) != (len(channels), *expected_analysis_shape):
        raise ValueError("LayerLens analysis array shape disagrees with its embedded metadata")

    _require_float_tuple(input_metadata.get("voxel_size"), name="input.voxel_size")
    voxel_um = _voxel_size_micrometers(summary, voxel_size_um)

    destination_shape = tuple(math.ceil(size / stride_value) for size in full_shape)
    level_shapes = [
        tuple(math.ceil(size / (2**level)) for size in full_shape)
        for level in range(physical_level + 1)
    ]
    overlay_name = name or f"LayerLens {'low-quality risk' if invert else channel}"
    output_stem = output_path.name
    for suffix in (".zarr", ".ome"):
        if output_stem.lower().endswith(suffix):
            output_stem = output_stem[: -len(suffix)]
    overlay_uuid = uuid or f"layerlens-{_safe_identifier(output_stem)}"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.parent / f".{output_path.name}.tmp-{uuid_module.uuid4().hex}"
    try:
        destination_root = zarr.open_group(temporary, mode="w", zarr_format=2)
        compressor = Blosc(cname="zstd", clevel=5, shuffle=Blosc.SHUFFLE)
        arrays: list[zarr.Array] = []
        for level, shape in enumerate(level_shapes):
            chunks = tuple(min(chunk_shape, size) for size in shape)
            arrays.append(
                destination_root.create_array(
                    str(level),
                    shape=shape,
                    chunks=chunks,
                    dtype="uint8",
                    fill_value=0,
                    compressor=compressor,
                    overwrite=True,
                )
            )

        destination = arrays[physical_level]
        for starts in product(*(range(0, size, chunk_shape) for size in destination_shape)):
            stops = tuple(
                min(start + chunk_shape, size)
                for start, size in zip(starts, destination_shape, strict=True)
            )
            block = _read_padded_chunk(source, channel_index, starts, stops)
            values = 1.0 - block if invert else block
            encoded = np.asarray(np.rint(np.clip(values, 0.0, 1.0) * 255.0), dtype=np.uint8)
            selection = tuple(slice(start, stop) for start, stop in zip(starts, stops, strict=True))
            destination[selection] = encoded

        axes_metadata = [{"name": axis_name, "type": "space"} for axis_name in axes]
        datasets = []
        for level in range(physical_level + 1):
            # VC3D's prediction preflight requires /0 to use identity index
            # coordinates. Physical calibration belongs in meta.json.
            scale = [float(2**level)] * 3
            datasets.append(
                {
                    "path": str(level),
                    "coordinateTransformations": [{"type": "scale", "scale": scale}],
                }
            )
        vc3d_metadata = {
            "schema": "layerlens-vc3d-overlay-v1",
            "analysis": str(analysis_path),
            "channel": channel,
            "inverted": invert,
            "physical_level": physical_level,
            "stride": list(stride),
            "source_shape_zyx": list(full_shape),
            "source_grid_center_offset_zyx": [value // 2 for value in stride],
            "stored_shape_zyx": list(destination_shape),
            "coordinate_space": "source level-0 voxel indices",
            "quantization": "round(clip(value,0,1)*255)",
            "finer_levels": "metadata-only; VC3D falls back to the populated physical level",
        }
        destination_root.attrs.update(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "name": overlay_name,
                        "axes": axes_metadata,
                        "datasets": datasets,
                        "metadata": {"downsampling_method": "layerlens_stride_sampling"},
                    }
                ],
                "layerlens_vc3d": vc3d_metadata,
            }
        )
        meta = {
            "type": "vol",
            "uuid": overlay_uuid,
            "name": overlay_name,
            "format": "zarr",
            "width": full_shape[2],
            "height": full_shape[1],
            "slices": full_shape[0],
            "voxelsize": voxel_um,
            "min": 0.0,
            "max": 255.0,
            "layerlens_channel": channel,
            "layerlens_inverted": invert,
            "layerlens_physical_level": physical_level,
        }
        (temporary / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

        if output_path.is_symlink() or output_path.is_file():
            output_path.unlink()
        elif output_path.exists():
            shutil.rmtree(output_path)
        temporary.replace(output_path)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return {
        "schema": "layerlens-vc3d-export-result-v1",
        "output": str(output_path),
        "uuid": overlay_uuid,
        "name": overlay_name,
        "channel": channel,
        "inverted": invert,
        "physical_level": physical_level,
        "stored_shape_zyx": list(destination_shape),
        "source_shape_zyx": list(full_shape),
        "voxel_size_um": voxel_um,
    }


def _project_location(location: str | Path, project_path: Path) -> str:
    text = str(location)
    if "://" in text:
        return text
    return os.path.relpath(Path(text).resolve(), project_path.parent.resolve())


def write_vc3d_project(
    project: str | Path,
    *,
    base_volume: str | Path,
    overlay_volume: str | Path,
    coordinate_space: str | None = None,
    name: str = "LayerLens quality review",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create a minimal current-format VC3D project containing base and overlay."""

    project_path = Path(project)
    overlay_path = Path(overlay_volume)
    if _paths_overlap(project_path, overlay_path):
        raise ValueError("VC3D project and overlay paths must not contain one another")
    if project_path.exists() and not overwrite:
        raise FileExistsError(f"project already exists: {project_path}")
    base_text = str(base_volume)
    if "://" not in base_text:
        base_path = Path(base_volume)
        if not base_path.exists():
            raise FileNotFoundError(f"base volume does not exist: {base_volume}")
        if _paths_overlap(project_path, base_path):
            raise ValueError("VC3D project and base-volume paths must not contain one another")
    if not overlay_path.is_dir():
        raise FileNotFoundError(f"overlay volume does not exist: {overlay_path}")

    tags = []
    if coordinate_space is not None:
        stripped = coordinate_space.strip()
        if not stripped:
            raise ValueError("coordinate_space must not be empty")
        tags.append(f"vc-open-data-coordinate-space:{stripped}")

    def entry(location: str, extra_tags: Sequence[str] = ()) -> str | dict[str, Any]:
        entry_tags = [*tags, *extra_tags]
        if not entry_tags:
            return location
        return {"location": location, "tags": entry_tags}

    document = {
        "name": name,
        "version": 1,
        "volumes": [
            entry(_project_location(base_volume, project_path)),
            entry(_project_location(overlay_path, project_path), ("layerlens-overlay",)),
        ],
        "segments": [],
        "normal_grids": [],
        "lasagna_datasets": [],
    }
    project_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = project_path.with_name(f".{project_path.name}.tmp-{uuid_module.uuid4().hex}")
    try:
        temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        temporary.replace(project_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "schema": "layerlens-vc3d-project-result-v1",
        "project": str(project_path),
        "base_volume": document["volumes"][0],
        "overlay_volume": document["volumes"][1],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis", type=Path, help="LayerLens OME-Zarr analysis")
    parser.add_argument("output", type=Path, help="new VC3D OME-Zarr v2 overlay directory")
    parser.add_argument("--channel", default="quality", help="LayerLens channel to export")
    parser.add_argument(
        "--invert",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="encode low values as high overlay risk (default: true)",
    )
    parser.add_argument("--chunk-shape", type=_positive_int, default=64)
    parser.add_argument("--voxel-size-um", type=_positive_float)
    parser.add_argument("--name")
    parser.add_argument("--uuid")
    parser.add_argument("--project", type=Path, help="also create a new .volpkg.json project")
    parser.add_argument(
        "--base-volume",
        help="VC3D-readable base OME-Zarr path or URL for --project",
    )
    parser.add_argument(
        "--coordinate-space",
        help="optional VC3D open-data coordinate-space tag applied to both volumes",
    )
    parser.add_argument("--project-name", default="LayerLens quality review")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def run(arguments: Sequence[str] | None = None) -> dict[str, Any]:
    parser = _parser()
    args = parser.parse_args(arguments)
    if (args.project is None) != (args.base_volume is None):
        parser.error("--project and --base-volume must be provided together")
    if args.project is not None:
        if _paths_overlap(args.analysis, args.project):
            parser.error("--project must not be inside the analysis or contain it")
        if _paths_overlap(args.output, args.project):
            parser.error("--project must not be inside the overlay or contain it")
        if args.project.exists() and not args.overwrite:
            raise FileExistsError(f"project already exists: {args.project}")
        if "://" not in args.base_volume:
            base_path = Path(args.base_volume)
            if not base_path.exists():
                raise FileNotFoundError(f"base volume does not exist: {args.base_volume}")
            if _paths_overlap(args.project, base_path):
                parser.error("--project must not be inside the base volume or contain it")
    result = export_vc3d_overlay(
        args.analysis,
        args.output,
        channel=args.channel,
        invert=args.invert,
        chunk_shape=args.chunk_shape,
        voxel_size_um=args.voxel_size_um,
        name=args.name,
        uuid=args.uuid,
        overwrite=args.overwrite,
    )
    if args.project is not None:
        result["project"] = write_vc3d_project(
            args.project,
            base_volume=args.base_volume,
            overlay_volume=args.output,
            coordinate_space=args.coordinate_space,
            name=args.project_name,
            overwrite=args.overwrite,
        )
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    run()


if __name__ == "__main__":
    main()
