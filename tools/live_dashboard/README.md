# Live dashboard

A local web page that shows what the ESP32 receiver sees, in real time, and records labelled
sessions. Runs on your own computer; the server only listens on `127.0.0.1`.

```powershell
python tools/live_dashboard/server.py --port COM5     # real receiver board
python tools/live_dashboard/server.py --demo          # simulated data, no hardware needed
```

Open http://127.0.0.1:8765.

## What it shows

| Panel | Meaning |
|---|---|
| Room | "Motion detected" / "Room still", from the motion score and threshold |
| Motion score · last 30 s | the score over time, with the threshold line; shaded where it is above |
| Live waterfall | gain-normalised amplitude of subcarriers −26…26 over the last few seconds |
| Amplitude profile | current amplitude across subcarriers (average of the last 10 packets) |
| Phase after cleanup | last packet's phase with the linear clock-offset trend removed |
| Packets per second / RSSI | link health: the sender transmits 100 per second |
| Record a labelled session | saves raw lines to `data/recordings/` (needs the consent tick) |

Status pills show whether the receiver is connected, whether the sender is being heard, the
channel, packet rate, RSSI and packet count.

## Motion score (baseline, not a trained model)

1. Each packet's amplitudes are divided by that packet's mean amplitude. The ESP32's automatic
   gain control rescales whole packets, which would otherwise look like motion.
2. Over the last second, each subcarrier's coefficient of variation (std ÷ mean) is computed.
3. The score is the average across subcarriers.

Measured on real boards side by side in a still room: about 0.026 (0.18 before step 1).
Click **Calibrate empty room** with nobody between the boards: the threshold becomes the room's
mean noise + 4 standard deviations (at least 1.5 × the mean). Fans, pets and curtains raise the
score too.

Calibration and threshold are saved in `data/live_dashboard_settings.json`
(demo mode uses `data/live_dashboard_settings_demo.json`, so trying the demo never changes the
real calibration).

## API

`GET /events` (server-sent events, about 10 per second), `GET /api/status`,
`GET /api/recordings`, `POST /api/calibrate {"seconds"}`, `POST /api/threshold {"value"}`,
`POST /api/record/start {"label","seconds","consent","room"}`, `POST /api/record/stop`.

The processing lives in [`src/csi/live.py`](../../src/csi/live.py) and is covered by
`tests/test_live.py`.
