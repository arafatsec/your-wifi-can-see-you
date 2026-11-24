"""Record CSI from an ESP32 receiver board over USB serial.

Example (Windows, receiver on COM5 and sender on COM6):
    python scripts/record_esp32.py --rx COM5 --tx COM6 --label walking --seconds 60 --consent

Omit --rx to use whichever port is printing CSI_DATA. --port is the old name for --rx.

Example (Linux/macOS):
    python scripts/record_esp32.py --rx /dev/ttyUSB0 --label empty --seconds 60 --consent

Writes data/recordings/<date>_<label>_<n>.csv (data/ is git-ignored) plus a small .json sidecar
with the session details. Only lines starting with CSI_DATA (and the header row) are kept.

Only record people who have agreed to it. See ETHICS.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

LABELS = ["empty", "sitting", "standing", "walking", "other"]


def list_ports() -> None:
    from serial.tools import list_ports as lp
    ports = list(lp.comports())
    if not ports:
        print("No serial ports found. Is the board plugged in, and is its USB driver installed?")
    for p in ports:
        print(f"{p.device}\t{p.description}")


def recording_rate(kept: int, elapsed_s: float) -> float:
    """Packets per second over the time the serial port was actually open.

    Using the requested duration under-counts a session stopped early with Ctrl+C.
    """
    if elapsed_s <= 0:
        return 0.0
    return kept / elapsed_s


def next_path(out_dir: Path, label: str) -> Path:
    day = datetime.now().strftime("%Y-%m-%d")
    n = 1
    while (out_dir / f"{day}_{label}_{n:02d}.csv").exists():
        n += 1
    return out_dir / f"{day}_{label}_{n:02d}.csv"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rx", help="receiver COM port (csi_recv). Omit to auto-detect the port printing CSI_DATA")
    ap.add_argument("--tx", help="sender COM port (csi_send). Stored in the sidecar; the port is not opened")
    ap.add_argument("--port", help="same as --rx (older name), e.g. COM5 or /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=921600, help="must match the firmware (default 921600)")
    ap.add_argument("--label", choices=LABELS, help="what is happening in the room")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--room", default="", help="free text, e.g. 'bedroom, boards 4 m apart'")
    ap.add_argument("--out", default="data/recordings")
    ap.add_argument("--consent", action="store_true", help="confirm everyone recorded has agreed")
    ap.add_argument("--list-ports", action="store_true", help="show serial ports and exit")
    ap.add_argument("--no-reset", action="store_true",
                    help="don't restart the board first (esp-csi prints its column header only after a restart)")
    args = ap.parse_args(argv)

    try:
        import serial  # pyserial
    except ImportError:
        print("pyserial is missing: pip install pyserial", file=sys.stderr)
        return 2

    if args.list_ports:
        list_ports()
        return 0
    if not args.label:
        ap.error("--label is required (use --list-ports to see COM ports)")
    if not args.consent:
        ap.error("add --consent to confirm everyone in the room has agreed to be recorded (see ETHICS.md)")
    if args.seconds <= 0:
        ap.error("--seconds must be positive")

    repo = Path(__file__).resolve().parents[1]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from src.csi.ports import list_serial_ports, listen_for_csi, open_serial_quiet, resolve_link_ports
    try:
        chosen = resolve_link_ports(
            rx=args.rx, tx=args.tx, legacy_port=args.port, ports=list_serial_ports(),
            probe=lambda device: listen_for_csi(device, args.baud, 1.0, open_serial_quiet),
        )
    except ValueError as exc:
        ap.error(str(exc))
    print(chosen.detail)
    args.port = chosen.rx

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = next_path(out_dir, args.label)

    kept = 0
    started = datetime.now().isoformat(timespec="seconds")
    t_begin = time.monotonic()
    with serial.Serial(args.port, args.baud, timeout=1) as ser, open(path, "x", encoding="utf-8") as f:
        ser.reset_input_buffer()
        if not args.no_reset:
            # Pulse EN through the board's auto-reset circuit. esp-csi's csi_recv prints its
            # column header with the first packet after boot, and the loader needs that header.
            # (Don't flush the buffer after this, or the header can be thrown away.)
            ser.dtr = False
            ser.rts = True
            time.sleep(0.1)
            ser.rts = False
        t_end = time.monotonic() + args.seconds
        print(f"Recording '{args.label}' for {args.seconds:.0f} s to {path} ... (Ctrl+C to stop early)")
        try:
            while time.monotonic() < t_end:
                line = ser.readline().decode("utf-8", errors="replace").strip()
                if line.startswith("type,") or line.startswith("CSI_DATA"):
                    f.write(line + "\n")
                    if line.startswith("CSI_DATA"):
                        kept += 1
                        if kept % 500 == 0:
                            print(f"  {kept} packets")
        except KeyboardInterrupt:
            print("Stopped early.")

    elapsed = time.monotonic() - t_begin
    rate = recording_rate(kept, elapsed)
    meta = {"label": args.label, "started": started, "seconds_requested": args.seconds,
            "seconds_recorded": round(elapsed, 1), "packets": kept,
            "packets_per_second": round(rate, 1), "port": args.port, "rx_port": chosen.rx,
            "tx_port": chosen.tx, "ports_from": chosen.how, "baud": args.baud,
            "room": args.room, "consent": True}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Done: {kept} packets (~{rate:.0f} per second) -> {path}")
    if kept == 0:
        print("No CSI lines received. Check the baud rate, that the receiver firmware prints CSI_DATA, "
              "and that the transmitter board is powered and on the same channel.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
