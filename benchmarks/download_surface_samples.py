"""Download a reproducible random sample of official surface-label cubes."""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import tifffile


API_ROOT = "https://huggingface.co/api/buckets/scrollprize/datasets/tree"
RESOLVE_ROOT = "https://huggingface.co/buckets/scrollprize/datasets/resolve"
RELATIVE_ROOT = "surfaces/kaggle"


def _request_json(url: str, attempts: int = 6) -> Any:
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "layerlens/0.1"})
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except (OSError, urllib.error.URLError):
            if attempt + 1 == attempts:
                raise
            time.sleep(min(2**attempt, 16))
    raise AssertionError("unreachable")


def _listing(kind: str) -> dict[str, dict[str, Any]]:
    url = f"{API_ROOT}/{RELATIVE_ROOT}/{kind}?limit=1000"
    entries = _request_json(url)
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        name = Path(entry["path"]).stem
        result[name] = entry
    return result


def _download(entry: dict[str, Any], destination: Path, attempts: int = 6) -> Path:
    expected = int(entry["size"])
    if destination.exists() and destination.stat().st_size == expected:
        return destination
    part = destination.with_suffix(f"{destination.suffix}.part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = f"{RESOLVE_ROOT}/{entry['path']}"

    for attempt in range(attempts):
        aria2 = shutil.which("aria2c")
        if aria2 is not None:
            command = [
                aria2,
                "--allow-overwrite=true",
                "--auto-file-renaming=false",
                "--connect-timeout=30",
                "--continue=true",
                f"--dir={part.parent}",
                "--file-allocation=none",
                "--max-connection-per-server=8",
                "--max-tries=5",
                "--min-split-size=1M",
                f"--out={part.name}",
                "--retry-wait=2",
                "--split=8",
                "--summary-interval=0",
                "--timeout=90",
                url,
            ]
            process = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            if process.returncode == 0 and part.exists() and part.stat().st_size == expected:
                os.replace(part, destination)
                with tifffile.TiffFile(destination) as tiff:
                    if not tiff.series:
                        raise OSError(f"TIFF has no image series: {destination}")
                return destination

        offset = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": "layerlens/0.1"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                append = offset > 0 and response.status == 206
                with part.open("ab" if append else "wb") as handle:
                    while chunk := response.read(1024 * 1024):
                        handle.write(chunk)
            if part.stat().st_size != expected:
                raise OSError(
                    f"size mismatch for {destination.name}: "
                    f"{part.stat().st_size} != {expected}"
                )
            os.replace(part, destination)
            # Opening the series verifies that the file is a readable TIFF
            # without forcing a full-volume decode during download.
            with tifffile.TiffFile(destination) as tiff:
                if not tiff.series:
                    raise OSError(f"TIFF has no image series: {destination}")
            return destination
        except (OSError, urllib.error.URLError):
            if attempt + 1 == attempts:
                raise
            time.sleep(min(2**attempt, 16))
    raise AssertionError("unreachable")


def download_sample(
    *, count: int, seed: int, output: Path, manifest: Path, workers: int
) -> dict[str, Any]:
    images = _listing("images")
    labels = _listing("labels")
    available = sorted(images.keys() & labels.keys())
    if count < 1 or count > len(available):
        raise ValueError(f"count must be between 1 and {len(available)}")
    selected = sorted(random.Random(seed).sample(available, count))

    jobs: list[tuple[dict[str, Any], Path]] = []
    records: list[dict[str, Any]] = []
    for sample in selected:
        image_path = output / f"{sample}.image.tif"
        label_path = output / f"{sample}.label.tif"
        jobs.extend(((images[sample], image_path), (labels[sample], label_path)))
        records.append(
            {
                "sample": sample,
                "image": {
                    "path": str(image_path),
                    "size": int(images[sample]["size"]),
                    "xet_hash": images[sample].get("xetHash"),
                },
                "label": {
                    "path": str(label_path),
                    "size": int(labels[sample]["size"]),
                    "xet_hash": labels[sample].get("xetHash"),
                },
            }
        )

    payload = {
        "schema": "layerlens-surface-validation-sample-v1",
        "state": "downloading",
        "source": "ScrollPrize Vesuvius Challenge surface-label bucket",
        "api_root": API_ROOT,
        "population_size": len(available),
        "seed": seed,
        "count": count,
        "samples": records,
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_download, entry, path) for entry, path in jobs]
        for future in as_completed(futures):
            print(f"ready {future.result()}", flush=True)

    payload["state"] = "ready"
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--seed", type=int, default=20260718)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path, default=Path("data/raw/surface_kaggle"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/cache/surface_validation_manifest.json"),
    )
    args = parser.parse_args()
    payload = download_sample(
        count=args.count,
        seed=args.seed,
        output=args.output,
        manifest=args.manifest,
        workers=args.workers,
    )
    print(json.dumps({"count": payload["count"], "seed": payload["seed"]}))


if __name__ == "__main__":
    main()
