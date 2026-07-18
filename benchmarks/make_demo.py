"""Build a shareable LayerLens walkthrough from a deterministic synthetic volume."""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from pathlib import Path

import numpy as np
import tifffile
import zarr
from numcodecs import Blosc
from scipy import ndimage as ndi

from layerlens import analyze_to_ome_zarr, open_volume
from layerlens.report import render_report
from layerlens.vc3d import export_vc3d_overlay, write_vc3d_project

from .synthetic import layered_phantom


def demo_volume(size: int = 96) -> np.ndarray:
    """Create a layered volume whose right side has locally degraded separability."""

    sharp = layered_phantom(
        size=size,
        angle_degrees=31.0,
        blur_sigma=0.35,
        noise_sigma=0.012,
        seed=20260717,
    )
    blurred = ndi.gaussian_filter(sharp, sigma=2.2, mode="reflect")
    coordinate = np.linspace(-1.0, 1.0, size, dtype=np.float32)
    transition = 1.0 / (1.0 + np.exp(-10.0 * coordinate))
    blend = transition[None, None, :]
    return np.asarray(sharp * (1.0 - blend) + blurred * blend, dtype=np.float32)


def write_demo_vc3d_base(
    volume: np.ndarray,
    output: Path,
    *,
    overwrite: bool = False,
) -> None:
    """Write the small demo source as a directly readable VC3D base volume."""

    if output.exists() and not overwrite:
        raise FileExistsError(f"VC3D demo base already exists: {output}")
    if volume.ndim != 3 or any(size < 1 for size in volume.shape):
        raise ValueError("VC3D demo base must be a non-empty ZYX volume")
    if not np.isfinite(volume).all():
        raise ValueError("VC3D demo base contains non-finite values")

    encoded = np.asarray(np.rint(np.clip(volume, 0.0, 1.0) * 65535.0), dtype=np.uint16)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    try:
        root = zarr.open_group(temporary, mode="w", zarr_format=2)
        root.create_array(
            "0",
            data=encoded,
            chunks=tuple(min(64, size) for size in encoded.shape),
            compressor=Blosc(cname="zstd", clevel=5, shuffle=Blosc.SHUFFLE),
            overwrite=True,
        )
        root.attrs.update(
            {
                "note_axes_order": "ZYX (slice, row, col)",
                "multiscales": [
                    {
                        "version": "0.4",
                        "name": "LayerLens deterministic demo base",
                        "axes": [
                            {"name": "z", "type": "space"},
                            {"name": "y", "type": "space"},
                            {"name": "x", "type": "space"},
                        ],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [1.0, 1.0, 1.0]}
                                ],
                            }
                        ],
                        "metadata": {"downsampling_method": "none"},
                    }
                ],
            }
        )
        slices, height, width = (int(size) for size in encoded.shape)
        metadata = {
            "type": "vol",
            "uuid": "layerlens-demo-base",
            "name": "LayerLens deterministic demo base",
            "format": "zarr",
            "width": width,
            "height": height,
            "slices": slices,
            "voxelsize": 1.0,
            "min": 0.0,
            "max": 65535.0,
        }
        (temporary / "meta.json").write_text(
            json.dumps(metadata, indent=2) + "\n",
            encoding="utf-8",
        )
        if output.is_symlink() or output.is_file():
            output.unlink()
        elif output.exists():
            shutil.rmtree(output)
        temporary.replace(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def build_demo(output_dir: Path, *, size: int = 96, overwrite: bool = False) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source = output_dir / "layerlens-demo.tif"
    analysis = output_dir / "layerlens-demo.zarr"
    report = output_dir / "layerlens-demo.html"
    vc3d_base = output_dir / "layerlens-demo.base.ome.zarr"
    vc3d_overlay = output_dir / "layerlens-demo.vc3d.ome.zarr"
    vc3d_project = output_dir / "layerlens-demo.volpkg.json"
    destinations = (source, analysis, report, vc3d_base, vc3d_overlay, vc3d_project)
    if not overwrite:
        existing = next((path for path in destinations if path.exists()), None)
        if existing is not None:
            raise FileExistsError(f"demo artifact already exists: {existing}")

    volume = demo_volume(size)
    encoded = np.asarray(np.rint(volume * 65535.0), dtype=np.uint16)
    tifffile.imwrite(source, encoded, compression="deflate", photometric="minisblack")
    opened = open_volume(source)
    analyze_to_ome_zarr(
        opened,
        analysis,
        stride=2,
        tile_shape=64,
        overwrite=overwrite,
    )
    render_report(
        opened,
        analysis,
        report,
        axis="z",
        index=size // 2,
        overwrite=overwrite,
    )
    write_demo_vc3d_base(volume, vc3d_base, overwrite=overwrite)
    export_vc3d_overlay(
        analysis,
        vc3d_overlay,
        name="LayerLens demo low-quality risk",
        uuid="layerlens-demo-risk",
        overwrite=overwrite,
    )
    write_vc3d_project(
        vc3d_project,
        base_volume=vc3d_base,
        overlay_volume=vc3d_overlay,
        name="LayerLens deterministic quality review",
        overwrite=overwrite,
    )
    return {
        "source": str(source),
        "analysis": str(analysis),
        "report": str(report),
        "vc3d_base": str(vc3d_base),
        "vc3d_overlay": str(vc3d_overlay),
        "vc3d_project": str(vc3d_project),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/demo"))
    parser.add_argument("--size", type=int, default=96)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.size < 24:
        parser.error("--size must be at least 24")
    print(json.dumps(build_demo(args.output_dir, size=args.size, overwrite=args.overwrite), indent=2))


if __name__ == "__main__":
    main()
