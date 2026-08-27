"""Passive liveness (anti-spoofing).

MiniFASNet ONNX models from MiniVision's Silent-Face-Anti-Spoofing (Apache-2.0).
Each model outputs 3 logits where index 1 is the "real face" class; scores from
every model present are averaged.

If no model file is present the service still runs but reports liveness as not
evaluated; callers must treat that as a failure in production, never as a
pass. Silently continuing without an anti-spoofing check is the failure worth
engineering against here — a photograph held up to the camera passes
everything else.
"""
from __future__ import annotations

import threading

import cv2
import numpy as np

from . import config

_sessions: list | None = None
_lock = threading.Lock()


def _get_sessions() -> list:
    global _sessions
    if _sessions is None:
        with _lock:
            if _sessions is None:
                import onnxruntime as ort

                sessions = []
                for path in sorted(config.MODELS_DIR.glob("*MiniFASNet*.onnx")):
                    sess = ort.InferenceSession(
                        str(path), providers=["CPUExecutionProvider"]
                    )
                    sessions.append((sess, _scale_from_name(path.name)))
                _sessions = sessions
    return _sessions


def _scale_from_name(name: str) -> float:
    """Crop scale is encoded in the MiniFASNet filename, e.g. '2.7_80x80_...'
    or '4_0_0_80x80_...' (meaning 4.0)."""
    head = name.split("_80x80")[0]
    tokens = head.split("_")
    candidate = tokens[0] if "." in tokens[0] or len(tokens) == 1 else f"{tokens[0]}.{tokens[1]}"
    try:
        return float(candidate)
    except ValueError:
        return 2.7


def _crop_face(img: np.ndarray, bbox, scale: float, size: int) -> np.ndarray:
    """Crop a square region around the face bbox, padded by `scale`."""
    x1, y1, x2, y2 = bbox
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    half = max(x2 - x1, y2 - y1) * scale / 2
    h, w = img.shape[:2]
    left, top = int(max(0, cx - half)), int(max(0, cy - half))
    right, bottom = int(min(w, cx + half)), int(min(h, cy + half))
    crop = img[top:bottom, left:right]
    return cv2.resize(crop, (size, size))


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / e.sum()


def check_liveness(img: np.ndarray, bbox) -> dict:
    """Run anti-spoofing on the face region.

    Returns {evaluated, score, live} — score is the mean probability of the
    "real face" class across loaded models.
    """
    sessions = _get_sessions()
    if not sessions:
        return {"evaluated": False, "score": None, "live": None}

    scores = []
    for sess, scale in sessions:
        inp = sess.get_inputs()[0]
        size = inp.shape[2] if isinstance(inp.shape[2], int) else 80
        crop = _crop_face(img, bbox, scale=scale, size=size)
        blob = crop.astype(np.float32).transpose(2, 0, 1)[np.newaxis]
        out = sess.run(None, {inp.name: blob})[0][0]
        scores.append(float(_softmax(out.astype(np.float32))[1]))

    score = float(np.mean(scores))
    return {
        "evaluated": True,
        "score": round(score, 4),
        "live": score >= config.LIVENESS_THRESHOLD,
    }
