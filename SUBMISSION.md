# LayerLens — Progress Prize submission draft

## Title

**LayerLens: label-free local layer-separability maps for Vesuvius CT scans**

## One-sentence summary

LayerLens is a CPU-first quality-control tool that finds local papyrus regions
where compressed, blurred, noisy, or weakly separated layers are likely to
undermine surface tracing, maps scan-axis-persistent structure for ring/streak
review, and exports the result to OME-Zarr, an offline HTML report, or a native
Volume Cartographer overlay.

## Ready-to-paste entry

Vesuvius pipelines often learn that a scan region is hard only after expensive
segmentation or tracing has already failed. Global scan labels miss the local
problem: one part of a volume can contain sharp, directionally organized sheet
interfaces while a compressed or hazy fold a few hundred voxels away does not.

LayerLens measures that local evidence without labels, model weights, or a GPU.
It computes a full-resolution structure tensor, separates directional edge
energy from isotropic response, compares fine and coarse derivative scales,
and writes six inspectable maps: combined quality, coherence, sharpness,
scale-normalized sharpness, confidence, and scan-axis persistence. The new
persistence channel is kept separate from quality: it can flag controlled
ring/streak morphology without silently changing the validated quality score.
Its tiled implementation uses
mathematically sufficient Gaussian halos, deterministic global normalization,
lazy TIFF/Zarr reads, and exact cross-tile aggregation, so it can operate on
large volumes with bounded memory and no seam artifacts.

The main output is standard OME-Zarr 0.5 / Zarr v3 plus a versioned JSON
summary. A self-contained HTML report provides source/heatmap/overlay review.
A second adapter writes a compact VC3D-readable Zarr v2 `uint8` risk overlay
and optional `.volpkg.json` project. With default stride 4, the adapter stores
only the physical `/2` map and relies on VC3D's fine-to-coarse missing-chunk
fallback, preserving source voxel coordinates without expanding the map 64x.

The metric was frozen before broad validation. On a deterministic random
sample of 24 official surface-label cubes, every cube had higher mean quality
on recto voxels than other valid voxels; mean recto-vs-other AUC was 0.6442
(cube-bootstrap 95% CI 0.6154–0.6720). This is reported only as an external
localization diagnostic, not recto segmentation or scan-quality ground truth.
On nested real-CT degradations, LayerLens achieved mean blur ordering 0.9917
and noise ordering 1.0000, with the correct noise direction in 24/24 cubes.
Under the identical fixed protocol, Tenengrad and variance of Laplacian
detected blur but rewarded added noise, yielding combined blur/noise ranks of
0.0833 and 0.0000 versus LayerLens' 0.9958.

Version 0.2.0 was then frozen before a one-shot, preregistered robustness test
on 24 disjoint official crops. Controlled ring and streak perturbations raised
the separate persistence summary on 24/24 cubes in both families. Mean deltas
were +0.01859 and +0.01922; multiplicity-adjusted 97.5% bootstrap lower
endpoints were +0.01293 and +0.01407. All 168 comparisons of the original five
maps, aggregation weight, and scalar score were bit-identical to the frozen
0.1.0 path. Independent pure-Python, 50-digit, NumPy, and SciPy checks agreed.
This establishes sensitivity to those frozen controlled morphologies, not an
artifact-probability model or universal quality correction.

LayerLens is deliberately modular: researchers can use the scalar score to
triage related regions, the component maps to diagnose failure modes, OME-Zarr
in existing tools, or the VC3D overlay during surface review. The repository
includes an MIT license, lockfile, CI, tests, a data-free visual walkthrough,
exact source-object hashes, machine-readable validation reports, and commands
to reproduce every result. It does not redistribute challenge scans or labels.

## Specific advantages

- **Local rather than global:** produces spatial maps that expose mixed-quality
  regions inside one scan.
- **Noise-aware rather than focus-only:** does not mistake isotropic
  high-frequency noise for better layer separability in the 24-cube test.
- **Persistence-aware without score drift:** adds a separately interpretable
  scan-axis-persistence map while preserving the original metric bit-for-bit.
- **Reference-free:** no recto, surface, ink, or quality labels are required at
  inference time.
- **Operationally light:** CPU-only, no model download, bounded-memory tiles,
  lazy TIFF/Zarr reads, and optional anonymous S3 input.
- **Inspectable:** every component and normalization choice is recorded rather
  than hidden behind a learned score.
- **Interoperable:** OME-Zarr 0.5, JSON, one-file HTML, VC3D Zarr v2, and
  `.volpkg.json` output.

## Evidence at a glance

| Check | Result |
|---|---:|
| Frozen synthetic/official composite benchmark | 95.966 / 100 |
| Controlled blur ordering, 24 official cubes | 0.9917 (23/24 perfect) |
| Controlled noise ordering, 24 official cubes | 1.0000 (24/24 perfect) |
| Combined blur/noise ordering | **0.9958** |
| Tenengrad combined ordering, same inputs | 0.0833 |
| Laplacian-variance combined ordering, same inputs | 0.0000 |
| Recto mean above other-valid mean | 24/24 cubes |
| Mean recto-vs-other AUC | 0.6442 (95% CI 0.6154–0.6720) |
| Controlled ring persistence delta | +0.01859; 24/24 positive (97.5% CI +0.01293–+0.02500) |
| Controlled streak persistence delta | +0.01922; 24/24 positive (97.5% CI +0.01407–+0.02533) |
| Legacy outputs preserved after addition | 168/168 bit-identical comparisons |
| Lazy TIFF runtime, 320³ reference cubes | 15.7–21.9 s |
| Six-channel overhead, 96³ reference fixture | +19.6% median |
| Official VC3D headless native-reader decode | 96/96 base + 48/48 overlay slices |

Exact values and negative controls:

- [`docs/validation.md`](docs/validation.md)
- [`docs/evidence/surface_validation_report.json`](docs/evidence/surface_validation_report.json)
- [`docs/evidence/degradation_validation_report.json`](docs/evidence/degradation_validation_report.json)
- [`docs/evidence/baseline_comparison_report.json`](docs/evidence/baseline_comparison_report.json)
- [`docs/evidence/persistence_holdout_report.json`](docs/evidence/persistence_holdout_report.json)
- [`docs/evidence/persistence_holdout_independent_verification.json`](docs/evidence/persistence_holdout_independent_verification.json)
- [`docs/evidence/persistence_holdout_claim_certificate.json`](docs/evidence/persistence_holdout_claim_certificate.json)
- [`docs/evidence/vc3d_cli_validation_report.json`](docs/evidence/vc3d_cli_validation_report.json)

## Two-minute data-free demo

```bash
git clone https://github.com/streetquant/layerlens.git
cd layerlens
uv sync --extra dev

uv run python -m benchmarks.make_demo
```

Open `outputs/demo/layerlens-demo.html`. The deterministic phantom transitions
from sharp sheets on the left to locally blurred sheets on the right; the
quality overlay follows that change. Or open
`outputs/demo/layerlens-demo.volpkg.json` directly in VC3D; the same command
generates its base volume and compact risk overlay. The committed browser
screenshot is [`docs/assets/layerlens-report.png`](docs/assets/layerlens-report.png).
The official VC3D AppImage's native C++ CLI reader successfully decoded all
slices of both generated Zarr payloads without a display server; the exact
compatibility target, AppImage hash, and machine-readable report are in
[`docs/vc3d.md`](docs/vc3d.md).

## Real-data use

```bash
uv run layerlens scan.tif outputs/scan.layerlens.zarr \
  --tile-shape 160 --stride 4 \
  --scan-axis 0 --persistence-sigma 8 \
  --voxel-size 7.91,7.91,7.91 --unit micrometer

uv run layerlens-report scan.tif \
  outputs/scan.layerlens.zarr outputs/scan.layerlens.html

uv run layerlens-vc3d \
  outputs/scan.layerlens.zarr outputs/scan.layerlens-vc3d.ome.zarr \
  --project outputs/scan-review.volpkg.json \
  --base-volume /path/to/base.ome.zarr
```

## Honest boundaries

LayerLens measures image evidence, not historical truth. It does not identify
ink, trace a surface, infer recto/verso, or guarantee downstream success. A
clean weakly textured interface can score low; a strong organized non-papyrus
edge can score high. Scores are best used to compare related acquisition
regions rather than as one universal scanner-independent threshold. The two
near-chance external AUC cubes and sole imperfect blur ordering remain in the
published evidence. High scan-axis persistence is a review cue, not an artifact
classifier: valid repeated structure can also raise it, and the current holdout
uses generated broadcast perturbations rather than expert-labeled natural
artifacts.

## Public links

- Source: [github.com/streetquant/layerlens](https://github.com/streetquant/layerlens)
- Current public release: [v0.2.0](https://github.com/streetquant/layerlens/releases/tag/v0.2.0)
- Demo/report: [two-minute data-free walkthrough](https://github.com/streetquant/layerlens/blob/main/SUBMISSION.md#two-minute-data-free-demo)
- Community post: pending human-operated announcement in the official community

## Progress Prize form answers

### Public contribution URLs

- https://github.com/streetquant/layerlens
- https://github.com/streetquant/layerlens/releases/tag/v0.2.0
- https://github.com/streetquant/layerlens/blob/main/SUBMISSION.md#two-minute-data-free-demo

### Short description of contribution impact

LayerLens increases the probability of reading complete scrolls by identifying
local CT regions where compression, haze, noise, or weakly separated papyrus
layers are likely to make surface localization and tracing unreliable before
expensive downstream work is committed. It needs no labels, model weights, or
GPU, and writes standard OME-Zarr maps plus JSON, self-contained HTML, and
compact VC3D overlays. On controlled degradations of 24 official Vesuvius
surface cubes, it achieved 0.9958 combined blur/noise ordering and preserved
the correct direction for all 24 noise sequences, while Tenengrad and variance
of Laplacian rewarded added noise. A separately preregistered holdout on 24
disjoint official crops raised the separate signal under controlled ring and
streak morphology on 24/24 cubes in both families while preserving all 168
legacy-output comparisons bit-for-bit. This gives scanning, segmentation, and
tracing teams an interoperable, inspectable way to triage difficult regions
and distinguish weak layer evidence from scan-axis-persistent review cues.

The form's full-name and individual/team-description fields must be completed
by the submitting person. Do not replace them with a repository handle unless
that is the submitter's intended public identity.

## Required community-projects pull request

The July 2026 form requires a pull request to the official
[`awesome-scroll-tools` community-projects list](https://github.com/ScrollPrize/villa/blob/main/scrollprize.org/docs/20_community_projects.md).
Add this entry under **Data access/visualization → Tools** using the public
repository-owner attribution:

```markdown
- [LayerLens](https://github.com/streetquant/layerlens): CPU-first, label-free local papyrus-layer separability diagnostics for Vesuvius CT volumes. Produces OME-Zarr quality maps, self-contained HTML reports, and compact VC3D overlays. By streetquant
```

Suggested pull-request title:

```text
docs: add LayerLens to community projects
```

Suggested pull-request body:

```text
Adds LayerLens, a public MIT-licensed local scan-quality and papyrus-layer
separability diagnostic, to Data access/visualization tools.

Repository: https://github.com/streetquant/layerlens
Release: https://github.com/streetquant/layerlens/releases/tag/v0.2.0

Validation includes controlled degradations and baseline comparison on 24
official Vesuvius surface cubes, plus a preregistered ring/streak holdout on 24
disjoint official crops with independent verification. Outputs include
OME-Zarr, JSON, self-contained HTML, and compact VC3D overlays.
```

## Community announcement draft

> I released LayerLens, a label-free local layer-separability QC tool for
> Vesuvius CT. It runs on CPU, writes OME-Zarr/HTML, and can export a compact
> native VC3D risk overlay. Version 0.2.0 adds a separate scan-axis-persistence
> map: a preregistered holdout raised the signal on 24/24 disjoint official
> crops for both controlled ring and streak families, while all 168 legacy
> comparisons remained bit-identical. The repo includes exact object hashes,
> machine-readable reports, independent checks, negative controls, tests, and
> a data-free demo:
> https://github.com/streetquant/layerlens. I would especially value feedback
> on whether the VC3D overlay and separate quality/persistence maps help choose
> or triage difficult tracing regions.

## Human-only submission checklist

- [x] Confirm the live Progress Prize deadline and rules (rechecked July 23,
      2026: July 31, 2026 at 11:59 PM Pacific).
- [x] Choose or authorize the public GitHub owner/repository name.
- [x] Push the robust candidate commit and publish the
      [`v0.2.0`](https://github.com/streetquant/layerlens/releases/tag/v0.2.0)
      release.
- [ ] Submit the required community-projects pull request above and record its
      URL.
- [ ] Add the official community-announcement URL above.
- [x] Re-run the official VC3D native CLI reader headlessly on freshly generated
      `v0.2.0` release outputs (96/96 base and 48/48 overlay slices decoded).
- [ ] Post the announcement in the official Vesuvius Challenge community and
      collect the message URL plus any early feedback.
- [ ] Submit the official [Progress Prize form](https://forms.gle/xoF5C3QsYutKP97x7)
      before the deadline.
