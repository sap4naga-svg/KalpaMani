"""Test-suite configuration.

Puts the ``tests`` directory itself on ``sys.path`` so the Phase-3A synthetic
fixtures can be imported as ``fixtures.phase3a`` from any test module, without
turning ``tests`` into an installed package and without disturbing how the
existing Phase-1 and Phase-2 tests are collected.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_ROOT = Path(__file__).resolve().parent
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))
