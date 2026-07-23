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
  LayerLens, Tenengrad, and variance of Laplacian;
- `persistence_holdout_selection.json`, `persistence_holdout_exclusions.txt`,
  `persistence_holdout_acquisition_manifest.json`, and
  `persistence_holdout_crop_manifest.json` freeze the disjoint 24-cube
  confirmatory sample and source/crop provenance;
- `persistence_holdout_preregistration.md` fixes the candidate, families,
  parameters, seeds, statistical unit, multiplicity correction, pass rule,
  and valid-negative behavior before voxel acquisition;
- `persistence_holdout_records.jsonl` and
  `persistence_holdout_report.json` contain every controlled ring/streak
  comparison and the one-shot decision;
- `persistence_holdout_independent_verification.json` records the
  pure-Python bootstrap, 50-digit aggregation, and two alternate metric paths;
- `persistence_holdout_claim_certificate.json` binds the narrow empirical
  claim to its preregistration, records, verifier, and isolated reproduction.

The repository does not redistribute the TIFF volumes or labels. Recreate the
sample and all reports with the commands in the validation document.
Scientific values are deterministic given the recorded objects, code, and
seed; runtime fields vary by machine and are not scientific endpoints.

Verify the committed persistence record and all of its hash links without
downloading scan data:

```bash
uv run python -m benchmarks.verify_persistence_evidence
```

This command reconstructs the cube-level deltas and independent bootstrap. It
does not turn the controlled perturbations into evidence about natural-artifact
prevalence; that limitation is part of the frozen result itself.
