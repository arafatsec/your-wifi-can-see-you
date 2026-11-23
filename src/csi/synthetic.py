"""Simple physics-based synthetic CSI generator.

⚠️ SYNTHETIC DATA. This is for unit tests, tutorials and sanity checks only. It is a toy
multipath model: it is NOT realistic enough to train or evaluate pose models, and results on it
must never be reported as real-world performance. Output is always marked `synthetic=True`.

Model (2D room, point scatterers, far from perfect on purpose):

    H(f, t) = sum_p  a_p / d_p(t) * exp(-j 2 pi f d_p(t) / c)      (channel)
              * exp(-j (2 pi f_k * sto + cfo_phase))                (per-packet hardware offsets)
              + noise

Paths: line-of-sight TX->RX, fixed wall/furniture reflectors, and optionally one moving person
modeled as a single reflector following a trajectory.
"""
from __future__ import annotations

import numpy as np

from .types import CSIData

C = 299_792_458.0  # speed of light, m/s


def subcarrier_frequencies(center_hz: float = 2.437e9, bandwidth_hz: float = 20e6,
                           n_subcarriers: int = 30) -> np.ndarray:
    """Evenly spaced subcarrier frequencies across the band (Intel 5300-style 30 groups)."""
    half = bandwidth_hz / 2
    return np.linspace(center_hz - half, center_hz + half, n_subcarriers)


def _antenna_positions(base: np.ndarray, n: int, spacing: float) -> np.ndarray:
    offsets = (np.arange(n) - (n - 1) / 2) * spacing
    return base[None, :] + np.stack([np.zeros(n), offsets], axis=1)


def generate_room_csi(
    duration_s: float = 2.0,
    sample_rate_hz: float = 100.0,
    n_tx: int = 3,
    n_rx: int = 3,
    n_subcarriers: int = 30,
    center_hz: float = 2.437e9,
    bandwidth_hz: float = 20e6,
    room_size: tuple[float, float] = (6.0, 4.0),
    n_static_reflectors: int = 6,
    person: bool = True,
    person_speed_mps: float = 0.8,
    snr_db: float = 25.0,
    hardware_offsets: bool = True,
    seed: int | None = 0,
) -> CSIData:
    """Generate a synthetic CSI recording of a room, optionally with a walking person.

    Ground-truth person positions (or None) are stored in `metadata["person_xy"]`.
    """
    rng = np.random.default_rng(seed)
    n_t = max(1, int(round(duration_s * sample_rate_hz)))
    t = np.arange(n_t) / sample_rate_hz
    freqs = subcarrier_frequencies(center_hz, bandwidth_hz, n_subcarriers)
    lam = C / center_hz
    w, h = room_size

    tx = _antenna_positions(np.array([0.3, h / 2]), n_tx, lam / 2)       # (n_tx, 2)
    rx = _antenna_positions(np.array([w - 0.3, h / 2]), n_rx, lam / 2)   # (n_rx, 2)

    # Path lengths, shape (time, n_tx, n_rx, n_paths); gains, shape (n_paths,)
    dist = lambda a, b: np.linalg.norm(a - b, axis=-1)  # noqa: E731
    los = dist(tx[:, None, :], rx[None, :, :])[None, ..., None].repeat(n_t, 0)
    lengths = [los]
    gains = [1.0]

    refl = rng.uniform([0, 0], [w, h], size=(n_static_reflectors, 2))
    for r in refl:
        d = dist(tx, r)[:, None] + dist(rx, r)[None, :]
        lengths.append(d[None, ..., None].repeat(n_t, 0))
        gains.append(rng.uniform(0.2, 0.6))

    person_xy = None
    if person:
        # Walk back and forth along a line across the middle of the room.
        x0, x1 = 1.5, w - 1.5
        span = x1 - x0
        s = (person_speed_mps * t) % (2 * span)
        x = x0 + np.where(s < span, s, 2 * span - s)
        y = h / 2 + 0.8 + 0.1 * np.sin(2 * np.pi * 1.5 * t)  # small torso sway
        person_xy = np.stack([x, y], axis=1)                  # (time, 2)
        d = (dist(tx[None, :, None, :], person_xy[:, None, None, :])
             + dist(rx[None, None, :, :], person_xy[:, None, None, :]))
        lengths.append(d[..., None])
        gains.append(0.5)

    L = np.concatenate(lengths, axis=-1)            # (time, n_tx, n_rx, P)
    g = np.asarray(gains)                           # (P,)
    f = freqs[None, :, None, None, None]            # (1, S, 1, 1, 1)
    Lb = L[:, None]                                  # (time, 1, n_tx, n_rx, P)
    H = np.sum(g / Lb * np.exp(-2j * np.pi * f * Lb / C), axis=-1)  # (time, S, n_tx, n_rx)

    if hardware_offsets:
        # Random per-packet STO (linear in subcarrier freq) and CFO (constant) phase offsets.
        sto = rng.uniform(-50e-9, 50e-9, size=n_t)
        cfo = rng.uniform(-np.pi, np.pi, size=n_t)
        offset = 2 * np.pi * (freqs[None, :] - center_hz) * sto[:, None] + cfo[:, None]
        H = H * np.exp(-1j * offset)[..., None, None]

    sig_power = np.mean(np.abs(H) ** 2)
    noise_power = sig_power / (10 ** (snr_db / 10))
    H = H + np.sqrt(noise_power / 2) * (rng.standard_normal(H.shape) + 1j * rng.standard_normal(H.shape))

    return CSIData(
        csi=H,
        timestamps=t,
        subcarrier_freqs=freqs,
        source="synthetic",
        synthetic=True,
        metadata={
            "generator": "generate_room_csi",
            "seed": seed,
            "room_size": room_size,
            "person_xy": person_xy,
            "warning": "Synthetic toy data - not valid for reporting real-world results.",
        },
    )
