"""Reference-free local layer-separability measurements.

The baseline deliberately uses conventional, inspectable image statistics.
Papyrus interfaces should produce strong gradients whose directions agree in a
small neighbourhood. Random noise can produce strong gradients, but not a
stable dominant direction. Haze and blur weaken the gradients even when the
remaining direction is coherent. The score therefore combines both signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy import ndimage as ndi


FloatArray = NDArray[np.float32]


@dataclass(frozen=True)
class QualityMap:
    """Coarse local quality maps and their volume-level summary."""

    quality: FloatArray
    coherence: FloatArray
    sharpness: FloatArray
    scale_sharpness: FloatArray
    confidence: FloatArray
    weight: FloatArray
    score: float
    stride: tuple[int, ...]


def _as_tuple(value: int | Sequence[int], ndim: int) -> tuple[int, ...]:
    if isinstance(value, int):
        result = (value,) * ndim
    else:
        result = tuple(int(item) for item in value)
    if len(result) != ndim or any(item < 1 for item in result):
        raise ValueError(f"stride must contain {ndim} positive integers")
    return result


def _robust_normalize(
    volume: ArrayLike, bounds: tuple[float, float] | None = None
) -> FloatArray:
    data = np.asarray(volume)
    if data.ndim not in (2, 3):
        raise ValueError(f"expected a 2D image or 3D volume, got shape {data.shape}")
    if not np.issubdtype(data.dtype, np.number):
        raise TypeError(f"expected numeric input, got {data.dtype}")

    finite = np.isfinite(data)
    if not finite.any():
        raise ValueError("input contains no finite values")
    values = data[finite].astype(np.float32, copy=False)
    if bounds is None:
        lower, upper = np.percentile(values, (1.0, 99.0))
    else:
        lower, upper = (float(item) for item in bounds)
        if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
            raise ValueError("normalization bounds must be finite and increasing")
    if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
        return np.zeros(data.shape, dtype=np.float32)

    normalized = (data.astype(np.float32, copy=False) - np.float32(lower)) / np.float32(
        upper - lower
    )
    normalized = np.nan_to_num(normalized, nan=0.0, posinf=1.0, neginf=0.0)
    return np.clip(normalized, 0.0, 1.0).astype(np.float32, copy=False)


def _weighted_mean(values: FloatArray, weights: FloatArray) -> float:
    total = float(np.sum(weights, dtype=np.float64))
    if total <= 1e-12:
        return 0.0
    return float(np.sum(values * weights, dtype=np.float64) / total)


def compute_quality(
    volume: ArrayLike,
    *,
    gradient_sigma: float = 0.6,
    tensor_sigma: float = 2.5,
    stride: int | Sequence[int] = 4,
    normalization: tuple[float, float] | None = None,
) -> QualityMap:
    """Compute a reference-free local layer-separability map.

    Parameters are expressed in voxels. ``stride`` only controls output
    sampling; derivatives and tensor integration are evaluated at full input
    resolution before sampling. ``normalization`` can provide global 1st and
    99th percentile bounds when adjacent tiles must share one intensity scale.
    """

    if (
        not np.isfinite(gradient_sigma)
        or not np.isfinite(tensor_sigma)
        or gradient_sigma <= 0
        or tensor_sigma <= 0
    ):
        raise ValueError("gradient_sigma and tensor_sigma must be positive and finite")

    data = _robust_normalize(volume, normalization)
    stride_tuple = _as_tuple(stride, data.ndim)
    sample = tuple(slice(step // 2, None, step) for step in stride_tuple)

    gradients: list[FloatArray] = []
    for axis in range(data.ndim):
        order = [0] * data.ndim
        order[axis] = 1
        gradient = ndi.gaussian_filter(
            data,
            sigma=gradient_sigma,
            order=tuple(order),
            mode="reflect",
        ).astype(np.float32, copy=False)
        gradients.append(gradient)

    coarse_shape = gradients[0][sample].shape
    matrices = np.empty((*coarse_shape, data.ndim, data.ndim), dtype=np.float32)
    for row in range(data.ndim):
        for column in range(row, data.ndim):
            component = ndi.gaussian_filter(
                gradients[row] * gradients[column],
                sigma=tensor_sigma,
                mode="reflect",
            )[sample]
            matrices[..., row, column] = component
            matrices[..., column, row] = component

    eigenvalues = np.linalg.eigvalsh(matrices)
    largest = np.maximum(eigenvalues[..., -1], 0.0)
    second = np.maximum(eigenvalues[..., -2], 0.0)
    eps = np.float32(1e-8)
    coherence = (largest - second) / (largest + eps)
    coherence = np.clip(coherence, 0.0, 1.0).astype(np.float32, copy=False)

    # Remove the isotropic part of the tensor before calling the response an
    # edge.  White noise lifts every eigenvalue, whereas a sheet interface
    # primarily lifts the dominant one.  This keeps the multiscale sharpness
    # ratio from rewarding added high-frequency noise.
    edge_strength = np.sqrt(np.maximum(largest - second, 0.0), dtype=np.float32)
    # The robust intensity normalization fixes the useful signal range.  Do
    # not divide by the high-pass residual estimate here: genuine sub-sheet
    # texture in high-resolution papyrus is also high-frequency and would be
    # misclassified as scanner noise.  Tensor coherence provides the noise
    # rejection term, while this fixed scale measures retained edge strength.
    edge_snr = edge_strength / np.float32(0.04)
    sharpness = (edge_snr / (1.0 + edge_snr)).astype(np.float32, copy=False)

    trace = np.maximum(np.sum(eigenvalues, axis=-1), 0.0)
    support_snr = np.sqrt(trace, dtype=np.float32) / np.float32(0.04)
    confidence = (support_snr / (0.5 + support_snr)).astype(np.float32, copy=False)

    # Edge amplitude alone is not a scale-free sharpness measure: robust
    # normalization can re-expand a blurred volume.  Compare the same
    # directional edge energy at a coarser derivative scale.  Sharp sheet
    # interfaces lose substantially more response at the coarse scale than
    # already-blurred interfaces, making the ratio invariant to scanner gain.
    coarse_sigma = max(1.5, 2.5 * gradient_sigma)
    additional_sigma = np.sqrt(coarse_sigma**2 - gradient_sigma**2)
    for index, gradient in enumerate(gradients):
        gradients[index] = ndi.gaussian_filter(
            gradient, sigma=additional_sigma, mode="reflect"
        ).astype(np.float32, copy=False)
    coarse_matrices = np.empty_like(matrices)
    for row in range(data.ndim):
        for column in range(row, data.ndim):
            component = ndi.gaussian_filter(
                gradients[row] * gradients[column],
                sigma=tensor_sigma,
                mode="reflect",
            )[sample]
            coarse_matrices[..., row, column] = component
            coarse_matrices[..., column, row] = component
    coarse_eigenvalues = np.linalg.eigvalsh(coarse_matrices)
    coarse_largest = np.maximum(coarse_eigenvalues[..., -1], 0.0)
    coarse_second = np.maximum(coarse_eigenvalues[..., -2], 0.0)
    coarse_strength = np.sqrt(
        np.maximum(coarse_largest - coarse_second, 0.0), dtype=np.float32
    )
    scale_ratio = edge_strength / (coarse_strength + eps)
    scale_sharpness = np.clip((scale_ratio - 1.0) / 0.8, 0.0, 1.0).astype(
        np.float32, copy=False
    )

    # A mild super-linear coherence response suppresses chance alignments in
    # isotropic noise without the real-data degradation regression caused by
    # a hard veto or a squared response.
    quality = (
        np.power(coherence, 1.5)
        * np.power(sharpness, 1.5)
        * scale_sharpness
    ).astype(np.float32, copy=False)
    weights = confidence * np.sqrt(np.maximum(edge_strength, 0.0), dtype=np.float32)
    score = _weighted_mean(quality, weights)

    return QualityMap(
        quality=quality,
        coherence=coherence,
        sharpness=sharpness,
        scale_sharpness=scale_sharpness,
        confidence=confidence,
        weight=weights,
        score=score,
        stride=stride_tuple,
    )
