import numpy as np

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
