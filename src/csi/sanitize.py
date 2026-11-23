"""CSI phase sanitization, following the steps described in DensePose From WiFi (arXiv:2301.00250).

Steps: unwrap along subcarriers -> median filter over time -> remove per-packet linear phase trend.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import medfilt


def sanitize_phase(phase: np.ndarray, kernel: int = 3) -> np.ndarray:
    """Clean raw CSI phase.

    Args:
        phase: raw phase in radians, shape (time, subcarriers, ...) e.g. (T, 30, 3, 3).
        kernel: odd median-filter length along the time axis (1 disables filtering).

    Returns:
        Sanitized phase with the same shape.
    """
    phase = np.asarray(phase, dtype=np.float64)
    if phase.ndim < 2:
        raise ValueError("phase must have shape (time, subcarriers, ...)")

    # 1. Unwrap 2*pi jumps across subcarriers.
    out = np.unwrap(phase, axis=1)

    # 2. Median filter along time to suppress outliers.
    if kernel > 1:
        if kernel % 2 == 0:
            raise ValueError("kernel must be odd")
        flat = out.reshape(out.shape[0], -1)
        flat = np.stack([medfilt(flat[:, i], kernel) for i in range(flat.shape[1])], axis=1)
        out = flat.reshape(out.shape)

    # 3. Remove linear trend across subcarriers (CFO / STO offsets) per packet & antenna pair.
    n_sub = out.shape[1]
    k = np.arange(n_sub, dtype=np.float64)
    moved = np.moveaxis(out, 1, -1)  # (..., subcarriers)
    flat = moved.reshape(-1, n_sub)
    coeffs = np.polyfit(k, flat.T, deg=1)  # (2, N)
    trend = np.outer(coeffs[0], k) + coeffs[1][:, None]
    flat = flat - trend
    return np.moveaxis(flat.reshape(moved.shape), -1, 1)
