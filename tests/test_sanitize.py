import numpy as np
import pytest

from src.csi import sanitize_phase


def test_removes_linear_trend_and_wraps():
    t, s = 10, 30
    k = np.arange(s)
    true = 0.3 * np.sin(k / 4.0)  # "real" phase pattern
    offset = 0.8 * k + 1.5  # CFO/STO-like linear distortion
    raw = np.angle(np.exp(1j * (true + offset)))  # wrapped into [-pi, pi]
    raw = np.tile(raw, (t, 1))[..., None, None].repeat(3, 2).repeat(3, 3)

    clean = sanitize_phase(raw)

    assert clean.shape == raw.shape
    # Result should match the true pattern minus its own linear fit.
    expected = true - np.polyval(np.polyfit(k, true, 1), k)
    assert np.allclose(clean[0, :, 0, 0], expected, atol=1e-6)


def test_short_record_is_not_wiped_by_the_median():
    """Zero-padded medfilt used to replace a short nonlinear phase with zeros."""
    k = np.arange(8)
    true = 0.5 * np.sin(k / 1.3)
    out = sanitize_phase(true[None, :, None, None], kernel=5)[0, :, 0, 0]
    expected = true - np.polyval(np.polyfit(k.astype(float), true, 1), k)
    assert np.allclose(out, expected, atol=1e-8)


def test_packet_offsets_do_not_leak_through_the_median():
    """Per-packet slope and offset must be removed before the time median."""
    rng = np.random.default_rng(0)
    t, s = 9, 30
    k = np.arange(s)
    true = 0.4 * np.sin(k / 3.0)
    phase = np.zeros((t, s))
    for i in range(t):
        slope = rng.uniform(-1.5, 1.5)
        offset = rng.uniform(-np.pi, np.pi)
        phase[i] = np.angle(np.exp(1j * (true + slope * (k - k.mean()) + offset)))
    clean = sanitize_phase(phase[:, :, None, None], kernel=3)[:, :, 0, 0]
    expected = true - np.polyval(np.polyfit(k.astype(float), true, 1), k)
    assert np.mean(np.abs(clean - expected)) < 1e-6


def test_linear_fit_uses_subcarrier_indices_when_there_is_a_gap():
    k = np.array([0, 1, 2, 4, 5], dtype=float)  # missing bin 3
    phase = 0.2 * k
    out = sanitize_phase(phase[None, :, None, None], kernel=1, indices=k)[0, :, 0, 0]
    assert np.allclose(out, 0, atol=1e-8)
    # Fitting against 0..4 leaves a residual, because the gap is not one step.
    contiguous = sanitize_phase(phase[None, :, None, None], kernel=1)[0, :, 0, 0]
    assert np.max(np.abs(contiguous)) > 1e-3


def test_kernel_and_nonfinite_phase_rejected():
    phase = np.zeros((4, 8, 1, 1))
    with pytest.raises(ValueError, match="kernel"):
        sanitize_phase(phase, kernel=2)
    phase[0, 0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        sanitize_phase(phase)
