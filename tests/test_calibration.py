"""Tests for the threshold calibration maths.

These need no photographs: they check that the tool draws the right conclusion
from a given set of scores. Whether the scores themselves are any good is a
question about the photographs, and calibrate.py's report says so out loud.

To actually calibrate, put photographs in face-service/tests/faces/ and run
``sh calibrate.sh`` from the project root.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import calibrate  # noqa: E402


def test_clean_separation_lands_between_the_two_distributions():
    genuine = [0.62, 0.58, 0.71, 0.55]
    impostor = [0.21, 0.30, 0.18, 0.12]

    result = calibrate.recommend(genuine, impostor, calibrate.sweep(genuine, impostor))

    assert result["ok"] is True
    assert result["separated"] is True
    # Midway between the worst genuine pair and the best impostor pair.
    assert result["match_threshold"] == pytest.approx((0.55 + 0.30) / 2, abs=1e-4)
    assert result["review_min"] < result["match_threshold"]


def test_overlapping_distributions_are_reported_as_overlapping():
    """The dangerous case: no threshold separates these, and saying otherwise
    would hand somebody a number that quietly lets impostors through."""
    genuine = [0.45, 0.28, 0.61, 0.33]
    impostor = [0.20, 0.38, 0.15, 0.41]

    result = calibrate.recommend(genuine, impostor, calibrate.sweep(genuine, impostor))

    assert result["ok"] is True
    assert result["separated"] is False
    assert "equal error rate" in result["rule"]


def test_a_single_person_is_not_enough_to_conclude_anything():
    genuine = [0.61, 0.58]
    result = calibrate.recommend(genuine, [], calibrate.sweep(genuine, []))

    assert result["ok"] is False
    assert "two people" in result["reason"]


def test_error_rates_move_the_right_way_as_the_threshold_rises():
    genuine = [0.50, 0.55, 0.60]
    impostor = [0.20, 0.25, 0.30]
    rows = calibrate.sweep(genuine, impostor)

    low = next(r for r in rows if abs(r["threshold"] - 0.15) < 1e-9)
    high = next(r for r in rows if abs(r["threshold"] - 0.60) < 1e-9)

    # A low threshold accepts everybody; a high one rejects everybody.
    assert low["far"] == 1.0 and low["frr"] == 0.0
    assert high["far"] == 0.0 and high["frr"] > 0.0


def test_photos_are_grouped_by_person_in_both_layouts(tmp_path):
    flat = tmp_path / "flat"
    flat.mkdir()
    (flat / "somchai_1.jpg").write_bytes(b"x")
    (flat / "somchai_2.jpg").write_bytes(b"x")
    (flat / "nid_1.jpg").write_bytes(b"x")
    (flat / "notes.txt").write_text("ignored")

    grouped = calibrate.collect_photos(flat)
    assert sorted(grouped) == ["nid", "somchai"]
    assert len(grouped["somchai"]) == 2

    nested = tmp_path / "nested"
    (nested / "somchai").mkdir(parents=True)
    (nested / "nid").mkdir(parents=True)
    (nested / "somchai" / "enrolment.png").write_bytes(b"x")
    (nested / "somchai" / "webcam.jpg").write_bytes(b"x")
    (nested / "nid" / "1.jpeg").write_bytes(b"x")

    grouped = calibrate.collect_photos(nested)
    assert sorted(grouped) == ["nid", "somchai"]
    assert len(grouped["somchai"]) == 2


def test_pair_scoring_separates_same_person_from_different_people():
    def unit(*values):
        vector = np.array(values, dtype=np.float32)
        return vector / np.linalg.norm(vector)

    embeddings = {
        "a": [unit(1, 0, 0), unit(0.99, 0.14, 0)],
        "b": [unit(0, 1, 0), unit(0.14, 0.99, 0)],
    }

    genuine, impostor = calibrate.score_pairs(embeddings)

    assert len(genuine) == 2       # one pair per person
    assert len(impostor) == 4      # every a against every b
    assert min(s for _, s in genuine) > max(s for _, s in impostor)
