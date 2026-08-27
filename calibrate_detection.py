"""Where should the detector's confidence floor sit?

It shipped at 0.9, which is OpenCV's number from a demo script, and it is wrong
for this job. A large, sharply focused, well-lit portrait scores 0.882 with
YuNet and was being refused — while the learner was told to turn a light on,
because the failure message blamed the lighting for everything.

Genuine faces score roughly 0.87 to 0.95. A floor at 0.9 therefore sits in the
middle of the distribution of real faces and rejects a slice of them at random,
which from the learner's side looks exactly like a system that does not work.

Confidence alone cannot separate real faces from noise here: the spurious
detections in these photographs reach 0.871, above some genuine ones. What does
separate them is size — the false ones are 16 to 46 pixels across while the
real ones are 220 to 410. So the floor moves down and the size rule does the
work it was always better suited to.

Run inside the service container:
    python calibrate_detection.py
"""
from __future__ import annotations

from pathlib import Path

import cv2

from app import config

HERE = Path(__file__).resolve().parent
MODEL = config.MODELS_DIR / "face_detection_yunet_2023mar.onnx"

# Below this, YuNet is reporting texture rather than a face; the sweep only
# needs to see what is above it.
PROBE_FLOOR = 0.3

CANDIDATES = [0.60, 0.70, 0.75, 0.80, 0.85, 0.88, 0.90, 0.92]


def detections(path: Path) -> list[tuple[float, int]]:
    """(score, smaller side in pixels) for everything YuNet finds."""
    image = cv2.imread(str(path))
    if image is None:
        return []
    height, width = image.shape[:2]

    detector = cv2.FaceDetectorYN.create(str(MODEL), "", (width, height),
                                         score_threshold=PROBE_FLOOR)
    detector.setInputSize((width, height))
    _, faces = detector.detect(image)

    return [] if faces is None else [
        (float(face[-1]), int(min(face[2], face[3]))) for face in faces]


if __name__ == "__main__":
    photos = sorted(HERE.glob("tests/faces-public/*/*.jpg"))
    if not photos:
        raise SystemExit("no reference photographs; run fetch-reference-faces.py")

    # The subject of a portrait is the largest face in it. Everything else that
    # YuNet reports in these images is either a bystander or noise, and both
    # behave the same way for this measurement.
    genuine: list[float] = []
    spurious: list[float] = []

    for photo in photos:
        found = detections(photo)
        if not found:
            continue
        biggest = max(found, key=lambda pair: pair[1])
        for score, size in found:
            (genuine if (score, size) == biggest and size >= config.MIN_FACE_SIZE
             else spurious).append(score)

    lines = [
        "YuNet confidence floor",
        f"{len(photos)} photographs, {len(genuine)} subject faces, "
        f"{len(spurious)} bystanders and false positives",
        f"size floor held at {config.MIN_FACE_SIZE}px throughout",
        "",
    ]

    if genuine:
        genuine.sort()
        lines.append(f"subject faces score {genuine[0]:.3f} to {genuine[-1]:.3f}")
    if spurious:
        spurious.sort()
        lines.append(f"everything else scores {spurious[0]:.3f} to {spurious[-1]:.3f}")
    lines += ["", "floor   subjects accepted   others let through"]

    rows = []
    for floor in CANDIDATES:
        accepted = sum(1 for score in genuine if score >= floor)
        leaked = sum(1 for score in spurious if score >= floor)
        rows.append((floor, accepted, leaked))
        lines.append(f" {floor:.2f}      {accepted:2d} / {len(genuine):<2d}"
                     f"            {leaked}")

    # Every subject accepted, then the highest such floor: the further above the
    # noise it sits, the less a slightly worse frame flips the outcome. Leakage
    # is not the tiebreaker because the size rule already stops it, and a
    # bystander in frame is reported as multiple faces rather than accepted.
    perfect = [row for row in rows if row[1] == len(genuine)]

    lines.append("")
    if perfect:
        chosen = max(perfect, key=lambda row: row[0])
        lines.append(
            f"CHOSEN: {chosen[0]:.2f}  ({chosen[1]}/{len(genuine)} subject faces accepted)")
    else:
        # No fallback. The first version quietly took whichever floor accepted
        # the most, which was the lowest one on offer — a number nobody had
        # reasoned about, presented as a result. If the labelling cannot
        # separate the set, the honest output is that it cannot.
        chosen = (None, 0, 0)
        lines += [
            "NO FLOOR ACCEPTS EVERY SUBJECT FACE.",
            "",
            "Which means the labelling here is too crude to pick a number:"
            " 'largest face in",
            "the photograph' catches blurred bystanders in press shots as well as"
            " subjects.",
            "Do not read a threshold off this table. What it does establish is the"
            " range that",
            "genuine, sharp, large faces occupy, and that 0.90 cuts through the"
            " middle of it.",
        ]

    lines += [
        "",
        "",
        "0.90 accepted only "
        f"{sum(1 for score in genuine if score >= 0.90)}/{len(genuine)}"
        " of these faces, and the learner was told to turn a light on.",
        "",
        "Measured on public-domain press portraits, not on webcam frames from",
        "the people who will use this. A webcam frame is noisier and dimmer than",
        "a press photograph, so if anything this floor is still on the high side.",
        "Re-run it against real enrolment frames when there are some.",
    ]

    report = "\n".join(lines) + "\n"
    print(report, end="")

    for candidate in [HERE / "reports", HERE.parent / "reports"]:
        if candidate.is_dir():
            (candidate / "DETECTION-CALIBRATION.txt").write_text(report, encoding="utf-8")
            break
