# Output contract

LayerLens writes an OME-Zarr 0.5 / Zarr v3 image with one resolution level at
array path `0`.

## Array layout

The array is channel-first:

```text
(c, z, y, x)  for 3D input
(c, y, x)     for 2D input
```

The five `float32` channels are:

| Index | Name | Meaning |
|---:|---|---|
| 0 | `quality` | Combined local layer separability |
| 1 | `coherence` | Dominance of one interface-normal direction |
| 2 | `sharpness` | Fine-scale anisotropic edge response |
| 3 | `scale_sharpness` | Fine-to-coarse response separation |
| 4 | `confidence` | Amount of local tensor evidence |

Every channel is finite and bounded to `[0, 1]`. The output chunk layout is
`(1, tile_z / stride_z, tile_y / stride_y, tile_x / stride_x)`, clipped to the
array shape, so viewers can request one component without reading all five.

## OME-Zarr metadata

The root `ome` namespace contains:

- `version: "0.5"`
- `multiscales` with channel and spatial axes
- a per-level `scale` transform
- a `translation` transform when the sampled grid is offset
- optional spatial units copied from the input or CLI calibration
- `omero.channels` labels, colors, and `[0, 1]` display windows

The source OME-Zarr transformation is preserved when available. TIFF inputs
default to unit voxel coordinates unless `--voxel-size` and `--unit` are
provided.

## JSON summary

The companion file has schema identifier `layerlens-summary-v1` and these
top-level objects:

```json
{
  "schema": "layerlens-summary-v1",
  "layerlens_version": "0.1.0",
  "input": {},
  "output": {},
  "parameters": {},
  "metrics": {},
  "runtime": {}
}
```

`metrics` contains:

- `score`: evidence-weighted quality mean
- `mean_quality`: unweighted quality mean
- `quality_p10`, `quality_p50`, `quality_p90`: 1000-bin approximate quantiles
- `poor_fraction`: fraction below `0.25`
- `good_fraction`: fraction at or above `0.75`

The same summary is embedded under the root `layerlens` attribute. Runtime is
informational and excluded from scientific comparisons.

## Visual report

`layerlens-report` renders a source plane, the quality heatmap, a
confidence-weighted overlay, summary cards, a quality histogram, and the full
analysis provenance into one self-contained HTML file. It loads the scalar
summary from the companion JSON when present and otherwise uses the copy
embedded in the OME-Zarr root.

For 3D inputs, `--axis auto` selects the plane with the largest mean
`(1 - quality) * confidence` away from the outer five percent of each axis.
Use `--axis z --index 512` (or another input axis name and voxel index) for an
explicit view. The selected input coordinate is mapped to the nearest sampled
quality-map center using the recorded stride.

## Volume Cartographer overlay

`layerlens-vc3d` converts any 3D LayerLens channel into a compact, directly
loadable Volume Cartographer volume overlay. The adapter writes a Zarr v2
`uint8` pyramid with VC3D's required `meta.json`, ZYX axes, identity level-0
index coordinates, dyadic numeric level groups, and the source dimensions.

The populated array lives at the physical pyramid level matching the
LayerLens stride. For the default stride 4, groups `/0` and `/1` contain array
metadata only and `/2` contains the quantized map. VC3D's fine-to-coarse
sampler falls through missing fine chunks to `/2`, preserving source level-0
voxel coordinates without materializing a 64-times-larger full-resolution
array. Edge cells are replicated only when a source dimension is not divisible
by the stride.

By default the exporter stores `round((1 - quality) * 255)`, so high overlay
values identify low-quality risk and VC3D's lower threshold can isolate them.
Use `--no-invert` to store the selected channel directly. The optional
`.volpkg.json` writer places the base and overlay volumes in one project and
can attach the same `vc-open-data-coordinate-space` tag to both.

This sparse fallback layout is deliberately VC3D-specific. A generic
OME-Zarr viewer that treats absent chunks as fill values can show the
metadata-only fine levels as blank; use the native LayerLens Zarr v3 output
for general OME tooling. See [the VC3D integration guide](vc3d.md) for commands,
review workflow, constraints, and the exact compatibility target.

## Write safety

LayerLens refuses an existing analysis, summary, or HTML report unless
`--overwrite` is explicit. The VC3D adapter follows the same rule for overlay
and project paths. It rejects identical or nested input/output locations before
writing. Input and analysis Zarr stores are always opened read-only.

Numeric scale options must be positive and finite, and tile dimensions must be
exact multiples of their strides; invalid configurations fail before an output
store is created.
