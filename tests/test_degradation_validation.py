from __future__ import annotations

import numpy as np

from benchmarks.synthetic import layered_phantom
from benchmarks.validate_degradations import (
    _label_rich_crop,
    _quality_order_rank,
    _score_degradations,
    _starts,
)


def test_crop_search_is_deterministic_and_includes_final_start() -> None:
    image = np.arange(26**3, dtype=np.float32).reshape((26,) * 3)
    label = np.zeros_like(image, dtype=np.uint8)
    label[18:26, 18:26, 18:26] = 1

    crop, metadata = _label_rich_crop(
        image, label, size=8, search_step=8, search_subsample=2
    )

    assert _starts(26, 8, 8) == (0, 8, 16, 18)
    assert metadata["start"] == [18, 18, 18]
    assert metadata["recto_fraction"] == 1.0
    assert crop.shape == (8, 8, 8)
    assert float(crop.min()) == 0.0
    assert float(crop.max()) == 1.0


def test_degradation_protocol_uses_shared_baseline_and_finite_ranks() -> None:
    crop = layered_phantom(size=28, seed=101)
    lower, upper = np.percentile(crop, (1.0, 99.0))
    crop = np.clip((crop - lower) / (upper - lower), 0.0, 1.0)

    result = _score_degradations(crop, seed=103)

    assert result["blur"]["scores"][0] == result["noise"]["scores"][0]
    assert len(result["blur"]["scores"]) == 4
    assert len(result["noise"]["scores"]) == 4
    assert np.isfinite(result["blur"]["quality_order_rank"])
    assert np.isfinite(result["noise"]["quality_order_rank"])
    assert _quality_order_rank((0.0, 1.0, 2.0), (0.8, 0.5, 0.2)) == 1.0
    assert _quality_order_rank((0.0, 1.0, 2.0), (0.2, 0.5, 0.8)) == -1.0
