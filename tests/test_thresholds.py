"""Whose thresholds decide.

The platform configures them, shows them to an auditor, and writes them into
the record of every check. For a while it did all three while this service
decided on its own environment instead, so the number on the report and the
number that decided the learner's result were two unrelated things that only
happened to agree — and one of them, the review threshold, did not even agree.

These check the arithmetic of that handover. Nothing here needs a photograph.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, face_engine  # noqa: E402
from app.main import _thresholds  # noqa: E402


def test_the_callers_thresholds_are_the_ones_applied():
    # 0.5 sits above the shipped match threshold of 0.363, so on this
    # service's own configuration it would pass.
    assert face_engine.decide(0.5) == "pass"

    # A site that has calibrated something stricter gets what it asked for.
    assert face_engine.decide(0.5, match=0.8, review=0.6) == "fail"
    assert face_engine.decide(0.7, match=0.8, review=0.6) == "review"
    assert face_engine.decide(0.9, match=0.8, review=0.6) == "pass"


def test_a_caller_that_sends_nothing_still_gets_a_decision():
    """An older integration must keep working, on this service's values."""
    resolved = _thresholds(None, None)
    assert resolved["match"] == config.MATCH_THRESHOLD
    assert resolved["review_min"] == config.REVIEW_MIN

    assert face_engine.decide(0.5, None, None) == "pass"


def test_the_thresholds_that_were_applied_are_reported_back():
    """The caller stores what was used, not what it hoped would be used."""
    resolved = _thresholds("0.8", "0.6")
    assert resolved["match"] == 0.8
    assert resolved["review_min"] == 0.6


def test_a_threshold_that_is_not_a_number_is_refused():
    """Quietly substituting a default would hide a broken setting while
    writing decisions the platform cannot account for."""
    with pytest.raises(ValueError):
        _thresholds("very strict", None)


@pytest.mark.parametrize("value", ["1.5", "-2", "42"])
def test_a_threshold_outside_the_cosine_range_is_refused(value):
    """Above 1 nothing can ever match and below -1 everything does, so either
    is a mistake rather than a policy anybody meant to set."""
    with pytest.raises(ValueError):
        _thresholds(value, None)


def test_a_review_band_that_sits_above_the_match_threshold_is_refused():
    """There is no band between them to review, so the pair is nonsense and
    the site needs telling rather than having it silently ignored."""
    with pytest.raises(ValueError):
        _thresholds("0.4", "0.9")
