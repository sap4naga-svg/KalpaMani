"""ADR-0036 governance: a production principal design that declares, applies and runs nothing.

The decision designs the two production principals ADR-0035 §3.10 named -- a write-only
acquisition actor with one bounded secret grant and a research-build actor with exact reads and
no secret -- each as a human permission set plus an ECS task role. The checks here hold the
document to its own claims: it is proposed and not in force, it was produced without running
anything, it declares no Terraform and no policy under ``infra/``, it keeps the qualification
principals isolated and CONTROL deferred, and it carries no private value. The acceptance tests
it lists are checked for presence, not for satisfaction -- none is satisfied by its merge.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0036-production-data-plane-principals-and-trust-model.md"
ADR_0035: Final = DECISIONS / "ADR-0035-initial-breakout-long-research-dataset-ingestion-design.md"
INFRA: Final = PROJECT_ROOT / "infra"
README: Final = PROJECT_ROOT / "README.md"
CLAUDE: Final = PROJECT_ROOT / "CLAUDE.md"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""
ADR_FLAT: Final = " ".join(ADR_TEXT.split())

#: Names the design introduces. None may exist under ``infra/`` until the Terraform gate.
DESIGNED_NAMES: Final = (
    "kalpamani-production-acquisition",
    "kalpamani-research-build",
    "KalpaManiProductionAcquire",
    "KalpaManiResearchBuild",
    "KalpaManiTaskLauncher",
    "kalpamani-production-acquire-task",
    "kalpamani-research-build-task",
)

#: The pinned provider's permission-set name bound, as ADR-0022 records it.
PERMISSION_SET_NAME_LIMIT: Final = 32

TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")
HEX_40_OR_64: Final = re.compile(r"\b[0-9a-f]{40}\b|\b[0-9a-f]{64}\b")
REAL_ARN: Final = re.compile(r"\barn:aws\b")
IDENTIFIER_SHAPED: Final = re.compile(r"\b(?:runa|runb|assess)[a-z0-9]*-\d{8}-[a-z0-9]+\b")
SSO_START_URL: Final = re.compile(r"https?://[a-z0-9-]+\.awsapps\.com", re.IGNORECASE)


# -- existence and authority --------------------------------------------------


def test_the_adr_exists_at_its_exact_path() -> None:
    assert ADR.is_file()


def test_exactly_one_adr_0036_exists() -> None:
    assert [path.name for path in sorted(DECISIONS.glob("ADR-0036-*.md"))] == [ADR.name]


def test_the_adr_carries_a_conditional_acceptance_status() -> None:
    assert "Status: PROPOSED — NOT IN FORCE" in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "architecture and acceptance tests only" in ADR_FLAT


def test_the_adr_states_that_nothing_was_run_and_authorizes_no_implementation() -> None:
    assert "Nothing was run to produce this design" in ADR_FLAT
    assert "no Terraform command of any kind" in ADR_FLAT
    assert "Accepting this ADR authorizes no implementation and no execution" in ADR_FLAT
    assert "no Terraform declaration, plan or apply" in ADR_FLAT
    assert "five separate gates" in ADR_FLAT


def test_the_adr_supersedes_and_amends_nothing() -> None:
    assert "This ADR supersedes no earlier decision and amends no earlier ADR document" in ADR_FLAT


@pytest.mark.parametrize("number", [f"{n:04d}" for n in range(1, 35)])
def test_no_earlier_adr_mentions_this_one(number: str) -> None:
    earlier = sorted(DECISIONS.glob(f"ADR-{number}-*.md"))
    assert earlier, number
    for path in earlier:
        assert "ADR-0036" not in path.read_text(encoding="utf-8")


def test_adr_0035_names_this_one_only_in_its_post_merge_note() -> None:
    # ADR-0035 §3.10 left the production principals to a later gate; its post-merge note may
    # point forward to this design, but the decision text it was accepted with may not.
    text = ADR_0035.read_text(encoding="utf-8")
    note = text.index("The condition above has since been satisfied")
    assert "ADR-0036" not in text[:note]
    assert "ADR-0036" in text[note:]
    assert "itself proposed and not in force" in " ".join(text[note:].split())


def test_the_adr_is_built_on_adr_0035_and_the_accepted_trust_model() -> None:
    assert ADR_0035.name in ADR_TEXT
    assert "§3.10" in ADR_TEXT
    for earlier in ("ADR-0018", "ADR-0019", "ADR-0021", "ADR-0022", "ADR-0023"):
        assert earlier in ADR_TEXT, earlier


# -- the design itself --------------------------------------------------------


def test_the_two_actors_have_four_principals_and_no_long_lived_credential() -> None:
    assert "Two actors, four principals" in ADR_TEXT
    for name in DESIGNED_NAMES:
        assert f"`{name}`" in ADR_TEXT or f"({name})" in ADR_TEXT, name
    assert "No IAM user, no access key, no cross-account principal" in ADR_FLAT
    assert "`PT1H`" in ADR_TEXT


@pytest.mark.parametrize("name", ["KalpaManiProductionAcquire", "KalpaManiResearchBuild"])
def test_permission_set_names_fit_the_pinned_provider_bound(name: str) -> None:
    assert 1 <= len(name) <= PERMISSION_SET_NAME_LIMIT
    assert re.fullmatch(r"[\w+=,.@-]+", name) is not None
    assert f"`{name}` ({len(name)})" in ADR_TEXT


def test_the_acquisition_actor_is_write_only_with_one_bounded_secret() -> None:
    assert "bounded secret access, write-only Bronze" in ADR_TEXT
    assert "on exactly ONE secret ARN" in ADR_FLAT
    assert "the qualification secret is a different resource" in ADR_FLAT
    assert "it cannot read what it wrote, cannot list, cannot delete, cannot copy" in ADR_FLAT
    assert "DENY   s3:GetObject, s3:GetObjectVersion, s3:GetObjectAttributes" in ADR_TEXT


def test_the_build_actor_reads_exactly_and_holds_no_secret() -> None:
    assert "exact reads, licensed Silver/Gold writes, no secret" in ADR_TEXT
    assert "DENY   secretsmanager:*  (no secret of any kind)" in ADR_TEXT
    assert "no NAT and no internet egress" in ADR_FLAT
    assert "claims are validated from the locator, never read" in ADR_FLAT
    assert "Manifests stay LICENSED while CONTROL is deferred" in ADR_FLAT


def test_exact_object_references_come_from_a_run_locator_and_never_from_listing() -> None:
    assert "`licensed/bronze/sharadar/_indexes/<run-id>.json`" in ADR_TEXT
    assert "The build actor may not list" in ADR_FLAT
    assert "reads **only the objects it names**" in ADR_FLAT
    assert "no fallback that reconstructs by listing, probing or guessing" in ADR_FLAT
    assert "`read_exact`" in ADR_TEXT


def test_bindings_are_validated_by_one_loader_and_delivered_two_ways() -> None:
    for contract in (
        "kalpamani-production-acquisition-runtime-binding/v1",
        "kalpamani-research-build-runtime-binding/v1",
        "KALPAMANI_PRODUCTION_ACQUISITION_RUNTIME_BINDING_FILE",
        "KALPAMANI_RESEARCH_BUILD_RUNTIME_BINDING_FILE",
    ):
        assert contract in ADR_TEXT, contract
    assert "neither loads as a qualification binding" in ADR_FLAT
    assert "per-actor SSM `SecureString` parameter" in ADR_FLAT
    assert "The **same loader** validates the document" in ADR_FLAT
    assert "loading is not identity proof" in ADR_FLAT
    assert "Identity proof is unchanged in kind and extended in shape" in ADR_FLAT


def test_immutable_write_enforcement_is_claimed_only_as_far_as_it_can_be_proved() -> None:
    assert "`s3:if-none-match`" in ADR_TEXT
    assert (
        "to be verified against the pinned provider and API version at the Terraform gate"
        in ADR_FLAT
    )
    assert "rather than claiming enforcement it cannot prove" in ADR_FLAT
    assert "the bucket stays deletion-first" in ADR_FLAT


def test_ephemeral_compute_assumes_roles_only_through_a_gated_launcher() -> None:
    assert "How ephemeral compute assumes each role" in ADR_TEXT
    assert "ecs-tasks.amazonaws.com" in ADR_TEXT
    assert "no human and no other service can" in ADR_FLAT
    assert "no service, no schedule, no scaling group" in ADR_FLAT
    assert (
        "Launcher permission set, task definitions, images and subnets are each infrastructure"
        in ADR_FLAT
    )


def test_deletion_responsibilities_are_widened_and_still_cannot_read() -> None:
    assert "Unchanged in principle, widened in scope" in ADR_FLAT
    assert "cannot read any of them" in ADR_FLAT
    assert "Neither production actor can delete anything" in ADR_FLAT
    assert "the runbook never depends on one to discover licensed objects" in ADR_FLAT


def test_the_acceptance_tests_are_layered_and_present() -> None:
    for label in ("A-1", "A-2", "A-3", "A-4", "A-5", "A-6", "A-7", "A-8"):
        assert f"| {label} |" in ADR_TEXT, label
    assert "Offline, before any apply" in ADR_FLAT
    assert "Live, only under the application gate and its own authorization" in ADR_FLAT
    assert "Permitted — must succeed | Denied — must be refused" in ADR_TEXT
    assert (
        "A cell that cannot be exercised is recorded as not exercised, never as passed" in ADR_FLAT
    )


def test_qualification_stays_isolated_and_control_stays_deferred() -> None:
    assert "licensed/qualification/*" in ADR_TEXT
    assert "the qualification policies gain nothing" in ADR_FLAT
    assert "qualification principals and artifacts:       UNCHANGED / ISOLATED" in ADR_TEXT
    assert "CONTROL:                                      DEFERRED" in ADR_TEXT
    assert "first bounded ingestion:                      NOT AUTHORIZED / NOT RUN" in ADR_TEXT
    assert "live trading:                                 HARD-DISABLED" in ADR_TEXT


# -- nothing is declared, and nothing private is recorded ----------------------


def test_no_designed_name_exists_under_infra() -> None:
    files = [
        path
        for path in INFRA.rglob("*")
        if path.is_file() and path.suffix in {".tf", ".example", ".md", ".json"}
    ]
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in DESIGNED_NAMES:
            assert name not in text, f"{name} is designed, not declared: {path}"


def test_the_adr_carries_no_private_value() -> None:
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    assert HEX_40_OR_64.search(ADR_TEXT) is None
    assert REAL_ARN.search(ADR_TEXT) is None
    assert IDENTIFIER_SHAPED.search(ADR_TEXT) is None
    assert SSO_START_URL.search(ADR_TEXT) is None
    for word in ("PROCEED", "APPROVED", "QUALIFIED", "READY"):
        assert re.search(rf"\b{word}\b", ADR_TEXT) is None, word


# -- the status documents -----------------------------------------------------


@pytest.mark.parametrize("path", [README, CLAUDE])
def test_status_documents_record_the_adr_as_proposed(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "ADR-0036" in text
    assert re.search(r"ADR-0036[^\n]{0,200}PROPOSED — NOT IN FORCE", text) is not None
    assert "CONTROL stays DEFERRED" in text
