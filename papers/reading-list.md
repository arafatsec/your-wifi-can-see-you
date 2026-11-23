# Reading List

A curated, community-maintained list. To add a paper, follow the format below and open a PR
(see [CONTRIBUTING.md](../CONTRIBUTING.md)). Optional: add a summary in
[`summaries/`](summaries/) using [`summaries/TEMPLATE.md`](summaries/TEMPLATE.md).

Format: `- **Title**. Authors/Group (Year). [link] (code if available). One-line takeaway.`

## ⭐ Core paper

- **DensePose From WiFi**. Geng, Huang, De la Torre, CMU (2022).
  [arXiv:2301.00250](https://arxiv.org/abs/2301.00250).
  CSI ➜ modality translation ➜ DensePose-RCNN with image-teacher transfer learning.

## 🦴 WiFi-based 2D / 3D pose estimation

- **AdaPose: Towards Cross-Site Device-Free Human Pose Estimation with Commodity WiFi**. NTU (2023).
  [arXiv:2309.16964](https://arxiv.org/abs/2309.16964). Domain adaptation across sites.
- **Towards Robust and Realistic Human Pose Estimation via WiFi Signals**. PolyU, HKUST, Alibaba, NTU (2025).
  [arXiv:2501.09411](https://arxiv.org/abs/2501.09411). Revisits overlooked issues in WiFi HPE.
- **VST-Pose: Velocity-Integrated Spatiotemporal Attention Network for Human WiFi Pose Estimation** (2025).
  [arXiv:2507.09672](https://arxiv.org/abs/2507.09672). Temporal attention over CSI.
- **Graph-based 3D Human Pose Estimation using WiFi Signals**. EURECOM, RWTH Aachen (2025).
  [arXiv:2511.19105](https://arxiv.org/abs/2511.19105). Graph modeling of skeleton structure.
- **WiFlow: Lightweight WiFi-based Continuous Human Pose Estimation** (2026).
  [arXiv:2602.08661](https://arxiv.org/abs/2602.08661). Spatio-temporal feature decoupling.
- **Seeing Through WiFi: Lightweight Human Pose Estimation with Dynamic Kernel Attention** (2026).
  [arXiv:2607.03196](https://arxiv.org/abs/2607.03196).
- **WiSPER: Multi-Person 3D Pose Estimation With WiFi CSI** (2026).
  [arXiv:2610.07025](https://arxiv.org/abs/2610.07025). Multi-person setting.
- **KOALA: Koopman Operator Learning for WiFi-Based Anticipatory Human Pose** (2026).
  [arXiv:2608.15815](https://arxiv.org/abs/2608.15815). Predicts future poses.

## 🌍 Cross-environment generalization (the big open problem)

- **Breaking Coordinate Overfitting: Geometry-Aware WiFi Sensing for Cross-Layout 3D Pose Estimation** (2026).
  [arXiv:2601.12252](https://arxiv.org/abs/2601.12252).
- **C-MambaPose: Phase-Preserving Complex Mamba for Cross-Environment Wi-Fi HPE** (2026).
  [arXiv:2606.13700](https://arxiv.org/abs/2606.13700).
- **RePos: Relative-to-Absolute Pose Factorization for Cross-Environment WiFi 3D HPE** (2026).
  [arXiv:2607.02986](https://arxiv.org/abs/2607.02986).
- **Physics-Informed WiFi Sensing for Robust 3D HPE in Mobile and Cross-Environment Settings** (2026).
  [arXiv:2608.23995](https://arxiv.org/abs/2608.23995).

## 🧪 Self-supervised & foundation models

- **WiFi-JEPA: Self-supervised Learning for WiFi-CSI 3D Human Pose Estimation** (2026).
  [arXiv:2607.11064](https://arxiv.org/abs/2607.11064).

## 📶 Beyond WiFi (related RF sensing)

- **5G Sensing for Human Pose Estimation with PRS-based CSI** (2026).
  [arXiv:2610.37435](https://arxiv.org/abs/2610.37435).
- **Human Walking Sensing and Pose Estimation in the 6 GHz Band Using Amplitude and Phase CSI** (2026).
  [arXiv:2606.10048](https://arxiv.org/abs/2606.10048).

## 📊 Datasets & benchmarks
See [`../datasets/README.md`](../datasets/README.md).

- **CSI-Bench: A Large-Scale In-the-Wild Dataset for Multi-task WiFi Sensing** (2025).
  [arXiv:2505.21866](https://arxiv.org/abs/2505.21866).

## 🔐 Privacy, attacks & defenses
*Help wanted!* Add papers on detecting WiFi sensing, CSI obfuscation, and legal/ethical analysis.

## 📝 TODO (help wanted)
- [ ] Add classic foundations: Person-in-WiFi (ICCV 2019), WiPose, RF-Pose / RF-Capture (MIT).
- [ ] Add WiFi human mesh work (e.g. Wi-Mesh, Person-in-WiFi 3D, CVPR 2024).
- [ ] Add code links where official implementations exist.
