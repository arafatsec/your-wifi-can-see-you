# Roadmap

Legend: 🟢 good first issue · 🟡 intermediate · 🔴 advanced

## Phase 1: Knowledge base
- [x] Project skeleton, README, background doc
- [ ] 🟢 Summaries for the top 10 papers in the reading list
- [ ] 🟢 Verify and expand the dataset table (links, licenses, CSI shapes)
- [ ] 🟢 Glossary of terms (OFDM, CSI, CFO, STO, DensePose UV, GPS metric…)
- [ ] 🟡 Diagram of the full pipeline (SVG in `docs/`)

## Phase 2: CSI preprocessing toolkit (`src/csi/`)
- [x] Standard `CSIData` format that every loader/generator returns
- [x] Phase sanitization: unwrap, linear-trend removal, then a median filter (the trend is removed first so per-packet offsets are not mixed)
- [x] Labelled synthetic multipath CSI generator for tests (toy model, never for reported results)
- [x] ESP32 CSI log loader returning `CSIData` + recording script + hardware guide
- [x] Verify the ESP32 loader and guide on real boards (classic ESP32 + esp-csi, Nov 2026)
- [ ] 🟡 Loaders for Intel 5300 `.dat` and Nexmon `.pcap` returning `CSIData`
- [x] Visualization: live amplitude waterfall, amplitude and phase profiles (`tools/live_dashboard/`)

## Phase 2.5: Presence & motion detection (first real-world milestone)
Much easier than pose, works even on cheap ESP32 hardware, and proves the capture pipeline end to end.
- [x] Baseline: gain-normalised amplitude variation + calibrated threshold, live in the dashboard
- [x] Doppler-*like* fluctuation spectrum of amplitude (a frequency in Hz, not a speed in m/s)
- [x] Empty-room calibration also stores the static amplitude shape; the dashboard flags a later mismatch as a multipath change, not as a recognised object
- [x] Breathing-rate estimate: band-pass 0.1–0.5 Hz on CSI amplitude, marked unreliable unless the window is long and still
- [x] Person-count guess: 0 / 1 / 2+, always labelled "estimate, not yet validated"
- [x] Dashboard recording controls for `empty` / `sitting` / `standing` / `walking`, with a consent tick
- [ ] 🟢 Measure the baseline's accuracy on labelled recordings (empty vs. walking)
- [ ] 🟡 Record a small, consented, real dataset (empty / standing / walking) and report accuracy
- [ ] 🟡 Simple classifier (e.g. random forest or 1D CNN) with honest train/test split by session

## Phase 3: Reproduction (`src/models/`)
- [x] Model interface: 17 joints in, `trained` flag, placeholder animation when no weights are loaded (`src/models/pose.py`)
- [ ] 🔴 A trained pose model on a real, consented capture (nothing in-tree is trained)
- [ ] 🔴 Modality Translation Network (PyTorch)
- [ ] 🔴 Keypoint-only baseline on MM-Fi (simpler than full DensePose)
- [ ] 🔴 DensePose head via Detectron2 integration
- [ ] 🔴 Teacher–student transfer learning loss
- [ ] 🟡 Evaluation scripts (AP, PCK, MPJPE, dpAP·GPS)

## Phase 4: Extensions
- [ ] 🔴 Cross-environment benchmark: train on N rooms, test on unseen rooms
- [ ] 🔴 Low-cost ESP32 data collection + feasibility study
- [ ] 🔴 Temporal models (transformer / Mamba) over CSI sequences
- [ ] 🔴 Self-supervised pretraining on unlabeled CSI

## Phase 5: Privacy & defense
- [ ] 🟡 Survey of privacy risks and the legal landscape
- [ ] 🔴 Detecting active WiFi sensing in a room
- [ ] 🔴 CSI obfuscation / phase-randomization defenses and their effect on pose accuracy

Want to take an item? Open an issue (or comment on an existing one) so we avoid duplicate work.
