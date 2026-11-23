# Roadmap

Legend: 🟢 good first issue · 🟡 intermediate · 🔴 advanced

## Phase 1: Knowledge base
- [x] Project skeleton, README, background doc
- [ ] 🟢 Summaries for the top 10 papers in the reading list
- [ ] 🟢 Verify and expand the dataset table (links, licenses, CSI shapes)
- [ ] 🟢 Glossary of terms (OFDM, CSI, CFO, STO, DensePose UV, GPS metric…)
- [ ] 🟡 Diagram of the full pipeline (SVG in `docs/`)

## Phase 2: CSI preprocessing toolkit (`src/csi/`)
- [ ] 🟡 Loaders for common CSI formats (Intel 5300 `.dat`, Nexmon `.pcap`, ESP32 CSV)
- [ ] 🟡 Phase sanitization: unwrap, median filter, linear fit removal
- [ ] 🟢 Visualization: amplitude/phase heatmaps over time
- [ ] 🟢 Unit tests with small synthetic CSI samples

## Phase 3: Reproduction (`src/models/`)
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
