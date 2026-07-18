from __future__ import annotations

import numpy as np
import pytest

from benchmarks.synthetic import layered_phantom
from layerlens import compute_quality


def test_quality_shapes_and_bounds() -> None:
    volume = layered_phantom(size=32)
    result = compute_quality(volume, stride=4)
    assert result.quality.shape == (8, 8, 8)
    assert result.weight.shape == result.quality.shape
    assert result.stride == (4, 4, 4)
    assert 0.0 <= result.score <= 1.0
    assert np.all((result.quality >= 0.0) & (result.quality <= 1.0))
    assert np.isfinite(result.quality).all()
    assert np.all(result.weight >= 0.0)


def test_constant_input_is_zero_quality() -> None:
    result = compute_quality(np.ones((24, 24, 24), dtype=np.float32), stride=4)
    assert result.score == pytest.approx(0.0, abs=1e-8)


def test_rotation_and_affine_intensity_invariance() -> None:
    volume = layered_phantom(size=36, angle_degrees=37.0, seed=3)
    score = compute_quality(volume, stride=4).score
    rotated = compute_quality(np.rot90(volume, axes=(0, 2)), stride=4).score
    transformed = compute_quality(volume * 0.4 + 0.15, stride=4).score
    assert rotated == pytest.approx(score, rel=0.08)
    assert transformed == pytest.approx(score, rel=0.03)


def test_rejects_invalid_input() -> None:
    with pytest.raises(ValueError):
        compute_quality(np.zeros((2, 2, 2, 2), dtype=np.float32))
    with pytest.raises(ValueError):
        compute_quality(np.zeros((8, 8), dtype=np.float32), stride=(2, 2, 2))
    with pytest.raises(ValueError):
        compute_quality(np.zeros((8, 8), dtype=np.float32), normalization=(1.0, 1.0))
    with pytest.raises(ValueError, match="positive and finite"):
        compute_quality(np.zeros((8, 8), dtype=np.float32), tensor_sigma=float("nan"))


def test_explicit_normalization_matches_automatic_bounds() -> None:
    volume = layered_phantom(size=32, seed=41)
    bounds = tuple(float(item) for item in np.percentile(volume, (1.0, 99.0)))
    automatic = compute_quality(volume, stride=4)
    explicit = compute_quality(volume, stride=4, normalization=bounds)
    np.testing.assert_allclose(explicit.quality, automatic.quality, rtol=1e-6, atol=1e-7)
    assert explicit.score == pytest.approx(automatic.score, rel=1e-6)
