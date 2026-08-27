"""Configuration for the face recognition service.

Every threshold is an environment variable because the value in use has to be
documented and auditable — a regulator asking "what threshold decided this
person failed?" must get an answer from configuration, not from a code diff.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = Path(os.environ.get("FACE_MODELS_DIR", ROOT / "models"))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------
# SFace produces 128-d embeddings compared by cosine similarity. OpenCV's own
# reference threshold is 0.363; it is the starting point, NOT a calibrated
# value. Calibrate against your own enrolment photos before production — see
# README, "การปรับ threshold". A threshold carried over from another face
# model does not transfer.
MATCH_THRESHOLD = _env_float("FACE_MATCH_THRESHOLD", 0.363)
REVIEW_MIN = _env_float("FACE_REVIEW_MIN", 0.30)

LIVENESS_THRESHOLD = _env_float("FACE_LIVENESS_THRESHOLD", 0.60)

MIN_FACE_SIZE = int(_env_float("FACE_MIN_SIZE", 80))
MAX_IMAGE_BYTES = int(_env_float("FACE_MAX_IMAGE_BYTES", 8 * 1024 * 1024))

# Face detector confidence.
#
# Was 0.9, copied from OpenCV's demo, and it rejected real faces. A 410-pixel
# sharply focused well-lit portrait scores 0.882 with YuNet, so the floor sat
# in the middle of the distribution of genuine faces and refused a slice of
# them — while the enrolment page told the person to turn a light on, because
# the failure message blamed the lighting for every cause.
#
# Loosened to 0.80: below every clear subject face measured (0.882 to 0.951),
# above the band where YuNet is reporting texture. This is a correction of a
# demonstrated false rejection, not a calibrated optimum — confidence alone
# cannot separate faces from noise in this data, because bystanders reach 0.93
# too. MIN_FACE_SIZE does that work, and does it better: the false detections
# are 16 to 46 pixels across and the real ones 220 to 410.
#
# Re-measure against real webcam frames, which are dimmer and noisier than
# press photographs, when there are some.
DET_SCORE_THRESHOLD = _env_float("FACE_DET_SCORE", 0.80)

SERVICE_VERSION = "1.0.0"
MODEL_PACK = "yunet+sface"

# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------
# Shared secret the caller sends as X-Face-Key.
#
# An unset key disables the check, which is convenient for a local test run and
# wrong anywhere else: this service answers "is this the same person", and an
# unauthenticated caller can ask that about anybody whose photo they hold. Set
# it, and do not publish the port beyond the network that needs it.
API_KEY = os.environ.get("FACE_API_KEY", "").strip()
