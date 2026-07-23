"""Create a self-contained visual QC report from a LayerLens OME-Zarr store."""

from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path
from typing import Any, Sequence

import imagecodecs
import numpy as np
import zarr
from scipy import ndimage as ndi

from . import __version__
from .io import OpenedVolume, open_volume


def _image_data_url(image: np.ndarray) -> str:
    encoded = imagecodecs.png_encode(np.ascontiguousarray(image, dtype=np.uint8))
    return "data:image/png;base64," + base64.b64encode(encoded).decode("ascii")


def _normalize_plane(plane: np.ndarray, lower: float, upper: float) -> np.ndarray:
    values = np.asarray(plane, dtype=np.float32)
    values = np.nan_to_num(values, nan=lower, posinf=upper, neginf=lower)
    values = np.clip((values - lower) / (upper - lower), 0.0, 1.0)
    return np.asarray(np.rint(values * 255.0), dtype=np.uint8)


def _quality_colors(values: np.ndarray) -> np.ndarray:
    positions = np.asarray((0.0, 0.25, 0.5, 0.75, 1.0), dtype=np.float32)
    controls = np.asarray(
        (
            (92, 10, 42),
            (221, 51, 55),
            (246, 174, 45),
            (42, 190, 121),
            (54, 190, 225),
        ),
        dtype=np.float32,
    )
    clipped = np.clip(values, 0.0, 1.0)
    channels = [np.interp(clipped, positions, controls[:, index]) for index in range(3)]
    return np.asarray(np.rint(np.stack(channels, axis=-1)), dtype=np.uint8)


def _persistence_colors(values: np.ndarray) -> np.ndarray:
    positions = np.asarray((0.0, 0.35, 0.7, 1.0), dtype=np.float32)
    controls = np.asarray(
        ((12, 19, 43), (49, 84, 150), (231, 111, 81), (255, 226, 120)),
        dtype=np.float32,
    )
    clipped = np.clip(values, 0.0, 1.0)
    channels = [np.interp(clipped, positions, controls[:, index]) for index in range(3)]
    return np.asarray(np.rint(np.stack(channels, axis=-1)), dtype=np.uint8)


def _resize(values: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    factors = tuple(target / current for target, current in zip(shape, values.shape, strict=True))
    resized = ndi.zoom(values, factors, order=1, mode="nearest", prefilter=False)
    result = np.empty(shape, dtype=np.float32)
    common = tuple(slice(0, min(left, right)) for left, right in zip(shape, resized.shape, strict=True))
    result.fill(0.0)
    result[common] = resized[common]
    return result


def _auto_plane(quality: np.ndarray, confidence: np.ndarray) -> tuple[int, int]:
    best_axis = 0
    best_index = 0
    best_score = -1.0
    risk = (1.0 - quality) * confidence
    for axis, length in enumerate(quality.shape):
        other_axes = tuple(index for index in range(quality.ndim) if index != axis)
        scores = np.mean(risk, axis=other_axes)
        margin = max(1, length // 20)
        candidates = scores[margin : length - margin]
        if candidates.size == 0:
            candidates = scores
            margin = 0
        local_index = int(np.argmax(candidates)) + margin
        value = float(scores[local_index])
        if value > best_score:
            best_axis, best_index, best_score = axis, local_index, value
    return best_axis, best_index


def _histogram_svg(values: np.ndarray, bins: int = 64) -> str:
    counts = np.histogram(values, bins=bins, range=(0.0, 1.0))[0]
    maximum = max(int(counts.max()), 1)
    width, height = 640, 150
    bar_width = width / bins
    bars = []
    for index, count in enumerate(counts):
        bar_height = 130.0 * int(count) / maximum
        x = index * bar_width
        y = 135.0 - bar_height
        color = "#dd3337" if index < bins // 4 else "#2abe79"
        bars.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width + 0.2:.2f}" '
            f'height="{bar_height:.2f}" fill="{color}" />'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Quality value histogram">'
        '<line x1="0" y1="135" x2="640" y2="135" stroke="#9fa5b4" />'
        + "".join(bars)
        + '<text x="0" y="149" fill="#9fa5b4" font-size="12">0 low</text>'
        + '<text x="600" y="149" fill="#9fa5b4" font-size="12">high 1</text>'
        + "</svg>"
    )


def _analysis_summary(root: zarr.Group, analysis_path: Path) -> dict[str, Any]:
    companion = Path(f"{analysis_path}.json")
    if companion.exists():
        return json.loads(companion.read_text(encoding="utf-8"))
    summary = root.attrs.get("layerlens")
    if not isinstance(summary, dict):
        raise ValueError("analysis store has no LayerLens summary")
    return summary


def _source_plane(
    volume: OpenedVolume, axis: int | None, index: int | None
) -> np.ndarray:
    if len(volume.shape) == 2:
        return np.asarray(volume.data[:, :])
    assert axis is not None and index is not None
    selection: list[int | slice] = [slice(None)] * 3
    selection[axis] = index
    return np.asarray(volume.data[tuple(selection)])


def _map_plane(values: np.ndarray, axis: int | None, index: int | None) -> np.ndarray:
    if values.ndim == 2:
        return values
    assert axis is not None and index is not None
    return np.take(values, index, axis=axis)


def render_report(
    volume: OpenedVolume,
    analysis: str | Path,
    output: str | Path,
    *,
    axis: str = "auto",
    index: int | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write a self-contained HTML quality report and return its view metadata."""

    analysis_path = Path(analysis)
    output_path = Path(output)
    if output_path.resolve() == analysis_path.resolve():
        raise ValueError("analysis and report paths must be different")
    if "://" not in volume.source and Path(volume.source).resolve() == output_path.resolve():
        raise ValueError("input and report paths must be different")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"report already exists: {output_path}")

    root = zarr.open_group(analysis_path, mode="r")
    maps = root["0"]
    if maps.shape[0] < 5:
        raise ValueError("analysis array does not contain all LayerLens channels")
    quality = np.asarray(maps[0], dtype=np.float32)
    confidence = np.asarray(maps[4], dtype=np.float32)
    persistence = np.asarray(maps[5], dtype=np.float32) if maps.shape[0] >= 6 else None
    summary = _analysis_summary(root, analysis_path)
    if tuple(summary["input"]["shape"]) != volume.shape:
        raise ValueError("source shape does not match the analysis provenance")
    if quality.ndim not in (2, 3):
        raise ValueError("analysis maps must be two- or three-dimensional")
    if quality.ndim == 2 and (axis != "auto" or index is not None):
        raise ValueError("--axis and --index apply only to 3D inputs")
    if quality.ndim == 3 and axis == "auto" and index is not None:
        raise ValueError("--index requires an explicit --axis")

    selected_axis: int | None = None
    map_index: int | None = None
    input_index: int | None = None
    if quality.ndim == 3:
        if axis == "auto":
            selected_axis, map_index = _auto_plane(quality, confidence)
        else:
            names = tuple(str(item) for item in summary["input"]["axes"])
            try:
                selected_axis = names.index(axis) if not axis.isdigit() else int(axis)
            except ValueError as error:
                raise ValueError(f"axis must be auto, an axis name, or 0-{quality.ndim - 1}") from error
            if not 0 <= selected_axis < quality.ndim:
                raise ValueError(f"axis index is outside 0-{quality.ndim - 1}")
            if index is None:
                risk = (1.0 - quality) * confidence
                other = tuple(item for item in range(3) if item != selected_axis)
                map_index = int(np.argmax(np.mean(risk, axis=other)))
            else:
                if not 0 <= index < volume.shape[selected_axis]:
                    raise ValueError(
                        f"input index is outside 0-{volume.shape[selected_axis] - 1}"
                    )
                stride = int(summary["parameters"]["stride"][selected_axis])
                offset = stride // 2
                map_index = int(round((index - offset) / stride))
        assert selected_axis is not None and map_index is not None
        map_index = int(np.clip(map_index, 0, quality.shape[selected_axis] - 1))
        stride = int(summary["parameters"]["stride"][selected_axis])
        input_index = stride // 2 + map_index * stride
        input_index = min(input_index, volume.shape[selected_axis] - 1)

    source = _source_plane(volume, selected_axis, input_index)
    quality_plane = _map_plane(quality, selected_axis, map_index)
    confidence_plane = _map_plane(confidence, selected_axis, map_index)
    persistence_plane = (
        _map_plane(persistence, selected_axis, map_index) if persistence is not None else None
    )
    normalization = summary["parameters"]["normalization"]
    grayscale = _normalize_plane(source, normalization["lower"], normalization["upper"])
    target_shape = tuple(int(item) for item in grayscale.shape)
    quality_large = _resize(quality_plane, target_shape)
    confidence_large = _resize(confidence_plane, target_shape)
    colors = _quality_colors(quality_large)
    gray_rgb = np.repeat(grayscale[..., None], 3, axis=-1)
    alpha = np.clip(0.15 + 0.65 * confidence_large, 0.0, 0.8)[..., None]
    overlay = np.asarray(
        np.rint(gray_rgb * (1.0 - alpha) + colors * alpha), dtype=np.uint8
    )
    persistence_image = (
        _persistence_colors(_resize(persistence_plane, target_shape))
        if persistence_plane is not None
        else None
    )
    persistence_figure = (
        ""
        if persistence_image is None
        else (
            f'<figure><img src="{_image_data_url(persistence_image)}" '
            'alt="Scan-axis persistence heatmap"><figcaption><strong>Scan-axis '
            'persistence</strong>Persistent transverse structure; not an artifact '
            'probability</figcaption></figure>'
        )
    )

    metrics = summary["metrics"]
    cards = [
        ("LayerLens score", f"{metrics['score']:.3f}"),
        ("Poor fraction", f"{100 * metrics['poor_fraction']:.1f}%"),
        ("Median quality", f"{metrics['quality_p50']:.3f}"),
    ]
    if "scan_axis_persistence_score" in metrics:
        cards.append(
            ("Scan-axis persistence", f"{metrics['scan_axis_persistence_score']:.3f}")
        )
    cards.append(("Analysis runtime", f"{summary['runtime']['seconds']:.1f}s"))
    card_html = "".join(
        f'<div class="card"><span>{html.escape(label)}</span><strong>{value}</strong></div>'
        for label, value in cards
    )
    axis_name = (
        "full 2D image"
        if selected_axis is None
        else f"{summary['input']['axes'][selected_axis]} = {input_index}"
    )
    provenance = json.dumps(
        {
            "input": summary["input"],
            "parameters": summary["parameters"],
            "output": summary["output"],
        },
        indent=2,
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>LayerLens quality report</title>
<style>
:root {{ color-scheme: dark; --bg:#0d111b; --panel:#151b29; --line:#283044;
  --text:#eef2f8; --muted:#9fa9ba; --accent:#35bea0; }}
* {{ box-sizing:border-box }} body {{ margin:0; background:radial-gradient(circle at 20% 0,#182238,#0d111b 48%);
  color:var(--text); font:15px/1.5 Inter,ui-sans-serif,system-ui,sans-serif; }}
main {{ max-width:1500px; margin:auto; padding:42px 28px 64px }}
header {{ display:flex; align-items:end; justify-content:space-between; gap:20px; margin-bottom:25px }}
h1 {{ font-size:34px; margin:0; letter-spacing:-.04em }} h2 {{ font-size:19px; margin:0 0 14px }}
.eyebrow {{ color:var(--accent); text-transform:uppercase; font-size:12px; font-weight:750; letter-spacing:.13em }}
.muted {{ color:var(--muted) }} .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin:18px 0 24px }}
.card,.block {{ background:rgba(21,27,41,.9); border:1px solid var(--line); border-radius:13px; box-shadow:0 15px 35px #0004 }}
.card {{ padding:15px 18px }} .card span {{ display:block; color:var(--muted); font-size:12px }} .card strong {{ font-size:25px }}
.panels {{ display:grid; grid-template-columns:repeat(2,1fr); gap:13px }} figure {{ margin:0; overflow:hidden; background:var(--panel); border:1px solid var(--line); border-radius:13px }}
figure img {{ display:block; width:100%; aspect-ratio:1/1; object-fit:contain; background:#05070c; image-rendering:auto }}
figcaption {{ padding:11px 14px; color:var(--muted) }} figcaption strong {{ color:var(--text); display:block }}
.lower {{ display:grid; grid-template-columns:1.25fr .75fr; gap:13px; margin-top:13px }} .block {{ padding:18px }}
.gradient {{ height:9px; border-radius:9px; background:linear-gradient(90deg,#5c0a2a,#dd3337,#f6ae2d,#2abe79,#36bee1); margin-top:8px }}
details pre {{ overflow:auto; color:#c7d1df; font-size:12px; white-space:pre-wrap }}
@media(max-width:900px) {{ .cards,.panels,.lower {{ grid-template-columns:1fr 1fr }} }}
@media(max-width:620px) {{ .cards,.panels,.lower {{ grid-template-columns:1fr }} header {{ display:block }} }}
</style></head>
<body><main>
<header><div><div class="eyebrow">Reference-free CT quality control</div><h1>LayerLens report</h1>
<div class="muted">{html.escape(str(summary['input']['source']))}</div></div>
<div class="muted">LayerLens {__version__}<br>{html.escape(axis_name)}</div></header>
<section class="cards">{card_html}</section>
<section class="panels">
<figure><img src="{_image_data_url(gray_rgb)}" alt="Normalized source CT plane"><figcaption><strong>Source CT</strong>Global p1/p99 normalization</figcaption></figure>
<figure><img src="{_image_data_url(colors)}" alt="LayerLens quality heatmap"><figcaption><strong>Quality map</strong>Low red · high cyan<div class="gradient"></div></figcaption></figure>
<figure><img src="{_image_data_url(overlay)}" alt="Quality map overlaid on source CT"><figcaption><strong>Evidence-weighted overlay</strong>Opacity follows confidence</figcaption></figure>
{persistence_figure}
</section>
<section class="lower"><div class="block"><h2>Quality distribution</h2>{_histogram_svg(quality)}</div>
<div class="block"><h2>Interpretation</h2><p>Low quality values identify locally weak, blurred, or directionally disorganized interfaces. Elevated scan-axis persistence identifies transverse structure that remains similar along the selected acquisition axis. Inspect the component channels before treating either signal as unusable data or an artifact.</p>
<p class="muted">Scores compare image evidence; they do not identify ink, recto/verso, or historical truth.</p></div></section>
<details class="block" style="margin-top:13px"><summary>Provenance and parameters</summary><pre>{html.escape(provenance)}</pre></details>
</main></body></html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
    return {
        "output": str(output_path),
        "axis": selected_axis,
        "map_index": map_index,
        "input_index": input_index,
    }


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="source TIFF or Zarr volume")
    parser.add_argument("analysis", type=Path, help="LayerLens OME-Zarr output")
    parser.add_argument("output", type=Path, help="self-contained HTML report")
    parser.add_argument("--axis", default="auto", help="auto, axis name, or axis index")
    parser.add_argument("--index", type=int, help="input-voxel index for an explicit axis")
    parser.add_argument("--array-path")
    parser.add_argument("--level", type=int, default=0)
    parser.add_argument("--authenticated-s3", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(arguments)
    volume = open_volume(
        args.input,
        array_path=args.array_path,
        level=args.level,
        anonymous_s3=not args.authenticated_s3,
    )
    result = render_report(
        volume,
        args.analysis,
        args.output,
        axis=args.axis,
        index=args.index,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
