"""ADR-0021 is ACCEPTED ARCHITECTURE, and every guard here holds it to exactly that.

PR #52 merged two qualification permission-set declarations and deliberately left
them unheld, because accepted authority determined no runtime trust principal.
ADR-0021 chooses one -- IAM Identity Center permission-set roles, two permission
sets, two profiles, one governed operator group -- and chooses **nothing else**.
**PR #54 merged it**, so the architecture is accepted and **nothing is
implemented**.

**The guards were inverted on that merge, not deleted.** Every assertion that held
the proposal state has a one-for-one replacement asserting the accepted state and
refusing a return to the proposal wording, so neither direction is left unguarded
-- the treatment ADR-0017, ADR-0018, ADR-0019 and ADR-0020 were each given.

Three drifts follow from that shape, and each is guarded here:

1. **Backwards, out of acceptance** -- an accepted decision read back down into a
   proposal. ADR-0021 must carry its **preserved** conditional status line **and**
   the adjacent post-merge note, must be registered in ``MERGED_ADR_STATUS`` at
   the exact pull request, and must claim an in-force row in **both** status
   documents.
2. **Forwards, into infrastructure** -- an accepted decision read as a deployed
   one. No permission set, assignment, role, attachment or profile exists, and
   whether any live AWS object exists is deliberately **not established**, because
   establishing it would take a call nobody authorized. Merging an architecture
   decision granted no authority and opened no gate.
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

#: The registry line that records ADR-0021's merge, quoted once so a mutation
#: test can remove or forge it in a copy of the real audit source. Built from
#: the audit's own pull-request constant rather than retyped.
REGISTRY_ANCHOR: Final = '    ("ADR-0021", "PR #54 merged"),\n'

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


def test_the_adr_preserves_its_conditional_status_line() -> None:
    """The conditional text the ADR was written with, kept rather than rewritten.

    A decision record that edited its own status line to read "accepted" would
    have erased the state it moved out of, which is the one thing a decision
    record exists not to do.
    """
    reading = flat(read(ADR))
    assert (
        "status: proposed — no authority until the pull request introducing this adr is "
        "independently reviewed and merged" in reading
    )
    assert (
        "while the pull request introducing this adr is open, adr-0021 is proposed and carries "
        "no authority" in reading
    )


def test_the_adr_carries_the_adjacent_post_merge_note() -> None:
    """Accepted, with the merge identity spelled out rather than implied."""
    reading = flat(read(ADR))
    assert "the condition above has since been satisfied" in reading
    assert f"pr {GUARD.ADR_0021_PR} merged" in reading
    assert f"merge commit `{GUARD.ADR_0021_MERGE_COMMIT}`" in reading
    assert (
        f"ordered parents `{GUARD.ADR_0021_FIRST_PARENT}` then "
        f"`{GUARD.ADR_0021_APPROVED_HEAD}`" in reading
    )
    assert GUARD.ADR_0021_MERGED_AT.lower() in reading
    assert "adr-0021's conditional acceptance event has occurred" in reading
    assert "this adr is now accepted / in force, as architecture only" in reading
    assert GUARD.ADR_0021_HISTORICAL_PROPOSED in reading
    assert "no implementation or operational authority followed from the merge" in reading


@pytest.mark.parametrize(
    "label",
    [
        "records that the condition was satisfied",
        "names the merging pull request",
        "names the merge commit",
        "names the ordered parents",
        "records the identical merge tree",
        "records the acceptance event",
        "records the accepted status",
        "keeps the conditional line as history",
        "keeps the proposed period historical",
        "records that the merge approved architecture only",
        "records that no authority followed the merge",
    ],
)
def test_removing_a_post_merge_note_clause_is_caught(label: str) -> None:
    """Each half of the note individually, so none can be softened in place."""
    phrase = clause(label, GUARD.ADR_0021_SELF_REQUIRED)
    mutated = without(read(ADR), phrase)
    assert label in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)


@pytest.mark.parametrize(
    "constant",
    ["ADR_0021_MERGE_COMMIT", "ADR_0021_FIRST_PARENT", "ADR_0021_APPROVED_HEAD"],
)
def test_changing_the_merge_or_parent_identity_is_caught(constant: str) -> None:
    """A different commit or parent is a different merge, and must not pass."""
    real: str = getattr(GUARD, constant)
    forged = ("0" if real[0] != "0" else "1") + real[1:]
    assert forged != real
    mutated = flat(read(ADR)).replace(real, forged)
    assert forged in mutated, "the mutation must actually replace the identity"
    absent = missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)
    assert absent, f"a forged {constant} must fail at least one required clause"


def test_deleting_the_conditional_status_line_is_caught() -> None:
    """The preserved history is required, not merely tolerated."""
    for label in (
        "preserves the conditional status line",
        "preserves the pre-merge refusal of authority",
    ):
        phrase = clause(label, GUARD.ADR_0021_SELF_REQUIRED)
        mutated = without(read(ADR), phrase)
        assert label in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)


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
# Accepted, and registered as merged
# ---------------------------------------------------------------------------


def test_the_registry_records_adr_0021_as_merged() -> None:
    """Inverted on the merge: the decision is in force, so the registry governs it.

    The one-for-one replacement for the absence assertion this file carried while
    PR #54 was open. Driven over a static parse of the real audit source, so it is
    the audit's own registry that is read rather than a local copy of it.
    """
    registry = dict(registry_from_source(read(AUDIT)))
    assert registry.get("ADR-0021") == f"PR {GUARD.ADR_0021_PR} merged"
    assert "ADR-0020" in registry, "the registry must still govern the earlier ADRs"


def test_unregistering_or_misregistering_adr_0021_is_caught() -> None:
    """Driven over *mutated audit source*, not a mutated local dictionary.

    The inversion of the early-registration mutation this file carried while
    PR #54 was open: what must fail now is the entry going away, or naming a pull
    request that did not merge the decision.
    """
    source = read(AUDIT)
    anchor = REGISTRY_ANCHOR
    assert anchor in source, "the mutation target must exist"

    removed = dict(registry_from_source(source.replace(anchor, "", 1)))
    assert "ADR-0021" not in removed, "the mutation must actually unregister it"
    assert "ADR-0020" in removed, "the mutation must remove only ADR-0021"

    forged_anchor = anchor.replace("PR #54 merged", "PR #99 merged")
    assert forged_anchor != anchor
    forged = dict(registry_from_source(source.replace(anchor, forged_anchor, 1)))
    assert forged["ADR-0021"] == "PR #99 merged"
    assert forged["ADR-0021"] != f"PR {GUARD.ADR_0021_PR} merged"


@pytest.mark.parametrize(
    "injected",
    [
        "adr-0021: proposed / not in force",
        "adr-0021: not in force",
        "adr-0021: unmerged",
        "adr-0021: not effective",
        "adr-0021 is not accepted",
        "adr-0021 architecture: proposed only",
        "adr-0021's conditional acceptance event has not occurred",
        "runtime principal/trust architecture: proposed only",
        "pr #54 is open",
        "pr #54 remains open",
        "pr #54 is unmerged",
        "pr #54 has not been merged",
    ],
)
def test_reverting_adr_0021_to_the_proposal_state_is_caught(injected: str) -> None:
    """Backwards drift out of acceptance, in the audit's own denylist.

    The one-for-one replacement for the acceptance-drift refusals retired when
    PR #54 merged: each of those refused a claim that is now the truth, and each
    entry here refuses the proposal wording that entry used to protect.
    """
    mutated = flat(read(CLAUDE_MD)) + " " + injected
    assert injected in overstated(GUARD.ADR_0021_STATUS_FORBIDDEN, mutated)


@pytest.mark.parametrize(
    "injected",
    [
        "the merge implemented the permission sets",
        "the merge created the runtime roles",
        "the merge granted aws authority",
        "implementation followed from the merge",
        "deployment followed from the merge",
        "permission-set implementation: implemented",
        "identity center assignments: created",
        "customer-managed-policy attachments: implemented",
        "governed aws profiles: implemented",
        "identity-gate/profile-constant correction: implemented",
        "organization-instance prerequisite: satisfied",
        "aws account/group/instance binding values: known",
    ],
)
def test_claiming_something_followed_from_the_merge_is_caught(injected: str) -> None:
    """The merge approved architecture. It implemented, granted and deployed nothing."""
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
def test_each_document_carries_the_full_accepted_status(document: Path) -> None:
    """Independently, because merged main has twice carried a fact in one file
    and its contradiction in the other. One-for-one inversion of the proposal
    assertion this file carried while PR #54 was open."""
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


def test_the_plan_records_the_accepted_decision() -> None:
    """One-for-one inversion of the plan's proposal assertion."""
    absent = missing(GUARD.ADR_0021_PLAN_REQUIRED, read(PLAN))
    assert not absent, f"the implementation plan is missing: {absent}"


@pytest.mark.parametrize(
    "label",
    [
        "records the accepted status",
        "names the merging pull request",
        "keeps the proposed period historical",
        "records the satisfied architecture prerequisite",
        "refuses to read that prerequisite as authorization",
        "names the chosen model",
        "names what the next gate covers",
        "refuses to assert live role existence",
        "records the organization-instance prerequisite",
        "records the sts assumed-role caller form",
        "records that no authority was granted",
        "keeps the three gates separate",
    ],
)
def test_removing_a_plan_clause_is_caught(label: str) -> None:
    phrase = clause(label, GUARD.ADR_0021_PLAN_REQUIRED)
    mutated = without(read(PLAN), phrase)
    assert label in missing(GUARD.ADR_0021_PLAN_REQUIRED, mutated)


# ---------------------------------------------------------------------------
# The two zero-valued acquisition clauses, read as complete values
# ---------------------------------------------------------------------------
#
# The independent review found that a presence check --
# ``"acquisition headobject: 0" in text`` -- is answered by
# ``acquisition HeadObject: 0 to 145``, because the malformed extension contains
# the required phrase as a prefix. The audit now reads the **complete value** and
# compares it whole. These drive the audit's own scanner over in-memory copies of
# the real documents; no tracked file is touched.


def zero_defects(text: str) -> list[str]:
    """The audit's own complete-value reading, driven rather than reimplemented."""
    defects: list[str] = GUARD.acquisition_zero_operation_defects(text)
    return defects


@pytest.mark.parametrize(
    "document",
    [ADR, PLAN],
    ids=["ADR-0021", "implementation-plan.md"],
)
def test_the_committed_zero_statements_pass(document: Path) -> None:
    """A guard a correct document cannot satisfy is a guard that gets deleted."""
    assert zero_defects(read(document)) == []


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_the_committed_section_zero_statements_pass(document: Path) -> None:
    """Section-scoped, and satisfied by the section each document actually carries."""
    assert zero_defects(split_at_section(document)[1]) == []


@pytest.mark.parametrize("operation", ["HeadObject", "GetObject"])
def test_deleting_a_zero_statement_is_caught(operation: str) -> None:
    """A clause no text can fail is a clause that proves nothing, so absence fails."""
    reading = flat(read(ADR))
    target = f"acquisition {operation.lower()}: 0"
    assert target in reading, "the mutation target must exist"
    mutated = reading.replace(target, "")
    assert f"acquisition {operation.lower()}: absent" in zero_defects(mutated)


@pytest.mark.parametrize("operation", ["HeadObject", "GetObject"])
def test_changing_a_zero_to_one_is_caught(operation: str) -> None:
    """The value is read, not merely located."""
    reading = flat(read(ADR))
    target = f"acquisition {operation.lower()}: 0"
    assert target in reading
    mutated = reading.replace(target, f"acquisition {operation.lower()}: 1", 1)
    assert f"acquisition {operation.lower()}: 1" in zero_defects(mutated)


@pytest.mark.parametrize("operation", ["HeadObject", "GetObject"])
@pytest.mark.parametrize("extension", ["0 to 145", "0-145", "0 to 3"])
def test_extending_a_zero_into_a_range_is_caught(operation: str, extension: str) -> None:
    """The exact defect the review found: a prefix match accepts a whole range.

    ``acquisition HeadObject: 0 to 145`` contains ``acquisition headobject: 0``,
    so the presence entry alone passes while the statement means the opposite of
    zero. The complete-value reading refuses it.
    """
    reading = flat(read(ADR))
    target = f"acquisition {operation.lower()}: 0"
    assert target in reading
    mutated = reading.replace(target, f"acquisition {operation.lower()}: {extension}", 1)
    assert target in mutated, "the malformed extension must still contain the old prefix"
    assert f"acquisition {operation.lower()}: {extension}" in zero_defects(mutated)


def test_the_presence_entry_alone_would_not_have_caught_the_extension() -> None:
    """The hardening is load-bearing: the old reading passes what the new one fails."""
    mutated = flat(read(ADR)).replace(
        "acquisition headobject: 0", "acquisition headobject: 0 to 145", 1
    )
    presence = clause("preserves zero acquisition head", GUARD.ADR_0021_SELF_REQUIRED)
    assert presence in mutated, "the presence entry is satisfied by the malformed line"
    assert "preserves zero acquisition head" not in missing(GUARD.ADR_0021_SELF_REQUIRED, mutated)
    assert zero_defects(mutated), "the complete-value reading must refuse it"


@pytest.mark.parametrize("qualifier", ["exactly 0", "0"])
def test_an_honest_spelling_of_zero_passes(qualifier: str) -> None:
    """ADR-0019's own sections write "exactly 0"; refusing it would be a false failure."""
    assert (
        zero_defects(f"acquisition HeadObject: {qualifier}\nacquisition GetObject: {qualifier}")
        == []
    )


def test_head_and_get_are_not_confused_for_each_other() -> None:
    """Two clauses, independently required: neither answers for the other.

    A reading anchored only on ``: 0`` would let one zero-valued clause satisfy
    the guard for the other, so a deletion of exactly one would pass.
    """
    assert zero_defects("acquisition GetObject: exactly 0") == ["acquisition headobject: absent"]
    assert zero_defects("acquisition HeadObject: exactly 0") == ["acquisition getobject: absent"]
    both_wrong = zero_defects("acquisition HeadObject: exactly 0 acquisition GetObject: 0 to 145")
    assert both_wrong == ["acquisition getobject: 0 to 145"]


def test_a_neighbouring_sentence_is_not_swept_in() -> None:
    """``the acquisition role receives no s3:GetObject`` is not this claim."""
    assert (
        zero_defects(
            "the acquisition role receives no s3:GetObject, and no s3:GetObjectAttributes. "
            "acquisition HeadObject: 0, acquisition GetObject: 0"
        )
        == []
    )


def test_an_empty_document_fails_rather_than_passing_vacuously() -> None:
    """A scanner that finds nothing must report absence, not agreement."""
    assert sorted(zero_defects("")) == [
        "acquisition getobject: absent",
        "acquisition headobject: absent",
    ]


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_the_zero_reading_is_section_scoped(document: Path) -> None:
    """A range inside the ADR-0021 section fails even though another section is fine.

    Both documents legitimately carry ``acquisition HeadObject: exactly 0`` in
    ADR-0019's own status section a few hundred lines away. A document-wide
    reading would let that neighbour stand in for a section-local defect.
    """
    before, section, after = split_at_section(document)
    neighbour = before + after
    assert "acquisition headobject:" in flat(neighbour), "the neighbouring clause must exist"
    assert zero_defects(neighbour) == [], "and must itself be conformant"
    assert zero_defects(section) == []

    # A section-local deletion, answered by the neighbour under a document-wide
    # reading and reported under a section-scoped one. That difference is the
    # whole reason the scan is scoped to the section.
    stripped = section.replace("acquisition HeadObject: 0", "", 1)
    assert stripped != section, "the mutation must actually apply"
    assert "acquisition headobject: absent" in zero_defects(stripped)
    assert zero_defects(rebuild(before, stripped, after)) == []

    # And a section-local range, which a document-wide reading would also catch,
    # but which must be caught here rather than left to it.
    broken = section.replace("acquisition HeadObject: 0", "acquisition HeadObject: 0 to 145", 1)
    assert broken != section
    assert zero_defects(broken) == ["acquisition headobject: 0 to 145"]


# ---------------------------------------------------------------------------
# The carried-forward implementation findings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "requires an organization instance",
        "refuses to assert the instance exists",
        "defers the instance check to a later gate",
        "records the sts assumed-role caller form",
        "parses the runtime caller form",
        "binds the actor-specific prefix",
        "refuses loose matching",
        "refuses a permanently pinned arn",
        "refuses weaker proofs",
        "keeps the suffix grammar structural",
        "keeps get-caller-identity plus the contract as the proof",
    ],
)
@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_removing_a_carried_forward_finding_is_caught(document: Path, label: str) -> None:
    """Each finding clause individually, and section-locally in both documents."""
    phrase = clause(label, GUARD.ADR_0021_STATUS_REQUIRED)
    mutated = without(split_at_section(document)[1], phrase)
    assert label in missing(GUARD.ADR_0021_STATUS_REQUIRED, mutated)


def test_falsely_claiming_the_organization_instance_prerequisite_is_satisfied_is_caught() -> None:
    """Existence is NOT ESTABLISHED, and claiming otherwise would take an AWS call."""
    for injected in (
        "organization-instance prerequisite: satisfied",
        "organization-instance prerequisite: established",
    ):
        mutated = flat(read(CLAUDE_MD)) + " " + injected
        assert injected in overstated(GUARD.ADR_0021_STATUS_FORBIDDEN, mutated)


def test_replacing_the_sts_caller_form_with_the_iam_role_arn_is_caught() -> None:
    """``GetCallerIdentity`` returns an assumed-role ARN, not the generated role ARN.

    A gate written against the IAM role ARN would never match what STS returns, so
    substituting one for the other is the defect this clause exists to prevent.
    """
    label = "records the sts assumed-role caller form"
    phrase = clause(label, GUARD.ADR_0021_STATUS_REQUIRED)
    _before, section, _after = split_at_section(CLAUDE_MD)
    reading = flat(section)
    assert phrase in reading
    substituted = reading.replace(
        phrase,
        "`sts:getcalleridentity` returns an iam role arn of the form "
        "`arn:aws:iam::<account>:role/aws-reserved/sso.amazonaws.com/"
        "awsreservedsso_<permission-set-name>_<suffix>`",
        1,
    )
    assert label in missing(GUARD.ADR_0021_STATUS_REQUIRED, substituted)


@pytest.mark.parametrize(
    "weakened",
    [
        "the identity gate binds the exact target account",
        "the identity gate binds the exact permission-set role-name prefix",
        "the identity gate binds a validated aws-generated suffix grammar",
    ],
)
def test_weakening_the_account_prefix_suffix_conjunction_is_caught(weakened: str) -> None:
    """All three together, or the contract is not the one that was accepted."""
    label = "binds account and role prefix"
    phrase = clause(label, GUARD.ADR_0021_STATUS_REQUIRED)
    _before, section, _after = split_at_section(CLAUDE_MD)
    reading = flat(section)
    assert phrase in reading
    assert weakened != phrase, "a weakening must drop at least one conjunct"
    assert label in missing(GUARD.ADR_0021_STATUS_REQUIRED, reading.replace(phrase, weakened, 1))


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_a_section_local_deletion_survived_by_a_copy_elsewhere_is_caught(document: Path) -> None:
    """The phrase left standing outside the section must not answer for it.

    This is the property a flat document scan cannot provide, applied to a clause
    the accepted status turns on rather than to an incidental one.
    """
    label = "records the accepted status"
    phrase = clause(label, GUARD.ADR_0021_STATUS_REQUIRED)
    before, section, after = split_at_section(document)
    assert phrase in flat(section)
    stripped = flat(section).replace(phrase, "")
    elsewhere = flat(before + after) + " " + phrase
    assert phrase in elsewhere, "the copy must survive outside the section"
    assert label in missing(GUARD.ADR_0021_STATUS_REQUIRED, stripped)


# ---------------------------------------------------------------------------
# The implementation clauses PR #56 inverted
# ---------------------------------------------------------------------------
#
# ADR-0021 was accepted as architecture only, and its status block recorded seven
# clauses that read "not authorized / not implemented". PR #56 implemented the
# decision offline, so each of those describes a state the merge ended. They were
# inverted in the audit, one for one, and these drive the replacements.
#
# The three states stay apart in both directions: merged declarations, an isolated
# offline validation, and live AWS objects that still do not exist. Reverse drift
# -- a merged implementation written back to an unimplemented one -- is what a
# later synchronization is most likely to reintroduce, so it is driven too.

#: The labels PR #56's merge inverted, with what each must now say.
PR_56_INVERTED_CLAUSES: Final[tuple[tuple[str, str], ...]] = (
    ("records the merged permission-set implementation", "merged / offline-validated / dormant"),
    ("records the merged but uncreated assignments", "uncreated / existence not established"),
    ("refuses to assert live role existence", "uncreated / unobserved"),
    ("records the merged but uncreated attachments", "uncreated / existence not established"),
    ("records the unmaterialized profiles", "unmaterialized"),
    ("records the merged identity-gate correction", "merged / offline-validated / dormant"),
    ("scopes the isolated validation", "performed in external copies only"),
    ("closes terraform plan and apply", "not authorized / not run"),
)


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
@pytest.mark.parametrize("label", [label for label, _ in PR_56_INVERTED_CLAUSES])
def test_removing_an_inverted_implementation_clause_is_caught(document: Path, label: str) -> None:
    phrase = clause(label, GUARD.ADR_0021_STATUS_REQUIRED)
    _before, section, _after = split_at_section(document)
    reading = flat(section)
    assert phrase in reading, f"{document.name}: absent before removal: {phrase}"
    assert label in missing(GUARD.ADR_0021_STATUS_REQUIRED, reading.replace(phrase, ""))


@pytest.mark.parametrize(("label", "expected"), PR_56_INVERTED_CLAUSES)
def test_each_inverted_clause_says_what_the_merge_made_true(label: str, expected: str) -> None:
    """The inversion is real, and the replacement is not the old wording renamed."""
    phrase = clause(label, GUARD.ADR_0021_STATUS_REQUIRED)
    assert expected in phrase, label
    assert "not implemented" not in phrase, label
    assert "not created" not in phrase, label


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_the_merged_implementation_is_not_read_as_a_live_resource(document: Path) -> None:
    """Merged declarations, and no live permission set, assignment, role or profile."""
    _before, section, _after = split_at_section(document)
    reading = flat(section)
    assert "runtime roles: uncreated / unobserved" in reading
    assert "governed aws profiles: unmaterialized" in reading
    assert "authority granted: none" in reading
    assert (
        "organization-instance prerequisite: required / live existence not established" in reading
    )
    assert overstated(GUARD.ADR_0021_STATUS_FORBIDDEN, reading) == []


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_the_isolated_validation_is_not_read_as_plan_or_apply(document: Path) -> None:
    """Validation happened; plan and apply did not, and the two are separate clauses."""
    _before, section, _after = split_at_section(document)
    reading = flat(section)
    assert "terraform isolated init/validate: performed in external copies only" in reading
    assert "terraform plan/apply: not authorized / not run" in reading
    assert "infrastructure mutation and deployment: not authorized / not performed" in reading


@pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
def test_reverting_the_implementation_to_unimplemented_is_caught(document: Path) -> None:
    """Reverse drift: the merged implementation written back to an unimplemented one."""
    _before, section, _after = split_at_section(document)
    reading = flat(section)
    reverted = reading.replace(
        "permission-set implementation: merged / offline-validated / dormant",
        "permission-set implementation: not authorized / not implemented",
    )
    assert reverted != reading, "the mutation must actually replace the clause"
    assert "records the merged permission-set implementation" in missing(
        GUARD.ADR_0021_STATUS_REQUIRED, reverted
    )
