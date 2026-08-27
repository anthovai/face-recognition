"""Smoke tests for the YuNet + SFace pipeline.

These prove the engine loads and behaves on the error paths. They do NOT prove
matching accuracy — that needs real enrolment photos and a calibration run.
See test_calibration.py for the harness that does.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, face_engine  # noqa: E402

MODELS_PRESENT = (
    (config.MODELS_DIR / face_engine.DETECTOR_MODEL).is_file()
    and (config.MODELS_DIR / face_engine.RECOGNIZER_MODEL).is_file()
)
needs_models = pytest.mark.skipif(not MODELS_PRESENT, reason="run models/fetch.sh first")


def encode(img: np.ndarray) -> bytes:
    return cv2.imencode(".jpg", img)[1].tobytes()


def test_decode_rejects_garbage():
    with pytest.raises(face_engine.FaceEngineError) as e:
        face_engine.decode_image(b"not an image")
    assert e.value.code == "invalid_image"


def test_decode_rejects_oversized_payload():
    with pytest.raises(face_engine.FaceEngineError) as e:
        face_engine.decode_image(b"x" * (config.MAX_IMAGE_BYTES + 1))
    assert e.value.code == "image_too_large"


@needs_models
def test_blank_frame_reports_no_face():
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    with pytest.raises(face_engine.FaceEngineError) as e:
        face_engine.extract_face(blank)
    assert e.value.code == "no_face"


@needs_models
def test_noise_frame_reports_no_face():
    rng = np.random.default_rng(0)
    noise = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)
    with pytest.raises(face_engine.FaceEngineError) as e:
        face_engine.extract_face(noise)
    assert e.value.code == "no_face"


def test_decision_bands_follow_thresholds():
    assert face_engine.decide(config.MATCH_THRESHOLD) == "pass"
    assert face_engine.decide(config.MATCH_THRESHOLD + 0.1) == "pass"
    assert face_engine.decide(config.REVIEW_MIN) == "review"
    assert face_engine.decide(config.REVIEW_MIN - 0.01) == "fail"


def test_pose_is_estimated_from_yunets_five_landmarks():
    """Regression: solvePnP's default ITERATIVE solver bootstraps with DLT,
    which needs six point correspondences. YuNet gives five, so the default
    raised on every real face — invisible to a fake camera that never produces
    one, and fatal to enrolment and verification in production."""
    landmarks = np.array([
        [270.0, 220.0],   # right eye
        [370.0, 220.0],   # left eye
        [320.0, 280.0],   # nose tip
        [280.0, 330.0],   # right mouth corner
        [360.0, 330.0],   # left mouth corner
    ], dtype=np.float32)

    pitch, yaw, roll = face_engine._estimate_pose(landmarks, (480, 640))

    assert all(isinstance(angle, float) for angle in (pitch, yaw, roll))
    # Symmetric landmarks in the middle of the frame: close to facing forward.
    assert abs(yaw) < 20
    assert abs(roll) < 20


def test_a_face_turned_to_its_own_left_reads_as_positive_yaw():
    """The sign convention active_liveness depends on.

    On the raw, un-mirrored frame the subject faces the camera, so their own
    left is on the *right* of the image — the same way it is when you look at
    somebody. Turning their head to their own left therefore swings the nose
    toward image-right, and that must come back as positive yaw. Getting this
    backwards would tell every learner to turn the wrong way.
    """
    def landmarks_with_nose_at(dx: float) -> np.ndarray:
        return np.array([
            [270.0, 220.0],            # right eye (image-left)
            [370.0, 220.0],            # left eye  (image-right)
            [320.0 + dx, 280.0],       # nose tip, swung by the turn
            [280.0, 330.0],
            [360.0, 330.0],
        ], dtype=np.float32)

    # Nose toward image-right = subject turned to their own left.
    _, yaw_own_left, _ = face_engine._estimate_pose(landmarks_with_nose_at(40), (480, 640))
    _, yaw_own_right, _ = face_engine._estimate_pose(landmarks_with_nose_at(-40), (480, 640))

    assert yaw_own_left > 0, "turning to the subject's own left must be positive yaw"
    assert yaw_own_right < 0, "turning to the subject's own right must be negative yaw"


def test_cosine_similarity_of_identical_vectors_is_one():
    v = np.array([0.6, 0.8], dtype=np.float32)
    assert face_engine.cosine_similarity(v, v) == pytest.approx(1.0)
