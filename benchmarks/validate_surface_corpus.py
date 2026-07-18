"""Run LayerLens over official labeled cubes and summarize recto enrichment."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import tifffile
import zarr
from scipy.stats import rankdata

from layerlens import analyze_to_ome_zarr, open_volume


def _auc(values: np.ndarray, positive: np.ndarray) -> float:
    positive_count = int(np.count_nonzero(positive))
    negative_count = int(positive.size - positive_count)
    if positive_count == 0 or negative_count == 0:
        return float("nan")
    ranks = rankdata(values, method="average")
    rank_sum = float(np.sum(ranks[positive], dtype=np.float64))
    return (rank_sum - positive_count * (positive_count + 1) / 2) / (
        positive_count * negative_count
    )


def _recto_metrics(
    quality: np.ndarray, label: np.ndarray, stride: tuple[int, ...]
) -> dict[str, float | int]:
    offset = tuple(step // 2 for step in stride)
    selection = tuple(slice(start, None, step) for start, step in zip(offset, stride, strict=True))
    sampled_label = label[selection]
    if sampled_label.shape != quality.shape:
        raise ValueError(
            f"quality/label shape mismatch: {quality.shape} != {sampled_label.shape}"
        )
    valid = sampled_label != 2
    positive = sampled_label[valid] == 1
    values = quality[valid]
    recto_mean = float(np.mean(values[positive]))
    other_mean = float(np.mean(values[~positive]))
    return {
        "recto_voxels": int(np.count_nonzero(positive)),
        "other_voxels": int(np.count_nonzero(~positive)),
        "recto_mean_quality": recto_mean,
        "other_mean_quality": other_mean,
        "recto_quality_delta": recto_mean - other_mean,
        "recto_quality_auc": _auc(values, positive),
    }


def _analyze_one(
    sample: str,
    input_dir: str,
    output_dir: str,
    tile_shape: int,
) -> dict[str, Any]:
    image_path = Path(input_dir) / f"{sample}.image.tif"
    label_path = Path(input_dir) / f"{sample}.label.tif"
    destination = Path(output_dir) / f"{sample}.layerlens.zarr"
    summary_path = Path(f"{destination}.json")
    shared_destination = Path(output_dir).parent / f"{sample}.layerlens.zarr"
    shared_summary = Path(f"{shared_destination}.json")
    if not destination.exists() and shared_destination.exists() and shared_summary.exists():
        destination = shared_destination
        summary_path = shared_summary
    if destination.exists() and summary_path.exists():
        summary = json.loads(summary_path.read_text())
    else:
        summary = analyze_to_ome_zarr(
            open_volume(image_path), destination, tile_shape=tile_shape
        )
    root = zarr.open_group(destination, mode="r")
    quality = np.asarray(root["0"][0])
    label = tifffile.imread(label_path)
    stride = tuple(int(item) for item in summary["parameters"]["stride"])
    return {
        "sample": sample,
        "shape": summary["input"]["shape"],
        "score": summary["metrics"]["score"],
        "poor_fraction": summary["metrics"]["poor_fraction"],
        "runtime_seconds": summary["runtime"]["seconds"],
        **_recto_metrics(quality, label, stride),
    }


def _bootstrap_mean_interval(
    values: np.ndarray, *, seed: int = 20260718, repetitions: int = 10_000
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=(repetitions, len(values)), replace=True)
    means = np.mean(samples, axis=1)
    return tuple(float(item) for item in np.percentile(means, (2.5, 97.5)))


def _sample_ids(manifest: Path | None, input_dir: Path) -> list[str]:
    if manifest is not None:
        payload = json.loads(manifest.read_text())
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
    output_dir: Path,
    report: Path,
    tile_shape: int,
    workers: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _analyze_one, sample, str(input_dir), str(output_dir), tile_shape
            ): sample
            for sample in samples
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(
                f"{result['sample']} score={result['score']:.3f} "
                f"recto_auc={result['recto_quality_auc']:.3f}",
                flush=True,
            )
    results.sort(key=lambda item: item["sample"])

    aucs = np.asarray([item["recto_quality_auc"] for item in results], dtype=np.float64)
    deltas = np.asarray([item["recto_quality_delta"] for item in results], dtype=np.float64)
    scores = np.asarray([item["score"] for item in results], dtype=np.float64)
    auc_interval = _bootstrap_mean_interval(aucs)
    delta_interval = _bootstrap_mean_interval(deltas)
    payload = {
        "schema": "layerlens-surface-corpus-validation-v1",
        "interpretation": (
            "Recto enrichment is an external localization diagnostic, not a supervised "
            "training target or a complete scan-quality ground truth. Label 0 can contain "
            "legitimate non-recto papyrus structure; label 2 is excluded."
        ),
        "aggregate": {
            "cubes": len(results),
            "recto_mean_exceeds_other": int(np.count_nonzero(deltas > 0.0)),
            "mean_recto_quality_auc": float(np.mean(aucs)),
            "mean_recto_quality_auc_95ci": list(auc_interval),
            "mean_recto_quality_delta": float(np.mean(deltas)),
            "mean_recto_quality_delta_95ci": list(delta_interval),
            "median_cube_score": float(np.median(scores)),
        },
        "cubes": results,
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw/surface_kaggle"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/surface_validation"))
    parser.add_argument(
        "--report", type=Path, default=Path("outputs/surface_validation_report.json")
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--samples", nargs="+", help="explicit sample IDs")
    parser.add_argument("--tile-shape", type=int, default=160)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.manifest is not None and args.samples is not None:
        parser.error("--manifest and --samples are mutually exclusive")
    samples = args.samples or _sample_ids(args.manifest, args.input_dir)
    payload = validate(
        samples=samples,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        report=args.report,
        tile_shape=args.tile_shape,
        workers=args.workers,
    )
    print(json.dumps(payload["aggregate"], indent=2))


if __name__ == "__main__":
    main()
