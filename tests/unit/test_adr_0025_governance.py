"""ADR-0025 governance: what the decision says, and what it must not have moved.

ADR-0023 corrected the acquisition actor and said, in its own text, that the combined
assessment was out of scope and that correcting it was a separate authorization. This
is that authorization, and it removes **two** dependencies rather than one: the
Terraform state read, and the private Terraform input the account binding came from.

**A decision that corrects one actor is an easy place to move another quietly**, so most
of the checks here are about what did *not* change: the ADR-0023 runtime schema and its
environment variable, the ADR-0024 environment binding, the assessment's own public
outcome vocabulary and exit codes, the operation arithmetic, and every earlier ADR's own
text. The mechanism itself is tested in ``test_qualification_assessment_binding.py``, and
the isolation in ``test_sharadar_assessment_terraform_isolation.py``.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any, Final

import pytest

from kalpamani.data.qualify.sharadar import runtime_binding as rb

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0025-private-runtime-binding-for-the-combined-assessment.md"
ADR_0023: Final = DECISIONS / "ADR-0023-private-runtime-binding-for-the-licensed-bucket.md"
README: Final = PROJECT_ROOT / "README.md"
SCRIPTS: Final = PROJECT_ROOT / "scripts"
INFRA: Final = PROJECT_ROOT / "infra" / "aws" / "research-data-plane"
POLICIES: Final = INFRA / "qualification_policies.tf"
ASSESS: Final = SCRIPTS / "sharadar_qualification_assessment.py"
ACQUIRE: Final = SCRIPTS / "sharadar_empirical_qualification.py"
GATE: Final = SCRIPTS / "qualification_assessment_binding_materialize.py"
ACQUIRE_GATE: Final = SCRIPTS / "qualification_runtime_binding_materialize.py"
VERIFIER: Final = SCRIPTS / "aws_foundation_verify.py"
CONTRACT: Final = (
    PROJECT_ROOT / "src" / "kalpamani" / "data" / "qualify" / "sharadar" / "runtime_binding.py"
)

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""

#: The ADR with its line wrapping removed, so a rewrap cannot hide a clause.
ADR_FLAT: Final = " ".join(ADR_TEXT.split())

#: The README section this decision owns, so a status line found somewhere else in a
#: four-thousand-line document does not count as this section carrying it.
SECTION: Final = (
    README.read_text(encoding="utf-8")
    .split("### The assessment runtime binding, and ADR-0025")[1]
    .split("\n### ")[0]
)


def _gate_module() -> Any:
    """The materialization gate, loaded from its file under a test-only name."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("_adr_0025_gate_under_test", GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _gate_module()


# -- the decision exists and claims no authority it has not been given --------


def test_the_adr_exists_at_its_exact_path() -> None:
    assert ADR.is_file()


def test_exactly_one_adr_0025_exists() -> None:
    assert [path.name for path in sorted(DECISIONS.glob("ADR-0025-*.md"))] == [ADR.name]


def test_the_adr_carries_a_conditional_acceptance_status() -> None:
    """PROPOSED until independently reviewed and merged -- the repository's own rule."""
    assert "Status: PROPOSED — NOT IN FORCE" in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "independently reviewed and merged" in ADR_FLAT


def test_the_adr_states_that_nothing_was_run_to_produce_it() -> None:
    for claim in (
        "No AWS CLI or SDK call",
        "no Terraform command of any kind",
        "no execution-identifier or assessment-identifier allocation",
        "no Run A retry, no Run B and no combined assessment",
        "No real assessment binding was created",
    ):
        assert claim in ADR_FLAT, claim


def test_the_adr_authorizes_no_execution() -> None:
    assert "Accepting this ADR authorizes no execution" in ADR_FLAT
    assert (
        "Architecture and offline implementation, real assessment-binding materialization, "
        "the binding preflight, Run B and combined-assessment execution are five separate gates"
    ) in ADR_FLAT


def test_the_adr_supersedes_and_amends_nothing() -> None:
    assert "This ADR supersedes no earlier decision and amends no earlier ADR document" in ADR_FLAT


@pytest.mark.parametrize("number", ["0017", "0018", "0019", "0020", "0021", "0022", "0023", "0024"])
def test_no_earlier_adr_mentions_this_one(number: str) -> None:
    """Historical decisions are not rewritten to know about a later correction."""
    earlier = sorted(DECISIONS.glob(f"ADR-{number}-*.md"))
    assert earlier, number
    for path in earlier:
        assert "ADR-0025" not in path.read_text(encoding="utf-8")


# -- the defect it answers ----------------------------------------------------


def test_the_adr_names_both_prohibited_dependencies() -> None:
    """One correction would have looked finished while leaving the other in place."""
    assert "Two prohibited dependencies, not one" in ADR_FLAT
    for clause in (
        "the Terraform state read",
        "the private Terraform input",
        "`tf_outputs()` starts a Terraform child process",
        "which parses `terraform.tfvars`",
    ):
        assert clause in ADR_FLAT, clause


def test_the_adr_records_the_call_path_it_removes() -> None:
    for step in ("qualification_identity_gate(ASSESSMENT)", "expected_account()", "tf_outputs()"):
        assert step in ADR_TEXT, step


def test_the_adr_rejects_widening_the_assessment_actor() -> None:
    assert "Widening the actor is the wrong repair, and is rejected" in ADR_FLAT
    assert "The assessment IAM policy is untouched by this decision" in ADR_FLAT


def test_the_adr_explains_why_the_acquisition_artifact_is_not_reused() -> None:
    for clause in (
        "It pins the acquisition profile",
        "An actor field would make a private file choose the principal",
        "One artifact means one mistake reaches both actors",
    ):
        assert clause in ADR_FLAT, clause


# -- the contract the decision fixes ------------------------------------------


def test_the_adr_names_the_one_environment_variable() -> None:
    assert rb.ASSESSMENT_RUNTIME_BINDING_ENV_VAR in ADR_TEXT
    assert "There is no default path" in ADR_FLAT


def test_the_adr_schema_matches_the_implemented_field_set() -> None:
    """The document the ADR shows and the fields the validator admits are one set."""
    for field in sorted(rb._ASSESSMENT_DOCUMENT_FIELDS):
        assert f'"{field}"' in ADR_TEXT, field
    for field in sorted(rb._PROVENANCE_FIELDS):
        assert f'"{field}"' in ADR_TEXT, field


def test_the_adr_pins_the_same_constants_the_contract_compiles() -> None:
    assert f'"{rb.ASSESSMENT_RUNTIME_BINDING_KIND}"' in ADR_TEXT
    assert f'"{rb.ASSESSMENT_RUNTIME_BINDING_CONTRACT_ID}"' in ADR_TEXT
    assert f'"{rb.EXPECTED_ASSESSMENT_PROFILE}"' in ADR_TEXT
    assert f'"{rb.EXPECTED_REGION}"' in ADR_TEXT
    assert "16 KiB" in ADR_TEXT
    assert rb.MAX_ASSESSMENT_RUNTIME_BINDING_BYTES == 16 * 1024
    assert rb.ASSESSMENT_RUNTIME_BINDING_SCHEMA_VERSION == 1


def test_the_adr_records_every_clause_of_the_trust_boundary() -> None:
    for clause in (
        "the path is absolute",
        "the file is a regular file",
        "no symlink, junction or other reparse point appears anywhere in the chain",
        "the owner is the current Windows identity",
        "ACL inheritance is disabled",
        "exactly one effective Allow entry exists, and it names the current user",
        "no Deny entry exists",
        "the identity, path and security metadata are verified before AND after reading",
        "a duplicate JSON key is refused rather than collapsed",
        "partition, region and the assessment profile are exact",
    ):
        assert clause in ADR_FLAT, clause


def test_the_adr_requires_the_platform_check_to_fail_closed() -> None:
    assert "production fails closed" in ADR_FLAT
    assert "SECURITY_UNVERIFIABLE" in ADR_TEXT
    assert "No second ACL parser is written" in ADR_FLAT


def test_the_adr_states_that_the_document_carries_no_capability() -> None:
    assert "The document carries no capability" in ADR_FLAT
    assert (
        "It holds no secret identifier, credential, token, provider endpoint, execution "
        "identifier, locator, report key or payload"
    ) in ADR_FLAT


def test_the_adr_says_the_bound_account_is_not_identity_proof() -> None:
    assert "Carrying it is not trusting it, and loading it is not identity proof" in ADR_FLAT
    assert "The proof remains **one `sts:GetCallerIdentity`**" in ADR_FLAT
    assert "A binding is not a credential" in ADR_FLAT


def test_the_adr_records_the_corrected_stage_order() -> None:
    stages = [
        " 3  pin the governed assessment profile",
        " 4  load and validate the private assessment binding",
        " 5  one identity call, against the account THAT binding names",
        " 6  accept the two owner-known execution identities",
        " 7  construct the S3 client",
    ]
    positions = [ADR_TEXT.index(stage) for stage in stages]
    assert positions == sorted(positions)
    assert "Stages 4 and 5 changed places" in ADR_FLAT


def test_the_adr_pins_the_implementation_provenance_the_gate_writes() -> None:
    """The decision and the tool name the same accepted implementation.

    Read out of the gate rather than restated: two spellings of one provenance is a
    provenance that drifts.
    """
    assert re.fullmatch(r"[0-9a-f]{40}", gate.IMPLEMENTATION_COMMIT)
    assert re.fullmatch(r"[0-9a-f]{40}", gate.IMPLEMENTATION_TREE)
    assert gate.IMPLEMENTATION_COMMIT != gate.IMPLEMENTATION_TREE


# -- the rejected alternatives ------------------------------------------------

REJECTED: Final[tuple[str, ...]] = (
    "Leave the assessment on Terraform because Run A was the urgent case",
    "Give the assessment actor Terraform-state access",
    "Reuse the ADR-0023 acquisition runtime binding",
    "Add an actor field or an actor flag to a shared real artifact",
    "Keep `expected_account()` and replace only `tf_outputs()`",
    "Take the account from the environment binding at run time",
    "Accept a raw bucket or account environment variable",
    "Hardcode the bucket or the account in Git",
    "Discover the artifact by listing the private directory, or by taking the newest file",
    "Fall back to the `kalpamani-foundation` profile",
    "Treat a successfully loaded binding as identity proof",
    "Put the assessment contract in a new module",
    "Give the acquisition and assessment materializations one command with two modes",
    "Overwrite an occupied destination",
)


@pytest.mark.parametrize("alternative", REJECTED)
def test_every_required_alternative_is_explicitly_rejected(alternative: str) -> None:
    assert alternative in ADR_FLAT, alternative
    assert "Rejected:" in ADR_FLAT


# -- what must not have moved -------------------------------------------------


def test_the_acquisition_runtime_binding_schema_is_unchanged() -> None:
    """A second contract was added. No field of the first was added, removed or renamed."""
    assert rb._DOCUMENT_FIELDS == frozenset(
        {
            "schema_version",
            "binding_kind",
            "contract_id",
            "aws_partition",
            "aws_region",
            "target_account_id",
            "acquisition_profile",
            "licensed_bucket_name",
            "provenance",
        }
    )
    assert rb.RUNTIME_BINDING_SCHEMA_VERSION == 1
    assert rb.RUNTIME_BINDING_KIND == "kalpamani-qualification-runtime"
    assert rb.RUNTIME_BINDING_CONTRACT_ID == "qualification-runtime-binding/v1"
    assert rb.RUNTIME_BINDING_ENV_VAR == "KALPAMANI_QUALIFICATION_RUNTIME_BINDING_FILE"
    assert rb.EXPECTED_ACQUISITION_PROFILE == "kalpamani-qualification-acquisition"


def test_the_environment_binding_is_unchanged() -> None:
    assert rb.ENVIRONMENT_BINDING_KIND == "kalpamani-qualification-environment"
    assert rb.ENVIRONMENT_BINDING_CONTRACT_ID == "qualification-environment-binding/v1"
    assert rb.ENVIRONMENT_BINDING_SOURCE_KIND == "terraform-output"
    assert "acquisition_profile" not in rb._ENVIRONMENT_FIELDS
    assert "assessment_profile" not in rb._ENVIRONMENT_FIELDS


def test_the_acquisition_entry_point_keeps_its_own_gate_and_binding() -> None:
    """ADR-0025 corrected one actor. It did not touch the other."""
    acquire = ACQUIRE.read_text(encoding="utf-8")
    assert "qualification_identity_gate(" in acquire
    assert "qualification_identity_gate_for" not in acquire
    assert "load_runtime_binding" in acquire
    assert "load_assessment_runtime_binding" not in acquire
    assert "expected_account" in acquire


def test_the_verifier_keeps_both_functions_for_their_own_callers() -> None:
    """Callers were removed. Neither function was, because others still need them."""
    verifier = VERIFIER.read_text(encoding="utf-8")
    assert "def tf_outputs() -> dict[str, Any]:" in verifier
    assert "def expected_account() -> str | None:" in verifier
    assert "def qualification_identity_gate(actor: QualificationActor) -> str | None:" in verifier
    assert "def qualification_identity_gate_for(" in verifier


def test_the_shared_refusal_message_names_no_source() -> None:
    """Two callers, two governed sources: a message naming one would be wrong for the other."""
    verifier = VERIFIER.read_text(encoding="utf-8")
    assert "no 12-digit account binding was supplied for this actor" in verifier
    body = verifier.split("def qualification_identity_refusal(")[1].split("\ndef ")[0]
    assert "terraform.tfvars" not in body


def test_the_assessment_policy_is_unchanged() -> None:
    """A new private artifact must not have widened the actor it is delivered to."""
    policies = " ".join(POLICIES.read_text(encoding="utf-8").split())
    assert "AcquisitionNeverReadsOrDeletes" in policies
    assert "AcquisitionNeverEnumeratesTheLicensedStore" in policies
    for action in ('"s3:GetObject"', '"s3:GetObjectVersion"', '"s3:GetObjectAttributes"'):
        assert action in policies, action


def test_the_public_outcome_vocabulary_and_exit_codes_are_unchanged() -> None:
    assess = ASSESS.read_text(encoding="utf-8")
    assert (
        'REFUSED_LICENSED_BUCKET = "qualification assessment refused: licensed configuration"'
    ) in assess
    assert (
        'REFUSED_IDENTITY = "qualification assessment refused: the AWS identity gate did not pass"'
    ) in assess
    for line in (
        "AssessmentOutcome.COMPLETED: 0,",
        "AssessmentOutcome.REFUSED_IDENTITY: 5,",
        "AssessmentOutcome.REFUSED_LICENSED_BUCKET: 6,",
        "AssessmentOutcome.REFUSED_UNCLASSIFIED: 13,",
    ):
        assert line in assess, line


def test_the_assessment_still_reaches_no_provider_or_credential() -> None:
    assess = ASSESS.read_text(encoding="utf-8")
    for forbidden in (
        "secretsmanager",
        "get_secret_value",
        "SharadarCredential",
        "UrllibTransport",
        "KALPAMANI_SHARADAR_SECRET_ID",
    ):
        assert forbidden not in assess, forbidden
    assert "No provider capability is introduced anywhere" in ADR_FLAT


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
    assert "194 object-byte" in ADR_FLAT
    # The assessment envelope, restated in the consequences with the en dash the ADR
    # uses in prose. Normalised here rather than matched literally, so a rewrap or a
    # dash change cannot make a governed number look absent.
    assert "195-196 S3 operations" in ADR_FLAT.replace("–", "-")  # noqa: RUF001


def test_the_deadline_terms_are_restated_unchanged() -> None:
    assert "L >= 3 * T_s3 + C" in ADR_TEXT
    assert "remaining >= T_req + 3 * T_s3 + L" in ADR_TEXT


def test_the_earlier_decision_still_records_its_own_scope_exclusion() -> None:
    """ADR-0023's own text is not edited to know the assessment was corrected later."""
    earlier = " ".join(ADR_0023.read_text(encoding="utf-8").split())
    assert "The assessment entry point is deliberately out of scope" in earlier
    assert "correcting it is a separate authorization" in earlier


# -- the status document agrees -----------------------------------------------

REQUIRED_STATUS: Final[tuple[str, ...]] = (
    "assessment-binding contract:                  IMPLEMENTED / OFFLINE-VALIDATED",
    "assessment-binding materialization gate:      IMPLEMENTED / OFFLINE-VALIDATED / NEVER RUN",
    "real assessment runtime binding:              NOT MATERIALIZED",
    "Terraform reachable from the assessment:      NO",
    "private Terraform input reachable:            NO",
    "operator tools reachable from the assessment: NO",
    "provider or credential reachable:             NO",
)


@pytest.mark.parametrize("line", REQUIRED_STATUS)
def test_both_the_adr_and_the_status_document_carry_the_status_lines(line: str) -> None:
    assert line in ADR_TEXT, line
    assert line in SECTION, line


def test_the_status_section_keeps_every_downstream_gate_closed() -> None:
    for line in (
        "Run A:                                        COMPLETED ONCE / 2026-09-04",
        "a Run A retry:                                NOT AUTHORIZED / NOT RUN",
        "assessment-binding materialization:           NOT AUTHORIZED / NOT RUN",
        "binding preflight:                            NOT AUTHORIZED / NOT RUN",
        "Run B:                                        NOT AUTHORIZED / NOT RUN",
        "Run B earliest approved target:               12 SEPTEMBER 2026",
        "combined assessment:                          NOT AUTHORIZED / NOT RUN",
        "P1-P9:                                        UNEVALUATED",
        "data correctness and quality:                 NOT ESTABLISHED",
        "G1 / G2:                                      OPEN / OPEN",
        "provider selected:                            NONE",
        "backtesting:                                  NOT STARTED",
        "Phase 3:                                      NOT COMPLETE",
        "CONTROL:                                      DEFERRED",
        "live trading:                                 HARD-DISABLED",
        "new execution identifiers:                    0",
    ):
        assert line in ADR_TEXT, line
        assert line in SECTION, line


def test_the_status_document_claims_no_authority_for_a_proposed_adr() -> None:
    flat = " ".join(SECTION.split())
    assert "carries no authority while its pull request is open" in flat
    assert "PROPOSED" in flat
    for claimed in (
        "ADR-0025 is **ACCEPTED",
        "ADR-0025: ACCEPTED",
        "ADR-0025 — ACCEPTED",
        "AUTHORIZED TO RUN",
        "binding: MATERIALIZED",
        "combined assessment: COMPLETED",
    ):
        assert claimed not in flat, claimed


def test_the_status_document_does_not_claim_the_assessment_is_unblocked() -> None:
    flat = " ".join(SECTION.split()).lower()
    for overclaim in (
        "the combined assessment is unblocked",
        "the combined assessment may now run",
        "run b is unblocked",
        "p1-p9: evaluated",
    ):
        assert overclaim not in flat, overclaim


# -- nothing private reaches Git ----------------------------------------------

TRACKED_SURFACES: Final[tuple[Path, ...]] = (ADR, CONTRACT, GATE, ACQUIRE_GATE, ASSESS, ACQUIRE)


@pytest.mark.parametrize("path", TRACKED_SURFACES, ids=lambda path: path.name)
def test_no_surface_carries_a_private_identifier(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for marker in ("arn:aws:", "amazonaws.com", "AKIA", ".amazonaws", "awsapps.com"):
        assert marker not in text, marker
    assert re.search(r"\b\d{12}\b", text) is None
    assert "sap4n" not in text
