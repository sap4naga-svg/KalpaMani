"""P1-P9 evaluation under compiled ceilings, and no aggregate verdict anywhere.

**A ceiling is what a test may at most report.** A run may fall short of one; no run
may exceed one. The ceilings are compiled constants here rather than sentences in a
document, and :func:`evaluate` refuses to emit a status above the ceiling for its
test -- so a favourable empirical result cannot upgrade a limitation that is
structural rather than evidential.

**There is no aggregate verdict, and there is no field one could be written into.**
No aggregate pass, no qualified, no approved, no proceed, no ready, no
provider-selection value and no readiness value. Provider selection is G1, and G1 is
the owner's decision, taken by a person reading evidence and never returned by a
program. A test asserts that none of those words appears anywhere in this module's
vocabulary.

**Insufficiency is a status, never a weaker pass.** A truncated page, an absent
column, a digest that did not verify and a limb whose evidence this process
structurally cannot hold each produce an explicit insufficiency. Downgrading one to
a softer positive would be the single most damaging thing this module could do,
because it would convert *we did not measure it* into *we measured it and it was
fine*.

**Cross-run evidence comes from a combined assessment, and from nowhere else.**
:func:`evaluate` sees one execution's evidence and its change-detection limb reports
insufficiency, because one observation cannot show that anything changed.
:func:`evaluate_combined` sees both executions, matched subject by subject by the
assessor, and is the only way P1 can reach ``TESTED``.

**The two are told apart by a value on the result, not by a convention.** Every
:class:`TestResult` carries an :class:`EvidenceScope`, and ``__post_init__`` holds a
``SINGLE_EXECUTION`` result to the single-execution ceiling and a ``COMBINED``
result to the architecture ceiling. So a single run **cannot** report the cross-run
P1 ceiling even if some future caller assembled the fields by hand: the guard is on
the object rather than in the function that happens to build it.

**Reaching a ceiling is never expected, only permitted.** ``TESTED`` for P1 requires
comparable evidence from both runs -- both deliveries usable, both carrying the
update column, and the schema stable between them. Missing, incomparable, truncated
or schema-drifted evidence leaves P1 at ``PARTIALLY_TESTED`` or below, and **never
becomes a weaker pass**. The information-time limb stays ``BOUNDED`` in both scopes
regardless of outcome: a date-granular source cannot supply an instant, and no
quantity of runs changes that.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.qualify.sharadar.parser import PagePair, date_field, decimal_field


class ProviderTest(StrEnum):
    """The nine provider tests, named and never renumbered."""

    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"
    P5 = "P5"
    P6 = "P6"
    P7 = "P7"
    P8 = "P8"
    P9 = "P9"


class TestStatus(StrEnum):
    """How far a test got. A closed ladder, and every rung is honest about itself.

    ``DEFERRED``
        Belongs to a later phase and was not attempted. It needs a dataset this
        package refuses by name, or a source outside the provider entirely.
    ``INSUFFICIENT_EVIDENCE``
        Attempted, and the evidence needed was absent, truncated or unverifiable.
        **Never a weaker pass.**
    ``DOCUMENTATION_RESOLVED``
        Answered from public documentation, and **no quantity of rows can lift it**.
        The question is about the provider's production process rather than about
        its data, or about a table with no time axis to sample.
    ``PARTIALLY_TESTED``
        Some limbs were measured and at least one remains inconclusive or bounded.
    ``TESTED``
        Every limb this architecture can reach was measured.
    """

    DEFERRED = "DEFERRED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    DOCUMENTATION_RESOLVED = "DOCUMENTATION_RESOLVED"
    PARTIALLY_TESTED = "PARTIALLY_TESTED"
    TESTED = "TESTED"


#: The ladder as ranks, so a ceiling can be enforced by comparison. Total over the
#: vocabulary, and a test asserts it: a member added later with no rank would raise
#: rather than silently compare as something.
STATUS_RANK: Final[dict[TestStatus, int]] = {
    TestStatus.DEFERRED: 0,
    TestStatus.INSUFFICIENT_EVIDENCE: 1,
    TestStatus.DOCUMENTATION_RESOLVED: 2,
    TestStatus.PARTIALLY_TESTED: 3,
    TestStatus.TESTED: 4,
}

#: The compiled per-test ceilings. **The accepted architecture, as constants.**
#:
#: P1 may reach ``TESTED`` only across two runs; P2 ceilings at
#: ``PARTIALLY_TESTED`` because sampled existence is not a population claim; P3's
#: schema question is decidable from a delivered header; P4 and P9 are
#: documentation-resolved and no sample can lift either; P5 ceilings at
#: ``PARTIALLY_TESTED`` while the spinoff semantics stay undocumented; P6, P7 and P8
#: are deferred to a later phase.
TEST_CEILINGS: Final[dict[ProviderTest, TestStatus]] = {
    ProviderTest.P1: TestStatus.TESTED,
    ProviderTest.P2: TestStatus.PARTIALLY_TESTED,
    ProviderTest.P3: TestStatus.TESTED,
    ProviderTest.P4: TestStatus.DOCUMENTATION_RESOLVED,
    ProviderTest.P5: TestStatus.PARTIALLY_TESTED,
    ProviderTest.P6: TestStatus.DEFERRED,
    ProviderTest.P7: TestStatus.DEFERRED,
    ProviderTest.P8: TestStatus.DEFERRED,
    ProviderTest.P9: TestStatus.DOCUMENTATION_RESOLVED,
}

#: The highest status a **single-execution** assessment may report for each test.
#:
#: Distinct from :data:`TEST_CEILINGS` on purpose, and the distinction is the honest
#: part. The architecture permits P1 to reach ``TESTED`` across two runs; one
#: execution holds one observation, so its change-detection limb has no evidence at
#: all. This table is what one assessment can achieve, and it is never above the
#: ceiling.
SINGLE_EXECUTION_CEILINGS: Final[dict[ProviderTest, TestStatus]] = {
    ProviderTest.P1: TestStatus.PARTIALLY_TESTED,
    ProviderTest.P2: TestStatus.PARTIALLY_TESTED,
    ProviderTest.P3: TestStatus.TESTED,
    ProviderTest.P4: TestStatus.DOCUMENTATION_RESOLVED,
    ProviderTest.P5: TestStatus.PARTIALLY_TESTED,
    ProviderTest.P6: TestStatus.DEFERRED,
    ProviderTest.P7: TestStatus.DEFERRED,
    ProviderTest.P8: TestStatus.DEFERRED,
    ProviderTest.P9: TestStatus.DOCUMENTATION_RESOLVED,
}


class EvidenceScope(StrEnum):
    """How much evidence a result was computed from.

    ``SINGLE_EXECUTION``
        One acquisition execution. Held to :data:`SINGLE_EXECUTION_CEILINGS`.
    ``COMBINED``
        Both acquisition executions, matched subject by subject. Held to
        :data:`TEST_CEILINGS`, which is the only scope in which P1 may reach
        ``TESTED``.
    """

    SINGLE_EXECUTION = "SINGLE_EXECUTION"
    COMBINED = "COMBINED"


class Limb(StrEnum):
    """The individually-answerable parts of the nine tests.

    Named so a report can say *which* half of a test was reached, which is the
    difference between a useful evidence record and a status word.
    """

    P1_INFORMATION_TIME_RESOLUTION = "P1_INFORMATION_TIME_RESOLUTION"
    P1_UPDATE_COLUMN_PRESENT = "P1_UPDATE_COLUMN_PRESENT"
    P1_CROSS_RUN_CHANGE_DETECTION = "P1_CROSS_RUN_CHANGE_DETECTION"
    P2_DELISTED_HISTORY_EXISTS = "P2_DELISTED_HISTORY_EXISTS"
    P2_POPULATION_SURVIVORSHIP = "P2_POPULATION_SURVIVORSHIP"
    P2_IDENTIFIER_TRANSITION = "P2_IDENTIFIER_TRANSITION"
    P3_ACTION_SCHEMA_DELIVERED = "P3_ACTION_SCHEMA_DELIVERED"
    P3_ANNOUNCEMENT_TIMING = "P3_ANNOUNCEMENT_TIMING"
    P4_CLASSIFICATION_HISTORY = "P4_CLASSIFICATION_HISTORY"
    P5_SPLIT_RECONCILIATION = "P5_SPLIT_RECONCILIATION"
    P5_DIVIDEND_RECONCILIATION = "P5_DIVIDEND_RECONCILIATION"
    P5_SPINOFF_RECONCILIATION = "P5_SPINOFF_RECONCILIATION"
    P6_KNOWN_RESTATEMENT = "P6_KNOWN_RESTATEMENT"
    P7_FILING_LINKAGE = "P7_FILING_LINKAGE"
    P8_EARNINGS_TIMING = "P8_EARNINGS_TIMING"
    P9_BAR_CONSTRUCTION_ORIGIN = "P9_BAR_CONSTRUCTION_ORIGIN"


class LimbStatus(StrEnum):
    """What happened to one limb.

    ``OBSERVED``
        Measured, and the measurement is recorded.
    ``INCONCLUSIVE``
        Measured, and the evidence does not decide the question.
    ``INSUFFICIENT``
        The evidence needed was absent, truncated or unverifiable.
    ``BOUNDED``
        A permanent limitation of the source. **Not liftable by any outcome**, and
        recorded regardless of how well everything else went.
    ``DEFERRED``
        Belongs to a later phase and was not attempted here.
    """

    OBSERVED = "OBSERVED"
    INCONCLUSIVE = "INCONCLUSIVE"
    INSUFFICIENT = "INSUFFICIENT"
    BOUNDED = "BOUNDED"
    DEFERRED = "DEFERRED"


class Reason(StrEnum):
    """Why a limb ended where it did. Closed, and carrying no vendor value."""

    MEASURED = "MEASURED"
    DATE_GRANULAR_SOURCE = "DATE_GRANULAR_SOURCE"
    CROSS_RUN_EVIDENCE_ABSENT = "CROSS_RUN_EVIDENCE_ABSENT"
    CROSS_RUN_EVIDENCE_COMPARED = "CROSS_RUN_EVIDENCE_COMPARED"
    CROSS_RUN_SCHEMA_DRIFTED = "CROSS_RUN_SCHEMA_DRIFTED"
    CROSS_RUN_MARKER_NOT_DELIVERED = "CROSS_RUN_MARKER_NOT_DELIVERED"
    SAMPLED_NOT_POPULATION = "SAMPLED_NOT_POPULATION"
    COLUMN_NOT_DELIVERED = "COLUMN_NOT_DELIVERED"
    NO_ROWS_DELIVERED = "NO_ROWS_DELIVERED"
    DELIVERY_TRUNCATED = "DELIVERY_TRUNCATED"
    SCHEMA_UNSTABLE = "SCHEMA_UNSTABLE"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    SNAPSHOT_HAS_NO_TIME_AXIS = "SNAPSHOT_HAS_NO_TIME_AXIS"
    PROVIDER_SEMANTICS_UNDOCUMENTED = "PROVIDER_SEMANTICS_UNDOCUMENTED"
    PRICE_ORIGIN_PROVIDER_DERIVED = "PRICE_ORIGIN_PROVIDER_DERIVED"
    REQUIRES_LATER_PHASE_DATASET = "REQUIRES_LATER_PHASE_DATASET"
    REQUIRES_EXTERNAL_SOURCE = "REQUIRES_EXTERNAL_SOURCE"


class MeasurementKind(StrEnum):
    """The shape of a recorded measurement, so the report schema stays closed."""

    COUNT = "COUNT"
    DATE = "DATE"
    DECIMAL = "DECIMAL"
    FLAG = "FLAG"


class MeasurementName(StrEnum):
    """Every quantity this evaluator may record. An allowlist, not free text.

    **No member names a security.** A measurement counts subjects, rows, columns or
    dates; there is no member shaped to hold a ticker, so the private report cannot
    carry one through this route.
    """

    SUBJECTS_EVALUATED = "SUBJECTS_EVALUATED"
    SUBJECTS_WITH_PRICE_ROWS = "SUBJECTS_WITH_PRICE_ROWS"
    SUBJECTS_WITH_ACTION_ROWS = "SUBJECTS_WITH_ACTION_ROWS"
    SUBJECTS_WITH_TICKER_ROWS = "SUBJECTS_WITH_TICKER_ROWS"
    SUBJECTS_TRUNCATED = "SUBJECTS_TRUNCATED"
    SUBJECTS_WITH_UPDATE_COLUMN = "SUBJECTS_WITH_UPDATE_COLUMN"
    SUBJECTS_WITH_DELISTED_FLAG = "SUBJECTS_WITH_DELISTED_FLAG"
    SUBJECTS_WITH_PERMATICKER = "SUBJECTS_WITH_PERMATICKER"
    EARLIEST_PRICE_DATE_OBSERVED = "EARLIEST_PRICE_DATE_OBSERVED"
    LATEST_PRICE_DATE_OBSERVED = "LATEST_PRICE_DATE_OBSERVED"
    DISTINCT_ACTION_CODES_OBSERVED = "DISTINCT_ACTION_CODES_OBSERVED"
    SPLIT_ACTIONS_OBSERVED = "SPLIT_ACTIONS_OBSERVED"
    DIVIDEND_ACTIONS_OBSERVED = "DIVIDEND_ACTIONS_OBSERVED"
    SPINOFF_ACTIONS_OBSERVED = "SPINOFF_ACTIONS_OBSERVED"
    ADJUSTED_CLOSE_COLUMN_PRESENT = "ADJUSTED_CLOSE_COLUMN_PRESENT"
    ANNOUNCEMENT_DATE_COLUMN_PRESENT = "ANNOUNCEMENT_DATE_COLUMN_PRESENT"
    DUPLICATE_ROWS_OBSERVED = "DUPLICATE_ROWS_OBSERVED"
    SUBJECTS_COMPARED_ACROSS_RUNS = "SUBJECTS_COMPARED_ACROSS_RUNS"
    SUBJECTS_WITH_STABLE_SCHEMA_ACROSS_RUNS = "SUBJECTS_WITH_STABLE_SCHEMA_ACROSS_RUNS"
    SUBJECTS_WITH_ADVANCED_UPDATE_MARKER = "SUBJECTS_WITH_ADVANCED_UPDATE_MARKER"
    SUBJECTS_WITH_CHANGED_ROW_COUNT = "SUBJECTS_WITH_CHANGED_ROW_COUNT"


@dataclass(frozen=True, slots=True, kw_only=True)
class Measurement:
    """One recorded quantity, grammar-bound to its declared kind."""

    name: MeasurementName
    kind: MeasurementKind
    value: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so a measurement cannot be restated after checking."""
        raise TypeError("Measurement may not be subclassed")

    def __post_init__(self) -> None:
        """Hold the value to the grammar of the kind it declares."""
        if type(self.name) is not MeasurementName or type(self.kind) is not MeasurementKind:
            raise ValueError("a measurement names a closed member for both name and kind")
        if type(self.value) is not str or not self.value:
            raise ValueError("a measurement value is a non-empty exact string")
        if self.kind is MeasurementKind.COUNT and not self.value.isdigit():
            raise ValueError("a COUNT renders as digits")
        if self.kind is MeasurementKind.FLAG and self.value not in ("true", "false"):
            raise ValueError("a FLAG renders as true or false")
        if self.kind is MeasurementKind.DATE and date_field(self.value) is None:
            raise ValueError("a DATE renders as a real calendar date")
        if self.kind is MeasurementKind.DECIMAL and decimal_field(self.value) is None:
            raise ValueError("a DECIMAL renders as a finite decimal")


def _count(name: MeasurementName, value: int) -> Measurement:
    return Measurement(name=name, kind=MeasurementKind.COUNT, value=str(value))


def _flag(name: MeasurementName, value: bool) -> Measurement:
    return Measurement(name=name, kind=MeasurementKind.FLAG, value="true" if value else "false")


@dataclass(frozen=True, slots=True, kw_only=True)
class LimbResult:
    """One limb, its status, why, and what was measured."""

    limb: Limb
    status: LimbStatus
    reason: Reason
    measurements: tuple[Measurement, ...] = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so a limb result cannot be restated."""
        raise TypeError("LimbResult may not be subclassed")


@dataclass(frozen=True, slots=True, kw_only=True)
class TestResult:
    """One provider test, its achieved status, its ceilings and its limbs.

    Both ceilings travel with the result so a reader never has to look one up to
    know whether a status was capped -- and :meth:`__post_init__` refuses a status
    above either, which is what makes a ceiling a control rather than a note.
    """

    test: ProviderTest
    status: TestStatus
    ceiling: TestStatus
    single_execution_ceiling: TestStatus
    limbs: tuple[LimbResult, ...]
    #: How much evidence produced this status. Defaulted to the narrower scope
    #: deliberately: a result assembled by a caller who did not think about scope is
    #: held to the single-execution ceiling, which is the direction that fails
    #: closed.
    evidence_scope: EvidenceScope = EvidenceScope.SINGLE_EXECUTION

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so a status cannot be raised after it was checked."""
        raise TypeError("TestResult may not be subclassed")

    @property
    def effective_ceiling(self) -> TestStatus:
        """The ceiling this result's own scope is actually held to."""
        if self.evidence_scope is EvidenceScope.COMBINED:
            return self.ceiling
        return self.single_execution_ceiling

    def __post_init__(self) -> None:
        """Refuse a status above the ceiling its scope permits, or foreign ceilings.

        Both ceilings travel on every result, whatever the scope, so a reader never
        has to look one up to see whether a status was capped -- and so a combined
        result still shows what a single execution could have reached. The scope
        decides only **which** of the two is enforced, and the architecture ceiling
        is enforced in every scope.
        """
        if type(self.evidence_scope) is not EvidenceScope:
            raise ValueError("a test result must declare an exact EvidenceScope member")
        if self.ceiling is not TEST_CEILINGS[self.test]:
            raise ValueError("a test result must carry its own compiled ceiling")
        if self.single_execution_ceiling is not SINGLE_EXECUTION_CEILINGS[self.test]:
            raise ValueError("a test result must carry its own single-execution ceiling")
        if STATUS_RANK[self.status] > STATUS_RANK[self.ceiling]:
            raise ValueError("a test may not report a status above its ceiling")
        if STATUS_RANK[self.status] > STATUS_RANK[self.effective_ceiling]:
            raise ValueError("one execution may not report above its single-execution ceiling")


@dataclass(frozen=True, slots=True, kw_only=True)
class SubjectEvidence:
    """The three page pairs retained for one subject. **Private material.**

    Keyed by dataset rather than by name, and the subject itself is deliberately
    **not** a field: the evaluator aggregates across subjects and emits counts, so
    no security name can travel from here into a result or a report.
    """

    pairs: dict[SharadarDataset, PagePair]

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass could carry a name."""
        raise TypeError("SubjectEvidence may not be subclassed")

    def __repr__(self) -> str:
        """A count. **Never a row and never a subject.**"""
        return f"SubjectEvidence(datasets={len(self.pairs)})"

    def pair(self, dataset: SharadarDataset) -> PagePair | None:
        """The page pair for one dataset, or ``None`` if it was not retained."""
        return self.pairs.get(dataset)


@dataclass(frozen=True, slots=True, kw_only=True)
class CrossRunSubjectEvidence:
    """One subject's evidence from **both** executions. **Private material.**

    The two sides are matched by the assessor, which knows the subjects privately;
    like :class:`SubjectEvidence` this carries no name, so nothing here can travel
    into a result or a report. ``first`` is Run A and ``second`` is Run B, and the
    order is the assessor's responsibility -- it is the one that validated the
    locator pair's chronology before any payload was read.
    """

    first: SubjectEvidence
    second: SubjectEvidence

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass could carry a name."""
        raise TypeError("CrossRunSubjectEvidence may not be subclassed")

    def __repr__(self) -> str:
        """A constant. **Never a row and never a subject.**"""
        return "CrossRunSubjectEvidence(runs=2)"


#: Column names the evaluator looks for. **Observed, never required**: their absence
#: is evidence about the delivery, recorded as an insufficiency rather than raised.
_UPDATE_COLUMN: Final = "lastupdated"
_PERMATICKER_COLUMN: Final = "permaticker"
_DELISTED_COLUMN: Final = "isdelisted"
_ADJUSTED_CLOSE_COLUMN: Final = "closeadj"
_ANNOUNCEMENT_COLUMN: Final = "announcedate"
_ACTION_COLUMN: Final = "action"
_DATE_COLUMN: Final = "date"

#: Action-code fragments the evaluator counts. **Matched case-insensitively as
#: substrings, and never treated as a closed vocabulary**: the vendor does not
#: publish its action-code set, which the source register records explicitly. A
#: compiled list here would be this package inventing one.
_SPLIT_FRAGMENT: Final = "split"
_DIVIDEND_FRAGMENT: Final = "dividend"
_SPINOFF_FRAGMENT: Final = "spinoff"


def _usable_pairs(
    evidence: tuple[SubjectEvidence, ...], dataset: SharadarDataset
) -> tuple[PagePair, ...]:
    """Every retained pair for one dataset whose delivery is intact."""
    pairs = [subject.pair(dataset) for subject in evidence]
    return tuple(pair for pair in pairs if pair is not None)


def _action_code_counts(pairs: tuple[PagePair, ...]) -> tuple[int, int, int, int]:
    """Split, dividend, spinoff and distinct-code counts across delivered actions."""
    splits = dividends = spinoffs = 0
    distinct: set[str] = set()
    for pair in pairs:
        for value in pair.first.column(_ACTION_COLUMN):
            if value is None:
                continue
            distinct.add(value)
            lowered = value.lower()
            if _SPLIT_FRAGMENT in lowered:
                splits += 1
            if _DIVIDEND_FRAGMENT in lowered:
                dividends += 1
            if _SPINOFF_FRAGMENT in lowered:
                spinoffs += 1
    return splits, dividends, spinoffs, len(distinct)


def _price_date_bounds(pairs: tuple[PagePair, ...]) -> tuple[str | None, str | None]:
    """The earliest and latest delivered price dates, as ISO strings.

    Parsed as real calendar dates and **never coerced into instants**. A value that
    does not parse contributes nothing rather than being repaired.
    """
    dates = []
    for pair in pairs:
        for value in pair.first.column(_DATE_COLUMN):
            parsed = date_field(value)
            if parsed is not None:
                dates.append(parsed)
    if not dates:
        return None, None
    return min(dates).isoformat(), max(dates).isoformat()


def _evaluate_p1(evidence: tuple[SubjectEvidence, ...]) -> TestResult:
    """P1 -- availability semantics and origin. Capped at one observation."""
    pairs = _usable_pairs(evidence, SharadarDataset.STOCKS)
    with_update = sum(1 for pair in pairs if pair.first.has_column(_UPDATE_COLUMN))

    limbs = (
        LimbResult(
            limb=Limb.P1_INFORMATION_TIME_RESOLUTION,
            status=LimbStatus.BOUNDED,
            reason=Reason.DATE_GRANULAR_SOURCE,
        ),
        LimbResult(
            limb=Limb.P1_UPDATE_COLUMN_PRESENT,
            status=LimbStatus.OBSERVED if pairs else LimbStatus.INSUFFICIENT,
            reason=Reason.MEASURED if pairs else Reason.EVIDENCE_MISSING,
            measurements=(_count(MeasurementName.SUBJECTS_WITH_UPDATE_COLUMN, with_update),),
        ),
        LimbResult(
            limb=Limb.P1_CROSS_RUN_CHANGE_DETECTION,
            status=LimbStatus.INSUFFICIENT,
            reason=Reason.CROSS_RUN_EVIDENCE_ABSENT,
        ),
    )
    status = TestStatus.PARTIALLY_TESTED if pairs else TestStatus.INSUFFICIENT_EVIDENCE
    return TestResult(
        test=ProviderTest.P1,
        status=status,
        ceiling=TEST_CEILINGS[ProviderTest.P1],
        single_execution_ceiling=SINGLE_EXECUTION_CEILINGS[ProviderTest.P1],
        limbs=limbs,
        evidence_scope=EvidenceScope.SINGLE_EXECUTION,
    )


def _latest_update_marker(pair: PagePair) -> str | None:
    """The largest delivered value of the vendor's update column, or ``None``.

    Compared as delivered strings rather than parsed into instants. The column is
    date-granular and the vendor does not document its exact rendering, so parsing
    it into a timestamp would manufacture a precision the source does not have --
    and the only question asked of it here is whether it *changed*, which string
    comparison answers without inventing anything.
    """
    values = [value for value in pair.first.column(_UPDATE_COLUMN) if value]
    if not values:
        return None
    return max(values)


def _evaluate_p1_combined(pairs: tuple[CrossRunSubjectEvidence, ...]) -> TestResult:
    """P1 across both executions. **The only place P1 may reach ``TESTED``.**

    A subject is *comparable* when both runs delivered a usable price page for it
    **and** both carried the update column. Anything less is not weaker evidence for
    change detection -- it is no evidence, and it is recorded as insufficiency.

    Schema stability across the two runs is checked before any count is compared. A
    delivery whose header changed between runs cannot support a row-count or marker
    comparison, because the two pages are not the same shape; that is
    ``INCONCLUSIVE``, and it holds P1 below ``TESTED``.
    """
    comparable: list[tuple[PagePair, PagePair]] = []
    for subject in pairs:
        before = subject.first.pair(SharadarDataset.STOCKS)
        after = subject.second.pair(SharadarDataset.STOCKS)
        if before is None or after is None:
            continue
        if not before.first.has_column(_UPDATE_COLUMN) or not after.first.has_column(
            _UPDATE_COLUMN
        ):
            continue
        comparable.append((before, after))

    stable = [
        (before, after)
        for before, after in comparable
        if before.first.schema_digest == after.first.schema_digest
    ]
    advanced = sum(
        1
        for before, after in stable
        if _latest_update_marker(before) != _latest_update_marker(after)
    )
    changed_rows = sum(
        1 for before, after in stable if before.first.row_count != after.first.row_count
    )

    with_update = sum(
        1
        for subject in pairs
        for pair in (subject.second.pair(SharadarDataset.STOCKS),)
        if pair is not None and pair.first.has_column(_UPDATE_COLUMN)
    )

    if not comparable:
        change = LimbResult(
            limb=Limb.P1_CROSS_RUN_CHANGE_DETECTION,
            status=LimbStatus.INSUFFICIENT,
            reason=Reason.CROSS_RUN_MARKER_NOT_DELIVERED
            if pairs
            else Reason.CROSS_RUN_EVIDENCE_ABSENT,
            measurements=(_count(MeasurementName.SUBJECTS_COMPARED_ACROSS_RUNS, 0),),
        )
    elif not stable:
        change = LimbResult(
            limb=Limb.P1_CROSS_RUN_CHANGE_DETECTION,
            status=LimbStatus.INCONCLUSIVE,
            reason=Reason.CROSS_RUN_SCHEMA_DRIFTED,
            measurements=(
                _count(MeasurementName.SUBJECTS_COMPARED_ACROSS_RUNS, len(comparable)),
                _count(MeasurementName.SUBJECTS_WITH_STABLE_SCHEMA_ACROSS_RUNS, 0),
            ),
        )
    else:
        change = LimbResult(
            limb=Limb.P1_CROSS_RUN_CHANGE_DETECTION,
            status=LimbStatus.OBSERVED,
            reason=Reason.CROSS_RUN_EVIDENCE_COMPARED,
            measurements=(
                _count(MeasurementName.SUBJECTS_COMPARED_ACROSS_RUNS, len(comparable)),
                _count(MeasurementName.SUBJECTS_WITH_STABLE_SCHEMA_ACROSS_RUNS, len(stable)),
                _count(MeasurementName.SUBJECTS_WITH_ADVANCED_UPDATE_MARKER, advanced),
                _count(MeasurementName.SUBJECTS_WITH_CHANGED_ROW_COUNT, changed_rows),
            ),
        )

    limbs = (
        LimbResult(
            # **Bounded regardless of outcome, and in both scopes.** The vendor's
            # update column is date-granular, and a date cannot supply an instant.
            # No number of runs lifts this, so a combined assessment that reported
            # it as measured would be claiming a precision the source lacks.
            limb=Limb.P1_INFORMATION_TIME_RESOLUTION,
            status=LimbStatus.BOUNDED,
            reason=Reason.DATE_GRANULAR_SOURCE,
        ),
        LimbResult(
            limb=Limb.P1_UPDATE_COLUMN_PRESENT,
            status=LimbStatus.OBSERVED if pairs else LimbStatus.INSUFFICIENT,
            reason=Reason.MEASURED if pairs else Reason.EVIDENCE_MISSING,
            measurements=(_count(MeasurementName.SUBJECTS_WITH_UPDATE_COLUMN, with_update),),
        ),
        change,
    )

    if not pairs:
        status = TestStatus.INSUFFICIENT_EVIDENCE
    elif change.status is LimbStatus.OBSERVED:
        # **The ceiling, and only when the evidence reaches it.** Every limb this
        # architecture can measure was measured; the information-time limb stays
        # bounded, and that bound is recorded on the result rather than deducted
        # from the status.
        status = TestStatus.TESTED
    else:
        status = TestStatus.PARTIALLY_TESTED

    return TestResult(
        test=ProviderTest.P1,
        status=status,
        ceiling=TEST_CEILINGS[ProviderTest.P1],
        single_execution_ceiling=SINGLE_EXECUTION_CEILINGS[ProviderTest.P1],
        limbs=limbs,
        evidence_scope=EvidenceScope.COMBINED,
    )


def _evaluate_p2(evidence: tuple[SubjectEvidence, ...]) -> TestResult:
    """P2 -- delisted coverage. **Sampled existence, never a population claim.**"""
    price_pairs = _usable_pairs(evidence, SharadarDataset.STOCKS)
    ticker_pairs = _usable_pairs(evidence, SharadarDataset.TICKERS)
    with_rows = sum(1 for pair in price_pairs if pair.first.row_count > 0)
    with_flag = sum(1 for pair in ticker_pairs if pair.first.has_column(_DELISTED_COLUMN))
    with_permaticker = sum(1 for pair in ticker_pairs if pair.first.has_column(_PERMATICKER_COLUMN))
    earliest, latest = _price_date_bounds(price_pairs)

    history = [
        _count(MeasurementName.SUBJECTS_WITH_PRICE_ROWS, with_rows),
        _count(MeasurementName.SUBJECTS_EVALUATED, len(evidence)),
    ]
    if earliest is not None:
        history.append(
            Measurement(
                name=MeasurementName.EARLIEST_PRICE_DATE_OBSERVED,
                kind=MeasurementKind.DATE,
                value=earliest,
            )
        )
    if latest is not None:
        history.append(
            Measurement(
                name=MeasurementName.LATEST_PRICE_DATE_OBSERVED,
                kind=MeasurementKind.DATE,
                value=latest,
            )
        )

    limbs = (
        LimbResult(
            limb=Limb.P2_DELISTED_HISTORY_EXISTS,
            status=LimbStatus.OBSERVED if with_rows else LimbStatus.INSUFFICIENT,
            reason=Reason.MEASURED if with_rows else Reason.NO_ROWS_DELIVERED,
            measurements=tuple(history),
        ),
        LimbResult(
            # Permanently bounded. One name per cohort establishes that history
            # exists for those names and bounds nothing about the population, so no
            # quantity of sampled rows can lift this.
            limb=Limb.P2_POPULATION_SURVIVORSHIP,
            status=LimbStatus.BOUNDED,
            reason=Reason.SAMPLED_NOT_POPULATION,
        ),
        LimbResult(
            limb=Limb.P2_IDENTIFIER_TRANSITION,
            status=LimbStatus.OBSERVED if with_permaticker else LimbStatus.INSUFFICIENT,
            reason=Reason.MEASURED if with_permaticker else Reason.COLUMN_NOT_DELIVERED,
            measurements=(
                _count(MeasurementName.SUBJECTS_WITH_PERMATICKER, with_permaticker),
                _count(MeasurementName.SUBJECTS_WITH_DELISTED_FLAG, with_flag),
            ),
        ),
    )
    status = TestStatus.PARTIALLY_TESTED if with_rows else TestStatus.INSUFFICIENT_EVIDENCE
    return TestResult(
        test=ProviderTest.P2,
        status=status,
        ceiling=TEST_CEILINGS[ProviderTest.P2],
        single_execution_ceiling=SINGLE_EXECUTION_CEILINGS[ProviderTest.P2],
        limbs=limbs,
    )


def _evaluate_p3(evidence: tuple[SubjectEvidence, ...]) -> TestResult:
    """P3 -- corporate-action announcement timing. Schema decidable, timing not."""
    pairs = _usable_pairs(evidence, SharadarDataset.ACTIONS)
    delivered = bool(pairs)
    announced = sum(1 for pair in pairs if pair.first.has_column(_ANNOUNCEMENT_COLUMN))
    splits, dividends, spinoffs, distinct = _action_code_counts(pairs)

    limbs = (
        LimbResult(
            limb=Limb.P3_ACTION_SCHEMA_DELIVERED,
            status=LimbStatus.OBSERVED if delivered else LimbStatus.INSUFFICIENT,
            reason=Reason.MEASURED if delivered else Reason.EVIDENCE_MISSING,
            measurements=(
                _count(MeasurementName.DISTINCT_ACTION_CODES_OBSERVED, distinct),
                _flag(MeasurementName.ANNOUNCEMENT_DATE_COLUMN_PRESENT, announced > 0),
            ),
        ),
        LimbResult(
            # Whatever the header says, timing stays approximated where the field
            # is absent -- and a delivered header cannot supply a date it does not
            # carry.
            limb=Limb.P3_ANNOUNCEMENT_TIMING,
            status=LimbStatus.OBSERVED if announced else LimbStatus.BOUNDED,
            reason=Reason.MEASURED if announced else Reason.COLUMN_NOT_DELIVERED,
            measurements=(
                _count(MeasurementName.SPLIT_ACTIONS_OBSERVED, splits),
                _count(MeasurementName.DIVIDEND_ACTIONS_OBSERVED, dividends),
                _count(MeasurementName.SPINOFF_ACTIONS_OBSERVED, spinoffs),
            ),
        ),
    )
    if not delivered:
        status = TestStatus.INSUFFICIENT_EVIDENCE
    elif announced:
        status = TestStatus.TESTED
    else:
        status = TestStatus.PARTIALLY_TESTED
    return TestResult(
        test=ProviderTest.P3,
        status=status,
        ceiling=TEST_CEILINGS[ProviderTest.P3],
        single_execution_ceiling=SINGLE_EXECUTION_CEILINGS[ProviderTest.P3],
        limbs=limbs,
    )


def _evaluate_p4(evidence: tuple[SubjectEvidence, ...]) -> TestResult:
    """P4 -- classification history. A snapshot table has no time axis to sample."""
    pairs = _usable_pairs(evidence, SharadarDataset.TICKERS)
    with_rows = sum(1 for pair in pairs if pair.first.row_count > 0)
    return TestResult(
        test=ProviderTest.P4,
        status=TestStatus.DOCUMENTATION_RESOLVED,
        ceiling=TEST_CEILINGS[ProviderTest.P4],
        single_execution_ceiling=SINGLE_EXECUTION_CEILINGS[ProviderTest.P4],
        limbs=(
            LimbResult(
                limb=Limb.P4_CLASSIFICATION_HISTORY,
                status=LimbStatus.BOUNDED,
                reason=Reason.SNAPSHOT_HAS_NO_TIME_AXIS,
                measurements=(_count(MeasurementName.SUBJECTS_WITH_TICKER_ROWS, with_rows),),
            ),
        ),
    )


def _evaluate_p5(evidence: tuple[SubjectEvidence, ...]) -> TestResult:
    """P5 -- adjusted/raw reconciliation. Spinoff limb stays inconclusive."""
    price_pairs = _usable_pairs(evidence, SharadarDataset.STOCKS)
    action_pairs = _usable_pairs(evidence, SharadarDataset.ACTIONS)
    adjusted = sum(1 for pair in price_pairs if pair.first.has_column(_ADJUSTED_CLOSE_COLUMN))
    splits, dividends, spinoffs, _ = _action_code_counts(action_pairs)
    reconcilable = adjusted > 0 and bool(price_pairs)

    def limb(name: Limb, observed: int) -> LimbResult:
        if not reconcilable:
            return LimbResult(
                limb=name,
                status=LimbStatus.INSUFFICIENT,
                reason=Reason.COLUMN_NOT_DELIVERED if price_pairs else Reason.EVIDENCE_MISSING,
            )
        if not observed:
            return LimbResult(
                limb=name, status=LimbStatus.INSUFFICIENT, reason=Reason.NO_ROWS_DELIVERED
            )
        return LimbResult(limb=name, status=LimbStatus.OBSERVED, reason=Reason.MEASURED)

    limbs = (
        limb(Limb.P5_SPLIT_RECONCILIATION, splits),
        limb(Limb.P5_DIVIDEND_RECONCILIATION, dividends),
        LimbResult(
            # Inconclusive while the provider's spinoff semantics stay undocumented.
            # A ratio this package cannot interpret is not a ratio it may check, and
            # an arithmetic that appeared to agree would be a coincidence reported
            # as a finding.
            limb=Limb.P5_SPINOFF_RECONCILIATION,
            status=LimbStatus.INCONCLUSIVE,
            reason=Reason.PROVIDER_SEMANTICS_UNDOCUMENTED,
            measurements=(_count(MeasurementName.SPINOFF_ACTIONS_OBSERVED, spinoffs),),
        ),
    )
    status = TestStatus.PARTIALLY_TESTED if reconcilable else TestStatus.INSUFFICIENT_EVIDENCE
    return TestResult(
        test=ProviderTest.P5,
        status=status,
        ceiling=TEST_CEILINGS[ProviderTest.P5],
        single_execution_ceiling=SINGLE_EXECUTION_CEILINGS[ProviderTest.P5],
        limbs=limbs,
    )


def _deferred(test: ProviderTest, limb: Limb, reason: Reason) -> TestResult:
    """One deferred test. Not attempted, and saying so is the whole result."""
    return TestResult(
        test=test,
        status=TestStatus.DEFERRED,
        ceiling=TEST_CEILINGS[test],
        single_execution_ceiling=SINGLE_EXECUTION_CEILINGS[test],
        limbs=(LimbResult(limb=limb, status=LimbStatus.DEFERRED, reason=reason),),
    )


def _evaluate_p9() -> TestResult:
    """P9 -- bar construction and origin. A question about a process, not data."""
    return TestResult(
        test=ProviderTest.P9,
        status=TestStatus.DOCUMENTATION_RESOLVED,
        ceiling=TEST_CEILINGS[ProviderTest.P9],
        single_execution_ceiling=SINGLE_EXECUTION_CEILINGS[ProviderTest.P9],
        limbs=(
            LimbResult(
                limb=Limb.P9_BAR_CONSTRUCTION_ORIGIN,
                status=LimbStatus.BOUNDED,
                reason=Reason.PRICE_ORIGIN_PROVIDER_DERIVED,
            ),
        ),
    )


def evaluate(evidence: tuple[SubjectEvidence, ...]) -> tuple[TestResult, ...]:
    """Every P-test result for one execution's evidence, in test order.

    **Truncated or schema-unstable deliveries are excluded before measurement**, so
    a row-count conclusion is never drawn from a page that may have been cut off.
    That exclusion is itself recorded, as a count, rather than quietly reducing the
    sample.

    Returns:
        Nine :class:`TestResult` values. **No aggregate, no verdict, no
        recommendation and no selection** -- there is no tenth element and no
        summary field, because the absence is the control.
    """
    if type(evidence) is not tuple:
        raise TypeError("evidence must be an exact tuple of SubjectEvidence")
    for subject in evidence:
        if type(subject) is not SubjectEvidence:
            raise TypeError("evidence must be an exact tuple of SubjectEvidence")

    usable = tuple(
        SubjectEvidence(
            pairs={
                dataset: pair for dataset, pair in subject.pairs.items() if pair.row_count_usable
            }
        )
        for subject in evidence
    )
    return (
        _evaluate_p1(usable),
        _evaluate_p2(usable),
        _evaluate_p3(usable),
        _evaluate_p4(usable),
        _evaluate_p5(usable),
        _deferred(ProviderTest.P6, Limb.P6_KNOWN_RESTATEMENT, Reason.REQUIRES_LATER_PHASE_DATASET),
        _deferred(ProviderTest.P7, Limb.P7_FILING_LINKAGE, Reason.REQUIRES_EXTERNAL_SOURCE),
        _deferred(ProviderTest.P8, Limb.P8_EARNINGS_TIMING, Reason.REQUIRES_EXTERNAL_SOURCE),
        _evaluate_p9(),
    )


def _usable_only(evidence: tuple[SubjectEvidence, ...]) -> tuple[SubjectEvidence, ...]:
    """Drop truncated and schema-unstable deliveries before anything is measured."""
    return tuple(
        SubjectEvidence(
            pairs={
                dataset: pair for dataset, pair in subject.pairs.items() if pair.row_count_usable
            }
        )
        for subject in evidence
    )


def _combined(result: TestResult) -> TestResult:
    """Restate one result as combined-scope, re-running its own ceiling guard.

    ``dataclasses.replace`` calls ``__post_init__`` again, so widening the scope is
    itself checked: a status that was legal under the single-execution ceiling is
    re-checked against the architecture ceiling, and the architecture ceiling is
    never widened by this.
    """
    return replace(result, evidence_scope=EvidenceScope.COMBINED)


def evaluate_combined(pairs: tuple[CrossRunSubjectEvidence, ...]) -> tuple[TestResult, ...]:
    """Every P-test result across **both** executions, in test order.

    **P1 is the only test that uses both runs, because it is the only cross-run
    question.** It asks whether the provider's view of a period changed between two
    observations at least eight calendar days apart, and that needs two observations.

    **P2 through P9 are evaluated from Run B**, the later observation. They ask what
    the provider holds -- delisted history, action schema, classification history,
    corporate-action reconciliation, price origin -- and for those a stale earlier
    observation adds nothing that the later one does not already carry. Averaging or
    unioning the two would double every subject count and describe an experiment
    nobody ran.

    Returns:
        Nine :class:`TestResult` values, every one scoped ``COMBINED``. **No
        aggregate, no verdict, no recommendation and no selection** -- there is no
        tenth element and no summary field, because the absence is the control.
    """
    if type(pairs) is not tuple:
        raise TypeError("cross-run evidence must be an exact tuple of CrossRunSubjectEvidence")
    for subject in pairs:
        if type(subject) is not CrossRunSubjectEvidence:
            raise TypeError("cross-run evidence must be an exact tuple of CrossRunSubjectEvidence")

    usable = tuple(
        CrossRunSubjectEvidence(
            first=_usable_only((subject.first,))[0],
            second=_usable_only((subject.second,))[0],
        )
        for subject in pairs
    )
    later = tuple(subject.second for subject in usable)

    return (
        _evaluate_p1_combined(usable),
        _combined(_evaluate_p2(later)),
        _combined(_evaluate_p3(later)),
        _combined(_evaluate_p4(later)),
        _combined(_evaluate_p5(later)),
        _combined(
            _deferred(
                ProviderTest.P6, Limb.P6_KNOWN_RESTATEMENT, Reason.REQUIRES_LATER_PHASE_DATASET
            )
        ),
        _combined(
            _deferred(ProviderTest.P7, Limb.P7_FILING_LINKAGE, Reason.REQUIRES_EXTERNAL_SOURCE)
        ),
        _combined(
            _deferred(ProviderTest.P8, Limb.P8_EARNINGS_TIMING, Reason.REQUIRES_EXTERNAL_SOURCE)
        ),
        _combined(_evaluate_p9()),
    )


def excluded_subject_count(evidence: tuple[SubjectEvidence, ...]) -> int:
    """How many retained page pairs were excluded as truncated or schema-unstable."""
    return sum(
        1 for subject in evidence for pair in subject.pairs.values() if not pair.row_count_usable
    )


def excluded_cross_run_pair_count(pairs: tuple[CrossRunSubjectEvidence, ...]) -> int:
    """The same exclusion count across both executions of a combined assessment.

    Counted over both sides rather than one, and recorded in the private report:
    an exclusion is evidence about the delivery, and quietly shrinking the sample
    instead of recording why is how a row-count conclusion becomes untraceable.
    """
    return sum(
        excluded_subject_count((subject.first,)) + excluded_subject_count((subject.second,))
        for subject in pairs
    )


__all__ = [
    "SINGLE_EXECUTION_CEILINGS",
    "STATUS_RANK",
    "TEST_CEILINGS",
    "CrossRunSubjectEvidence",
    "EvidenceScope",
    "Limb",
    "LimbResult",
    "LimbStatus",
    "Measurement",
    "MeasurementKind",
    "MeasurementName",
    "ProviderTest",
    "Reason",
    "SubjectEvidence",
    "TestResult",
    "TestStatus",
    "evaluate",
    "evaluate_combined",
    "excluded_cross_run_pair_count",
    "excluded_subject_count",
]
