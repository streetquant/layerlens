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
    assert result.scan_axis_persistence.shape == result.quality.shape
    assert result.persistence_weight.shape == result.quality.shape
    assert result.stride == (4, 4, 4)
    assert 0.0 <= result.score <= 1.0
    assert 0.0 <= result.persistence_score <= 1.0
    assert np.all((result.quality >= 0.0) & (result.quality <= 1.0))
    assert np.all((result.scan_axis_persistence >= 0.0) & (result.scan_axis_persistence <= 1.0))
    assert np.isfinite(result.quality).all()
    assert np.isfinite(result.scan_axis_persistence).all()
    assert np.all(result.weight >= 0.0)
    assert np.all(result.persistence_weight >= 0.0)


def test_constant_input_is_zero_quality() -> None:
    result = compute_quality(np.ones((24, 24, 24), dtype=np.float32), stride=4)
    assert result.score == pytest.approx(0.0, abs=1e-8)
    assert result.persistence_score == pytest.approx(0.0, abs=1e-8)


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
    with pytest.raises(ValueError, match="positive and finite"):
        compute_quality(np.zeros((8, 8), dtype=np.float32), persistence_sigma=0.0)
    with pytest.raises(ValueError, match="scan_axis"):
        compute_quality(np.zeros((8, 8), dtype=np.float32), scan_axis=2)


def test_explicit_normalization_matches_automatic_bounds() -> None:
    volume = layered_phantom(size=32, seed=41)
    bounds = tuple(float(item) for item in np.percentile(volume, (1.0, 99.0)))
    automatic = compute_quality(volume, stride=4)
    explicit = compute_quality(volume, stride=4, normalization=bounds)
    np.testing.assert_allclose(explicit.quality, automatic.quality, rtol=1e-6, atol=1e-7)
    assert explicit.score == pytest.approx(automatic.score, rel=1e-6)


def test_scan_axis_persistence_detects_broadcast_structure() -> None:
    rng = np.random.default_rng(20260718)
    random_structure = rng.normal(0.0, 0.2, size=(40, 40, 40)).astype(np.float32)
    y, x = np.mgrid[:40, :40]
    pattern = 0.6 * np.sin(x / 2.3 + (y**2) / 19.0)
    broadcast = random_structure + pattern[np.newaxis, :, :].astype(np.float32)

    random_score = compute_quality(
        random_structure, stride=2, scan_axis=0, persistence_sigma=6.0
    ).persistence_score
    broadcast_result = compute_quality(broadcast, stride=2, scan_axis=0, persistence_sigma=6.0)
    wrong_axis_score = compute_quality(
        broadcast, stride=2, scan_axis=1, persistence_sigma=6.0
    ).persistence_score
    permuted_score = compute_quality(
        np.moveaxis(broadcast, 0, 2),
        stride=2,
        scan_axis=2,
        persistence_sigma=6.0,
    ).persistence_score

    assert broadcast_result.persistence_score > random_score + 0.25
    assert broadcast_result.persistence_score > wrong_axis_score + 0.15
    assert permuted_score == pytest.approx(broadcast_result.persistence_score, rel=2e-6)


def test_quality_score_remains_defined_only_by_original_components() -> None:
    result = compute_quality(layered_phantom(size=32, seed=43), stride=4)
    expected_quality = (
        np.power(result.coherence, 1.5) * np.power(result.sharpness, 1.5) * result.scale_sharpness
    ).astype(np.float32)
    np.testing.assert_array_equal(result.quality, expected_quality)
    expected_score = np.sum(result.quality * result.weight, dtype=np.float64) / np.sum(
        result.weight, dtype=np.float64
    )
    assert result.score == expected_score
