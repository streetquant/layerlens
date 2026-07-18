# Vesuvius Challenge Progress Prize target

LayerLens targets the Vesuvius Challenge monthly Progress Prize and the July
2026 open problem of uneven local scan quality in compressed or highly curved
papyrus regions.

## Current target

- **Deadline:** July 31, 2026 at 11:59 PM Pacific Time
- **Award:** the best qualifying monthly open-source progress submission is
  guaranteed US$20,000
- **Submission route:** register and share the work through the official
  Vesuvius Challenge community, then submit the monthly Progress Prize form
- **Release condition:** source, documentation, examples, and reusable outputs
  must be public

The authoritative pages are the official [prize description](https://scrollprize.org/prizes),
[2026 open problems](https://scrollprize.org/2026_open_problems), and
[data catalog](https://scrollprize.org/data). Entrants remain responsible for
checking the live rules and deadline before submitting.

## Rubric fit

The Progress Prize rubric rewards a specific demonstrated problem, meaningful
advantages over existing approaches, comprehensive documentation and examples,
standard formats, modular integration, early release, real use, and community
feedback. LayerLens addresses those points with:

- a label-free local papyrus-layer separability diagnostic rather than another
  segmentation or ink model;
- deterministic synthetic, controlled-degradation, baseline-comparison, and
  untouched official-corpus evidence;
- lazy TIFF/Zarr input, bounded-memory tiled CPU execution, OME-Zarr output,
  offline HTML reports, and a native VC3D overlay adapter;
- a public-ready Python package, pinned lockfile, CI, MIT license, exact
  machine-readable evidence, and reproducible walkthrough.

The ready-to-paste entry narrative and final human checklist are in
[`SUBMISSION.md`](SUBMISSION.md).
