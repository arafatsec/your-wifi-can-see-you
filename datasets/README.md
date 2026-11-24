# Datasets & CSI Capture Tools

⚠️ **Never commit raw datasets to this repo.** Put them under `data/` (git-ignored) and document
how to download them here instead.

Licences and what we will and will not copy are in
[`docs/research/open-source-landscape.md`](../docs/research/open-source-landscape.md).

## Public datasets

| Dataset | Content | Notes |
|---|---|---|
| DensePose-from-WiFi (CMU) | WiFi CSI + video, 16 layouts | Check the paper/authors for availability; it may not be public. |
| [MM-Fi](https://ntu-aiot-lab.github.io/mm-fi) | Multi-modal (WiFi CSI, mmWave, LiDAR, RGB-D), 2D/3D pose | NeurIPS 2023 Datasets & Benchmarks |
| [CSI-Bench](https://arxiv.org/abs/2505.21866) | Large in-the-wild multi-task WiFi sensing | 2025 |
| Person-in-WiFi 3D | Multi-person 3D pose from WiFi | CVPR 2024 |
| Widar3.0 | Gesture recognition CSI | Useful for pretraining / preprocessing practice |

*Help wanted:* verify links, licenses and download instructions for each, and add more.

## CSI capture tools (hardware)

| Tool | Hardware | Notes |
|---|---|---|
| Linux 802.11n CSI Tool | Intel 5300 NIC | Classic, 30 subcarrier groups, 3 antennas |
| Atheros CSI Tool | Qualcomm Atheros NICs | More subcarriers |
| Nexmon CSI | Broadcom chips (e.g. Raspberry Pi 4) | 802.11ac, up to 80 MHz |
| ESP32 CSI Tool | ESP32 microcontrollers | Very cheap, lower quality, great for hobby experiments |
| PicoScenes | Intel AX200/AX210, QCA9300, SDRs | Modern 802.11ax support |

## Contributing a dataset entry
Include: name, link, license, modalities, CSI shape, sampling rate, # subjects / environments,
label type (keypoints, DensePose UV, mesh), and how it was collected (with consent?).
