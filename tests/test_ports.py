"""Receiver/sender COM port selection, including auto-detect without hardware."""
import pytest

from src.csi.ports import LinkPorts, SerialPortInfo, listen_for_csi, open_serial_quiet, resolve_link_ports

PORTS = [
    SerialPortInfo("COM5", "Silicon Labs CP210x USB to UART Bridge"),
    SerialPortInfo("COM6", "USB-Enhanced-SERIAL CH9102"),
]


def test_explicit_rx_and_tx():
    got = resolve_link_ports(rx="COM6", tx="COM5", legacy_port=None, ports=PORTS, probe=lambda _d: False)
    assert got == LinkPorts(
        rx="COM6", tx="COM5", how="flags",
        detail="Receiver COM6. Sender COM5.",
    )


def test_legacy_port_flag_is_the_receiver():
    got = resolve_link_ports(rx=None, tx=None, legacy_port="COM5", ports=PORTS, probe=lambda _d: False)
    assert got.rx == "COM5" and got.tx == "COM6" and got.how == "flags"
    assert "not opened" in got.detail


def test_port_and_rx_must_agree():
    with pytest.raises(ValueError, match="differ"):
        resolve_link_ports(rx="COM6", tx=None, legacy_port="COM5", ports=PORTS, probe=lambda _d: False)


def test_rx_and_tx_must_be_different_boards():
    with pytest.raises(ValueError, match="two boards"):
        resolve_link_ports(rx="COM5", tx="COM5", legacy_port=None, ports=PORTS, probe=lambda _d: False)


def test_auto_picks_the_port_that_prints_csi_and_does_not_need_a_probe_when_named():
    called = []

    def probe(device):
        called.append(device)
        return device == "COM5"

    got = resolve_link_ports(rx=None, tx=None, legacy_port=None, ports=PORTS, probe=probe)
    assert got.rx == "COM5" and got.tx == "COM6" and got.how == "auto"
    assert called == ["COM5", "COM6"]
    named = resolve_link_ports(rx="COM5", tx="COM6", legacy_port=None, ports=PORTS, probe=probe)
    assert named.how == "flags"
    assert called == ["COM5", "COM6"]  # naming the receiver does not listen


def test_auto_reports_the_ports_it_saw_when_nothing_prints_csi():
    with pytest.raises(ValueError, match="CP210x") as exc:
        resolve_link_ports(rx=None, tx=None, legacy_port=None, ports=PORTS, probe=lambda _d: False)
    assert "CH9102" in str(exc.value)
    assert "COM5" in str(exc.value) and "COM6" in str(exc.value)


def test_auto_refuses_two_csi_ports():
    with pytest.raises(ValueError, match="More than one"):
        resolve_link_ports(rx=None, tx=None, legacy_port=None, ports=PORTS, probe=lambda _d: True)


def test_a_busy_port_is_skipped_rather_than_aborting_the_scan():
    def probe(device):
        if device == "COM6":
            raise OSError("access denied")
        return device == "COM5"

    got = resolve_link_ports(rx=None, tx=None, legacy_port=None, ports=PORTS, probe=probe)
    assert got.rx == "COM5"


def test_listen_for_csi_stops_on_a_csi_line_and_does_not_touch_reset_pins():
    class Fake:
        def __init__(self):
            self.lines = [b"boot noise\n", b"CSI_DATA,1,aa\n"]
            self.reset_toggles = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def readline(self):
            return self.lines.pop(0) if self.lines else b""

        @property
        def dtr(self):
            return False

        @dtr.setter
        def dtr(self, value):
            self.reset_toggles.append(("dtr", value))

        @property
        def rts(self):
            return False

        @rts.setter
        def rts(self, value):
            self.reset_toggles.append(("rts", value))

    fake = Fake()

    def opener(device, baud, timeout):
        assert device == "COM5" and baud == 921600 and timeout == 0.2
        return fake

    assert listen_for_csi("COM5", 921600, 1.0, opener) is True
    assert fake.reset_toggles == []


def test_quiet_open_holds_reset_lines_low_before_open():
    class Quiet:
        def __init__(self):
            self.dtr = True
            self.rts = True
            self.at_open = None
            self.port = None
            self.baudrate = None
            self.timeout = None

        def open(self):
            self.at_open = (self.dtr, self.rts)

    opened = open_serial_quiet("COM6", 921600, serial_cls=Quiet)
    assert opened.at_open == (False, False)
    assert opened.port == "COM6" and opened.baudrate == 921600
