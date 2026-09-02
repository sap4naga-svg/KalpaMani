"""ADR-0022 is a PROPOSED naming correction, and every guard here holds it to exactly that.

ADR-0021 accepted an acquisition permission-set name of 33 characters. The pinned
``hashicorp/aws`` v6.62.0 provider validates ``aws_ssoadmin_permission_set.name``
to 1-32, so **the accepted architecture, not the implementation, is what cannot be
built**. PR #56 implemented ADR-0021 faithfully and is blocked by that, which is
why the correction is an ADR and not an edit to PR #56.

Three drifts follow from that shape, and each is guarded here:

1. **Forwards, out of proposal** -- a proposed decision read as an accepted one.
   ADR-0022 must carry its proposed status, must stay **absent** from
   ``MERGED_ADR_STATUS``, and must claim no in-force row in either status
   document.
2. **Forwards, into implementation** -- a blocked pull request read as corrected,
   ready, merged, deployed or operational, or infrastructure read as live. Nothing
   has been applied, and whether any live AWS object exists is deliberately **not
   established**.
3. **Backwards, into the defect** -- the retired 33-character name reinstated as
   the proposed or current replacement, or its historical framing removed so a
   reader cannot tell which name governs.

**The length is measured, never transcribed.** A constant recording a length
beside the value it describes agrees with itself, and that is precisely the check
PR #56 lacked. Every length assertion here drives ``len()`` over the real string,
and the provider-limit guard is driven over synthetic names at 31, 32 and 33
characters so it is proved to *measure* rather than to recognise one value.

**Every guard has a mutation test behind it.** A required phrase that no edit can
remove proves nothing, so each load-bearing clause is deleted or inverted in an
in-memory copy and the **audit's own** requirement list is required to notice. The
registry and constant mutations drive an AST parse over **mutated audit source**
rather than a local dictionary, because a value compared against itself is not a
check.

These are text, structure and pure-function checks over committed files.
**Nothing here contacts AWS, a provider, Terraform or a network**, nothing imports
an operational entry point, and nothing mutates a tracked file -- every mutation
is applied to an in-memory copy, and a digest test proves the tracked files are
untouched.
"""

from __future__ import annotations

import ast
import hashlib
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
ADR = PROJECT_ROOT / "docs" / "decisions" / "ADR-0022-qualification-permission-set-name-limit.md"
ADR_0021 = (
    PROJECT_ROOT
    / "docs"
    / "decisions"
    / "ADR-0021-qualification-runtime-principal-and-trust-model.md"
)
CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"
README = PROJECT_ROOT / "README.md"
PLAN = PROJECT_ROOT / "docs" / "phase3" / "implementation-plan.md"
AUDIT = PROJECT_ROOT / "scripts" / "phase3_docs_audit.py"

#: Every tracked file this module reads. Digested at import and re-digested by
#: :func:`test_no_tracked_file_is_modified_by_these_guards`, so a mutation that
#: escaped onto disk is caught however pytest orders this file.
TRACKED: Final[tuple[Path, ...]] = (ADR, ADR_0021, CLAUDE_MD, README, PLAN, AUDIT)

#: The two acquisition executions the combined assessment reads.
EXECUTIONS: Final = 2


def _audit_module() -> ModuleType:
    """Load the audit by path, to *run* its guards rather than restate them.

    ``scripts`` is not an importable package. The module is registered in
    ``sys.modules`` before execution because the audit defines a ``@dataclass``,
    and ``dataclasses`` resolves the defining module through that entry.

    Importing it defines constants and functions. It runs no check, opens no
    socket and reaches no service -- ``main()`` is behind the usual guard, and the
    module is loaded under a name that is not ``__main__``.
    """
    spec = importlib.util.spec_from_file_location("kalpamani_phase3_docs_audit_0022", AUDIT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GUARD = _audit_module()

#: The names under test, read from the audit rather than retyped so a test cannot
#: disagree with the guard about which value it is measuring.
RETIRED: Final[str] = GUARD.ADR_0022_RETIRED_ACQUISITION_PERMISSION_SET
PROPOSED: Final[str] = GUARD.ADR_0022_PROPOSED_ACQUISITION_PERMISSION_SET
ASSESSMENT: Final[str] = GUARD.ADR_0021_ASSESSMENT_PERMISSION_SET
ACQUISITION_PROFILE: Final[str] = GUARD.ADR_0021_ACQUISITION_PROFILE
ASSESSMENT_PROFILE: Final[str] = GUARD.ADR_0021_ASSESSMENT_PROFILE

#: The registry line ADR-0022 must **not** occupy, quoted once so a mutation test
#: can forge it in a copy of the real audit source.
REGISTRY_FORGERY: Final = '    ("ADR-0022", "PR #57 merged"),\n'

#: The line ``MERGED_ADR_STATUS`` really ends with, used as the forgery anchor.
REGISTRY_ANCHOR: Final = '    ("ADR-0021", "PR #54 merged"),\n'

#: Digests captured at import, before any mutation test has run.
_BASELINE_DIGESTS: Final[dict[str, str]] = {
    path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in TRACKED
}


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
    phrase would prove nothing about the phrase the audit looks for.
    """
    for candidate, phrase in required:
        if candidate == label:
            return phrase
    raise AssertionError(f"no requirement labelled {label!r}")


def scan(text: str) -> Any:
    """The audit's own extractor, driven rather than reimplemented."""
    return GUARD.scan_adr_0022_status_sections(text)


def split_at_section(document: Path) -> tuple[str, str, str]:
    """``(before, section, after)`` for a document's one ADR-0022 status section."""
    text = read(document)
    found = scan(text)
    assert len(found.sections) == 1, f"{document.name}: {len(found.sections)} sections"
    section = str(found.sections[0])
    before, separator, after = text.partition(section)
    assert separator == section, document.name
    return before, section, after


def without(text: str, phrase: str) -> str:
    """``text``, flattened, with one required phrase deleted.

    Asserts the phrase was present first: a mutation that removes nothing proves
    nothing, and a guard that then reports the clause missing is reporting on a
    document that never carried it.
    """
    reading = flat(text)
    assert phrase in reading, f"the mutation target must exist: {phrase!r}"
    return reading.replace(phrase, "")


def constant_from_source(source: str, name: str) -> Any:
    """One module-level constant, read by static parse of the given audit source.

    Parsed from source text rather than imported, so a mutation test can feed it
    *modified* source and drive the real parse over it. Importing the loaded
    module instead would compare a value against itself.
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
        if target == name and value is not None:
            return ast.literal_eval(value)
    raise AssertionError(f"{name} not found in the audit source")


def registry_from_source(source: str) -> tuple[tuple[str, str], ...]:
    """``MERGED_ADR_STATUS`` read by static parse of the given audit source."""
    registry: tuple[tuple[str, str], ...] = constant_from_source(source, "MERGED_ADR_STATUS")
    return registry


def synthetic_name(length: int) -> str:
    """An allowed-character permission-set name of exactly ``length`` characters."""
    name = ("KalpaManiQualificationSynthetic" * 4)[:length]
    assert len(name) == length
    return name


# ---------------------------------------------------------------------------
# Name constraints -- measured, never transcribed
# ---------------------------------------------------------------------------


def test_the_retired_acquisition_name_is_thirty_three_characters() -> None:
    """The value the provider refuses, measured from the string itself."""
    assert len(RETIRED) == 33
    assert RETIRED == "KalpaManiQualificationAcquisition"


def test_the_proposed_acquisition_name_is_twenty_nine_characters() -> None:
    """The value this ADR proposes, measured from the string itself."""
    assert len(PROPOSED) == 29
    assert PROPOSED == "KalpaManiQualificationAcquire"


def test_the_assessment_name_is_thirty_two_characters() -> None:
    """Exactly at the ceiling, which is why it was never the defect."""
    assert len(ASSESSMENT) == 32


def test_the_audit_length_constants_agree_with_the_measured_values() -> None:
    """The recorded lengths are checked against ``len()``, not trusted as prose."""
    assert GUARD.ADR_0022_PROPOSED_NAME_LENGTH == len(PROPOSED)
    assert GUARD.ADR_0022_RETIRED_NAME_LENGTH == len(RETIRED)


def test_the_provider_bounds_are_the_pinned_providers_own() -> None:
    """1-32, and the character grammar, as declared at ``hashicorp/aws`` v6.62.0."""
    assert (GUARD.PERMISSION_SET_NAME_MIN, GUARD.PERMISSION_SET_NAME_MAX) == (1, 32)
    assert GUARD.PERMISSION_SET_NAME_GRAMMAR.pattern == r"[\w+=,.@-]+"


def test_the_retired_name_is_refused_by_the_provider_limit_guard() -> None:
    """The defect, refused -- and refused on length rather than on characters."""
    defects = GUARD.permission_set_name_defects(RETIRED)
    assert defects
    assert any("33 characters" in defect for defect in defects)
    assert not any("grammar" in defect for defect in defects)


def test_the_proposed_name_passes_the_provider_limit_guard() -> None:
    assert GUARD.permission_set_name_defects(PROPOSED) == []


def test_the_assessment_name_passes_the_provider_limit_guard() -> None:
    assert GUARD.permission_set_name_defects(ASSESSMENT) == []


def test_an_empty_name_fails_on_both_clauses() -> None:
    """Zero characters is outside 1-32, and matches no grammar of one-or-more."""
    defects = GUARD.permission_set_name_defects("")
    assert len(defects) == 2
    assert any("0 characters" in defect for defect in defects)
    assert any("grammar" in defect for defect in defects)


def test_a_synthetic_thirty_three_character_name_fails() -> None:
    """Not the retired value -- a different name of the same length, so the guard
    is shown to refuse the *length* rather than to recognise one string."""
    name = synthetic_name(33)
    assert name != RETIRED
    assert GUARD.permission_set_name_defects(name)


def test_an_invalid_character_name_fails_on_the_grammar_alone() -> None:
    """A space is outside ``[\\w+=,.@-]`` and the name is short enough to pass length."""
    name = "KalpaMani Qualification"
    assert len(name) <= GUARD.PERMISSION_SET_NAME_MAX
    defects = GUARD.permission_set_name_defects(name)
    assert len(defects) == 1
    assert "grammar" in defects[0]


@pytest.mark.parametrize(
    ("length", "refused"),
    [(1, False), (31, False), (32, False), (33, True), (64, True)],
)
def test_the_guard_measures_length_rather_than_recognising_a_value(
    length: int, refused: bool
) -> None:
    """Driven over synthetic names either side of the ceiling.

    A guard that recognised one bad string would pass every other length. This
    walks the boundary, so the verdict is proved to come from ``len()`` of the
    value handed in.
    """
    assert bool(GUARD.permission_set_name_defects(synthetic_name(length))) is refused


def test_every_qualification_permission_set_name_satisfies_the_provider() -> None:
    """The audit's own list, driven -- and the retired name is not in it."""
    names = dict(GUARD.QUALIFICATION_PERMISSION_SET_NAMES)
    assert set(names.values()) == {PROPOSED, ASSESSMENT}
    assert RETIRED not in names.values()
    for value in names.values():
        assert GUARD.permission_set_name_defects(value) == []


# ---------------------------------------------------------------------------
# Proposal status
# ---------------------------------------------------------------------------


def test_the_adr_exists_at_its_exact_path() -> None:
    """One decision, one file name, and the audit points at the same one."""
    assert ADR.is_file()
    assert GUARD.ADR_0022 == ADR


def test_the_adr_exists_exactly_once() -> None:
    assert len(sorted(ADR.parent.glob("ADR-0022-*.md"))) == 1


def test_the_adr_carries_a_proposed_status() -> None:
    reading = flat(read(ADR))
    assert "status: proposed — not in force" in reading
    assert (
        "no authority until the pull request introducing this adr is independently reviewed and "
        "merged" in reading
    )
    assert (
        "while the pull request introducing this adr is open, adr-0022 is proposed and carries "
        "no authority" in reading
    )


def test_the_adr_does_not_claim_to_be_accepted_or_in_force() -> None:
    """The conditional wording is allowed; a settled claim is not.

    ``if adr-0022 is accepted`` is honest and must survive, which is why the
    refusals are anchored rather than loose.
    """
    reading = flat(read(ADR))
    assert "if adr-0022 is accepted" in reading
    for claim in ("adr-0022: accepted", "adr-0022: in force", "adr-0022 is now in force"):
        assert claim not in reading


def test_the_adr_is_absent_from_the_merged_registry() -> None:
    """The registry governs an in-force claim, and a proposal has no entry."""
    assert "ADR-0022" not in dict(GUARD.MERGED_ADR_STATUS)
    assert "ADR-0022" not in dict(registry_from_source(read(AUDIT)))


def test_neither_status_document_claims_an_in_force_row() -> None:
    for document in (CLAUDE_MD, README):
        assert "ADR-0022" not in GUARD._in_force_adr_claims(read(document))


def test_the_status_documents_record_the_blocked_pull_request() -> None:
    for document in (CLAUDE_MD, README):
        _, section, _ = split_at_section(document)
        reading = flat(section)
        assert "pr #56: open / unmerged / blocked on architecture" in reading
        assert "pr #56 correction: not authorized / not begun" in reading


def test_no_code_correction_is_claimed() -> None:
    """A proposal that had begun correcting the implementation would be the
    collapse of two gates into one."""
    for path in (ADR, CLAUDE_MD, README, PLAN):
        reading = flat(read(path))
        for claim in (
            "pr #56: corrected",
            "pr #56 has been corrected",
            "pr #56 correction: complete",
            "pr #56 correction: begun",
            "pr #56 correction: authorized",
        ):
            assert claim not in reading, f"{path.name}: {claim}"


def test_no_terraform_application_is_claimed() -> None:
    for path in (ADR, CLAUDE_MD, README, PLAN):
        reading = flat(read(path))
        for claim in ("terraform has been applied", "terraform apply: performed"):
            assert claim not in reading, f"{path.name}: {claim}"


def test_the_adr_carries_every_self_required_clause() -> None:
    assert missing(GUARD.ADR_0022_SELF_REQUIRED, read(ADR)) == []


def test_the_adr_records_every_rejected_alternative() -> None:
    assert missing(GUARD.ADR_0022_REJECTED_ALTERNATIVES, read(ADR)) == []


# ---------------------------------------------------------------------------
# Historical integrity
# ---------------------------------------------------------------------------


def test_adr_0021_remains_present_and_unedited_by_this_slice() -> None:
    """ADR-0021 still accepts the name it accepted.

    If this slice had edited ADR-0021 rather than superseding one of its values,
    the 33-character name would have vanished from the document that accepted it
    -- which is the one thing a decision record exists not to do.
    """
    assert ADR_0021.is_file()
    reading = flat(read(ADR_0021))
    assert RETIRED.lower() in reading
    assert (
        "status: proposed — no authority until the pull request introducing this adr is "
        "independently reviewed and merged" in reading
    )
    assert "adr-0021's conditional acceptance event has occurred" in reading
    assert "adr-0022" not in reading


def test_the_retired_name_survives_only_as_historical_or_defect_context() -> None:
    for path in (ADR, CLAUDE_MD, README, PLAN):
        assert GUARD.retired_permission_set_name_defects(read(path)) == [], path.name


def test_pr_56_is_not_blamed_for_following_adr_0021() -> None:
    reading = flat(read(ADR))
    assert (
        "pr #56 is not defective for implementing the accepted architecture as written" in reading
    )
    assert "pr #56 is not defective for obeying adr-0021" in reading
    for document in (CLAUDE_MD, README):
        _, section, _ = split_at_section(document)
        assert "pr #56 is not defective for obeying adr-0021" in flat(section)


def test_the_independent_reviews_refusal_is_recorded_accurately() -> None:
    reading = flat(read(ADR))
    assert (
        "independent review of pr #56 found that the accepted name cannot be created by the "
        "pinned terraform provider" in reading
    )
    assert "the independent review correctly refused the merge" in reading
    assert "the defect is therefore in the accepted architecture, not in the implementation" in (
        reading
    )


def test_no_previous_architecture_history_is_erased() -> None:
    reading = flat(read(ADR))
    assert "adr-0021 is not rewritten" in reading
    assert "no previous architecture history is erased" in reading
    assert "adr-0018's original arithmetic stays inside its historical markers" in reading
    assert "adr-0019's amendment stays the governing acquisition arithmetic" in reading


# ---------------------------------------------------------------------------
# Unchanged contracts
# ---------------------------------------------------------------------------


def test_the_assessment_permission_set_name_is_unchanged() -> None:
    reading = flat(read(ADR))
    assert ASSESSMENT.lower() in reading
    for document in (CLAUDE_MD, README):
        _, section, _ = split_at_section(document)
        assert "the assessment permission-set name is unchanged" in flat(section)


def test_both_profile_names_are_unchanged() -> None:
    reading = flat(read(ADR))
    assert ACQUISITION_PROFILE in reading
    assert ASSESSMENT_PROFILE in reading
    for document in (CLAUDE_MD, README):
        _, section, _ = split_at_section(document)
        assert "both profile names are unchanged" in flat(section)


def test_the_suffix_grammar_is_unchanged_and_not_reopened() -> None:
    reading = flat(read(ADR))
    assert "adr-0022 does not reopen the suffix grammar" in reading
    assert "it still proves structure, not provenance" in reading
    for document in (CLAUDE_MD, README):
        _, section, _ = split_at_section(document)
        assert "the suffix grammar is unchanged" in flat(section)


def test_the_actor_identities_and_session_bound_are_unchanged() -> None:
    for document in (CLAUDE_MD, README):
        _, section, _ = split_at_section(document)
        reading = flat(section)
        assert "actor identities and semantics" in reading
        assert "one-hour sessions" in reading
        assert "identity center group assignments" in reading


def test_the_neighbouring_decisions_are_unchanged() -> None:
    """ADR-0017 isolation, ADR-0019 write-only acquisition, ADR-0020 payload identity."""
    reading = flat(read(ADR))
    assert (
        "adr-0017 isolation, adr-0019 write-only acquisition, adr-0020 request-scoped payload "
        "identity" in reading
    )
    for document in (CLAUDE_MD, README):
        _, section, _ = split_at_section(document)
        assert "adr-0017, adr-0019 and adr-0020 are unchanged" in flat(section)


def test_the_arithmetic_is_derived_and_unchanged() -> None:
    """Recomputed from the locked constants, then compared against what is written."""
    bronze = EMPIRICAL_REQUEST_COUNT * BRONZE_OPERATIONS_PER_REQUEST
    low = bronze + 1
    high = bronze + MAX_LOCATOR_ATTEMPTS
    assert (EMPIRICAL_REQUEST_COUNT, bronze, low, high) == (48, 144, 145, 147)
    package_low = low * EXECUTIONS + (EXECUTIONS * (2 * EMPIRICAL_REQUEST_COUNT + 1) + 1)
    package_high = high * EXECUTIONS + (EXECUTIONS * (2 * EMPIRICAL_REQUEST_COUNT + 1) + 2)
    assert (package_low, package_high) == (485, 490)

    written = flat(read(ADR))
    assert f"acquisition putobject: {low} to {high}" in written
    assert f"two successful runs: {low * EXECUTIONS} to {high * EXECUTIONS}" in written
    assert f"whole successful package: {package_low} to {package_high}" in written
    assert "acquisition headobject: 0" in written
    assert "acquisition getobject: 0" in written


def test_the_adr_adds_no_operation_and_changes_no_deadline_term() -> None:
    reading = flat(read(ADR))
    assert "adds no s3 operation and changes no deadline term" in reading
    assert "l >= 3 * t_s3 + c" in reading
    assert "remaining >= t_req + 3 * t_s3 + l" in reading


# ---------------------------------------------------------------------------
# Section structure and parity
# ---------------------------------------------------------------------------


def test_each_status_document_carries_exactly_one_sound_section() -> None:
    for document in (CLAUDE_MD, README):
        found = scan(read(document))
        assert len(found.sections) == 1, document.name
        assert found.defects == (), document.name


def test_each_section_ends_at_its_declared_boundary() -> None:
    for document in (CLAUDE_MD, README):
        text = read(document)
        _, section, _ = split_at_section(document)
        assert GUARD.qualification_iam_section_is_terminated(
            text, section, GUARD.ADR_0022_SECTION_TERMINATORS[document.name]
        ), document.name


def test_the_two_sections_are_byte_identical() -> None:
    _, claude_section, _ = split_at_section(CLAUDE_MD)
    _, readme_section, _ = split_at_section(README)
    assert claude_section == readme_section


def test_each_section_carries_every_required_clause() -> None:
    for document in (CLAUDE_MD, README):
        _, section, _ = split_at_section(document)
        assert missing(GUARD.ADR_0022_STATUS_REQUIRED, section) == [], document.name


def test_neither_document_overstates_the_proposal() -> None:
    for document in (CLAUDE_MD, README):
        assert overstated(GUARD.ADR_0022_STATUS_FORBIDDEN, read(document)) == [], document.name


def test_the_implementation_plan_carries_every_required_clause() -> None:
    assert missing(GUARD.ADR_0022_PLAN_REQUIRED, read(PLAN)) == []


# ---------------------------------------------------------------------------
# Mutation proof -- each drives a production guard over an in-memory change
# ---------------------------------------------------------------------------


def test_mutation_new_name_reverted_to_the_retired_value() -> None:
    """The audit constant edited back to the 33-character name, by static parse."""
    source = read(AUDIT)
    anchor = f'ADR_0022_PROPOSED_ACQUISITION_PERMISSION_SET: Final = "{PROPOSED}"\n'
    assert source.count(anchor) == 1
    mutated = source.replace(
        anchor, f'ADR_0022_PROPOSED_ACQUISITION_PERMISSION_SET: Final = "{RETIRED}"\n'
    )
    reverted = constant_from_source(mutated, "ADR_0022_PROPOSED_ACQUISITION_PERMISSION_SET")
    assert reverted == RETIRED
    assert GUARD.permission_set_name_defects(reverted)


def test_mutation_new_name_changed_to_a_synthetic_thirty_three_character_value() -> None:
    name = synthetic_name(33)
    assert GUARD.permission_set_name_defects(PROPOSED) == []
    assert GUARD.permission_set_name_defects(name)


def test_mutation_invalid_character_introduced_into_the_new_name() -> None:
    broken = PROPOSED[:-1] + "/"
    assert len(broken) == len(PROPOSED)
    assert GUARD.permission_set_name_defects(PROPOSED) == []
    assert GUARD.permission_set_name_defects(broken)


def test_mutation_assessment_permission_set_name_changed() -> None:
    phrase = clause("names the unchanged assessment set", GUARD.ADR_0022_SELF_REQUIRED)
    mutated = without(read(ADR), phrase)
    assert "names the unchanged assessment set" in missing(GUARD.ADR_0022_SELF_REQUIRED, mutated)


def test_mutation_acquisition_profile_changed() -> None:
    phrase = clause("names the unchanged acquisition profile", GUARD.ADR_0022_SELF_REQUIRED)
    mutated = without(read(ADR), phrase)
    assert "names the unchanged acquisition profile" in missing(
        GUARD.ADR_0022_SELF_REQUIRED, mutated
    )


def test_mutation_assessment_profile_changed() -> None:
    phrase = clause("names the unchanged assessment profile", GUARD.ADR_0022_SELF_REQUIRED)
    mutated = without(read(ADR), phrase)
    assert "names the unchanged assessment profile" in missing(
        GUARD.ADR_0022_SELF_REQUIRED, mutated
    )


def test_mutation_suffix_grammar_claimed_changed() -> None:
    phrase = clause("keeps the suffix grammar unchanged", GUARD.ADR_0022_STATUS_REQUIRED)
    _, section, _ = split_at_section(CLAUDE_MD)
    mutated = without(section, phrase)
    assert "keeps the suffix grammar unchanged" in missing(GUARD.ADR_0022_STATUS_REQUIRED, mutated)


def test_mutation_adr_0022_registered_as_merged() -> None:
    """A forged registry entry, parsed out of mutated audit source."""
    source = read(AUDIT)
    assert source.count(REGISTRY_ANCHOR) == 1
    assert "ADR-0022" not in dict(registry_from_source(source))
    mutated = source.replace(REGISTRY_ANCHOR, REGISTRY_ANCHOR + REGISTRY_FORGERY)
    assert "ADR-0022" in dict(registry_from_source(mutated))


def test_mutation_proposal_claimed_accepted() -> None:
    _, section, _ = split_at_section(CLAUDE_MD)
    assert overstated(GUARD.ADR_0022_STATUS_FORBIDDEN, section) == []
    mutated = section.replace(
        "**ADR-0022: PROPOSED / NOT IN FORCE.**", "**ADR-0022: ACCEPTED / IN FORCE.**", 1
    )
    assert mutated != section
    assert "adr-0022: accepted / in force" in overstated(GUARD.ADR_0022_STATUS_FORBIDDEN, mutated)


@pytest.mark.parametrize(
    "claim",
    ["pr #56: corrected", "pr #56: merged", "pr #56: ready", "pr #56: mergeable"],
)
def test_mutation_pr_56_claimed_corrected_merged_or_ready(claim: str) -> None:
    _, section, _ = split_at_section(CLAUDE_MD)
    assert claim not in flat(section)
    mutated = section + f"\n{claim}\n"
    assert claim in overstated(GUARD.ADR_0022_STATUS_FORBIDDEN, mutated)


@pytest.mark.parametrize(
    "claim",
    [
        "terraform has been applied",
        "identity center permission sets: created",
        "aws account/group/instance binding values: known",
        "governed aws profiles: created",
        "run a: authorized",
        "g1: closed",
        "live trading: enabled",
    ],
)
def test_mutation_infrastructure_or_gate_claimed_live(claim: str) -> None:
    _, section, _ = split_at_section(CLAUDE_MD)
    assert claim not in flat(section)
    mutated = section + f"\n{claim}\n"
    assert claim in overstated(GUARD.ADR_0022_STATUS_FORBIDDEN, mutated)


def test_mutation_historical_old_name_framing_removed() -> None:
    """The retired name kept, every historical framing deleted."""
    _, section, _ = split_at_section(CLAUDE_MD)
    assert GUARD.retired_permission_set_name_defects(section) == []
    mutated = flat(section)
    for mark in GUARD.ADR_0022_RETIRED_NAME_FRAMINGS:
        mutated = mutated.replace(mark, "")
    assert RETIRED.lower() in mutated
    defects = GUARD.retired_permission_set_name_defects(mutated)
    assert defects == ["names the retired acquisition permission set with no historical framing"]


def test_mutation_retired_name_presented_as_the_replacement() -> None:
    _, section, _ = split_at_section(CLAUDE_MD)
    assert GUARD.retired_permission_set_name_defects(section) == []
    mutated = section + f"\nproposed acquisition permission-set name: {RETIRED}\n"
    defects = GUARD.retired_permission_set_name_defects(mutated)
    assert any("presents the retired name as current" in defect for defect in defects)


def test_mutation_provider_limit_removed() -> None:
    """The ceiling raised past the defect, by static parse of mutated source."""
    source = read(AUDIT)
    anchor = "PERMISSION_SET_NAME_MAX: Final = 32\n"
    assert source.count(anchor) == 1
    assert constant_from_source(source, "PERMISSION_SET_NAME_MAX") == 32
    mutated = source.replace(anchor, "PERMISSION_SET_NAME_MAX: Final = 64\n")
    raised = constant_from_source(mutated, "PERMISSION_SET_NAME_MAX")
    assert raised == 64
    # With the ceiling raised, the value the provider refuses would be admitted --
    # which is what makes the real constant load-bearing rather than decorative.
    assert len(RETIRED) > 32
    assert len(RETIRED) <= raised
    assert GUARD.permission_set_name_defects(RETIRED)


def test_mutation_length_guard_removed() -> None:
    """A grammar-only guard admits the retired name; the real guard refuses it."""

    def grammar_only(name: str) -> list[str]:
        if GUARD.PERMISSION_SET_NAME_GRAMMAR.fullmatch(name) is None:
            return ["grammar"]
        return []

    assert grammar_only(RETIRED) == []
    assert GUARD.permission_set_name_defects(RETIRED)


def test_mutation_status_section_duplicated() -> None:
    before, section, after = split_at_section(CLAUDE_MD)
    mutated = before + section + section + after
    found = scan(mutated)
    assert len(found.sections) == 2


def test_mutation_status_section_removed() -> None:
    before, section, after = split_at_section(CLAUDE_MD)
    assert section
    mutated = before + after
    found = scan(mutated)
    assert found.sections == ()


def test_mutation_wrong_level_heading() -> None:
    before, section, after = split_at_section(CLAUDE_MD)
    heading = f"### {GUARD.ADR_0022_STATUS_HEADING}"
    assert section.startswith(heading)
    mutated = before + section.replace(heading, f"#### {GUARD.ADR_0022_STATUS_HEADING}", 1) + after
    found = scan(mutated)
    assert found.sections == ()
    assert any("sits at level 4" in defect for defect in found.defects)


def test_mutation_section_local_clause_deleted_while_a_duplicate_remains_elsewhere() -> None:
    """The clause removed from the section and re-added outside it.

    A document-wide scan is answered by the copy that moved; the section-scoped
    guard is not, which is the whole reason these clauses are read section-locally.
    """
    phrase = clause("keeps both gates open", GUARD.ADR_0022_STATUS_REQUIRED)
    before, section, after = split_at_section(CLAUDE_MD)
    stripped = section.replace("G1 / G2:                                          OPEN / OPEN", "")
    assert stripped != section
    mutated_document = before + stripped + f"\n{phrase}\n" + after
    assert phrase in flat(mutated_document)
    assert "keeps both gates open" in missing(GUARD.ADR_0022_STATUS_REQUIRED, stripped)


def test_mutation_claude_readme_parity_broken() -> None:
    _, claude_section, _ = split_at_section(CLAUDE_MD)
    _, readme_section, _ = split_at_section(README)
    assert claude_section == readme_section
    mutated = readme_section.replace("provider selected:", "provider chosen:", 1)
    assert mutated != readme_section
    assert claude_section != mutated


def test_mutation_implementation_plan_claims_correction_begun() -> None:
    phrase = clause("refuses to begin the correction", GUARD.ADR_0022_PLAN_REQUIRED)
    mutated = without(read(PLAN), phrase)
    assert "refuses to begin the correction" in missing(GUARD.ADR_0022_PLAN_REQUIRED, mutated)


# ---------------------------------------------------------------------------
# Negative controls -- the guards must not agree vacuously
# ---------------------------------------------------------------------------


def test_negative_control_the_real_documents_pass_every_guard() -> None:
    assert missing(GUARD.ADR_0022_SELF_REQUIRED, read(ADR)) == []
    assert missing(GUARD.ADR_0022_PLAN_REQUIRED, read(PLAN)) == []
    for document in (CLAUDE_MD, README):
        _, section, _ = split_at_section(document)
        assert missing(GUARD.ADR_0022_STATUS_REQUIRED, section) == []
        assert overstated(GUARD.ADR_0022_STATUS_FORBIDDEN, read(document)) == []
        assert GUARD.retired_permission_set_name_defects(section) == []


def test_negative_control_an_empty_document_fails_rather_than_passing() -> None:
    """Absence must be a failure. A requirement list that an empty string
    satisfies is a list that proves nothing about a real document."""
    assert len(missing(GUARD.ADR_0022_SELF_REQUIRED, "")) == len(GUARD.ADR_0022_SELF_REQUIRED)
    assert len(missing(GUARD.ADR_0022_STATUS_REQUIRED, "")) == len(GUARD.ADR_0022_STATUS_REQUIRED)
    assert len(missing(GUARD.ADR_0022_PLAN_REQUIRED, "")) == len(GUARD.ADR_0022_PLAN_REQUIRED)
    assert scan("").sections == ()


def test_negative_control_the_requirement_lists_are_not_empty() -> None:
    """A guard driven over an empty list passes everything."""
    assert len(GUARD.ADR_0022_SELF_REQUIRED) >= 20
    assert len(GUARD.ADR_0022_STATUS_REQUIRED) >= 20
    assert len(GUARD.ADR_0022_PLAN_REQUIRED) >= 10
    assert len(GUARD.ADR_0022_STATUS_FORBIDDEN) >= 20
    assert len(GUARD.ADR_0022_REJECTED_ALTERNATIVES) >= 8


def test_negative_control_forbidden_claims_are_absent_from_a_clean_section() -> None:
    """Each refusal is checked to be absent, so none is a phrase the real text
    carries and therefore silently always-failing."""
    for document in (CLAUDE_MD, README):
        _, section, _ = split_at_section(document)
        assert overstated(GUARD.ADR_0022_STATUS_FORBIDDEN, section) == []


def test_no_tracked_file_is_modified_by_these_guards() -> None:
    """Every mutation above is in memory, and this proves it."""
    now = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in TRACKED}
    assert now == _BASELINE_DIGESTS
