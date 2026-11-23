"""Load CSI logs from ESP32 boards into `CSIData`.

Supports the text logs printed over serial by:
- Espressif's official esp-csi examples (e.g. `csi_recv`), and
- the community ESP32-CSI-Tool (Steven M. Hernandez).

Both print one packet per line starting with `CSI_DATA`, with the raw CSI as a bracketed list
of signed 8-bit integers at the end of the line. Each subcarrier is two numbers:
imaginary part first, then real part (per Espressif's documentation).

For 20 MHz HT/legacy packets the ESP32 reports the 64 L-LTF subcarriers in the order
0..31, -32..-1. We reorder them to -32..31 so frequency increases along the subcarrier axis.

If the log has a header row (a line starting with `type,`), column positions are read from it.
Otherwise the ESP32-CSI-Tool default column layout is assumed.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Iterable

import numpy as np

from ..types import CSIData

SUBCARRIER_SPACING_HZ = 312_500.0

# ESP32-CSI-Tool default columns (used when the log has no header row).
DEFAULT_COLUMNS = [
    "type", "role", "mac", "rssi", "rate", "sig_mode", "mcs", "bandwidth", "smoothing",
    "not_sounding", "aggregation", "stbc", "fec_coding", "sgi", "noise_floor", "ampdu_cnt",
    "channel", "secondary_channel", "local_timestamp", "ant", "sig_len", "rx_state",
    "real_time_set", "real_timestamp", "len", "CSI_DATA",
]

_ARRAY_RE = re.compile(r"\[([^\]]*)\]")


def channel_center_hz(channel: int) -> float:
    """Center frequency of a WiFi channel (2.4 GHz channels 1-14, 5 GHz channels 32-177)."""
    if 1 <= channel <= 13:
        return (2407 + 5 * channel) * 1e6
    if channel == 14:
        return 2484e6
    if 32 <= channel <= 177:
        return (5000 + 5 * channel) * 1e6
    raise ValueError(f"unknown WiFi channel {channel}")


def _parse_lines(lines: Iterable[str]):
    columns = DEFAULT_COLUMNS
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("type,"):
            columns = [c.strip() for c in line.split(",")]
            continue
        if not line.startswith("CSI_DATA"):
            continue  # boot messages, logs, partial lines
        m = _ARRAY_RE.search(line)
        if not m:
            continue
        try:
            values = np.array([int(v) for v in m.group(1).replace(",", " ").split()], dtype=np.int16)
        except ValueError:
            continue  # corrupted serial line
        head = line[: m.start()].rstrip(' ,"').split(",")
        fields = {name: head[i].strip() for i, name in enumerate(columns) if i < len(head)}
        yield fields, values


def _reorder_lltf(c: np.ndarray) -> np.ndarray:
    """(T, 64) in ESP32 order 0..31, -32..-1  ->  order -32..31."""
    return np.concatenate([c[:, 32:], c[:, :32]], axis=1)


def load_esp32_csi(
    path: str | Path,
    mac: str | None = None,
    drop_null_subcarriers: bool = True,
) -> CSIData:
    """Read an ESP32 CSI log file.

    Args:
        path: text log captured from the receiver board's serial port.
        mac: keep only packets from this transmitter MAC (case-insensitive). If None, the most
            frequent MAC in the log is used, since receivers often overhear other devices.
        drop_null_subcarriers: remove subcarriers that are zero in every packet (DC and guard).

    Returns:
        CSIData with shape (packets, subcarriers, 1, 1) and source "esp32".
    """
    path = Path(path)
    with open(path, encoding="utf-8", errors="replace") as f:
        parsed = list(_parse_lines(f))
    if not parsed:
        raise ValueError(f"no CSI_DATA lines found in {path}")

    macs = Counter(p[0].get("mac", "").lower() for p in parsed)
    target = mac.lower() if mac else macs.most_common(1)[0][0]
    rows = [p for p in parsed if p[0].get("mac", "").lower() == target]
    if not rows:
        raise ValueError(f"no packets from MAC {mac} in {path}; seen: {dict(macs)}")

    # Keep only the most common CSI length (mixing packet formats would mix subcarrier layouts).
    lengths = Counter(len(v) for _, v in rows)
    n_vals = lengths.most_common(1)[0][0]
    rows = [p for p in rows if len(p[1]) == n_vals]
    if n_vals % 2:
        raise ValueError(f"odd CSI length {n_vals}: expected imaginary/real pairs")

    raw = np.stack([v for _, v in rows]).astype(np.float64)
    csi = raw[:, 1::2] + 1j * raw[:, 0::2]  # pairs are (imag, real)
    reordered = csi.shape[1] == 64
    if reordered:
        csi = _reorder_lltf(csi)
        idx = np.arange(-32, 32)
    else:
        idx = np.arange(csi.shape[1]) - csi.shape[1] // 2

    if drop_null_subcarriers:
        keep = np.any(np.abs(csi) > 0, axis=0)
        csi, idx = csi[:, keep], idx[keep]

    # Timestamps: microseconds from the board, may wrap at 2**32.
    ts = np.array([float(f.get("local_timestamp", "nan") or "nan") for f, _ in rows])
    if np.all(np.isfinite(ts)):
        ts = np.unwrap(ts, period=2**32)
        ts = (ts - ts[0]) / 1e6
        ts = np.maximum.accumulate(ts)  # guard against occasional out-of-order lines
    else:
        ts = np.arange(len(rows), dtype=np.float64)  # no timestamps: use packet index

    channels = Counter(int(f["channel"]) for f, _ in rows if f.get("channel", "").isdigit())
    channel = channels.most_common(1)[0][0] if channels else 6
    freqs = channel_center_hz(channel) + idx * SUBCARRIER_SPACING_HZ

    rssi = np.array([float(f["rssi"]) for f, _ in rows if f.get("rssi", "").lstrip("-").isdigit()])

    return CSIData(
        csi=csi[:, :, None, None],
        timestamps=ts,
        subcarrier_freqs=freqs,
        source="esp32",
        metadata={
            "file": str(path),
            "mac": target,
            "channel": channel,
            "subcarrier_index": idx,
            "lltf_reordered": reordered,
            "rssi_dbm": rssi if len(rssi) == len(rows) else None,
            "packets_total": len(parsed),
            "packets_used": len(rows),
            "other_macs": {k: v for k, v in macs.items() if k != target},
        },
    )
