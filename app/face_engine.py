"""Face detection, embedding and head pose — OpenCV Zoo models only.

Deliberately free of InsightFace: the buffalo_l weights are licensed for
non-commercial research only, which rules them out for a product. YuNet and
SFace are both Apache-2.0 (see models/LICENSES.md) and ship as plain ONNX,
so `cv2.FaceDetectorYN` / `cv2.FaceRecognizerSF` run them without extra deps.

Stateless: images in, results out. Nothing is persisted here — storing images,
embeddings and decisions is the calling system's job, where consent and
retention rules already live.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import cv2
import numpy as np

from . import config


class FaceEngineError(Exception):
    """Raised when an image cannot be processed (no face, too small, ...)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class DetectedFace:
    embedding: np.ndarray          # L2-normalized, shape (128,)
    bbox: tuple[float, float, float, float]
    det_score: float
    # Head pose in degrees (pitch, yaw, roll), estimated from the five YuNet
    # landmarks. yaw > 0 -> subject turned to their own left on the raw frame.
    pose: tuple[float, float, float]
    landmarks: np.ndarray          # shape (5, 2)


_detector = None
_recognizer = None
_lock = threading.Lock()

DETECTOR_MODEL = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_MODEL = "face_recognition_sface_2021dec.onnx"


def _models():
    """Lazy-load both ONNX models. Raises if a weight file is missing."""
    global _detector, _recognizer
    if _detector is None or _recognizer is None:
        with _lock:
            if _detector is None:
                path = config.MODELS_DIR / DETECTOR_MODEL
                if not path.is_file():
                    raise FaceEngineError(
                        "model_missing",
                        f"{DETECTOR_MODEL} not found — run face-service/models/fetch.sh",
                    )
                # Input size is overridden per frame in extract_face().
                _detector = cv2.FaceDetectorYN.create(
                    str(path), "", (320, 320),
                    score_threshold=config.DET_SCORE_THRESHOLD,
                )
            if _recognizer is None:
                path = config.MODELS_DIR / RECOGNIZER_MODEL
                if not path.is_file():
                    raise FaceEngineError(
                        "model_missing",
                        f"{RECOGNIZER_MODEL} not found — run face-service/models/fetch.sh",
                    )
                _recognizer = cv2.FaceRecognizerSF.create(str(path), "")
    return _detector, _recognizer


def decode_image(data: bytes) -> np.ndarray:
    """Decode raw upload bytes to a BGR image."""
    if len(data) > config.MAX_IMAGE_BYTES:
        raise FaceEngineError("image_too_large", "Image exceeds maximum allowed size")
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FaceEngineError("invalid_image", "Could not decode image data")
    return img


# A coarse generic head model in millimetres, ordered to match YuNet's five
# landmarks: right eye, left eye, nose tip, right mouth corner, left mouth
# corner. Absolute scale is irrelevant — only the resulting angles are used.
_MODEL_POINTS = np.array([
    (-30.0,  30.0, -30.0),   # right eye
    ( 30.0,  30.0, -30.0),   # left eye
    (  0.0,   0.0,   0.0),   # nose tip
    (-25.0, -30.0, -30.0),   # right mouth corner
    ( 25.0, -30.0, -30.0),   # left mouth corner
], dtype=np.float64)


def _estimate_pose(landmarks: np.ndarray, shape: tuple[int, int]) -> tuple[float, float, float]:
    """Recover (pitch, yaw, roll) in degrees from the five landmarks.

    A pinhole camera with focal length ≈ image width is assumed; webcams vary
    but the active-liveness challenge only needs "turned far enough", not a
    metric angle, so the approximation is adequate.
    """
    h, w = shape
    camera = np.array([[w, 0, w / 2], [0, w, h / 2], [0, 0, 1]], dtype=np.float64)

    # SQPNP, not the default ITERATIVE: iterative bootstraps with DLT, which
    # needs six point correspondences, and YuNet gives five. With five points
    # it does not return a poor answer — it raises, on every real face.
    try:
        ok, rvec, _ = cv2.solvePnP(
            _MODEL_POINTS, landmarks.astype(np.float64), camera,
            np.zeros((4, 1)), flags=cv2.SOLVEPNP_SQPNP,
        )
    except cv2.error:
        # Pose is used to steer the liveness challenge, not to decide identity.
        # Losing it should degrade the challenge, never fail the detection.
        return (0.0, 0.0, 0.0)

    if not ok:
        return (0.0, 0.0, 0.0)

    rmat, _ = cv2.Rodrigues(rvec)
    sy = float(np.sqrt(rmat[0, 0] ** 2 + rmat[1, 0] ** 2))
    if sy > 1e-6:
        pitch = np.degrees(np.arctan2(rmat[2, 1], rmat[2, 2]))
        yaw = np.degrees(np.arctan2(-rmat[2, 0], sy))
        roll = np.degrees(np.arctan2(rmat[1, 0], rmat[0, 0]))
    else:  # gimbal lock
        pitch = np.degrees(np.arctan2(-rmat[1, 2], rmat[1, 1]))
        yaw = np.degrees(np.arctan2(-rmat[2, 0], sy))
        roll = 0.0

    # solvePnP measures the head's rotation relative to the camera; the sign of
    # yaw is flipped so that "subject turned to their own left" reads positive,
    # matching the convention active_liveness.js was written against.
    return (float(pitch), float(-yaw), float(roll))


def extract_face(img: np.ndarray) -> DetectedFace:
    """Detect the single dominant face and return its embedding and pose.

    During identity verification there must be exactly one subject: if a second
    face is comparably large, the image is rejected rather than guessed at.
    """
    detector, recognizer = _models()
    h, w = img.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(img)

    if faces is None or len(faces) == 0:
        raise FaceEngineError("no_face", "No face detected in image")

    # YuNet row: x, y, w, h, then 5 landmark xy pairs, then score.
    faces = sorted(faces, key=lambda f: float(f[2]) * float(f[3]), reverse=True)
    main = faces[0]

    def area(f) -> float:
        return float(f[2]) * float(f[3])

    if len(faces) > 1 and area(faces[1]) > 0.5 * area(main):
        raise FaceEngineError("multiple_faces", "More than one face detected")

    if float(main[2]) < config.MIN_FACE_SIZE:
        raise FaceEngineError("face_too_small", "Face too small — move closer to the camera")

    # alignCrop expects the detector's raw row, so `main` is passed through
    # unmodified rather than reconstructed from the parsed fields.
    aligned = recognizer.alignCrop(img, main)
    emb = recognizer.feature(aligned).flatten().astype(np.float32)
    norm = float(np.linalg.norm(emb))
    if norm > 0:
        emb = emb / norm

    landmarks = np.array(main[4:14], dtype=np.float32).reshape(5, 2)
    x, y, bw, bh = (float(main[0]), float(main[1]), float(main[2]), float(main[3]))

    return DetectedFace(
        embedding=emb,
        bbox=(x, y, x + bw, y + bh),
        det_score=float(main[14]),
        pose=_estimate_pose(landmarks, (h, w)),
        landmarks=landmarks,
    )


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two L2-normalized embeddings."""
    return float(np.dot(a, b))


def decide(similarity: float,
           match: float | None = None,
           review: float | None = None) -> str:
    """Map a similarity score to a decision: pass / review / fail.

    The caller may supply the two thresholds. It should: the platform is where
    an administrator sets them, where they are shown to an auditor, and where
    they are written into the record of the decision. This service's own
    values are the fallback for a caller that has none, not the authority —
    when the two disagreed, the record said one number and the decision used
    another, and only the record was ever read.
    """
    match = config.MATCH_THRESHOLD if match is None else match
    review = config.REVIEW_MIN if review is None else review

    if similarity >= match:
        return "pass"
    if similarity >= review:
        return "review"
    return "fail"
