"""ADR-0020 is ACCEPTED as ARCHITECTURE, and every guard here holds it to exactly that.

PR #48 implemented ADR-0019's fail-closed write-only collision rule correctly and
offline, and in doing so exposed a pre-existing incompatibility between three
separately accepted clauses: a complete acquisition run is a fixed 48 requests
and 144 Bronze writes, the qualification payload object is content-addressed by
``(provider, dataset, digest)``, and an acquisition-side 412 fails closed without
reading or comparing the occupied object. Two legitimate byte-identical
observations therefore derive one object name and halt a correct run.

ADR-0020 fixes the **name**, not the write. PR #49 merged it, so its conditional
effectiveness event has occurred and its architecture is in force -- and the
implementation is not. Three drifts follow from that, and each is guarded here:

1. **Backwards** -- a merged decision read as still proposed. ADR-0020 is
   registered in ``MERGED_ADR_STATUS`` as ``PR #49 merged``, exactly once, and
   neither status document may revert to the pre-merge wording. The conditional
   status line inside the ADR is **preserved as history** and is not forbidden.
2. **Sideways** -- the identity fix used as cover for relaxing the collision
   policy. Acquisition stays conditional ``PutObject`` only, with zero object
   reads and zero listing, and no occupied object may be read, compared or
   adopted.
3. **Forwards** -- a merged offline implementation read as a deployed one. The
   qualification payload-key builder now exists and PR #48 is merged, under a
   separate later authorization; nothing is deployed, nothing has run, and no
   infrastructure or IAM role exists.

**Backwards has a second half now.** PR #48 merged the production-code correction,
so the six spellings of "not implemented" that this file used to require became
false, and the eight that it used to forbid became true. Each was inverted rather
than dropped -- the superseded spelling moved into the denylist -- so a revert to
"still uncorrected" fails, and so does a claim that the merge deployed anything.

**The arithmetic is derived here, not transcribed.** A number copied from prose
into prose is a number nobody checks, so the request count, the write count and
every envelope are recomputed from the accepted inventory and compared against
what the ADR says.

**Every guard has a mutation test behind it.** A required phrase that no edit can
remove is a phrase that proves nothing, so each load-bearing clause is deleted or
inverted in a copy of the real document and the guard is required to notice. The
registry mutations drive the audit's **own** functions over a mutated registry
rather than a local dictionary, because a dictionary compared against itself is
not a check.

These are text and structure checks over committed files. **Nothing here contacts
AWS, a provider or a network**, and nothing here imports an operational entry
point.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ADR = (
    PROJECT_ROOT
    / "docs"
    / "decisions"
    / "ADR-0020-request-scoped-qualification-payload-identity.md"
)
CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"
README = PROJECT_ROOT / "README.md"
PLAN = PROJECT_ROOT / "docs" / "phase3" / "implementation-plan.md"
SHARED_STORE = PROJECT_ROOT / "src" / "kalpamani" / "data" / "storage" / "s3.py"
SHARED_BRONZE = PROJECT_ROOT / "src" / "kalpamani" / "data" / "ingest" / "publication.py"
AUDIT = PROJECT_ROOT / "scripts" / "phase3_docs_audit.py"

#: The accepted ADR-0018 inventory every envelope below is derived from.
SUBJECTS = 8
DATASETS = 3
PAGES = 2
WRITES_PER_REQUEST = 3
LOCATOR_PUT_MIN = 1
LOCATOR_PUT_MAX = 3
EXECUTIONS = 2
REPORT_PUT = 1
REPORT_HEAD_MAX = 1

#: The pull request the proposal, and its merge, must leave alone.
BLOCKED_PR = "#48"

#: The pull request that merged ADR-0020.
MERGED_PR = "#49"


def _audit_module() -> ModuleType:
    """Load the audit by path, to *run* its scanners rather than restate them.

    ``scripts`` is not an importable package. The module is registered in
    ``sys.modules`` before execution because the audit defines a ``@dataclass``,
    and ``dataclasses`` resolves the defining module through that entry rather
    than through the object it is handed.

    Importing it defines constants and functions. It runs no check, opens no
    socket and reaches no service -- ``main()`` is behind the usual guard, and the
    module is loaded under a name that is not ``__main__``.
    """
    spec = importlib.util.spec_from_file_location("kalpamani_phase3_docs_audit", AUDIT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GUARD = _audit_module()

#: The merge that carried the production-code correction, and the head approved
#: for it. Read from the audit rather than restated here, so a test cannot
#: disagree with the guard about which commit is the one under discussion.
IMPL_MERGE_COMMIT: Final[str] = GUARD.ADR_0019_IMPL_MERGE_COMMIT
IMPL_APPROVED_HEAD: Final[str] = GUARD.ADR_0019_IMPL_APPROVED_HEAD


def flat(text: str) -> str:
    """Whitespace-collapsed, emphasis-stripped, lowercased -- the audit's own reading."""
    return " ".join(text.replace("**", "").split()).lower()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def missing(required: Iterable[tuple[str, str]], text: str) -> list[str]:
    """Every required clause the text does not carry, by label."""
    reading = flat(text)
    return [label for label, phrase in required if phrase not in reading]


def overstated(forbidden: Iterable[str], text: str) -> list[str]:
    """Every forbidden claim the text does carry."""
    reading = flat(text)
    return [claim for claim in forbidden if claim in reading]


def clause(label: str, required: Iterable[tuple[str, str]]) -> str:
    """The exact phrase a labelled requirement is asserting, read from the audit.

    Read rather than restated: a mutation test that deleted its own copy of a
    phrase would prove nothing about the phrase the audit actually looks for.
    """
    for candidate, phrase in required:
        if candidate == label:
            return phrase
    raise AssertionError(f"no requirement labelled {label!r}")


def _status_documents() -> dict[str, str]:
    """Both current-status documents, keyed the way the audit keys them."""
    return {"CLAUDE.md": read(CLAUDE_MD), "README.md": read(README)}


def audit_registry() -> tuple[tuple[str, str], ...]:
    """``MERGED_ADR_STATUS`` read by static parse.

    Parsed rather than imported from the loaded module, so the registry this
    checks is the one committed in the file rather than one a later import could
    rebind.
    """
    tree = ast.parse(read(AUDIT))
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


# ---------------------------------------------------------------------------
# The proposal, and what it refuses to claim
# ---------------------------------------------------------------------------


def test_the_adr_preserves_its_conditional_status_line() -> None:
    """A decision record is not rewritten when the world moves.

    The conditional line is what the ADR said while PR #49 was open, so it stays
    exactly as written. The post-merge note beside it is what stops that line
    from being read as current.
    """
    assert ADR.is_file(), "the payload-identity amendment must be the file it names"
    reading = flat(read(ADR))
    assert "status: proposed" in reading
    assert (
        "no authority until the pull request introducing it is independently reviewed and merged"
        in reading
    )
    assert "preserved as history, not rewritten" in reading


def test_the_adr_carries_the_adjacent_post_merge_note() -> None:
    """Added on the merge, not substituted for the line above it."""
    reading = flat(read(ADR))
    assert "the condition above has since been satisfied" in reading
    assert GUARD.ADR_0020_MERGE_COMMIT in reading
    assert GUARD.ADR_0020_APPROVED_HEAD in reading
    assert "adr-0020's conditional effectiveness event has occurred" in reading
    assert "adr-0020 architecture: accepted / in force" in reading
    assert "this section is a historical note added after the" in reading


def test_the_adr_keeps_the_proposed_period_historical() -> None:
    """The pre-merge period is a fact about those days, not a claim about today."""
    reading = flat(read(ADR))
    assert GUARD.ADR_0020_HISTORICAL_PROPOSED in reading
    assert (
        "adr-0018 as amended by adr-0019 governed the qualification payload identity before the "
        f"pr {MERGED_PR} merge" in reading
    )


def test_the_merge_approved_architecture_only() -> None:
    """Acceptance of a design is not permission to build it."""
    reading = flat(read(ADR))
    assert (
        "the merge approved architecture only, and authorized no implementation, no "
        "infrastructure mutation, no deployment and no execution" in reading
    )
    assert "acceptance of adr-0020 is not authorization to implement or execute it" in reading


def test_the_adr_records_the_merged_implementation_and_the_closed_gates() -> None:
    """Architecture accepted, implementation merged, nothing deployed -- three states.

    Inverted on the PR #48 merge, not deleted. While the correction was outstanding
    this required "not authorized / not implemented" and refused the claim that the
    identity was implemented; both are now the other way round, and the spellings
    they replaced are refused by :data:`ADR_0020_SELF_FORBIDDEN` below.
    """
    reading = flat(read(ADR))
    assert "adr-0020 implementation: merged / dormant / offline-conforming" in reading
    assert "a qualification payload-key builder exists" in reading
    assert (
        "the current dormant implementation is offline-conforming under the authoritative "
        "architecture" in reading
    )
    assert "the adr-0020 implementation-correction prerequisite is satisfied" in reading
    # Merged is not deployed, and the ADR has to say so in the same breath.
    assert (
        "merging an implementation authorizes no infrastructure, no deployment and no run"
        in reading
    )
    assert (
        "offline-conforming is not deployed, not active, not operational, not authorized to run "
        "and not empirically validated" in reading
    )
    assert "adr-0020 implementation: not authorized / not implemented" not in reading
    assert "no qualification payload-key builder exists" not in reading
    assert "the request-scoped payload identity is deployed" not in reading


def test_the_adr_keeps_the_pre_correction_period_historical() -> None:
    """The days before the correction merged are a fact, and §1-§8 are not rewritten.

    §8 records PR #48 as open and uncorrected because that is what it was when this
    ADR was proposed and reviewed. §9 carries the current state. Both, because
    deleting either is how a record stops being able to show that anything moved.
    """
    reading = flat(read(ADR))
    assert f"before pr {BLOCKED_PR} merged no qualification payload-key builder existed" in reading
    assert (
        f"pr {BLOCKED_PR} is open, non-draft, unmerged, blocked on architecture, and untouched by "
        "this proposal" in reading
    ), "§8's proposal-time record stays unedited"
    assert f"pr {BLOCKED_PR} was untouched by this decision and by its merge" in reading


def test_the_registry_records_adr_0020_as_merged() -> None:
    """Inverted on the merge, not deleted.

    While PR #49 was open this asserted ADR-0020 was **absent** from the registry.
    The merge is the event that flips it, and deleting the guard would leave the
    reverted claim unguarded.
    """
    registry = audit_registry()
    assert dict(registry).get("ADR-0020") == f"PR {MERGED_PR} merged"
    assert [adr for adr, _ in registry].count("ADR-0020") == 1
    assert dict(registry).get("ADR-0019") == "PR #46 merged", (
        "the merged neighbour stays registered"
    )


def test_the_adr_names_the_legitimate_duplicate_byte_collision() -> None:
    """The conflict is named, and named as legitimate rather than as a defect."""
    reading = flat(read(ADR))
    assert "the legitimate duplicate-payload collision" in reading
    assert "header-only" in reading
    assert "an unchanged snapshot re-observed in run b" in reading
    assert f"pr {BLOCKED_PR} is not defective for obeying adr-0019" in reading
    assert (
        "this is an identity and key-contract problem. it is not a reason to weaken write-only "
        "acquisition." in reading
    )


def test_the_adr_binds_all_three_identity_inputs() -> None:
    """Execution identity, request ordinal and payload digest -- all three, or none."""
    reading = flat(read(ADR))
    for token in ("execution_identity", "request_ordinal", "payload_sha256_digest"):
        assert token in reading, token
    assert "all three bindings must be preserved" in reading
    assert "a different execution identity produces a different key" in reading
    assert "a different request ordinal produces a different key" in reading
    assert "different payload bytes produce a different digest and a different key" in reading
    assert "a retry of the same publication attempt targets the same key" in reading
    assert "there is no random suffix" in reading


def test_the_ordinal_cannot_come_from_the_provider() -> None:
    """An ordinal a response could influence is an ordinal an attacker could choose."""
    reading = flat(read(ADR))
    assert "the deterministic ordinal from the locked 48-request inventory" in reading
    assert "cannot be supplied freely by the provider" in reading


def test_the_adr_keeps_private_request_values_out_of_every_key() -> None:
    """A key is not private. A subject name in one is a subject name in every listing."""
    reading = flat(read(ADR))
    assert (
        "no provider subject, ticker, date range, api path, credential, bucket, account, owner "
        "name or other private request value" in reading
    )


def test_the_adr_exposes_no_subject_shaped_literal_in_a_sample_key() -> None:
    """A worked example is where a real ticker gets typed in while nobody is looking."""
    leaked = GUARD._sample_key_subject_segments(read(ADR))
    assert not leaked, f"subject-shaped segments in sample keys: {sorted(set(leaked))}"


# ---------------------------------------------------------------------------
# ADR-0019, preserved exactly
# ---------------------------------------------------------------------------


def test_the_adr_preserves_conditional_put_only_acquisition() -> None:
    """The identity changes. The collision policy does not."""
    reading = flat(read(ADR))
    assert "acquisition performs conditional `putobject` only" in reading
    assert "a 412 establishes neither identical nor different content" in reading
    assert "no compare, adopt, resume or deduplicate behaviour exists" in reading
    assert "it does not relax collision handling" in reading
    assert "it does not supersede adr-0019's write-only collision policy" in reading


def test_the_adr_preserves_zero_acquisition_reads_and_zero_listing() -> None:
    """Every read-shaped operation is denied by name, because AWS authorizes them as one."""
    reading = flat(read(ADR))
    for denial in (
        "acquisition performs no `headobject`",
        "acquisition performs no `getobject`",
        "acquisition performs no `getobjectattributes`",
        "acquisition performs no s3 listing",
        "no list operation and no preflight existence check is introduced",
    ):
        assert denial in reading, denial


def test_the_adr_preserves_both_occupied_name_outcomes() -> None:
    """The closed vocabulary ADR-0019 settled on is carried forward unrenamed."""
    reading = flat(read(ADR))
    assert "bronze_name_occupied" in reading
    assert "locator_name_occupied" in reading
    assert "an ambiguous write followed by a 412 remains a safe-direction false negative" in reading
    assert "no occupied object is counted as retained or verified evidence" in reading


# ---------------------------------------------------------------------------
# Arithmetic, derived rather than transcribed
# ---------------------------------------------------------------------------


def test_the_acquisition_arithmetic_is_derived_not_transcribed() -> None:
    """Recomputed from the accepted inventory, then compared with what the ADR says."""
    requests = SUBJECTS * DATASETS * PAGES
    bronze = requests * WRITES_PER_REQUEST
    low = bronze + LOCATOR_PUT_MIN
    high = bronze + LOCATOR_PUT_MAX
    reading = flat(read(ADR))
    assert requests == 48
    assert f"exactly {requests} requests" in reading
    assert f"exactly {bronze} bronze" in reading
    assert f"bronze putobject: exactly {bronze}" in reading
    assert f"total putobject: {low} to {high}" in reading
    assert f"{low * EXECUTIONS} to {high * EXECUTIONS}" in reading


def test_the_package_envelope_is_derived_not_transcribed() -> None:
    """485 to 490 is two acquisition runs plus one combined assessment, and nothing else."""
    requests = SUBJECTS * DATASETS * PAGES
    bronze = requests * WRITES_PER_REQUEST
    run_low, run_high = bronze + LOCATOR_PUT_MIN, bronze + LOCATOR_PUT_MAX
    reads = EXECUTIONS * (2 * requests + 1)
    assess_low = reads + REPORT_PUT
    assess_high = reads + REPORT_PUT + REPORT_HEAD_MAX
    package_low = run_low * EXECUTIONS + assess_low
    package_high = run_high * EXECUTIONS + assess_high
    assert (reads, assess_low, assess_high) == (194, 195, 196)
    assert (package_low, package_high) == (485, 490)
    reading = flat(read(ADR))
    assert f"{assess_low} to {assess_high} total" in reading
    assert f"{package_low} to {package_high}" in reading
    assert "the new key identity introduces no additional operation" in reading


def test_the_adr_preserves_the_adr_0019_deadline_arithmetic() -> None:
    """The per-request obligation is the three Bronze writes, and nothing was re-inflated."""
    obligation = f"{WRITES_PER_REQUEST} * t_s3"
    reading = flat(read(ADR))
    assert "d = 1800 seconds" in reading
    assert f"l >= {obligation} + c" in reading
    assert f"per-request s3 obligation = {obligation}" in reading
    assert f"t_req + p + {obligation} + l <= d" in reading
    assert f"remaining >= t_req + {obligation} + l" in reading
    assert "6 * t_s3" not in reading, "the retired per-request allowance must not return"
    assert "4 * t_s3" not in reading, "the retired locator allowance must not return"


# ---------------------------------------------------------------------------
# Integrity, isolation and the durable schema
# ---------------------------------------------------------------------------


def test_the_adr_requires_key_reconstruction_and_exact_comparison() -> None:
    """A recorded key nobody rebuilds is a key anybody can write."""
    reading = flat(read(ADR))
    assert "the expected qualification payload key is deterministically reconstructed" in reading
    assert "the recorded payload key exactly equals the reconstructed key" in reading
    assert "do not treat the key name alone as integrity proof" in reading


def test_the_adr_preserves_assessment_digest_recomputation() -> None:
    """The bytes are what the digest is about, and they are hashed again on the way in."""
    reading = flat(read(ADR))
    assert "sha-256 is recomputed over the retrieved payload bytes" in reading
    assert "the recomputed digest exactly equals the durable digest" in reading
    assert "any mismatch fails closed before parsing or evaluation" in reading
    assert "read only by the separately authorized assessment role and process" in reading


def test_the_adr_introduces_no_locator_field() -> None:
    """A new durable field would be a schema change nobody authorized."""
    reading = flat(read(ADR))
    assert "no new locator field is introduced" in reading
    assert "no private subject value is introduced" in reading
    assert "no additional s3 read is introduced" in reading
    assert "no s3 list is introduced" in reading
    assert "no provider request is introduced" in reading
    assert (
        "the merged durable record already carries enough to reconstruct the new key, so no new "
        "field is required" in reading
    )
    assert "no migration is authorized or needed" in reading


def test_the_adr_changes_no_shared_bronze_or_store_contract() -> None:
    """Production ingestion is not qualification, and keeps the namespace it was accepted with."""
    reading = flat(read(ADR))
    assert (
        "it does not modify the shared general-purpose bronze or `s3researchobjectstore` contract"
        in reading
    )
    assert "not change the shared general-purpose `bronze_payload_key`" in reading
    assert "not change `s3researchobjectstore`" in reading
    assert "do not generalize this choice to ingestion or control storage" in reading


def test_the_adr_changes_no_adr_0017_behaviour() -> None:
    """ADR-0017 publishes through the shared store and must not learn about this key."""
    reading = flat(read(ADR))
    assert "it does not supersede adr-0017" in reading
    assert "not change adr-0017 publication behaviour" in reading
    assert "structurally unreachable from adr-0017" in reading
    assert "it must stop for a new architecture decision" in reading


def test_the_same_execution_and_ordinal_case_admits_one_observation_only() -> None:
    """Two competing payloads for one governed request are never one complete observation."""
    reading = flat(read(ADR))
    assert (
        "must not permit two competing payloads for one governed request to be accepted as a "
        "complete observation" in reading
    )
    assert "bind only the single governed terminal outcome" in reading


def test_the_adr_records_its_costs() -> None:
    """A trade-off nobody wrote down is a trade-off the next reader has to rediscover."""
    reading = flat(read(ADR))
    assert "qualification payloads are no longer globally deduplicated by payload digest" in reading
    assert "identical bytes may be stored more than once" in reading
    assert "maximum 96 qualification payload objects" in reading


# ---------------------------------------------------------------------------
# What the proposal authorizes: nothing
# ---------------------------------------------------------------------------


def test_the_adr_authorizes_nothing() -> None:
    """Implementation, infrastructure mutation and execution stay three separate gates."""
    reading = flat(read(ADR))
    assert "this adr authorizes nothing" in reading
    assert "it carries no implementation authority and no infrastructure authority" in reading
    assert "it authorizes no deployment" in reading
    assert "it authorizes no run a, no run b and no combined assessment" in reading
    assert "infrastructure remains blocked" in reading


def test_the_adr_records_the_blocked_pull_request_state() -> None:
    """Open, unmerged, blocked and untouched -- all four, and none of them softened."""
    reading = flat(read(ADR))
    assert (
        f"pr {BLOCKED_PR} is open, non-draft, unmerged, blocked on architecture, and untouched by "
        "this proposal" in reading
    )
    assert f"this adr does not make pr {BLOCKED_PR} mergeable" in reading
    assert f"it does not retroactively change the status of pr {BLOCKED_PR}" in reading
    assert (
        f"pr {BLOCKED_PR} cannot be reviewed or merged until this adr is independently reviewed, "
        "merged and synchronized" in reading
    )


def test_the_adr_makes_no_claim_it_cannot_support() -> None:
    """Every forbidden claim is a positive assertion, so an honest negation is not one."""
    claims = overstated(GUARD.ADR_0020_SELF_FORBIDDEN, read(ADR))
    assert not claims, f"ADR-0020 overstates: {claims}"


def test_the_audit_requires_every_clause_this_file_checks() -> None:
    """The two guards agree, so neither can be weakened while the other passes.

    Not a tautology: this compares the *audit's* requirement list against the
    committed ADR, which is the same comparison the audit performs and a
    different one from every phrase asserted above.
    """
    assert not missing(GUARD.ADR_0020_SELF_REQUIRED, read(ADR))
    assert len(GUARD.ADR_0020_SELF_REQUIRED) > 0


# ---------------------------------------------------------------------------
# Both status documents, independently
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_record_the_merged_amendment(document: Path) -> None:
    """Independently, and in ADR-0020's own status section.

    Independently, because merged main has twice carried a fact in one file and
    its contradiction in the other. In the section, because 46 of the 49 clauses
    are spelled elsewhere in the same file as well, so a whole-document reading
    was answered by a neighbouring status block -- see the section-scope block at
    the end of this file.
    """
    absent = missing(GUARD.ADR_0020_STATUS_REQUIRED, split_at_section(document)[1])
    assert not absent, f"{document.name} is missing from its ADR-0020 section: {absent}"


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_record_the_merge_and_its_bounds(document: Path) -> None:
    """The merge, its two commits, and the sentence that keeps the pre-merge period historical."""
    reading = flat(read(document))
    assert f"pr {MERGED_PR}: merged" in reading
    assert GUARD.ADR_0020_MERGE_COMMIT in reading
    assert GUARD.ADR_0020_APPROVED_HEAD in reading
    assert "conditional effectiveness event: occurred" in reading
    assert GUARD.ADR_0020_HISTORICAL_PROPOSED in reading
    assert "the merge approved architecture only" in reading


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_separate_acceptance_from_implementation(document: Path) -> None:
    """The one distinction this whole synchronization exists to keep.

    It used to be *accepted architecture versus absent implementation*. It is now
    *merged offline implementation versus absent infrastructure, deployment and
    execution* -- a different pair, and the same discipline: two states, never one.
    """
    reading = flat(read(document))
    assert "architecture acceptance: complete" in reading
    assert "production implementation: merged / dormant / offline-conforming" in reading
    assert (
        "the architecture blocker that prevented adr-0020 from being authoritative is resolved"
        in reading
    )
    assert "the implementation blocker is resolved as well, offline" in reading
    assert "adr-0018 merged implementation: dormant / offline-conforming" in reading
    # The half that keeps a merged correction from reading as a deployment.
    assert "the adr-0020 implementation-correction prerequisite is satisfied" in reading
    assert (
        "satisfying the implementation prerequisite does not itself authorize or begin "
        "infrastructure work" in reading
    )
    assert "infrastructure design and mutation: not authorized / not implemented" in reading
    assert "terraform / iam: not authorized / not implemented" in reading
    assert "deployment: not performed" in reading
    assert "execution: zero" in reading


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_record_the_merged_correction(document: Path) -> None:
    """Merged, with both commits, under a separate authorization -- and still not deployed.

    Inverted on the merge. The four "open / not begun" clauses this required moved
    into :data:`ADR_0020_STATUS_FORBIDDEN`, so reverting to them fails rather than
    merely going unchecked; the sentence absolving PR #48 of a defect stays, because
    obeying ADR-0019 was never the error.
    """
    reading = flat(read(document))
    assert f"pr {BLOCKED_PR}: merged" in reading
    assert IMPL_MERGE_COMMIT in reading
    assert IMPL_APPROVED_HEAD in reading
    assert f"pr {BLOCKED_PR} correction against adr-0020: merged" in reading
    assert f"pr {BLOCKED_PR} is not defective for obeying adr-0019" in reading
    # Past tense, and exactly true: the proposal and its merge touched nothing. A
    # later, separately authorized correction did.
    assert f"pr {BLOCKED_PR} was untouched by the adr-0020 proposal and by its merge" in reading
    assert (
        f"while pr {BLOCKED_PR} was open it was not ready for review or merge and its correction "
        "had not begun" in reading
    )
    assert (
        "the next possible gate is a separate owner authorization for offline infrastructure"
        in reading
    )


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_do_not_overstate_the_amendment(document: Path) -> None:
    """No document may read an accepted architecture as an implemented one, or revert it."""
    claims = overstated(GUARD.ADR_0020_STATUS_FORBIDDEN, read(document))
    assert not claims, f"{document.name} overstates: {claims}"


@pytest.mark.parametrize(
    "document", [CLAUDE_MD, README, PLAN], ids=["CLAUDE.md", "README.md", "plan"]
)
def test_no_document_says_the_blocked_pull_request_is_ready(document: Path) -> None:
    """The one sentence a reviewer would act on, and the one nobody may write yet."""
    reading = flat(read(document))
    for claim in (
        f"pr {BLOCKED_PR} is ready to merge",
        f"pr {BLOCKED_PR} is mergeable",
        f"pr {BLOCKED_PR} has been corrected",
        f"pr {BLOCKED_PR} is merged",
    ):
        assert claim not in reading, claim


@pytest.mark.parametrize(
    "document", [CLAUDE_MD, README, PLAN], ids=["CLAUDE.md", "README.md", "plan"]
)
def test_no_document_says_the_merged_identity_is_deployed(document: Path) -> None:
    """A built key is not a deployed one, and the forward drift moved one gate along.

    Inverted on the merge: what may not be claimed is no longer *implemented* but
    *deployed, run or validated*, and the three spellings this used to refuse are
    now required facts.
    """
    reading = flat(read(document))
    assert "the request-scoped payload identity is deployed" not in reading
    assert "the qualification payload-key builder is deployed" not in reading
    assert "the production implementation is deployed" not in reading
    assert "adr-0020 implementation: deployed" not in reading
    assert "the implementation has been empirically validated" not in reading
    assert "infrastructure is deployed" not in reading
    assert "adr-0020 implementation: merged / dormant / offline-conforming" in reading


@pytest.mark.parametrize(
    "document", [CLAUDE_MD, README, PLAN], ids=["CLAUDE.md", "README.md", "plan"]
)
def test_no_document_permits_reading_or_adopting_an_occupied_object(document: Path) -> None:
    """The sideways drift: an identity fix used as cover for relaxing the boundary."""
    reading = flat(read(document))
    for claim in (
        "acquisition may read an occupied object",
        "an occupied object may be adopted",
        "identical occupied content may be adopted",
        "acquisition deduplicates objects",
        "acquisition may resolve a collision with headobject",
    ):
        assert claim not in reading, claim


def test_the_implementation_plan_carries_the_same_state() -> None:
    """The plan is where the ceilings are read from, so it carries the same accepted state."""
    absent = missing(GUARD.ADR_0020_PLAN_REQUIRED, read(PLAN))
    assert not absent, f"the implementation plan is missing: {absent}"


def test_the_merged_correction_left_the_shared_surfaces_alone() -> None:
    """The correction routed around the shared surfaces rather than widening them.

    ADR-0020 required a *later* implementation gate to introduce a
    qualification-specific builder, and PR #48 is that gate. The proof that it
    stayed inside its own package: the shared content-addressed builder and the
    shared store's collision resolution are both still here and unchanged, and
    neither has learned the qualification key.

    ADR-0011's store keeps its ``head_object``. ADR-0019 removed the *acquisition
    role's* authority to issue one, not the shared store's collision resolution --
    two different surfaces, and conflating them is how a narrow amendment turns
    into a wide one.
    """
    bronze = read(SHARED_BRONZE)
    store = read(SHARED_STORE)
    assert "def bronze_payload_key" in bronze
    assert '"objects",\n        "sha256",' in bronze, "the shared key is still content-addressed"
    assert "def head_object" in store
    assert "qualification_payload_key" not in bronze
    assert "qualification_payload_key" not in store


def test_the_qualification_key_builder_lives_only_in_the_qualification_package() -> None:
    """The builder exists, and exactly one module defines it.

    The forward half of the isolation proof. A builder that existed in the shared
    namespace would be the widening ADR-0020 explicitly refuses, so this asserts
    both that it is here and that it is only here.
    """
    package = PROJECT_ROOT / "src" / "kalpamani" / "data" / "qualify" / "sharadar"
    definitions = [
        path.name
        for path in sorted(package.glob("*.py"))
        if "def qualification_payload_key(" in read(path)
    ]
    assert definitions == ["publication.py"], definitions

    src = PROJECT_ROOT / "src"
    everywhere = [
        path.relative_to(src).as_posix()
        for path in sorted(src.rglob("*.py"))
        if "def qualification_payload_key(" in read(path)
    ]
    assert everywhere == ["kalpamani/data/qualify/sharadar/publication.py"], everywhere


def test_the_acquisition_path_is_a_second_caller_and_stays_separate() -> None:
    """Exactly two production call sites, and the second cannot reach ADR-0017's.

    The caller-count correction, proved against the tree rather than the prose.
    ADR-0017's caller is still exactly one; the repository has two because the
    dormant ADR-0018 acquisition path merged. The guard is driven, not restated.
    """
    sites = sorted(path.name for path in GUARD._runtime_execute_call_sites())
    assert sites == list(GUARD.RUNTIME_EXECUTE_CALLERS), sites
    assert sites == ["acquisition.py", "composition.py"], sites

    composition = PROJECT_ROOT / "src" / "kalpamani" / "data" / "ingest" / "sharadar"
    executable = GUARD._executable_python(composition / "composition.py")
    assert executable.count(".execute(") == 1, "ADR-0017's path did not grow a second call"

    acquisition = PROJECT_ROOT / "src" / "kalpamani" / "data" / "qualify" / "sharadar"
    assert "assessment" not in GUARD._executable_python(acquisition / "acquisition.py"), (
        "the write-only acquisition path may not reach the assessment read surface"
    )


def test_a_third_production_caller_is_caught() -> None:
    """MUTATION. The permitted caller set is two names, so a third fails.

    Driven over a mutated *result*, not a mutated copy of the constant: the audit's
    comparison is what has to notice, and comparing a list against itself would not
    be a check.
    """
    intruder = [*GUARD.RUNTIME_EXECUTE_CALLERS, "runner.py"]
    assert sorted(intruder) != list(GUARD.RUNTIME_EXECUTE_CALLERS)
    assert len(GUARD.RUNTIME_EXECUTE_CALLERS) == 2, GUARD.RUNTIME_EXECUTE_CALLERS


def test_widening_the_store_builder_set_is_caught() -> None:
    """MUTATION. One module may construct the licensed store, and a second fails."""
    assert list(GUARD.STORE_BUILDERS) == ["composition.py"], GUARD.STORE_BUILDERS
    actual = sorted(path.name for path in GUARD._store_construction_sites())
    assert actual == list(GUARD.STORE_BUILDERS), actual
    widened = sorted([*GUARD.STORE_BUILDERS, "acquisition.py"])
    assert widened != list(GUARD.STORE_BUILDERS), "a second builder must not compare equal"


# ---------------------------------------------------------------------------
# Mutation proofs -- every guard above is load-bearing
#
# Each takes the real committed document, removes or inverts exactly one clause,
# and requires the guard to notice. A guard no edit can break is a guard that
# proves nothing, and a constant compared against itself is not a check.
# ---------------------------------------------------------------------------


def _without(label: str) -> str:
    """The real ADR with one audited clause deleted."""
    phrase = clause(label, GUARD.ADR_0020_SELF_REQUIRED)
    text = read(ADR)
    reading = flat(text)
    assert phrase in reading, f"the clause must be present before it is removed: {phrase}"
    return flat(text).replace(phrase, "")


def test_removing_the_execution_identity_binding_is_caught() -> None:
    mutated = _without("binds the execution identity")
    assert "binds the execution identity" in missing(GUARD.ADR_0020_SELF_REQUIRED, mutated)


def test_removing_the_request_ordinal_binding_is_caught() -> None:
    mutated = _without("binds the request ordinal")
    assert "binds the request ordinal" in missing(GUARD.ADR_0020_SELF_REQUIRED, mutated)


def test_removing_the_payload_digest_binding_is_caught() -> None:
    mutated = _without("binds the payload digest")
    assert "binds the payload digest" in missing(GUARD.ADR_0020_SELF_REQUIRED, mutated)


def test_replacing_write_only_behaviour_with_headobject_resolution_is_caught() -> None:
    """The sideways drift, in the exact spelling a well-meaning edit would use."""
    text = flat(read(ADR)).replace(
        clause("keeps headobject at zero", GUARD.ADR_0020_SELF_REQUIRED),
        "acquisition may use headobject to resolve a collision",
    )
    assert "keeps headobject at zero" in missing(GUARD.ADR_0020_SELF_REQUIRED, text)
    assert "acquisition may use headobject" in overstated(GUARD.ADR_0020_SELF_FORBIDDEN, text)


def test_reverting_a_document_to_the_proposed_state_is_caught() -> None:
    """The backwards drift: a merged decision demoted by a document edit.

    Inverted on the merge. While PR #49 was open this proved an *acceptance*
    claim was caught; the pre-merge spellings moved into the forbidden list on the
    merge, so the same guard now catches the revert.
    """
    for document in (CLAUDE_MD, README):
        for injected in (
            "adr-0020: proposed / not in force",
            "adr-0020 is still proposed",
            "adr-0020 has not merged",
        ):
            mutated = flat(read(document)) + " " + injected
            claims = overstated(GUARD.ADR_0020_STATUS_FORBIDDEN, mutated)
            assert injected in claims, f"{document.name}: {injected}"


def test_the_registry_entry_is_the_one_the_documents_are_measured_against(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact committed tuple, and the exact claim both documents make.

    Not a local dictionary: the entry is read by static parse of the committed
    audit, and the documents' claims are read by the audit's **own** row scanner.
    A registry that agreed only with itself would prove nothing about either.
    """
    assert dict(audit_registry())["ADR-0020"] == f"PR {MERGED_PR} merged"
    for document in (CLAUDE_MD, README):
        claims = GUARD._in_force_adr_claims(read(document))
        assert claims.get("ADR-0020") == f"PR {MERGED_PR} merged", document.name
    monkeypatch.setattr(GUARD, "MERGED_ADR_STATUS", audit_registry())
    assert not GUARD._registry_coverage_defects(_status_documents())


def test_removing_the_registry_entry_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deleting the entry must fail the audit's real coverage check, not merely go unasserted."""
    without = tuple(pair for pair in audit_registry() if pair[0] != "ADR-0020")
    assert len(without) == len(audit_registry()) - 1, "the mutation must actually remove something"
    monkeypatch.setattr(GUARD, "MERGED_ADR_STATUS", without)
    defects = GUARD._registry_coverage_defects(_status_documents())
    assert defects, "an in-force row outside the registry's coverage must be a defect"
    assert all("ADR-0020" in defect for defect in defects), defects


def test_a_wrong_pull_request_number_in_the_registry_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registry naming another pull request must disagree with both documents."""
    wrong = tuple(
        (adr, f"PR {BLOCKED_PR} merged" if adr == "ADR-0020" else merged_in)
        for adr, merged_in in audit_registry()
    )
    assert dict(wrong)["ADR-0020"] != f"PR {MERGED_PR} merged"
    monkeypatch.setattr(GUARD, "MERGED_ADR_STATUS", wrong)
    assert GUARD._registry_coverage_defects(_status_documents())
    for name, body in _status_documents().items():
        assert GUARD._stale_adr_status_defects(name, body), name


def test_a_duplicate_registry_entry_is_caught() -> None:
    """A mapping keeps the last value for a repeated key, so the tuple is what is counted."""
    doubled = (*audit_registry(), ("ADR-0020", f"PR {MERGED_PR} merged"))
    assert GUARD._duplicate_registry_entries(doubled) == ["ADR-0020"]
    assert not GUARD._duplicate_registry_entries(audit_registry()), (
        "the committed registry is clean"
    )


def test_reverting_a_document_to_the_uncorrected_state_is_caught() -> None:
    """The second backwards drift: a merged correction demoted by a document edit.

    Inverted on the merge. While the correction was outstanding this proved a
    *mergeable* claim was caught; those spellings became true, so the pre-merge
    spellings took their place and the same guard now catches the revert.
    """
    for injected in (
        "adr-0020 implementation: not authorized / not implemented",
        "production implementation: not authorized / not implemented",
        "no qualification payload-key builder exists",
        "adr-0018 merged implementation: dormant / nonconforming",
        f"pr {BLOCKED_PR} state: open / unmerged",
        f"pr {BLOCKED_PR} ready for review or merge: no",
        f"pr {BLOCKED_PR} correction against adr-0020: not begun",
        "the implementation blocker remains",
        "infrastructure design and mutation: blocked",
    ):
        mutated = flat(read(CLAUDE_MD)) + " " + injected
        assert injected in overstated(GUARD.ADR_0020_STATUS_FORBIDDEN, mutated), injected


def test_claiming_the_merged_implementation_was_deployed_is_caught() -> None:
    """The forward drift, one gate further along than it used to sit."""
    for injected in (
        "the request-scoped payload identity is deployed",
        "the qualification payload-key builder is deployed",
        "the production implementation is deployed",
        "adr-0020 implementation: deployed",
        "the implementation has been empirically validated",
        "infrastructure is authorized",
        "infrastructure is implemented",
        "infrastructure is deployed",
        "deployment: performed",
        "run a is authorized",
        "run b is authorized",
        "the combined assessment is authorized",
        "phase 3 is complete",
        "live trading is enabled",
    ):
        mutated = flat(read(CLAUDE_MD)) + " " + injected
        assert injected in overstated(GUARD.ADR_0020_STATUS_FORBIDDEN, mutated), injected


def test_a_subject_value_in_a_sample_key_is_caught() -> None:
    """The privacy guard, proved against a synthetic placeholder rather than a real symbol."""
    poisoned = read(ADR) + (
        "\n\nlicensed/bronze/sharadar/stocks/qualification/EXAMPLE/requests/00/sha256/abc\n"
    )
    leaked = GUARD._sample_key_subject_segments(poisoned)
    assert "EXAMPLE" in leaked
    assert not GUARD._sample_key_subject_segments(read(ADR)), "the committed ADR stays clean"


def test_a_retired_package_envelope_is_caught() -> None:
    """Reverting the envelope to ADR-0018's original figure must fail the derived check."""
    requests = SUBJECTS * DATASETS * PAGES
    bronze = requests * WRITES_PER_REQUEST
    reads = EXECUTIONS * (2 * requests + 1)
    package_low = (bronze + LOCATOR_PUT_MIN) * EXECUTIONS + reads + REPORT_PUT
    package_high = (bronze + LOCATOR_PUT_MAX) * EXECUTIONS + reads + REPORT_PUT + REPORT_HEAD_MAX
    mutated = flat(read(ADR)).replace(f"{package_low} to {package_high}", "485 to 780")
    assert "keeps the package envelope" in missing(GUARD.ADR_0020_SELF_REQUIRED, mutated)
    assert f"{package_low} to {package_high}" not in mutated


def test_weakening_the_digest_recomputation_is_caught() -> None:
    """A key that is trusted as integrity proof is a key that never gets verified."""
    mutated = flat(read(ADR)).replace(
        clause("requires the digest to be recomputed", GUARD.ADR_0020_SELF_REQUIRED),
        "the recorded digest is trusted",
    )
    assert "requires the digest to be recomputed" in missing(GUARD.ADR_0020_SELF_REQUIRED, mutated)


def test_removing_the_adr_0017_isolation_is_caught() -> None:
    """Isolation is what keeps a qualification-only key out of the accepted entry point."""
    mutated = _without("keeps the later builder unreachable from adr-0017")
    absent = missing(GUARD.ADR_0020_SELF_REQUIRED, mutated)
    assert "keeps the later builder unreachable from adr-0017" in absent


def test_the_guards_pass_only_because_the_documents_carry_the_clauses() -> None:
    """NEGATIVE CONTROL. An empty document fails every list, so a pass is never silence."""
    assert len(missing(GUARD.ADR_0020_SELF_REQUIRED, "")) == len(GUARD.ADR_0020_SELF_REQUIRED)
    assert len(missing(GUARD.ADR_0020_STATUS_REQUIRED, "")) == len(GUARD.ADR_0020_STATUS_REQUIRED)
    assert len(missing(GUARD.ADR_0020_PLAN_REQUIRED, "")) == len(GUARD.ADR_0020_PLAN_REQUIRED)


# ---------------------------------------------------------------------------
# The ADR-0020 status section -- scope, cardinality, and the boundary
#
# Independent review of PR #50 found the status guards anchored on the whole
# flattened document rather than on ADR-0020's own section. 46 of the 49 required
# phrases are also spelled elsewhere in the same file -- ADR-0018's and
# ADR-0019's status blocks carry their own "run a: not authorized / not run" --
# so deleting one from ADR-0020's section was answered by a neighbour's copy and
# the audit stayed green. Only three phrases were file-unique, which is why
# removing the whole section was caught while gutting it clause by clause was not.
#
# Everything below mutates real committed text in memory. No tracked file is
# written, and every scope decision is read from the audit rather than restated.
# ---------------------------------------------------------------------------

#: The six clauses the review disclosed: required of ADR-0020's section, and also
#: spelled elsewhere in both documents, so a section-local deletion of any of them
#: was invisible to a whole-document scan.
DUPLICATED_ELSEWHERE: Final[tuple[str, ...]] = (
    "records that run a has not run",
    "records that run b has not run",
    "records that the assessment has not run",
    # Three labels moved with the PR #48 merge. The clauses they name were
    # inverted, not removed, so the disclosed defect is still exercised six ways
    # across two documents -- against the clauses the audit requires *now*.
    "keeps infrastructure unauthorized",
    "records that the correction merged",
    "records that the implementation merged",
)

#: Clauses that anchor the merge and the gap. Section scope must catch a local
#: deletion of these too. Three of them are the whole reason deleting the entire
#: section was caught before this correction; the other two are duplicated
#: elsewhere and were not.
SECTION_ANCHORS: Final[tuple[str, ...]] = (
    "records the conditional effectiveness event",
    "records the merge",
    "records the accepted architecture status",
    # "records that the correction has not begun" became false on the PR #48
    # merge; the implementation merge is the clause that anchors the same place.
    "records the implementation merge",
    "records that nothing was deployed",
)

#: The three clauses with no copy outside ADR-0020's section, by phrase.
#:
#: Named rather than counted. A count is satisfied by any three clauses, so it
#: stays green if the ADR-0020 anchors leak into a neighbouring block and three
#: unrelated clauses go file-unique in their place; naming them is what makes the
#: check say *which* three.
FILE_UNIQUE_CLAUSES: Final[tuple[str, ...]] = (
    "adr-0020 architecture: accepted / in force",
    "pr #49: merged",
    "conditional effectiveness event: occurred",
)

#: The heading that ends ADR-0020's section in each document. The two differ on
#: purpose: CLAUDE.md is terminated by a sibling ``###`` and README.md by a parent
#: ``##``, so both terminator classes are exercised.
TERMINATORS: Final[dict[str, tuple[str, str]]] = {
    "CLAUDE.md": ("### ", "Non-blocking follow-ups carried forward"),
    "README.md": ("## ", "Governance"),
}


def scan(text: str) -> Any:
    """The audit's own extractor, driven rather than reimplemented."""
    return GUARD.scan_adr_0020_status_sections(text)


def split_at_section(document: Path) -> tuple[str, str, str]:
    """``(before, section, after)`` for a document's one ADR-0020 status section.

    The split is made on the extractor's own output, so a test cannot disagree
    with the audit about where the section begins and ends.
    """
    text = read(document)
    found = scan(text)
    assert not found.defects, f"{document.name}: {found.defects}"
    assert len(found.sections) == 1, f"{document.name}: {len(found.sections)} sections"
    section = str(found.sections[0])
    before, separator, after = text.partition(section)
    assert separator == section, f"{document.name}: the section is not verbatim in the document"
    return before, section, after


def drop_inside_section(document: Path, label: str) -> tuple[str, str, str, str]:
    """Remove one required clause from ADR-0020's section only.

    Returns ``(phrase, mutated section reading, mutated whole-document reading,
    unchanged outside reading)``. The phrase is read from the audit's own
    requirement list, so this deletes what the audit actually looks for.
    """
    phrase = clause(label, GUARD.ADR_0020_STATUS_REQUIRED)
    before, section, after = split_at_section(document)
    reading = flat(section)
    assert phrase in reading, f"{document.name}: absent before removal: {phrase}"
    mutated = reading.replace(phrase, "")
    assert phrase not in mutated, f"{document.name}: still present after removal: {phrase}"
    outside = flat(before) + " " + flat(after)
    whole = flat(before) + " " + mutated + " " + flat(after)
    return phrase, mutated, whole, outside


def rebuild(before: str, section: str, after: str) -> str:
    """A whole document with one substituted section, as raw text."""
    return before + section + after


# --- the six disclosed boundary mutations ----------------------------------


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
@pytest.mark.parametrize("label", DUPLICATED_ELSEWHERE)
def test_a_section_local_deletion_of_a_duplicated_clause_is_caught(
    document: Path, label: str
) -> None:
    """The defect, one clause at a time: section scope catches it, file scope did not."""
    phrase, mutated, whole, outside = drop_inside_section(document, label)
    assert label in missing(GUARD.ADR_0020_STATUS_REQUIRED, mutated), f"{document.name}: {phrase}"
    assert outside.count(phrase) >= 1, f"{document.name}: not duplicated elsewhere: {phrase}"
    assert phrase in whole, f"{document.name}: file scope would have caught this: {phrase}"


def test_every_disclosed_boundary_mutation_is_detected() -> None:
    """All twelve, counted: six clauses across two documents, none unreported."""
    attempted = 0
    detected = 0
    for document in (CLAUDE_MD, README):
        for label in DUPLICATED_ELSEWHERE:
            attempted += 1
            _phrase, mutated, _whole, _outside = drop_inside_section(document, label)
            if label in missing(GUARD.ADR_0020_STATUS_REQUIRED, mutated):
                detected += 1
    assert attempted == 2 * len(DUPLICATED_ELSEWHERE), attempted
    assert detected == attempted, f"{detected} of {attempted} detected"


def test_the_old_whole_document_scope_missed_every_one_of_them() -> None:
    """NEGATIVE CONTROL for the correction: the scope that was replaced caught none."""
    missed = 0
    for document in (CLAUDE_MD, README):
        for label in DUPLICATED_ELSEWHERE:
            phrase, _mutated, whole, _outside = drop_inside_section(document, label)
            if phrase in whole:
                missed += 1
    assert missed == 2 * len(DUPLICATED_ELSEWHERE), f"only {missed} were invisible to file scope"


def test_a_section_local_deletion_leaves_every_outside_occurrence_alone() -> None:
    """The mutation is section-local, so the test proves scope rather than deletion."""
    for document in (CLAUDE_MD, README):
        before, _section, after = split_at_section(document)
        untouched = flat(before) + " " + flat(after)
        for label in DUPLICATED_ELSEWHERE + SECTION_ANCHORS:
            phrase, _mutated, _whole, outside = drop_inside_section(document, label)
            assert outside == untouched, f"{document.name}: outside text changed for {phrase}"


# --- unique-anchor mutations -----------------------------------------------


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
@pytest.mark.parametrize("label", SECTION_ANCHORS)
def test_a_section_local_deletion_of_an_anchor_clause_is_caught(document: Path, label: str) -> None:
    """The clauses that name the merge and the gap, deleted from their own section."""
    phrase, mutated, _whole, _outside = drop_inside_section(document, label)
    assert label in missing(GUARD.ADR_0020_STATUS_REQUIRED, mutated), f"{document.name}: {phrase}"


def test_three_anchors_are_the_only_file_unique_clauses() -> None:
    """Why the old scope caught a deleted section and nothing smaller.

    Read from the documents rather than asserted: exactly three required clauses
    have no copy outside ADR-0020's section, so removing the whole section tripped
    three guards and removing any single clause tripped none.

    Strengthened from a count to an identity. Three-of-something is satisfied by
    any three clauses, and the set does move -- the PR #48 merge added clauses to
    the section, and each had to be carried into the ADR-0020 row for the
    duplication this file relies on to keep holding. Naming the three says *which*.
    """
    for document in (CLAUDE_MD, README):
        before, _section, after = split_at_section(document)
        outside = flat(before) + " " + flat(after)
        unique = [
            phrase for _label, phrase in GUARD.ADR_0020_STATUS_REQUIRED if phrase not in outside
        ]
        assert set(unique) == set(FILE_UNIQUE_CLAUSES), f"{document.name}: {unique}"
        assert len(unique) == len(FILE_UNIQUE_CLAUSES), f"{document.name}: {unique}"


def test_every_file_unique_clause_is_one_the_audit_requires() -> None:
    """NEGATIVE CONTROL. The named three are the audit's clauses, not this file's."""
    required = [phrase for _label, phrase in GUARD.ADR_0020_STATUS_REQUIRED]
    for phrase in FILE_UNIQUE_CLAUSES:
        assert phrase in required, phrase


# --- cardinality, boundaries and statelessness -----------------------------


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_each_document_carries_exactly_one_intact_status_section(document: Path) -> None:
    """The emitted cardinality check, on the real file."""
    found = scan(read(document))
    assert len(found.sections) == 1, f"{document.name}: {len(found.sections)}"
    assert not found.defects, f"{document.name}: {found.defects}"


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_removing_the_whole_status_section_is_caught(document: Path) -> None:
    """Zero sections is a cardinality failure, not a document that simply passed."""
    before, _section, after = split_at_section(document)
    found = scan(before + after)
    assert len(found.sections) == 0, f"{document.name}: {len(found.sections)}"


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_duplicating_the_whole_status_section_is_caught(document: Path) -> None:
    """A second copy is invisible to a phrase scan -- it only ever adds occurrences."""
    before, section, after = split_at_section(document)
    duplicated = rebuild(before, section + section, after)
    found = scan(duplicated)
    assert len(found.sections) == 2, f"{document.name}: {len(found.sections)}"
    assert not missing(GUARD.ADR_0020_STATUS_REQUIRED, duplicated), (
        f"{document.name}: a phrase scan cannot see the duplicate, which is why it is counted"
    )


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_duplicating_the_heading_alone_is_caught(document: Path) -> None:
    """A bare repeated heading opens a second section with the same claim to answer."""
    before, section, after = split_at_section(document)
    heading = section.splitlines(keepends=True)[0]
    found = scan(rebuild(before, section + heading, after))
    assert len(found.sections) == 2, f"{document.name}: {len(found.sections)}"


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_an_empty_duplicate_section_is_caught(document: Path) -> None:
    """A heading with nothing under it still answers the question a second time."""
    before, section, after = split_at_section(document)
    heading = section.splitlines(keepends=True)[0]
    found = scan(rebuild(before, section + heading + "\n", after))
    assert len(found.sections) == 2, f"{document.name}: {len(found.sections)}"


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_renaming_the_status_heading_is_caught(document: Path) -> None:
    """Heading drift is refused, not absorbed: a rename detaches every section guard."""
    before, section, after = split_at_section(document)
    lines = section.splitlines(keepends=True)
    renamed = lines[0].replace("ADR-0020", "ADR-0021")
    assert renamed != lines[0], "the heading must name the decision it anchors"
    found = scan(rebuild(before, renamed + "".join(lines[1:]), after))
    assert len(found.sections) == 0, f"{document.name}: {len(found.sections)}"


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_the_status_heading_at_another_level_is_refused(document: Path) -> None:
    """Ambiguous structure is reported, never resolved by picking one reading."""
    before, section, after = split_at_section(document)
    lines = section.splitlines(keepends=True)
    found = scan(rebuild(before, "#" + lines[0] + "".join(lines[1:]), after))
    assert len(found.sections) == 0, f"{document.name}: {len(found.sections)}"
    assert found.defects, f"{document.name}: a demoted heading must be reported"


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_the_section_keeps_its_own_level_four_subsections(document: Path) -> None:
    """A ``####`` heading is deeper than the anchor, so it stays inside."""
    _before, section, _after = split_at_section(document)
    subsections = [line for line in section.splitlines() if line.startswith("#### ")]
    assert len(subsections) == len(GUARD.ADR_0020_STATUS_SUBSECTIONS), subsections
    for line in subsections:
        assert line[len("#### ") :].strip() in GUARD.ADR_0020_STATUS_SUBSECTIONS, line


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_the_next_heading_of_level_three_or_higher_ends_the_section(document: Path) -> None:
    """CLAUDE.md is ended by a sibling ``###`` and README.md by a parent ``##``."""
    prefix, title = TERMINATORS[document.name]
    _before, section, after = split_at_section(document)
    assert title.lower() not in flat(section), f"{document.name}: the section swallowed {title}"
    assert after.startswith(prefix + title), f"{document.name}: {after[:60]!r}"


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_demoting_the_terminating_heading_is_caught_as_boundary_drift(document: Path) -> None:
    """The only way this section can drift is forward, so that is what is tested."""
    prefix, title = TERMINATORS[document.name]
    before, section, after = split_at_section(document)
    demoted = after.replace(prefix + title, "#### " + title, 1)
    assert demoted != after, f"{document.name}: the terminator must be present to demote"
    found = scan(rebuild(before, section, demoted))
    assert found.defects, f"{document.name}: a swallowed neighbour must be reported"
    assert title.lower() in flat(found.sections[0]), f"{document.name}: drift not reproduced"


def test_the_extractor_carries_no_state_between_documents() -> None:
    """Order-independent and repeatable, so one scan cannot colour the next."""
    claude, readme = read(CLAUDE_MD), read(README)
    first = (scan(claude).sections, scan(readme).sections)
    second = (scan(readme).sections, scan(claude).sections)
    third = (scan(claude).sections, scan(readme).sections)
    assert first == third, "a repeated scan of the same text must give the same answer"
    assert (second[1], second[0]) == first, "the answer must not depend on scan order"
    assert scan("").sections == (), "a document with no section yields none"


def test_one_documents_section_cannot_satisfy_the_other() -> None:
    """Each file is measured against its own section, never against their union."""
    claude_section = split_at_section(CLAUDE_MD)[1]
    readme_section = flat(split_at_section(README)[1])
    assert claude_section != readme_section, "the two sections are not the same text"
    label = "records the conditional effectiveness event"
    phrase, mutated, _whole, _outside = drop_inside_section(CLAUDE_MD, label)
    assert label in missing(GUARD.ADR_0020_STATUS_REQUIRED, mutated), phrase
    assert label not in missing(GUARD.ADR_0020_STATUS_REQUIRED, readme_section), (
        "the other document is intact, so its own check must still pass"
    )
    assert label not in missing(GUARD.ADR_0020_STATUS_REQUIRED, mutated + " " + readme_section), (
        "a union would hide it, which is why each document is scanned on its own"
    )


def test_the_extractor_ignores_headings_inside_fenced_code_blocks() -> None:
    """README.md carries a shell comment inside a fence; a naive scan reads it as ``#``."""
    before, section, after = split_at_section(CLAUDE_MD)
    fence = "```text"
    fenced = fence + "\n" + "## not a heading" + "\n" + fence + "\n"
    lines = section.splitlines(keepends=True)
    injected = rebuild(before, lines[0] + fenced + "".join(lines[1:]), after)
    found = scan(injected)
    assert len(found.sections) == 1, f"{len(found.sections)} sections"
    assert not found.defects, found.defects
    assert "not a heading" in found.sections[0], "the fenced lines belong to the section body"


# --- non-tautology ---------------------------------------------------------


def test_the_section_scope_is_read_from_the_audit_not_restated_here() -> None:
    """Every scope decision above is the audit's, so the tests cannot drift from it."""
    assert callable(GUARD.scan_adr_0020_status_sections)
    assert GUARD.ADR_0020_STATUS_HEADING_LEVEL == 3
    assert GUARD.ADR_0020_STATUS_HEADING.startswith("The legitimate duplicate-payload collision")
    assert len(GUARD.ADR_0020_STATUS_SUBSECTIONS) > 0
    for document in (CLAUDE_MD, README):
        _before, section, _after = split_at_section(document)
        assert section.splitlines()[0] == "### " + GUARD.ADR_0020_STATUS_HEADING, document.name


def test_every_mutated_clause_is_one_the_audit_actually_requires() -> None:
    """NEGATIVE CONTROL. Nothing above deletes a phrase of its own invention."""
    required = [label for label, _phrase in GUARD.ADR_0020_STATUS_REQUIRED]
    assert len(DUPLICATED_ELSEWHERE) == 6, DUPLICATED_ELSEWHERE
    assert len(SECTION_ANCHORS) == 5, SECTION_ANCHORS
    for label in DUPLICATED_ELSEWHERE + SECTION_ANCHORS:
        assert label in required, label
    assert len(missing(GUARD.ADR_0020_STATUS_REQUIRED, "")) == len(GUARD.ADR_0020_STATUS_REQUIRED)
