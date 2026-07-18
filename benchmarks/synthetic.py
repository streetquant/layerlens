"""Deterministic layered CT-like phantoms."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage as ndi


def _layer_distance(size: int, angle_degrees: float) -> NDArray[np.float32]:
    axis = np.linspace(-1.0, 1.0, size, dtype=np.float32)
    z, y, x = np.meshgrid(axis, axis, axis, indexing="ij")
    angle = np.deg2rad(angle_degrees)
    normal_coordinate = x * np.cos(angle) + y * np.sin(angle)
    normal_coordinate += 0.06 * np.sin(2.5 * np.pi * z)
    spacing = 0.22
    return np.mod(normal_coordinate + spacing / 2.0, spacing) - spacing / 2.0


def layer_mask(
    size: int = 48, *, angle_degrees: float = 23.0
) -> NDArray[np.bool_]:
    """Return the ideal thin-sheet support for a matching phantom."""

    return np.abs(_layer_distance(size, angle_degrees)) <= 0.025


def layered_phantom(
    size: int = 48,
    *,
    angle_degrees: float = 23.0,
    blur_sigma: float = 0.4,
    noise_sigma: float = 0.02,
    seed: int = 0,
) -> NDArray[np.float32]:
    """Create curved, approximately parallel bright papyrus interfaces."""

    axis = np.linspace(-1.0, 1.0, size, dtype=np.float32)
    z = np.meshgrid(axis, axis, axis, indexing="ij")[0]
    distance = _layer_distance(size, angle_degrees)
    sheets = np.exp(-0.5 * (distance / 0.025) ** 2)

    # Low-frequency attenuation variation mimics uneven carbonized material.
    attenuation = 0.7 + 0.25 * (z + 1.0) / 2.0
    volume = 0.12 + attenuation * sheets
    volume = ndi.gaussian_filter(volume.astype(np.float32), blur_sigma, mode="reflect")
    rng = np.random.default_rng(seed)
    volume += rng.normal(0.0, noise_sigma, volume.shape).astype(np.float32)
    return np.clip(volume, 0.0, 1.0).astype(np.float32, copy=False)
