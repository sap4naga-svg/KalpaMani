"""ADR-0018 is PROPOSED, and the repository has to keep saying so.

A merged ADR drifts by having its facts go stale. A **proposed** one drifts a
different way: the document exists, it reads like a decision, and a later session
treats it as authority it does not have. That has a precedent in this repository
-- ADR-0017 spent time in an open pull request while its own text already read
"Accepted", and the status documents had to carry the distinction explicitly.

These are text and arithmetic checks over committed files. **Nothing here
contacts AWS, a provider or a network**, and nothing here imports the operational
entry points. What they guard is three things:

1. **The conditional status stays conditional.** The ADR says it is accepted only
   on merge, says the merge has not happened, and supersedes nothing.
2. **The arithmetic is recomputed, not quoted.** ADR-0018 states a nominal and a
   maximum operation count. A count copied from prose into prose is a count
   nobody checks, so the numbers are derived here from the package's own
   parameters and compared against what the ADR says.
3. **The architecture is still only an architecture.** Every artifact the ADR
   designs is asserted **absent**, because "authorizes architecture only" is a
   claim about the repository and not a sentence about intent.
"""

from __future__ import annotations

import re
from pathlib import Path

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

#: The artifacts ADR-0018 designs and does not create. Implementation is a
#: separate gate; these paths existing is what crossing it looks like.
DESIGNED_BUT_ABSENT = (
    PROJECT_ROOT / "src" / "kalpamani" / "data" / "qualify",
    PROJECT_ROOT / "scripts" / "sharadar_empirical_qualification.py",
    PROJECT_ROOT / "scripts" / "sharadar_qualification_assessment.py",
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


def flat(path: Path) -> str:
    """The document with emphasis removed, whitespace collapsed and case folded.

    The same normalisation the documentation audit uses, and for the same reason:
    a rewrapped line and a bolded phrase are the same claim, and a guard that
    only sees one of them is a guard a reflow disables.
    """
    return " ".join(path.read_text(encoding="utf-8").replace("**", "").split()).lower()


class TestTheStatusStaysConditional:
    def test_the_status_line_is_the_exact_conditional_acceptance(self) -> None:
        assert (
            "status: accepted — effective only upon merge of the pull request "
            "introducing this adr." in flat(ADR)
        )

    def test_the_adr_says_the_merge_condition_has_not_been_met(self) -> None:
        assert "before that merge this adr is proposed and carries no authority." in flat(ADR)

    def test_the_adr_supersedes_nothing(self) -> None:
        assert "supersedes: nothing." in flat(ADR)

    def test_the_adr_is_absent_from_the_merged_registry(self) -> None:
        """A merged-ADR registry entry asserts an acceptance that has not happened."""
        registry = AUDIT.read_text(encoding="utf-8")
        block = registry.split("MERGED_ADR_STATUS: Final", 1)[1].split(")\n", 1)[0]
        assert "ADR-0018" not in block

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_status_documents_record_it_as_proposed(self, document: Path) -> None:
        assert "proposed — not accepted, and it carries no authority." in flat(document)

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_neither_document_claims_it_is_in_force(self, document: Path) -> None:
        """The audit's own in-force pattern, applied to the ADR-0018 rows."""
        in_force = re.compile(
            r"ACCEPTED\s*/\s*IN\s+FORCE.*?\bPR\s*#\d+\s+merged", re.IGNORECASE | re.DOTALL
        )
        rows = [
            line
            for line in document.read_text(encoding="utf-8").splitlines()
            if line.lstrip().startswith("|") and "ADR-0018-bounded-private" in line.split("|")[1]
        ]
        assert rows, "the ADR-0018 status row must exist to be checked"
        assert not any(in_force.search(row.replace("**", "")) for row in rows)


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

    def test_the_assessment_read_formula_excludes_claims(self) -> None:
        reads = 2 * REQUESTS + 1
        assert reads == 97
        adr = flat(ADR)
        assert "acquisition-claim `getobject` | `0`" in adr
        assert f"`2r + 1` | {reads}" in adr
        assert f"`2r + 2` to `2r + 3` | {reads + 1} to {reads + 2}" in adr

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
    @pytest.mark.parametrize("path", DESIGNED_BUT_ABSENT, ids=lambda p: p.name)
    def test_every_designed_artifact_is_absent(self, path: Path) -> None:
        assert not path.exists(), (
            f"{path.name} exists. ADR-0018 approves architecture only; implementation, "
            "infrastructure mutation and execution are three separate gates."
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
