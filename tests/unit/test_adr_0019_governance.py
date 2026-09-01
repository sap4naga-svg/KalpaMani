"""ADR-0019 is ACCEPTED ARCHITECTURE with UNCORRECTED CODE, and both halves matter.

ADR-0018 accepted two requirements that AWS cannot both satisfy: the acquisition
role was granted a metadata-only collision resolution and denied object-byte
reads, and AWS authorizes ``HeadObject`` with ``s3:GetObject`` and publishes no
metadata action of its own. ADR-0019 keeps the security boundary and removes the
operation. **PR #46 merged**, so its conditional acceptance took effect.

An accepted amendment with an uncorrected implementation drifts three ways, and
each is guarded here:

1. **Backwards** -- a merged amendment read as still proposed. The proposed-state
   guards are **inverted rather than deleted**, so a revert to the pre-merge
   wording fails instead of merely going un-asserted.
2. **Forwards** -- accepted architecture read as built architecture. The
   production implementation does **not** conform: the dormant acquisition path
   still uses the pre-ADR-0019 shared collision path, no write-only publication
   surface exists, and infrastructure stays blocked.
3. **Downward** -- the security boundary quietly reverting to the weaker
   application-only reading that ADR-0019 declines. Granting the read action
   would let a compromised credential-holding process read known licensed
   objects, which is exactly the argument ADR-0018 s10.3 rests its two-role
   split on.

**The history is preserved, not rewritten.** While PR #46 was open ADR-0019 was
proposed and carried no authority, and ADR-0018's original design and arithmetic
governed until the merge. Both facts stay required.

**The arithmetic is derived here, not transcribed.** A number copied from prose
into prose is a number nobody checks, so the acquisition totals are recomputed
from the inventory and compared against what the ADR says.

These are text and structure checks over committed files. **Nothing here contacts
AWS, a provider or a network**, and nothing here imports an operational entry
point.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ADR = PROJECT_ROOT / "docs" / "decisions" / "ADR-0019-write-only-acquisition-collision-policy.md"
CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"
README = PROJECT_ROOT / "README.md"
PLAN = PROJECT_ROOT / "docs" / "phase3" / "implementation-plan.md"
SHARED_STORE = PROJECT_ROOT / "src" / "kalpamani" / "data" / "storage" / "s3.py"
AUDIT = PROJECT_ROOT / "scripts" / "phase3_docs_audit.py"

#: The accepted ADR-0018 inventory the corrected arithmetic is derived from.
SUBJECTS = 8
DATASETS = 3
PAGES = 2
WRITES_PER_REQUEST = 3
EXECUTIONS = 2

#: The PR #46 merge, pinned. Recorded here so a document that quietly renamed the
#: event would fail rather than pass by describing some other merge.
MERGE_COMMIT = "77974f476ead96548beb16543dfd3db8c03232c3"
APPROVED_HEAD = "bf0414c4a915d85a124ba400284ca1fa671fda27"


def flat(path: Path) -> str:
    """Whitespace-collapsed, emphasis-stripped, lowercased -- the audit's own reading."""
    return " ".join(path.read_text(encoding="utf-8").replace("**", "").split()).lower()


def _audit_module() -> ModuleType:
    """Load the audit by path, to *run* its scanner rather than read its constants.

    ``scripts`` is not an importable package. The module is registered in
    ``sys.modules`` before execution because the audit defines a ``@dataclass``,
    and ``dataclasses`` resolves the defining module through that entry rather
    than through the object it is handed.

    Importing it defines constants and functions. It runs no check, opens no
    socket and reaches no service -- ``main()`` is behind the usual guard, and
    the module is loaded under a name that is not ``__main__``.
    """
    spec = importlib.util.spec_from_file_location("kalpamani_phase3_docs_audit", AUDIT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GUARD = _audit_module()

#: The delimiters the corrected documents use, quoted here as test data.
BEGIN = (
    "<!-- RETIRED-ARITHMETIC BEGIN: ADR-0018 original, superseded by ADR-0019, "
    "no longer governing -->"
)
END = "<!-- RETIRED-ARITHMETIC END -->"


def _labels(text: str) -> list[str]:
    """Every retired figure the scan reads as current, by label."""
    return [label for _, label in GUARD.scan_retired_arithmetic(text).findings]


def _audit_registry() -> tuple[tuple[str, str], ...]:
    """``MERGED_ADR_STATUS`` read by static parse.

    Parsed rather than imported: ``scripts`` is not an importable package, and a
    static read cannot execute the audit as a side effect of checking it.
    """
    tree = ast.parse(AUDIT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        target: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            first = node.targets[0]
            if isinstance(first, ast.Name):
                target, value = first.id, node.value
        if target == "MERGED_ADR_STATUS" and isinstance(value, ast.Tuple):
            registry: tuple[tuple[str, str], ...] = ast.literal_eval(value)
            return registry
    raise AssertionError("MERGED_ADR_STATUS not found in the audit")


def test_the_adr_keeps_its_conditional_line_and_records_the_merge() -> None:
    """Inverted on the merge of PR #46, not deleted.

    This required only the conditional status line while the pull request was open.
    That line is still required -- it is what the ADR said then, and a decision
    record is not rewritten when the world moves -- and what is added beside it is
    the event that satisfied it.
    """
    text = flat(ADR)
    assert (
        "no authority until the pull request introducing it is independently reviewed and merged"
        in text
    )
    assert "adr-0018 as accepted is what governs" in text
    assert "the condition above has since been satisfied" in text
    assert "adr-0019's conditional acceptance event has occurred" in text
    assert "preserved as history, not rewritten" in text
    assert MERGE_COMMIT in text
    assert APPROVED_HEAD in text


def test_the_adr_records_the_relationship_and_the_open_implementation_gap() -> None:
    """Accepted architecture, uncorrected code. Four states, kept apart."""
    text = flat(ADR)
    assert "adr-0019 supersedes no adr wholesale" in text
    assert "narrowly amends the enumerated clauses of adr-0018" in text
    assert "adr-0018 remains accepted / in force except as amended by adr-0019" in text
    assert "adr-0017 is not amended or superseded" in text
    assert "adr-0011 is not amended or superseded" in text
    assert "the shared s3researchobjectstore remains unchanged" in text
    assert "adr-0019's amendment is now authoritative architecture" in text
    assert "the production implementation does not yet conform to that architecture" in text
    assert "adr-0019 production-code correction: not authorized / not implemented" in text
    assert (
        "the current dormant acquisition implementation still uses the pre-adr-0019 shared "
        "collision path" in text
    )
    assert (
        "no claim is made that the current implementation already has zero acquisition head "
        "operations" in text
    )
    assert (
        "no claim is made that the adr-0018-specific write-only publication surface already exists"
        in text
    )
    assert "acceptance of adr-0019 is not authorization to implement or execute it" in text


def test_the_registry_records_adr_0019_as_merged() -> None:
    """Inverted on the merge, not deleted.

    While PR #46 was open this asserted ADR-0019 was **absent** from the registry.
    The merge is the event that flips it, and deleting the guard would leave the
    reverted claim unguarded.
    """
    registry = dict(_audit_registry())
    assert registry.get("ADR-0019") == "PR #46 merged"
    assert registry.get("ADR-0018") == "PR #39 merged"
    assert registry.get("ADR-0017") == "PR #33 merged"


def test_the_adr_authorizes_nothing() -> None:
    """Accepting a corrected design is not permission to build it."""
    text = flat(ADR)
    assert "this adr authorizes nothing" in text
    assert "infrastructure remains blocked" in text
    assert "adr-0019 opens none of them" in text


def test_the_adr_leaves_the_accepted_decisions_standing() -> None:
    """It amends one rule. It supersedes nothing, and it rewrites no history."""
    text = flat(ADR)
    assert "adr-0018 remains accepted / in force" in text
    assert "the merged adr-0018 offline implementation remains merged / dormant" in text
    assert "adr-0017 is not amended and not superseded" in text
    assert "supersedes: nothing." in text


def test_the_adr_records_the_aws_constraint() -> None:
    """The gap is a documented permission fact, not a preference."""
    text = flat(ADR)
    for finding in (
        "stopped_architecture_gap_head_requires_get",
        "headobject requires the s3:getobject permission",
        "aws exposes no independent s3:headobject iam action",
        "getobjectattributes does not solve it",
        "absence of s3:listbucket prevents enumeration but not a known-key read",
        "does not remove iam authority from a compromised process",
        "the current sse-s3 design offers no kms permission that could be withheld",
    ):
        assert finding in text


def test_the_adr_cites_the_aws_documentation_it_relies_on() -> None:
    """A finding sourced to nothing is an assertion."""
    text = flat(ADR)
    for url in (
        "docs.aws.amazon.com/amazons3/latest/api/api_headobject.html",
        "docs.aws.amazon.com/amazons3/latest/userguide/using-with-s3-policy-actions.html",
        "docs.aws.amazon.com/amazons3/latest/api/api_getobjectattributes.html",
    ):
        assert url in text


def test_the_acquisition_role_is_write_only_at_both_layers() -> None:
    """The IAM prohibition is the control; the application shape is defense in depth."""
    text = flat(ADR)
    for clause in (
        "receives no s3:getobject",
        "receives no s3:getobjectversion",
        "receives no s3:getobjectattributes",
        "performs no headobject",
        "performs no object-byte read",
        "both layers are retained, independently",
    ):
        assert clause in text


def test_the_collision_fails_closed_without_comparison() -> None:
    """A 412 says a name is occupied. It says nothing about what occupies it."""
    text = flat(ADR)
    assert "a 412 does not establish that the occupied object is identical" in text
    assert "bronze_name_occupied" in text
    assert "locator_name_occupied" in text
    assert "the bounded locator retry permission of adr-0018" in text
    assert "that is a false negative in the safe direction" in text


def test_the_adr_isolates_adr_0017_from_the_correction() -> None:
    """Removing the resolution from the shared store would rewrite ADR-0017's accounting."""
    text = flat(ADR)
    assert "adr-0018-specific write-only publication surface" in text
    assert "cannot be used by adr-0017 accidentally" in text
    assert "not code authorized by this adr's proposal pull request" in text


def test_the_acquisition_arithmetic_is_derived_not_transcribed() -> None:
    """Recomputed from the inventory, then compared against the ADR's own words."""
    text = flat(ADR)
    requests = SUBJECTS * DATASETS * PAGES
    bronze_puts = requests * WRITES_PER_REQUEST
    low = bronze_puts + 1
    high = bronze_puts + 3

    assert requests == 48
    assert bronze_puts == 144
    assert f"{low} to {high}" in text
    assert f"{low * EXECUTIONS} to {high * EXECUTIONS}" in text
    assert "head_object_count == 0" in text
    assert "get_object_count == 0" in text


def test_the_assessment_arithmetic_is_unchanged() -> None:
    """The assessment role is supposed to read bytes; this amendment does not touch it."""
    text = flat(ADR)
    requests = SUBJECTS * DATASETS * PAGES
    reads = EXECUTIONS * (2 * requests + 1)
    low = reads + 1
    high = reads + 2

    assert reads == 194
    assert f"{low} to {high}" in text
    assert "195 to 196" in text


def test_the_whole_package_envelope_is_derived() -> None:
    """Two acquisition runs plus one combined assessment, added rather than quoted."""
    text = flat(ADR)
    requests = SUBJECTS * DATASETS * PAGES
    bronze_puts = requests * WRITES_PER_REQUEST
    acq_low = (bronze_puts + 1) * EXECUTIONS
    acq_high = (bronze_puts + 3) * EXECUTIONS
    reads = EXECUTIONS * (2 * requests + 1)

    assert f"{acq_low + reads + 1} to {acq_high + reads + 2}" in text
    assert "485 to 490" in text


def test_the_deadline_arithmetic_drops_every_head_allowance() -> None:
    """Re-derived from the obligations, and the preserved ceiling stays preserved."""
    text = flat(ADR)
    assert "l >= 3 * t_s3 + c" in text
    assert "remaining >= t_req + 3 * t_s3 + l" in text
    assert "t_req + p + 3 * t_s3 + l <= d" in text
    assert "1,800-second total elapsed acquisition deadline" in text
    assert "the ceiling is not raised" in text


def test_the_adr_rejects_the_weaker_alternative_and_says_why() -> None:
    """Small diffs are not a security argument."""
    text = flat(ADR)
    assert "the application-only alternative is not adopted" in text
    assert "the weaker alternative was never authorized" in text
    assert "is not a substitute for iam least" in text


def test_the_adr_preserves_the_chronology() -> None:
    """The defect was found before it could cost anything, and that is recorded."""
    text = flat(ADR)
    assert "adr-0018 is not rewritten as though the corrected design had always existed" in text
    assert "no infrastructure was built and no run occurred before the discovery" in text


def test_the_adr_makes_no_claim_it_cannot_support() -> None:
    """Both directions of drift, in the spellings each would take."""
    text = flat(ADR)
    for overstated in (
        "adr-0019 is now accepted",
        "adr-0019 has been accepted",
        "adr-0019 is in force",
        "the acquisition role receives s3:getobject",
        "acquisition may use headobject",
        "headobject has its own iam action",
        "s3:headobject is a valid iam action",
        "a 412 establishes identical content",
        "infrastructure is ready to deploy",
        "terraform is authorized",
        "g1 is closed",
        "g2 is closed",
    ):
        assert overstated not in text


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_record_the_feasibility_gap(document: Path) -> None:
    """One file carrying the gap and the other carrying a stale design is the drift."""
    text = flat(document)
    assert "stopped_architecture_gap_head_requires_get" in text
    assert "infrastructure design: blocked pending implementation correction" in text
    assert "headobject requires the s3:getobject permission" in text
    assert "aws exposes no independent s3:headobject iam action" in text


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_record_the_merged_amendment(document: Path) -> None:
    """Inverted on the merge of PR #46, not deleted.

    This required the proposed state while the pull request was open. What must
    now be recorded is the acceptance **and** the historical fact that the
    amendment carried no authority before it -- both, because dropping the
    second would rewrite those days.
    """
    text = flat(document)
    assert "adr-0019: accepted / in force" in text
    assert "adr-0019 architecture: accepted / in force" in text
    assert MERGE_COMMIT in text
    assert APPROVED_HEAD in text
    assert "2026-09-01t01:01:22z" in text
    assert "adr-0019's conditional acceptance event has occurred" in text
    assert "pr #46 was independently reviewed before its merge" in text
    assert "while pr #46 was open adr-0019 was proposed and carried no authority" in text
    assert (
        "adr-0018's original collision-resolution design and arithmetic governed "
        "before the pr #46 merge" in text
    )
    assert (
        "the merge approved architecture only, and authorized no production-code correction" in text
    )


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_record_the_selected_direction(document: Path) -> None:
    """The direction chosen is the one that keeps the boundary, and it is named."""
    text = flat(document)
    assert "the acquisition role receives no s3:getobject" in text
    assert "acquisition headobject: exactly 0" in text
    assert "acquisition getobject: exactly 0" in text
    assert "every acquisition-side conditional putobject collision fails closed" in text
    assert "bronze_name_occupied is the authoritative architectural closed outcome" in text
    assert (
        "locator_name_occupied is the authoritative architectural replacement for the "
        "earlier collision claim" in text
    )
    assert "a partial locator cannot claim the collided object was verified or retained" in text
    assert "the closed result remains locator_not_published" in text
    assert "both the iam boundary and the application boundary are retained" in text
    assert "the application-only alternative is not adopted" in text


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_keep_every_operational_gate_closed(document: Path) -> None:
    """A blocked design is not a smaller permission. It is no permission."""
    text = flat(document)
    for gate in (
        "production implementation correction: not authorized / not implemented",
        "terraform/iam implementation: not authorized / not implemented",
        "deployment: not authorized / not performed",
        "infrastructure mutation: not authorized / not performed",
        "run a: not authorized / not run",
        "run b: not authorized / not run",
        "combined assessment: not authorized / not run",
        "new qualification iam roles zero -- none exists",
        "no infrastructure was built and no run occurred before the discovery",
    ):
        assert gate in text


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_do_not_overstate_the_amendment(document: Path) -> None:
    """Both directions of drift: reverting the merge, and reading it as built."""
    text = flat(document)
    for overstated in (
        "adr-0019 is still proposed",
        "adr-0019 has not merged",
        "adr-0019: proposed / not in force",
        "pr #46 is open",
        "the acquisition role receives s3:getobject",
        "acquisition may use headobject",
        "s3:headobject is a valid iam action",
        "a 412 establishes identical content",
        "infrastructure is ready to deploy",
        "the write-only publication surface exists",
        "the production implementation conforms",
        "the production-code correction is implemented",
        "the feasibility gap is resolved",
        "the architecture gap is closed",
        "the assessment envelope changed",
    ):
        assert overstated not in text


def test_the_implementation_plan_records_the_gap_and_the_proposal() -> None:
    """The plan is where the ceilings are read from."""
    text = flat(PLAN)
    assert "stopped_architecture_gap_head_requires_get" in text
    assert "infrastructure design: blocked pending implementation correction" in text
    assert "adr-0019 architecture: accepted / in force" in text
    assert "while pr #46 was open adr-0019 was proposed and carried no authority" in text
    assert "the production implementation does not yet conform to that architecture" in text
    assert "acquisition putobject: 145 to 147" in text


def test_the_implementation_plan_separates_the_clarification_from_the_merge() -> None:
    """The PR #45 wording observation, corrected rather than carried forward.

    "Implementation ... remains NOT AUTHORIZED" read as a present-state claim in a
    paragraph that had just recorded the implementation merging. What PR #42
    conferred and what PR #41 later did are two facts, and they are kept apart.
    """
    text = flat(PLAN)
    assert "the pr #42 clarification merge conferred no implementation authority" in text
    assert (
        "the offline implementation later merged dormant through pr #41, but its execution and "
        "deployment remain unauthorized" in text
    )


def test_this_proposal_changed_no_production_code() -> None:
    """The shared store keeps its collision resolution, because ADR-0017 relies on it.

    ADR-0019 requires a *later* correction to introduce a separate write-only
    surface. It does not perform that correction, and the proof is that the shared
    store still has the method the correction would route around.
    """
    store = SHARED_STORE.read_text(encoding="utf-8")
    assert "def head_object" in store
    assert "_resolve_occupied" in store


# ---------------------------------------------------------------------------
# The contextual retirement of ADR-0018's original arithmetic
#
# The independent review of PR #47 stopped on STOPPED_STATUS_ARITHMETIC_CONFLICT.
# Both status documents recorded that ADR-0018's acquisition figures no longer
# govern, and both still carried those figures unlabelled in the detailed
# ADR-0018 narrative -- so one file held `remaining >= T_req + 6 * T_s3 + L` and
# `remaining >= T_req + 3 * T_s3 + L`, and `485 to 780` and `485 to 490`, three
# hundred lines apart with nothing saying which governed.
#
# A retirement sentence somewhere in a file is not contextualisation of an
# occurrence somewhere else in it. These tests hold the scanner to that, and
# prove it is not passing vacuously.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_contextualise_every_retired_figure(document: Path) -> None:
    """Nothing retired stands as current prose in either status document."""
    scan = GUARD.scan_retired_arithmetic(document.read_text(encoding="utf-8"))
    assert scan.balanced, "an unclosed or nested marker would make this scan vacuous"
    assert scan.blocks >= GUARD.RETIRED_ARITHMETIC_BLOCKS
    rendered = ", ".join(f"line {number}: {label}" for number, label in scan.findings)
    assert not scan.findings, f"retired arithmetic presented as current: {rendered}"


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_stripping_the_markers_reintroduces_the_finding(document: Path) -> None:
    """The mutation proof: the pass above is the labels' doing, not the scanner's silence.

    The real document is read, its delimiters are removed **in memory**, and the
    scan is required to report the defect the review found. Nothing on disk is
    touched.
    """
    text = document.read_text(encoding="utf-8")
    stripped = "\n".join(
        line
        for line in text.splitlines()
        if "retired-arithmetic begin" not in line.lower()
        and "retired-arithmetic end" not in line.lower()
    )
    scan = GUARD.scan_retired_arithmetic(stripped)
    assert scan.blocks == 0
    found = {label for _, label in scan.findings}
    assert "the 6 x T_s3 per-request allowance" in found
    assert "the 485-to-780 package envelope" in found
    assert "the 0-to-145 conditional HeadObject range" in found


def test_an_unlabelled_retired_deadline_formula_is_caught() -> None:
    """The two sub-budget terms ADR-0019 replaced with `3 * T_s3`."""
    found = _labels(
        "The reserve must cover `4 * T_s3 + C`.\n"
        "per-request admission:  remaining >= T_req + 6 * T_s3 + L\n"
    )
    assert found == [
        "the 4 x T_s3 locator allowance",
        "the 6 x T_s3 per-request allowance",
    ]


def test_an_unlabelled_retired_package_envelope_is_caught() -> None:
    """Both spellings, because the two documents use both."""
    assert _labels("whole empirical package    485 to 780 S3 operations") == [
        "the 485-to-780 package envelope"
    ]
    assert _labels("its `485\u2013780` package envelope") == ["the 485-to-780 package envelope"]
    assert _labels("two acquisition runs       290 to 584 S3 operations") == [
        "the 290-to-584 two-run total"
    ]


def test_an_unlabelled_retired_headobject_count_is_caught() -> None:
    """The range ADR-0019 replaced with exactly zero."""
    assert _labels("conditional HeadObject   0 to 145 -- only after a 412") == [
        "the 0-to-145 conditional HeadObject range"
    ]
    assert _labels("ADR-0018's `zero to 145` conditional HeadObject range") == [
        "the zero-to-145 conditional HeadObject range"
    ]
    assert _labels("total S3 operations      145 to 290") == ["the 145-to-290 per-run total"]
    assert _labels("maximum S3 operations    147 to 292") == ["the 147-to-292 per-run total"]


def test_a_labelled_historical_occurrence_is_allowed() -> None:
    """Both permitted contexts, because the documents need both.

    A delimited block is the general mechanism. The same-line marker exists for
    the ADR-0018 registry row, which is a table row an HTML comment cannot wrap
    without breaking the table.
    """
    retired = "total S3 operations 145 to 290 and whole empirical package 485 to 780"
    assert _labels(retired)
    assert _labels(f"{BEGIN}\n{retired}\n{END}") == []
    assert _labels(f"{retired} -- ADR-0018's original arithmetic, which no longer govern") == []


def test_the_governing_adr_0019_arithmetic_is_not_flagged() -> None:
    """A guard that refused the corrected figures would force the defect back."""
    governing = "\n".join(
        (
            "locator terminal reserve      L >= 3 * T_s3 + C",
            "per-request S3 obligation     3 * T_s3",
            "feasibility                   T_req + P + 3 * T_s3 + L <= D",
            "admission                     remaining >= T_req + 3 * T_s3 + L",
            "acquisition PutObject: 145 to 147",
            "two successful runs: 290 to 294",
            "assessment: unchanged at 195 to 196",
            "whole successful package: 485 to 490",
            "total GetObject          E x (2R + 1) = 194",
            "merge commit 77974f476ead96548beb16543dfd3db8c03232c3",
        )
    )
    assert _labels(governing) == []


def test_a_current_zero_head_claim_is_not_the_retired_range() -> None:
    """Exactly-zero and zero-to-145 share a word and mean opposite things."""
    assert _labels("acquisition HeadObject: exactly 0") == []
    assert _labels("acquisition GetObject: exactly 0") == []
    assert _labels("report PutObject 1 -- NOT retried    conditional HeadObject  0 to 1") == []
    assert _labels("conditional HeadObject zero to 145") == [
        "the zero-to-145 conditional HeadObject range"
    ]


def test_a_supersession_explanation_needs_its_own_context() -> None:
    """Naming a retired figure to explain it is still naming it.

    The same-line marker set is strict on purpose: the whole-package paragraph
    already contained "the superseded canonical arithmetic is gone", which is
    about a different supersession entirely, and a loose "superseded" marker
    would have admitted the retired envelope beside it.
    """
    explanation = "its `145 to 290` and `147 to 292` per-run totals, its `485 to 780` envelope"
    assert _labels(explanation)
    assert _labels(f"{explanation}. The superseded canonical arithmetic is gone.")
    assert _labels(f"{BEGIN}\n{explanation}\n{END}") == []


def test_an_unbalanced_marker_is_refused_rather_than_believed() -> None:
    """An unclosed BEGIN swallows the file, so emptiness must not read as cleanliness."""
    retired = "total S3 operations 145 to 290"
    swallowed = GUARD.scan_retired_arithmetic(f"{BEGIN}\n{retired}\n")
    assert swallowed.findings == ()
    assert not swallowed.balanced
    assert not GUARD.scan_retired_arithmetic(f"{retired}\n{END}\n").balanced
    assert not GUARD.scan_retired_arithmetic(f"{BEGIN}\n{BEGIN}\n{retired}\n{END}\n").balanced


def test_the_scan_carries_nothing_between_documents() -> None:
    """Each document is scanned on its own text, in either order."""
    clean = f"{BEGIN}\ntotal S3 operations 145 to 290\n{END}"
    dirty = "total S3 operations 145 to 290"
    assert _labels(dirty) and _labels(clean) == []
    assert _labels(clean) == [] and _labels(dirty)
