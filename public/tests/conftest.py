"""
Test configuration and fixtures for ReputationOracle.
"""

import pytest
import sys
import os
import atexit
from pathlib import Path


# ---------------------------------------------------------------------------
# Windows temp-file cleanup workaround
# ---------------------------------------------------------------------------
_leaked_temps: list[Path] = []

if sys.platform == "win32":
    _original_unlink = os.unlink

    def _tolerant_unlink(path):
        try:
            _original_unlink(path)
        except PermissionError:
            _leaked_temps.append(Path(path))

    os.unlink = _tolerant_unlink

    @atexit.register
    def _cleanup_leaked_temps():
        for path in _leaked_temps:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Contract registry reset
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_contract_registry():
    """Clear the GenLayer contract registry between tests."""
    try:
        import genlayer
        if hasattr(genlayer, "_contract_registry"):
            genlayer._contract_registry.clear()
    except ImportError:
        pass
    yield


# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_signals():
    return [
        {"key": "audit_status", "value": "passed_2025", "polarity": "positive"},
        {"key": "compliance", "value": "active", "polarity": "positive"},
        {"key": "user_reviews", "value": "4.5_stars", "polarity": "positive"},
    ]


@pytest.fixture
def sample_signals_changed():
    return [
        {"key": "audit_status", "value": "failed_2026", "polarity": "negative"},
        {"key": "compliance", "value": "expired", "polarity": "negative"},
        {"key": "user_reviews", "value": "2.1_stars", "polarity": "negative"},
    ]
