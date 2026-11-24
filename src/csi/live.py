"""Real-time CSI processing for the live dashboard.

Works on packets from `CSILineParser` (ESP32 boards running esp-csi), one at a time.

Motion score (the phase-2.5 baseline, unchanged so the hardware calibration still means
the same thing): each packet's amplitudes are divided by that packet's mean amplitude,
removing the ESP32's automatic-gain steps. Over the last `window_s` seconds, take each
subcarrier's coefficient of variation (std / mean) and average across subcarriers.
On a real capture this lowered the still-room score from 0.18 to 0.03. Presence is this
score compared with the empty-room threshold. It is not a trained detector.

Beside it, the snapshot carries estimates that are labelled as such: a Doppler-like
fluctuation spectrum, a band-pass breathing rate, a 0/1/2+ occupancy guess, and a
static-multipath change against the calibrated empty-room shape. None of those have
been validated on a labelled recording. The body figure comes from `src/models`; with
no trained model it is an animation.
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np

from ..models.pose import PlaceholderPoseModel
from .loaders.esp32 import is_first_word_invalid, lltf_complex
from .sanitize import sanitize_phase
from .sensing import (
    STATIC_NOTE,
    coefficient_of_variation,
    estimate_occupancy,
    estimate_respiration,
    fluctuation_spectrum,
    profile_change,
    rssi_band,
    subcarrier_std,
)

# L-LTF subcarrier indices -32..31; keep the 20 MHz data subcarriers, minus DC (0) and
# subcarrier 1, which esp-csi often flags as invalid (first word).
K_ALL = np.arange(-32, 32)
K_USED = np.concatenate([np.arange(-26, 0), np.arange(2, 27)])
MASK = np.isin(K_ALL, K_USED)

LABELS = ["empty", "sitting", "standing", "walking", "other"]

# 1 - correlation. Above this, the still-room shape no longer matches the empty baseline.
STATIC_CHANGE_MIN = 0.12


class LiveProcessor:
    def __init__(self, window_s: float = 1.0, history_s: float = 30.0, tick_hz: float = 10.0,
                 buffer_packets: int = 600, threshold: float = 0.06, model=None):
        self.window_s = window_s
        self.tick_hz = tick_hz
        self.lock = threading.Lock()
        self.times: deque[float] = deque(maxlen=buffer_packets)
        self.amps: deque[np.ndarray] = deque(maxlen=buffer_packets)       # gain-normalised
        self.raw_amps: deque[np.ndarray] = deque(maxlen=50)               # as received, for the profile
        # Longer store for breathing (about 40 s at 100 packets/s).
        self.breath_t: deque[float] = deque(maxlen=4000)
        self.breath_amp: deque[np.ndarray] = deque(maxlen=4000)
        self.last_csi: np.ndarray | None = None
        self.last_fields: dict = {}
        n_hist = int(history_s * tick_hz)
        self.hist_t: deque[float] = deque(maxlen=n_hist)
        self.hist_motion: deque[float] = deque(maxlen=n_hist)
        self.hist_rate: deque[float] = deque(maxlen=n_hist)
        self.hist_rssi: deque[float] = deque(maxlen=n_hist)
        self.activity: deque[dict] = deque(maxlen=180)
        self.events: deque[dict] = deque(maxlen=80)
        self._last_activity_t = -1e9
        self.rows: deque[tuple[int, np.ndarray]] = deque(maxlen=buffer_packets)
        self.row_seq = 0
        self.threshold = threshold
        self.packets_total = 0
        self.packets_bad = 0
        self.last_packet_host_t: float | None = None
        self.sender_macs: dict[str, int] = {}
        self.channel: int | None = None
        self.raw_len: int | None = None
        self._calib: dict | None = None
        self.calibration: dict | None = None
        self.baseline_profile: np.ndarray | None = None
        self._static_status: str | None = None
        self._presence: bool | None = None
        self._features_at = -1e9
        self._features: dict = {
            "spectrum": fluctuation_spectrum(np.zeros((0, 1)), 0.0),
            "breathing": estimate_respiration(np.zeros((0, 1)), 0.0),
            "subcarrier_std": None,
            "static_change": None,
            "static_status": "no empty-room baseline — calibrate while the room is empty",
        }
        self.model = model if model is not None else PlaceholderPoseModel()
        self.t0 = time.time()

    # ---- input -----------------------------------------------------------------------------
    def add_packet(self, fields: dict, values: np.ndarray, host_t: float | None = None) -> bool:
        host_t = time.time() if host_t is None else host_t
        c = lltf_complex(values, is_first_word_invalid(fields))
        with self.lock:
            if c is None:
                self.packets_bad += 1
                return False
            raw = np.abs(c[MASK]).astype(np.float32)
            m = float(raw.mean())
            if m <= 1e-6:
                self.packets_bad += 1
                return False
            amp = raw / m  # remove per-packet gain (AGC) steps
            self.times.append(host_t)
            self.amps.append(amp)
            self.raw_amps.append(raw)
            self.breath_t.append(host_t)
            self.breath_amp.append(amp)
            self.last_csi = c
            self.last_fields = fields
            self.packets_total += 1
            self.last_packet_host_t = host_t
            mac = str(fields.get("mac", "?")).lower()
            self.sender_macs[mac] = self.sender_macs.get(mac, 0) + 1
            ch = str(fields.get("channel", ""))
            self.channel = int(ch) if ch.isdigit() else self.channel
            self.raw_len = len(values)
            self.row_seq += 1
            self.rows.append((self.row_seq, amp))
            if self._calib is not None:
                self._calib["amps"].append(amp.copy())
        return True

    def log_event(self, kind: str, message: str) -> None:
        with self.lock:
            self._event(kind, message)

    def _event(self, kind: str, message: str) -> None:
        self.events.append({
            "t": round(time.time() - self.t0, 1),
            "kind": str(kind)[:40],
            "message": str(message)[:200],
        })

    # ---- periodic --------------------------------------------------------------------------
    def _window(self, now: float) -> np.ndarray | None:
        cut = now - self.window_s
        sel = [a for t, a in zip(self.times, self.amps) if t >= cut]
        return np.stack(sel) if len(sel) >= 5 else None

    def tick(self, now: float | None = None) -> None:
        """Update histories; call about `tick_hz` times per second."""
        now = time.time() if now is None else now
        with self.lock:
            w = self._window(now)
            motion = float("nan")
            if w is not None:
                motion = coefficient_of_variation(w)
            rate = sum(1 for t in self.times if t >= now - 1.0)
            rssi = self.last_fields.get("rssi", "")
            try:
                rssi_v = float(rssi)
            except (TypeError, ValueError):
                rssi_v = float("nan")
            self.hist_t.append(now - self.t0)
            self.hist_motion.append(motion)
            self.hist_rate.append(float(rate))
            self.hist_rssi.append(rssi_v)
            if now - self._features_at >= 0.5 or self._features["subcarrier_std"] is None:
                self._update_features(now, w, motion)
                self._features_at = now
            self._latch_presence(motion)
            self._update_activity(now)
            if self._calib is not None:
                if not math.isnan(motion):
                    self._calib["values"].append(motion)
                if now >= self._calib["end"]:
                    self._finish_calibration()

    def _update_features(self, now: float, window: np.ndarray | None, motion: float) -> None:
        spectrum = self._features["spectrum"]
        breathing = self._features["breathing"]
        std = None
        if window is not None:
            std = subcarrier_std(window)
            span = self.window_s
            times = [t for t in self.times if t >= now - span]
            if len(times) >= 2 and times[-1] > times[0]:
                fs = (len(times) - 1) / (times[-1] - times[0])
                spectrum = fluctuation_spectrum(window, fs)
        if len(self.breath_amp) >= 8:
            amps = np.stack(self.breath_amp)
            bt = np.asarray(self.breath_t, dtype=np.float64)
            # Keep the most recent ~30 s so a long session does not dilute the band.
            if bt[-1] - bt[0] > 30:
                keep = bt >= bt[-1] - 30
                amps, bt = amps[keep], bt[keep]
            if len(bt) >= 8 and bt[-1] > bt[0]:
                fs = (len(bt) - 1) / (bt[-1] - bt[0])
                breathing = estimate_respiration(amps, fs)
        change = None
        status = "no empty-room baseline — calibrate while the room is empty"
        if self.baseline_profile is not None and window is not None:
            current = window.mean(axis=0)
            if current.shape == self.baseline_profile.shape:
                change = profile_change(current, self.baseline_profile)
                if not math.isnan(motion) and motion > self.threshold:
                    status = "paused — the room is moving, so this is not a static reading"
                elif change >= STATIC_CHANGE_MIN:
                    status = "static multipath changed since the empty-room baseline"
                else:
                    status = "matches the empty-room baseline"
        if status != self._static_status:
            self._static_status = status
            if status.startswith("static multipath changed"):
                self._event("static", status)
        self._features = {
            "spectrum": spectrum,
            "breathing": breathing,
            "subcarrier_std": std,
            "static_change": change,
            "static_status": status,
        }

    def _update_activity(self, now: float) -> None:
        if now - self._last_activity_t < 1.0 and self.activity:
            return
        self._last_activity_t = now
        age = None if self.last_packet_host_t is None else now - self.last_packet_host_t
        if age is None or age > 2:
            state = "no-signal"
        elif self._presence is None:
            state = "uncertain"
        elif self._presence:
            state = "motion"
        else:
            state = "still"
        self.activity.append({"t": round(now - self.t0, 1), "state": state})

    def _latch_presence(self, motion: float):
        """Presence with a little hysteresis so a score on the threshold does not chatter.

        Rising through the threshold turns presence on. It stays on until the score falls
        below 85% of the threshold. The first sample does not emit an event.
        """
        if _missing(motion):
            return self._presence
        if self._presence:
            present = motion > self.threshold * 0.85
        else:
            present = motion > self.threshold
        if self._presence is not None and present != self._presence:
            self._event("presence", "motion above threshold" if present else "motion back under threshold")
        self._presence = present
        return present

    # ---- calibration -----------------------------------------------------------------------
    def start_calibration(self, seconds: float = 10.0) -> None:
        with self.lock:
            self._calib = {
                "start": time.time(), "end": time.time() + seconds, "seconds": seconds,
                "values": [], "amps": [],
            }
            self._event("calibration", f"empty-room calibration started ({seconds:.0f} s)")

    def _finish_calibration(self) -> None:
        vals = np.array(self._calib["values"])
        amps = self._calib["amps"]
        if len(vals) < 10:
            self.calibration = {"ok": False, "reason": "not enough packets during calibration",
                                "at": datetime.now().isoformat(timespec="seconds")}
            self._event("calibration", "calibration failed: not enough packets")
        else:
            mean, std = float(vals.mean()), float(vals.std())
            self.threshold = max(mean + 4 * std, mean * 1.5, 0.01)
            baseline = np.mean(np.stack(amps), axis=0) if amps else None
            self.baseline_profile = None if baseline is None else np.asarray(baseline, dtype=np.float64)
            self.calibration = {
                "ok": True, "mean": mean, "std": std, "threshold": self.threshold,
                "samples": int(len(vals)), "at": datetime.now().isoformat(timespec="seconds"),
                "baseline_profile": None if baseline is None else [round(float(x), 4) for x in baseline],
            }
            self._event("calibration", f"threshold set to {self.threshold:.4f} from the empty room")
        self._calib = None

    def set_threshold(self, value: float) -> None:
        value = float(value)
        if not math.isfinite(value) or value < 0 or value > 10:
            raise ValueError("threshold must be a finite number between 0 and 10")
        with self.lock:
            self.threshold = value

    # ---- output ----------------------------------------------------------------------------
    def snapshot(self, since_seq: int = 0, max_rows: int = 40) -> dict:
        now = time.time()
        with self.lock:
            rows = [(s, a) for s, a in self.rows if s > since_seq]
            if len(rows) > max_rows:  # decimate by averaging consecutive rows
                groups = np.array_split(np.arange(len(rows)), max_rows)
                new_rows = [np.mean([rows[i][1] for i in g], axis=0) for g in groups]
            else:
                new_rows = [a for _, a in rows]
            recent = list(self.raw_amps)[-10:]
            profile = np.mean(recent, axis=0) if recent else None
            phase = None
            if self.last_csi is not None:
                raw_phase = np.angle(self.last_csi[MASK]).astype(np.float64)
                phase = sanitize_phase(raw_phase[None, :], kernel=1, indices=K_USED)[0]
            motion = self.hist_motion[-1] if self.hist_motion else float("nan")
            age = None if self.last_packet_host_t is None else now - self.last_packet_host_t
            calibrating = None
            if self._calib is not None:
                calibrating = {"remaining": max(0.0, self._calib["end"] - now), "seconds": self._calib["seconds"]}
            features = self._features
            std = features["subcarrier_std"]
            current_shape = None
            if self.amps:
                current_shape = np.mean(np.stack(list(self.amps)[-min(50, len(self.amps)):]), axis=0)
            try:
                pose = self.model.infer(
                    self.last_csi if self.last_csi is not None else np.zeros((0, 64), dtype=np.complex128),
                    float(self.hist_rate[-1]) if self.hist_rate else 0.0,
                    float(motion) if not _missing(motion) else float("nan"),
                    now,
                ).to_dict()
            except (TypeError, ValueError, AttributeError) as exc:
                pose = PlaceholderPoseModel().infer(np.zeros((0, 1)), 0.0, float("nan"), now).to_dict()
                pose["message"] = "no trained model - demo/animated placeholder"
                pose["placeholder"] = True
                pose["trained"] = False
                self._event("model", f"pose model output rejected: {exc}")
            if not getattr(self.model, "trained", False):
                pose["placeholder"] = True
                pose["trained"] = False
                pose["message"] = "no trained model - demo/animated placeholder"
            rssi_v = self.hist_rssi[-1] if self.hist_rssi else float("nan")
            bad_total = self.packets_bad + self.packets_total
            return {
                "seq": self.row_seq,
                "rows": [_round(r, 3) for r in new_rows],
                "k": K_USED.tolist(),
                "profile": None if profile is None else _round(profile, 2),
                "phase": None if phase is None else _round(phase, 3),
                "subcarrier_std": None if std is None else _round(std, 4),
                "motion": _num(motion, 4),
                "threshold": round(self.threshold, 4),
                "presence": bool(self._latch_presence(motion)),
                "hist": {"t": _round(self.hist_t, 1), "motion": [_num(v, 4) for v in self.hist_motion],
                         "rate": [_num(v, 2) for v in self.hist_rate],
                         "rssi": [_num(v, 1) for v in self.hist_rssi]},
                "rate": _num(self.hist_rate[-1], 2) if self.hist_rate else 0.0,
                "rssi": _num(rssi_v, 1),
                "quality": {
                    "rssi_dbm": _num(rssi_v, 1),
                    "rssi_band": rssi_band(None if _missing(rssi_v) else float(rssi_v)),
                    "packet_rate_hz": _num(self.hist_rate[-1], 2) if self.hist_rate else 0.0,
                    "bad_packets": self.packets_bad,
                    "bad_ratio": round(self.packets_bad / bad_total, 4) if bad_total else 0.0,
                    "note": "RSSI and packet rate describe the radio link, not pose accuracy.",
                },
                "packets_total": self.packets_total,
                "packets_bad": self.packets_bad,
                "last_packet_age": None if age is None else round(age, 2),
                "senders": dict(sorted(self.sender_macs.items(), key=lambda kv: -kv[1])[:3]),
                "channel": self.channel,
                "raw_len": self.raw_len,
                "calibrating": calibrating,
                "calibration": _jsonable_calibration(self.calibration),
                "occupancy": estimate_occupancy(motion, self.threshold),
                "breathing": features["breathing"],
                "spectrum": features["spectrum"],
                "activity": list(self.activity),
                "events": list(self.events),
                "static": {
                    "has_baseline": self.baseline_profile is not None,
                    "change": _num(features["static_change"], 4),
                    "status": features["static_status"],
                    "note": STATIC_NOTE,
                    "baseline": None if self.baseline_profile is None else _round(self.baseline_profile, 3),
                    "current": None if current_shape is None else _round(current_shape, 3),
                },
                "pose": pose,
            }


def _missing(v) -> bool:
    try:
        return not math.isfinite(float(v))
    except (TypeError, ValueError):
        return True


def _round(a, nd):
    return [round(float(x), nd) for x in a]


def _num(v, nd):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return round(x, nd)


def _jsonable_calibration(cal: dict | None) -> dict | None:
    if not cal:
        return cal
    out = dict(cal)
    for key in ("mean", "std", "threshold"):
        if key in out:
            out[key] = _num(out[key], 6)
    return out


class Recorder:
    """Writes raw CSI lines (header first) to data/recordings, same format as record_esp32.py."""

    def __init__(self, out_dir: str | Path = "data/recordings"):
        self.out_dir = Path(out_dir)
        self.lock = threading.Lock()
        self.f = None
        self.path: Path | None = None
        self.meta: dict = {}
        self.packets = 0
        self.started = 0.0
        self.seconds: float | None = None

    @property
    def active(self) -> bool:
        return self.f is not None

    def start(self, label: str, consent: bool, seconds: float | None = None, room: str = "",
              header_line: str | None = None, source: str = "") -> Path:
        if not consent:
            raise ValueError("consent required: confirm everyone in the room agreed to be recorded")
        if label not in LABELS:
            raise ValueError(f"label must be one of {LABELS}")
        if seconds is not None and not (1 <= seconds <= 3600):
            raise ValueError("seconds must be between 1 and 3600")
        with self.lock:
            if self.f is not None:
                raise ValueError("a recording is already running")
            self.out_dir.mkdir(parents=True, exist_ok=True)
            day = datetime.now().strftime("%Y-%m-%d")
            n = 1
            while True:
                path = self.out_dir / f"{day}_{label}_{n:02d}.csv"
                try:
                    self.f = open(path, "x", encoding="utf-8")
                except FileExistsError:
                    n += 1
                    continue
                self.path = path
                break
            if header_line:
                self.f.write(header_line + "\n")
            self.packets = 0
            self.started = time.time()
            self.seconds = seconds
            self.meta = {"label": label, "started": datetime.now().isoformat(timespec="seconds"),
                         "seconds_requested": seconds, "room": room, "consent": True,
                         "source": source, "recorded_with": "tools/live_dashboard"}
            return self.path

    def write_line(self, line: str) -> None:
        if self.f is None:
            return
        with self.lock:
            if self.f is None:
                return
            if line.startswith("type,") or line.startswith("CSI_DATA"):
                self.f.write(line + "\n")
                self.packets += line.startswith("CSI_DATA")
        self.check_timeout()

    def check_timeout(self) -> None:
        if self.f is not None and self.seconds is not None and time.time() - self.started >= self.seconds:
            self.stop()

    def stop(self) -> dict | None:
        with self.lock:
            if self.f is None:
                return None
            self.f.close()
            self.f = None
            elapsed = time.time() - self.started
            self.meta.update({"packets": self.packets, "seconds_recorded": round(elapsed, 1),
                              "packets_per_second": round(self.packets / elapsed, 1) if elapsed else 0})
            self.path.with_suffix(".json").write_text(json.dumps(self.meta, indent=2), encoding="utf-8")
            return {"file": self.path.name, **self.meta}

    def status(self) -> dict:
        if self.f is None:
            return {"active": False}
        el = time.time() - self.started
        return {"active": True, "file": self.path.name, "label": self.meta.get("label"),
                "packets": self.packets, "elapsed": round(el, 1), "seconds": self.seconds}

    def list(self, limit: int = 30) -> list[dict]:
        if not self.out_dir.exists():
            return []
        out = []
        for side in sorted(self.out_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            try:
                m = json.loads(side.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            csv = side.with_suffix(".csv")
            out.append({"file": csv.name, "label": m.get("label"), "started": m.get("started"),
                        "packets": m.get("packets"), "seconds": m.get("seconds_recorded"),
                        "rate": m.get("packets_per_second"),
                        "source": m.get("source"),
                        "kb": round(csv.stat().st_size / 1024, 1) if csv.exists() else None})
        return out
