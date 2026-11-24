"""Pluggable body-figure model.

`PlaceholderPoseModel` is what runs when nothing has been trained. It plays a generic
idle or walk cycle. The limb positions are not estimated from CSI. A future model sets
`trained = True` and returns 17 keypoints; the dashboard then draws those instead and
drops the placeholder banner.

There is no checkpoint in this repository. Loading a class does not make it trained —
the class has to say so itself.
"""
from __future__ import annotations

import importlib
import math
from dataclasses import dataclass

import numpy as np

# COCO 17, so a later model trained on that convention can be dropped in.
JOINTS: tuple[str, ...] = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)

PLACEHOLDER_MESSAGE = "no trained model - demo/animated placeholder"

# Standing figure, metres. y is up, x is to the figure's right, z is toward the viewer.
_STANDING = np.array(
    [
        [0.00, 1.70, 0.02],
        [-0.03, 1.74, 0.04],
        [0.03, 1.74, 0.04],
        [-0.08, 1.72, 0.00],
        [0.08, 1.72, 0.00],
        [-0.20, 1.46, 0.00],
        [0.20, 1.46, 0.00],
        [-0.24, 1.16, 0.02],
        [0.24, 1.16, 0.02],
        [-0.22, 0.90, 0.04],
        [0.22, 0.90, 0.04],
        [-0.12, 0.96, 0.00],
        [0.12, 0.96, 0.00],
        [-0.13, 0.52, 0.02],
        [0.13, 0.52, 0.02],
        [-0.12, 0.05, 0.04],
        [0.12, 0.05, 0.04],
    ],
    dtype=np.float64,
)


@dataclass
class BodyPose:
    """Seventeen 3D joints in metres, plus whether a trained model produced them."""

    keypoints: np.ndarray
    placeholder: bool
    message: str
    model: str

    def to_dict(self) -> dict:
        kp = np.asarray(self.keypoints, dtype=np.float64)
        if kp.shape != (len(JOINTS), 3) or not np.all(np.isfinite(kp)):
            raise ValueError("pose keypoints must be 17 finite (x, y, z) joints")
        return {
            "joints": list(JOINTS),
            "keypoints": [[round(float(v), 4) for v in row] for row in kp],
            "placeholder": bool(self.placeholder),
            "message": self.message,
            "model": self.model,
            "trained": not self.placeholder,
        }


class PlaceholderPoseModel:
    """Animated standing figure. `trained` is always false.

    Above `walk_at` the motion score, the figure switches from a breathing bob to a
    generic walk cycle. That switch is an animation cue, not a gait estimate.
    """

    name = "placeholder"
    trained = False

    def __init__(self, walk_at: float = 0.05):
        self.walk_at = walk_at

    def infer(self, csi: np.ndarray, sample_rate_hz: float, motion: float, now: float) -> BodyPose:
        del csi, sample_rate_hz  # the placeholder does not read the channel
        pose = _STANDING.copy()
        breath = math.sin(2 * math.pi * 0.25 * float(now))
        pose[5:7, 1] += 0.008 * breath
        pose[0, 1] += 0.004 * breath
        walking = np.isfinite(motion) and float(motion) >= self.walk_at
        if walking:
            swing = math.sin(2 * math.pi * 0.9 * float(now))
            pose[13, 0] += 0.05 * swing
            pose[15, 0] += 0.10 * swing
            pose[14, 0] -= 0.05 * swing
            pose[16, 0] -= 0.10 * swing
            pose[7, 0] -= 0.06 * swing
            pose[9, 0] -= 0.10 * swing
            pose[8, 0] += 0.06 * swing
            pose[10, 0] += 0.10 * swing
        return BodyPose(
            keypoints=pose,
            placeholder=True,
            message=PLACEHOLDER_MESSAGE,
            model=self.name,
        )


def load_pose_model(spec: str | None):
    """Return the placeholder, or an instance of `package.module:Class`.

    The class is constructed with no arguments. Only an instance with `trained is True`
    is treated as a real model by the dashboard; this loader does not flip that flag.
    """
    if spec is None or spec in ("", "placeholder"):
        return PlaceholderPoseModel()
    if ":" not in spec:
        raise ValueError("pose model must be 'package.module:Class' or 'placeholder'")
    module_name, class_name = spec.split(":", 1)
    if not module_name or not class_name:
        raise ValueError("pose model must be 'package.module:Class' or 'placeholder'")
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    model = cls()
    if not hasattr(model, "infer") or not hasattr(model, "trained"):
        raise ValueError(f"{spec} must provide infer(...) and a trained attribute")
    return model
