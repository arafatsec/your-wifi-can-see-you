"""Which COM port is the ESP32 receiver, and which is the sender.

The dashboard and the recording script read the receiver (the board running
esp-csi ``csi_recv``, the one that prints ``CSI_DATA``). The sender is remembered
for the session notes.

Auto-detect listens on each port. pyserial turns DTR and RTS on when a port
opens, and those lines reset an ESP32, so the listen opens with both held low.
After the receiver is chosen, only that port is opened again for the capture.

``--port`` is the old name for ``--rx`` and still works.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SerialPortInfo:
    device: str
    description: str = ""


@dataclass(frozen=True)
class LinkPorts:
    rx: str
    tx: str | None
    how: str  # "flags" when --rx/--port was given, "auto" when we listened
    detail: str


def list_serial_ports() -> list[SerialPortInfo]:
    from serial.tools import list_ports
    return [SerialPortInfo(p.device, p.description or "") for p in list_ports.comports()]


def open_serial_quiet(device: str, baud: int, timeout: float = 0.2, serial_cls=None):
    """Open ``device`` with DTR and RTS low, so the ESP32 auto-reset line stays released."""
    if serial_cls is None:
        import serial
        serial_cls = serial.Serial
    ser = serial_cls()
    ser.port = device
    ser.baudrate = baud
    ser.timeout = timeout
    ser.dtr = False
    ser.rts = False
    ser.open()
    return ser


def listen_for_csi(device: str, baud: int, listen_s: float, open_serial) -> bool:
    """True if ``device`` prints a CSI_DATA line within ``listen_s`` seconds.

    Does not touch DTR or RTS. ``open_serial`` is ``serial.Serial`` in production
    and a fake in tests.
    """
    deadline = time.monotonic() + listen_s
    with open_serial(device, baud, timeout=0.2) as ser:
        while time.monotonic() < deadline:
            raw = ser.readline()
            if raw.lstrip().startswith(b"CSI_DATA"):
                return True
    return False


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _format_ports(ports: list[SerialPortInfo]) -> str:
    if not ports:
        return "  (none)"
    return "\n".join(f"  {p.device}\t{p.description}".rstrip() for p in ports)


def resolve_link_ports(
    *,
    rx: str | None = None,
    tx: str | None = None,
    legacy_port: str | None = None,
    ports: list[SerialPortInfo],
    probe,
) -> LinkPorts:
    """Pick the receiver and, when there is one obvious other port, the sender.

    ``probe(device) -> bool`` is true when that port is printing CSI_DATA.
    It is called only when the receiver was not named. A probe that raises
    (port busy, unplugged mid-check) counts as "not the receiver".
    """
    rx = _clean(rx)
    tx = _clean(tx)
    legacy = _clean(legacy_port)
    if rx and legacy and rx != legacy:
        raise ValueError(
            f"--port {legacy} and --rx {rx} both name the receiver and they differ. Pass one of them."
        )
    if legacy and not rx:
        rx = legacy
    if rx and tx and rx == tx:
        raise ValueError(f"receiver and sender are both {rx}. They are two boards.")

    if rx:
        inferred = ""
        if tx is None:
            others = [p.device for p in ports if p.device != rx]
            if len(others) == 1:
                tx = others[0]
                inferred = f" Sender {tx} is the other serial port; it is not opened."
        return LinkPorts(
            rx=rx, tx=tx, how="flags",
            detail=f"Receiver {rx}." + (f" Sender {tx}." if tx and not inferred else "") + inferred,
        )

    errors: list[str] = []

    def safe(device: str) -> bool:
        try:
            return bool(probe(device))
        except Exception as exc:
            errors.append(f"  {device}: {type(exc).__name__}: {exc}")
            return False

    receivers = [p.device for p in ports if safe(p.device)]
    listing = _format_ports(ports)
    extra = ("\nCould not open:\n" + "\n".join(errors)) if errors else ""
    if len(receivers) == 1:
        chosen = receivers[0]
        others = [p.device for p in ports if p.device != chosen]
        sender = others[0] if len(others) == 1 else None
        if tx and tx != sender and tx != chosen:
            sender = tx
        sender_bit = (
            f" Sender {sender} is the other serial port. It is not opened again for the capture."
            if sender else " No single other port to call the sender."
        )
        return LinkPorts(
            rx=chosen, tx=sender, how="auto",
            detail=(
                f"Auto-detect: {chosen} is the receiver (it prints CSI_DATA)."
                + sender_bit
                + " Pass --rx and --tx to override."
            ),
        )
    if len(receivers) > 1:
        raise ValueError(
            "More than one port is printing CSI_DATA (" + ", ".join(receivers) + "). "
            "Pass --rx for the csi_recv board and --tx for the csi_send board.\n"
            f"Ports seen:\n{listing}{extra}"
        )
    raise ValueError(
        "No serial port is printing CSI_DATA, so the receiver could not be chosen. "
        "Check that csi_recv is running and the cable is a data cable, or pass --rx and --tx.\n"
        f"Ports seen:\n{listing}{extra}"
    )
