# 📡 Your WiFi Can See You

**An open, community research project on dense human pose estimation from WiFi signals.**

Ordinary WiFi routers fill every room with radio waves. When a person moves, those waves bounce,
scatter and fade in measurable ways, recorded in the **Channel State Information (CSI)** of each
packet. In 2022, researchers at Carnegie Mellon University showed that a deep network can turn
that CSI into a **dense, per-pixel map of the human body surface (DensePose UV)**, with no camera
and no light, and even through occlusion.

This repo exists to **understand, reproduce, critique and extend** that idea in the open, and to
think hard about what it means for privacy.

> Reference paper: Jiaqi Geng, Dong Huang, Fernando De la Torre.
> *DensePose From WiFi*. arXiv:2301.00250, 2022. https://arxiv.org/abs/2301.00250

---

## 🎯 Goals

1. **Learn**: clear, beginner-friendly explanations of WiFi sensing, CSI and DensePose.
2. **Survey**: a living, curated reading list of WiFi-based pose / mesh estimation work.
3. **Reproduce**: an open-source re-implementation of the DensePose-from-WiFi pipeline.
4. **Extend**: cross-environment generalization, cheap hardware (ESP32), multi-person scenes.
5. **Protect**: study the privacy risks and defenses (detection, jamming, CSI obfuscation).

## ✅ What actually works today

We only list what exists and is tested. No measured result is claimed until it can be reproduced.

| Component | Status |
|---|---|
| `CSIData` standard format (`src/csi/types.py`) | ✅ Implemented, tested |
| Phase sanitization (`src/csi/sanitize.py`) | ✅ Implemented, tested. Linear trend is removed before the median filter |
| Synthetic multipath generator (`src/csi/synthetic.py`) | ✅ For tests only, output labelled `synthetic=True` |
| ESP32 CSI loader (`src/csi/loaders/esp32.py`) | ✅ Verified on real ESP32 boards running esp-csi ([guide](docs/hardware/esp32.md)) |
| ESP32 recording script (`scripts/record_esp32.py`) | 🧪 Board connection verified; first labelled recording session not yet made |
| ESP32 firmware setup (`scripts/flash_esp32_boards.ps1`) | ✅ Configures, builds and flashes both boards; verified on real boards |
| Live dashboard (`tools/live_dashboard/`) | ✅ Local page (127.0.0.1). Demo mode is synthetic and labelled. Real-board path is the same UI |
| Motion score (phase 2.5 baseline) | 🧪 Gain-normalised amplitude variation, empty-room threshold. Accuracy not measured on labelled data |
| Fluctuation spectrum, breathing, person count, static-shape change | 🧪 Estimates in the dashboard, each labelled as such. Not validated |
| Pose model interface (`src/models/`) | 🧪 Interface only. No weights. The figure is an animation until a trained model is plugged in |
| Loaders for Intel 5300 / Nexmon | ⏳ Not started ([help wanted](https://github.com/arafatsec/your-wifi-can-see-you/issues/6)) |
| Real-world accuracy numbers | ❌ None yet |

## 🗂️ Repository layout

| Path | What's inside |
|---|---|
| [`docs/background.md`](docs/background.md) | WiFi CSI, multipath, and how the CMU pipeline works |
| [`docs/hardware/esp32.md`](docs/hardware/esp32.md) | Capture real CSI with two cheap ESP32 boards |
| [`scripts/`](scripts/) | Board flashing and data recording tools |
| [`tools/live_dashboard/`](tools/live_dashboard/) | Live local dashboard for the ESP32 boards |
| [`firmware/esp32/`](firmware/esp32/) | Radio settings applied to Espressif's esp-csi firmware |
| [`papers/reading-list.md`](papers/reading-list.md) | Curated papers, grouped by topic |
| [`datasets/README.md`](datasets/README.md) | Public WiFi sensing datasets and CSI capture tools |
| [`src/`](src/) | Code: CSI preprocessing, models, training (work in progress) |
| [`notebooks/`](notebooks/) | Exploratory Jupyter notebooks |
| [`experiments/`](experiments/) | Experiment logs and results write-ups |
| [`ROADMAP.md`](ROADMAP.md) | What we're building and where help is needed |
| [`ETHICS.md`](ETHICS.md) | Privacy, consent and responsible-use principles |

## 🧠 The idea in one picture

```
 WiFi TX ))) ~~~~ person ~~~~ ((( WiFi RX
                                   │
                    CSI: amplitude + phase (antennas × subcarriers × time)
                                   │
                   Phase sanitization (unwrap, filter, linear fit)
                                   │
          Modality Translation Network (CSI ➜ image-like 2D feature map)
                                   │
              DensePose-RCNN-style head (keypoints + UV body surface)
                                   │
                 Dense human pose, without a camera
```

Training uses a **camera only as a teacher**: an image-based DensePose model labels synchronized
video frames, and the WiFi network learns to match it. At test time, only WiFi is needed.

## 🚀 Getting started

```bash
git clone https://github.com/arafatsec/your-wifi-can-see-you.git
cd your-wifi-can-see-you
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Then read [`docs/background.md`](docs/background.md) and pick something from the
[roadmap](ROADMAP.md) or the [good first issues](https://github.com/arafatsec/your-wifi-can-see-you/labels/good%20first%20issue).

## 🔗 Related projects

A longer, licence-checked pass is in [`docs/research/open-source-landscape.md`](docs/research/open-source-landscape.md).
Short version:

- [ruvnet/RuView](https://github.com/ruvnet/RuView) (the project formerly published as wifi-densepose).
  MIT. Their own README now separates three things: an MM-Fi benchmark pose model, a presence
  encoder, and an on-device pose path they describe as a stub (PCK@20 about 3%, runtime
  confidence 0). An earlier audit found the Python CSI path returning random placeholders.
  We did not copy code or repeat their accuracy numbers. The landscape note has the citations.
- [espressif/esp-csi](https://github.com/espressif/esp-csi) (Apache-2.0) is the firmware these
  boards run. [ESPectre](https://github.com/francescopace/espectre) (GPL-3.0) is the strongest
  maintained ESP32 motion firmware we found; we did not copy it. [SenseFi](https://github.com/xyanchen/WiFi-CSI-Sensing-Benchmark)
  (MIT code) is the model benchmark to use once there is a dataset.

Know a project with real, reproducible results? Please add it.

## 🤝 Contributing

Everyone is welcome: students, researchers, hardware hackers, writers and privacy advocates.
You can help by:

- 📄 adding or summarizing a paper,
- 🧪 reproducing a result or running an experiment,
- 🛠️ writing preprocessing / model / visualization code,
- 📡 contributing CSI capture guides for specific hardware,
- 🔐 researching privacy attacks and defenses.

Please read [CONTRIBUTING.md](CONTRIBUTING.md), the [Code of Conduct](CODE_OF_CONDUCT.md) and
the [Ethics policy](ETHICS.md) before opening a pull request.

## ⚖️ License

- Code: [MIT](LICENSE)
- Documentation and written research notes: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

Papers referenced here belong to their authors; we link to them, we don't redistribute them.

## 📚 Citing

If this repo helps your work, please cite the original paper:

```bibtex
@article{geng2022densepose,
  title   = {DensePose From WiFi},
  author  = {Geng, Jiaqi and Huang, Dong and De la Torre, Fernando},
  journal = {arXiv preprint arXiv:2301.00250},
  year    = {2022}
}
```
