"""ADR-0018 is ACCEPTED ARCHITECTURE ONLY, and the repository has to keep saying so.

PR #39 merged, so the conditional acceptance took effect. A merged ADR drifts by
having its facts go stale, and this one has two ways to do it: a status document
that still calls it proposed, and a status document that reads an approved design
as permission to write, provision or run it. That second one has a precedent in
this repository -- ADR-0017 spent time in an open pull request while its own text
already read "Accepted", and the status documents had to carry the distinction
explicitly.

These are text and arithmetic checks over committed files. **Nothing here
contacts AWS, a provider or a network**, and nothing here imports the operational
entry points. What they guard is three things:

1. **The acceptance is recorded, and its history is not rewritten.** The ADR keeps
   its conditional status line, keeps the sentence saying it carried no authority
   before the merge, records that the merge has since occurred, and supersedes
   nothing. Both status documents name the same pull request.
2. **The arithmetic is recomputed, not quoted.** ADR-0018 states a nominal and a
   maximum operation count. A count copied from prose into prose is a count
   nobody checks, so the numbers are derived here from the package's own
   parameters and compared against what the ADR says.
3. **Implementation exists as a candidate; infrastructure and execution do not.**
   The offline implementation is present on this branch and is asserted **present**,
   with its structural boundaries. Everything past it is asserted **absent** --
   no Terraform, no IAM role, no locator, no private report, no run record --
   because "implementation only" is a claim about the repository and not a
   sentence about intent, and infrastructure mutation and execution are each
   required to still read NOT AUTHORIZED.
4. **The clarification amendment says what it clarifies, and claims nothing more.**
   It makes 1,800 seconds an actual elapsed-time deadline with a stated scope, a
   stated clock and stated enforcement points, and it makes the canonical
   assessment a combined one over both acquisition executions. Both took effect
   only on merge, exactly as the ADR itself did -- **PR #42 has since merged**, so
   the guards below are inverted rather than deleted, its conditional status line
   is kept as the thing that merge satisfied, and neither decision opens a gate.
   The combined arithmetic is derived here from `R` and `E` rather than
   transcribed, for the same reason the acquisition arithmetic is.

**Implementation, infrastructure mutation and execution are three separate gates.**
Crossing the first is not crossing the second or the third, and this file is where
that distinction is checked rather than asserted.
"""

from __future__ import annotations

import builtins
import importlib.util
import os
import re
import subprocess
import sys
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
    / ("ADR-0018-bounded-private-empirical-sharadar-qualification.md")
)
CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"
README = PROJECT_ROOT / "README.md"
DELETION_RUNBOOK = PROJECT_ROOT / "docs" / "runbooks" / "vendor-data-cloud-deletion.md"
AUDIT = PROJECT_ROOT / "scripts" / "phase3_docs_audit.py"

#: The pull request whose merge satisfied ADR-0018's conditional acceptance.
ADR_0018_PR = "#39"

#: The pull request whose merge satisfied the clarification amendment's own
#: conditional effectiveness, with the merge commit and the approved
#: clarification head. Named here because a merge recorded only as a number is a
#: merge nobody can check against the history that produced it.
ADR_0018_CLARIFICATION_PR = "#42"
ADR_0018_CLARIFICATION_MERGE_COMMIT = "28239514b9e4e13f55ee98fa50877077e70bd593"
ADR_0018_CLARIFICATION_APPROVED_HEAD = "579259a62ff7561ae2991f3923ea8aa1d0064be8"

#: The pull request that merged the ADR-0018 offline implementation, and the
#: pull request that merged the fixed 48-request assessment-boundary correction
#: afterwards. **Two separate merge events**, pinned separately and never read
#: through each other: PR #41 merged while the fixed-count validation was still
#: missing, and describing it as having passed PR #44's review would be
#: rewriting the order they happened in.
ADR_0018_IMPL_PR = "#41"
ADR_0018_IMPL_MERGE_COMMIT = "3ddd7d40741bb9a50ae4fc5452324ddbfb5e1ec0"
ADR_0018_IMPL_APPROVED_HEAD = "96daac7963d936f231b37847579c5f28bb313760"
ADR_0018_FIX_PR = "#44"
ADR_0018_FIX_MERGE_COMMIT = "c945970613b80bfd4f42acc4f3acb4814895eb42"
ADR_0018_FIX_APPROVED_HEAD = "78b4425077e65eeb12dfd24b35825741370e0e0f"

#: What approving a design did **not** do. Each is separately checkable, so each
#: is separately required of both status documents -- an accepted architecture
#: read as permission to build, provision or run is the drift this guards.
STILL_UNAUTHORIZED = (
    "infrastructure mutation: not authorized",
    "run a: not authorized",
    "run b: not authorized",
    "assessment: not authorized",
)

#: The artifacts ADR-0018 designs, now built as an **offline implementation
#: candidate**. Their presence is what crossing the implementation gate looks like,
#: and it is checked here so "implemented" is a fact about the repository.
IMPLEMENTED_ON_THIS_BRANCH = (
    PROJECT_ROOT / "src" / "kalpamani" / "data" / "qualify",
    PROJECT_ROOT / "scripts" / "sharadar_empirical_qualification.py",
    PROJECT_ROOT / "scripts" / "sharadar_qualification_assessment.py",
)

#: Everything past the implementation gate. Infrastructure mutation and execution
#: are the second and third gates, and neither has been crossed -- so no Terraform
#: for these roles exists.
#:
#: **The owner-only inventory used to be the third entry here, and it does not
#: belong in this category.** Physical absence was a sound question about the two
#: Terraform files -- nobody's workflow creates one, so a file at either path
#: could only be unauthorized infrastructure. It was never a sound question about
#: the inventory: the sanctioned runtime path is where ADR-0018 says the owner's
#: private input lives, so requiring the file to be absent required the owner not
#: to have made the decision the implementation reads. It is replaced, one for
#: one, by :class:`TestThePrivateInventoryStaysOutOfGit` -- a strictly stronger
#: contract, because absence proves nothing about Git and exclusion from Git holds
#: in both physical states.
STILL_ABSENT = (
    PROJECT_ROOT / "infra" / "aws" / "research-data-plane" / "qualification_roles.tf",
    PROJECT_ROOT / "infra" / "aws" / "research-data-plane" / "qualification-roles.tf",
)

#: The owner-only inventory, at the sanctioned runtime path. Named so the guards
#: below can say what they protect; **no value inside the file is read here**, and
#: no test creates, copies or opens it.
PRIVATE_INVENTORY: Final = (
    PROJECT_ROOT / ".runtime" / "phase3" / "sharadar" / "empirical-inventory.json"
)


def _audit_module() -> ModuleType:
    """Load the audit as a module so its own rule can be exercised, not restated.

    The contract under test is the audit's. Re-implementing it here would give the
    repository two spellings of one rule, which is exactly how a value one stage
    admits becomes a value the next refuses -- the defect ADR-0016 was written to
    correct. So the tests below drive the audit's functions and vary the
    repository underneath them.

    Registered in ``sys.modules`` before execution because the audit defines a
    ``@dataclass``, and ``dataclasses`` resolves the defining module through that
    entry. Importing it defines constants and functions; it runs no check, opens
    no socket and reaches no service.
    """
    spec = importlib.util.spec_from_file_location("kalpamani_phase3_docs_audit_0018", AUDIT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GUARD = _audit_module()

#: An ignore file that protects the runtime area exactly the way this repository
#: does: the broad directory rule, and the inventory named in its own right.
PROTECTED_IGNORE: Final = f".runtime/\n{GUARD.ADR_0018_INVENTORY_RELPATH}\n"

#: Invented, non-market fixture content. Eight lines of nothing: no ticker, no
#: real symbol, no owner selection, and nothing derived from the real file, which
#: no test reads.
FIXTURE_INVENTORY_BODY: Final = '{"schema_version": "fixture-v0", "subjects": []}\n'


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(  # noqa: S603 - fixed program, fixture-local arguments
        ["git", "-C", str(root), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"git {args[0]} failed in the fixture repository"
    return result


def _fixture_repo(root: Path, ignore: str) -> Path:
    """A real, minimal git repository carrying `ignore` as its whole ignore policy.

    Hermetic on purpose: the fixture pins its own empty global-excludes file, so
    the answers below come from the rules written here and from nothing this
    workstation happens to configure.
    """
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "--quiet", "-b", "main")
    empty_excludes = root / ".git" / "fixture-global-excludes"
    empty_excludes.write_text("", encoding="utf-8")
    _git(root, "config", "core.excludesFile", str(empty_excludes))
    _git(root, "config", "user.email", "guard-fixture")
    _git(root, "config", "user.name", "Guard Fixture")
    (root / ".gitignore").write_text(ignore, encoding="utf-8")
    _git(root, "add", "--", ".gitignore")
    _git(root, "commit", "--quiet", "-m", "fixture baseline")
    return root


def _write_fixture_inventory(root: Path) -> Path:
    """Create a synthetic file at the sanctioned relative path inside a fixture."""
    path = root / str(GUARD.ADR_0018_INVENTORY_RELPATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FIXTURE_INVENTORY_BODY, encoding="utf-8")
    return path


def _ours_merged_disclosure(root: Path) -> tuple[Path, str, str]:
    """A fixture whose disclosure survives only through a pruned merge parent.

    The graph is the one the PR #63 review demonstrated: the inventory is
    committed on a side branch, the branch is merged with ``-s ours`` so the
    merge tree omits the path, and the side ref is deleted. What is left is a
    repository whose ``HEAD``, index and working tree are all clean, and whose
    object database still holds a committed subject list reachable from the merge
    commit's second parent.

    Returns the repository root, the disclosure commit and the merge commit, so a
    test can prove the reachability rather than trusting the construction.
    """
    repo = _fixture_repo(root, PROTECTED_IGNORE)
    _git(repo, "checkout", "--quiet", "-b", "side")
    _write_fixture_inventory(repo)
    _git(repo, "add", "--force", "--", GUARD.ADR_0018_INVENTORY_RELPATH)
    _git(repo, "commit", "--quiet", "-m", "fixture disclosure on a side branch")
    side = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "--quiet", "main")
    (repo / "unrelated.txt").write_text("fixture line", encoding="utf-8")
    _git(repo, "add", "--", "unrelated.txt")
    _git(repo, "commit", "--quiet", "-m", "independent mainline commit")
    _git(repo, "merge", "--quiet", "--no-ff", "-s", "ours", "-m", "fixture ours merge", "side")
    merge = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "branch", "--quiet", "-D", "side")
    return repo, side, merge


def _facts(root: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """The audit's own boundary answers, taken against `root`."""
    monkeypatch.setattr(GUARD, "REPO_ROOT", root)
    return {
        "written_down": bool(GUARD._inventory_ignore_rule_is_written_down()),
        "ignored": bool(GUARD._inventory_is_git_ignored()),
        "area_ignored": bool(GUARD._ignores(GUARD.ADR_0018_RUNTIME_RELPATH)),
        "negations": list(GUARD._runtime_ignore_negations()),
        "in_index": bool(GUARD._inventory_is_in_index()),
        "in_head": bool(GUARD._inventory_is_in_head()),
        "history": list(GUARD._inventory_history_commits()),
    }


def _holds(facts: dict[str, object]) -> bool:
    """Does the whole confidentiality contract hold for those answers?"""
    return bool(
        facts["written_down"]
        and facts["ignored"]
        and facts["area_ignored"]
        and not facts["negations"]
        and not facts["in_index"]
        and not facts["in_head"]
        and not facts["history"]
    )


#: The package's own parameters, from ADR-0018 §4. Every count below is derived
#: from these rather than transcribed, so a later edit that changes one and
#: forgets the other fails here.
SUBJECTS = 8
DATASETS = 3
PAGES = 2
REQUESTS = SUBJECTS * DATASETS * PAGES
OBJECTS_PER_ACQUISITION = 3
MAX_LOCATOR_ATTEMPTS = 3
#: A conditional HEAD is issued only after a 412, at most once per PutObject.
#: The two classifications that permit a locator retry refuse the conditional
#: PutObject *before* the occupancy resolution and send no HEAD, and a 412
#: resolves the condition the retry permission needs unresolved -- so only one
#: locator attempt can ever reach that path. The locator contributes exactly
#: one, however many times it wrote, and a retry cannot raise this bound.
MAX_HEADOBJECTS = OBJECTS_PER_ACQUISITION * REQUESTS + 1

#: Two acquisition executions feed ONE combined assessment (ADR-0018 §8.1, §9.4).
#: P1's TESTED ceiling is a cross-run question, so a per-run assessment cannot
#: reach it however many per-run assessments are run.
EXECUTIONS = 2
#: Per execution: one locator, plus one acquisition record and one payload per
#: request. Acquisition claims are validated from the locator and never retrieved.
COMBINED_GETOBJECTS = EXECUTIONS * (2 * REQUESTS + 1)
#: The acquisition envelope across both runs, nominal floor and worst-case ceiling.
ACQUISITION_BOTH_MIN = EXECUTIONS * (OBJECTS_PER_ACQUISITION * REQUESTS + 1)
ACQUISITION_BOTH_MAX = EXECUTIONS * (
    OBJECTS_PER_ACQUISITION * REQUESTS + MAX_LOCATOR_ATTEMPTS + MAX_HEADOBJECTS
)

#: The three deadline values ADR-0018 §4.3 already accepted. Every other term in
#: §4.5.3 is a required implementation constant whose value is reviewed with the
#: correction pull request, so none of them is asserted here.
DEADLINE_SECONDS = 1800
PROVIDER_CEILING_SECONDS = 30
MIN_PACING_SECONDS = 1


def flat(path: Path) -> str:
    """The document with emphasis removed, whitespace collapsed and case folded.

    The same normalisation the documentation audit uses, and for the same reason:
    a rewrapped line and a bolded phrase are the same claim, and a guard that
    only sees one of them is a guard a reflow disables.
    """
    return " ".join(path.read_text(encoding="utf-8").replace("**", "").split()).lower()


class TestTheAcceptanceIsRecordedWithoutRewritingItsHistory:
    """Inverted, not deleted.

    Every guard below required the opposite while PR #39 was open. Deleting them
    on merge would have left the reverted claim unguarded, so each one was turned
    around instead -- the same treatment ADR-0017's registry guard was given when
    PR #33 merged.
    """

    def test_the_status_line_is_the_exact_conditional_acceptance(self) -> None:
        """The ADR's own status line is immutable; the merge is what satisfied it."""
        assert (
            "status: accepted — effective only upon merge of the pull request "
            "introducing this adr." in flat(ADR)
        )

    def test_the_adr_keeps_the_pre_merge_condition_exactly_as_written(self) -> None:
        """Acceptance now does not give it authority it lacked while the PR was open."""
        assert "before that merge this adr is proposed and carries no authority." in flat(ADR)

    def test_the_adr_records_that_the_merge_condition_has_since_been_met(self) -> None:
        assert "that merge has since occurred" in flat(ADR)

    def test_the_adr_no_longer_claims_to_be_an_open_pull_request(self) -> None:
        assert "it is a document in an open pull request" not in flat(ADR)

    def test_the_adr_supersedes_nothing(self) -> None:
        assert "supersedes: nothing." in flat(ADR)

    def test_the_adr_is_registered_in_the_merged_registry_against_its_pull_request(self) -> None:
        """An in-force row outside the registry is a row nothing governs."""
        registry = AUDIT.read_text(encoding="utf-8")
        block = registry.split("MERGED_ADR_STATUS: Final", 1)[1].split(")\n", 1)[0]
        assert f'("ADR-0018", "PR {ADR_0018_PR} merged")' in block

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_status_documents_record_it_as_accepted_and_in_force(self, document: Path) -> None:
        assert "adr-0018: accepted / in force" in flat(document)

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_neither_document_still_records_it_as_proposed(self, document: Path) -> None:
        assert "proposed — not accepted, and it carries no authority." not in flat(document)

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_documents_claim_it_in_force_against_the_right_pull_request(
        self, document: Path
    ) -> None:
        """The audit's own in-force pattern, applied to the ADR-0018 rows."""
        in_force = re.compile(
            r"ACCEPTED\s*/\s*IN\s+FORCE.*?\bPR\s*#(\d+)\s+merged", re.IGNORECASE | re.DOTALL
        )
        rows = [
            line
            for line in document.read_text(encoding="utf-8").splitlines()
            if line.lstrip().startswith("|") and "ADR-0018-bounded-private" in line.split("|")[1]
        ]
        assert len(rows) == 1, "exactly one ADR-0018 status row must exist to be checked"
        matched = in_force.search(rows[0].replace("**", ""))
        assert matched is not None, "the row must state ACCEPTED / IN FORCE and name its PR"
        assert f"#{matched.group(1)}" == ADR_0018_PR

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_documents_keep_the_pre_merge_no_authority_fact(self, document: Path) -> None:
        """A merge is not licence to backdate authority onto the days before it."""
        assert f"while pr {ADR_0018_PR} was open it was proposed and carried no authority" in flat(
            document
        )


class TestTheArithmeticIsDerived:
    """Recomputed from §4's parameters, never transcribed from §9's prose."""

    def test_the_request_count_follows_from_the_inventory(self) -> None:
        assert REQUESTS == 48
        # The multiplication sign is the document's own character; an ASCII
        # look-alike would match nothing, so the rule is suppressed per line.
        phrase = f"{REQUESTS} = {SUBJECTS} subjects × {DATASETS} datasets × {PAGES} pages"  # noqa: RUF001
        assert phrase in flat(ADR)

    def test_provider_retries_are_forced_to_zero_by_the_compiled_budget(self) -> None:
        """One retry each would need 48 <= 32, which is false -- so attempts is 1."""
        compiled_retry_budget = 32
        assert REQUESTS * (2 - 1) > compiled_retry_budget
        assert REQUESTS * (1 - 1) <= compiled_retry_budget
        assert "`max_attempts = 1` — zero provider retries" in flat(ADR)

    def test_the_nominal_put_object_count_is_bronze_plus_one_locator(self) -> None:
        bronze = REQUESTS * OBJECTS_PER_ACQUISITION
        assert bronze == 144
        assert bronze + 1 == 145
        adr = flat(ADR)
        assert f"bronze `putobject` | exactly {bronze}" in adr
        assert f"total `putobject` | exactly {bronze + 1}" in adr

    def test_the_maximum_put_object_count_allows_at_most_two_locator_retries(self) -> None:
        bronze = REQUESTS * OBJECTS_PER_ACQUISITION
        assert bronze + MAX_LOCATOR_ATTEMPTS == 147
        adr = flat(ADR)
        assert "may be retried at most twice" in adr
        assert f"maximum total `putobject` | {bronze + MAX_LOCATOR_ATTEMPTS}" in adr
        assert f"{bronze} <= n <= {bronze + MAX_LOCATOR_ATTEMPTS}" in adr

    def test_head_object_is_bounded_by_the_completed_requests_not_by_the_writes(self) -> None:
        """A retry buys PutObject invocations that send no HEAD, so the bound holds."""
        assert MAX_HEADOBJECTS == OBJECTS_PER_ACQUISITION * REQUESTS + 1 == 145
        adr = flat(ADR)
        assert "zero to 145" in adr
        assert "only after a `412`" in adr
        assert "head_object_count <= 3 * completed_requests + 1" in adr
        assert f"head_object_count <= {MAX_HEADOBJECTS}" in adr
        assert (
            "at most one locator attempt can ever reach the `412` metadata-resolution path" in adr
        )

    def test_the_stale_put_object_derived_head_bound_is_gone(self) -> None:
        """147 HEADs was arithmetic no run can produce, and it must not come back."""
        adr = flat(ADR)
        for stale in ("zero to 147", "147 to 294", "294 to 588"):
            assert stale not in adr, f"{stale} is the superseded HeadObject arithmetic"

    def test_the_maximum_totals_follow_from_the_two_bounds(self) -> None:
        maximum_puts = REQUESTS * OBJECTS_PER_ACQUISITION + MAX_LOCATOR_ATTEMPTS
        per_run = maximum_puts + MAX_HEADOBJECTS
        assert maximum_puts == 147
        assert per_run == 147 + 145 == 292
        assert 2 * per_run == 584
        adr = flat(ADR)
        assert f"maximum total s3 operations | {maximum_puts} to {per_run}" in adr
        assert f"`{maximum_puts} + {MAX_HEADOBJECTS} = {per_run}`" in adr
        # The multiplication sign is the document's own character; an ASCII
        # look-alike would match nothing, so the rule is suppressed per line.
        assert f"`2 × {per_run} = {2 * per_run}`" in adr  # noqa: RUF001
        assert f"294 to {2 * per_run}" in adr

    def test_the_combined_assessment_read_formula_excludes_claims(self) -> None:
        """One assessment, two executions, and no claim retrieved from either."""
        assert COMBINED_GETOBJECTS == EXECUTIONS * (2 * REQUESTS + 1) == 194
        adr = flat(ADR)
        assert "acquisition-claim `getobject` | `0`" in adr
        # The multiplication sign is the document's own character; an ASCII
        # look-alike would match nothing, so the rule is suppressed per line.
        assert f"`e × r` | {EXECUTIONS * REQUESTS}" in adr  # noqa: RUF001
        assert f"`e × (2r + 1)` | {COMBINED_GETOBJECTS}" in adr  # noqa: RUF001
        assert (
            f"`e × (2r + 1) + 1` to `e × (2r + 1) + 2` | "  # noqa: RUF001
            f"{COMBINED_GETOBJECTS + 1} to {COMBINED_GETOBJECTS + 2}" in adr
        )

    def test_the_superseded_single_execution_arithmetic_is_no_longer_canonical(self) -> None:
        """The old numbers survive only in the historical note, never as a table row."""
        adr = flat(ADR)
        for stale in (
            "total `getobject` | `2r + 1` | 97",
            "`2r + 2` to `2r + 3` | 98 to 99",
            "assessment s3 operations, both runs | 196 to 198",
            "for a `complete` locator over",
        ):
            assert stale not in adr, f"{stale} is the superseded single-execution arithmetic"

    def test_the_whole_package_envelope_follows_from_its_two_halves(self) -> None:
        assert ACQUISITION_BOTH_MIN == 290
        assert ACQUISITION_BOTH_MAX == 584
        assert ACQUISITION_BOTH_MIN + COMBINED_GETOBJECTS + 1 == 485
        assert ACQUISITION_BOTH_MAX + COMBINED_GETOBJECTS + 2 == 780
        assert "`485 = 290 + 195` and `780 = 584 + 196`" in flat(ADR)

    def test_a_refused_locator_reads_no_payload(self) -> None:
        assert "no payload is read on a refusal" in flat(ADR)


class TestRetryIsNeverAmbiguous:
    def test_only_two_closed_classifications_permit_a_locator_retry(self) -> None:
        adr = flat(ADR)
        assert "no retry may follow an ambiguous or unclassified result." in adr
        for forbidden in (
            "access_denied",
            "not_found",
            "invalid_response",
            "invalid_configuration",
            "unknown",
        ):
            assert forbidden in adr, f"{forbidden} must be named as forbidding retry"

    def test_bronze_writes_are_never_retried(self) -> None:
        assert "bronze writes are never retried" in flat(ADR)


class TestTheArchitectureIsStillOnlyAnArchitecture:
    @pytest.mark.parametrize("path", IMPLEMENTED_ON_THIS_BRANCH, ids=lambda p: p.name)
    def test_every_designed_artifact_exists_as_an_implementation_candidate(
        self, path: Path
    ) -> None:
        assert path.exists(), (
            f"{path.name} is missing. The offline implementation is a candidate on this "
            "branch, and its presence is what the implementation gate having been "
            "crossed looks like."
        )

    @pytest.mark.parametrize("path", STILL_ABSENT, ids=lambda p: p.name)
    def test_nothing_past_the_implementation_gate_exists(self, path: Path) -> None:
        assert not path.exists(), (
            f"{path.name} exists. Implementation, infrastructure mutation and execution "
            "are three separate gates, and only the first has been crossed."
        )

    def test_the_owner_only_inventory_is_not_in_the_physical_absence_category(self) -> None:
        """It is neither a forbidden artifact nor one this branch must carry.

        Both memberships would be wrong, in opposite directions. In
        ``STILL_ABSENT`` the owner's sanctioned runtime input reads as
        unauthorized infrastructure and ordinary validation fails on it; in
        ``IMPLEMENTED_ON_THIS_BRANCH`` it reads as something this branch must
        commit, which is the disclosure the whole contract exists to prevent.
        """
        assert PRIVATE_INVENTORY not in STILL_ABSENT
        assert PRIVATE_INVENTORY not in IMPLEMENTED_ON_THIS_BRANCH

    def test_the_other_physical_absence_guards_are_still_enforced(self) -> None:
        """Removing one parameter must not have emptied the category.

        A guard reduced to nothing passes trivially, so the two Terraform paths
        are pinned by name here rather than left to a count.
        """
        assert STILL_ABSENT == (
            PROJECT_ROOT / "infra" / "aws" / "research-data-plane" / "qualification_roles.tf",
            PROJECT_ROOT / "infra" / "aws" / "research-data-plane" / "qualification-roles.tf",
        )
        for path in STILL_ABSENT:
            assert not path.exists()

    def test_no_new_iam_role_is_declared_for_the_two_designed_roles(self) -> None:
        """No IAM ROLE, and no attachment, for either designed actor.

        This once refused the substring ``qualification_acquisition`` anywhere
        under ``infra/``, which was the right question while no qualification
        Terraform was authorized at all. The offline permission-set candidate is
        now authorized and present, and it has to name the two actors to be about
        them -- so the guard is inverted into the question it was always asking:
        does an identity exist? Roles, role policies, users, access keys and every
        attachment resource are refused; a managed policy attached to nothing is
        not an identity and grants nothing.
        """
        infra = PROJECT_ROOT / "infra"
        if not infra.is_dir():  # pragma: no cover - the tree exists in this repository
            return
        identity = re.compile(
            r'resource\s+"(aws_iam_role|aws_iam_role_policy|aws_iam_user|aws_iam_access_key|'
            r"aws_iam_policy_attachment|aws_iam_role_policy_attachment|"
            r'aws_iam_user_policy_attachment|aws_iam_group_policy_attachment)"\s+"([^"]+)"'
        )
        for path in infra.rglob("*.tf"):
            hcl = "\n".join(
                line
                for line in path.read_text(encoding="utf-8").splitlines()
                if not line.lstrip().startswith("#")
            )
            for resource_type, name in identity.findall(hcl):
                assert not resource_type.endswith("attachment"), (
                    f"{path.name} declares {resource_type}.{name}. Attaching a permission "
                    "set to a principal is infrastructure mutation, which is a separate gate."
                )
                for role in ("qualification_acquisition", "qualification_assessment"):
                    assert role not in name, (
                        f"{path.name} declares {resource_type}.{name}. Designing a role is "
                        "not creating one, and infrastructure mutation is a separate gate."
                    )

    def test_the_offline_permission_set_candidate_exists_and_creates_no_identity(self) -> None:
        """The reverse-drift half. Deleting the candidate must fail too.

        A guard that only forbids is satisfied by an empty directory. This one
        requires the accepted ADR-0018 s.10 permission sets to be expressed as two
        managed policies, and requires them to be the ONLY resources the candidate
        declares -- so the file cannot quietly grow a role, a bucket or a trust
        policy while the guard above keeps passing on its own terms.
        """
        candidate = (
            PROJECT_ROOT / "infra" / "aws" / "research-data-plane" / "qualification_policies.tf"
        )
        assert candidate.is_file(), (
            "the offline qualification permission-set candidate is missing; the accepted "
            "ADR-0018 s.10 permission sets would then be expressed nowhere in Terraform"
        )
        hcl = "\n".join(
            line
            for line in candidate.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        declared = re.findall(r'resource\s+"([a-z0-9_]+)"\s+"([a-z0-9_]+)"', hcl)
        assert declared == [
            ("aws_iam_policy", "qualification_acquisition"),
            ("aws_iam_policy", "qualification_assessment"),
        ], f"the candidate declares something other than the two permission sets: {declared}"
        assert "assume_role_policy" not in hcl, "a trust policy would name a principal nobody chose"

    def test_neither_entry_point_has_ever_been_executed_against_a_real_service(self) -> None:
        """A statement about the repository: no run record of either exists."""
        runtime = PROJECT_ROOT / ".runtime"
        if not runtime.is_dir():
            return
        for pattern in ("**/empirical-qualification*", "**/qualification-assessment*"):
            assert not list(runtime.glob(pattern))

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    @pytest.mark.parametrize("phrase", STILL_UNAUTHORIZED)
    def test_both_documents_keep_each_further_gate_unauthorized(
        self, document: Path, phrase: str
    ) -> None:
        assert phrase in flat(document)

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_documents_record_what_the_merge_did_and_did_not_do(self, document: Path) -> None:
        text = flat(document)
        assert "the merge approved architecture only" in text
        assert (
            "the merge authorized no implementation, no infrastructure mutation and no execution"
            in text
        )

    def test_the_adr_states_that_merging_authorizes_nothing_further(self) -> None:
        assert (
            "merging approves architecture. it authorizes no implementation, no infrastructure "
            "mutation and no execution." in flat(ADR)
        )

    def test_no_concrete_subject_list_is_carried(self) -> None:
        """Subjects are evaluation information and live in a git-ignored input."""
        adr = flat(ADR)
        for carrier in ("locked_subject", "--subject", "subjects = (", "subjects=("):
            assert carrier not in adr

    def test_the_adr_leaves_adr_0017_accounting_untouched(self) -> None:
        assert "exactly three `putobject`" in flat(ADR)
        assert "it is untouched." in flat(ADR)


class TestThePrivateInventoryStaysOutOfGit:
    """The owner-only inventory: either physical state, and never in Git.

    The guard this replaces asked whether the file existed. That question had one
    right answer while nothing downstream was implemented and no owner input
    existed, and it acquired a wrong one the moment the owner populated the
    sanctioned runtime path ADR-0018 fixes for it: ordinary validation then failed
    on the owner's own private file, and the two ways to make it pass were to
    delete the decision or to stop running the audit.

    **Existence was never the property worth having.** These are, and each is
    asked of git metadata rather than of the file:

    1. an effective ignore rule covers the exact path, and the runtime area too;
    2. no re-include re-exposes anything under that area;
    3. the exact path is not in the index;
    4. the exact path is not in ``HEAD``;
    5. the exact path appears in no reachable commit -- a later deletion leaves a
       committed subject list retrievable, so the question is *ever*, not *now*.

    All five hold whether the file is on this machine or not, which is why the
    correction is a strengthening rather than a relaxation. Every mutation case
    below runs against a **real, throwaway git repository** with invented
    contents; none of them copies, opens or derives anything from the owner's
    file.
    """

    def test_the_contract_holds_in_this_checkout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The present state, in the primary checkout, with the real file in place."""
        assert _holds(_facts(PROJECT_ROOT, monkeypatch))

    def test_the_contract_holds_with_the_inventory_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _fixture_repo(tmp_path / "present", PROTECTED_IGNORE)
        _write_fixture_inventory(root)
        assert _holds(_facts(root, monkeypatch))

    def test_the_contract_holds_with_the_inventory_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The absent state. Both physical states pass, and neither is required."""
        root = _fixture_repo(tmp_path / "absent", PROTECTED_IGNORE)
        assert not (root / GUARD.ADR_0018_INVENTORY_RELPATH).exists()
        assert _holds(_facts(root, monkeypatch))

    def test_a_staged_inventory_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Staging is the step before committing, and it must fail closed there."""
        root = _fixture_repo(tmp_path / "staged", PROTECTED_IGNORE)
        _write_fixture_inventory(root)
        _git(root, "add", "--force", "--", GUARD.ADR_0018_INVENTORY_RELPATH)
        facts = _facts(root, monkeypatch)
        assert facts["in_index"] is True
        assert not _holds(facts)

    def test_a_committed_inventory_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _fixture_repo(tmp_path / "committed", PROTECTED_IGNORE)
        _write_fixture_inventory(root)
        _git(root, "add", "--force", "--", GUARD.ADR_0018_INVENTORY_RELPATH)
        _git(root, "commit", "--quiet", "-m", "fixture disclosure")
        facts = _facts(root, monkeypatch)
        assert facts["in_head"] is True
        assert facts["history"]
        assert not _holds(facts)

    def test_an_inventory_deleted_after_being_committed_still_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The case a file-existence guard cannot see at all.

        After the delete commit the working tree is clean, the index is clean and
        ``HEAD`` no longer carries the file -- and the blob is still reachable from
        the earlier commit. Deleting a committed subject list does not undo the
        disclosure, so history is asked separately from ``HEAD``.
        """
        root = _fixture_repo(tmp_path / "deleted", PROTECTED_IGNORE)
        _write_fixture_inventory(root)
        _git(root, "add", "--force", "--", GUARD.ADR_0018_INVENTORY_RELPATH)
        _git(root, "commit", "--quiet", "-m", "fixture disclosure")
        _git(root, "rm", "--quiet", "--", GUARD.ADR_0018_INVENTORY_RELPATH)
        _git(root, "commit", "--quiet", "-m", "fixture deletion")
        facts = _facts(root, monkeypatch)
        assert facts["in_index"] is False
        assert facts["in_head"] is False
        assert facts["history"], "a deleted commit is still a reachable disclosure"
        assert not _holds(facts)

    def test_a_disclosure_merged_ordinarily_still_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The straightforward merge shape, kept beside the `ours` case below.

        Here the merge carries the path into its own tree, so the disclosure is
        on the mainline and no traversal question arises. It is asserted anyway:
        the correction below widens the walk, and a widened walk must not stop
        finding what the narrow one already found.
        """
        root = _fixture_repo(tmp_path / "merged", PROTECTED_IGNORE)
        _git(root, "checkout", "--quiet", "-b", "side")
        _write_fixture_inventory(root)
        _git(root, "add", "--force", "--", GUARD.ADR_0018_INVENTORY_RELPATH)
        _git(root, "commit", "--quiet", "-m", "fixture disclosure on a side branch")
        side = _git(root, "rev-parse", "HEAD").stdout.strip()
        _git(root, "checkout", "--quiet", "main")
        (root / "unrelated.txt").write_text("fixture line", encoding="utf-8")
        _git(root, "add", "--", "unrelated.txt")
        _git(root, "commit", "--quiet", "-m", "independent mainline commit")
        _git(root, "merge", "--quiet", "--no-ff", "-m", "fixture merge", "side")
        _git(root, "branch", "--quiet", "-D", "side")
        carried = _git(
            root, "ls-tree", "-r", "--name-only", "HEAD", "--", GUARD.ADR_0018_INVENTORY_RELPATH
        ).stdout.strip()
        assert carried, "an ordinary merge carries the path into its own tree"
        facts = _facts(root, monkeypatch)
        assert side in facts["history"]  # type: ignore[operator]
        assert not _holds(facts)

    def test_a_disclosure_hidden_by_an_ours_merge_still_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The shape default path simplification prunes, and the reason for `--full-history`.

        A side branch commits the inventory and is merged with ``-s ours``, so the
        merge tree omits the path and matches the first parent's for it. Default
        ``git log -- <path>`` treats that as "nothing happened here", follows the
        first parent and prunes the second -- while the disclosure commit stays
        reachable through that pruned parent, and its blob stays retrievable by
        exact SHA. Deleting the side ref changes nothing: reachability comes from
        the merge, not from the branch name.

        This is the case the contract's fifth limb claims to cover, so it is
        asserted directly rather than inferred from the linear cases.
        """
        root, side, merge = _ours_merged_disclosure(tmp_path / "ours-merged")
        assert _git(root, "rev-parse", f"{merge}^2").stdout.strip() == side, (
            "the disclosure must be the merge's second parent"
        )
        _git(root, "merge-base", "--is-ancestor", side, merge)
        omitted = _git(
            root, "ls-tree", "-r", "--name-only", merge, "--", GUARD.ADR_0018_INVENTORY_RELPATH
        ).stdout.strip()
        assert not omitted, "an `ours` merge omits the path from its own tree"
        facts = _facts(root, monkeypatch)
        assert facts["in_index"] is False
        assert facts["in_head"] is False
        assert side in facts["history"], (  # type: ignore[operator]
            "a disclosure reachable through a pruned merge parent is still a disclosure"
        )
        assert not _holds(facts)

    def test_the_full_history_traversal_is_what_detects_the_ours_merged_disclosure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutation, not assertion: the flag is removed and the guard must go blind.

        Without this, the case above would pass without showing which part of the
        query earned the answer. The production helper is run twice against one
        fixture -- once as written, once through a boundary that drops
        ``--full-history`` on the way to git -- and the second run is required to
        find nothing. The helper is never reimplemented here; only the argument
        under test is taken away from it.
        """
        root, side, _merge = _ours_merged_disclosure(tmp_path / "ours-mutated")
        monkeypatch.setattr(GUARD, "REPO_ROOT", root)
        assert side in GUARD._inventory_history_commits()

        real_boundary: Any = GUARD._git_boundary

        def boundary_without_full_history(*args: str) -> Any:
            return real_boundary(*[arg for arg in args if arg != "--full-history"])

        monkeypatch.setattr(GUARD, "_git_boundary", boundary_without_full_history)
        assert not GUARD._inventory_history_commits(), (
            "default path simplification hides this disclosure, so `--full-history` "
            "is load-bearing and not decoration"
        )

    def test_removing_the_runtime_ignore_protection_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _fixture_repo(tmp_path / "unignored", "# no runtime rule at all\n")
        _write_fixture_inventory(root)
        facts = _facts(root, monkeypatch)
        assert facts["written_down"] is False
        assert facts["ignored"] is False
        assert facts["area_ignored"] is False
        assert not _holds(facts)

    def test_an_ignore_rule_scoped_elsewhere_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rule that looks like protection and does not cover the exact path."""
        root = _fixture_repo(tmp_path / "misscoped", ".runtime/data/\n.runtime/**/*.parquet\n")
        _write_fixture_inventory(root)
        facts = _facts(root, monkeypatch)
        assert facts["ignored"] is False
        assert not _holds(facts)

    def test_a_reinclude_under_the_runtime_area_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The edit that removes protection while leaving every rule in place."""
        root = _fixture_repo(
            tmp_path / "reincluded",
            f".runtime/\n{GUARD.ADR_0018_INVENTORY_RELPATH}\n!.runtime/phase3/**\n",
        )
        facts = _facts(root, monkeypatch)
        assert facts["negations"]
        assert not _holds(facts)

    def test_the_contract_does_not_depend_on_the_inventory_contents(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two different synthetic bodies, byte-different, and one set of answers.

        The contract is about where the file may appear, never about what it says,
        so a change of contents must be invisible to it.
        """
        root = _fixture_repo(tmp_path / "contents", PROTECTED_IGNORE)
        path = _write_fixture_inventory(root)
        first = _facts(root, monkeypatch)
        path.write_text('{"schema_version": "fixture-v0", "note": "different"}\n', encoding="utf-8")
        second = _facts(root, monkeypatch)
        assert first == second
        assert _holds(first)

    def test_the_contract_opens_no_file_under_the_private_runtime_area(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Instrumented, not asserted: reading the file would fail this test.

        Every read, open, stat and existence check the contract performs is
        recorded, and any of them landing under the runtime area is the finding.
        The real inventory is present in this checkout, so this runs against the
        state that would actually expose it.
        """
        touched: list[str] = []
        real_open: Any = builtins.open
        real_read_text: Any = Path.read_text
        real_read_bytes: Any = Path.read_bytes
        real_stat: Any = Path.stat
        real_exists: Any = Path.exists

        def spy_open(file: Any, *args: Any, **kwargs: Any) -> Any:
            touched.append(str(file))
            return real_open(file, *args, **kwargs)

        def spy_read_text(target: Path, *args: Any, **kwargs: Any) -> Any:
            touched.append(str(target))
            return real_read_text(target, *args, **kwargs)

        def spy_read_bytes(target: Path) -> Any:
            touched.append(str(target))
            return real_read_bytes(target)

        def spy_stat(target: Path, *args: Any, **kwargs: Any) -> Any:
            touched.append(str(target))
            return real_stat(target, *args, **kwargs)

        def spy_exists(target: Path, *args: Any, **kwargs: Any) -> Any:
            touched.append(str(target))
            return real_exists(target, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", spy_open)
        monkeypatch.setattr(Path, "read_text", spy_read_text)
        monkeypatch.setattr(Path, "read_bytes", spy_read_bytes)
        monkeypatch.setattr(Path, "stat", spy_stat)
        monkeypatch.setattr(Path, "exists", spy_exists)
        facts = _facts(PROJECT_ROOT, monkeypatch)
        assert _holds(facts)
        under_runtime = [p for p in touched if ".runtime" in p.replace("\\", "/")]
        assert not under_runtime, f"the contract touched the private runtime area: {under_runtime}"

    def test_the_contract_enumerates_no_directory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No walk, anywhere -- so no owner-side filename can reach this process.

        A recursive listing under the runtime area is the disclosure the recorded
        listing incident already produced once. The contract needs no enumeration
        at all, so the bar here is zero rather than zero-under-one-prefix.
        """
        enumerated: list[str] = []

        def spy(name: str) -> Any:
            def enumerator(*args: Any, **kwargs: Any) -> Any:
                enumerated.append(name)
                return iter(())

            return enumerator

        monkeypatch.setattr(Path, "glob", spy("Path.glob"))
        monkeypatch.setattr(Path, "rglob", spy("Path.rglob"))
        monkeypatch.setattr(Path, "iterdir", spy("Path.iterdir"))
        monkeypatch.setattr(os, "walk", spy("os.walk"))
        monkeypatch.setattr(os, "listdir", spy("os.listdir"))
        monkeypatch.setattr(os, "scandir", spy("os.scandir"))
        facts = _facts(PROJECT_ROOT, monkeypatch)
        assert _holds(facts)
        assert not enumerated, f"the contract enumerated: {enumerated}"

    def test_only_git_metadata_queries_name_the_inventory_path(self) -> None:
        """And the check is not vacuous: the path IS named, in those queries only.

        A subset assertion over an empty set passes for the wrong reason, so the
        reference set is required to be non-empty first.
        """
        sites = GUARD._inventory_path_reference_sites()
        assert sites, "nothing names the path; the subset check would pass vacuously"
        assert sites <= GUARD.ADR_0018_INVENTORY_QUERY_SITES
        assert "<module>" not in sites

    def test_the_audit_enumerates_no_runtime_directory(self) -> None:
        assert not GUARD._runtime_enumeration_sites()

    def test_no_ignore_rule_makes_the_ignore_limb_a_constant_pass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The limb answers a question rather than agreeing with itself.

        A repository with no ignore policy at all must answer ``False`` for the
        exact path, for the runtime area, and for an unrelated path -- otherwise
        every passing ignore answer above would be a constant.
        """
        root = _fixture_repo(tmp_path / "constant", "# empty policy\n")
        monkeypatch.setattr(GUARD, "REPO_ROOT", root)
        assert GUARD._ignores(GUARD.ADR_0018_INVENTORY_RELPATH) is False
        assert GUARD._ignores(GUARD.ADR_0018_RUNTIME_RELPATH) is False
        assert GUARD._ignores("docs/architecture") is False

    def test_an_unanswerable_git_query_is_a_failure_and_not_a_pass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unanswerable git query is a verification failure, never a pass.

        Pointed at a directory that is not a repository, every limb raises the
        boundary error rather than returning a reassuring ``False``.
        """
        outside = tmp_path / "not-a-repository"
        outside.mkdir()
        (outside / ".gitignore").write_text(PROTECTED_IGNORE, encoding="utf-8")
        monkeypatch.setattr(GUARD, "REPO_ROOT", outside)
        for limb in (
            GUARD._inventory_is_git_ignored,
            GUARD._inventory_is_in_index,
            GUARD._inventory_is_in_head,
            GUARD._inventory_history_commits,
        ):
            with pytest.raises(GUARD.PrivateInventoryBoundaryError):
                limb()


class TestTheDeletionRunbookClarification:
    def test_both_new_prefixes_are_named_as_expected(self) -> None:
        runbook = flat(DELETION_RUNBOOK)
        assert "qualification/sharadar/locators/" in runbook
        assert "qualification/sharadar/reports/" in runbook

    def test_deletion_behaviour_is_explicitly_unchanged(self) -> None:
        assert "deletion behaviour is unchanged by naming them." in flat(DELETION_RUNBOOK)

    def test_the_procedure_never_depends_on_a_locator(self) -> None:
        assert (
            "a locator may be absent, and this procedure must never depend on one to discover "
            "licensed objects." in flat(DELETION_RUNBOOK)
        )


class TestTheAcquisitionDeadlineIsElapsedTime:
    """Gap A, closed.

    The accepted text called 1,800 seconds a wall-clock ceiling and derived it
    from ``48 x 30 s`` plus pacing, which says nothing about whether local work,
    Bronze publication, metadata resolution, locator construction or locator
    retry fall inside it. A number with no scope is a compile-time assertion, and
    an implementation candidate reproduced exactly that. Each guard below pins one
    clause of the scope, the clock, an enforcement point or a refusal.
    """

    def test_the_ceiling_is_an_actual_elapsed_deadline(self) -> None:
        assert (
            "the 1,800-second ceiling is one actual elapsed-time deadline, and not compile-time "
            "arithmetic." in flat(ADR)
        )

    def test_the_clock_is_monotonic_and_calendar_time_is_refused(self) -> None:
        """A daylight-saving transition must not lengthen a licensed acquisition."""
        adr = flat(ADR)
        assert "measured on an injected monotonic clock." in adr
        assert "wall-clock calendar time must never be used for deadline arithmetic" in adr

    def test_the_deadline_spans_stage_eleven_to_stage_thirteen(self) -> None:
        adr = flat(ADR)
        assert (
            "starts immediately before the first provider request, at acquisition stage 11" in adr
        )
        assert (
            "ends only when acquisition reaches a terminal locator result, at acquisition stage 13"
            in adr
        )

    @pytest.mark.parametrize(
        "covered",
        [
            "provider requests",
            "inter-request pacing",
            "local validation and digest work",
            "three bronze publications per completed request",
            "conditional metadata resolution",
            "partial or complete locator construction",
            "locator publication",
            "permitted locator retry",
            "terminal classification",
        ],
    )
    def test_every_phase_of_the_acquisition_execution_is_inside_the_deadline(
        self, covered: str
    ) -> None:
        assert covered in flat(ADR)

    def test_the_gates_before_execution_are_outside_the_deadline(self) -> None:
        """A slow secret retrieval must not spend budget belonging to licensed work."""
        assert "gates that happen before acquisition execution begins" in flat(ADR)

    def test_nothing_starts_on_hope_and_a_short_run_halts(self) -> None:
        adr = flat(ADR)
        assert "no operation may be started merely in the hope that it completes before it" in adr
        assert "the run halts before starting another provider request." in adr

    def test_pacing_is_refused_rather_than_truncated(self) -> None:
        """Quietly shortening pacing to save a run is the trade this refuses."""
        assert "pacing is never silently shortened." in flat(ADR)

    def test_a_halt_keeps_completed_work_and_discounts_unpersisted_bytes(self) -> None:
        adr = flat(ADR)
        assert "completed requests | remain completed." in adr
        assert "an unpersisted response | is not a completed request." in adr

    def test_an_unwritable_locator_is_never_claimed_to_exist(self) -> None:
        adr = flat(ADR)
        assert "it must not claim a locator exists" in adr
        assert "`locator_not_published`" in adr

    def test_exhaustion_is_closed_sanitized_and_grants_nothing(self) -> None:
        adr = flat(ADR)
        assert "deadline exhaustion is a closed, sanitized status" in adr
        assert (
            "no exception text, private identifier, key, subject, digest, vendor row or timing "
            "trace" in adr
        )
        assert (
            "deadline exhaustion never authorizes a retry, a resume or a new execution identity."
            in adr
        )

    def test_the_sdk_cannot_defeat_the_deadline(self) -> None:
        """A deadline the library underneath ignores is not a deadline."""
        adr = flat(ADR)
        assert "disabled for qualification s3 calls." in adr
        assert "adaptive or hidden retry mode | forbidden" in adr
        assert "connect timeout | explicit and bounded" in adr
        assert "read timeout | explicit and bounded" in adr
        assert "is the only locator retry" in adr
        assert "bronze writes | remain unretried" in adr
        assert "sdk automatic retries enabled" not in adr

    def test_the_reserve_covers_the_whole_permitted_locator_sequence(self) -> None:
        """Three locator PutObject attempts and at most one locator HeadObject."""
        locator_operations = MAX_LOCATOR_ATTEMPTS + 1
        assert locator_operations == 4
        adr = flat(ADR)
        assert f"cover `{locator_operations} * t_s3 + c`" in adr
        assert "configuration that cannot fit is refused, not clamped." in adr

    def test_a_request_is_admitted_only_with_its_whole_downstream_budget(self) -> None:
        """Three Bronze writes plus the at-most-three HEADs they may trigger."""
        worst_case_operations = 2 * OBJECTS_PER_ACQUISITION
        assert worst_case_operations == 6
        assert f"remaining >= t_req + {worst_case_operations} * t_s3 + l" in flat(ADR)

    def test_the_sub_budget_values_are_left_to_the_correction_review(self) -> None:
        """Numbers that cannot be derived from committed constraints are not invented."""
        adr = flat(ADR)
        assert (
            "required implementation constant whose proposed numerical value must be reviewed "
            "with the correction pull request" in adr
        )
        for constant in (
            "s3_connect_timeout_seconds",
            "s3_read_timeout_seconds",
            "s3_operation_ceiling",
            "locator_construction_allowance",
            "locator_terminal_reserve",
        ):
            assert constant in adr

    def test_the_worst_case_does_not_fit_and_the_adr_says_so(self) -> None:
        """The honest consequence: the deadline bounds elapsed time, not completion."""
        provider_time = REQUESTS * (PROVIDER_CEILING_SECONDS + MIN_PACING_SECONDS)
        residual = DEADLINE_SECONDS - provider_time
        bronze_worst_case_operations = 2 * OBJECTS_PER_ACQUISITION * REQUESTS
        assert provider_time == 1488
        assert residual == 312
        assert bronze_worst_case_operations == 288
        assert round(residual / bronze_worst_case_operations, 2) == 1.08
        adr = flat(ADR)
        assert f"{REQUESTS} * ({PROVIDER_CEILING_SECONDS} + {MIN_PACING_SECONDS}) = 1488 s" in adr
        assert (
            "the 1,800-second deadline is therefore a safety bound on elapsed time, and not a "
            f"guarantee that {REQUESTS} requests complete." in adr
        )

    def test_the_ceiling_is_not_raised(self) -> None:
        adr = flat(ADR)
        assert "raising it is an adr change" in adr
        assert "wall-clock ceiling | 1,800 seconds" not in adr

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_status_documents_carry_the_deadline(self, document: Path) -> None:
        text = flat(document)
        assert "1,800-second acquisition elapsed-time deadline" in text
        assert "injected monotonic clock" in text
        assert "and not compile-time arithmetic" in text
        assert "wall clock 1,800 s" not in text


class TestTheCombinedRunAAndRunBAssessment:
    """Gap B, closed.

    P1's TESTED ceiling asks whether the same rows changed between two
    observations separated by real calendar time. No per-run assessment can
    answer that, so the canonical assessment consumes both executions.
    """

    def test_one_assessment_consumes_both_executions(self) -> None:
        assert "one combined private assessment evaluates run a and run b together" in flat(ADR)

    def test_the_assessor_takes_three_private_inputs_in_fixed_order(self) -> None:
        adr = flat(ADR)
        assert "1 run a execution identity 2 run b execution identity 3 one new assessment" in adr

    @pytest.mark.parametrize(
        "requirement",
        [
            "two distinct execution identities.",
            "both locators `complete`",
            "`publication_state_unknown = false` for both",
            "the same plan digest",
            "the same inventory digest",
            "the same source-schema version",
            "exactly 48 planned and 48 completed requests in each",
            "matching subject-class and request inventories",
            "run a ordered before run b",
            "at least eight calendar days between the accepted run dates",
        ],
    )
    def test_every_pair_precondition_is_stated(self, requirement: str) -> None:
        assert requirement in flat(ADR)

    def test_the_pair_is_validated_before_any_payload_is_read(self) -> None:
        adr = flat(ADR)
        assert "before any acquisition record or payload is read." in adr
        assert "no payload is read on a refusal" in adr

    def test_neither_locator_is_found_by_listing(self) -> None:
        """A producer or assessor that could list the store could enumerate it."""
        adr = flat(ADR)
        assert "both locator keys are resolved without listing" in adr
        assert "s3 listing | `0`" in adr

    def test_a_refused_pair_reads_at_most_two_locators_and_nothing_else(self) -> None:
        assert f"locator `getobject` | 0 to {EXECUTIONS}" in flat(ADR)

    def test_observed_counters_are_never_replaced_by_nominal_ones(self) -> None:
        assert "never report nominal counts as observed counts" in flat(ADR)

    def test_the_report_key_binds_both_executions_in_order(self) -> None:
        adr = flat(ADR)
        assert (
            "licensed/qualification/sharadar/reports/<run-a-execution-id>/"
            "<run-b-execution-id>/<assessment-id>.json" in adr
        )
        assert "three separately validated path segments" in adr
        assert "preserves run a / run b order" in adr
        assert "forbids identical execution identities" in adr

    def test_the_combined_report_carries_no_verdict(self) -> None:
        assert (
            "no aggregate verdict, no provider-selection value, no readiness value and no "
            "operational recommendation" in flat(ADR)
        )

    def test_no_preliminary_run_a_report_is_introduced(self) -> None:
        adr = flat(ADR)
        assert "no preliminary run a report is required by this architecture" in adr

    def test_the_assessment_reaches_no_provider_and_no_credential(self) -> None:
        assert (
            "no provider credential, no secret access, no provider transport, no provider "
            "request, no s3 listing, no delete, no copy, no bronze publication, no control "
            "operation and no local report" in flat(ADR)
        )

    def test_p1_is_capped_by_run_a_alone_and_tested_is_only_a_ceiling(self) -> None:
        adr = flat(ADR)
        assert "run a evidence alone has a p1 ceiling of `partially_tested`" in adr
        assert (
            "the information-time limitation remains explicitly bounded even when p1 reaches "
            "`tested`." in adr
        )
        assert "never becomes a weaker pass." in adr
        assert "p1 may remain `partially_tested` or insufficient after run b" in adr
        assert "`tested` is a ceiling, not an expected outcome." in adr
        assert (
            "no p1 result is an aggregate provider verdict, and no p1 result is a g1 or g2 "
            "decision." in adr
        )

    def test_the_delivery_sequence_places_one_combined_assessment_after_run_b(self) -> None:
        assert "one owner-only combined run a / run b assessment" in flat(ADR)

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_status_documents_carry_the_combined_arithmetic(self, document: Path) -> None:
        text = flat(document)
        assert f"`e × (2r + 1)` = {COMBINED_GETOBJECTS}" in text  # noqa: RUF001
        assert f"{COMBINED_GETOBJECTS + 1} to {COMBINED_GETOBJECTS + 2}" in text
        assert "whole empirical package 485 to 780" in text
        assert "`2r + 1` = 97" not in text


class TestTheClarificationAmendmentClaimsNothing:
    """Effective on merge of PR #42 -- exactly as the ADR itself became on PR #39.

    A clarification read as an authorization is the same drift the pre-merge
    ADR-0018 guards exist to catch, one document later. Making it effective
    changed what the architecture *means*; it opened no gate, so every
    NOT AUTHORIZED boundary is still required here rather than retired.
    """

    def test_the_amendment_status_is_conditional(self) -> None:
        """Immutable: the conditional line is the thing the merge satisfied."""
        assert (
            "status of this amendment: proposed — effective only upon merge of the pull request "
            "introducing it." in flat(ADR)
        )

    def test_the_amendment_records_that_its_own_merge_has_occurred(self) -> None:
        adr = flat(ADR)
        assert "the clarification's own merge has since occurred" in adr
        assert "the conditional effectiveness event has occurred" in adr

    def test_the_amendment_names_its_merge_commit_and_approved_head(self) -> None:
        """A merge recorded only as a number cannot be checked against history."""
        adr = flat(ADR)
        assert ADR_0018_CLARIFICATION_MERGE_COMMIT in adr
        assert ADR_0018_CLARIFICATION_APPROVED_HEAD in adr

    def test_the_audit_pins_the_same_merge_commit_and_approved_head(self) -> None:
        """The audit and this file must not drift into two different merges."""
        audit = AUDIT.read_text(encoding="utf-8")
        assert f'ADR_0018_CLARIFICATION_PR: Final = "{ADR_0018_CLARIFICATION_PR}"' in audit
        assert (
            "ADR_0018_CLARIFICATION_MERGE_COMMIT: Final = "
            f'"{ADR_0018_CLARIFICATION_MERGE_COMMIT}"' in audit
        )
        assert (
            "ADR_0018_CLARIFICATION_APPROVED_HEAD: Final = "
            f'"{ADR_0018_CLARIFICATION_APPROVED_HEAD}"' in audit
        )

    def test_the_amendment_keeps_its_pre_merge_no_authority_fact(self) -> None:
        """Effectiveness now does not backdate authority onto the days before it."""
        assert (
            f"while pr {ADR_0018_CLARIFICATION_PR} was open the clarification was proposed and "
            "carried no authority" in flat(ADR)
        )

    def test_the_merge_approved_clarification_of_architecture_only(self) -> None:
        assert "the merge approved clarification of architecture only" in flat(ADR)

    def test_the_amendment_records_the_blocking_review_outcome(self) -> None:
        assert "`blocked_adr_clarification_required`" in flat(ADR)

    def test_the_amendment_opens_no_gate(self) -> None:
        adr = flat(ADR)
        assert "this clarification authorizes none of the later gates." in adr
        assert (
            "the offline implementation candidate cannot be merged until it is corrected against "
            "this clarification" in adr
        )

    def test_clarifying_an_architecture_is_not_correcting_an_implementation(self) -> None:
        assert "clarifying an architecture is not correcting an implementation" in flat(ADR)

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_documents_record_the_amendment_as_effective(self, document: Path) -> None:
        """Inverted on the merge, not deleted, and the superseded spelling is gone."""
        text = flat(document)
        assert (
            f"the clarification amendment is effective — pr {ADR_0018_CLARIFICATION_PR} merged"
            in text
        )
        assert ADR_0018_CLARIFICATION_MERGE_COMMIT in text
        assert ADR_0018_CLARIFICATION_APPROVED_HEAD in text
        assert "the conditional effectiveness event has occurred" in text
        superseded = "a clarification amendment is proposed and is not effective until merged"
        assert superseded not in text

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_documents_name_the_two_decisions_now_effective(self, document: Path) -> None:
        """Recording that something happened is not recording what now governs."""
        text = flat(document)
        assert (
            "adr-0018's total elapsed acquisition deadline clarification is now effective" in text
        )
        assert "adr-0018's combined run a / run b assessment clarification is now effective" in text

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_documents_keep_the_amendments_pre_merge_no_authority_fact(
        self, document: Path
    ) -> None:
        assert (
            f"while pr {ADR_0018_CLARIFICATION_PR} was open the clarification was proposed and "
            "carried no authority" in flat(document)
        )

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_documents_keep_the_clarification_merge_authorizing_nothing(
        self, document: Path
    ) -> None:
        """An effective clarification is a meaning, never a permission."""
        text = flat(document)
        assert "the merge approved clarification of architecture only" in text
        assert (
            "the clarification merge authorized no implementation, no infrastructure mutation "
            "and no execution" in text
        )
        for still_gated in STILL_UNAUTHORIZED:
            assert still_gated in text

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_documents_record_the_merged_offline_implementation(self, document: Path) -> None:
        """Inverted, not deleted.

        This guard required "unmerged and not accepted" while the implementation sat
        on an open pull request, and it forbade "pr #41 is merged" because at that
        point the claim would have been false. PR #41 has since merged, so the guard
        is turned around rather than removed: what must now be recorded is that the
        implementation is **merged and dormant**, that the correction happened, that
        the independent re-review has since occurred, and that PR #44 merged after
        it. The superseded spellings move into the refusal set below, so a revert is
        caught rather than merely un-asserted -- and every claim that reads a merged
        implementation as a **deployed** or **executed** one stays forbidden, because
        crossing the first gate is not crossing the second or the third.
        """
        text = flat(document)
        assert "the offline implementation is merged, dormant and never executed" in text
        assert "corrected against the now-authoritative clarification" in text
        assert (
            "the independent re-review has since occurred and produced the fixed-count "
            f"correction merged as pr {ADR_0018_FIX_PR}" in text
        )
        assert (
            "merging an implementation authorized no execution, no infrastructure "
            "deployment and no run" in text
        )
        for pinned in (
            ADR_0018_IMPL_MERGE_COMMIT,
            ADR_0018_IMPL_APPROVED_HEAD,
            ADR_0018_FIX_MERGE_COMMIT,
            ADR_0018_FIX_APPROVED_HEAD,
        ):
            assert pinned in text
        for superseded in (
            "the offline implementation candidate is unmerged and not accepted",
            "awaits an independent re-review",
            "implementation candidate, not merged, not accepted, never executed",
            "read surface does not exist",
            "exists only as dormant code on an open pull request",
            "adr-0018 implementation: not authorized",
        ):
            assert superseded not in text
        for overstated in (
            "implementation candidate is ready to merge",
            "implementation candidate may be merged",
            "the implementation is deployed",
            "qualification infrastructure is deployed",
            "run a qualified the provider",
            "run b was executed",
            "the combined assessment was executed",
            "the empirical qualification passed",
            "provider selection has occurred",
        ):
            assert overstated not in text

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_documents_keep_the_two_merge_events_separate(self, document: Path) -> None:
        """The order the two merges happened in is itself a governance fact.

        PR #41 merged with the fixed-count validation still missing; the defect was
        dormant only because execution was not authorized; PR #44 corrected it
        afterwards. Collapsing the two would credit the implementation with a review
        that had not happened when it merged.
        """
        text = flat(document)
        assert (
            f"while pr {ADR_0018_IMPL_PR} was open it was an unmerged implementation candidate"
            in text
        )
        assert (
            f"before pr {ADR_0018_IMPL_PR} merged, the offline package and its two dormant "
            "entry points were absent from main" in text
        )
        assert (
            f"pr {ADR_0018_IMPL_PR} merged before the missing fixed-count validation was "
            "corrected" in text
        )
        assert "the defect remained dormant because execution was not authorized" in text
        assert f"pr {ADR_0018_FIX_PR} subsequently corrected the implementation on main" in text
        assert (
            f"pr {ADR_0018_IMPL_PR} is not described as having passed the later pr "
            f"{ADR_0018_FIX_PR} correction review" in text
        )
        assert (
            "no run a, run b or combined assessment occurred before, during or after "
            "either merge" in text
        )
        assert (
            "the premature merge is no evidence of execution or of empirical qualification" in text
        )

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_documents_state_the_read_implementation_precisely(self, document: Path) -> None:
        """A reading implementation existing is not private evidence existing.

        "The read surface does not exist" was true of the accepted tree and is false
        now, so it is replaced by what is actually true of the merged code rather
        than softened. Each clause is separate because a single sentence covering
        all of them is one a later edit can weaken in place.
        """
        text = flat(document)
        for clause in (
            "the bounded assessment-only read implementation now exists in committed code",
            "it is dormant and not deployed",
            "it permits no s3 listing",
            "it is not a general read surface",
            "it has never been executed against licensed objects",
            "no locator, record, payload or report has been read by the empirical package",
            "the acquisition process remains write-only",
            "the ordinary ingestion path remains unable to use the qualification read surface",
            "a reading implementation existing is not private evidence existing",
        ):
            assert clause in text
        for overstated in (
            "a general licensed object read surface exists",
            "licensed objects have been read",
        ):
            assert overstated not in text

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_documents_keep_the_four_states_apart(self, document: Path) -> None:
        """Architecture, implementation, deployment and execution are four states.

        Merging an implementation moved exactly one of them. This is the row where
        collapsing any two would show up.
        """
        text = flat(document)
        for distinction in (
            "adr-0018 architecture: accepted / in force",
            "adr-0018 offline implementation: merged / dormant",
            "fixed 48-request correction: merged",
            "infrastructure deployment: not authorized / not performed",
            "implementation execution: not authorized / zero",
            "run a: not authorized / not run",
            "run b: not authorized / not run",
            "combined assessment: not authorized / not run",
        ):
            assert distinction in text

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_documents_record_the_sanitized_incident(self, document: Path) -> None:
        """Recorded, sanitized, and carrying no permission to look again."""
        text = flat(document)
        assert "unauthorized directory listing beneath the private runtime area" in text
        assert "read no file contents" in text
        assert "no tracked contamination was found by the read-only review" in text
        assert "filenames are intentionally not disclosed" in text
        assert "authorizes neither private-directory inspection nor further diagnosis" in text
