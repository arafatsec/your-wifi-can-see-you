"""Heuristics on one ESP32 link: motion, fluctuation spectrum, breathing, occupancy, room change.

Nothing in this module has been checked against a labelled recording from this project.
`estimate_occupancy` is always `validated=False`. Breathing is a band-pass peak, not a
medical measurement. The spectrum is a Doppler-*like* view of amplitude over time, not
a speed in m/s. `profile_change` compares two amplitude shapes; it does not name objects.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfiltfilt

OCCUPANCY_LABEL = "estimate, not yet validated"
BREATH_NOTE = "Band-pass estimate on CSI amplitude. Not a medical measurement."
SPECTRUM_NOTE = (
    "Temporal fluctuation spectrum of CSI amplitude. A Doppler-like proxy, not a speed in m/s."
)
STATIC_NOTE = (
    "Compares amplitude shape with the empty-room baseline. A rise means the static "
    "multipath changed (someone still, a door, furniture). This is not object recognition."
)


def coefficient_of_variation(window: np.ndarray) -> float:
    """Mean over subcarriers of (std / mean) along time.

    `window` is (time, subcarriers), already gain-normalised if the caller removed
    per-packet AGC. Subcarriers with a near-zero mean are ignored. Returns NaN when
    there are fewer than two packets or no usable subcarrier.
    """
    window = np.asarray(window, dtype=np.float64)
    if window.ndim != 2 or window.shape[0] < 2:
        return float("nan")
    mean = window.mean(axis=0)
    ok = mean > 1e-6
    if not np.any(ok):
        return float("nan")
    return float(np.mean(window.std(axis=0)[ok] / mean[ok]))


def subcarrier_std(window: np.ndarray) -> np.ndarray:
    """Per-subcarrier amplitude standard deviation over time, shape (subcarriers,)."""
    window = np.asarray(window, dtype=np.float64)
    if window.ndim != 2 or window.shape[0] < 2:
        return np.zeros(window.shape[-1] if window.ndim == 2 else 0, dtype=np.float64)
    return window.std(axis=0)


def _sample_rate(n: int, duration_s: float) -> float:
    if n < 2 or duration_s <= 0:
        return 0.0
    return (n - 1) / duration_s


def fluctuation_spectrum(
    window: np.ndarray,
    fs: float,
    band: tuple[float, float] = (0.5, 8.0),
    n_bins: int = 32,
) -> dict:
    """Average amplitude spectrum across subcarriers, plus the share of energy in `band`.

    DC is excluded from the energy fraction. `dominant_hz` is the strongest bin at or
    above the low edge of `band` (body motion), not a radial velocity.
    """
    empty = {
        "freqs": [],
        "power": [],
        "band_hz": [band[0], band[1]],
        "band_fraction": None,
        "dominant_hz": None,
        "note": SPECTRUM_NOTE,
    }
    window = np.asarray(window, dtype=np.float64)
    if window.ndim != 2 or window.shape[0] < 8 or not np.isfinite(fs) or fs <= 0:
        return empty
    x = window - window.mean(axis=0, keepdims=True)
    spec = np.mean(np.abs(np.fft.rfft(x, axis=0)) ** 2, axis=1)
    freqs = np.fft.rfftfreq(window.shape[0], d=1.0 / fs)
    ac = float(spec[1:].sum()) + 1e-12
    band_mask = (freqs >= band[0]) & (freqs <= min(band[1], fs / 2.0))
    fraction = float(spec[band_mask].sum() / ac) if np.any(band_mask) else 0.0
    # Only call a bin "dominant" when it stands out inside the motion band.
    # The argmax of a flat noisy spectrum is not a body frequency, and it used
    # to land anywhere up to the Nyquist rate.
    dominant = None
    if np.any(band_mask):
        band_spec = spec[band_mask]
        peak = float(band_spec.max())
        floor = float(np.median(band_spec))
        if peak > max(3.0 * floor, 1e-18):
            dominant = float(freqs[band_mask][int(np.argmax(band_spec))])

    fmax = min(fs / 2.0, 10.0)
    edges = np.linspace(0.0, fmax, n_bins + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    power = np.zeros(n_bins, dtype=np.float64)
    for i in range(n_bins):
        sel = (freqs >= edges[i]) & (freqs < edges[i + 1] if i < n_bins - 1 else freqs <= edges[i + 1])
        if np.any(sel):
            power[i] = float(spec[sel].mean())
    peak = float(power.max())
    if peak > 0:
        power = power / peak
    return {
        "freqs": [round(float(f), 3) for f in centers],
        "power": [round(float(p), 3) for p in power],
        "band_hz": [band[0], band[1]],
        "band_fraction": round(fraction, 3),
        "dominant_hz": None if dominant is None else round(dominant, 2),
        "note": SPECTRUM_NOTE,
    }


def _parabolic_peak(power: np.ndarray, freqs: np.ndarray) -> float:
    peak = int(np.argmax(power))
    freq = float(freqs[peak])
    if 0 < peak < len(power) - 1:
        a, b, c = float(power[peak - 1]), float(power[peak]), float(power[peak + 1])
        denom = a - 2 * b + c
        if denom != 0:
            delta = float(np.clip(0.5 * (a - c) / denom, -0.5, 0.5))
            step = float(freqs[1] - freqs[0]) if len(freqs) > 1 else 0.0
            freq += delta * step
    return freq


def estimate_respiration(
    window: np.ndarray,
    fs: float,
    band: tuple[float, float] = (0.1, 0.5),
    min_seconds: float = 20.0,
) -> dict:
    """Breaths per minute from a band-pass of CSI amplitude.

    Each subcarrier is mean-removed. Confidence is the share of that subcarrier's
    AC energy that already sits in `band` *before* filtering, so the filter cannot
    inflate it. The reported rate is the spectral peak after a 2nd-order band-pass.
    `reliable` stays false until the window is long enough, the peak is inside
    6–30 breaths/min, confidence is at least 0.35, and faster fluctuations do not
    dominate. A person walking makes this unreliable on purpose.
    """
    lo, hi = band

    def pack(bpm, reliable, confidence, reason, seconds, filtered):
        return {
            "bpm": None if bpm is None else round(float(bpm), 1),
            "reliable": bool(reliable),
            "confidence": None if confidence is None else round(float(confidence), 3),
            "reason": reason,
            "band_hz": [lo, hi],
            "seconds": None if seconds is None else round(float(seconds), 1),
            "filtered": bool(filtered),
            "note": BREATH_NOTE,
        }

    window = np.asarray(window, dtype=np.float64)
    if window.ndim != 2 or window.shape[0] < 8 or not np.isfinite(fs) or fs <= 1.0:
        return pack(None, False, None, "not enough amplitude history", None, False)
    seconds = window.shape[0] / fs
    x = window - np.mean(window, axis=0, keepdims=True)
    if float(np.max(np.std(x, axis=0))) < 1e-8:
        return pack(None, False, 0.0, "amplitude is flat", seconds, False)

    freqs = np.fft.rfftfreq(window.shape[0], d=1.0 / fs)
    raw = np.abs(np.fft.rfft(x, axis=0)) ** 2
    band_mask = (freqs >= lo) & (freqs <= hi)
    if hi >= fs / 2:
        return pack(None, False, None, "sample rate cannot resolve the breathing band", seconds, False)
    if not np.any(band_mask):
        return pack(None, False, None, "window is too short to resolve the breathing band", seconds, False)

    band_power = raw[band_mask].sum(axis=0)
    ac_power = raw[freqs > 0].sum(axis=0) + 1e-12
    confidence_per = band_power / ac_power
    idx = int(np.argmax(band_power))
    confidence = float(confidence_per[idx])

    filtered = x
    used_filter = False
    if seconds >= 8:
        try:
            sos = butter(2, [lo, hi], btype="bandpass", fs=fs, output="sos")
            filtered = sosfiltfilt(sos, x, axis=0)
            used_filter = True
        except ValueError:
            filtered = x
    spec = np.abs(np.fft.rfft(filtered[:, idx])) ** 2
    bpm = _parabolic_peak(spec[band_mask], freqs[band_mask]) * 60.0

    motion_power = float(raw[freqs >= 0.8, idx].sum()) if np.any(freqs >= 0.8) else 0.0
    breath_power = float(raw[band_mask, idx].sum())
    moving = motion_power > 2.0 * max(breath_power, 1e-12)

    in_range = 6.0 <= bpm <= 30.0
    long_enough = seconds >= min_seconds
    clear = confidence >= 0.35
    reliable = bool(long_enough and clear and in_range and not moving)
    if not long_enough:
        reason = f"need about {min_seconds:.0f} s of packets before this can be called reliable"
    elif moving:
        reason = "faster fluctuation in this window dominates the breathing band"
    elif not clear:
        reason = "no clear periodic component in the breathing band"
    elif not in_range:
        reason = "peak is outside 6–30 breaths/min"
    else:
        reason = "strongest peak in the 0.1–0.5 Hz band on the quietest-looking subcarrier"
    return pack(bpm, reliable, confidence, reason, seconds, used_filter)


def estimate_occupancy(motion: float, threshold: float) -> dict:
    """Coarse 0 / 1 / 2+ guess from how far the motion score sits above the empty-room threshold.

    This is not a trained counter. One person moving quickly crosses the same 2.5× line
    that a second person might. The reason string says so when the estimate is ``2+``.
    """
    base = {"validated": False, "label": OCCUPANCY_LABEL}
    if motion is None or threshold is None:
        return {**base, "estimate": None, "reason": "no motion score yet"}
    try:
        motion_f, thr = float(motion), float(threshold)
    except (TypeError, ValueError):
        return {**base, "estimate": None, "reason": "no motion score yet"}
    if not np.isfinite(motion_f) or not np.isfinite(thr):
        return {**base, "estimate": None, "reason": "no motion score yet"}
    if motion_f <= thr:
        estimate, reason = "0", "motion is at or below the empty-room threshold"
    elif motion_f <= thr * 2.5:
        estimate, reason = "1", "above the empty-room threshold; not high enough to suggest another person"
    else:
        estimate, reason = (
            "2+",
            "above 2.5× the empty-room threshold. One person moving quickly can do this too",
        )
    return {**base, "estimate": estimate, "reason": reason}


def profile_change(current: np.ndarray, baseline: np.ndarray) -> float:
    """``1 - correlation`` of two amplitude profiles. 0 matches; higher means the shape moved.

    Both vectors must be the same length. A flat profile (no shape) reports 0 rather than
    dividing by zero. The result is clipped to [0, 2].
    """
    a = np.asarray(current, dtype=np.float64).ravel()
    b = np.asarray(baseline, dtype=np.float64).ravel()
    if a.shape != b.shape or a.size < 2:
        raise ValueError("profiles must be finite arrays of the same length (>= 2)")
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        raise ValueError("profiles must be finite arrays of the same length (>= 2)")
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-12:
        return 0.0
    corr = float(np.dot(a, b) / denom)
    return float(np.clip(1.0 - corr, 0.0, 2.0))


def rssi_band(rssi_dbm: float | None) -> str:
    """Coarse link label from RSSI. This describes the radio link, not sensing accuracy."""
    if rssi_dbm is None:
        return "unknown"
    try:
        value = float(rssi_dbm)
    except (TypeError, ValueError):
        return "unknown"
    if not np.isfinite(value):
        return "unknown"
    if value >= -55:
        return "strong"
    if value >= -75:
        return "fair"
    return "weak"
