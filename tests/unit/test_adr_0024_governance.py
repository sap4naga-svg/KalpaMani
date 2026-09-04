"""ADR-0024 governance: what the decision says, and what it must not have moved.

ADR-0023 required ``provenance.environment_binding_sha256`` and defined the artifact it
digests nowhere. ADR-0024 defines it, gives it a producer, and gives the runtime
binding a materialization gate.

**A decision that adds an artifact is an easy place to move an accepted one quietly**,
so most of the checks here are about what did *not* change: the ADR-0023 runtime schema,
the acquisition IAM policy, the entry point's public outcome, the operation arithmetic,
and every earlier ADR's own text. The mechanism itself is tested in
``test_qualification_environment_binding.py``, and Run A's inability to reach any of it
in ``test_sharadar_acquisition_terraform_isolation.py``.
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
ADR: Final = DECISIONS / "ADR-0024-governed-qualification-environment-binding-source.md"
ADR_0023: Final = DECISIONS / "ADR-0023-private-runtime-binding-for-the-licensed-bucket.md"
README: Final = PROJECT_ROOT / "README.md"
SCRIPTS: Final = PROJECT_ROOT / "scripts"
INFRA: Final = PROJECT_ROOT / "infra" / "aws" / "research-data-plane"
POLICIES: Final = INFRA / "qualification_policies.tf"
ACQUIRE: Final = SCRIPTS / "sharadar_empirical_qualification.py"
WRITER: Final = SCRIPTS / "qualification_private_artifacts.py"
CAPTURE: Final = SCRIPTS / "qualification_environment_binding_capture.py"
GATE: Final = SCRIPTS / "qualification_runtime_binding_materialize.py"
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
    .split("### The environment binding, and ADR-0024")[1]
    .split("\n### ")[0]
)


def _gate_module() -> Any:
    """The materialization gate, loaded from its file under a test-only name."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("_adr_0024_gate_under_test", GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _gate_module()


# -- the decision exists and claims no authority it has not been given --------


def test_the_adr_exists_at_its_exact_path() -> None:
    assert ADR.is_file()


def test_exactly_one_adr_0024_exists() -> None:
    assert [path.name for path in sorted(DECISIONS.glob("ADR-0024-*.md"))] == [ADR.name]


def test_the_adr_carries_a_conditional_acceptance_status() -> None:
    """PROPOSED until independently reviewed and merged -- the repository's own rule."""
    assert "Status: PROPOSED — NOT IN FORCE" in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "independently reviewed and merged" in ADR_FLAT


def test_the_adr_states_that_nothing_was_run_to_produce_it() -> None:
    for claim in (
        "No AWS CLI or SDK call",
        "no Terraform command of any kind",
        "no execution-identifier allocation",
        "No real environment binding and no real runtime binding was created",
    ):
        assert claim in ADR_FLAT, claim


def test_the_adr_authorizes_no_execution() -> None:
    assert "Accepting this ADR authorizes no execution" in ADR_FLAT
    assert "Implementation, materialization and execution stay three separate gates" in ADR_FLAT


def test_the_adr_supersedes_and_amends_nothing() -> None:
    assert "This ADR supersedes no earlier decision and amends no earlier ADR document" in ADR_FLAT


@pytest.mark.parametrize("number", ["0017", "0018", "0019", "0020", "0021", "0022", "0023"])
def test_no_earlier_adr_mentions_this_one(number: str) -> None:
    """Historical decisions are not rewritten to know about a later addition."""
    earlier = sorted(DECISIONS.glob(f"ADR-{number}-*.md"))
    assert earlier, number
    for path in earlier:
        assert "ADR-0024" not in path.read_text(encoding="utf-8")


# -- the gap it answers -------------------------------------------------------


def test_the_adr_states_the_gap_precisely() -> None:
    for clause in (
        "The loader validates that field's grammar and nothing else",
        "Nothing in the repository established what those bytes are",
        "no producer that writes one",
        "no path-discovery mechanism that selects one",
        "no code that hands the digest to runtime-binding materialization",
    ):
        assert clause in ADR_FLAT, clause


def test_the_adr_rejects_the_secret_access_receipt_with_a_reason() -> None:
    assert "The applied secret-access receipt is not the environment binding" in ADR_FLAT
    assert "It carries no licensed bucket" in ADR_FLAT


def test_the_adr_rejects_the_private_terraform_input_with_a_reason() -> None:
    assert "The private Terraform input is not the environment binding either" in ADR_FLAT
    assert "an architectural change and not a naming convenience" in ADR_FLAT


def test_the_adr_records_the_naming_collision_that_hid_it() -> None:
    assert "The same phrase was doing two jobs in one module" in ADR_FLAT


# -- the contract the decision fixes ------------------------------------------


def test_the_adr_names_the_one_environment_variable() -> None:
    assert rb.ENVIRONMENT_BINDING_ENV_VAR in ADR_TEXT
    assert "There is no default path" in ADR_FLAT


def test_the_adr_schema_matches_the_implemented_field_set() -> None:
    """The document the ADR shows and the fields the validator admits are one set."""
    for field in sorted(rb._ENVIRONMENT_FIELDS):
        assert f'"{field}"' in ADR_TEXT, field
    for field in sorted(rb._ENVIRONMENT_PROVENANCE_FIELDS):
        assert f'"{field}"' in ADR_TEXT, field


def test_the_adr_pins_the_same_constants_the_contract_compiles() -> None:
    assert f'"{rb.ENVIRONMENT_BINDING_KIND}"' in ADR_TEXT
    assert f'"{rb.ENVIRONMENT_BINDING_CONTRACT_ID}"' in ADR_TEXT
    assert f'"{rb.ENVIRONMENT_BINDING_SOURCE_KIND}"' in ADR_TEXT
    assert f'"{rb.EXPECTED_REGION}"' in ADR_TEXT
    assert "16 KiB" in ADR_TEXT
    assert rb.MAX_ENVIRONMENT_BINDING_BYTES == 16 * 1024


def test_the_adr_says_the_artifact_is_actor_neutral() -> None:
    """The runtime binding adds the actor. A captured environment must not pick one."""
    assert "It is deliberately actor-neutral" in ADR_FLAT
    assert "There is no `acquisition_profile` field" in ADR_FLAT
    assert "acquisition_profile" not in rb._ENVIRONMENT_FIELDS


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
        "the account is exactly twelve digits and matches the governed expected account",
    ):
        assert clause in ADR_FLAT, clause


def test_the_adr_requires_the_platform_check_to_fail_closed() -> None:
    assert "production fails closed" in ADR_FLAT
    assert "SECURITY_UNVERIFIABLE" in ADR_TEXT


def test_the_adr_defines_the_digest_as_bytes_rather_than_shape() -> None:
    assert "is the SHA-256, in lowercase hexadecimal, of the exact byte sequence" in ADR_FLAT
    assert "not recomputed from the parsed document" in ADR_FLAT
    assert "would name a *shape*" in ADR_FLAT


def test_the_adr_records_that_no_aws_call_resolves_the_account() -> None:
    assert "no AWS call is made to obtain it" in ADR_FLAT
    assert "no Terraform process is started" in ADR_FLAT


def test_the_adr_pins_the_implementation_provenance_the_gate_writes() -> None:
    """The decision and the tool name the same accepted implementation."""
    assert gate.IMPLEMENTATION_COMMIT in ADR_TEXT
    assert gate.IMPLEMENTATION_TREE in ADR_TEXT


# -- the rejected alternatives ------------------------------------------------

REJECTED: Final[tuple[str, ...]] = (
    "Leave `environment_binding_sha256` as a grammar-checked field",
    "Redesignate the applied secret-access receipt as the environment binding",
    "Redesignate the private Terraform input as the environment binding",
    "Let Run A capture the values itself when the runtime binding is absent",
    "Resolve the environment binding from its own environment variable inside the validator",
    "Discover the artifact by listing the private directory, or by taking the newest file",
    "Accept a raw bucket or account environment variable for materialization",
    "Overwrite an occupied destination",
    "Give the capture and the materialization one command with two modes",
    "Write the artifact with a second, tool-local notion of owner-only permissions",
    "Take the digest over a re-serialisation of the parsed document",
)


@pytest.mark.parametrize("alternative", REJECTED)
def test_every_required_alternative_is_explicitly_rejected(alternative: str) -> None:
    assert alternative in ADR_FLAT, alternative
    assert "Rejected:" in ADR_FLAT


# -- what must not have moved -------------------------------------------------


def test_the_runtime_binding_schema_is_unchanged() -> None:
    """One field gained a meaning. No field was added, removed or renamed."""
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
    assert rb._PROVENANCE_FIELDS == frozenset(
        {"implementation_commit", "implementation_tree", "environment_binding_sha256"}
    )
    assert rb.RUNTIME_BINDING_SCHEMA_VERSION == 1
    assert rb.RUNTIME_BINDING_KIND == "kalpamani-qualification-runtime"
    assert rb.RUNTIME_BINDING_CONTRACT_ID == "qualification-runtime-binding/v1"


def test_the_two_contracts_cannot_be_confused_by_kind_or_identifier() -> None:
    """Distinctness through a set rather than an inequality.

    Both constants are literal-typed, so a direct ``!=`` is a comparison the type
    checker can decide -- and refuses as non-overlapping. The set is the same
    question asked in a form it will evaluate at runtime.
    """
    kinds: set[str] = {rb.ENVIRONMENT_BINDING_KIND, rb.RUNTIME_BINDING_KIND}
    contracts: set[str] = {
        rb.ENVIRONMENT_BINDING_CONTRACT_ID,
        rb.RUNTIME_BINDING_CONTRACT_ID,
    }
    assert len(kinds) == 2
    assert len(contracts) == 2


def test_the_acquisition_policy_still_denies_every_object_read() -> None:
    """A new artifact must not have widened the actor it is delivered to."""
    policies = " ".join(POLICIES.read_text(encoding="utf-8").split())
    assert "AcquisitionNeverReadsOrDeletes" in policies
    for action in ('"s3:GetObject"', '"s3:GetObjectVersion"', '"s3:GetObjectAttributes"'):
        assert action in policies, action
    assert "AcquisitionNeverEnumeratesTheLicensedStore" in policies


def test_the_public_bucket_outcome_and_exit_code_are_unchanged() -> None:
    acquire = ACQUIRE.read_text(encoding="utf-8")
    assert 'REFUSED_LICENSED_BUCKET = "empirical acquisition refused: licensed configuration"' in (
        acquire
    )
    assert "EmpiricalOutcome.REFUSED_LICENSED_BUCKET: 8," in acquire


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


def test_the_earlier_decision_still_defers_the_materialization_gate() -> None:
    """ADR-0023's own text is not edited to know the gate now exists."""
    earlier = " ".join(ADR_0023.read_text(encoding="utf-8").split())
    assert "A separate, foundation-authorized materialization gate must create the real file" in (
        earlier
    )


# -- the status document agrees -----------------------------------------------

REQUIRED_STATUS: Final[tuple[str, ...]] = (
    "environment-binding contract:                 IMPLEMENTED / OFFLINE-VALIDATED",
    "environment-binding producer:                 IMPLEMENTED / OFFLINE-VALIDATED / NEVER RUN",
    "runtime-binding materialization gate:         IMPLEMENTED / OFFLINE-VALIDATED / NEVER RUN",
    "real environment binding:                     NOT MATERIALIZED",
    "real private runtime binding:                 NOT MATERIALIZED",
    "Terraform reachable from Run A:               NO",
    "operator tools reachable from Run A:          NO",
    "Run A:                                        BLOCKED PENDING MATERIALIZATION AND REVIEW",
)


@pytest.mark.parametrize("line", REQUIRED_STATUS)
def test_both_the_adr_and_the_status_document_carry_the_status_lines(line: str) -> None:
    assert line in ADR_TEXT, line
    assert line in SECTION, line


def test_the_status_section_keeps_every_downstream_gate_closed() -> None:
    for line in (
        "environment-binding capture:                  NOT AUTHORIZED / NOT RUN",
        "runtime-binding materialization:              NOT AUTHORIZED / NOT RUN",
        "binding preflight:                            NOT AUTHORIZED / NOT RUN",
        "execution-identifier allocation:              NOT AUTHORIZED / NOT PERFORMED",
        "Run B / combined assessment:                  NOT AUTHORIZED / NOT RUN",
        "G1 / G2:                                      OPEN / OPEN",
        "provider selected:                            NONE",
        "Phase 3:                                      NOT COMPLETE",
        "CONTROL:                                      DEFERRED",
        "live trading:                                 HARD-DISABLED",
        "new execution identifiers:                    0",
    ):
        assert line in SECTION, line


def test_the_status_document_claims_no_authority_for_a_proposed_adr() -> None:
    flat = " ".join(SECTION.split())
    assert "carries no authority while its pull request is open" in flat
    assert "PROPOSED" in flat
    # The section may say what the ADR *becomes* on merge. It may not say it is there
    # already, and it may not claim either artifact exists or that a run may go.
    assert "On independent review and merge\nit becomes **ACCEPTED / IN FORCE**" in SECTION
    for claimed in (
        "ADR-0024 is **ACCEPTED",
        "ADR-0024: ACCEPTED",
        "ADR-0024 — ACCEPTED",
        "AUTHORIZED TO RUN",
        "binding: MATERIALIZED",
    ):
        assert claimed not in flat, claimed


# -- nothing private reaches Git ----------------------------------------------

TRACKED_SURFACES: Final[tuple[Path, ...]] = (ADR, CONTRACT, WRITER, CAPTURE, GATE, ACQUIRE)


@pytest.mark.parametrize("path", TRACKED_SURFACES, ids=lambda path: path.name)
def test_no_new_surface_carries_a_private_identifier(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for marker in ("arn:aws:", "amazonaws.com", "AKIA", ".amazonaws", "awsapps.com"):
        assert marker not in text, marker
    assert re.search(r"\b\d{12}\b", text) is None
    assert "sap4n" not in text
