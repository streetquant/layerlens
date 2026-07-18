# Changelog

All notable LayerLens changes are recorded here. The project follows semantic
versioning once its public release begins.

## 0.1.0 - 2026-07-17

- Add the label-free, multi-scale layer-separability metric and five component
  maps.
- Add lazy TIFF, local Zarr, OME-Zarr, and optional S3 input.
- Add seam-safe tiled execution with exact global normalization and score
  aggregation.
- Add OME-Zarr 0.5 / Zarr v3 output and a versioned JSON summary contract.
- Add self-contained HTML quality reports.
- Add compact VC3D-native Zarr v2 quality overlays and portable review
  projects with coordinate-space tags.
- Make the deterministic walkthrough generate a complete, data-free VC3D base,
  risk overlay, and directly openable review project.
- Add synthetic, official-corpus, format, tiling, and controlled-degradation
  validation workflows.
- Expand the untouched official-cube validation to a deterministic 24-object
  sample and commit the exact reports and source hashes.
- Add a fixed comparison with Tenengrad and variance of Laplacian.
- Reject non-finite numeric CLI parameters and invalid tile/stride layouts
  before creating any output artifacts.
