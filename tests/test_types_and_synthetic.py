import numpy as np
import pytest

from src.csi import CSIData, generate_room_csi, sanitize_phase


def _small(**kw):
    t, s = 4, 30
    defaults = dict(
        csi=np.ones((t, s, 3, 3), dtype=complex),
        timestamps=np.arange(t) / 100.0,
        subcarrier_freqs=np.linspace(2.427e9, 2.447e9, s),
        source="intel5300",
    )
    defaults.update(kw)
    return CSIData(**defaults)


def test_csidata_valid_and_properties():
    d = _small()
    assert d.amplitude.shape == (4, 30, 3, 3)
    assert d.phase.shape == (4, 30, 3, 3)
    assert d.n_packets == 4
    assert d.sample_rate == pytest.approx(100.0)


@pytest.mark.parametrize("bad", [
    dict(csi=np.ones((4, 30, 3, 3))),                 # not complex
    dict(csi=np.ones((4, 30, 3), dtype=complex)),     # wrong ndim
    dict(timestamps=np.arange(5)),                    # wrong length
    dict(timestamps=np.array([0, 2, 1, 3.0])),        # decreasing
    dict(subcarrier_freqs=np.arange(10)),             # wrong length
    dict(synthetic=True),                             # synthetic but source not "synthetic"
])
def test_csidata_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        _small(**bad)


def test_source_synthetic_must_be_flagged():
    with pytest.raises(ValueError, match="synthetic"):
        _small(source="synthetic", synthetic=False)


def test_synthetic_is_labelled_and_shaped():
    d = generate_room_csi(duration_s=1.0, sample_rate_hz=50, seed=1)
    assert d.synthetic and d.source == "synthetic"
    assert d.csi.shape == (50, 30, 3, 3)
    assert d.metadata["person_xy"].shape == (50, 2)
    assert "Synthetic" in d.metadata["warning"]


def test_synthetic_is_reproducible():
    a = generate_room_csi(duration_s=0.5, seed=7)
    b = generate_room_csi(duration_s=0.5, seed=7)
    assert np.array_equal(a.csi, b.csi)


def test_moving_person_changes_amplitude_more_than_empty_room():
    """Basis for presence detection: motion causes temporal amplitude variation."""
    kw = dict(duration_s=3.0, sample_rate_hz=100, seed=3, snr_db=30)
    empty = generate_room_csi(person=False, **kw)
    walking = generate_room_csi(person=True, **kw)
    var = lambda d: np.mean(np.var(d.amplitude, axis=0))  # noqa: E731
    assert var(walking) > 5 * var(empty)


def test_sanitize_removes_per_packet_linear_offsets():
    """With hardware offsets on, raw phase jumps packet-to-packet; sanitized phase should be stable."""
    kw = dict(duration_s=0.5, sample_rate_hz=100, seed=5, person=False, snr_db=40)
    noisy = generate_room_csi(hardware_offsets=True, **kw)
    clean = sanitize_phase(noisy.phase, kernel=1)
    raw_jitter = np.mean(np.abs(np.diff(np.unwrap(noisy.phase, axis=1), axis=0)))
    clean_jitter = np.mean(np.abs(np.diff(clean, axis=0)))
    assert clean_jitter < 0.2 * raw_jitter
