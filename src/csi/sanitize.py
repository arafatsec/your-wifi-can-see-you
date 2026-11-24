"""CSI phase sanitization.

The three operations named in DensePose From WiFi (arXiv:2301.00250) are all here:
unwrap along subcarriers, a median filter over time, and removal of the per-packet
linear phase trend (CFO / STO).

The linear trend is removed *before* the median filter. A median taken while each
packet still carries its own slope and offset stitches neighbouring packets together
across subcarriers, and the trend that remains is no longer a straight line. The
filter also uses edge replication rather than zero padding, which otherwise wipes a
short recording toward 0.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter


def sanitize_phase(phase: np.ndarray, kernel: int = 3, indices: np.ndarray | None = None) -> np.ndarray:
    """Clean raw CSI phase.

    Args:
        phase: raw phase in radians, shape (time, subcarriers, ...), e.g. (T, 30, 3, 3).
        kernel: odd median-filter length along time. 1 disables the filter. The filter
            is also skipped when the recording is shorter than `kernel`.
        indices: subcarrier index of each column (length = subcarriers). The linear
            trend is fit against these, so a missing DC bin is not treated as one step.
            Defaults to 0 .. S-1, which is right only when the columns are contiguous.

    Returns:
        Sanitized phase with the same shape. The per-packet slope and mean are gone.
    """
    phase = np.asarray(phase, dtype=np.float64)
    if phase.ndim < 2:
        raise ValueError("phase must have shape (time, subcarriers, ...)")
    if not np.all(np.isfinite(phase)):
        raise ValueError("phase must be finite")
    if isinstance(kernel, bool) or not isinstance(kernel, (int, np.integer)):
        raise ValueError("kernel must be 1 or a positive odd integer")
    kernel = int(kernel)
    if kernel != 1 and (kernel < 1 or kernel % 2 == 0):
        raise ValueError("kernel must be 1 or a positive odd integer")

    out = np.unwrap(phase, axis=1)
    out = _remove_linear_trend(out, indices)

    if kernel > 1 and out.shape[0] >= kernel:
        size = (kernel,) + (1,) * (out.ndim - 1)
        out = median_filter(out, size=size, mode="nearest")
    return out


def _remove_linear_trend(phase: np.ndarray, indices: np.ndarray | None) -> np.ndarray:
    """Subtract a least-squares line vs subcarrier index, per packet and antenna."""
    n_sub = phase.shape[1]
    if indices is None:
        k = np.arange(n_sub, dtype=np.float64)
    else:
        k = np.asarray(indices, dtype=np.float64)
        if k.shape != (n_sub,) or not np.all(np.isfinite(k)):
            raise ValueError(f"indices must be a finite array of shape ({n_sub},)")
    if n_sub < 2 or np.unique(k).size < 2:
        return phase

    k = k - k.mean()
    denom = float(np.dot(k, k))
    if denom == 0.0:
        return phase
    moved = np.moveaxis(phase, 1, -1)
    mean = moved.mean(axis=-1, keepdims=True)
    slope = (moved * k).sum(axis=-1, keepdims=True) / denom
    flat = moved - (mean + slope * k)
    return np.moveaxis(flat, -1, 1)
