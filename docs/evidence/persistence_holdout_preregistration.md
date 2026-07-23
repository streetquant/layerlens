hypothesis: The frozen stride-4 scan-axis persistence diagnostic generalizes its controlled ring and streak response to a disjoint 24-cube official holdout while preserving the original LayerLens outputs bit-for-bit.
predicted_outcome: Both preregistered artifact families will increase persistence on at least 75 percent of holdout cubes and have positive Bonferroni-adjusted bootstrap lower endpoints; all legacy comparisons will be exactly equal.
success_criteria: PASS only if ring and streak each satisfy the positive-fraction and adjusted-interval rules and every original quality field and scalar score is bit-identical to the frozen public implementation.
label: confirmatory

# One-shot holdout protocol

## Epistemic state before acquisition

The 24 sample identifiers and object metadata were selected deterministically
from the official ScrollPrize surface-label listing with seed `20260719`, after
excluding every one of the 30 sample IDs previously present in the LayerLens
workspace. The selection is metadata-only. At preregistration time no selected
holdout image or label file has been downloaded, decoded, summarized, or used
to change the candidate.

The holdout packet hash is
`951939a1073a4828922d525b880d305449240032529646072c26e22fff955376`;
the exclusion-list hash is
`ed5084b05f7073de3ce6f68ee1287a9c298a562f93785accfd326515a600e0f0`.
There are exactly 24 unique selected IDs and zero overlap with the exclusions.

## Frozen candidate and implementations

- LayerLens candidate commit:
  `415131c2fdcf2dbd2e9e45efefbfa5ed003ef147`
- candidate `quality.py` SHA-256:
  `f7720a0001ee33cca2c20f1d191a5cdadb94d36d84332b4e76fb58d004507427`
- candidate `pipeline.py` SHA-256:
  `aa961948d06aa7a9c9b84ac84e2354c93738567cbe5babef4f2fab4e73b10d75`
- frozen public-baseline `quality.py` SHA-256:
  `934c86fd297a51bb21ddb7397cd2c7f1944986921ef56a2870a05cf317c13c6d`
- structured-artifact suite SHA-256:
  `0ae2b2f8ac3c55db0124c5c0cc2511df3fbbb3d905ff1831cf669b5f7e38685f`
- unchanged crop selector SHA-256:
  `9741d26c65a33fd616f312da24dea7c8ea066cf44a8ec3e698ac8528f2bff11b`
- acquisition script SHA-256:
  `4d51951995f1508b60d041ee7297a92b9cf8f5d7b4aea2e70826616bbded05ee`
- primary evaluator SHA-256:
  `f977402cc2e1fc92862aa424d2fd287cdf77da88a0fbdbe6b3f609a13b9c1add`
- independent verifier SHA-256:
  `959f1aa8cc2a0503761fa91f30a3e417eb8ceb7ad489d57685be1c49ca0d1141`
- research-protocol parent commit:
  `0670265aa22654ac52146eeb39cda340b01fdb4c`

Any hash mismatch invalidates execution before scoring. Documentation-only
commits may follow, but the scored source files and parameters may not change.

## Acquisition and deterministic crop preparation

Only after this protocol is committed, acquire exactly the 48 image/label
objects named by the frozen selection. Validate expected byte sizes, readable
TIFF series, image/label shape equality, local SHA-256 values, uniqueness, and
zero overlap. No replacement sample is allowed.

Prepare one 64-by-64-by-64 image crop per source cube. Search starts every 32
voxels on each axis and include the final legal start when it is off-grid.
Choose the crop with the largest exact count of label value `1`, breaking ties
by the first lexicographic `(z,y,x)` start. The label is used only to choose a
reproducible papyrus-rich crop; LayerLens and the artifact diagnostic never see
the label. Record source, crop, and manifest hashes.

## Fixed perturbation and scoring design

For each clean crop, freeze its 1st/99th percentile normalization bounds and
reuse them for every paired corruption. Test only these families:

- `ring`
- `streak`

For each family use severity `0.20`, seeds `104729`, `130363`, and `169087`,
and array/scan axis `0`. Do not score seam or add another family after seeing
the holdout.

The candidate parameters are gradient sigma `0.6`, tensor sigma `2.5`,
persistence sigma `8.0`, scan axis `0`, and stride `4`. The primary response is
`corrupted_persistence_score - clean_persistence_score`. For each family,
average the three seed deltas within each source cube. The source cube, not a
voxel or artifact seed, is the statistical unit (`n=24`).

On every clean and corrupted input, compare the candidate's original
`quality`, `coherence`, `sharpness`, `scale_sharpness`, `confidence`, internal
quality weight, and scalar quality score against the frozen public baseline.
Equality is bit-for-bit, not tolerance-based.

## Primary analysis and decision

For each of the two families, run 10,000 deterministic cube-bootstrap
resamples of the mean. The base seed is `20260720`; a SHA-256-derived family
offset yields a separate fixed stream. Use two-sided `97.5%` percentile
intervals, corresponding to Bonferroni control of familywise alpha `0.05`
across two families.

The confirmatory result is PASS only when all conditions hold:

1. ring has a positive persistence delta on at least 75% of cubes;
2. ring's adjusted interval lower endpoint is greater than zero;
3. streak has a positive persistence delta on at least 75% of cubes;
4. streak's adjusted interval lower endpoint is greater than zero;
5. every legacy candidate/baseline comparison is bit-identical; and
6. every frozen provenance, sample, crop, shape, and arithmetic invariant is
   valid.

Failure of conditions 1-5 is a valid negative/refutation and must be reported
without tuning or rerunning this holdout. Failure of condition 6 is a technical
invalidation: stop, preserve the partial evidence, and do not substitute or
silently repair samples. A materially changed implementation would require a
newly selected, still-untouched holdout and a new preregistration.

## Independent checks

After the primary result is written, the frozen verifier will independently:

- reconstruct every delta and cube mean from the raw records;
- recompute interval decisions with a pure-Python bootstrap stream;
- recompute family means at 50-digit precision;
- report Bonferroni-adjusted t lower bounds and one-sided Wilcoxon sensitivity;
- rerun both families with pure-NumPy finite differences plus explicit box
  averaging and with SciPy Gaussian derivatives plus box averaging.

These checks are secondary. They may expose fragility or implementation error
but cannot replace or overturn the preregistered primary decision.

## Interpretation boundary

A PASS supports a bounded, separately reported structural diagnostic under
controlled broadcast ring and streak stress on disjoint official papyrus-rich
crops. It does not calibrate an artifact probability, estimate the prevalence
of natural scanner artifacts, establish seam or universal artifact coverage,
or justify modifying the original quality score. A negative result narrows or
refutes the candidate claim and will be retained.
