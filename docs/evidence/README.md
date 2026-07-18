# Validation evidence

These JSON files are the exact machine-readable artifacts behind the rounded
tables in [`docs/validation.md`](../validation.md):

- `surface_validation_manifest.json` fixes the 24-cube sample with official
  source paths, byte sizes, and Xet object identifiers;
- `surface_validation_report.json` records full-cube quality, runtime, and
  post-hoc recto-enrichment measurements;
- `degradation_validation_report.json` records every blur/noise perturbation,
  crop coordinate, normalization bound, score, and aggregate interval;
- `baseline_comparison_report.json` records the same perturbations for
  LayerLens, Tenengrad, and variance of Laplacian.

The repository does not redistribute the TIFF volumes or labels. Recreate the
sample and all reports with the commands in the validation document.
Scientific values are deterministic given the recorded objects, code, and
seed; runtime fields vary by machine and are not scientific endpoints.
