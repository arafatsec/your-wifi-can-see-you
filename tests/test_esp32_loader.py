"""Tests for the ESP32 CSI loader using synthetic logs written in the ESP32 text format."""
import numpy as np
import pytest

from src.csi import sanitize_phase
from src.csi.loaders import channel_center_hz, load_esp32_csi

TX = "aa:bb:cc:dd:ee:01"
OTHER = "11:22:33:44:55:66"


def _true_channel(n_packets, seed=0):
    """Known complex CSI in natural order -32..31, with guard/DC subcarriers zeroed like real ESP32 L-LTF."""
    rng = np.random.default_rng(seed)
    k = np.arange(-32, 32)
    base = 40 * np.exp(1j * 0.15 * k)
    h = base[None, :] * (1 + 0.1 * rng.standard_normal((n_packets, 1)))
    null = (k == 0) | (k < -26) | (k > 26)
    h[:, null] = 0
    return np.round(h.real).astype(int), np.round(h.imag).astype(int), null


def _line(cols, re_, im_):
    # ESP32 order: 0..31 then -32..-1; each pair is (imag, real)
    order = list(range(32, 64)) + list(range(0, 32))
    vals = []
    for i in order:
        vals += [int(im_[i]), int(re_[i])]
    return ",".join(cols) + ',"[' + " ".join(map(str, vals)) + ']"'


def _tool_cols(mac, ts, channel=6, rssi=-45, length=128):
    # ESP32-CSI-Tool default layout (no header row)
    c = ["CSI_DATA", "STA", mac, str(rssi), "11", "1", "7", "0", "1", "1", "1", "0", "0", "0",
         "-92", "0", str(channel), "0", str(ts), "0", "100", "0", "0", "0.0", str(length)]
    return c


def write_log(path, n=50, header=False, wrap=False, extra_noise=True):
    re_, im_, null = _true_channel(n)
    lines = ["I (312) wifi: boot message that must be ignored", "# synthetic test log"]
    if header:
        lines.append("type,role,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,aggregation,stbc,"
                     "fec_coding,sgi,noise_floor,ampdu_cnt,channel,secondary_channel,local_timestamp,ant,sig_len,"
                     "rx_state,real_time_set,real_timestamp,len,CSI_DATA")
    start = 2**32 - 200_000 if wrap else 1_000_000
    for p in range(n):
        ts = (start + p * 10_000) % 2**32  # 100 packets per second
        lines.append(_line(_tool_cols(TX, ts), re_[p], im_[p]))
        if extra_noise and p % 10 == 0:
            lines.append(_line(_tool_cols(OTHER, ts + 5), re_[p], im_[p]))  # overheard device
            lines.append("CSI_DATA,STA," + TX + ",-40,[1 2 3")  # truncated serial line
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return re_, im_, null


@pytest.mark.parametrize("header", [False, True])
def test_loads_values_order_and_shape(tmp_path, header):
    f = tmp_path / "log.csv"
    re_, im_, null = write_log(f, header=header)
    d = load_esp32_csi(f)
    assert d.source == "esp32" and not d.synthetic
    assert d.csi.shape == (50, int((~null).sum()), 1, 1)
    expected = (re_ + 1j * im_)[:, ~null]
    assert np.allclose(d.csi[:, :, 0, 0], expected)
    assert list(d.metadata["subcarrier_index"]) == list(np.arange(-32, 32)[~null])


def test_picks_most_common_mac_and_skips_bad_lines(tmp_path):
    f = tmp_path / "log.csv"
    write_log(f)
    d = load_esp32_csi(f)
    assert d.metadata["mac"] == TX
    assert d.metadata["packets_used"] == 50
    assert d.metadata["other_macs"] == {OTHER: 5}
    other = load_esp32_csi(f, mac=OTHER.upper())
    assert other.n_packets == 5


def test_timestamps_seconds_and_wraparound(tmp_path):
    f = tmp_path / "log.csv"
    write_log(f, wrap=True)
    d = load_esp32_csi(f)
    assert d.timestamps[0] == 0
    assert np.allclose(np.diff(d.timestamps), 0.01)
    assert d.sample_rate == pytest.approx(100.0)


def test_frequencies_follow_channel(tmp_path):
    f = tmp_path / "log.csv"
    write_log(f)
    d = load_esp32_csi(f)
    center = channel_center_hz(6)
    assert center == 2437e6
    assert np.all(np.diff(d.subcarrier_freqs) > 0)
    assert d.subcarrier_freqs.min() >= center - 32 * 312_500


def test_works_with_sanitize_phase(tmp_path):
    f = tmp_path / "log.csv"
    write_log(f)
    d = load_esp32_csi(f)
    clean = sanitize_phase(d.phase)
    assert clean.shape == d.phase.shape and np.all(np.isfinite(clean))


def test_empty_file_raises(tmp_path):
    f = tmp_path / "empty.csv"
    f.write_text("boot\nno csi here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no CSI_DATA"):
        load_esp32_csi(f)
