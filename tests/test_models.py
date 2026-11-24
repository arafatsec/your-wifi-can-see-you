"""The pose interface must not pretend an animation is a trained model."""
import numpy as np
import pytest

from src.models import JOINTS, BodyPose, PlaceholderPoseModel, load_pose_model
from src.models.pose import PLACEHOLDER_MESSAGE


def test_placeholder_is_labelled_and_deterministic():
    model = load_pose_model(None)
    assert model.trained is False
    a = model.infer(np.zeros((4, 8)), 100.0, motion=0.0, now=1.25).to_dict()
    b = model.infer(np.zeros((4, 8)), 100.0, motion=0.0, now=1.25).to_dict()
    assert a["placeholder"] is True
    assert a["message"] == PLACEHOLDER_MESSAGE
    assert a["trained"] is False
    assert a["keypoints"] == b["keypoints"]
    assert len(a["keypoints"]) == len(JOINTS) == 17
    assert len(a["keypoints"][0]) == 3


def test_placeholder_walk_cycle_moves_the_ankles_more_than_idle():
    model = PlaceholderPoseModel()
    idle = model.infer(np.zeros((1, 1)), 0.0, motion=0.0, now=0.3).keypoints
    walk = model.infer(np.zeros((1, 1)), 0.0, motion=0.2, now=0.3).keypoints
    assert abs(walk[15, 0] - idle[15, 0]) > 0.02


class _Fixed:
    trained = True
    name = "fixed-test"

    def infer(self, csi, sample_rate_hz, motion, now):
        del csi, sample_rate_hz, motion, now
        keypoints = np.zeros((17, 3))
        keypoints[:, 1] = np.linspace(0.1, 1.7, 17)
        return BodyPose(keypoints=keypoints, placeholder=False, message="fixed-test output", model=self.name)


def test_loader_accepts_a_trained_class():
    model = load_pose_model("tests.test_models:_Fixed")
    pose = model.infer(np.zeros((2, 2)), 10.0, 0.0, 0.0).to_dict()
    assert pose["placeholder"] is False
    assert pose["model"] == "fixed-test"
    assert pose["keypoints"][0][1] == pytest.approx(0.1)


def test_loader_rejects_a_bad_spec():
    with pytest.raises(ValueError):
        load_pose_model("not-a-spec")
