# Background: How WiFi Can "See"

> Status: living document. Corrections and better explanations are very welcome. If a detail
> here disagrees with the original paper, the paper wins; please open an issue.

## 1. Channel State Information (CSI)

WiFi (802.11n/ac/ax) uses **OFDM**: each transmission is split across many narrow
**subcarriers**. For every packet, the receiver estimates how the channel changed each subcarrier,
one complex number per (TX antenna, RX antenna, subcarrier):

```
H(f) = |H(f)| · e^{j∠H(f)}
```

- **Amplitude** `|H|`: how much the signal was attenuated.
- **Phase** `∠H`: how much it was delayed/rotated.

A CSI sample is therefore a tensor like `[n_tx, n_rx, n_subcarriers]` of complex values,
collected tens to thousands of times per second.

## 2. Why people change CSI: multipath

Signals reach the receiver along many paths: direct line-of-sight plus reflections off walls,
furniture and **human bodies**. Each path adds its own delay and attenuation. When a person moves
an arm, the reflected paths change, and so does CSI. Static parts of the room form a
fairly stable background; dynamic changes carry information about the body.

Challenges:

- **Raw phase is noisy**: carrier frequency offset (CFO), sampling time offset (STO) and
  packet detection delay add random phase shifts per packet.
- **Environment dependence**: the same pose produces different CSI in a different room
  (the biggest open problem; see the reading list).
- **Low spatial resolution**: 20–80 MHz bandwidth and a few antennas give far less
  resolution than a camera.

## 3. The DensePose-from-WiFi pipeline (Geng, Huang, De la Torre, 2022)

### Hardware and input
Commodity routers with 3 transmitting and 3 receiving antennas, with CSI over 30 subcarriers.
Several consecutive CSI samples are stacked, giving amplitude and phase tensors roughly of shape
`150 × 3 × 3` (5 samples × 30 subcarriers, by 3 × 3 antenna pairs). Synchronized video is
recorded only to create training labels.

### Step 1: Phase sanitization
The paper lists three operations: unwrap along subcarriers, a filter across time (a median
filter is the usual choice), and a linear fit across subcarriers whose subtraction removes the
CFO/STO slope.

`sanitize_phase` does all three, in an order that does not mix packets. The per-packet line
is subtracted *before* the median filter. A median taken while each packet still has its own
offset stitches neighbouring packets together across subcarriers, and the piece that remains
is no longer a straight line. The filter also repeats the edge samples instead of padding with
zeros, which would pull a short recording toward 0. See `docs/REVIEW-2026-11-24.md`.

### Step 2: Modality Translation Network
Separate MLP encoders embed amplitude and phase; features are fused, reshaped into a small 2D map
(e.g. 24×24), and passed through a conv encoder–decoder that outputs an **image-like feature map**
(3 channels, at image resolution). This lets a standard vision backbone process WiFi data.

### Step 3: WiFi-DensePose RCNN
A DensePose-RCNN–style model (ResNet + FPN backbone) predicts:
- person boxes,
- **keypoints** (17 COCO joints),
- **dense UV coordinates**: for each body pixel, which of 24 body parts it belongs to and its
  (u, v) location on that part's surface.

### Step 4: Transfer learning from images
An image-based DensePose model acts as the **teacher**. Its multi-level features supervise the
WiFi student (feature-matching loss) in addition to the usual DensePose losses. This
significantly speeds up training and improves accuracy.

### Evaluation
COCO-style metrics: box **AP**, and DensePose **dpAP·GPS** / **dpAP·GPSm** (geodesic point
similarity). The paper reports strong results when train/test share the same room layouts, and a
large drop on **unseen layouts**, which is a key motivation for follow-up work.

## 4. Open questions worth researching

- Generalization to new rooms, devices, and people.
- Multi-person separation.
- Cheap hardware: can ESP32 CSI (lower quality, single antenna) do anything useful?
- Temporal models (transformers, state-space models) over CSI sequences.
- Self-supervised pretraining on unlabeled CSI.
- **Defenses**: detecting sensing, adding phase noise, or randomizing CSI to protect privacy.

## 5. Further reading
See [`../papers/reading-list.md`](../papers/reading-list.md).
