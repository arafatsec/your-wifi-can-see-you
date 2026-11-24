# Live dashboard

A local web page for the ESP32 receiver: the motion baseline, a few labelled estimates, and
recording. The server listens on `127.0.0.1` only.

```powershell
python tools/live_dashboard/server.py --port COM5     # real receiver board
python tools/live_dashboard/server.py --demo          # simulated packets, labelled as such
```

Open http://127.0.0.1:8765.

Demo mode does not touch `data/live_dashboard_settings.json`. It uses
`data/live_dashboard_settings_demo.json`.

## What is real, what is an estimate, what is a placeholder

| Panel | What it is |
|---|---|
| Room, motion chart, threshold | The phase-2.5 baseline: gain-normalised amplitude variation against an empty-room threshold. Not a trained detector. Accuracy on labelled data is not measured. |
| Link, packet rate, RSSI | The radio link. Not a sensing accuracy. |
| Subcarrier heatmap, amplitude, phase, per-subcarrier variation | The current CSI, after the same gain normalisation the motion score uses. Phase has the linear clock trend removed. |
| Fluctuation spectrum | Doppler-*like* spectrum of amplitude. A frequency in Hz, not a speed in m/s. |
| People | `0` / `1` / `2+`. Always "estimate, not yet validated". One fast person can read as `2+`. |
| Breathing | Band-pass (0.1–0.5 Hz) peak on CSI amplitude. Not a medical measurement. Unreliable while the window contains faster motion, or before ~20 s. |
| Static multipath | Empty-room amplitude *shape* versus now. A mismatch means the static multipath changed. It does not name objects. |
| Activity timeline | Still / motion / no signal, from the same threshold. Sitting and standing are not separated. |
| Body figure | An animation. The banner says `no trained model - demo/animated placeholder` until you pass a class with `trained = True`. |
| Record | Writes raw lines to `data/recordings/` (git-ignored) after the consent tick. Demo recordings are marked `source: demo`. |

```powershell
python tools/live_dashboard/server.py --port COM5 --pose-model package.module:Class
```

The class is constructed with no arguments and must provide `infer(csi, sample_rate_hz, motion, now)`
returning a `BodyPose` of 17 finite `(x, y, z)` joints. See `src/models/pose.py`. Loading a class
does not mark it trained; the class says so itself.

## Motion score

1. Each packet's amplitudes are divided by that packet's mean, so an AGC step is not motion.
2. Over the last second, each subcarrier's coefficient of variation (std ÷ mean) is averaged.
3. Presence turns on above the threshold and off below 85% of it, so a score sitting on the line does not flicker.

Measured on real boards side by side in a still room: about 0.026 (0.18 before step 1).
**Calibrate empty room** with nobody between the boards. The threshold becomes the room's mean
noise + 4 standard deviations (at least 1.5 × the mean), and the mean amplitude shape is stored
as the static baseline.

## API

`GET /events` (server-sent events, about 10 per second), `GET /api/status`,
`GET /api/recordings`, `POST /api/calibrate {"seconds"}` (1–120),
`POST /api/threshold {"value"}` (finite, 0–10),
`POST /api/record/start {"label","seconds","consent","room"}`, `POST /api/record/stop`.

A browser `Origin` that is not this machine is rejected. Bodies larger than 16 KiB are rejected.

Processing lives in [`src/csi/live.py`](../../src/csi/live.py) and [`src/csi/sensing.py`](../../src/csi/sensing.py).
Tests: `tests/test_live.py`, `tests/test_sensing.py`, `tests/test_server.py`, `tests/test_models.py`.
