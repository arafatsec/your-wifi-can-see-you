"""Apply this project's radio settings to Espressif's esp-csi get-started examples.

Edits csi_send and csi_recv in a local esp-csi checkout so both boards use the same channel and
bandwidth, and so the receiver captures only what our loader uses. Safe to run more than once.

    python firmware/esp32/configure_esp_csi.py --esp-csi C:\\esp\\esp-csi --channel 1

Settings (classic ESP32 targets):
- channel: pick the quietest 2.4 GHz channel near you (1, 6 or 11). Default 1.
- bandwidth 20 MHz: our loader uses the 20 MHz L-LTF block only, and 40 MHz overlaps more
  neighbouring networks.
- receiver captures L-LTF only (htltf_en/stbc_htltf2_en/ltf_merge_en off): 128 values per packet
  instead of 384, so the 921600-baud serial link can carry all 100 packets per second.
- channel_filter_en off: raw subcarriers, no smoothing between neighbours (better for research).
- flash size 4 MB in sdkconfig.defaults (the boards tested have 4 MB; removes a boot warning).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def sub(text: str, pattern: str, repl: str, what: str, changes: list[str]) -> str:
    new, n = re.subn(pattern, repl, text, flags=re.MULTILINE)
    if n == 0:
        raise SystemExit(f"could not find {what!r}; esp-csi may have changed. Pattern: {pattern}")
    if new != text:
        changes.append(what)
    return new


def configure(esp_csi: Path, channel: int, bandwidth: int, raw: bool) -> list[str]:
    bw = "WIFI_BW_HT20" if bandwidth == 20 else "WIFI_BW_HT40"
    phy = "WIFI_PHY_MODE_HT20" if bandwidth == 20 else "WIFI_PHY_MODE_HT40"
    changes: list[str] = []
    for name in ("csi_send", "csi_recv"):
        src = esp_csi / "examples" / "get-started" / name / "main" / "app_main.c"
        t = src.read_text(encoding="utf-8")
        t = sub(t, r"^(#define CONFIG_LESS_INTERFERENCE_CHANNEL\s+)\d+", rf"\g<1>{channel}", f"{name}: channel {channel}", changes)
        t = sub(t, r"^(#define CONFIG_WIFI_BANDWIDTH\s+)WIFI_BW_HT\d+", rf"\g<1>{bw}", f"{name}: bandwidth {bandwidth} MHz", changes)
        t = sub(t, r"^(#define CONFIG_ESP_NOW_PHYMODE\s+)WIFI_PHY_MODE_HT\d+", rf"\g<1>{phy}", f"{name}: ESP-NOW phy {phy}", changes)
        if name == "csi_recv":
            # Classic ESP32 branch of the csi_config initialiser (the one with .lltf_en).
            for field, value in (("htltf_en", "false"), ("stbc_htltf2_en", "false"), ("ltf_merge_en", "false"),
                                 ("channel_filter_en", "false" if raw else "true")):
                t = sub(t, rf"^(\s*\.{field}\s*=\s*)(true|false)", rf"\g<1>{value}", f"{name}: {field}={value}", changes)
        src.write_text(t, encoding="utf-8", newline="\n")

        defaults = src.parent.parent / "sdkconfig.defaults"
        d = defaults.read_text(encoding="utf-8") if defaults.exists() else ""
        if "CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y" not in d:
            d = re.sub(r"^CONFIG_ESPTOOLPY_FLASHSIZE.*\n?", "", d, flags=re.MULTILINE)
            d = d.rstrip("\n") + "\nCONFIG_ESPTOOLPY_FLASHSIZE_4MB=y\nCONFIG_ESPTOOLPY_FLASHSIZE=\"4MB\"\n"
            defaults.write_text(d, encoding="utf-8", newline="\n")
            changes.append(f"{name}: flash size 4MB")
    return changes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--esp-csi", type=Path, default=Path(r"C:\esp\esp-csi"))
    ap.add_argument("--channel", type=int, default=1, choices=range(1, 14), metavar="1-13")
    ap.add_argument("--bandwidth", type=int, default=20, choices=(20, 40))
    ap.add_argument("--smoothing", action="store_true", help="keep esp-csi's channel filter (smoothing) on")
    args = ap.parse_args(argv)
    if not (args.esp_csi / "examples" / "get-started" / "csi_recv").is_dir():
        print(f"esp-csi not found at {args.esp_csi}", file=sys.stderr)
        return 2
    changes = configure(args.esp_csi, args.channel, args.bandwidth, raw=not args.smoothing)
    print("\n".join(f"changed: {c}" for c in changes) if changes else "already configured, nothing changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
