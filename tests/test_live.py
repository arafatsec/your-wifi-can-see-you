"""Tests for live processing (motion score, calibration, recorder) and the dashboard's demo feed."""
import importlib.util
import json
import time
from pathlib import Path

import numpy as np
import pytest

from src.csi.live import K_USED, LiveProcessor, Recorder
from src.csi.loaders import CSILineParser, lltf_complex

FIELDS = {"mac": "1a:00:00:00:00:00", "rssi": "-40", "channel": "1", "first_word": "0"}


def packet(amp_scale=1.0, rng=None, noise=0.2, ripple=0.0, ripple_phase=0.0):
    """128 raw values (imag, real pairs, ESP32 order).

    amp_scale scales every subcarrier at once (like the ESP32's gain control). ripple adds a
    frequency-selective change across subcarriers (like a person moving the multipath).
    """
    rng = rng or np.random.default_rng(0)
    k = np.arange(-32, 32)
    shape = 1 + ripple * np.sin(k / 3.0 + ripple_phase)
    c = 30 * amp_scale * shape * np.exp(1j * 0.1 * k) + noise * (rng.standard_normal(64) + 1j * rng.standard_normal(64))
    c[(np.abs(k) > 26) | (k == 0)] = 0
    esp = np.concatenate([c[32:], c[:32]])
    v = np.empty(128, dtype=np.int16)
    v[0::2] = np.round(esp.imag)
    v[1::2] = np.round(esp.real)
    return v


def feed(proc, n, t0, scale_fn, rng, ripple_fn=None):
    for i in range(n):
        kw = {} if ripple_fn is None else {"ripple": 0.3, "ripple_phase": ripple_fn(i)}
        proc.add_packet(FIELDS, packet(scale_fn(i), rng, **kw), host_t=t0 + i * 0.01)
    return t0 + n * 0.01


def test_lltf_complex_lengths():
    v = packet()
    assert lltf_complex(v).shape == (64,)
    assert np.allclose(lltf_complex(np.concatenate([v, np.zeros(256, np.int16)])), lltf_complex(v))
    assert lltf_complex(v[:100]) is None


def test_parser_streams_and_remembers_header():
    p = CSILineParser()
    assert p.feed("I (27) boot: hello") is None
    assert p.feed("type,id,mac,rssi,channel,data") is None
    out = p.feed('CSI_DATA,5,1a:00:00:00:00:00,-40,1,"[1,2,3,4]"')
    assert out[0]["channel"] == "1" and list(out[1]) == [1, 2, 3, 4]
    assert p.header_line.startswith("type,")


def test_motion_low_when_still_high_when_moving():
    rng = np.random.default_rng(1)
    still, moving = LiveProcessor(), LiveProcessor()
    t = feed(still, 150, 1000.0, lambda i: 1.0, rng)
    still.tick(now=t)
    t = feed(moving, 150, 1000.0, lambda i: 1.0, rng, ripple_fn=lambda i: i / 6)
    moving.tick(now=t)
    m_still, m_move = still.hist_motion[-1], moving.hist_motion[-1]
    assert m_still < 0.03 < m_move
    moving.set_threshold(0.05)
    assert moving.snapshot()["presence"] is True
    still.set_threshold(0.05)
    assert still.snapshot()["presence"] is False


def test_gain_jumps_alone_do_not_look_like_motion():
    """Real ESP32 packets jump in overall level (AGC); that must not raise the motion score."""
    rng = np.random.default_rng(4)
    agc = LiveProcessor()
    t = feed(agc, 150, 1000.0, lambda i: 0.55 if i % 7 == 0 else 1.0, rng)  # every 7th packet at ~half level
    agc.tick(now=t)
    assert agc.hist_motion[-1] < 0.03


def test_calibration_sets_threshold_above_room_noise():
    rng = np.random.default_rng(2)
    p = LiveProcessor()
    p.start_calibration(seconds=0.0)
    p._calib["end"] = 2000.0  # simulated clock
    t = 1000.0
    for _ in range(30):
        t = feed(p, 10, t, lambda i: 1.0, rng)
        p.tick(now=t)
    p.tick(now=2000.5)
    assert p.calibration["ok"] and p.threshold >= p.calibration["mean"] * 1.5
    assert p._calib is None


def test_snapshot_rows_are_incremental_and_capped():
    rng = np.random.default_rng(3)
    p = LiveProcessor()
    feed(p, 100, 1000.0, lambda i: 1.0, rng)
    s1 = p.snapshot(since_seq=0, max_rows=40)
    assert len(s1["rows"]) == 40 and len(s1["rows"][0]) == len(K_USED)
    feed(p, 5, 2000.0, lambda i: 1.0, rng)
    s2 = p.snapshot(since_seq=s1["seq"])
    assert len(s2["rows"]) == 5
    raw = json.dumps(s2)  # must be JSON serialisable for the browser; NaN/Infinity are not
    assert "NaN" not in raw and "Infinity" not in raw
    assert s2["occupancy"]["validated"] is False
    assert s2["pose"]["placeholder"] is True
    assert s2["pose"]["message"] == "no trained model - demo/animated placeholder"
    assert "not a speed" in s2["spectrum"]["note"]
    assert s2["static"]["note"]
    assert s2["quality"]["rssi_band"] in {"strong", "fair", "weak", "unknown"}


def test_presence_hysteresis_does_not_chatter_on_the_threshold():
    p = LiveProcessor(threshold=0.05)
    assert p._latch_presence(0.06) is True
    assert p._latch_presence(0.048) is True  # still above 85% of the threshold
    assert not any(ev["kind"] == "presence" for ev in p.events)
    assert p._latch_presence(0.03) is False
    assert any("under" in ev["message"] for ev in p.events)


def test_nonfinite_threshold_is_rejected():
    p = LiveProcessor()
    with pytest.raises(ValueError):
        p.set_threshold(float("nan"))
    with pytest.raises(ValueError):
        p.set_threshold(-1)


def test_calibration_stores_an_empty_room_profile_and_a_match_reads_low():
    rng = np.random.default_rng(2)
    p = LiveProcessor()
    p.start_calibration(seconds=10)
    p._calib["end"] = 2000.0
    t = 1000.0
    for _ in range(20):
        t = feed(p, 10, t, lambda i: 1.0, rng)
        p.tick(now=t)
    p.tick(now=2000.5)
    assert p.calibration["ok"]
    assert len(p.baseline_profile) == len(K_USED)
    p._features_at = -1e9
    p.tick(now=t)  # the finishing tick is after the packets; score the shape against them
    snap = p.snapshot()
    assert snap["static"]["has_baseline"] is True
    assert snap["static"]["change"] < 0.05


def test_occupancy_stays_zero_for_a_still_window():
    rng = np.random.default_rng(1)
    p = LiveProcessor()
    t = feed(p, 150, 1000.0, lambda i: 1.0, rng)
    p.tick(now=t)
    assert p.snapshot()["occupancy"]["estimate"] == "0"


def test_bad_packets_counted():
    p = LiveProcessor()
    assert p.add_packet(FIELDS, np.zeros(10, np.int16)) is False
    assert p.packets_bad == 1 and p.packets_total == 0


def test_recorder_needs_consent_and_valid_label(tmp_path):
    r = Recorder(tmp_path)
    with pytest.raises(ValueError, match="consent"):
        r.start("walking", consent=False)
    with pytest.raises(ValueError, match="label"):
        r.start("dancing", consent=True)


def test_recorder_writes_header_lines_and_sidecar(tmp_path):
    r = Recorder(tmp_path)
    path = r.start("empty", consent=True, header_line="type,id,mac,data", room="test room")
    r.write_line("I (1) boot noise")  # ignored
    r.write_line('CSI_DATA,1,1a:00:00:00:00:00,"[1,2]"')
    r.write_line('CSI_DATA,2,1a:00:00:00:00:00,"[3,4]"')
    saved = r.stop()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("type,") and len(lines) == 3
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert saved["packets"] == meta["packets"] == 2 and meta["consent"] is True
    assert r.list()[0]["file"] == path.name


def test_recorder_auto_stops(tmp_path):
    r = Recorder(tmp_path)
    r.start("other", consent=True, seconds=1)
    r.started -= 2  # pretend 2 s passed
    r.check_timeout()
    assert not r.active


def test_dashboard_demo_lines_flow_through_pipeline():
    spec = importlib.util.spec_from_file_location(
        "live_server", Path(__file__).resolve().parents[1] / "tools" / "live_dashboard" / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    lines = server.make_demo_lines(seconds_each=1.0)
    parser, proc = CSILineParser(), LiveProcessor()
    parser.feed(server.ESPCSI_HEADER)
    t = time.time()
    for i, line in enumerate(lines):
        fields, values = parser.feed(line.replace("@TS@", str(i * 10_000)))
        assert len(values) == 128
        proc.add_packet(fields, values, host_t=t + i * 0.01)
    assert proc.packets_total == len(lines) == 200 and proc.packets_bad == 0


def _load_server():
    spec = importlib.util.spec_from_file_location(
        "live_server", Path(__file__).resolve().parents[1] / "tools" / "live_dashboard" / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    return server


def test_demo_walking_and_empty_fall_on_opposite_sides_of_demo_threshold():
    server = _load_server()
    lines = server.make_demo_lines(seconds_each=4.0)
    parser = CSILineParser()
    parser.feed(server.ESPCSI_HEADER)
    scores = {}
    for name, part in (("walking", lines[:400]), ("empty", lines[400:])):
        proc = LiveProcessor()
        t = 1000.0
        vals = []
        for i, line in enumerate(part):
            proc.add_packet(*parser.feed(line.replace("@TS@", "0")), host_t=t + i * 0.01)
            if i % 50 == 49 and i > 100:
                proc.tick(now=t + i * 0.01)
                vals.append(proc.hist_motion[-1])
        scores[name] = float(np.mean(vals))
    assert scores["empty"] < server.DEMO_THRESHOLD < scores["walking"], scores


def test_demo_mode_uses_its_own_settings_file():
    server = _load_server()

    class A:
        demo, port, baud, out, no_reset = True, "COM5", 921600, "data/recordings", False
    demo_app = server.App(A)
    A.demo = False
    real_app = server.App(A)
    assert demo_app.settings_path != real_app.settings_path
    assert demo_app.settings_path.name.endswith("_demo.json")
