# LayerLens metric autoresearch

Goal: Improve the reference-free Local Layer Separability Index so it ranks
known blur/noise degradations on both synthetic phantoms and untouched official
3D cubes, remains rotation and intensity invariant, rejects isotropic noise,
and prefers the official sharp 2.4 um Paris 4 crop to the hazy 7.91 um crop.

Scope: `src/layerlens/quality.py`

Metric: Composite benchmark score from `benchmarks.verify_metric`; higher is
better.

Verify: `.venv/bin/python -m benchmarks.verify_metric`

Guard: `.venv/bin/pytest -q && .venv/bin/ruff check src/layerlens/quality.py tests benchmarks`

The benchmark and tests are guard rails and are not modified by metric-search
iterations. The real crops are prepared deterministically from two official
surface-label cubes and remain ignored data rather than repository content.
