"""Live CSI dashboard: reads the ESP32 receiver over USB serial and serves a local web page.

    python tools/live_dashboard/server.py --port COM5          # real boards
    python tools/live_dashboard/server.py --demo               # simulated data, no hardware

Then open http://127.0.0.1:8765. Only listens on this computer (127.0.0.1).

Endpoints: GET / (page), GET /events (server-sent events, ~10 per second), GET /api/status,
GET /api/recordings, POST /api/calibrate {"seconds"}, POST /api/threshold {"value"},
POST /api/record/start {"label","seconds","consent","room"}, POST /api/record/stop.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from src.csi.live import LABELS, LiveProcessor, Recorder  # noqa: E402
from src.csi.loaders.esp32 import CSILineParser  # noqa: E402

HERE = Path(__file__).resolve().parent
DEMO_THRESHOLD = 0.042  # suits the simulated demo room (walking ~0.05-0.06, empty ~0.025-0.034)
ESPCSI_HEADER = ("type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,aggregation,stbc,"
                 "fec_coding,sgi,noise_floor,ampdu_cnt,channel,secondary_channel,local_timestamp,ant,"
                 "sig_len,rx_format,len,first_word,data")


class App:
    def __init__(self, args):
        self.args = args
        self.proc = LiveProcessor()
        self.rec = Recorder(REPO / args.out)
        self.parser = CSILineParser()
        self.source = {"mode": "demo" if args.demo else "serial", "port": args.port, "baud": args.baud,
                       "connected": False, "error": None, "lines": 0}
        self.stop = threading.Event()
        # separate settings so trying the demo never changes the real boards' calibration
        self.settings_path = REPO / "data" / ("live_dashboard_settings_demo.json" if args.demo
                                              else "live_dashboard_settings.json")
        if args.demo:
            self.proc.threshold = DEMO_THRESHOLD
        self._load_settings()

    # ---- settings --------------------------------------------------------------------------
    def _load_settings(self):
        try:
            s = json.loads(self.settings_path.read_text(encoding="utf-8"))
            self.proc.threshold = float(s.get("threshold", self.proc.threshold))
            self.proc.calibration = s.get("calibration")
        except (OSError, ValueError):
            pass

    def save_settings(self):
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps({"threshold": self.proc.threshold, "calibration": self.proc.calibration},
                                       indent=2), encoding="utf-8")

    # ---- line handling (shared by serial and demo) -----------------------------------------
    def handle_line(self, line: str):
        self.source["lines"] += 1
        self.rec.write_line(line)
        out = self.parser.feed(line)
        if out is not None:
            self.proc.add_packet(*out)

    # ---- sources ---------------------------------------------------------------------------
    def serial_loop(self):
        import serial  # pyserial
        while not self.stop.is_set():
            try:
                with serial.Serial(self.args.port, self.args.baud, timeout=0.5) as ser:
                    ser.reset_input_buffer()
                    if not self.args.no_reset:  # restart board so esp-csi prints its column header
                        ser.dtr = False
                        ser.rts = True
                        time.sleep(0.1)
                        ser.rts = False
                    self.source.update(connected=True, error=None)
                    while not self.stop.is_set():
                        raw = ser.readline()
                        if raw:
                            self.handle_line(raw.decode("utf-8", errors="replace").strip())
            except Exception as e:  # unplugged, port busy, wrong name ...
                self.source.update(connected=False, error=f"{type(e).__name__}: {e}")
                time.sleep(2)

    def demo_loop(self):
        lines = make_demo_lines()
        self.source.update(connected=True, error=None)
        self.handle_line(ESPCSI_HEADER)
        i = 0
        next_t = time.time()
        while not self.stop.is_set():
            self.handle_line(lines[i % len(lines)].replace("@TS@", str(int(time.time() * 1e6) % 2**32)))
            i += 1
            next_t += 0.01
            time.sleep(max(0.0, next_t - time.time()))

    def tick_loop(self):
        while not self.stop.is_set():
            self.proc.tick()
            self.rec.check_timeout()
            time.sleep(1 / self.proc.tick_hz)

    def status(self) -> dict:
        return {"source": self.source, "recording": self.rec.status(), "labels": LABELS,
                "header_seen": self.parser.header_line is not None}


def make_demo_lines(seconds_each: float = 8.0, person_gain: float = 5.0) -> list[str]:
    """Simulated esp-csi lines: a person walks for a while, then the room is empty. Not real data.

    The toy room model's walker is faint once packets are gain-normalised, so for the demo its
    contribution is multiplied by `person_gain` to make the effect easy to see.
    """
    from src.csi.synthetic import generate_room_csi
    kw = dict(duration_s=seconds_each, sample_rate_hz=100, n_tx=1, n_rx=1, n_subcarriers=64, center_hz=2.412e9,
              bandwidth_hz=20e6, snr_db=80, seed=7, hardware_offsets=False)
    empty = generate_room_csi(person=False, **kw).csi[:, :, 0, 0]
    walk = empty + person_gain * (generate_room_csi(person=True, **kw).csi[:, :, 0, 0] - empty)
    csi = np.concatenate([walk, empty])
    rng = np.random.default_rng(0)
    k = np.arange(-32, 32)
    noise_amp = np.sqrt(np.mean(np.abs(csi) ** 2) / 10 ** (30 / 10) / 2)
    csi = csi + noise_amp * (rng.standard_normal(csi.shape) + 1j * rng.standard_normal(csi.shape))
    # per-packet clock offsets, as on real hardware (the dashboard's phase cleanup removes them)
    csi = csi * np.exp(-1j * (rng.uniform(-0.3, 0.3, (len(csi), 1)) * k + rng.uniform(-np.pi, np.pi, (len(csi), 1))))
    csi = csi / np.abs(csi).max() * 40
    k = np.arange(-32, 32)
    csi[:, (np.abs(k) > 26) | (k == 0)] = 0
    esp_order = np.concatenate([csi[:, 32:], csi[:, :32]], axis=1)  # -32..31 -> 0..31, -32..-1
    out = []
    for n, row in enumerate(esp_order):
        vals = np.empty(128, dtype=int)
        vals[0::2] = np.round(row.imag).astype(int)
        vals[1::2] = np.round(row.real).astype(int)
        rssi = -45 + int(2 * np.sin(n / 50))
        cols = ["CSI_DATA", str(n), "1a:00:00:00:00:00", str(rssi), "11", "1", "0", "0", "1", "1", "0", "0",
                "0", "0", "-96", "0", "1", "0", "@TS@", "0", "47", "1", "128", "0"]
        out.append(",".join(cols) + ',"[' + ",".join(map(str, vals)) + ']"')
    return out


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):  # keep the console quiet
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return {}

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                body = (HERE / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                seq = 0
                try:
                    while not app.stop.is_set():
                        snap = app.proc.snapshot(since_seq=seq)
                        seq = snap["seq"]
                        snap.update(app.status())
                        self.wfile.write(b"data: " + json.dumps(snap).encode() + b"\n\n")
                        self.wfile.flush()
                        time.sleep(0.1)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
            elif self.path == "/api/status":
                self._json(app.status())
            elif self.path == "/api/recordings":
                self._json(app.rec.list())
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            b = self._body()
            try:
                if self.path == "/api/calibrate":
                    app.proc.start_calibration(float(b.get("seconds", 10)))
                    threading.Thread(target=_save_after_calibration, args=(app,), daemon=True).start()
                    self._json({"ok": True})
                elif self.path == "/api/threshold":
                    app.proc.set_threshold(float(b["value"]))
                    app.save_settings()
                    self._json({"ok": True, "threshold": app.proc.threshold})
                elif self.path == "/api/record/start":
                    secs = b.get("seconds")
                    path = app.rec.start(label=str(b.get("label", "")), consent=bool(b.get("consent")),
                                         seconds=float(secs) if secs not in (None, "") else None,
                                         room=str(b.get("room", ""))[:200], header_line=app.parser.header_line,
                                         source=app.source["mode"])
                    self._json({"ok": True, "file": path.name})
                elif self.path == "/api/record/stop":
                    self._json({"ok": True, "saved": app.rec.stop()})
                else:
                    self._json({"error": "not found"}, 404)
            except (ValueError, KeyError, TypeError) as e:
                self._json({"ok": False, "error": str(e)}, 400)

    return Handler


def _save_after_calibration(app: App):
    while app.proc._calib is not None and not app.stop.is_set():
        time.sleep(0.2)
    app.save_settings()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="COM5", help="receiver board serial port")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--http-port", type=int, default=8765)
    ap.add_argument("--demo", action="store_true", help="simulated data instead of a board")
    ap.add_argument("--no-reset", action="store_true", help="don't restart the board on connect")
    ap.add_argument("--out", default="data/recordings", help="recordings folder (relative to repo)")
    args = ap.parse_args(argv)

    app = App(args)
    threading.Thread(target=app.demo_loop if args.demo else app.serial_loop, daemon=True).start()
    threading.Thread(target=app.tick_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", args.http_port), make_handler(app))
    srv.daemon_threads = True
    print(f"Live dashboard: http://127.0.0.1:{args.http_port}  ({'DEMO data' if args.demo else 'serial ' + args.port})",
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        app.rec.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
