# Open-source WiFi CSI landscape

Notes for this repo, written 2026-11-24. Versions and licences were checked against the upstream pages that day. "Adopt" means an idea we reimplemented in our own code. We did not copy source from any of these projects.

This repository is MIT for code. GPL code cannot be vendored into it. A missing licence means we do not copy, even if the idea is useful. Dataset licences are not code licences: CC BY-NC data must not be redistributed from this repo.

## What we actually took

All of it is standard signal processing, written here, with tests in `tests/test_sensing.py` and `tests/test_models.py`:

- Empty-room calibration of a motion threshold, plus the mean amplitude shape as a static-multipath baseline. A later mismatch is reported as "the shape changed", not as a named object.
- Gain-normalised amplitude (already in the dashboard before this pass; the ESP32 AGC step is why).
- A fluctuation spectrum of amplitude over time, described as Doppler-*like*. It is not a speed in m/s. The geometry of one bistatic link is unknown.
- A 2nd-order band-pass (0.1–0.5 Hz) on CSI amplitude for a breathing-rate *estimate*, marked unreliable while the room is moving or the window is short.
- A 0 / 1 / 2+ occupancy *guess* from how far the motion score sits above the empty-room threshold, always `validated: false`.
- A pose-model interface (`src/models/pose.py`) that draws 17 COCO-ordered joints. With no weights, the figure is an animation and says so.

No pretrained weights, no benchmark accuracy, and no firmware were imported.

## RuView (ruvnet/RuView), including wifi-densepose

- **What it is.** A large Rust/Python platform (MIT) aimed at ESP32-S3 CSI: presence, breathing, heart rate, person count, and 17-keypoint pose, plus a lot of product surface (edge modules, attestations, three.js scenes). `wifi-densepose` on PyPI is the same line of work; the repository now lives at `github.com/ruvnet/RuView`.
- **Licence.** MIT. Copying with attribution would be allowed. We did not copy. The useful parts for us are either a Rust service we do not run, or accuracy claims we will not repeat as if they were ours.
- **What is real, by their own README (checked 2026-11-24).** They publish a table that splits checkpoints:
  - A CSI encoder and presence head (`ruvnet/wifi-densepose-pretrained`). They report 82.3% held-out *temporal-triplet* accuracy. They retracted an older "100% presence" figure because it was measured on a single-class recording.
  - An MM-Fi pose model (`ruvnet/wifi-densepose-mmfi-pose`) reported at 82.69% torso-PCK@20 on MM-Fi's `random_split` protocol. That number is a benchmark on MM-Fi's multi-antenna capture, not a live single-ESP32 result.
  - The on-device pose cog checked into the repo is described by them as a first cut: PCK@20 = 3.0% on a 217-sample holdout, below their own 35% target, with the runtime path still a centred skeleton that returns `confidence=0`. The weights are not wired in.
  - The archived Python v1 `DensePoseHead` is random initialisation with no checkpoint.
- **The placeholder history is real.** Their ADR-011 and the audit that became PR #62 on `wifi-densepose` list default-path code that returned `np.random` from CSI parsing, a Doppler feature, and pose generation (`csi_extractor.py`, `csi_processor.py`, `pose_service.py`). Later revisions moved mock generation behind an explicit mock mode and made the unimplemented hardware path raise instead of inventing samples. The README's honesty section is much better than the marketing sections above it. Use-case tables still say things like ">95% occupancy" and through-wall pose next to a limitations block that says camera-free pose on their pipeline is about 2.5% PCK@20 with proxy labels, and that a single-antenna 56-subcarrier stream does not carry the spatial detail the multi-antenna papers use.
- **What we did not adopt.** Their weights, their PCK numbers, heart-rate claims, "environment mapping" as object recognition, and the three.js scene. A single classic ESP32 link in this repo cannot support those claims, and we have no labelled set to test even the modest ones.

## Projects worth knowing

| Project | What it actually does | Licence | Maturity | For us |
|---|---|---|---|---|
| [espressif/esp-csi](https://github.com/espressif/esp-csi) | Official examples: `csi_send` / `csi_recv`, CSI on ESP32-class chips. This repo's firmware notes and loader target that text format. | Apache-2.0 | Maintained by Espressif. Issues are active; the hardware guide pins ESP-IDF 5.5.x because newer IDF has broken their examples (their issue #267). | Already our firmware. Do not vendor it. Keep the loader matched to the line format we have seen on a classic ESP32. |
| [ESP32-CSI-Tool](https://github.com/StevenMHernandez/ESP32-CSI-Tool) (Steven M. Hernandez) | Classic ESP32, active AP/STA, CSI printed as text. The tool our loader falls back to when a log has no header. | MIT | Community project, a few years old, still the usual citation for ESP32 CSI. Less active than esp-csi. | Format already supported. No C++ copied. |
| [ESPectre](https://github.com/francescopace/espectre) | One ESP32 as a motion sensor: CSI in, a movement score out, on device. ESPHome, Matter, a C++ SDK. Their own docs say it does **not** identify people, count them, or prove a room is empty. v3 (2026) covers ESP32, S2, S3, C3, C5, C6. | GPL-3.0-only, plus a paid commercial licence for closed firmware | The most serious maintained ESP32 *sensing* firmware we looked at. Algorithm notes are public; the code is copyleft. | **Do not copy.** Ideas we already share, reimplemented: gain-invariant features, an empty-room calibration, and honest limits on what a motion score is. |
| [SenseFi](https://github.com/xyanchen/WiFi-CSI-Sensing-Benchmark) | PyTorch benchmark of MLP/CNN/RNN/Transformer models on UT-HAR, NTU-HAR, and Widar3.0. Paper: Yang et al., Patterns 2023. | Code MIT. The Patterns paper is CC BY-NC-ND. | The standard "which network actually works" reference. Weights are published. Datasets are separate downloads. | The right place to copy a *training loop shape* from later, with attribution, once we have a dataset. Not useful on unlabelled ESP32 CSI. No code copied now. Shallow models beat very deep ones in their cross-environment results; worth remembering before a large pose net. |
| [CSIKit](https://github.com/Gi-z/CSIKit) | Python readers for Intel 5300, Atheros, Nexmon, ESP32, FeitCSI, PicoScenes. | MIT | Usable library, docs still described by the author as in progress. ~300 stars. | Best reference when we write the Intel 5300 and Nexmon loaders (roadmap). Write them against `CSIData` rather than wrapping CSIKit blindly, and attribute if a parser is ported. |
| [nexmon_csi](https://github.com/seemoo-lab/nexmon_csi) | CSI extraction on Broadcom chips (Raspberry Pi 3B+/4/5 and a few phones/routers), up to 80 MHz. Paper: Gringoli et al., WiNTECH 2019. | Firmware patch framework is GPL. The project additionally requires citation of nexmon and the WiNTECH paper for academic use. | The practical way to get wideband CSI from a Pi. Backwards-incompatible changes landed (PR #256). | Future `.pcap` loader only. Do not vendor the firmware. Cite the paper if we publish numbers from it. |
| [FeitCSI](https://github.com/KuskoSoft/FeitCSI) | CSI extraction and injection on Intel AX200/AX210, 802.11ax, up to 160 MHz, including 6 GHz on some NICs. | GPL-3.0 | Younger than nexmon. Small team, active enough to have a site and a GUI. | Do not copy. A possible capture path later, same citation expectation as their README. |
| [Linux 802.11n CSI Tool](https://github.com/dhalperi/linux-80211n-csitool) | The classic Intel 5300 extractor. 30 subcarrier groups, up to 3×3. | Kernel changes stay GPL-2.0. Code the authors wrote is MIT (their FAQ). The modified firmware is Intel's binary licence and cannot be rebuilt. | Frozen. It is still what most older datasets used. Supplementary repo is archived. | The `.dat` loader on the roadmap can follow the MIT userspace reader. Do not ship firmware. |
| [PicoScenes](https://ps.zpj.io/) | Middleware for Intel AX200/AX210, QCA9300, and USRP, including 802.11ax. | Not open source. Free tier with online checks; Pro tier is paid. | Polished, and not something we can vendor. | Mention only as a capture option. No code. |
| [MM-Fi](https://github.com/ybhbingo/MMFi_dataset) | 40 subjects, 27 actions, synchronised WiFi CSI (3×114), RGB-D, LiDAR, mmWave. 2D/3D pose labels. Yang et al., NeurIPS 2023 Datasets. | Dataset **CC BY-NC 4.0**. Confirm the toolbox licence before copying a loader. | The public set that actually has pose labels and a WiFi modality. | The honest target for a later keypoint baseline. The CSI shape is not our ESP32 shape. Do not commit the data. Non-commercial only. |
| [Person-in-WiFi 3D](https://github.com/aiotgroup/Person-in-WiFi-3D-repo) | Multi-person 3D pose from several WiFi devices, transformer, their own 97k-frame set. They report ~92 mm MPJPE for one person, rising with two and three, on *their* capture. | Apache-2.0 | A paper repo. Not a general tool, and not a single-link ESP32 system. | No code copied. The joint interface we draw is 3D so a later model can return real coordinates; front and side views are a schematic, not their network. |
| [WiCount / CSI-BERT2](https://github.com/RS2002/CSI-BERT2) | People counting (0–3) and other tasks from ESP32-S3 CSI, 52 subcarriers, ~100 Hz. WiCount is on Hugging Face as short CSV captures. | **No licence file found** on the GitHub repo at review time. Do not copy. | A paper repo (IEEE TMC 2025) with a dataset that matches our hardware class better than MM-Fi does. | The problem shape (0–3 people, one cheap link) is why our dashboard has a 0/1/2+ guess. The guess is not their model and is not validated. |

## Also on the dataset list, not re-audited as code

Widar3.0 (gesture CSI, often distributed as a body-velocity profile rather than raw CSI) and the Intel 5300 UT-HAR set are SenseFi's training data. CSI-Bench (2025) is a large in-the-wild collection; we have not checked its licence beyond the existing one-line entry in `datasets/README.md`. None of these are in this repository.

## What this hardware can and cannot borrow

A classic ESP32 running esp-csi, one transmitter and one receiver, gives on the order of 50 usable L-LTF subcarriers at about 90 packets/s after the settings in `firmware/esp32/configure_esp_csi.py`. That is enough to try presence, a coarse activity bit, a breathing *candidate* when the person is still, and a static-shape change against an empty-room baseline. It is not enough, on published evidence including RuView's own single-antenna note, to claim dense pose or a reliable person count. Those need either a trained model on a consented labelled set from this hardware, or a different radio (3×3 Intel/Nexmon, or the MM-Fi setup) and a stated split. Until then the dashboard's extra panels stay estimates or placeholders.
