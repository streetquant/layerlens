# Contributing to LayerLens

LayerLens is most useful when its successes and failures are both visible.
Bug reports, difficult scan regions, viewer compatibility results, and focused
code changes are welcome.

## Report a scan-quality case

Do not upload restricted challenge data or credentials. A useful report can be
made from metadata and LayerLens outputs alone. Include, when available:

- scanner or public dataset identifier and voxel size;
- input shape, file format, LayerLens version, and exact command;
- the companion `*.zarr.json` summary;
- a cropped or redacted report image that the data terms permit sharing;
- what a human reviewer or downstream tracing step found in the same region;
- whether the result is a useful detection, false alarm, or missed problem.

The component maps matter: note whether low quality came from coherence,
sharpness, scale separation, confidence, or a combination. Reports from clean
and difficult regions in the same acquisition are especially informative.

## Development setup

```bash
uv sync --extra dev
uv run ruff check src tests benchmarks
uv run pytest -q
uv run python -m benchmarks.make_demo
```

Run a packaged-command smoke test before proposing a release-facing change:

```bash
uv build
uv run layerlens --help
uv run layerlens-report --help
uv run layerlens-vc3d --help
```

## Evidence discipline

- Keep the frozen benchmark parameters unchanged unless a new version and
  predeclared validation protocol justify a change.
- Record negative controls and failed cases; do not remove an example because
  it weakens an aggregate.
- Never use surface labels, ink labels, or hand-authored quality labels during
  inference while describing the method as label-free.
- Keep challenge scans and labels out of git. Commit only permitted derived
  summaries, object identifiers, and reproducible code.
- Add or update tests for behavior changes and explain any output-schema or
  coordinate-contract change.

Small, reviewable contributions are preferred. By contributing code, you agree
that it may be distributed under the repository's MIT license.
