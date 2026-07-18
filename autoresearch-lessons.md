# LayerLens autoresearch lessons

## Lesson 1 — iterations 1-8

**Pattern**: Retain fine gradients, integrate their orientation over a wider
neighbourhood, and measure edge strength on the robust-normalized intensity
scale rather than dividing by a high-pass residual estimate.

**Why it worked**: Real high-resolution papyrus texture is high-frequency and
was mistaken for noise, while true sheet interfaces remain directionally
stable over a larger neighbourhood. Separating sharpness from coherence kept
both signals available.

**Conditions**: Applies to robust-normalized, layer-dominated 2D or 3D CT
inputs where scanner gain is arbitrary but spatial orientation is meaningful.

**Anti-pattern**: Softening the coherence exponent, linearly emphasizing the
strongest edges, or shrinking tensor integration all reduced the composite
score.

**Metric delta**: +7.829106 cumulative from the baseline.

## Lesson 2 — iterations 9-16

**Pattern**: Combine super-linear retained-edge sharpness with a fine-to-coarse
derivative response ratio, subtract the tensor's isotropic energy before
measuring edge strength, and apply only a mild super-linear coherence response.

**Why it worked**: Absolute edge amplitude is not invariant to robust contrast
normalization, but a sharp interface loses more response when measured at a
coarser derivative scale.  Subtracting the second eigenvalue prevents isotropic
noise from masquerading as that fine-scale response.  A 1.5 coherence power
then removes residual chance alignment while preserving monotonic degradation
ordering on every official holdout crop.

**Conditions**: Applies when fine and coarse derivatives are computed from the
same normalized 2D or 3D region and tensor integration is wide enough to
capture locally curved but organized interfaces.

**Anti-pattern**: A squared coherence response was too aggressive and reduced
real-data degradation rank.  Foreground-versus-background edge AUC is not a
valid validation target because official background includes legitimate verso
and non-recto structure.  Synthetic quality truth should be measured from the
task signal rather than assigned by a hand-authored blur/noise formula.

**Metric delta**: Iteration 16 improved benchmark v3 by +0.287256 to 95.966458.
Benchmark resets at iterations 11 and 15 make cross-version deltas non-additive.
