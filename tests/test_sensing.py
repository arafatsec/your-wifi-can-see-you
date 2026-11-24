"""Tests for the unvalidated sensing heuristics."""
import numpy as np
import pytest

from src.csi.sensing import (
    OCCUPANCY_LABEL,
    coefficient_of_variation,
    estimate_occupancy,
    estimate_respiration,
    fluctuation_spectrum,
    profile_change,
    rssi_band,
)


def test_coefficient_of_variation_ignores_dead_subcarriers():
    window = np.ones((20, 4))
    window[:, 3] = 0
    window[:, 0] += np.linspace(-0.2, 0.2, 20)
    score = coefficient_of_variation(window)
    assert 0.01 < score < 0.2
    assert np.isnan(coefficient_of_variation(np.ones((1, 4))))


def test_fluctuation_spectrum_finds_a_tone_and_is_not_a_velocity():
    fs = 20.0
    t = np.arange(int(4 * fs)) / fs
    tone = np.sin(2 * np.pi * 2.0 * t)
    window = np.repeat(tone[:, None], 6, axis=1)
    spec = fluctuation_spectrum(window, fs)
    assert spec["dominant_hz"] == pytest.approx(2.0, abs=0.2)
    assert spec["band_fraction"] > 0.5
    assert "not a speed" in spec["note"]
    flat = fluctuation_spectrum(np.ones_like(window), fs)
    assert flat["band_fraction"] == 0.0
    assert flat["dominant_hz"] is None
    rng = np.random.default_rng(1)
    noise = fluctuation_spectrum(rng.standard_normal((int(4 * fs), 6)), fs)
    assert noise["dominant_hz"] is None or 0.5 <= noise["dominant_hz"] <= 8.0


def test_respiration_recovers_a_still_breathing_tone():
    fs = 20.0
    bpm = 12.0  # 0.2 Hz, exactly on a bin over 30 s
    t = np.arange(int(30 * fs)) / fs
    tone = np.sin(2 * np.pi * (bpm / 60.0) * t)
    rng = np.random.default_rng(0)
    window = 0.02 * rng.standard_normal((len(t), 8))
    window[:, 3] += tone
    out = estimate_respiration(window, fs)
    assert out["bpm"] == pytest.approx(bpm, abs=1.0)
    assert out["reliable"] is True
    assert "Not a medical measurement" in out["note"]


def test_respiration_is_unreliable_while_a_faster_motion_dominates():
    fs = 20.0
    t = np.arange(int(30 * fs)) / fs
    walk = np.sin(2 * np.pi * 2.0 * t)
    window = np.repeat(walk[:, None], 4, axis=1)
    out = estimate_respiration(window, fs)
    assert out["reliable"] is False
    assert "dominates" in out["reason"]


def test_respiration_needs_a_long_enough_window():
    fs = 20.0
    t = np.arange(int(5 * fs)) / fs
    window = np.sin(2 * np.pi * 0.25 * t)[:, None] * np.ones((len(t), 3))
    out = estimate_respiration(window, fs)
    assert out["reliable"] is False
    assert "20" in out["reason"]


def test_occupancy_thresholds_and_the_unvalidated_label():
    assert estimate_occupancy(0.02, 0.05)["estimate"] == "0"
    mid = estimate_occupancy(0.08, 0.05)
    assert mid["estimate"] == "1" and mid["validated"] is False and mid["label"] == OCCUPANCY_LABEL
    high = estimate_occupancy(0.20, 0.05)
    assert high["estimate"] == "2+"
    assert "quickly" in high["reason"]
    assert estimate_occupancy(float("nan"), 0.05)["estimate"] is None


def test_profile_change_is_zero_for_the_same_shape_and_detects_a_rewrite():
    base = np.linspace(0.2, 2.0, 16) ** 2
    assert profile_change(base, base) == pytest.approx(0.0, abs=1e-9)
    other = np.linspace(2.0, 0.2, 16)
    assert profile_change(other, base) > 0.2
    with pytest.raises(ValueError):
        profile_change(base, base[:-1])


def test_rssi_bands_are_link_labels_only():
    assert rssi_band(-40) == "strong"
    assert rssi_band(-60) == "fair"
    assert rssi_band(-80) == "weak"
    assert rssi_band(None) == "unknown"
    assert rssi_band(float("nan")) == "unknown"
