"""The bounded empirical qualification plan: 48 requests, and no way to ask for more.

**Every number here is the accepted architecture, compiled in.** Nothing on this
path is operator-selectable: an operator who could choose the dataset, the window,
the page count or the retry policy could choose a retrieval nobody reviewed. The
subjects arrive from the owner-only private inventory and the execution identity
is the operator's; everything else is a constant in this module.

**Zero provider retries are arithmetically forced, not merely configured.** The
plan model refuses unless ``requests * (attempts - 1) <= retry_budget``. The
compiled budget is 32 and this plan issues 48 requests, so a single retry would
need ``48 <= 32``. Any ``max_attempts`` above one is refused by the accepted plan
model itself, before this module's own check is even reached -- which is the
stronger guarantee, because it does not depend on this module staying correct.

**The 1,800 seconds are a real elapsed-time deadline, not compile-time
arithmetic.** An earlier revision of this module computed a worst case -- 48
requests at a 30-second timeout plus 47 one-second gaps is 1,487 seconds -- and
called the comparison against 1,800 an enforcement. It was not one. It bounded the
provider requests and the pacing and nothing else: the 144 Bronze writes and the
locator were all outside it, and no running program was ever held to it. The
clarified architecture states one actual
deadline measured on an **injected monotonic clock** over the complete acquisition
execution phase, and this module supplies the constants that deadline is made of.

**What is compiled here is the budget arithmetic; the stopwatch lives in**
:class:`~kalpamani.data.qualify.sharadar.operations.AcquisitionDeadline`. Every
constant below is checked against the others at import by
:func:`validate_deadline_constants`, and a configuration that cannot fit is
**refused rather than clamped** -- a clamped budget is a budget that says one thing
and does another.

**And the uncomfortable consequence is recorded rather than smoothed over.** At the
compiled worst case the 48 requests and their pacing occupy 1,487 seconds, leaving
313 for 144 Bronze writes and at most three locator writes -- 147 operations, about
two seconds each, which is roughly double the allowance ADR-0018's design left
because ADR-0019 removed roughly half the operations. **It is still not a guarantee
that 48 requests complete**, and the deadline is still a safety bound on elapsed
time. A slow provider means the run halts short, publishes a ``PARTIAL`` locator,
and the assessor refuses to evaluate it.

**Page two is a completeness probe, and it is not an invitation to paginate.**
Sorting is a forbidden request parameter and the vendor's row limit truncates
silently, so an empty second page is the only available proof the first was
complete. Three pages are not reachable: ``max_pages`` is a compiled 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Final

from kalpamani.data.ingest.sharadar.datasets import (
    DateWindow,
    ResponseFormat,
    SharadarDataset,
)
from kalpamani.data.ingest.sharadar.qualification import (
    DatasetPlan,
    QualificationLimits,
    QualificationPlan,
)
from kalpamani.data.qualify.sharadar.inventory import (
    REQUIRED_SUBJECT_COUNT,
    PrivateInventory,
)

#: The three Stage-3A datasets, in the plan model's own canonical order. A fourth
#: is not expressible: the accepted dataset vocabulary refuses the Phase-3B tables
#: by name, and this tuple names no candidate for one.
EMPIRICAL_DATASETS: Final[tuple[SharadarDataset, ...]] = (
    SharadarDataset.TICKERS,
    SharadarDataset.STOCKS,
    SharadarDataset.ACTIONS,
)

#: Two pages per subject and dataset: the first, and the completeness probe.
EMPIRICAL_MAX_PAGES: Final = 2

#: 8 subjects x 3 datasets x 2 pages. Derived from its factors rather than written
#: as ``48``, so a change to any factor cannot leave the total stale.
EMPIRICAL_REQUEST_COUNT: Final = (
    REQUIRED_SUBJECT_COUNT * len(EMPIRICAL_DATASETS) * EMPIRICAL_MAX_PAGES
)

#: Per-dataset page limits. ``tickers`` is a snapshot of identifiers and needs a
#: small page; the two windowed tables use the vendor's documented maximum, which
#: is also the truncation boundary the probe exists to detect.
TICKERS_PAGE_LIMIT: Final = 100
STOCKS_PAGE_LIMIT: Final = 10_000
ACTIONS_PAGE_LIMIT: Final = 10_000

PAGE_LIMITS: Final[dict[SharadarDataset, int]] = {
    SharadarDataset.TICKERS: TICKERS_PAGE_LIMIT,
    SharadarDataset.STOCKS: STOCKS_PAGE_LIMIT,
    SharadarDataset.ACTIONS: ACTIONS_PAGE_LIMIT,
}

#: The documented depth of the two windowed tables. **A planning boundary, not a
#: certified earliest record** -- the Q8 disposition is unchanged by this package,
#: and what the provider actually holds is one of the things a run measures.
HISTORY_START: Final = date(1998, 1, 1)

#: 4 MiB per response, 64 MiB per run. Both at or below the compiled ceilings the
#: plan model enforces, and the response value **must also be given to the
#: transport**, because the transport is what stops reading.
MAX_RESPONSE_BYTES: Final = 4 * 1024 * 1024
MAX_RUN_BYTES: Final = 64 * 1024 * 1024

#: One attempt. Zero retries, which the retry-budget arithmetic already forces.
PROVIDER_MAX_ATTEMPTS: Final = 1

#: 30 seconds per request, at least one second between requests. The vendor
#: publishes no rate limit, and no documented limit is not an absent limit.
TIMEOUT_SECONDS: Final = 30.0
MIN_REQUEST_INTERVAL_SECONDS: Final = 1.0

#: ``D`` -- the one acquisition elapsed-time deadline, in seconds. Measured on an
#: injected monotonic clock over the complete acquisition execution phase, from
#: immediately before the first provider request to the terminal locator result.
#: **Lowering it is a configuration choice; raising it is an ADR change.**
ACQUISITION_DEADLINE_SECONDS: Final = 1_800.0

#: The two socket timeouts configured on **every** qualification S3 client -- the
#: acquisition one and the assessment one -- and the retry settings that stop the SDK
#: from multiplying them. **Retries are disabled**, so one invocation is one attempt
#: and the application-level locator retry is the only retry anywhere on either path.
#:
#: **``total_max_attempts``, and deliberately not ``max_attempts``.** Botocore
#: distinguishes the two: ``max_attempts`` counts the retries that follow the first
#: request, so ``max_attempts = 1`` permits a *second* attempt, while
#: ``total_max_attempts`` counts every attempt including the first, so one means one
#: request and no retry. Botocore documents ``total_max_attempts`` as the preferred
#: setting, and it is the only one of the two that expresses what this path needs.
S3_CONNECT_TIMEOUT_SECONDS: Final = 5.0
S3_READ_TIMEOUT_SECONDS: Final = 10.0
S3_TOTAL_MAX_ATTEMPTS: Final = 1
S3_RETRY_MODE: Final = "standard"

#: ``T_s3`` -- the worst case one qualification S3 invocation may occupy.
#:
#: **Deliberately not either socket timeout on its own.** A single attempt can
#: consume its connect timeout and then its read timeout in sequence, so a bound
#: taken from one of them is not a bound on the operation. This is their sum plus a
#: 5-second margin for name resolution, TLS and local SDK work -- and
#: :func:`validate_deadline_constants` refuses a value below that sum, so the
#: relationship is checked rather than remembered. It is sound only because SDK
#: retries are disabled: with retries on, one invocation is several attempts.
S3_OPERATION_CEILING_SECONDS: Final = 20.0

#: ``C`` -- deterministic locator construction, serialization and terminal
#: classification. No network, so this is local work with a generous margin.
LOCATOR_CONSTRUCTION_ALLOWANCE_SECONDS: Final = 5.0

#: ``L`` -- the budget held back so the locator can always be written.
#:
#: It must cover ``3 * T_s3 + C`` (ADR-0019 §7): three permitted locator
#: ``PutObject`` attempts, **zero** locator ``HeadObject`` -- the acquisition path
#: has no metadata read at all, so a ``412`` fails closed instead of resolving --
#: and the deterministic construction above. 90 is 65 with a conservative margin;
#: the value is unchanged by the amendment because a larger reserve than the rule
#: requires is safe in the direction that keeps the locator reachable.
LOCATOR_TERMINAL_RESERVE_SECONDS: Final = 90.0

#: Three Bronze ``PutObject`` per completed request, and **no conditional
#: ``HeadObject`` after a ``412``**: ADR-0019 removed the acquisition role's
#: object-read authority, so a collision fails closed rather than being resolved.
#: This is the ``3 * T_s3`` per-request S3 obligation, down from the ``6 * T_s3``
#: ADR-0018 was accepted with.
BRONZE_OPERATIONS_PER_REQUEST: Final = 3

#: Three locator ``PutObject`` attempts and **zero** locator ``HeadObject``.
LOCATOR_OPERATIONS_ALLOWED: Final = 3

#: What must still remain before a provider request may **start**: its own ceiling,
#: the complete downstream Bronze obligation it creates, and the locator reserve.
#: **Pacing is not in this sum**, and that is the correction rather than an
#: oversight: pacing for this request has already been checked and already elapsed
#: by the time admission is asked, so including it here would spend it twice.
PROVIDER_REQUEST_ADMISSION_SECONDS: Final = (
    TIMEOUT_SECONDS
    + BRONZE_OPERATIONS_PER_REQUEST * S3_OPERATION_CEILING_SECONDS
    + LOCATOR_TERMINAL_RESERVE_SECONDS
)

#: What must remain before one Bronze operation may start: its own ceiling, plus the
#: locator reserve, so Bronze can never spend the budget the locator is holding.
BRONZE_OPERATION_ADMISSION_SECONDS: Final = (
    S3_OPERATION_CEILING_SECONDS + LOCATOR_TERMINAL_RESERVE_SECONDS
)

#: What must remain before one locator S3 operation may start. It is inside the
#: reserve already, so it holds nothing further back.
LOCATOR_OPERATION_ADMISSION_SECONDS: Final = S3_OPERATION_CEILING_SECONDS

#: What must remain before the locator is even **constructed**: the deterministic
#: construction plus one write. Below this there is no safe attempt at all, and the
#: run reports ``LOCATOR_NOT_PUBLISHED`` rather than starting one it cannot finish.
LOCATOR_ATTEMPT_ADMISSION_SECONDS: Final = (
    LOCATOR_CONSTRUCTION_ALLOWANCE_SECONDS + S3_OPERATION_CEILING_SECONDS
)

#: Responses are CSV. Stated rather than defaulted, because the parser's contract
#: is written against this exact encoding.
EMPIRICAL_RESPONSE_FORMAT: Final = ResponseFormat.CSV

#: The schema version recorded on every durable acquisition record this package
#: produces. Distinct from the ADR-0017 surface's, so evidence from the two
#: cannot be confused for one body of work.
EMPIRICAL_SCHEMA_VERSION: Final = "sharadar-empirical-v1"


class PlanDefect(StrEnum):
    """Why an empirical plan was refused. Closed, and carrying no value.

    Every member names a rule of this module. There is no member shaped to hold a
    subject, a date, a bucket or a count, so a refusal cannot leak one.
    """

    INVENTORY_MALFORMED = "INVENTORY_MALFORMED"
    CLOCK_MALFORMED = "CLOCK_MALFORMED"
    WINDOW_UNSATISFIABLE = "WINDOW_UNSATISFIABLE"
    REQUEST_COUNT_UNEXPECTED = "REQUEST_COUNT_UNEXPECTED"
    DEADLINE_UNSATISFIABLE = "DEADLINE_UNSATISFIABLE"


class EmpiricalPlanError(Exception):
    """A refusal carrying exactly one :class:`PlanDefect`.

    Raised ``from None``: the accepted plan model's own refusals can quote a
    subject, and a subject is precisely what must not reach a traceback.
    """

    __slots__ = ("defect",)

    def __init__(self, defect: PlanDefect) -> None:
        """Bind the defect. The message is the member's token, nothing more."""
        if type(defect) is not PlanDefect:  # pragma: no cover - type guard
            raise TypeError("a defect must be an exact PlanDefect member")
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: PlanDefect) -> EmpiricalPlanError:
    return EmpiricalPlanError(defect)


def compiled_request_phase_seconds(
    *,
    request_count: int = EMPIRICAL_REQUEST_COUNT,
    timeout_seconds: float = TIMEOUT_SECONDS,
    min_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
) -> float:
    """The longest the **provider requests and their pacing alone** can take.

    Every request may occupy its full timeout, and every request after the first may
    wait a full pacing interval. There are ``request_count - 1`` gaps, not
    ``request_count``: the pacer has nothing to wait for before the first request.

    **This is documentation, not a control, and it is not compared against the
    deadline.** It excludes the 144 Bronze writes and the locator, so a run that
    fitted inside it could still exceed the real deadline
    -- which is exactly why the earlier revision's comparison proved nothing. The
    enforcement is
    :class:`~kalpamani.data.qualify.sharadar.operations.AcquisitionDeadline`, on a
    monotonic clock, at every operation. This number is retained because the honest
    consequence -- that 48 requests are **not** guaranteed to complete inside 1,800
    seconds -- is only visible once it is written down.
    """
    if request_count < 1:
        return 0.0
    return request_count * timeout_seconds + (request_count - 1) * min_interval_seconds


def validate_deadline_constants(
    *,
    deadline_seconds: float = ACQUISITION_DEADLINE_SECONDS,
    request_timeout_seconds: float = TIMEOUT_SECONDS,
    pacing_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
    s3_operation_seconds: float = S3_OPERATION_CEILING_SECONDS,
    s3_connect_seconds: float = S3_CONNECT_TIMEOUT_SECONDS,
    s3_read_seconds: float = S3_READ_TIMEOUT_SECONDS,
    construction_seconds: float = LOCATOR_CONSTRUCTION_ALLOWANCE_SECONDS,
    locator_reserve_seconds: float = LOCATOR_TERMINAL_RESERVE_SECONDS,
) -> None:
    """Refuse a deadline configuration that cannot hold. **Never clamp one.**

    Every parameter defaults to its compiled constant, so the module-level call
    below checks the real configuration while a test can drive each branch with its
    own numbers rather than by editing the module.

    The rules, in the clarified architecture's own terms::

        T_s3 > 0                     an operation ceiling of zero bounds nothing
        T_s3 >= connect + read       one attempt may consume both, in sequence
        C >= 0
        L >= 3 * T_s3 + C            three locator writes, no HEAD, construction
        L < D                        a reserve as large as the deadline leaves none
        T_req + P + 3 * T_s3 + L <= D    one paced request-and-publish cycle, plus
                                         the reserve, must fit

    Raises:
        EmpiricalPlanError: ``DEADLINE_UNSATISFIABLE`` for any violation, and for a
            value that is not a finite real number. **Refused, not adjusted.**
    """
    values = (
        deadline_seconds,
        request_timeout_seconds,
        pacing_seconds,
        s3_operation_seconds,
        s3_connect_seconds,
        s3_read_seconds,
        construction_seconds,
        locator_reserve_seconds,
    )
    infinities = (float("inf"), -float("inf"))
    for value in values:
        # NaN is the case worth naming: every comparison below is ``False`` for it,
        # so a bare range check *accepts* it and silently disables the whole budget.
        if type(value) not in (int, float) or value != value or value in infinities:
            raise _refuse(PlanDefect.DEADLINE_UNSATISFIABLE) from None
    if s3_operation_seconds <= 0 or deadline_seconds <= 0:
        raise _refuse(PlanDefect.DEADLINE_UNSATISFIABLE) from None
    if request_timeout_seconds <= 0 or pacing_seconds < 0:
        raise _refuse(PlanDefect.DEADLINE_UNSATISFIABLE) from None
    if s3_connect_seconds <= 0 or s3_read_seconds <= 0:
        raise _refuse(PlanDefect.DEADLINE_UNSATISFIABLE) from None
    if s3_operation_seconds < s3_connect_seconds + s3_read_seconds:
        # The clarified architecture names this one explicitly: a bound taken from
        # one socket timeout is not a bound on an operation that may spend both.
        raise _refuse(PlanDefect.DEADLINE_UNSATISFIABLE) from None
    if construction_seconds < 0:
        raise _refuse(PlanDefect.DEADLINE_UNSATISFIABLE) from None
    if locator_reserve_seconds < (
        LOCATOR_OPERATIONS_ALLOWED * s3_operation_seconds + construction_seconds
    ):
        raise _refuse(PlanDefect.DEADLINE_UNSATISFIABLE) from None
    if locator_reserve_seconds >= deadline_seconds:
        raise _refuse(PlanDefect.DEADLINE_UNSATISFIABLE) from None
    cycle = (
        request_timeout_seconds
        + pacing_seconds
        + BRONZE_OPERATIONS_PER_REQUEST * s3_operation_seconds
        + locator_reserve_seconds
    )
    if cycle > deadline_seconds:
        raise _refuse(PlanDefect.DEADLINE_UNSATISFIABLE) from None


# Checked at import, against the compiled constants themselves. A configuration
# that cannot hold is refused where it is written rather than at the first run that
# would have discovered it against a real provider.
validate_deadline_constants()


def s3_client_config_kwargs() -> dict[str, object]:
    """The botocore ``Config`` arguments **every** qualification S3 client uses.

    A plain dictionary, built by a pure function that reads no environment and
    touches no SDK, so the configuration is assertable in a test that imports no SDK
    at all. **Retries are disabled** --
    ``total_max_attempts`` of one is one attempt in total, the first included -- and
    both socket timeouts are explicit and finite. Without both, the SDK's own
    defaults would multiply a single invocation into several attempts and
    :data:`S3_OPERATION_CEILING_SECONDS` would bound nothing.

    **``max_attempts`` is not used and must not be reintroduced.** In botocore it
    counts the retries *after* the first request, so ``max_attempts = 1`` allows two
    attempts and would silently double the worst case this module's ceiling is
    derived from -- the exact defect this configuration was corrected for.

    **Both operator commands take their client configuration from here**, for two
    different reasons that want the same answer. Acquisition needs it because its
    per-operation ceiling assumes one invocation is one attempt. Assessment needs it
    because every operation it performs is *counted*, and a hidden SDK retry is an
    operation the accounting never counted. One function, so no retry literal is
    written twice and the two cannot drift apart.
    """
    return {
        "connect_timeout": S3_CONNECT_TIMEOUT_SECONDS,
        "read_timeout": S3_READ_TIMEOUT_SECONDS,
        "retries": {
            "total_max_attempts": S3_TOTAL_MAX_ATTEMPTS,
            "mode": S3_RETRY_MODE,
        },
    }


def empirical_window(instant: datetime) -> DateWindow:
    """The full-history window, ``1998-01-01`` through UTC ``T-1``.

    ``T-1`` is the UTC calendar date immediately before ``instant``, derived from
    the injected clock and never operator-supplied. Ending the day before is the
    vendor's own documented upper-bound default, and a window whose last day is
    still in progress makes an empty answer ambiguous between *no session yet* and
    *no data*.

    Raises:
        EmpiricalPlanError: ``CLOCK_MALFORMED`` if ``instant`` is not an aware
            ``datetime``; ``WINDOW_UNSATISFIABLE`` if ``T-1`` falls on or before
            the documented history start, which would mean a clock reading a date
            in the last century.
    """
    if type(instant) is not datetime or instant.tzinfo is None:
        raise _refuse(PlanDefect.CLOCK_MALFORMED) from None
    end = (instant.astimezone(UTC) - timedelta(days=1)).date()
    if end <= HISTORY_START:
        raise _refuse(PlanDefect.WINDOW_UNSATISFIABLE) from None
    return DateWindow(start=HISTORY_START, end=end)


def empirical_dataset_plans(window: DateWindow) -> tuple[DatasetPlan, ...]:
    """The three dataset plans, with the snapshot rule applied where it belongs.

    ``tickers`` is a snapshot and takes **no** window -- the accepted plan model
    refuses one there, and passing one would be a plan that says it filtered a
    table with no time axis. The two windowed tables take the same full-history
    window, so a change in one place changes both.
    """
    plans: list[DatasetPlan] = []
    for dataset in EMPIRICAL_DATASETS:
        windowed = dataset is not SharadarDataset.TICKERS
        plans.append(
            DatasetPlan(
                dataset=dataset,
                window=window if windowed else None,
                page_limit=PAGE_LIMITS[dataset],
                max_pages=EMPIRICAL_MAX_PAGES,
            )
        )
    return tuple(plans)


def empirical_limits() -> QualificationLimits:
    """The run-level ceilings, every one at or below its compiled bound.

    ``retry_budget`` is left at the compiled default deliberately. Lowering it to
    zero would look tidier and would prove less: the guarantee this package relies
    on is that **48 requests cannot afford a retry against the budget that exists**,
    and stating a budget of zero would replace that arithmetic with a declaration.
    """
    return QualificationLimits(
        max_subjects=REQUIRED_SUBJECT_COUNT,
        max_datasets=len(EMPIRICAL_DATASETS),
        max_requests=EMPIRICAL_REQUEST_COUNT,
        max_pages_per_request=EMPIRICAL_MAX_PAGES,
        max_response_bytes=MAX_RESPONSE_BYTES,
        max_run_bytes=MAX_RUN_BYTES,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class EmpiricalPlan:
    """One validated 48-request plan, and the inventory digest that produced it.

    The digest travels with the plan so the locator can bind both without the
    acquisition path having to keep the inventory alive, and without any name
    being carried past the plan model's own typed subjects.
    """

    plan: QualificationPlan
    inventory_digest: str
    #: The elapsed-time deadline the acquisition phase will be held to, in seconds.
    #: Carried on the plan so the value enforced is the value validated, rather than
    #: a constant read again somewhere else and possibly differently.
    deadline_seconds: float

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a stand-in could present a plan never validated."""
        raise TypeError("EmpiricalPlan may not be subclassed")

    def __repr__(self) -> str:
        """Counts and a digest prefix. **Never a subject, and never a window.**"""
        return (
            f"EmpiricalPlan(requests={self.plan.request_count}, "
            f"inventory={self.inventory_digest[:8]}...)"
        )


def build_empirical_plan(
    *,
    inventory: PrivateInventory,
    execution_id: str,
    instant: datetime,
) -> EmpiricalPlan:
    """The one plan this package permits. **48 requests, and nothing selectable.**

    The subjects come from the validated private inventory and the execution
    identity from the operator; the datasets, windows, page limits, page count,
    response format, ceilings and schema version are this module's constants.

    Raises:
        EmpiricalPlanError: ``INVENTORY_MALFORMED`` for anything that is not an
            exact :class:`~kalpamani.data.qualify.sharadar.inventory.PrivateInventory`;
            ``CLOCK_MALFORMED`` or ``WINDOW_UNSATISFIABLE`` from the window;
            ``REQUEST_COUNT_UNEXPECTED`` if the assembled plan does not generate
            exactly :data:`EMPIRICAL_REQUEST_COUNT` requests;
            ``DEADLINE_UNSATISFIABLE`` if the compiled deadline configuration does
            not hold. The accepted plan model's own refusals -- which can quote a
            subject -- are converted to ``INVENTORY_MALFORMED`` ``from None``.
    """
    if type(inventory) is not PrivateInventory:
        raise _refuse(PlanDefect.INVENTORY_MALFORMED) from None

    window = empirical_window(instant)

    try:
        plan = QualificationPlan(
            subjects=inventory.subjects,
            datasets=empirical_dataset_plans(window),
            execution_id=execution_id,
            response_format=EMPIRICAL_RESPONSE_FORMAT,
            limits=empirical_limits(),
            source_schema_version=EMPIRICAL_SCHEMA_VERSION,
        )
    except Exception:
        # The plan model refuses a malformed execution identity, a duplicated
        # subject and a window on the snapshot table -- and its refusals can
        # quote the offending subject. Only the closed defect survives.
        raise _refuse(PlanDefect.INVENTORY_MALFORMED) from None

    if plan.request_count != EMPIRICAL_REQUEST_COUNT or len(plan.requests()) != (
        EMPIRICAL_REQUEST_COUNT
    ):
        # Both the arithmetic and the generator, because a ceiling that bounded a
        # different number from the one about to be issued would bound nothing.
        raise _refuse(PlanDefect.REQUEST_COUNT_UNEXPECTED) from None

    # Re-checked per plan, not only at import. The import-time call catches a bad
    # edit; this one catches a plan built in a process where the module was reloaded
    # or the constants were patched, which is exactly what a test does.
    validate_deadline_constants()

    return EmpiricalPlan(
        plan=plan,
        inventory_digest=inventory.digest,
        deadline_seconds=ACQUISITION_DEADLINE_SECONDS,
    )


__all__ = [
    "ACQUISITION_DEADLINE_SECONDS",
    "ACTIONS_PAGE_LIMIT",
    "BRONZE_OPERATIONS_PER_REQUEST",
    "BRONZE_OPERATION_ADMISSION_SECONDS",
    "EMPIRICAL_DATASETS",
    "EMPIRICAL_MAX_PAGES",
    "EMPIRICAL_REQUEST_COUNT",
    "EMPIRICAL_RESPONSE_FORMAT",
    "EMPIRICAL_SCHEMA_VERSION",
    "HISTORY_START",
    "LOCATOR_ATTEMPT_ADMISSION_SECONDS",
    "LOCATOR_CONSTRUCTION_ALLOWANCE_SECONDS",
    "LOCATOR_OPERATIONS_ALLOWED",
    "LOCATOR_OPERATION_ADMISSION_SECONDS",
    "LOCATOR_TERMINAL_RESERVE_SECONDS",
    "MAX_RESPONSE_BYTES",
    "MAX_RUN_BYTES",
    "MIN_REQUEST_INTERVAL_SECONDS",
    "PAGE_LIMITS",
    "PROVIDER_MAX_ATTEMPTS",
    "PROVIDER_REQUEST_ADMISSION_SECONDS",
    "S3_CONNECT_TIMEOUT_SECONDS",
    "S3_OPERATION_CEILING_SECONDS",
    "S3_READ_TIMEOUT_SECONDS",
    "S3_RETRY_MODE",
    "S3_TOTAL_MAX_ATTEMPTS",
    "STOCKS_PAGE_LIMIT",
    "TICKERS_PAGE_LIMIT",
    "TIMEOUT_SECONDS",
    "EmpiricalPlan",
    "EmpiricalPlanError",
    "PlanDefect",
    "build_empirical_plan",
    "compiled_request_phase_seconds",
    "empirical_dataset_plans",
    "empirical_limits",
    "empirical_window",
    "s3_client_config_kwargs",
    "validate_deadline_constants",
]
