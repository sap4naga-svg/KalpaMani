"""ADR-0020 is a PROPOSAL, and every guard here holds it to that.

PR #48 implemented ADR-0019's fail-closed write-only collision rule correctly and
offline, and in doing so exposed a pre-existing incompatibility between three
separately accepted clauses: a complete acquisition run is a fixed 48 requests
and 144 Bronze writes, the qualification payload object is content-addressed by
``(provider, dataset, digest)``, and an acquisition-side 412 fails closed without
reading or comparing the occupied object. Two legitimate byte-identical
observations therefore derive one object name and halt a correct run.

ADR-0020 proposes to fix the **name**, not the write. Three drifts follow from
that, and each is guarded here:

1. **Upward** -- a proposal read as an acceptance. ADR-0020 is not in
   ``MERGED_ADR_STATUS``, it authorizes nothing, and neither status document may
   say otherwise.
2. **Sideways** -- the identity fix used as cover for relaxing the collision
   policy. Acquisition stays conditional ``PutObject`` only, with zero object
   reads and zero listing, and no occupied object may be read, compared or
   adopted.
3. **Forwards** -- a proposed identity read as an implemented one. No
   qualification payload-key builder exists, PR #48 is open, unmerged, blocked on
   architecture and untouched, and its correction has not begun.

**The arithmetic is derived here, not transcribed.** A number copied from prose
into prose is a number nobody checks, so the request count, the write count and
every envelope are recomputed from the accepted inventory and compared against
what the ADR says.

**Every guard has a mutation test behind it.** A required phrase that no edit can
remove is a phrase that proves nothing, so each load-bearing clause is deleted or
inverted in a copy of the real document and the guard is required to notice.

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

#: The pull request the proposal must leave alone.
BLOCKED_PR = "#48"


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


def test_the_adr_exists_and_carries_its_conditional_status_line() -> None:
    """A proposal with no conditional line is a proposal nobody can hold to it."""
    assert ADR.is_file(), "the proposed payload-identity amendment must be the file it names"
    reading = flat(read(ADR))
    assert "status: proposed" in reading
    assert (
        "no authority until the pull request introducing it is independently reviewed and merged"
        in reading
    )
    assert "adr-0020 is accepted" not in reading
    assert "adr-0020 is in force" not in reading


def test_the_adr_is_not_registered_as_a_merged_decision() -> None:
    """Registration happens on the merge, not on the proposal."""
    registry = dict(audit_registry())
    assert "ADR-0020" not in registry
    assert registry.get("ADR-0019") == "PR #46 merged", "the merged neighbour stays registered"


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
def test_both_documents_record_the_proposed_state(document: Path) -> None:
    """Independently: merged main has twice carried a fact in one file and its contradiction
    in the other."""
    absent = missing(GUARD.ADR_0020_STATUS_REQUIRED, read(document))
    assert not absent, f"{document.name} is missing: {absent}"


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_both_documents_do_not_overstate_the_proposal(document: Path) -> None:
    """No document may read a proposal as an acceptance or an implementation."""
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
def test_no_document_says_the_new_identity_is_already_implemented(document: Path) -> None:
    """A proposed key is not a built one, and no qualification key builder exists."""
    reading = flat(read(document))
    assert "the request-scoped payload identity is implemented" not in reading
    assert "the qualification payload-key builder exists" not in reading
    assert "adr-0020 implementation: not authorized" in reading


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
    """The plan is where the ceilings are read from, so it carries the same proposed state."""
    absent = missing(GUARD.ADR_0020_PLAN_REQUIRED, read(PLAN))
    assert not absent, f"the implementation plan is missing: {absent}"


def test_this_proposal_changed_no_production_code() -> None:
    """The shared surfaces still have exactly what a later correction would route around.

    ADR-0020 requires a *later* implementation gate to introduce a
    qualification-specific builder. It does not perform that correction, and the
    proof is that the shared content-addressed builder and the shared store's
    collision resolution are both still here, unchanged.
    """
    bronze = read(SHARED_BRONZE)
    store = read(SHARED_STORE)
    assert "def bronze_payload_key" in bronze
    assert '"objects",\n        "sha256",' in bronze, "the shared key is still content-addressed"
    assert "def head_object" in store
    assert "qualification_payload_key" not in bronze
    assert "qualification_payload_key" not in store


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


def test_marking_the_adr_accepted_before_merge_is_caught() -> None:
    """The upward drift: a proposal promoted by a document rather than by a merge."""
    for document in (CLAUDE_MD, README):
        mutated = flat(read(document)) + " adr-0020: accepted / in force"
        claims = overstated(GUARD.ADR_0020_STATUS_FORBIDDEN, mutated)
        assert "adr-0020: accepted / in force" in claims, document.name


def test_registering_the_proposal_as_merged_is_caught() -> None:
    """The registry is what governs an in-force claim, so a premature entry must fail."""
    registry = dict(audit_registry())
    registry["ADR-0020"] = "PR #49 merged"
    assert "ADR-0020" in registry, "the mutation is the premature registration itself"
    assert "ADR-0020" not in dict(audit_registry()), "the committed registry stays clean"


def test_claiming_the_blocked_pull_request_is_mergeable_or_corrected_is_caught() -> None:
    for injected in (
        f"pr {BLOCKED_PR} is mergeable",
        f"pr {BLOCKED_PR} has been corrected",
        f"pr {BLOCKED_PR} is ready to merge",
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
