from __future__ import annotations

import json

import numpy as np
import pytest

from benchmarks.validate_surface_corpus import _recto_metrics, _sample_ids


def test_recto_metrics_exclude_ignore_and_respect_output_phase() -> None:
    quality = np.asarray([[0.9, 0.2], [0.1, 0.3]], dtype=np.float32)
    label = np.zeros((8, 8), dtype=np.uint8)
    label[2, 2] = 1
    label[6, 2] = 2

    result = _recto_metrics(quality, label, (4, 4))

    assert result["recto_voxels"] == 1
    assert result["other_voxels"] == 2
    assert result["recto_mean_quality"] == pytest.approx(0.9)
    assert result["other_mean_quality"] == pytest.approx(0.25)
    assert result["recto_quality_auc"] == 1.0


def test_pending_download_manifest_cannot_start_validation(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"state": "downloading", "samples": [{"sample": "sample_00001"}]})
    )

    with pytest.raises(RuntimeError, match="not ready"):
        _sample_ids(manifest, tmp_path)
