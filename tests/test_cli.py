from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import tifffile
import zarr

from benchmarks.synthetic import layered_phantom
from layerlens.cli import run


def test_cli_writes_calibrated_analysis_and_custom_summary(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source.tif"
    output = tmp_path / "analysis.zarr"
    summary_path = tmp_path / "summary.json"
    data = np.asarray(np.rint(layered_phantom(size=24, seed=103) * 65535), dtype=np.uint16)
    tifffile.imwrite(source, data, compression="deflate", photometric="minisblack")

    result = run(
        [
            str(source),
            str(output),
            "--stride",
            "2,2,2",
            "--tile-shape",
            "16,16,16",
            "--voxel-size",
            "2.4,2.4,2.4",
            "--unit",
            "micrometer",
            "--scan-axis",
            "2",
            "--persistence-sigma",
            "6.5",
            "--summary",
            str(summary_path),
        ]
    )

    printed = json.loads(capsys.readouterr().out)
    assert printed == result
    assert json.loads(summary_path.read_text()) == result
    assert result["input"]["voxel_size"] == [2.4, 2.4, 2.4]
    assert result["input"]["units"] == ["micrometer"] * 3
    assert result["parameters"]["stride"] == [2, 2, 2]
    assert result["parameters"]["scan_axis"] == 2
    assert result["parameters"]["scan_axis_name"] == "x"
    assert result["parameters"]["persistence_sigma"] == 6.5
    root = zarr.open_group(output, mode="r")
    transforms = root.attrs["ome"]["multiscales"][0]["datasets"][0][
        "coordinateTransformations"
    ]
    assert transforms[0]["scale"] == [1.0, 4.8, 4.8, 4.8]


@pytest.mark.parametrize(
    "arguments",
    [
        ["--stride", "2,0,2"],
        ["--voxel-size", "2.4,nan,2.4"],
        ["--gradient-sigma", "nan"],
        ["--tensor-sigma", "inf"],
        ["--persistence-sigma", "nan"],
    ],
)
def test_cli_rejects_invalid_numeric_options(arguments: list[str], tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="2"):
        run([str(tmp_path / "missing.tif"), str(tmp_path / "output.zarr"), *arguments])
