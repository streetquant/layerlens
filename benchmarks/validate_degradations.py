"""Measure LayerLens ordering under controlled degradation of official CT crops."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import tifffile
from scipy import ndimage as ndi
from scipy.stats import spearmanr

from layerlens import compute_quality


BLUR_SIGMAS = (0.0, 0.8, 1.6, 2.4)
NOISE_SIGMAS = (0.0, 0.02, 0.05, 0.10)


def _starts(length: int, size: int, step: int) -> tuple[int, ...]:
    if length < size:
        raise ValueError(f"dimension {length} is smaller than crop size {size}")
    starts = list(range(0, length - size + 1, step))
    if starts[-1] != length - size:
        starts.append(length - size)
    return tuple(starts)


def _label_rich_crop(
    image: np.ndarray,
    label: np.ndarray,
    *,
    size: int = 64,
    search_step: int = 32,
    search_subsample: int = 4,
) -> tuple[np.ndarray, dict[str, Any]]:
    if image.ndim != 3 or label.shape != image.shape:
        raise ValueError("official image and label must be matching 3D arrays")
    best_count = -1
    best_start: tuple[int, int, int] | None = None
    starts = [_starts(length, size, search_step) for length in image.shape]
    for z in starts[0]:
        for y in starts[1]:
            for x in starts[2]:
                sampled = label[
                    z : z + size : search_subsample,
                    y : y + size : search_subsample,
                    x : x + size : search_subsample,
                ]
                count = int(np.count_nonzero(sampled == 1))
                if count > best_count:
                    best_count = count
                    best_start = (z, y, x)
    assert best_start is not None
    selection = tuple(slice(start, start + size) for start in best_start)
    crop = np.asarray(image[selection], dtype=np.float32)
    crop_label = label[selection]
    lower, upper = (float(item) for item in np.percentile(crop, (1.0, 99.0)))
    if not upper > lower:
        raise ValueError("selected crop has no robust intensity range")
    crop = np.clip((crop - lower) / (upper - lower), 0.0, 1.0)
    return crop, {
        "start": list(best_start),
        "size": size,
        "selection_strategy": (
            f"maximum label-1 count on a {search_step}-voxel grid, "
            f"labels sampled every {search_subsample} voxels"
        ),
        "recto_fraction": float(np.mean(crop_label == 1)),
        "ignore_fraction": float(np.mean(crop_label == 2)),
        "normalization": {
            "percentile_low": 1.0,
            "percentile_high": 99.0,
            "lower": lower,
            "upper": upper,
        },
    }


def _quality_order_rank(levels: Sequence[float], scores: Sequence[float]) -> float:
    statistic = float(spearmanr(-np.asarray(levels), np.asarray(scores)).statistic)
    return statistic if np.isfinite(statistic) else 0.0


def _score_degradations(crop: np.ndarray, *, seed: int) -> dict[str, Any]:
    blur_scores = [
        compute_quality(
            crop if sigma == 0.0 else ndi.gaussian_filter(crop, sigma, mode="reflect"),
            stride=4,
            normalization=(0.0, 1.0),
        ).score
        for sigma in BLUR_SIGMAS
    ]
    rng = np.random.default_rng(seed)
    standard_noise = rng.standard_normal(crop.shape, dtype=np.float32)
    noise_scores = [
        compute_quality(
            crop
            if sigma == 0.0
            else np.clip(crop + sigma * standard_noise, 0.0, 1.0),
            stride=4,
            normalization=(0.0, 1.0),
        ).score
        for sigma in NOISE_SIGMAS
    ]

    def result(levels: Sequence[float], scores: list[float]) -> dict[str, Any]:
        return {
            "levels": list(levels),
            "scores": scores,
            "quality_order_rank": _quality_order_rank(levels, scores),
            "strictly_decreasing": bool(np.all(np.diff(scores) < 0.0)),
            "endpoint_relative_drop": float(
                (scores[0] - scores[-1]) / max(scores[0], 1e-12)
            ),
        }

    return {
        "blur": result(BLUR_SIGMAS, blur_scores),
        "noise": result(NOISE_SIGMAS, noise_scores),
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
        **_score_degradations(crop, seed=seed + numeric_id),
    }


def _bootstrap_mean_interval(
    values: np.ndarray, *, seed: int = 20260718, repetitions: int = 10_000
) -> list[float]:
    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(repetitions, len(values)), replace=True)
    return [float(item) for item in np.percentile(np.mean(draws, axis=1), (2.5, 97.5))]


def _sample_ids(manifest: Path | None, input_dir: Path) -> list[str]:
    if manifest is not None:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if payload.get("state", "ready") != "ready":
            raise RuntimeError(f"validation sample is not ready: {manifest}")
        return [str(entry["sample"]) for entry in payload["samples"]]
    images = {path.name.removesuffix(".image.tif") for path in input_dir.glob("*.image.tif")}
    labels = {path.name.removesuffix(".label.tif") for path in input_dir.glob("*.label.tif")}
    return sorted(images & labels)


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
            print(
                f"{result['sample']} blur_rank={result['blur']['quality_order_rank']:.3f} "
                f"noise_rank={result['noise']['quality_order_rank']:.3f}",
                flush=True,
            )
    results.sort(key=lambda item: item["sample"])

    blur_ranks = np.asarray(
        [item["blur"]["quality_order_rank"] for item in results], dtype=np.float64
    )
    noise_ranks = np.asarray(
        [item["noise"]["quality_order_rank"] for item in results], dtype=np.float64
    )
    blur_drops = np.asarray(
        [item["blur"]["endpoint_relative_drop"] for item in results], dtype=np.float64
    )
    noise_drops = np.asarray(
        [item["noise"]["endpoint_relative_drop"] for item in results], dtype=np.float64
    )
    combined_ranks = np.concatenate((blur_ranks, noise_ranks))
    payload = {
        "schema": "layerlens-controlled-degradation-validation-v1",
        "interpretation": (
            "These are nested synthetic perturbations of real official CT crops. They test "
            "expected response ordering, not performance against independent scan-quality "
            "ground truth. Labels select reproducible papyrus-rich crops and are never read "
            "by LayerLens."
        ),
        "protocol": {
            "seed": seed,
            "crop_size": crop_size,
            "blur_sigmas_voxels": list(BLUR_SIGMAS),
            "noise_sigmas_normalized_intensity": list(NOISE_SIGMAS),
            "normalization": "shared crop p1/p99 followed by fixed [0,1] metric bounds",
            "noise_nesting": "one standard-normal field scaled by every noise sigma",
        },
        "aggregate": {
            "cubes": len(results),
            "mean_blur_quality_order_rank": float(np.mean(blur_ranks)),
            "mean_blur_quality_order_rank_95ci": _bootstrap_mean_interval(blur_ranks),
            "mean_noise_quality_order_rank": float(np.mean(noise_ranks)),
            "mean_noise_quality_order_rank_95ci": _bootstrap_mean_interval(noise_ranks),
            "mean_combined_quality_order_rank": float(np.mean(combined_ranks)),
            "perfect_blur_orderings": int(
                np.count_nonzero(np.isclose(blur_ranks, 1.0, rtol=0.0, atol=1e-12))
            ),
            "perfect_noise_orderings": int(
                np.count_nonzero(np.isclose(noise_ranks, 1.0, rtol=0.0, atol=1e-12))
            ),
            "mean_blur_endpoint_relative_drop": float(np.mean(blur_drops)),
            "mean_noise_endpoint_relative_drop": float(np.mean(noise_drops)),
        },
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
        "--report", type=Path, default=Path("outputs/degradation_validation_report.json")
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
