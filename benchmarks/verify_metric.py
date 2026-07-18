"""Fast scalar benchmark used by the autonomous metric-improvement loop."""

from __future__ import annotations

from pathlib import Path

import imagecodecs
import numpy as np
from scipy import ndimage as ndi
from scipy.stats import rankdata, spearmanr

from layerlens import compute_quality

from .synthetic import layer_mask, layered_phantom


ROOT = Path(__file__).resolve().parents[1]


def _official_image(path: Path) -> np.ndarray:
    image = imagecodecs.imread(path)
    if image.ndim == 3:
        image = np.mean(image[..., :3], axis=-1)
    return image[5:-20, 5:-5]


def _intensity_auc(volume: np.ndarray, mask: np.ndarray) -> float:
    values = volume.ravel()
    foreground = mask.ravel()
    foreground_count = int(np.count_nonzero(foreground))
    background_count = int(foreground.size - foreground_count)
    ranks = rankdata(values, method="average")
    rank_sum = float(np.sum(ranks[foreground], dtype=np.float64))
    return (rank_sum - foreground_count * (foreground_count + 1) / 2) / (
        foreground_count * background_count
    )


def evaluate() -> tuple[float, dict[str, float]]:
    cases: list[np.ndarray] = []
    for blur in (0.4, 1.0, 1.8, 2.8):
        cases.append(layered_phantom(blur_sigma=blur, noise_sigma=0.02, seed=11))
    for noise in (0.01, 0.03, 0.06, 0.10):
        cases.append(layered_phantom(blur_sigma=0.5, noise_sigma=noise, seed=17))

    mask = layer_mask()
    truths = np.asarray([_intensity_auc(volume, mask) for volume in cases])
    predictions = np.asarray([compute_quality(volume, stride=4).score for volume in cases])
    rank = float(spearmanr(truths, predictions).statistic)

    reference = layered_phantom(size=44, angle_degrees=31.0, seed=23)
    base = compute_quality(reference, stride=4).score
    rotated = compute_quality(np.rot90(reference, axes=(1, 2)), stride=4).score
    transformed = compute_quality(reference * 0.37 + 0.21, stride=4).score
    invariance_error = (abs(base - rotated) + abs(base - transformed)) / max(2.0 * base, 1e-6)
    invariance = max(0.0, 1.0 - 5.0 * invariance_error)

    rng = np.random.default_rng(29)
    noise_only = rng.normal(0.5, 0.08, (44, 44, 44)).astype(np.float32)
    specificity = np.clip((base - compute_quality(noise_only, stride=4).score) / max(base, 1e-6), 0, 1)

    official_dir = ROOT / "data" / "raw" / "official_examples"
    low_path = official_dir / "paris4_dls_7.91um.jpg"
    high_path = official_dir / "paris4_esrf_2.4um.jpg"
    official_margin = 0.0
    if low_path.exists() and high_path.exists():
        low = compute_quality(_official_image(low_path), stride=4).score
        high = compute_quality(_official_image(high_path), stride=4).score
        official_margin = float(np.clip((high - low) / max(low, 1e-6), -1.0, 1.0))

    crop_path = ROOT / "data" / "cache" / "official_crops.npz"
    if not crop_path.exists():
        raise FileNotFoundError(
            f"missing {crop_path}; run python -m benchmarks.prepare_official_crops"
        )
    degradation_ranks: list[float] = []
    with np.load(crop_path) as crops:
        for name in crops.files:
            crop = crops[name].astype(np.float32) / 255.0
            blur_scores = [
                compute_quality(
                    crop if sigma == 0.0 else ndi.gaussian_filter(crop, sigma),
                    stride=4,
                ).score
                for sigma in (0.0, 0.8, 1.6, 2.4)
            ]
            degradation_ranks.append(
                float(spearmanr((1.0, 0.7, 0.4, 0.1), blur_scores).statistic)
            )
            rng = np.random.default_rng(20260717)
            noise_scores = [
                compute_quality(
                    np.clip(
                        crop + rng.normal(0.0, sigma, crop.shape).astype(np.float32),
                        0.0,
                        1.0,
                    ),
                    stride=4,
                ).score
                for sigma in (0.0, 0.02, 0.05, 0.10)
            ]
            degradation_ranks.append(
                float(spearmanr((1.0, 0.7, 0.4, 0.1), noise_scores).statistic)
            )
    real_degradation_rank = float(np.mean(degradation_ranks))

    metric = 40.0 * max(rank, -1.0) + 10.0 * invariance + 10.0 * specificity
    metric += 15.0 * max(official_margin, -1.0) + 25.0 * real_degradation_rank
    details = {
        "rank": rank,
        "invariance": float(invariance),
        "specificity": float(specificity),
        "official_margin": official_margin,
        "real_degradation_rank": real_degradation_rank,
    }
    return metric, details


def main() -> None:
    metric, details = evaluate()
    print(" ".join(f"{key}={value:.6f}" for key, value in details.items()))
    print(f"METRIC={metric:.6f}")


if __name__ == "__main__":
    main()
