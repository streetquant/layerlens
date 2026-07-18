"""Prepare small, ignored validation crops from official surface-label cubes."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import tifffile


SAMPLE_IDS = ("00001", "00916")


def _label_rich_crop(image: np.ndarray, label: np.ndarray, size: int = 64) -> np.ndarray:
    best: tuple[int, tuple[slice, slice, slice]] | None = None
    for z in range(0, image.shape[0] - size + 1, 32):
        for y in range(0, image.shape[1] - size + 1, 32):
            for x in range(0, image.shape[2] - size + 1, 32):
                region = np.s_[z : z + size, y : y + size, x : x + size]
                foreground = int(np.count_nonzero(label[region] == 1))
                if best is None or foreground > best[0]:
                    best = (foreground, region)
    if best is None:
        raise ValueError("volume is smaller than the requested crop")
    return image[best[1]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path("data/raw/surface_kaggle"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/cache/official_crops.npz"),
    )
    args = parser.parse_args()

    crops: dict[str, np.ndarray] = {}
    for sample_id in SAMPLE_IDS:
        image = tifffile.imread(args.dataset_dir / f"sample_{sample_id}.image.tif")
        label = tifffile.imread(args.dataset_dir / f"sample_{sample_id}.label.tif")
        crops[f"sample_{sample_id}"] = _label_rich_crop(image, label)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output, **crops)
    print(args.output)


if __name__ == "__main__":
    main()

