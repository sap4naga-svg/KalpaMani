"""ADR-0019 is a PROPOSAL, and the repository has to keep saying so.

ADR-0018 accepted two requirements that AWS cannot both satisfy: the acquisition
role was granted a metadata-only collision resolution and denied object-byte
reads, and AWS authorizes ``HeadObject`` with ``s3:GetObject`` and publishes no
metadata action of its own. ADR-0019 proposes keeping the security boundary and
removing the operation.

A proposal drifts in two directions, and both are guarded here:

1. **Upward** -- a proposal reading itself as accepted, or a corrected design
   reading itself as built. ADR-0019 has no authority until its pull request
   merges, so ADR-0018's accepted arithmetic is still the arithmetic that
   governs, and every operational gate stays shut.
2. **Downward** -- the security boundary quietly reverting to the weaker
   application-only reading that ADR-0019 declines. Granting the read action
   would let a compromised credential-holding process read known licensed
   objects, which is exactly the argument ADR-0018 s10.3 rests its two-role
   split on.

**The arithmetic is derived here, not transcribed.** A number copied from prose
into prose is a number nobody checks, so the acquisition totals are recomputed
from the inventory and compared against what the ADR says.

These are text and structure checks over committed files. **Nothing here contacts
AWS, a provider or a network**, and nothing here imports an operational entry
point.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ADR = PROJECT_ROOT / "docs" / "decisions" / "ADR-0019-write-only-acquisition-collision-policy.md"
CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"
README = PROJECT_ROOT / "README.md"
PLAN = PROJECT_ROOT / "docs" / "phase3" / "implementation-plan.md"
SHARED_STORE = PROJECT_ROOT / "src" / "kalpamani" / "data" / "storage" / "s3.py"

#: The accepted ADR-0018 inventory the corrected arithmetic is derived from.
SUBJECTS = 8
DATASETS = 3
PAGES = 2
WRITES_PER_REQUEST = 3
EXECUTIONS = 2


def flat(path: Path) -> str:
    """Whitespace-collapsed, emphasis-stripped, lowercased -- the audit's own reading."""
    return " ".join(path.read_text(encoding="utf-8").replace("**", "").split()).lower()


def test_the_adr_exists_and_is_proposed() -> None:
    """A proposal that read itself as accepted would claim an unmerged authority."""
    text = flat(ADR)
    assert (
        "no authority until the pull request introducing it is independently reviewed and merged"
        in text
    )
    assert "adr-0018 as accepted is what governs" in text


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
    assert "infrastructure design and deployment: blocked" in text
    assert "headobject requires the s3:getobject permission" in text
    assert "aws exposes no independent s3:headobject iam action" in text


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_record_the_proposal_as_proposed(document: Path) -> None:
    """A proposal recorded as in force would grant an authority no merge conferred."""
    text = flat(document)
    assert "adr-0019: proposed / not in force" in text
    assert "adr-0019 carries no authority until the pull request introducing it is merged" in text
    assert "adr-0018 as accepted is what governs" in text
    assert "proposed, not in force -- acquisition" in text


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_record_the_selected_direction(document: Path) -> None:
    """The direction chosen is the one that keeps the boundary, and it is named."""
    text = flat(document)
    assert (
        "the selected direction is the iam-preserving acquisition zero-head fail-closed design"
        in text
    )
    assert "the acquisition role receives no s3:getobject" in text
    assert "acquisition headobject invocations are zero" in text
    assert "acquisition object-byte reads are zero" in text
    assert "the acquisition collision fails closed without comparison" in text
    assert "both the iam boundary and the application boundary are retained" in text
    assert "the application-only alternative is not adopted" in text


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_keep_every_operational_gate_closed(document: Path) -> None:
    """A blocked design is not a smaller permission. It is no permission."""
    text = flat(document)
    for gate in (
        "production implementation correction: not authorized / not implemented",
        "terraform and iam implementation: not authorized / not implemented",
        "infrastructure mutation: not authorized / not performed",
        "run a: not authorized / not run",
        "run b: not authorized / not run",
        "combined assessment: not authorized / not run",
        "new qualification iam roles zero -- none exists",
        "no infrastructure was built and no run occurred before the discovery",
    ):
        assert gate in text


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_do_not_overstate_the_proposal(document: Path) -> None:
    """The upward drift, in the spellings it would take."""
    text = flat(document)
    for overstated in (
        "adr-0019 is now accepted",
        "adr-0019 has been accepted",
        "adr-0019 is in force",
        "adr-0019: accepted",
        "the acquisition role receives s3:getobject",
        "acquisition may use headobject",
        "s3:headobject is a valid iam action",
        "a 412 establishes identical content",
        "infrastructure is ready to deploy",
        "the feasibility gap is resolved",
        "the architecture gap is closed",
        "the assessment envelope changed",
    ):
        assert overstated not in text


def test_the_implementation_plan_records_the_gap_and_the_proposal() -> None:
    """The plan is where the ceilings are read from."""
    text = flat(PLAN)
    assert "stopped_architecture_gap_head_requires_get" in text
    assert "infrastructure design and deployment: blocked" in text
    assert "adr-0019 carries no authority until the pull request introducing it is merged" in text
    assert "adr-0018's accepted arithmetic remains the in-force arithmetic" in text
    assert "iam-preserving acquisition zero-head fail-closed design" in text


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
