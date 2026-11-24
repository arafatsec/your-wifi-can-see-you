"""Standard in-memory format for CSI recordings.

Every loader (Intel 5300, Nexmon, ESP32, ...) and every generator should return a `CSIData`,
so preprocessing and models never depend on where the data came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class CSIData:
    """A CSI recording.

    Attributes:
        csi: complex channel estimates, shape (time, subcarriers, n_tx, n_rx).
        timestamps: seconds since start of recording, shape (time,), non-decreasing.
        subcarrier_freqs: absolute subcarrier frequencies in Hz, shape (subcarriers,).
        source: where the data came from, e.g. "intel5300", "nexmon", "esp32", "synthetic".
        synthetic: True if generated rather than measured. Never mix this up in results.
        metadata: free-form extras (device, room, subject id, ground truth, ...).
    """

    csi: np.ndarray
    timestamps: np.ndarray
    subcarrier_freqs: np.ndarray
    source: str
    synthetic: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.csi = np.asarray(self.csi)
        self.timestamps = np.asarray(self.timestamps, dtype=np.float64)
        self.subcarrier_freqs = np.asarray(self.subcarrier_freqs, dtype=np.float64)

        if not np.iscomplexobj(self.csi):
            raise ValueError("csi must be a complex array")
        if self.csi.ndim != 4:
            raise ValueError(f"csi must have shape (time, subcarriers, n_tx, n_rx), got {self.csi.shape}")
        t, s = self.csi.shape[:2]
        if self.timestamps.shape != (t,):
            raise ValueError(f"timestamps must have shape ({t},), got {self.timestamps.shape}")
        if self.subcarrier_freqs.shape != (s,):
            raise ValueError(f"subcarrier_freqs must have shape ({s},), got {self.subcarrier_freqs.shape}")
        if t > 1 and np.any(np.diff(self.timestamps) < 0):
            raise ValueError("timestamps must be non-decreasing")
        if self.synthetic != (self.source == "synthetic"):
            raise ValueError("synthetic data must use source='synthetic' and synthetic=True")

    @property
    def amplitude(self) -> np.ndarray:
        return np.abs(self.csi)

    @property
    def phase(self) -> np.ndarray:
        """Raw (wrapped) phase in radians. Use `sanitize_phase` before feeding a model."""
        return np.angle(self.csi)

    @property
    def n_packets(self) -> int:
        return self.csi.shape[0]

    @property
    def sample_rate(self) -> float:
        """Mean packet rate in Hz (0.0 if fewer than two packets)."""
        if self.n_packets < 2:
            return 0.0
        span = self.timestamps[-1] - self.timestamps[0]
        return (self.n_packets - 1) / span if span > 0 else 0.0
