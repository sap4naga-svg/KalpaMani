"""ADR-0021 is a PROPOSAL, and every guard here holds it to exactly that.

PR #52 merged two qualification permission-set declarations and deliberately left
them unheld, because accepted authority determined no runtime trust principal.
ADR-0021 chooses one -- IAM Identity Center permission-set roles, two permission
sets, two profiles, one governed operator group -- and chooses **nothing else**.

Three drifts follow from that shape, and each is guarded here:

1. **Forwards, into acceptance** -- a proposal read as an accepted decision.
   ADR-0021 must carry its conditional status line, must be absent from
   ``MERGED_ADR_STATUS``, and must claim no in-force row in either status
   document.
2. **Forwards, into infrastructure** -- an accepted decision read as a deployed
   one. No permission set, assignment, role, attachment or profile exists, and
   whether any live AWS object exists is deliberately **not established**, because
   establishing it would take a call nobody authorized.
3. **Sideways, into a weaker identity** -- the two actors collapsed into one, a
   service or IAM-user principal substituted, a profile name treated as proof, or
   a full generated role ARN pinned through a suffix rotation.

**Every guard has a mutation test behind it.** A required phrase that no edit can
remove is a phrase that proves nothing, so each load-bearing clause is deleted or
inverted in a copy of the real document and the **audit's own** requirement list
is required to notice. The registry mutation drives an AST parse over **mutated
audit source** rather than a local dictionary, because a dictionary compared
against itself is not a check.

**The arithmetic is derived here, not transcribed.** The request count, the write
counts and every envelope are recomputed from the locked constants in
``kalpamani.data.qualify.sharadar`` and compared against what the ADR says, so a
number edited in prose fails rather than agreeing with its own copy.

These are text and structure checks over committed files. **Nothing here contacts
AWS, a provider or a network**, nothing imports an operational entry point, and
nothing mutates a tracked file -- every mutation is applied to an in-memory copy.
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

from kalpamani.data.qualify.sharadar.operations import MAX_LOCATOR_ATTEMPTS
from kalpamani.data.qualify.sharadar.plan import (
    BRONZE_OPERATIONS_PER_REQUEST,
    EMPIRICAL_REQUEST_COUNT,
)

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ADR = (
    PROJECT_ROOT
    / "docs"
    / "decisions"
    / "ADR-0021-qualification-runtime-principal-and-trust-model.md"
)
CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"
README = PROJECT_ROOT / "README.md"
PLAN = PROJECT_ROOT / "docs" / "phase3" / "implementation-plan.md"
AUDIT = PROJECT_ROOT / "scripts" / "phase3_docs_audit.py"

#: The two acquisition executions the combined assessment reads.
EXECUTIONS: Final = 2

#: One conditional report write, and at most one metadata confirmation after a 412.
REPORT_PUT: Final = 1
REPORT_HEAD_MAX: Final = 1


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

#: The heading each document's ADR-0021 section must be followed by. Read from the
#: audit rather than restated, so a test cannot disagree with the guard about
#: where the section ends.
TERMINATORS: Final[dict[str, str]] = dict(GUARD.ADR_0021_SECTION_TERMINATORS)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def flat(text: str) -> str:
    """Whitespace-collapsed, emphasis-stripped, lowercased -- the audit's own reading."""
    return " ".join(text.replace("**", "").split()).lower()


def missing(required: Iterable[tuple[str, str]], text: str) -> list[str]:
    """Every required clause the text does not carry, by label."""
    reading = flat(text)
    return [label for label, phrase in required if phrase not in reading]


def overstated(forbidden: Iterable[str], text: str) -> list[str]:
    """Every forbidden claim the text does carry."""
    reading = flat(text)
    return [claim for claim in forbidden if claim in reading]


def clause(label: str, required: Iterable[tuple[str, str]]) -> str:
    """The exact phrase a labelled requirement asserts, read from the audit.

    Read rather than restated: a mutation test that deleted its own copy of a
    phrase would prove nothing about the phrase the audit actually looks for.
    """
    for candidate, phrase in required:
        if candidate == label:
            return phrase
    raise AssertionError(f"no requirement labelled {label!r}")


def scan(text: str) -> Any:
    """The audit's own extractor, driven rather than reimplemented."""
    return GUARD.scan_adr_0021_status_sections(text)


def split_at_section(document: Path) -> tuple[str, str, str]:
    """``(before, section, after)`` for a document's one ADR-0021 status section."""
    text = read(document)
    found = scan(text)
    assert len(found.sections) == 1, f"{document.name}: {len(found.sections)} sections"
    section = str(found.sections[0])
    before, separator, after = text.partition(section)
    assert separator == section, document.name
    return before, section, after


def rebuild(before: str, section: str, after: str) -> str:
    return before + section + after


def without(text: str, phrase: str) -> str:
    """``text``, flattened, with one required phrase deleted.

    Asserts the phrase was present first: a mutation that removes nothing proves
    nothing, and a guard that then reports the clause missing is reporting on a
    document that never carried it.
    """
    reading = flat(text)
    assert phrase in reading, f"the mutation target must exist: {phrase!r}"
    return reading.replace(phrase, "")


def registry_from_source(source: str) -> tuple[tuple[str, str], ...]:
    """``MERGED_ADR_STATUS`` read by static parse of the given audit source.

    Parsed from source text rather than imported, so a mutation test can feed it
    *modified* source and drive the real parse over it. Importing the loaded
    module instead would compare a dictionary against itself.
    """
    tree = ast.parse(source)
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
    raise AssertionError("MERGED_ADR_STATUS not found in the audit source")


# ---------------------------------------------------------------------------
# The proposal itself
# ---------------------------------------------------------------------------


def test_the_adr_exists_at_its_exact_path() -> None:
    """One decision, one file name, and the audit points at the same one."""
    assert ADR.is_file()
    assert GUARD.ADR_0021 == ADR


def test_the_adr_carries_its_proposed_status_line() -> None:
    """PROPOSED, with the merge condition spelled out rather than implied."""
    reading = flat(read(ADR))
    assert (
        "status: proposed — no authority until the pull request introducing this adr is "
        "independently reviewed and merged" in reading
    )
    assert (
        "while the pull request introducing this adr is open, adr-0021 is proposed and carries "
        "no authority" in reading
    )


def test_the_adr_supersedes_nothing_and_amends_no_earlier_adr() -> None:
    """A narrowing decision, not a rewrite of the three it follows."""
    reading = flat(read(ADR))
    assert "it supersedes no prior adr" in reading
    assert "amends the text of none of them" in reading


def test_the_audit_requires_every_clause_this_file_checks() -> None:
    """The two guards agree, so neither can be weakened while the other passes.

    Not a tautology: this compares the *audit's* requirement list against the
    committed ADR, which is the same comparison the audit performs and a
    different one from every phrase asserted above.
    """
    assert not missing(GUARD.ADR_0021_SELF_REQUIRED, read(ADR))
    assert len(GUARD.ADR_0021_SELF_REQUIRED) > 0


def test_the_adr_carries_every_decision_table_case_and_rejected_alternative() -> None:
    """Eighteen identity cases and ten rejected alternatives, each individually."""
    reading = read(ADR)
    assert not missing(GUARD.ADR_0021_DECISION_CASES, reading)
    assert not missing(GUARD.ADR_0021_REJECTED_ALTERNATIVES, reading)
    assert len(GUARD.ADR_0021_DECISION_CASES) == 18
    assert len(GUARD.ADR_0021_REJECTED_ALTERNATIVES) == 10


# ---------------------------------------------------------------------------
# Proposed, and not registered as merged
# ---------------------------------------------------------------------------


def test_the_registry_does_not_record_adr_0021_as_merged() -> None:
    """A proposal is not in force, so it is absent from the merged-ADR registry."""
    registry = dict(registry_from_source(read(AUDIT)))
    assert "ADR-0021" not in registry
    assert "ADR-0020" in registry, "the registry must still govern the merged ADRs"


def test_registering_adr_0021_as_merged_is_caught() -> None:
    """Driven over *mutated audit source*, not a mutated local dictionary."""
    source = read(AUDIT)
    anchor = '    ("ADR-0020", "PR #49 merged"),'
    assert anchor in source, "the mutation target must exist"
    mutated = source.replace(anchor, anchor + '\n    ("ADR-0021", "PR #99 merged"),', 1)
    registry = dict(registry_from_source(mutated))
    assert "ADR-0021" in registry, "the mutation must actually register it"
    assert registry["ADR-0021"] == "PR #99 merged"


@pytest.mark.parametrize(
    "injected",
    [
        "adr-0021: accepted",
        "adr-0021: in force",
        "adr-0021: merged",
        "adr-0021: effective",
        "adr-0021 is accepted",
        "adr-0021 architecture: accepted / in force",
    ],
)
def test_claiming_the_proposal_is_accepted_is_caught(injected: str) -> None:
    """Forwards drift into acceptance, in the audit's own denylist."""
    mutated = flat(read(CLAUDE_MD)) + " " + injected
    assert injected in overstated(GUARD.ADR_0021_STATUS_FORBIDDEN, mutated)


@pytest.mark.parametrize(
    "injected",
    [
        "identity center permission sets: created",
        "account assignments: created",
        "runtime roles: created",
        "runtime roles: live",
        "runtime trust principals: selected in aws",
        "policy attachments: created",
        "profiles: created",
        "profiles: inspected",
        "a principal has received aws authority",
        "the qualification runtime role exists in aws",
        "qualification infrastructure is ready",
        "deployment is unblocked",
        "terraform access is authorized",
        "aws access is authorized",
        "terraform has been run",
        "run a: authorized",
        "run b: authorized",
        "g1: closed",
        "g2: closed",
        "phase 3: complete",
        "control: published",
        "live trading: enabled",
    ],
)
def test_claiming_a_live_resource_or_a_later_gate_is_caught(injected: str) -> None:
    """Forwards drift into deployment, and into every gate this proposal does not open."""
    mutated = flat(read(CLAUDE_MD)) + " " + injected
    assert injected in overstated(GUARD.ADR_0021_STATUS_FORBIDDEN, mutated)


@pytest.mark.parametrize(
    "injected",
    [
        "adr-0021: absent",
        "adr-0021 does not exist",
        "no runtime principal has been proposed",
        "no trust model has been proposed",
        "the runtime principal question is unanswered by any proposal",
    ],
)
def test_reverting_to_no_proposal_is_caught(injected: str) -> None:
    """Backwards drift: the pre-proposal wording may not be reinstated silently."""
    mutated = flat(read(CLAUDE_MD)) + " " + injected
    assert injected in overstated(GUARD.ADR_0021_STATUS_FORBIDDEN, mutated)


@pytest.mark.parametrize(
    "injected",
    [
        "an iam user is authorized for qualification",
        "a shared qualification role",
        "the qualification actors share one role",
        "the runtime principal is an ecs task role",
        "the runtime principal is a lambda execution role",
        "the runtime principal is an ec2 instance profile",
        "the runtime principal is an oidc principal",
        "a custom role chain is chosen",
        "application assumerole is chosen",
        "the profile name proves the identity",
        "the profile name is the identity proof",
        "the full generated role arn is pinned permanently",
    ],
)
def test_substituting_a_weaker_principal_or_proof_is_caught(injected: str) -> None:
    """Sideways drift: a different principal, a shared actor, or a weaker proof."""
    mutated = flat(read(CLAUDE_MD)) + " " + injected
    assert injected in overstated(GUARD.ADR_0021_STATUS_FORBIDDEN, mutated)


def test_the_committed_documents_carry_no_forbidden_claim() -> None:
    """The denylist has to be satisfiable by a correct document, or it gets deleted."""
    for document in (ADR, CLAUDE_MD, README, PLAN):
        assert not overstated(GUARD.ADR_0021_STATUS_FORBIDDEN, read(document)), document.name


# ---------------------------------------------------------------------------
# Removing an identity binding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "names identity center as the authentication root",
        "names the governed operator group",
        "names the acquisition permission set",
        "names the assessment permission set",
        "assigns each permission set to the group in one account",
        "names the acquisition profile",
        "names the assessment profile",
        "binds account and role prefix",
        "keeps the suffix grammar structural",
        "records suffix rotation",
    ],
)
def test_removing_an_identity_binding_is_caught(label: str) -> None:
    """Each binding individually: Identity Center, group, permission set, account,
    profile, role prefix and suffix grammar."""
    phrase = clause(label, GUARD.ADR_0021_SELF_REQUIRED)
    mutated = without(read(ADR), phrase)
    assert label in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)


def test_collapsing_the_two_permission_sets_into_one_is_caught() -> None:
    """One name substituted for the other leaves the second unreferenced."""
    reading = flat(read(ADR))
    acquisition = GUARD.ADR_0021_ACQUISITION_PERMISSION_SET.lower()
    assessment = GUARD.ADR_0021_ASSESSMENT_PERMISSION_SET.lower()
    assert acquisition in reading and assessment in reading
    mutated = reading.replace(assessment, acquisition)
    assert "names the assessment permission set" in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)


def test_collapsing_the_two_profiles_into_one_is_caught() -> None:
    """The same collapse at the profile layer, where the SDK resolves credentials."""
    reading = flat(read(ADR))
    acquisition = GUARD.ADR_0021_ACQUISITION_PROFILE
    assessment = GUARD.ADR_0021_ASSESSMENT_PROFILE
    assert acquisition in reading and assessment in reading
    mutated = reading.replace(assessment, acquisition)
    assert "names the assessment profile" in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)


def test_swapping_the_actor_to_profile_mapping_is_caught() -> None:
    """Acquisition must accept acquisition, and assessment assessment -- not the reverse."""
    phrase = clause("binds each entry point to its own actor", GUARD.ADR_0021_SELF_REQUIRED)
    reading = flat(read(ADR))
    assert phrase in reading
    swapped = (
        "the acquisition entry point accepts only the assessment permission-set role identity, "
        "and assessment accepts only acquisition"
    )
    mutated = reading.replace(phrase, swapped)
    assert "binds each entry point to its own actor" in missing(
        GUARD.ADR_0021_SELF_REQUIRED, mutated
    )


def test_replacing_temporary_credentials_with_static_ones_is_caught() -> None:
    """The refusal of IAM users and long-lived keys is a clause, not an implication."""
    phrase = clause("refuses iam users and long-lived keys", GUARD.ADR_0021_SELF_REQUIRED)
    mutated = without(read(ADR), phrase)
    assert "refuses iam users and long-lived keys" in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)


def test_introducing_a_custom_principal_or_chain_is_caught() -> None:
    """One clause rejects every custom, chained and service principal at once."""
    phrase = clause("rejects every custom principal", GUARD.ADR_0021_SELF_REQUIRED)
    mutated = without(read(ADR), phrase)
    assert "rejects every custom principal" in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)


def test_claiming_the_profile_name_is_proof_is_caught() -> None:
    """Removing the refusal is caught, and asserting the opposite is caught too."""
    phrase = clause("refuses profile name as proof", GUARD.ADR_0021_SELF_REQUIRED)
    mutated = without(read(ADR), phrase)
    assert "refuses profile name as proof" in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)
    injected = "the profile name proves the identity"
    assert injected in overstated(
        GUARD.ADR_0021_STATUS_FORBIDDEN, flat(read(CLAUDE_MD)) + " " + injected
    )


def test_pinning_one_full_generated_arn_forever_is_caught() -> None:
    """Suffix rotation is documented AWS behaviour, so a pinned ARN is a defect."""
    phrase = clause("refuses to pin one full arn", GUARD.ADR_0021_SELF_REQUIRED)
    mutated = without(read(ADR), phrase)
    assert "refuses to pin one full arn" in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)
    injected = "the full generated role arn is pinned permanently"
    assert injected in overstated(
        GUARD.ADR_0021_STATUS_FORBIDDEN, flat(read(CLAUDE_MD)) + " " + injected
    )


def test_removing_the_one_hour_session_bound_is_caught() -> None:
    """Both halves: the bound itself, and the reason it is enough."""
    for label in ("bounds the session to one hour", "explains the session bound"):
        phrase = clause(label, GUARD.ADR_0021_SELF_REQUIRED)
        mutated = without(read(ADR), phrase)
        assert label in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)


def test_weakening_exact_account_binding_is_caught() -> None:
    """Account-only binding is what exists today; this contract is strictly narrower."""
    phrase = clause("binds account and role prefix", GUARD.ADR_0021_SELF_REQUIRED)
    reading = flat(read(ADR))
    assert phrase in reading
    weakened = "the identity gate binds the exact target account"
    mutated = reading.replace(phrase, weakened)
    assert "binds account and role prefix" in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)


def test_removing_the_deferred_environment_bindings_is_caught() -> None:
    """The group identifier and the account id stay unknown and unread."""
    for label in ("defers the group identifier", "defers the account id"):
        phrase = clause(label, GUARD.ADR_0021_SELF_REQUIRED)
        mutated = without(read(ADR), phrase)
        assert label in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)


@pytest.mark.parametrize("label", [label for label, _ in GUARD.ADR_0021_DECISION_CASES])
def test_removing_any_identity_decision_case_is_caught(label: str) -> None:
    """Eighteen cases, each required individually rather than counted."""
    phrase = clause(label, GUARD.ADR_0021_DECISION_CASES)
    mutated = without(read(ADR), phrase)
    assert label in missing(GUARD.ADR_0021_DECISION_CASES, mutated)


@pytest.mark.parametrize("label", [label for label, _ in GUARD.ADR_0021_REJECTED_ALTERNATIVES])
def test_removing_any_rejected_alternative_is_caught(label: str) -> None:
    """A design that names only the option it took has not shown its work."""
    phrase = clause(label, GUARD.ADR_0021_REJECTED_ALTERNATIVES)
    mutated = without(read(ADR), phrase)
    assert label in missing(GUARD.ADR_0021_REJECTED_ALTERNATIVES, mutated)


def test_removing_later_gate_separation_is_caught() -> None:
    """Architecture only, a named next gate, and three gates that never merge."""
    for label in (
        "authorizes architecture only",
        "names the next gate",
        "keeps the three gates separate",
        "grants no principal authority",
    ):
        phrase = clause(label, GUARD.ADR_0021_SELF_REQUIRED)
        mutated = without(read(ADR), phrase)
        assert label in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)


def test_removing_a_preserved_application_boundary_is_caught() -> None:
    """Write-only, digest identity, ADR-0017, the schema and the arithmetic."""
    for label in (
        "preserves application behaviour",
        "adds no operation and no deadline term",
        "preserves the acquisition put range",
        "preserves zero acquisition head",
        "preserves zero acquisition get",
        "preserves the locator reserve",
        "preserves the admission rule",
    ):
        phrase = clause(label, GUARD.ADR_0021_SELF_REQUIRED)
        mutated = without(read(ADR), phrase)
        assert label in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)


def test_the_adr_preserves_the_write_only_and_digest_boundaries_by_name() -> None:
    """Named, so that "unchanged" is checkable rather than atmospheric."""
    reading = flat(read(ADR))
    assert "adr-0019 write-only acquisition" in reading
    assert "adr-0020 execution, request and digest scoped payload identity" in reading
    assert "assessment digest recomputation and key reconstruction" in reading
    assert "the durable locator schema" in reading
    assert "adr-0017, the shared store and ingestion behaviour" in reading


# ---------------------------------------------------------------------------
# The arithmetic, derived from the locked constants
# ---------------------------------------------------------------------------


def test_the_acquisition_arithmetic_is_derived_not_transcribed() -> None:
    """Recomputed from the locked plan constants, then compared against the prose."""
    bronze = EMPIRICAL_REQUEST_COUNT * BRONZE_OPERATIONS_PER_REQUEST
    low = bronze + 1
    high = bronze + MAX_LOCATOR_ATTEMPTS
    assert (EMPIRICAL_REQUEST_COUNT, bronze, low, high) == (48, 144, 145, 147)
    reading = flat(read(ADR))
    assert f"acquisition putobject: {low} to {high}" in reading
    assert f"two successful runs: {low * 2} to {high * 2}" in reading


def test_the_assessment_and_package_envelopes_are_derived_not_transcribed() -> None:
    """``E x (2R + 1)`` reads, one report write, and at most one confirmation."""
    reads = EXECUTIONS * (2 * EMPIRICAL_REQUEST_COUNT + 1)
    low = reads + REPORT_PUT
    high = reads + REPORT_PUT + REPORT_HEAD_MAX
    assert (reads, low, high) == (194, 195, 196)
    bronze = EMPIRICAL_REQUEST_COUNT * BRONZE_OPERATIONS_PER_REQUEST
    package_low = (bronze + 1) * 2 + low
    package_high = (bronze + MAX_LOCATOR_ATTEMPTS) * 2 + high
    assert (package_low, package_high) == (485, 490)
    reading = flat(read(ADR))
    assert f"assessment: {low} to {high}" in reading
    assert f"whole successful package: {package_low} to {package_high}" in reading


def test_editing_an_envelope_in_prose_is_caught() -> None:
    """The derived number and the written one must agree, so a prose edit fails."""
    reading = flat(read(ADR))
    phrase = "whole successful package: 485 to 490"
    assert phrase in reading
    mutated = reading.replace(phrase, "whole successful package: 485 to 780")
    assert "preserves the package envelope" in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)


# ---------------------------------------------------------------------------
# Identifier leakage
# ---------------------------------------------------------------------------


def test_the_committed_documents_expose_no_concrete_identifier() -> None:
    """The proposal says it carries no identifier. This is that claim, checked."""
    for document in (ADR, CLAUDE_MD, README, PLAN):
        assert not GUARD.adr_0021_identifier_leaks(read(document)), document.name


@pytest.mark.parametrize(
    ("label", "sample"),
    [
        ("account id", "sso_account_id = 123456789012"),
        ("access key id", "aws_access_key_id = AKIAIOSFODNN7EXAMPLE"),
        ("sso start url", "sso_start_url = https://my-sso-portal.awsapps.com/start"),
        (
            "account-bearing arn",
            "arn:aws:iam::123456789012:role/aws-reserved/sso.amazonaws.com/x",
        ),
    ],
)
def test_a_real_looking_identifier_in_a_sample_is_caught(label: str, sample: str) -> None:
    """A worked profile sample is exactly where a real value gets typed in."""
    leaks = GUARD.adr_0021_identifier_leaks(read(ADR) + "\n" + sample)
    assert any(found.startswith(label) for found in leaks), leaks


@pytest.mark.parametrize(
    "sample",
    [
        "sso_account_id = <target-account-id>",
        "sso_session = <governed-sso-session>",
        "region = <governed-region>",
        "sso_role_name = KalpaManiQualificationAcquisition",
        "AWSReservedSSO_<permission-set-name>_<aws-generated-suffix>",
        "no iam user or long-lived access key is permitted for qualification",
        "no live assignment, permission set, role or policy attachment exists",
        "IAM users are not permitted, and neither is any long-lived access key",
    ],
)
def test_placeholders_and_negative_statements_pass_the_scanner(sample: str) -> None:
    """A scanner that refused the proposal's own honest sentences would be deleted."""
    assert not GUARD.adr_0021_identifier_leaks(sample)


# ---------------------------------------------------------------------------
# Both status documents, independently and section-locally
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_each_document_carries_the_full_proposal_status(document: Path) -> None:
    """Independently, because merged main has twice carried a fact in one file
    and its contradiction in the other."""
    absent = missing(GUARD.ADR_0021_STATUS_REQUIRED, split_at_section(document)[1])
    assert not absent, f"{document.name} is missing from its ADR-0021 section: {absent}"


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_the_scan_is_section_local_not_document_wide(document: Path) -> None:
    """A clause deleted inside the section fails even though the file still has one.

    This is the property a flat document scan cannot provide: the phrase is
    re-inserted outside the section, so only a section-scoped reading notices.
    """
    phrase = clause("keeps both gates open", GUARD.ADR_0021_STATUS_REQUIRED)
    before, section, after = split_at_section(document)
    assert phrase in flat(section)
    stripped = flat(section).replace(phrase, "")
    assert phrase in flat(before + after) or phrase not in flat(stripped)
    assert "keeps both gates open" in missing(GUARD.ADR_0021_STATUS_REQUIRED, stripped)


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_exactly_one_section_with_no_structure_defects(document: Path) -> None:
    found = scan(read(document))
    assert len(found.sections) == 1, f"{document.name}: {len(found.sections)}"
    assert not found.defects, f"{document.name}: {found.defects}"


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
    renamed = lines[0].replace("ADR-0021", "ADR-0022").replace("principal", "principals")
    assert renamed != lines[0], "the heading must be alterable for this to prove anything"
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
def test_a_foreign_heading_inside_the_section_is_reported(document: Path) -> None:
    """A section that swallowed a neighbour is measuring somebody else's text."""
    before, section, after = split_at_section(document)
    injected = section.rstrip("\n") + "\n\n#### Not one of ours\n\n"
    found = scan(rebuild(before, injected, after))
    assert found.defects, f"{document.name}: a foreign subsection must be reported"


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_the_section_ends_at_its_declared_terminator(document: Path) -> None:
    """Both documents are terminated by the qualification-IAM heading."""
    terminator = TERMINATORS[document.name]
    _before, section, after = split_at_section(document)
    assert after.lstrip("\n").startswith(terminator), f"{document.name}: {after[:70]!r}"
    assert GUARD.qualification_iam_section_is_terminated(read(document), section, terminator)


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_demoting_the_terminating_heading_is_caught_as_boundary_drift(document: Path) -> None:
    """Deleting the boundary silently extends the section to the next one."""
    terminator = TERMINATORS[document.name]
    before, section, after = split_at_section(document)
    demoted = after.replace(terminator, "#### " + terminator[len("### ") :], 1)
    assert demoted != after, f"{document.name}: the terminator must be present to demote"
    found = scan(rebuild(before, section, demoted))
    assert not GUARD.qualification_iam_section_is_terminated(
        rebuild(before, section, demoted), str(found.sections[0]), terminator
    )


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_the_section_keeps_its_own_level_four_subsections(document: Path) -> None:
    """A ``####`` heading is deeper than the anchor, so it stays inside."""
    _before, section, _after = split_at_section(document)
    subsections = [line for line in section.splitlines() if line.startswith("#### ")]
    assert len(subsections) == len(GUARD.ADR_0021_STATUS_SUBSECTIONS), subsections
    for line in subsections:
        assert line[len("#### ") :].strip() in GUARD.ADR_0021_STATUS_SUBSECTIONS, line


def test_both_documents_carry_the_same_subsections_in_order() -> None:
    """Parity on structure: two documents whose sections have diverged are two answers."""
    titles = {
        document.name: GUARD._section_subsection_titles(scan(read(document)).sections)
        for document in (CLAUDE_MD, README)
    }
    assert len(set(titles.values())) == 1, titles
    assert titles["CLAUDE.md"] == tuple(GUARD.ADR_0021_STATUS_SUBSECTIONS)


def test_subsection_drift_between_the_documents_is_caught() -> None:
    """One document losing a subsection must not pass as parity."""
    claude = GUARD._section_subsection_titles(scan(read(CLAUDE_MD)).sections)
    drifted = claude[:-1]
    assert drifted != claude, "the mutation must actually drop a subsection"
    assert len({claude, drifted}) == 2


def test_the_two_sections_are_byte_identical() -> None:
    """The task requires byte-identical sections, and both sit at the same level."""
    _b1, claude, _a1 = split_at_section(CLAUDE_MD)
    _b2, readme, _a2 = split_at_section(README)
    assert claude == readme


@pytest.mark.parametrize("text", ["", "# Unrelated\n\nNothing to do with qualification.\n"])
def test_an_empty_or_unrelated_document_fails_every_required_list(text: str) -> None:
    """A guard that passes on an empty file is measuring nothing."""
    assert len(missing(GUARD.ADR_0021_STATUS_REQUIRED, text)) == len(GUARD.ADR_0021_STATUS_REQUIRED)
    assert len(missing(GUARD.ADR_0021_SELF_REQUIRED, text)) == len(GUARD.ADR_0021_SELF_REQUIRED)
    assert len(missing(GUARD.ADR_0021_PLAN_REQUIRED, text)) == len(GUARD.ADR_0021_PLAN_REQUIRED)
    assert scan(text).sections == ()


def test_the_scanner_carries_no_state_between_documents() -> None:
    """Pure and order-independent: two scans in either order give the same answer."""
    claude, readme = read(CLAUDE_MD), read(README)
    forward = (scan(claude).sections, scan(readme).sections)
    backward_readme = scan(readme).sections
    backward_claude = scan(claude).sections
    assert forward == (backward_claude, backward_readme)
    assert scan("").sections == ()
    assert scan(claude).sections == forward[0]


# ---------------------------------------------------------------------------
# The implementation plan
# ---------------------------------------------------------------------------


def test_the_plan_records_the_proposal() -> None:
    absent = missing(GUARD.ADR_0021_PLAN_REQUIRED, read(PLAN))
    assert not absent, f"the implementation plan is missing: {absent}"


@pytest.mark.parametrize(
    "label",
    [
        "records the proposed status",
        "names the chosen model",
        "refuses to assert live role existence",
        "records that no authority was granted",
        "keeps the three gates separate",
    ],
)
def test_removing_a_plan_clause_is_caught(label: str) -> None:
    phrase = clause(label, GUARD.ADR_0021_PLAN_REQUIRED)
    mutated = without(read(PLAN), phrase)
    assert label in missing(GUARD.ADR_0021_PLAN_REQUIRED, mutated)
