"""Compare LayerLens with standard focus measures on official CT degradations."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
import tifffile
from scipy import ndimage as ndi

from layerlens import compute_quality

from .validate_degradations import (
    BLUR_SIGMAS,
    NOISE_SIGMAS,
    _bootstrap_mean_interval,
    _label_rich_crop,
    _quality_order_rank,
    _sample_ids,
)


ScoreFunction = Callable[[np.ndarray], float]


def tenengrad_score(volume: np.ndarray) -> float:
    """Return mean squared Sobel gradient magnitude (higher is sharper)."""

    energy = np.zeros(volume.shape, dtype=np.float32)
    for axis in range(volume.ndim):
        gradient = ndi.sobel(volume, axis=axis, mode="reflect")
        energy += np.square(gradient, dtype=np.float32)
    return float(np.mean(energy, dtype=np.float64))


def laplacian_variance_score(volume: np.ndarray) -> float:
    """Return variance of the discrete Laplacian (higher is sharper)."""

    response = ndi.laplace(volume, mode="reflect")
    return float(np.var(response, dtype=np.float64))


def layerlens_score(volume: np.ndarray) -> float:
    return compute_quality(volume, stride=4, normalization=(0.0, 1.0)).score


def _metric_result(
    levels: Sequence[float], scores: list[float]
) -> dict[str, Any]:
    return {
        "levels": list(levels),
        "scores": scores,
        "quality_order_rank": _quality_order_rank(levels, scores),
        "strictly_decreasing": bool(np.all(np.diff(scores) < 0.0)),
        "endpoint_relative_drop": float(
            (scores[0] - scores[-1]) / max(abs(scores[0]), 1e-12)
        ),
    }


def _score_metrics(crop: np.ndarray, *, seed: int) -> dict[str, Any]:
    blur_variants = [
        crop if sigma == 0.0 else ndi.gaussian_filter(crop, sigma, mode="reflect")
        for sigma in BLUR_SIGMAS
    ]
    rng = np.random.default_rng(seed)
    standard_noise = rng.standard_normal(crop.shape, dtype=np.float32)
    noise_variants = [
        crop
        if sigma == 0.0
        else np.clip(crop + sigma * standard_noise, 0.0, 1.0)
        for sigma in NOISE_SIGMAS
    ]
    metrics: tuple[tuple[str, ScoreFunction], ...] = (
        ("layerlens", layerlens_score),
        ("tenengrad", tenengrad_score),
        ("laplacian_variance", laplacian_variance_score),
    )
    return {
        name: {
            "blur": _metric_result(BLUR_SIGMAS, [score(item) for item in blur_variants]),
            "noise": _metric_result(NOISE_SIGMAS, [score(item) for item in noise_variants]),
        }
        for name, score in metrics
    }


def _analyze_one(sample: str, input_dir: str, crop_size: int, seed: int) -> dict[str, Any]:
    root = Path(input_dir)
    image = tifffile.imread(root / f"{sample}.image.tif")
    label = tifffile.imread(root / f"{sample}.label.tif")
    crop, crop_metadata = _label_rich_crop(image, label, size=crop_size)
    numeric_id = int(sample.rsplit("_", maxsplit=1)[-1])
    return {
        "sample": sample,
        "source_shape": list(image.shape),
        "crop": crop_metadata,
        "metrics": _score_metrics(crop, seed=seed + numeric_id),
    }


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate: dict[str, Any] = {}
    for name in ("layerlens", "tenengrad", "laplacian_variance"):
        blur_ranks = np.asarray(
            [item["metrics"][name]["blur"]["quality_order_rank"] for item in results],
            dtype=np.float64,
        )
        noise_ranks = np.asarray(
            [item["metrics"][name]["noise"]["quality_order_rank"] for item in results],
            dtype=np.float64,
        )
        blur_drops = np.asarray(
            [item["metrics"][name]["blur"]["endpoint_relative_drop"] for item in results],
            dtype=np.float64,
        )
        noise_drops = np.asarray(
            [item["metrics"][name]["noise"]["endpoint_relative_drop"] for item in results],
            dtype=np.float64,
        )
        aggregate[name] = {
            "mean_blur_quality_order_rank": float(np.mean(blur_ranks)),
            "mean_blur_quality_order_rank_95ci": _bootstrap_mean_interval(blur_ranks),
            "mean_noise_quality_order_rank": float(np.mean(noise_ranks)),
            "mean_noise_quality_order_rank_95ci": _bootstrap_mean_interval(noise_ranks),
            "mean_combined_quality_order_rank": float(
                np.mean(np.concatenate((blur_ranks, noise_ranks)))
            ),
            "perfect_blur_orderings": int(np.count_nonzero(np.isclose(blur_ranks, 1.0))),
            "perfect_noise_orderings": int(np.count_nonzero(np.isclose(noise_ranks, 1.0))),
            "mean_blur_endpoint_relative_drop": float(np.mean(blur_drops)),
            "mean_noise_endpoint_relative_drop": float(np.mean(noise_drops)),
        }
    return aggregate


def validate(
    *,
    samples: list[str],
    input_dir: Path,
    report: Path,
    crop_size: int,
    workers: int,
    seed: int = 20260718,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_analyze_one, sample, str(input_dir), crop_size, seed): sample
            for sample in samples
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            layerlens = result["metrics"]["layerlens"]
            print(
                f"{result['sample']} layerlens_blur={layerlens['blur']['quality_order_rank']:.3f} "
                f"layerlens_noise={layerlens['noise']['quality_order_rank']:.3f}",
                flush=True,
            )
    results.sort(key=lambda item: item["sample"])
    payload = {
        "schema": "layerlens-focus-baseline-comparison-v1",
        "interpretation": (
            "Standard focus measures are useful blur detectors but can reward added "
            "high-frequency noise. This fixed comparison tests whether each higher-is-better "
            "score orders nested blur and noise perturbations of the same official CT crops."
        ),
        "protocol": {
            "seed": seed,
            "crop_size": crop_size,
            "blur_sigmas_voxels": list(BLUR_SIGMAS),
            "noise_sigmas_normalized_intensity": list(NOISE_SIGMAS),
            "normalization": "shared crop p1/p99 followed by fixed [0,1] metric bounds",
            "noise_nesting": "one standard-normal field scaled by every noise sigma",
            "baselines": {
                "tenengrad": "mean squared 3D Sobel gradient magnitude",
                "laplacian_variance": "variance of the discrete 3D Laplacian",
            },
            "selection": "no baseline parameters were tuned on these cubes",
        },
        "aggregate": _aggregate(results),
        "cubes": results,
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw/surface_kaggle"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--samples", nargs="+", help="explicit sample IDs")
    parser.add_argument(
        "--report", type=Path, default=Path("outputs/baseline_comparison_report.json")
    )
    parser.add_argument("--crop-size", type=int, default=64)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260718)
    args = parser.parse_args()
    if args.manifest is not None and args.samples is not None:
        parser.error("--manifest and --samples are mutually exclusive")
    samples = args.samples or _sample_ids(args.manifest, args.input_dir)
    if not samples:
        parser.error("no complete image/label pairs found")
    payload = validate(
        samples=samples,
        input_dir=args.input_dir,
        report=args.report,
        crop_size=args.crop_size,
        workers=args.workers,
        seed=args.seed,
    )
    print(json.dumps(payload["aggregate"], indent=2))


if __name__ == "__main__":
    main()
