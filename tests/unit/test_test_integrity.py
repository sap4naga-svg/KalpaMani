"""The test suite audits itself: no assertion in it may be unable to fail.

Two assertions on this branch could not. Both read as checks and neither was
one -- ``or True`` makes the whole expression unconditional, so the interesting
half was never evaluated for its truth, and both would have passed against a
build with no binding at all. That is worse than a missing test: a missing test
is visibly absent, while a tautological one is counted in a green run.

Running :mod:`scripts.test_integrity_audit` from a test is what makes this a
standing property rather than a one-off cleanup. The scanner also has its own
fixtures below, because an audit nobody tests is an audit that can quietly stop
finding anything -- exactly the failure it exists to prevent.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = PROJECT_ROOT / "tests"
AUDIT_PATH = PROJECT_ROOT / "scripts" / "test_integrity_audit.py"


def _audit_module() -> ModuleType:
    """Load the audit by path. ``scripts`` is not an importable package."""
    spec = importlib.util.spec_from_file_location("kalpamani_test_integrity_audit", AUDIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDIT = _audit_module()


# ---------------------------------------------------------------------------
# The standing property
# ---------------------------------------------------------------------------


def test_no_assertion_in_the_suite_is_unable_to_fail() -> None:
    """Every assertion under ``tests/`` depends on something the code decides."""
    findings = AUDIT.audit([TESTS_ROOT])
    rendered = "\n".join(finding.render(PROJECT_ROOT) for finding in findings)
    assert not findings, (
        "Assertions that cannot do their job are counted in a green run and prove "
        f"nothing:\n{rendered}"
    )


def test_the_audit_scans_the_whole_tree() -> None:
    """A scanner that silently covered one directory would pass trivially."""
    scanned = {path.name for path in AUDIT.python_files(TESTS_ROOT)}
    assert "phase3a.py" in scanned, "The fixtures are scanned too."
    assert "test_phase3a_query_identity.py" in scanned
    assert "test_phase2_order_safety.py" in scanned, "Phase-2 tests are in scope."
    assert len(scanned) >= 20


# ---------------------------------------------------------------------------
# The scanner itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("assert value or True", "TAUTOLOGICAL_ASSERT"),
        ("assert True or value", "TAUTOLOGICAL_ASSERT"),
        ("assert value or 1", "TAUTOLOGICAL_ASSERT"),
        ("assert (a == b) or 'why'", "TAUTOLOGICAL_ASSERT"),
        ("assert not False", "TAUTOLOGICAL_ASSERT"),
        ("assert value or (other or True)", "TAUTOLOGICAL_ASSERT"),
        ("assert True", "CONSTANT_ASSERT"),
        ("assert value and False", "IMPOSSIBLE_ASSERT"),
        ("assert False and value", "IMPOSSIBLE_ASSERT"),
        ("assert False", "IMPOSSIBLE_ASSERT"),
        ("assert not True", "IMPOSSIBLE_ASSERT"),
    ],
)
def test_the_scanner_catches_every_unconditional_spelling(source: str, kind: str) -> None:
    """One defect, many spellings. A text search for ``or True`` finds one of them."""
    findings = AUDIT.scan_source(source, Path("synthetic.py"))
    assert [finding.kind for finding in findings] == [kind], source


@pytest.mark.parametrize(
    "source",
    [
        "assert value",
        "assert a == b",
        "assert a or b",
        "assert a and b",
        "assert not value",
        "assert value, 'a message that is a constant, which is fine'",
        "assert flags or defaults",
        "x = True or value",  # NEGATIVE CONTROL: not an assertion.
    ],
)
def test_the_scanner_leaves_sound_assertions_alone(source: str) -> None:
    """A scanner that guessed at names would start refusing correct tests."""
    assert AUDIT.scan_source(source, Path("synthetic.py")) == []


def test_a_broad_raises_inside_a_test_is_refused() -> None:
    """``pytest.raises(Exception)`` records any failure as the expected refusal.

    A ``match=`` narrows the message and not the type, so an unrelated error
    whose text happens to contain the phrase still passes.
    """
    source = (
        "def test_thing():\n    with pytest.raises(Exception, match='refused'):\n        do_it()\n"
    )
    findings = AUDIT.scan_source(source, Path("synthetic.py"))
    assert [finding.kind for finding in findings] == ["BROAD_EXCEPTION"]


def test_a_narrow_raises_is_accepted() -> None:
    """NEGATIVE CONTROL for the refusal above."""
    source = (
        "def test_thing():\n"
        "    with pytest.raises(QualityGateError, match='refused'):\n"
        "        do_it()\n"
    )
    assert AUDIT.scan_source(source, Path("synthetic.py")) == []


def test_a_bare_except_inside_a_test_is_refused() -> None:
    source = "def test_thing():\n    try:\n        do_it()\n    except:\n        pass\n"
    findings = AUDIT.scan_source(source, Path("synthetic.py"))
    assert [finding.kind for finding in findings] == ["BROAD_EXCEPTION"]


def test_a_broad_except_outside_a_test_is_left_alone() -> None:
    """Helpers and fixtures legitimately translate errors; tests must not."""
    source = "def _helper():\n    try:\n        do_it()\n    except Exception:\n        pass\n"
    assert AUDIT.scan_source(source, Path("synthetic.py")) == []


@pytest.mark.parametrize(
    "decorator",
    ["@pytest.mark.skip", "@pytest.mark.xfail", "@pytest.mark.skipif(WINDOWS)"],
)
def test_a_skip_without_a_reason_is_refused(decorator: str) -> None:
    """A decision to stop checking something has to be reviewable."""
    source = f"{decorator}\ndef test_thing():\n    assert value\n"
    findings = AUDIT.scan_source(source, Path("synthetic.py"))
    assert [finding.kind for finding in findings] == ["UNEXPLAINED_SKIP"]


def test_a_skip_with_a_reason_is_accepted() -> None:
    """NEGATIVE CONTROL. Skipping is allowed; skipping silently is not."""
    marker = "@pytest.mark.skipif(WINDOWS, reason='no fork here')"
    source = marker + "\ndef test_thing():\n    assert value\n"
    assert AUDIT.scan_source(source, Path("synthetic.py")) == []


def test_the_audit_exits_non_zero_when_it_finds_something(tmp_path: Path) -> None:
    """The standalone script is the reportable artifact, so its exit code matters."""
    offender = tmp_path / "test_offender.py"
    offender.write_text("def test_thing():\n    assert value or True\n", encoding="utf-8")
    assert AUDIT.main([str(offender)]) == 1
    offender.write_text("def test_thing():\n    assert value\n", encoding="utf-8")
    assert AUDIT.main([str(offender)]) == 0
    assert AUDIT.main([str(tmp_path / "nope")]) == 2
