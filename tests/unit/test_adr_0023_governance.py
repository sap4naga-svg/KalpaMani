"""ADR-0023 governance: what the decision says, and what it must not have moved.

Run A resolved the licensed bucket from Terraform remote state under an actor
ADR-0019 deliberately made write-only, so it refused at stage 6 every time. The
correction replaces the state read with a private, ACL-protected configuration file.

**A correction is the easiest place to widen something quietly**, so the checks here
are mostly about what did *not* change: the acquisition IAM policy, the operation
arithmetic, the assessment separation, and every earlier ADR's own text. The
mechanism itself is tested in ``test_sharadar_runtime_binding.py``, and its
unreachability of Terraform in ``test_sharadar_acquisition_terraform_isolation.py``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from kalpamani.data.qualify.sharadar import runtime_binding as rb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DECISIONS = PROJECT_ROOT / "docs" / "decisions"
ADR = DECISIONS / "ADR-0023-private-runtime-binding-for-the-licensed-bucket.md"
README = PROJECT_ROOT / "README.md"
INFRA = PROJECT_ROOT / "infra" / "aws" / "research-data-plane"
POLICIES = INFRA / "qualification_policies.tf"
ACQUIRE = PROJECT_ROOT / "scripts" / "sharadar_empirical_qualification.py"
ASSESS = PROJECT_ROOT / "scripts" / "sharadar_qualification_assessment.py"
VERIFIER = PROJECT_ROOT / "scripts" / "aws_foundation_verify.py"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""

#: The ADR with its line wrapping removed, so a rewrap cannot hide a clause.
ADR_FLAT: Final = " ".join(ADR_TEXT.split())


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


# -- the decision exists and claims no authority it has not been given --------


def test_the_adr_exists_at_its_exact_path() -> None:
    assert ADR.is_file()


def test_exactly_one_adr_0023_exists() -> None:
    assert [path.name for path in sorted(DECISIONS.glob("ADR-0023-*.md"))] == [ADR.name]


def test_the_adr_carries_a_conditional_acceptance_status() -> None:
    """PROPOSED until independently reviewed and merged -- the repository's own rule.

    Every ADR here is written this way, and the reason is that a document declaring
    itself accepted while its pull request is open would be claiming an authority
    nobody has granted it yet.
    """
    assert "Status: PROPOSED — NOT IN FORCE" in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "independently reviewed and merged" in ADR_FLAT


def test_the_adr_states_that_nothing_was_run_to_produce_it() -> None:
    for claim in (
        "No AWS CLI or SDK call",
        "no Terraform command of any kind",
        "No real private runtime binding was created",
    ):
        assert claim in ADR_FLAT


def test_the_adr_authorizes_no_execution() -> None:
    assert "Accepting this ADR authorizes no execution" in ADR_FLAT
    assert "Implementation, materialization and execution stay three separate gates" in ADR_FLAT


def test_the_adr_supersedes_and_amends_nothing() -> None:
    assert "This ADR supersedes no earlier decision and amends no earlier ADR document" in ADR_FLAT


@pytest.mark.parametrize("number", ["0017", "0018", "0019", "0020", "0021", "0022"])
def test_no_earlier_adr_mentions_this_one(number: str) -> None:
    """Historical decisions are not rewritten to know about a later correction."""
    earlier = sorted(DECISIONS.glob(f"ADR-{number}-*.md"))
    assert earlier, number
    for path in earlier:
        assert "ADR-0023" not in path.read_text(encoding="utf-8")


# -- the diagnosis, and the boundary it approved ------------------------------


def test_the_adr_names_the_approved_root_cause() -> None:
    assert "RUNTIME_ACQUISITION_PROFILE_CANNOT_READ_GOVERNED_REMOTE_STATE" in ADR_TEXT


def test_the_adr_records_the_whole_approved_correction_boundary() -> None:
    for clause in (
        "no acquisition-role state access",
        "no private identifiers in Git",
        "fail-closed validation",
        "no Terraform subprocess reachable from the acquisition path",
    ):
        assert clause in ADR_FLAT, clause


def test_the_adr_explains_why_the_state_read_could_never_have_worked() -> None:
    assert "spawns Terraform with no `env=` argument" in ADR_FLAT
    assert "so the child inherits the process environment" in ADR_FLAT
    assert "reads remote state from the state bucket **as the acquisition actor**" in ADR_FLAT


def test_the_adr_records_that_the_old_guard_could_not_have_caught_it() -> None:
    assert '`"terraform" not in source.lower()`' in ADR_FLAT
    assert "no test followed the call graph to the subprocess" in ADR_FLAT


# -- the contract the decision fixes ------------------------------------------


def test_the_adr_names_the_one_environment_variable() -> None:
    assert rb.RUNTIME_BINDING_ENV_VAR in ADR_TEXT
    assert "There is no default path" in ADR_FLAT


def test_the_adr_schema_matches_the_implemented_field_set() -> None:
    """The document the ADR shows and the fields the loader admits are one set."""
    for field in sorted(rb._DOCUMENT_FIELDS):
        assert f'"{field}"' in ADR_TEXT, field
    for field in sorted(rb._PROVENANCE_FIELDS):
        assert f'"{field}"' in ADR_TEXT, field


def test_the_adr_pins_the_same_constants_the_loader_compiles() -> None:
    assert f'"{rb.RUNTIME_BINDING_KIND}"' in ADR_TEXT
    assert f'"{rb.RUNTIME_BINDING_CONTRACT_ID}"' in ADR_TEXT
    assert f'"{rb.EXPECTED_ACQUISITION_PROFILE}"' in ADR_TEXT
    assert f'"{rb.EXPECTED_REGION}"' in ADR_TEXT
    assert "16 KiB" in ADR_TEXT
    assert rb.MAX_RUNTIME_BINDING_BYTES == 16 * 1024


def test_the_adr_records_every_clause_of_the_trust_boundary() -> None:
    for clause in (
        "the path is absolute",
        "the file is a regular file",
        "no symlink, junction or other reparse point appears anywhere in the chain",
        "the owner is the current Windows identity",
        "ACL inheritance is disabled",
        "exactly one effective Allow entry exists",
        "no Deny entry exists",
        "the identity, path and security metadata are verified before AND after reading",
        "a duplicate JSON key is refused rather than collapsed",
        "the account matches the governed expected account",
    ):
        assert clause in ADR_FLAT, clause


def test_the_adr_requires_the_platform_check_to_fail_closed() -> None:
    assert "production fails closed" in ADR_FLAT
    assert "production cannot silently skip the check" in ADR_FLAT


def test_the_adr_records_that_no_aws_call_resolves_the_account() -> None:
    assert "No AWS call is made to obtain it" in ADR_FLAT
    assert "no Terraform process is started" in ADR_FLAT


# -- the rejected alternatives ------------------------------------------------

REJECTED: Final[tuple[str, ...]] = (
    "Give the acquisition actor Terraform-state access",
    "Switch to `kalpamani-foundation` inside Run A",
    "Hardcode the bucket in Git",
    "Read Terraform state with the AWS CLI instead of the Terraform binary",
    "Accept a raw bucket-name environment variable",
    "Default to the first (or newest) file found in the private directory",
    "Keep the real binding inside the repository working tree",
    "Weaken or delete the acquisition actor's explicit S3 read denials",
)


@pytest.mark.parametrize("alternative", REJECTED)
def test_every_required_alternative_is_explicitly_rejected(alternative: str) -> None:
    assert alternative in ADR_FLAT
    assert "Rejected:" in ADR_FLAT


# -- what must not have moved -------------------------------------------------


def test_the_acquisition_policy_still_denies_every_object_read() -> None:
    """The correction must not have widened the actor it exists to keep narrow."""
    policies = _flat(POLICIES)
    assert "AcquisitionNeverReadsOrDeletes" in policies
    for action in ('"s3:GetObject"', '"s3:GetObjectVersion"', '"s3:GetObjectAttributes"'):
        assert action in policies, action
    assert "AcquisitionNeverEnumeratesTheLicensedStore" in policies


def test_the_acquisition_policy_grants_only_the_one_write_action() -> None:
    policies = POLICIES.read_text(encoding="utf-8")
    allow = policies.split('sid       = "PublishQualificationEvidence"')[1].split("}")[0]
    assert 'actions   = ["s3:PutObject"]' in allow


def test_no_qualification_policy_names_the_state_bucket() -> None:
    """The acquisition actor holds nothing on state, and the declaration says so."""
    policies = POLICIES.read_text(encoding="utf-8")
    assert "state" not in policies.lower().replace("statement", "").replace("states", "")


def test_the_operation_arithmetic_is_restated_unchanged() -> None:
    for line in (
        "acquisition PutObject: 145 to 147",
        "acquisition HeadObject: 0",
        "acquisition GetObject: 0",
        "two successful runs: 290 to 294",
        "assessment: 195 to 196",
        "whole successful package: 485 to 490",
    ):
        assert line in ADR_TEXT, line


def test_the_deadline_terms_are_restated_unchanged() -> None:
    assert "L >= 3 * T_s3 + C" in ADR_TEXT
    assert "remaining >= T_req + 3 * T_s3 + L" in ADR_TEXT


def test_the_public_bucket_outcome_and_exit_code_are_unchanged() -> None:
    acquire = ACQUIRE.read_text(encoding="utf-8")
    assert 'REFUSED_LICENSED_BUCKET = "empirical acquisition refused: licensed configuration"' in (
        acquire
    )
    assert "EmpiricalOutcome.REFUSED_LICENSED_BUCKET: 8," in acquire
    assert "exit code `8`" in ADR_FLAT


def test_the_acquisition_stage_order_is_unchanged() -> None:
    acquire = ACQUIRE.read_text(encoding="utf-8")
    stages = [
        " 4  pin the governed AWS profile",
        " 5  pass the governed identity gate",
        " 6  resolve only the LICENSED bucket",
        " 7  resolve the fixed secret identifier",
        " 8  retrieve one governed credential",
    ]
    positions = [acquire.index(stage) for stage in stages]
    assert positions == sorted(positions)


def test_the_verifier_keeps_the_state_read_for_its_own_actor() -> None:
    """One caller was removed. The function was not, because others still need it."""
    verifier = VERIFIER.read_text(encoding="utf-8")
    assert "def tf_outputs() -> dict[str, Any]:" in verifier
    assert "outputs = tf_outputs()" in verifier


def test_the_assessment_scope_exclusion_is_still_stated_as_this_decision_made_it() -> None:
    """ADR-0023's own text is not rewritten now that a later decision corrected it.

    It said the assessment entry point was out of scope and that correcting it was a
    separate authorization, and both are historical facts about that slice. ADR-0025
    is that separate authorization; it removed the Terraform state read here, so the
    predecessor of this test -- which asserted ``tf_outputs`` was still present -- is
    now asking the wrong question. The properties that survive are that ADR-0023 still
    records its own boundary, and that the correction happened in a decision of its own
    rather than silently.
    """
    assert "The assessment entry point is deliberately out of scope" in ADR_FLAT
    assert "correcting it is a separate authorization" in ADR_FLAT
    assert "ADR-0025" not in ADR_TEXT

    successor = DECISIONS / "ADR-0025-private-runtime-binding-for-the-combined-assessment.md"
    assert successor.is_file()
    assert "tf_outputs" not in ASSESS.read_text(encoding="utf-8")


# -- the status document agrees -----------------------------------------------

REQUIRED_STATUS: Final[tuple[str, ...]] = (
    "private runtime-binding contract:             IMPLEMENTED / OFFLINE-VALIDATED",
    "real private runtime binding:                 NOT MATERIALIZED",
    "acquisition IAM policy:                       UNCHANGED / WRITE-ONLY",
    "Terraform-state access for acquisition actor: NONE",
    "Terraform reachable from Run A:               NO",
    "Run A:                                        BLOCKED PENDING MATERIALIZATION AND REVIEW",
)


@pytest.mark.parametrize("line", REQUIRED_STATUS)
def test_both_the_adr_and_the_status_document_carry_the_status_lines(line: str) -> None:
    assert line in ADR_TEXT, line
    assert line in README.read_text(encoding="utf-8"), line


def test_the_status_document_keeps_every_downstream_gate_closed() -> None:
    readme = README.read_text(encoding="utf-8")
    section = readme.split("### The private runtime binding, and ADR-0023")[1]
    section = section.split("\n### ")[0]
    for line in (
        "G1 / G2:                                      OPEN / OPEN",
        "provider selected:                            NONE",
        "Phase 3:                                      NOT COMPLETE",
        "CONTROL:                                      DEFERRED",
        "live trading:                                 HARD-DISABLED",
        "new execution identifiers:                    0",
    ):
        assert line in section, line


def test_the_status_document_claims_no_authority_for_a_proposed_adr() -> None:
    readme = README.read_text(encoding="utf-8")
    section = readme.split("### The private runtime binding, and ADR-0023")[1]
    section = section.split("\n### ")[0]
    flat = " ".join(section.split())
    assert "carries no authority while its pull request is open" in flat
    assert "PROPOSED" in flat
    # The section may say what the ADR *becomes* on merge. It may not say it is
    # there already, and it may not claim the binding exists or that a run may go.
    assert "On independent review and merge it becomes **ACCEPTED / IN FORCE**" in flat
    for claimed in (
        "ADR-0023 is **ACCEPTED",
        "ADR-0023: ACCEPTED",
        "ADR-0023 — ACCEPTED",
        "AUTHORIZED TO RUN",
        "binding: MATERIALIZED",
    ):
        assert claimed not in flat, claimed


# -- nothing private reaches Git ----------------------------------------------

TRACKED_SURFACES: Final[tuple[Path, ...]] = (
    ADR,
    PROJECT_ROOT / "src" / "kalpamani" / "data" / "qualify" / "sharadar" / "runtime_binding.py",
    ACQUIRE,
)


@pytest.mark.parametrize("path", TRACKED_SURFACES, ids=lambda path: path.name)
def test_no_new_surface_carries_a_private_identifier(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for marker in ("arn:aws:", "amazonaws.com", "AKIA", ".amazonaws", "awsapps.com"):
        assert marker not in text, marker
    assert re.search(r"\b\d{12}\b", text) is None
    assert "sap4n" not in text
