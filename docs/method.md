# Method

LayerLens estimates whether a local CT neighborhood contains sharp,
directionally organized interfaces at the expected papyrus scale. Every term
is inspectable and has a distinct failure interpretation.

## 1. Robust intensity scale

Finite input values are clipped and normalized between their first and 99th
percentiles. A tiled run estimates these bounds once for the whole source and
passes the same bounds to every tile. This is essential: per-tile contrast
normalization would create artificial boundaries and incomparable scores.

For sources larger than the normalization budget, LayerLens reads up to 32
deterministically selected spatial blocks. The default budget is one million
voxels. The exact bounds, sample count, and strategy are recorded in JSON.

## 2. Fine-scale structure tensor

Let `I` be the robust-normalized image. Gaussian derivatives at
`sigma_g = 0.6` voxels produce the gradient. The local structure tensor is

```text
J = G(sigma_t) * (gradient(I) gradient(I)^T),  sigma_t = 2.5 voxels
```

where `*` denotes convolution. If `lambda_1 >= lambda_2` are the two largest
eigenvalues, directional coherence is

```text
coherence = (lambda_1 - lambda_2) / (lambda_1 + epsilon)
```

and anisotropic edge strength is

```text
edge = sqrt(max(lambda_1 - lambda_2, 0))
```

Subtracting `lambda_2` removes the tensor energy that isotropic noise adds in
every direction. The bounded sharpness response is

```text
sharpness = (edge / 0.04) / (1 + edge / 0.04)
```

The fixed response scale is valid because robust normalization fixes the
intensity range. Dividing by a high-pass noise estimate was rejected: genuine
high-resolution papyrus texture was misclassified as noise.

## 3. Fine-to-coarse separability

Absolute edge amplitude can be restored by contrast normalization even after
blur. LayerLens therefore measures the same anisotropic response at a coarser
derivative scale, `sigma_c = max(1.5, 2.5 sigma_g)`, and computes

```text
scale_sharpness = clip((edge_fine / edge_coarse - 1) / 0.8, 0, 1)
```

A genuinely sharp interface loses more response at the coarser scale than an
already blurred interface.

## 4. Local and volume scores

The local quality channel is

```text
quality = coherence^1.5 * sharpness^1.5 * scale_sharpness
```

Confidence is a bounded response of total tensor energy. The volume score is
the quality mean weighted by

```text
confidence * sqrt(edge)
```

so empty background does not dominate a volume summary. Unweighted quality
statistics and poor/good fractions are reported separately.

## 5. Seam-safe tiling

TIFF strips or tiles are exposed through tifffile's read-only Zarr adapter,
while Zarr inputs remain lazy. Only the current normalization sample or
halo-extended compute tile is decoded into memory.

SciPy Gaussian filters use finite support. LayerLens adds the support radii of
the fine derivative, fine-to-coarse smoothing, and tensor integration, then
rounds the halo up to a stride multiple. With the defaults, the halo is 20
voxels on every axis.

Tile origins, halos, and output samples share one global stride phase. Halo
outputs are discarded before writing. A test reconstructs an irregular 42³
volume from multiple tiles and compares all six internal maps against the
whole-volume result to `2e-5` relative tolerance.

## 6. Coordinates

With stride `s`, the first output sample is taken at input index `s // 2`.
OME-Zarr output therefore uses physical scale

```text
output_scale = input_voxel_size * stride
```

and translation

```text
output_translation = input_translation + input_voxel_size * (stride // 2)
```

This prevents the common half-block registration error when a quality map is
overlaid on its source volume.
