# Volume Cartographer integration

LayerLens can export its local quality map as a compact Volume Cartographer
(VC3D) overlay while preserving the base scan's level-0 voxel coordinates.
This makes low-separability regions visible on arbitrary planes and surfaces
without changing VC3D or expanding the diagnostic map to full resolution.

## Data-free walkthrough

Generate a complete local VC3D project without downloading challenge data:

```bash
uv run python -m benchmarks.make_demo
```

The command writes a small VC3D-readable base volume, compact LayerLens risk
overlay, and `outputs/demo/layerlens-demo.volpkg.json`. Open that project in
VC3D and select `LayerLens demo low-quality risk` in the volume-overlay
control. The same run also writes `layerlens-demo.html` for browser review.

## Export an overlay

After running the normal analysis:

```bash
uv run layerlens scan.tif outputs/scan.layerlens.zarr \
  --voxel-size 7.91,7.91,7.91 --unit micrometer

uv run layerlens-vc3d \
  outputs/scan.layerlens.zarr \
  outputs/scan.layerlens-vc3d.ome.zarr
```

The default export is low-quality risk: `uint8(round((1 - quality) * 255))`.
A value of 255 means the LayerLens quality was 0; a value of 0 means it was 1.
To export another component or preserve its original direction:

```bash
uv run layerlens-vc3d analysis.zarr overlay.ome.zarr \
  --channel coherence --no-invert
```

Accepted channels are recorded in the analysis metadata. The exporter refuses
an existing destination unless `--overwrite` is explicit.

## Create a review project

The adapter can also create the current VC3D project format with both the base
scan and overlay registered:

```bash
uv run layerlens-vc3d \
  outputs/scan.layerlens.zarr \
  outputs/scan.layerlens-vc3d.ome.zarr \
  --project outputs/scan-review.volpkg.json \
  --base-volume /path/to/base-scan.ome.zarr
```

`--base-volume` may be a local VC3D-readable volume or remote URL. Local paths
are written relative to the project, making the directory portable. For an
open-data base volume, pass its coordinate-space identifier without the tag
prefix so VC3D filters overlays into the matching coordinate system:

```bash
uv run layerlens-vc3d analysis.zarr overlay.ome.zarr \
  --project review.volpkg.json \
  --base-volume https://example.invalid/base.ome.zarr \
  --coordinate-space 'PHercParis4/volume-id@L0'
```

Open `review.volpkg.json` in VC3D, select the LayerLens volume in the volume
overlay control, choose a colormap and opacity, then raise the lower threshold
to show only the highest-risk regions. A threshold of 160, for example,
displays approximately `quality <= 1 - 160/255`, or `quality <= 0.373`, under
the default inversion. That is a review starting point, not a calibrated
universal pass/fail cutoff.

## Storage and coordinate contract

For a LayerLens analysis with source shape `(Z,Y,X)` and isotropic stride
`s = 2^L`, the export contains:

- root Zarr v2 `.zgroup` and OME multiscales 0.4 `.zattrs`;
- numeric arrays `/0` through `/L`, all ZYX `uint8` with dyadic shapes;
- identity index scale at `/0` and scale `2^k` at group `/k`;
- no payload chunks in `/0` through `/L-1`;
- the map payload in `/L`, padded by edge replication to
  `(ceil(Z/s), ceil(Y/s), ceil(X/s))` when needed;
- `meta.json` with `type: vol`, full source width/height/slices, one isotropic
  voxel size in micrometers, UUID/name, and display range 0–255;
- `layerlens_vc3d` provenance describing channel, inversion, stride, physical
  level, quantization, source shape, and sampled-grid center offset.

VC3D first requests the fine group corresponding to the current view. Missing
chunks remain uncovered, so its fine-to-coarse sampler retries the same source
coordinates at successively coarser physical levels. At `/L`, VC3D applies
the `1 / 2^L` coordinate transform and reads the compact LayerLens map. This
behavior is why metadata-only fine arrays are intentional rather than corrupt.

## Constraints and limitations

- The LayerLens analysis must be 3D with axes exactly `z,y,x`.
- Stride must be isotropic and a power of two. Re-run analysis with a compatible
  stride if the exporter rejects it.
- VC3D metadata has one scalar voxel size, so source calibration must be
  isotropic. `--voxel-size-um` is an explicit override when the input metadata
  is absent or intentionally being registered into another calibrated space.
- The generated project aligns arrays by voxel index; it does not perform
  image registration. Base and analysis must already share dimensions and
  coordinates.
- Quantization has 256 levels. Keep the native float32 LayerLens output for
  measurement, statistics, or generic OME-Zarr review.
- Generic Zarr readers treat missing chunks as fill values and may not perform
  VC3D's fine-to-coarse fallback.

## Compatibility target

The adapter contract was checked against the Vesuvius Challenge `villa`
repository at commit `1fe401acfb25` (2026-07-18 checkout), including:

- `volume-cartographer/core/src/Volume.cpp` for `meta.json`, group shapes, and
  local Zarr requirements;
- `volume-cartographer/core/src/render/ZarrChunkFetcher.cpp` for Zarr v2,
  `uint8`, physical-level transforms, and missing-chunk classification;
- `volume-cartographer/core/src/render/ChunkedPlaneSampler.cpp` for
  fine-to-coarse fallback;
- `volume-cartographer/apps/VC3D/volume_viewers/CChunkedVolumeViewer.cpp` for
  same-coordinate overlay sampling and threshold compositing;
- `volume-cartographer/apps/VC3D/overlays/VolumeOverlayController.cpp` and
  `core/src/VolumePkg.cpp` for coordinate tags and project entries.

The official `VC3D-1fe401a-2026-07-17-linux-x86_64.AppImage` built from that
same commit was also exercised with its bundled native `vc_zarr_to_tiff`
reader. It opened the generated demo base at level 0 as `96x96x96 uint16` and
the populated overlay at level 1 as `48x48x48 uint8`, then decoded every slice
successfully. The tested AppImage SHA-256 was
`381fa57c6fd8b9f3183019fc828ea076f8480ce812ab859bcf7d38d58d1e3e3c`.
This checks the actual C++ Zarr metadata, compressor, chunk, and dtype path;
it does not substitute for visually checking project loading and overlay
compositing in the GUI.

Automated tests assert the on-disk Zarr v2 metadata, compression, sparse fine
levels, irregular-edge padding, identity/dyadic transforms, `meta.json`,
project-relative locations, matching coordinate tags, the complete data-free
project, overwrite behavior, and CLI generation. A native VC3D executable is
not bundled with LayerLens; the source and native-reader checks do not replace
an end-user visual smoke test on each future VC3D release.
