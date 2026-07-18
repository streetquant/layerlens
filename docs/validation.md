# Validation

LayerLens uses three independent forms of evidence: known synthetic signal,
controlled degradation of official CT, and enrichment on official surface
labels that were never used to fit the metric. The exact machine-readable
reports and source-object hashes are committed under [`docs/evidence`](evidence/).

## Frozen benchmark

`python -m benchmarks.verify_metric` currently reports:

| Component | Result |
|---|---:|
| Composite metric | **95.966458 / 100** |
| Measured sheet-detection rank | 0.904762 |
| Rotation/intensity invariance | 0.999991 |
| Isotropic-noise specificity | 0.977608 |
| Official 2D high-vs-low margin | 1.000000 (clipped) |
| Official 3D degradation rank | 1.000000 |

Synthetic truth is not a hand-authored blur/noise score. It is the measured
ROC AUC of ideal sheet support against degraded phantom intensities. The
remaining rank error is two adjacent cross-degradation swaps; tuning stopped
because further complexity would overfit that small ordering.

The official Paris 4 examples score:

| Official example | Score |
|---|---:|
| DLS 7.91 µm, visibly compressed/hazy | 0.056203 |
| ESRF 2.4 µm, visibly separated layers | 0.336923 |

## Controlled degradation on 24 official cubes

The broad validation uses a deterministic random sample of 24 complete cubes
from the 892 image/label pairs listed by the official surface-label bucket.
The selection seed is `20260718`; exact Xet object identifiers and byte sizes
are in the [sample manifest](evidence/surface_validation_manifest.json).

For each cube, the protocol selects a reproducible recto-rich 64³ crop, fixes
normalization to that crop's p1/p99 bounds, then applies nested Gaussian blur
at `0, 0.8, 1.6, 2.4` voxels or one fixed Gaussian-noise field scaled to
`0, 0.02, 0.05, 0.10` of normalized intensity. Higher quality should order
both sequences from the unmodified crop to the strongest perturbation.

| Result over 24 cubes | Blur | Noise |
|---|---:|---:|
| Mean Spearman ordering | **0.991667** | **1.000000** |
| Cube-bootstrap 95% CI | 0.975–1.000 | 1.000–1.000 |
| Perfect orderings | 23/24 | 24/24 |
| Mean endpoint quality drop | 74.46% | 12.21% |

The combined blur/noise ordering is `0.995833`. The sole non-perfect sequence
is blur on `sample_00559` (`0.8`); it is retained rather than excluded. Full
per-level scores, crop coordinates, label fractions, and normalization bounds
are in the [controlled-degradation report](evidence/degradation_validation_report.json).

This is nested perturbation evidence on real CT structure, not independent
scan-quality ground truth. Labels choose reproducible papyrus-rich crops and
are never read by LayerLens itself.

## Comparison with standard focus measures

Tenengrad and variance of Laplacian are standard no-reference focus measures.
They are useful blur detectors, but high-frequency noise can also increase
their response. `benchmarks.compare_baselines` applies both fixed definitions
to exactly the same normalized crops and perturbations, with no baseline
parameter tuning on these cubes.

| Higher-is-better metric | Mean blur rank | Mean noise rank | Combined rank | Perfect noise orderings |
|---|---:|---:|---:|---:|
| **LayerLens** | 0.991667 | **1.000000** | **0.995833** | **24/24** |
| Tenengrad (mean squared 3D Sobel magnitude) | 1.000000 | -0.833333 | 0.083333 | 0/24 |
| Variance of 3D Laplacian | 1.000000 | -1.000000 | 0.000000 | 0/24 |

The classical measures detect blur perfectly, but their negative noise ranks
mean they generally reward added noise as extra “sharpness.” LayerLens is
slightly less perfect on blur while preserving the correct direction for all
24 noise sequences. The [baseline comparison report](evidence/baseline_comparison_report.json)
contains every score and bootstrap interval.

## Full-cube external localization check

The same 24 complete labeled cubes were processed with the frozen default
metric, stride 4, and 160³ tiles. Labels were read only after map generation.
Recto mean quality exceeded other valid-voxel mean quality in **24/24 cubes**.
Mean recto-vs-other AUC was `0.644207` (deterministic cube-bootstrap 95% CI
`0.615435–0.671983`), and mean quality difference was `+0.087317` (95% CI
`+0.063084–+0.114306`).

| Cube | Shape | Score | Poor fraction | Recto AUC | Recto delta | Seconds |
|---|---:|---:|---:|---:|---:|---:|
| sample_00040 | 320³ | 0.440 | 0.505 | 0.803 | +0.275 | 20.9 |
| sample_00052 | 320³ | 0.420 | 0.378 | 0.713 | +0.158 | 20.9 |
| sample_00064 | 320³ | 0.429 | 0.428 | 0.763 | +0.212 | 20.2 |
| sample_00067 | 320³ | 0.445 | 0.306 | 0.736 | +0.183 | 19.9 |
| sample_00124 | 320³ | 0.265 | 0.643 | 0.652 | +0.081 | 21.9 |
| sample_00127 | 320³ | 0.443 | 0.239 | 0.665 | +0.128 | 15.9 |
| sample_00134 | 320³ | 0.143 | 0.928 | 0.627 | +0.033 | 15.7 |
| sample_00177 | 320³ | 0.126 | 0.911 | 0.509 | +0.004 | 15.9 |
| sample_00268 | 320³ | 0.135 | 0.894 | 0.506 | +0.002 | 16.0 |
| sample_00347 | 320³ | 0.242 | 0.689 | 0.569 | +0.034 | 16.1 |
| sample_00369 | 320³ | 0.248 | 0.708 | 0.654 | +0.083 | 16.2 |
| sample_00385 | 320³ | 0.298 | 0.650 | 0.685 | +0.117 | 16.2 |
| sample_00400 | 320³ | 0.296 | 0.558 | 0.579 | +0.047 | 16.2 |
| sample_00428 | 320³ | 0.239 | 0.676 | 0.569 | +0.040 | 15.8 |
| sample_00466 | 320³ | 0.258 | 0.662 | 0.668 | +0.096 | 16.0 |
| sample_00486 | 256³ | 0.235 | 0.669 | 0.638 | +0.069 | 9.0 |
| sample_00559 | 320³ | 0.211 | 0.729 | 0.597 | +0.038 | 16.2 |
| sample_00603 | 320³ | 0.237 | 0.714 | 0.710 | +0.122 | 16.3 |
| sample_00636 | 320³ | 0.200 | 0.755 | 0.655 | +0.074 | 16.1 |
| sample_00662 | 320³ | 0.200 | 0.762 | 0.653 | +0.075 | 16.2 |
| sample_00738 | 320³ | 0.169 | 0.814 | 0.599 | +0.039 | 16.8 |
| sample_00785 | 320³ | 0.196 | 0.768 | 0.645 | +0.063 | 16.8 |
| sample_00806 | 320³ | 0.192 | 0.769 | 0.661 | +0.074 | 17.4 |
| sample_00882 | 256³ | 0.204 | 0.735 | 0.608 | +0.049 | 9.2 |

This is not a claim that LayerLens segments recto. Label `0` includes valid
verso and other organized papyrus edges that a reference-free quality metric
should also reward; label `2` is excluded. The near-chance `sample_00177` and
`sample_00268` results are important negative controls and remain in both the
table and [full-cube report](evidence/surface_validation_report.json).

## Tiling and format controls

- All component maps and exact aggregation weights from a tiled irregular 42³
  phantom match whole-volume computation within `2e-5` relative tolerance.
- Rotation and affine-intensity transforms preserve the scalar score.
- Constant input produces exactly zero quality.
- Invalid dimensionality, stride, calibration, and normalization bounds fail
  explicitly.
- `ome-zarr-models` 1.x parsed a full generated store as
  `ome_zarr_models.v05.image.Image` without validation error.
- The automated test suite exercises Python 3.11 and 3.13 in CI.

## Runtime

On a 24-core Threadripper 3960X, the lazy TIFF path processed the two 256³
cubes in 9.0–9.2 seconds and the 320³ cubes in 15.7–21.9 seconds (median over
all 24: 16.2 seconds). A 320³ analysis contains five 80³ `float32` channels and
compresses to roughly 8 MB. Runtime is recorded for transparency, not used as
a scientific endpoint.

## Reproduce

```bash
uv run python -m benchmarks.download_surface_samples \
  --count 24 --seed 20260718 --workers 2

uv run python -m benchmarks.validate_surface_corpus \
  --manifest data/cache/surface_validation_manifest.json --workers 4

uv run python -m benchmarks.validate_degradations \
  --manifest data/cache/surface_validation_manifest.json --workers 4

uv run python -m benchmarks.compare_baselines \
  --manifest data/cache/surface_validation_manifest.json --workers 4
```

## Known limitations

- Scores are most meaningful for comparing regions from related acquisitions;
  the method is not calibrated to one universal threshold across every
  scanner, voxel size, and reconstruction pipeline.
- A clean but weakly textured interface can score low.
- A strong organized edge that is not papyrus can score high.
- Local quality does not establish recto/verso identity, surface continuity,
  traceability, or ink presence.
- Current parameters are expressed in voxels. Physical-scale-normalized
  presets require broader scan-metadata coverage.
- Deterministic block sampling bounds memory and remote reads, but a highly
  heterogeneous volume can have a different sampled p1/p99 estimate than an
  exact full-volume percentile.

These limitations are why the component channels, normalization provenance,
and confidence map are first-class outputs rather than hidden internals.
