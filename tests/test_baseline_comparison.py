from __future__ import annotations

import numpy as np

from benchmarks.compare_baselines import (
    _score_metrics,
    laplacian_variance_score,
    tenengrad_score,
)
from benchmarks.synthetic import layered_phantom


def test_focus_baselines_are_zero_for_constant_volume() -> None:
    constant = np.ones((16, 16, 16), dtype=np.float32)
    assert tenengrad_score(constant) == 0.0
    assert laplacian_variance_score(constant) == 0.0


def test_metric_comparison_is_deterministic_and_finite() -> None:
    crop = layered_phantom(size=32, seed=20260720).astype(np.float32, copy=False)
    first = _score_metrics(crop, seed=19)
    second = _score_metrics(crop, seed=19)
    assert first == second
    assert set(first) == {"layerlens", "tenengrad", "laplacian_variance"}
    for metric in first.values():
        for degradation in metric.values():
            assert len(degradation["scores"]) == 4
            assert np.isfinite(degradation["scores"]).all()
            assert -1.0 <= degradation["quality_order_rank"] <= 1.0
