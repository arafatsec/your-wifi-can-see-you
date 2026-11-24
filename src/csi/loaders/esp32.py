"""Load CSI logs from ESP32 boards into `CSIData`.

Supports the text logs printed over serial by:
- Espressif's official esp-csi examples (e.g. `csi_recv`), and
- the community ESP32-CSI-Tool (Steven M. Hernandez).

Both print one packet per line starting with `CSI_DATA`, with the raw CSI as a bracketed list
of signed 8-bit integers at the end of the line. Each subcarrier is two numbers:
imaginary part first, then real part (per Espressif's documentation).

The ESP32 reports the 64 L-LTF subcarriers in the order 0..31, -32..-1. We reorder them to
-32..31 so frequency increases along the subcarrier axis. For HT packets the L-LTF block is
followed by HT-LTF blocks (the esp-csi examples' default 40 MHz mode gives 384 values per
packet); by default only the leading L-LTF block is kept.

Verified on real hardware: two classic ESP32-D0WD-V3 boards running esp-csi csi_send/csi_recv
(ESP-IDF v5.5.6, channel 11, HT40), November 2026.

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

# esp-csi csi_recv column header (ESP-IDF 5.5.x). The bracketed CSI is the last column
# and is not part of the comma-separated head, so a headerless line has 24 fields.
ESPCSI_COLUMNS = [
    "type", "id", "mac", "rssi", "rate", "sig_mode", "mcs", "bandwidth", "smoothing",
    "not_sounding", "aggregation", "stbc", "fec_coding", "sgi", "noise_floor", "ampdu_cnt",
    "channel", "secondary_channel", "local_timestamp", "ant", "sig_len", "rx_format",
    "len", "first_word", "data",
]

# Signed 8-bit CSI stored in int16. Anything outside int16 is a corrupt serial token;
# NumPy 1.x would wrap it and NumPy 2 raises OverflowError.
_CSI_INT_MIN = -32768
_CSI_INT_MAX = 32767
_MAX_CSI_VALUES = 8192


def channel_center_hz(channel: int) -> float:
    """Center frequency of a WiFi channel (2.4 GHz channels 1-14, 5 GHz channels 32-177)."""
    if 1 <= channel <= 13:
        return (2407 + 5 * channel) * 1e6
    if channel == 14:
        return 2484e6
    if 32 <= channel <= 177:
        return (5000 + 5 * channel) * 1e6
    raise ValueError(f"unknown WiFi channel {channel}")


class CSILineParser:
    """Stateful parser for ESP32 CSI text lines, for files or a live serial stream.

    Remembers the most recent header row (`type,...`) so later `CSI_DATA` lines map to the right
    columns. `feed(line)` returns `(fields, values)` for a CSI line and None for anything else.
    """

    def __init__(self) -> None:
        self.columns: list[str] = DEFAULT_COLUMNS
        self.header_line: str | None = None

    def feed(self, raw: str):
        line = raw.strip()
        if not line or line.startswith("#"):
            return None
        if line.startswith("type,"):
            self.columns = [c.strip() for c in line.split(",")]
            self.header_line = line
            return None
        if not line.startswith("CSI_DATA"):
            return None  # boot messages, logs, partial lines
        m = _ARRAY_RE.search(line)
        if not m:
            return None
        values = _parse_csi_ints(m.group(1))
        if values is None:
            return None  # corrupted serial line, or a value that would wrap in int16
        head = line[: m.start()].rstrip(' ,"').split(",")
        # No header yet: esp-csi (24 fields, with first_word) and ESP32-CSI-Tool (25 fields)
        # share the prefix but not the tail. Guessing with the tool layout drops first_word
        # and keeps the junk subcarriers esp-csi marks invalid.
        if self.header_line is None and len(head) == len(ESPCSI_COLUMNS) - 1:
            columns = ESPCSI_COLUMNS
        else:
            columns = self.columns
        fields = {name: head[i].strip() for i, name in enumerate(columns) if i < len(head)}
        return fields, values


def lltf_complex(values: np.ndarray, first_word_invalid: bool = False) -> np.ndarray | None:
    """One packet's raw values -> 64 complex L-LTF subcarriers in order -32..31.

    Accepts 128-value records and longer HT records whose length is a multiple of 128 (the L-LTF
    block comes first). Returns None for any other length. Junk first-word values are zeroed.
    """
    n = len(values)
    if n < 128 or n % 128:
        return None
    v = values[:128].astype(np.float64)
    if first_word_invalid:
        v[:4] = 0
    c = v[1::2] + 1j * v[0::2]  # (imag, real) pairs
    return np.concatenate([c[32:], c[:32]])


def is_first_word_invalid(fields: dict) -> bool:
    return fields.get("first_word", fields.get("first_word_invalid", "0")).strip() == "1"


def _parse_csi_ints(text: str) -> np.ndarray | None:
    parts = text.replace(",", " ").split()
    if not parts or len(parts) > _MAX_CSI_VALUES:
        return None
    try:
        nums = [int(part, 10) for part in parts]
    except ValueError:
        return None
    if any(n < _CSI_INT_MIN or n > _CSI_INT_MAX for n in nums):
        return None
    return np.asarray(nums, dtype=np.int16)


def _float_or_nan(text: object) -> float:
    try:
        return float(text)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("nan")


def _parse_lines(lines: Iterable[str]):
    parser = CSILineParser()
    for raw in lines:
        out = parser.feed(raw)
        if out is not None:
            yield out


def _reorder_lltf(c: np.ndarray) -> np.ndarray:
    """(T, 64) in ESP32 order 0..31, -32..-1  ->  order -32..31."""
    return np.concatenate([c[:, 32:], c[:, :32]], axis=1)


def load_esp32_csi(
    path: str | Path,
    mac: str | None = None,
    drop_null_subcarriers: bool = True,
    lltf_only: bool = True,
) -> CSIData:
    """Read an ESP32 CSI log file.

    Args:
        path: text log captured from the receiver board's serial port.
        mac: keep only packets from this transmitter MAC (case-insensitive). If None, the most
            frequent MAC in the log is used, since receivers often overhear other devices.
        drop_null_subcarriers: remove subcarriers that are zero in every packet (DC and guard).
        lltf_only: for records longer than 128 values (HT20/HT40 packets with HT-LTF blocks
            appended), keep only the leading 64-subcarrier L-LTF block. This matches the
            esp-csi examples' default 40 MHz output (384 values per packet).

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

    # When the firmware's "first word invalid" flag is set, the first 4 bytes (subcarriers 0 and 1
    # in ESP32 order) hold junk, not channel estimates. Zero them so they are treated as null.
    first_word_invalid = np.array([is_first_word_invalid(f) for f, _ in rows])
    raw[first_word_invalid, :4] = 0

    # HT20/HT40 packets append HT-LTF (and STBC) blocks after the L-LTF, e.g. 256, 384 or 640
    # values. The first 128 values are always the 64 L-LTF subcarriers of the primary 20 MHz
    # channel, the one field present in every packet type, so that is what we keep.
    lltf_only = lltf_only and n_vals > 128 and n_vals % 128 == 0
    if lltf_only:
        raw = raw[:, :128]

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
    # One corrupt token used to abort the whole file. Fall back to the packet index instead.
    ts = np.array([_float_or_nan(f.get("local_timestamp", "")) for f, _ in rows])
    if np.all(np.isfinite(ts)):
        ts = np.unwrap(ts, period=2**32)
        ts = (ts - ts[0]) / 1e6
        ts = np.maximum.accumulate(ts)  # guard against occasional out-of-order lines
        timestamps_from = "local_timestamp"
    else:
        ts = np.arange(len(rows), dtype=np.float64)
        timestamps_from = "packet_index"

    channels = Counter(int(f["channel"]) for f, _ in rows if f.get("channel", "").isdigit())
    channel = channels.most_common(1)[0][0] if channels else 6
    freqs = channel_center_hz(channel) + idx * SUBCARRIER_SPACING_HZ

    # Keep one RSSI per kept packet. A single bad field used to drop the whole column.
    rssi = np.array([_float_or_nan(f.get("rssi", "")) for f, _ in rows], dtype=np.float64)

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
            "raw_values_per_packet": n_vals,
            "lltf_only": lltf_only,
            "first_word_invalid_packets": int(first_word_invalid.sum()),
            "rssi_dbm": rssi,
            "timestamps_from": timestamps_from,
            "packets_total": len(parsed),
            "packets_used": len(rows),
            "other_macs": {k: v for k, v in macs.items() if k != target},
        },
    )
