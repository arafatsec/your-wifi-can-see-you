"""Pose-model interface. No trained weights ship with this repo."""

from .pose import (
    JOINTS,
    BodyPose,
    PlaceholderPoseModel,
    load_pose_model,
)

__all__ = ["JOINTS", "BodyPose", "PlaceholderPoseModel", "load_pose_model"]
