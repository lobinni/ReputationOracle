"""
Direct-mode tests for ReputationOracle.

Run with: pytest tests/direct/ -v
"""

import pytest
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'contracts'))


# ---------------------------------------------------------------------------
# Digest tests
# ---------------------------------------------------------------------------

def test_canonical_signals_digest_deterministic():
    """Same signals in any order produce the same digest."""
    from reputation_oracle import canonical_signals_digest

    signals_a = [
        {"key": "compliance", "value": "active", "polarity": "positive"},
        {"key": "audit_status", "value": "passed", "polarity": "positive"},
    ]
    signals_b = [
        {"key": "audit_status", "value": "passed", "polarity": "positive"},
        {"key": "compliance", "value": "active", "polarity": "positive"},
    ]
    assert canonical_signals_digest(signals_a) == canonical_signals_digest(signals_b)


def test_canonical_signals_digest_changes_on_value():
    """A changed value produces a different digest."""
    from reputation_oracle import canonical_signals_digest

    signals_a = [{"key": "compliance", "value": "active", "polarity": "positive"}]
    signals_b = [{"key": "compliance", "value": "expired", "polarity": "negative"}]
    assert canonical_signals_digest(signals_a) != canonical_signals_digest(signals_b)


def test_canonical_signals_digest_changes_on_polarity():
    """A changed polarity produces a different digest."""
    from reputation_oracle import canonical_signals_digest

    signals_a = [{"key": "audit", "value": "completed", "polarity": "positive"}]
    signals_b = [{"key": "audit", "value": "completed", "polarity": "negative"}]
    assert canonical_signals_digest(signals_a) != canonical_signals_digest(signals_b)


# ---------------------------------------------------------------------------
# Signal sanitisation tests
# ---------------------------------------------------------------------------

def test_sanitise_signals_deduplicates():
    """Duplicate keys keep only the first occurrence."""
    from reputation_oracle import sanitise_signals

    raw = [
        {"key": "audit", "value": "passed", "polarity": "positive"},
        {"key": "audit", "value": "failed", "polarity": "negative"},
    ]
    result = sanitise_signals(raw)
    assert len(result) == 1
    assert result[0]["value"] == "passed"


def test_sanitise_signals_sorts():
    """Output is alphabetically sorted by key."""
    from reputation_oracle import sanitise_signals

    raw = [
        {"key": "z_signal", "value": "a", "polarity": "neutral"},
        {"key": "a_signal", "value": "b", "polarity": "positive"},
    ]
    result = sanitise_signals(raw)
    assert result[0]["key"] == "a_signal"
    assert result[1]["key"] == "z_signal"


def test_sanitise_signals_caps_count():
    """More than MAX_SIGNALS items are capped."""
    from reputation_oracle import sanitise_signals, MAX_SIGNALS

    raw = [
        {"key": f"key_{i:03d}", "value": f"val_{i}", "polarity": "neutral"}
        for i in range(MAX_SIGNALS + 20)
    ]
    result = sanitise_signals(raw)
    assert len(result) == MAX_SIGNALS


def test_sanitise_signals_validates_polarity():
    """Invalid polarities are normalised to neutral."""
    from reputation_oracle import sanitise_signals

    raw = [{"key": "test", "value": "val", "polarity": "INVALID"}]
    result = sanitise_signals(raw)
    assert result[0]["polarity"] == "neutral"


def test_sanitise_signals_empty_key_dropped():
    """Signals with empty keys are dropped."""
    from reputation_oracle import sanitise_signals

    raw = [
        {"key": "", "value": "val", "polarity": "neutral"},
        {"key": "valid", "value": "val", "polarity": "positive"},
    ]
    result = sanitise_signals(raw)
    assert len(result) == 1
    assert result[0]["key"] == "valid"


def test_sanitise_signals_non_dict_skipped():
    """Non-dict items are skipped."""
    from reputation_oracle import sanitise_signals

    raw = ["not a dict", 42, {"key": "valid", "value": "val", "polarity": "neutral"}]
    result = sanitise_signals(raw)
    assert len(result) == 1


def test_sanitise_signals_rejects_non_list():
    """A non-list input raises ValueError."""
    from reputation_oracle import sanitise_signals

    with pytest.raises(ValueError, match="not a list"):
        sanitise_signals("not a list")


# ---------------------------------------------------------------------------
# JSON parsing tests
# ---------------------------------------------------------------------------

def test_parse_json_envelope_plain():
    """Parses plain JSON."""
    from reputation_oracle import parse_json_envelope

    result = parse_json_envelope('{"key": "value"}')
    assert result == {"key": "value"}


def test_parse_json_envelope_fenced():
    """Parses JSON inside code fences."""
    from reputation_oracle import parse_json_envelope

    text = '```json\n{"key": "value"}\n```'
    result = parse_json_envelope(text)
    assert result == {"key": "value"}


def test_parse_json_envelope_with_prose():
    """Parses JSON buried in prose."""
    from reputation_oracle import parse_json_envelope

    text = 'Here is the result: {"key": "value"} end.'
    result = parse_json_envelope(text)
    assert result == {"key": "value"}


def test_parse_json_envelope_raises_on_garbage():
    """Raises on unparseable input."""
    from reputation_oracle import parse_json_envelope

    with pytest.raises(ValueError, match="LLM_ERROR"):
        parse_json_envelope("not json at all")


def test_parse_json_envelope_accepts_dict():
    """Already-parsed dicts pass through."""
    from reputation_oracle import parse_json_envelope

    result = parse_json_envelope({"key": "value"})
    assert result == {"key": "value"}


# ---------------------------------------------------------------------------
# Envelope packing tests
# ---------------------------------------------------------------------------

def test_pack_observation_valid():
    """Valid model output produces an ok envelope."""
    from reputation_oracle import pack_observation

    raw = json.dumps({"signals": [{"key": "audit", "value": "passed", "polarity": "positive"}]})
    result = json.loads(pack_observation(raw))
    assert result["ok"] is True
    assert len(result["signals"]) == 1


def test_pack_observation_malformed():
    """Malformed output produces an error envelope."""
    from reputation_oracle import pack_observation

    result = json.loads(pack_observation("not json"))
    assert result["ok"] is False
    assert "LLM_ERROR" in result["error"]


def test_pack_verdict_valid():
    """Valid verdict is packed correctly."""
    from reputation_oracle import pack_verdict

    raw = json.dumps({
        "score": 4,
        "confidence": 2,
        "summary": "Good standing",
        "changes": [{"key": "audit", "before": "pending", "after": "passed"}]
    })
    result = json.loads(pack_verdict(raw))
    assert result["ok"] is True
    assert result["score"] == 4
    assert result["confidence"] == 2


def test_pack_verdict_clamps_score():
    """Out-of-range scores are clamped."""
    from reputation_oracle import pack_verdict, MAX_SCORE

    raw = json.dumps({"score": 99, "confidence": 1, "summary": "test", "changes": []})
    result = json.loads(pack_verdict(raw))
    assert result["score"] == MAX_SCORE


def test_pack_verdict_clamps_confidence():
    """Out-of-range confidence is clamped."""
    from reputation_oracle import pack_verdict, MAX_CONFIDENCE

    raw = json.dumps({"score": 3, "confidence": 99, "summary": "test", "changes": []})
    result = json.loads(pack_verdict(raw))
    assert result["confidence"] == MAX_CONFIDENCE


# ---------------------------------------------------------------------------
# Clamp function tests
# ---------------------------------------------------------------------------

def test_clamp_score_handles_non_integer():
    """Non-integer score defaults to SCORE_MIXED."""
    from reputation_oracle import clamp_score, SCORE_MIXED

    assert clamp_score("not_a_number") == SCORE_MIXED
    assert clamp_score(None) == SCORE_MIXED


def test_clamp_confidence_handles_non_integer():
    """Non-integer confidence defaults to CONF_LOW."""
    from reputation_oracle import clamp_confidence, CONF_LOW

    assert clamp_confidence("not_a_number") == CONF_LOW
    assert clamp_confidence(None) == CONF_LOW


# ---------------------------------------------------------------------------
# Constant tests
# ---------------------------------------------------------------------------

def test_score_constants_ordering():
    """Score constants are ordered correctly."""
    from reputation_oracle import (
        SCORE_UNKNOWN, SCORE_CRITICAL, SCORE_POOR,
        SCORE_MIXED, SCORE_GOOD, SCORE_EXCELLENT
    )
    assert SCORE_UNKNOWN < SCORE_CRITICAL < SCORE_POOR < SCORE_MIXED < SCORE_GOOD < SCORE_EXCELLENT


def test_confidence_constants_ordering():
    """Confidence constants are ordered correctly."""
    from reputation_oracle import CONF_LOW, CONF_MEDIUM, CONF_HIGH
    assert CONF_LOW < CONF_MEDIUM < CONF_HIGH


# ---------------------------------------------------------------------------
# Prompt tests
# ---------------------------------------------------------------------------

def test_build_extraction_prompt_with_anchors():
    """Extraction prompt includes anchoring rules when anchors exist."""
    from reputation_oracle import build_extraction_prompt

    anchors = [{"key": "audit", "value": "passed", "polarity": "positive"}]
    prompt = build_extraction_prompt("page content", "criteria", "TestEntity", anchors)
    assert "ANCHORING RULES" in prompt
    assert "audit" in prompt


def test_build_extraction_prompt_without_anchors():
    """First extraction prompt has no anchoring rules."""
    from reputation_oracle import build_extraction_prompt

    prompt = build_extraction_prompt("page content", "criteria", "TestEntity", [])
    assert "no established signals" in prompt.lower()


def test_build_scoring_prompt_includes_snapshots():
    """Scoring prompt includes before and after signals."""
    from reputation_oracle import build_scoring_prompt

    before = [{"key": "audit", "value": "pending", "polarity": "neutral"}]
    after = [{"key": "audit", "value": "passed", "polarity": "positive"}]
    prompt = build_scoring_prompt("criteria", "TestEntity", before, after)
    assert "PREVIOUS" in prompt
    assert "CURRENT" in prompt
    assert "pending" in prompt
    assert "passed" in prompt


# ---------------------------------------------------------------------------
# Error prefix tests
# ---------------------------------------------------------------------------

def test_error_prefixes_are_distinct():
    """All error prefixes are defined and distinct."""
    from reputation_oracle import ERR_EXPECTED, ERR_EXTERNAL, ERR_TRANSIENT, ERR_LLM
    
    prefixes = [ERR_EXPECTED, ERR_EXTERNAL, ERR_TRANSIENT, ERR_LLM]
    assert len(prefixes) == len(set(prefixes))


def test_pack_error_format():
    """Error envelopes have the expected structure."""
    from reputation_oracle import pack_error

    result = json.loads(pack_error("test error"))
    assert result["ok"] is False
    assert result["error"] == "test error"
