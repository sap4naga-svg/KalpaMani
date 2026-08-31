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
3. **The architecture is still only an architecture.** Every artifact the ADR
   designs is asserted **absent**, because "approves architecture only" is a claim
   about the repository and not a sentence about intent, and implementation,
   infrastructure mutation and execution are each required to still read
   NOT AUTHORIZED.
4. **The clarification amendment says what it clarifies, and claims nothing more.**
   It makes 1,800 seconds an actual elapsed-time deadline with a stated scope, a
   stated clock and stated enforcement points, and it makes the canonical
   assessment a combined one over both acquisition executions. Both are
   **PROPOSED** and take effect only on merge, exactly as the ADR itself did, and
   neither opens a gate. The combined arithmetic is derived here from `R` and `E`
   rather than transcribed, for the same reason the acquisition arithmetic is.
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

#: The pull request whose merge satisfied ADR-0018's conditional acceptance.
ADR_0018_PR = "#39"

#: What approving a design did **not** do. Each is separately checkable, so each
#: is separately required of both status documents -- an accepted architecture
#: read as permission to build, provision or run is the drift this guards.
STILL_UNAUTHORIZED = (
    "adr-0018 implementation: not authorized",
    "infrastructure mutation: not authorized",
    "run a: not authorized",
    "run b: not authorized",
    "assessment: not authorized",
)

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
    @pytest.mark.parametrize("path", DESIGNED_BUT_ABSENT, ids=lambda p: p.name)
    def test_every_designed_artifact_is_absent(self, path: Path) -> None:
        assert not path.exists(), (
            f"{path.name} exists. ADR-0018 approves architecture only; implementation, "
            "infrastructure mutation and execution are three separate gates."
        )

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
    """PROPOSED, and effective only on merge -- exactly as the ADR itself was.

    A clarification read as an authorization is the same drift the pre-merge
    ADR-0018 guards exist to catch, one document later.
    """

    def test_the_amendment_status_is_conditional(self) -> None:
        assert (
            "status of this amendment: proposed — effective only upon merge of the pull request "
            "introducing it." in flat(ADR)
        )

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
    def test_both_documents_keep_the_amendment_ineffective_until_merged(
        self, document: Path
    ) -> None:
        assert "a clarification amendment is proposed and is not effective until merged" in flat(
            document
        )

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_documents_keep_the_implementation_candidate_blocked(self, document: Path) -> None:
        text = flat(document)
        assert "unmerged and blocked" in text
        assert "it cannot be merged until it is corrected against the clarified adr" in text
        for premature in (
            "implementation candidate is ready to merge",
            "implementation candidate may be merged",
            "pr #41 is ready to merge",
        ):
            assert premature not in text

    @pytest.mark.parametrize("document", [CLAUDE_MD, README], ids=["CLAUDE.md", "README.md"])
    def test_both_documents_record_the_sanitized_incident(self, document: Path) -> None:
        """Recorded, sanitized, and carrying no permission to look again."""
        text = flat(document)
        assert "unauthorized directory listing beneath the private runtime area" in text
        assert "read no file contents" in text
        assert "no tracked contamination was found by the read-only review" in text
        assert "filenames are intentionally not disclosed" in text
        assert "authorizes neither private-directory inspection nor further diagnosis" in text
