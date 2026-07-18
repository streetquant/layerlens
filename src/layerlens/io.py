"""Input discovery for TIFF and local or remote OME-Zarr volumes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import tifffile
import zarr


@dataclass(frozen=True)
class OpenedVolume:
    """A spatial image array with the calibration needed for NGFF output."""

    data: Any
    source: str
    axes: tuple[str, ...]
    voxel_size: tuple[float, ...]
    translation: tuple[float, ...]
    units: tuple[str | None, ...]
    array_path: str | None = None

    @property
    def shape(self) -> tuple[int, ...]:
        return tuple(int(item) for item in self.data.shape)


def _default_axes(ndim: int) -> tuple[str, ...]:
    if ndim == 2:
        return ("y", "x")
    if ndim == 3:
        return ("z", "y", "x")
    raise ValueError(f"LayerLens requires a 2D or 3D spatial array, got {ndim} dimensions")


def _spatial_metadata(
    multiscale: dict[str, Any] | None,
    dataset: dict[str, Any] | None,
    ndim: int,
) -> tuple[
    tuple[str, ...], tuple[float, ...], tuple[float, ...], tuple[str | None, ...]
]:
    axes = _default_axes(ndim)
    units: tuple[str | None, ...] = (None,) * ndim
    if multiscale:
        raw_axes = multiscale.get("axes")
        if isinstance(raw_axes, list) and len(raw_axes) == ndim:
            names: list[str] = []
            parsed_units: list[str | None] = []
            for index, axis in enumerate(raw_axes):
                if isinstance(axis, str):
                    names.append(axis)
                    parsed_units.append(None)
                elif isinstance(axis, dict):
                    names.append(str(axis.get("name", axes[index])))
                    unit = axis.get("unit")
                    parsed_units.append(str(unit) if unit is not None else None)
                else:
                    names.append(axes[index])
                    parsed_units.append(None)
            axes = tuple(names)
            units = tuple(parsed_units)

    scale = (1.0,) * ndim
    translation = (0.0,) * ndim
    if dataset:
        for transform in dataset.get("coordinateTransformations", []):
            if not isinstance(transform, dict):
                continue
            values = transform.get(transform.get("type", ""))
            if not isinstance(values, list) or len(values) != ndim:
                continue
            parsed = tuple(float(item) for item in values)
            if transform.get("type") == "scale":
                scale = parsed
            elif transform.get("type") == "translation":
                translation = parsed
    return axes, scale, translation, units


def _ome_multiscale(group: zarr.Group, level: int) -> tuple[dict[str, Any], dict[str, Any]] | None:
    attributes = group.attrs.asdict()
    namespace = attributes.get("ome")
    containers = [namespace, attributes] if isinstance(namespace, dict) else [attributes]
    for container in containers:
        if not isinstance(container, dict):
            continue
        multiscales = container.get("multiscales")
        if not isinstance(multiscales, list) or not multiscales:
            continue
        multiscale = multiscales[0]
        datasets = multiscale.get("datasets") if isinstance(multiscale, dict) else None
        if not isinstance(datasets, list) or not 0 <= level < len(datasets):
            raise ValueError(f"OME-Zarr level {level} is unavailable")
        dataset = datasets[level]
        if not isinstance(dataset, dict) or not isinstance(dataset.get("path"), str):
            raise ValueError("OME-Zarr dataset entry has no array path")
        return multiscale, dataset
    return None


def _open_zarr(
    source: str,
    *,
    array_path: str | None,
    level: int,
    anonymous_s3: bool,
) -> OpenedVolume:
    storage_options: dict[str, Any] | None = None
    if source.startswith("s3://"):
        storage_options = {"anon": anonymous_s3}
    try:
        node = zarr.open(source, mode="r", storage_options=storage_options)
    except ImportError as error:
        if "://" in source:
            raise RuntimeError(
                "remote Zarr support is not installed; install layerlens[remote]"
            ) from error
        raise

    multiscale: dict[str, Any] | None = None
    dataset: dict[str, Any] | None = None
    resolved_path = array_path
    if isinstance(node, zarr.Group):
        if resolved_path is None:
            discovered = _ome_multiscale(node, level)
            if discovered is not None:
                multiscale, dataset = discovered
                resolved_path = str(dataset["path"])
            else:
                array_keys = tuple(node.array_keys())
                if "0" in array_keys:
                    resolved_path = "0"
                elif len(array_keys) == 1:
                    resolved_path = array_keys[0]
                else:
                    raise ValueError(
                        "Zarr group has no unambiguous image array; pass --array-path"
                    )
        data = node[resolved_path]
    else:
        if resolved_path is not None:
            raise ValueError("--array-path cannot be used when the Zarr root is already an array")
        data = node

    if not isinstance(data, zarr.Array):
        raise ValueError(f"resolved Zarr node {resolved_path!r} is not an array")
    axes, scale, translation, units = _spatial_metadata(multiscale, dataset, data.ndim)
    if not np.issubdtype(data.dtype, np.number):
        raise TypeError(f"expected numeric Zarr input, got {data.dtype}")
    return OpenedVolume(
        data=data,
        source=source,
        axes=axes,
        voxel_size=scale,
        translation=translation,
        units=units,
        array_path=resolved_path,
    )


def open_volume(
    source: str | Path,
    *,
    array_path: str | None = None,
    level: int = 0,
    anonymous_s3: bool = True,
) -> OpenedVolume:
    """Open a TIFF or Zarr spatial volume without materializing Zarr inputs."""

    source_text = str(source)
    lower = source_text.lower().split("?", maxsplit=1)[0]
    if lower.endswith((".tif", ".tiff")):
        if "://" in source_text:
            raise ValueError("remote TIFF input is not supported; use OME-Zarr")
        # Expose TIFF strips or tiles as a read-only Zarr array. This keeps
        # large TIFF inputs lazy while preserving ordinary NumPy slicing.
        store = tifffile.imread(source_text, aszarr=True)
        data = zarr.open(store, mode="r")
        if not isinstance(data, zarr.Array):
            raise ValueError("TIFF input does not resolve to one image array")
        axes = _default_axes(data.ndim)
        if not np.issubdtype(data.dtype, np.number):
            raise TypeError(f"expected numeric TIFF input, got {data.dtype}")
        return OpenedVolume(
            data=data,
            source=source_text,
            axes=axes,
            voxel_size=(1.0,) * data.ndim,
            translation=(0.0,) * data.ndim,
            units=(None,) * data.ndim,
        )
    return _open_zarr(
        source_text,
        array_path=array_path,
        level=level,
        anonymous_s3=anonymous_s3,
    )


def override_calibration(
    volume: OpenedVolume,
    *,
    voxel_size: Sequence[float] | None = None,
    unit: str | None = None,
) -> OpenedVolume:
    """Return an input descriptor with explicit spatial calibration overrides."""

    updates: dict[str, Any] = {}
    if voxel_size is not None:
        parsed = tuple(float(item) for item in voxel_size)
        if len(parsed) != len(volume.shape) or any(item <= 0 for item in parsed):
            raise ValueError(
                f"voxel size must contain {len(volume.shape)} positive numbers"
            )
        updates["voxel_size"] = parsed
    if unit is not None:
        updates["units"] = (unit,) * len(volume.shape)
    return replace(volume, **updates)
