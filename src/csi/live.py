"""Real-time CSI processing for the live dashboard: motion score, presence, recording.

Works on packets from `CSILineParser` (ESP32 boards running esp-csi), one at a time.

Motion score: each packet's amplitudes are first divided by that packet's mean amplitude. The
ESP32's automatic gain control rescales whole packets (on real boards the packet mean varies
by about 18% and jumps in steps), which would otherwise look like motion; a person changes the
*shape* across subcarriers, which normalisation keeps. Then, over the last `window_s` seconds,
take each subcarrier's coefficient of variation (std / mean) and average across subcarriers.
On a real capture this lowered the still-room score from 0.18 to 0.03 and made it about 12x
steadier. This is the simple baseline from roadmap phase 2.5, not a trained model.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np

from .loaders.esp32 import is_first_word_invalid, lltf_complex

# L-LTF subcarrier indices -32..31; keep the 20 MHz data subcarriers, minus DC (0) and
# subcarrier 1, which esp-csi often flags as invalid (first word).
K_ALL = np.arange(-32, 32)
K_USED = np.concatenate([np.arange(-26, 0), np.arange(2, 27)])
MASK = np.isin(K_ALL, K_USED)

LABELS = ["empty", "sitting", "standing", "walking", "other"]


class LiveProcessor:
    def __init__(self, window_s: float = 1.0, history_s: float = 30.0, tick_hz: float = 10.0,
                 buffer_packets: int = 600, threshold: float = 0.06):
        self.window_s = window_s
        self.tick_hz = tick_hz
        self.lock = threading.Lock()
        self.times: deque[float] = deque(maxlen=buffer_packets)
        self.amps: deque[np.ndarray] = deque(maxlen=buffer_packets)       # gain-normalised
        self.raw_amps: deque[np.ndarray] = deque(maxlen=50)               # as received, for the profile
        self.last_csi: np.ndarray | None = None
        self.last_fields: dict = {}
        n_hist = int(history_s * tick_hz)
        self.hist_t: deque[float] = deque(maxlen=n_hist)
        self.hist_motion: deque[float] = deque(maxlen=n_hist)
        self.hist_rate: deque[float] = deque(maxlen=n_hist)
        self.hist_rssi: deque[float] = deque(maxlen=n_hist)
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
            self.last_csi = c
            self.last_fields = fields
            self.packets_total += 1
            self.last_packet_host_t = host_t
            mac = fields.get("mac", "?").lower()
            self.sender_macs[mac] = self.sender_macs.get(mac, 0) + 1
            ch = fields.get("channel", "")
            self.channel = int(ch) if ch.isdigit() else self.channel
            self.raw_len = len(values)
            self.row_seq += 1
            self.rows.append((self.row_seq, amp))
        return True

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
                mean = w.mean(axis=0)
                ok = mean > 1e-6
                if ok.any():
                    motion = float(np.mean(w.std(axis=0)[ok] / mean[ok]))
            rate = sum(1 for t in self.times if t >= now - 1.0)
            rssi = self.last_fields.get("rssi", "")
            try:
                rssi_v = float(rssi)
            except ValueError:
                rssi_v = float("nan")
            self.hist_t.append(now - self.t0)
            self.hist_motion.append(motion)
            self.hist_rate.append(float(rate))
            self.hist_rssi.append(rssi_v)
            if self._calib is not None:
                if not np.isnan(motion):
                    self._calib["values"].append(motion)
                if now >= self._calib["end"]:
                    self._finish_calibration()

    # ---- calibration -----------------------------------------------------------------------
    def start_calibration(self, seconds: float = 10.0) -> None:
        with self.lock:
            self._calib = {"start": time.time(), "end": time.time() + seconds, "seconds": seconds, "values": []}

    def _finish_calibration(self) -> None:
        vals = np.array(self._calib["values"])
        if len(vals) < 10:
            self.calibration = {"ok": False, "reason": "not enough packets during calibration",
                                "at": datetime.now().isoformat(timespec="seconds")}
        else:
            mean, std = float(vals.mean()), float(vals.std())
            self.threshold = max(mean + 4 * std, mean * 1.5, 0.01)
            self.calibration = {"ok": True, "mean": mean, "std": std, "threshold": self.threshold,
                                "samples": int(len(vals)), "at": datetime.now().isoformat(timespec="seconds")}
        self._calib = None

    def set_threshold(self, value: float) -> None:
        with self.lock:
            self.threshold = float(value)

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
                ph = np.unwrap(np.angle(self.last_csi[MASK]))
                fit = np.polyfit(K_USED, ph, 1)  # remove CFO/STO linear trend over subcarrier index
                phase = ph - np.polyval(fit, K_USED)
            motion = self.hist_motion[-1] if self.hist_motion else float("nan")
            age = None if self.last_packet_host_t is None else now - self.last_packet_host_t
            calibrating = None
            if self._calib is not None:
                calibrating = {"remaining": max(0.0, self._calib["end"] - now), "seconds": self._calib["seconds"]}
            return {
                "seq": self.row_seq,
                "rows": [_round(r, 3) for r in new_rows],
                "k": K_USED.tolist(),
                "profile": None if profile is None else _round(profile, 2),
                "phase": None if phase is None else _round(phase, 3),
                "motion": _num(motion, 4),
                "threshold": round(self.threshold, 4),
                "presence": bool(not np.isnan(motion) and motion > self.threshold),
                "hist": {"t": _round(self.hist_t, 1), "motion": [_num(v, 4) for v in self.hist_motion],
                         "rate": list(self.hist_rate), "rssi": [_num(v, 1) for v in self.hist_rssi]},
                "rate": self.hist_rate[-1] if self.hist_rate else 0.0,
                "rssi": _num(self.hist_rssi[-1], 1) if self.hist_rssi else None,
                "packets_total": self.packets_total,
                "packets_bad": self.packets_bad,
                "last_packet_age": None if age is None else round(age, 2),
                "senders": dict(sorted(self.sender_macs.items(), key=lambda kv: -kv[1])[:3]),
                "channel": self.channel,
                "raw_len": self.raw_len,
                "calibrating": calibrating,
                "calibration": self.calibration,
            }


def _round(a, nd):
    return [round(float(x), nd) for x in a]


def _num(v, nd):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), nd)


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
            while (self.out_dir / f"{day}_{label}_{n:02d}.csv").exists():
                n += 1
            self.path = self.out_dir / f"{day}_{label}_{n:02d}.csv"
            self.f = open(self.path, "w", encoding="utf-8")
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
                        "kb": round(csv.stat().st_size / 1024, 1) if csv.exists() else None})
        return out
