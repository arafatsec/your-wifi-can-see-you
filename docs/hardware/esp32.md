# ESP32 CSI Setup Guide

The cheapest way to capture **real** WiFi Channel State Information (CSI): two ESP32 boards,
about USD 15–30 in total. One board transmits packets, the other receives them and prints the
CSI of every packet over USB to your laptop.

> Status: verified on real hardware in November 2026 with two classic ESP32-D0WD-V3 boards
> (one CP2102 and one CH9102 USB chip), Espressif esp-csi `csi_send`/`csi_recv` built with
> ESP-IDF v5.5.6, on Windows 11. Measured: about 70 packets per second, RSSI about -45 dBm with
> the boards side by side, 55 L-LTF subcarriers per packet after loading. Please report results
> from other boards in an issue.

## What you get (and don't)

| | ESP32 | CMU DensePose setup |
|---|---|---|
| Antennas | 1 TX × 1 RX | 3 TX × 3 RX |
| Subcarriers | ~52 usable (20 MHz, L-LTF) | 30 |
| Packet rate | ~100+ per second | ~100 per second |
| Good for | presence, motion, activity, breathing experiments | dense body pose |

Start with presence and motion detection (roadmap phase 2.5). Full pose needs more antennas.

## 1. Shopping list

- 2 × ESP32 development boards. **ESP32-S3-DevKitC-1** is a good choice; a classic ESP32 DevKit
  also works. A spare third board is useful.
- Optional: boards with an external antenna connector (u.FL/IPEX) plus 2.4 GHz antennas, for a
  stronger, steadier signal.
- 2 × USB data cables (not charge-only) that fit the boards.
- A USB power bank or phone charger to power the transmitter board away from the laptop.

## 2. Software

1. Install the USB driver for your board's serial chip if Windows shows it with an error:
   Silicon Labs **CP210x** driver for CP2102 boards (silabs.com), WCH driver for CH340/CH9102 boards
   (Windows 11 often installs CH9102 by itself). The board should appear as a `COMx` port.
2. Install **ESP-IDF** (Espressif's SDK). Use **v5.5.x**: esp-csi's examples have a known build
   failure with newer releases (esp-csi issue #267). On Windows, for example:

```powershell
git clone --depth 1 --branch v5.5.6 --recurse-submodules --shallow-submodules https://github.com/espressif/esp-idf.git C:\esp\esp-idf
$env:IDF_TOOLS_PATH = "C:\Espressif"; C:\esp\esp-idf\install.ps1 esp32
```

3. Get CSI firmware. Either:
   - **Espressif esp-csi** (official): github.com/espressif/esp-csi, examples `csi_send` and
     `csi_recv` under `examples/get-started`.
   - **ESP32-CSI-Tool** (community, classic ESP32): github.com/StevenMHernandez/ESP32-CSI-Tool,
     projects `active_ap` (transmitter) and `active_sta` (receiver).
4. Flash the **transmitter** firmware to board A and the **receiver** firmware to board B
   (`idf.py -p <PORT> flash`). Set the same WiFi channel on both if the firmware asks.
5. Check the receiver's serial baud rate in its config (`idf.py menuconfig`). esp-csi uses 921600,
   which is our recording script's default.

   With esp-csi, build and flash from a PowerShell window where ESP-IDF is loaded:

```powershell
$env:IDF_TOOLS_PATH = "C:\Espressif"; . C:\esp\esp-idf\export.ps1
cd C:\esp\esp-csi\examples\get-started\csi_send; idf.py set-target esp32; idf.py -p COM6 flash
cd ..\csi_recv; idf.py set-target esp32; idf.py -p COM5 flash
```

   Notes on esp-csi's default output (handled by our loader):
   - It uses channel 11 at 40 MHz, so each packet has 384 values: the 64-subcarrier L-LTF block
     (128 values) followed by HT-LTF blocks. The loader keeps the L-LTF block.
   - The first 4 values are junk when the `first_word` column is 1. The loader drops them.
   - The column header is printed once, with the first packet after the board starts. The
     recording script restarts the board when it begins so the header is captured.
   - The receiver only prints CSI from the sender's fixed MAC `1a:00:00:00:00:00`.
6. On the laptop, inside this repo:

```bash
pip install -r requirements.txt   # includes pyserial
python scripts/record_esp32.py --list-ports
```

Plug in board B. Its port shows up as `COMx` on Windows or `/dev/ttyUSB0` / `/dev/ttyACM0` on Linux.

## 3. Placement

- Put the boards **3–5 m apart**, at about waist height, with open space between them.
- Power board A from a power bank; plug board B into the laptop.
- Keep them in the same spots for every session, and note the setup with `--room`.
- Avoid moving fans, curtains and pets between the boards while recording "empty".

## 4. Recording protocol

Record each label several times, in separate sessions (e.g. 10 × 60 s each):

| Label | What happens |
|---|---|
| `empty` | nobody in the room (leave before the countdown ends) |
| `sitting` | one person sitting still between the boards |
| `standing` | one person standing still |
| `walking` | one person walking back and forth across the line between boards |

```bash
python scripts/record_esp32.py --port COM5 --label walking --seconds 60 --room "living room, 4 m" --consent
```

Files go to `data/recordings/` (git-ignored) as `<date>_<label>_<nn>.csv` plus a `.json` sidecar.

**Consent:** only record people who agreed to it. The script refuses to run without `--consent`.
Never record neighbours or anyone who doesn't know. See [ETHICS.md](../../ETHICS.md).

## 5. Load a recording

```python
from src.csi.loaders import load_esp32_csi
from src.csi import sanitize_phase

d = load_esp32_csi("data/recordings/2026-12-01_walking_01.csv")
print(d.csi.shape, f"{d.sample_rate:.0f} packets/s", d.metadata["channel"])
amplitude = d.amplitude[:, :, 0, 0]          # (packets, subcarriers)
phase = sanitize_phase(d.phase)[:, :, 0, 0]
```

The loader:
- keeps `CSI_DATA` lines and ignores boot messages and broken lines,
- reads column positions from the header row if there is one,
- keeps the transmitter MAC seen most often (or the one you pass with `mac=`),
- converts each (imaginary, real) pair into a complex number,
- reorders the 64 L-LTF subcarriers from ESP32 order (0..31, −32..−1) to −32..31,
- drops always-zero guard and DC subcarriers,
- turns the board's microsecond timer into seconds, handling its wrap-around.

## 6. Troubleshooting

| Problem | Try |
|---|---|
| No serial port | different USB cable (data, not charge-only); install the CP210x or CH340 driver |
| 0 packets recorded | wrong baud rate; transmitter not powered; boards on different channels |
| Very low packet rate | move boards closer; check the transmitter's send interval in its config |
| Garbled lines | lower the baud rate in both firmware and `--baud` |
| Board shows error code 28 in Device Manager | install the USB driver for its serial chip (step 1) |
| esp-csi fails to build | use ESP-IDF v5.5.x, not 6.x |
| Several MACs in metadata | the receiver hears other devices; pass `mac=` with the transmitter's MAC |

## 7. Share results

Open an issue or PR with: board model, firmware and version, placement, packet rate, a plot of
amplitude over time for `empty` vs `walking`, and any loader fixes. Don't upload recordings of
people without their permission.
