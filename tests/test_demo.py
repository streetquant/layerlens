from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import zarr

from benchmarks.make_demo import build_demo, demo_volume
from layerlens import compute_quality


def test_demo_has_locally_degraded_separability() -> None:
    volume = demo_volume(32)
    quality = compute_quality(volume, stride=4).quality

    assert volume.shape == (32, 32, 32)
    assert np.isfinite(volume).all()
    assert float(volume.min()) >= 0.0
    assert float(volume.max()) <= 1.0
    assert float(np.mean(quality[..., :3])) > float(np.mean(quality[..., -3:]))


def test_build_demo_includes_portable_vc3d_project(tmp_path: Path) -> None:
    result = build_demo(tmp_path, size=32)

    assert set(result) == {
        "source",
        "analysis",
        "report",
        "vc3d_base",
        "vc3d_overlay",
        "vc3d_project",
    }
    assert all(Path(path).exists() for path in result.values())

    base = zarr.open_group(result["vc3d_base"], mode="r")
    assert tuple(base["0"].shape) == (32, 32, 32)
    assert base["0"].dtype == np.dtype("uint16")
    assert base.attrs["multiscales"][0]["datasets"][0]["path"] == "0"
    base_metadata = json.loads((Path(result["vc3d_base"]) / "meta.json").read_text())
    assert base_metadata["uuid"] == "layerlens-demo-base"
    assert base_metadata["width"] == 32

    project = json.loads(Path(result["vc3d_project"]).read_text())
    assert project["volumes"] == [
        "layerlens-demo.base.ome.zarr",
        {"location": "layerlens-demo.vc3d.ome.zarr", "tags": ["layerlens-overlay"]},
    ]
