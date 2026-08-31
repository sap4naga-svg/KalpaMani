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

**The wall-clock ceiling is a derived worst-case bound, and it is enforced as
one.** There is no interrupting timer here, and adding one would mean a new halt
state on an accepted runtime contract. What the architecture actually states is
arithmetic: 48 requests at a 30-second timeout, plus 47 one-second pacing gaps, is
1,487 seconds, inside the 1,800-second ceiling. :func:`worst_case_wall_clock_seconds`
computes that, and :func:`build_empirical_plan` refuses a plan whose worst case
exceeds the ceiling -- so the bound is checked rather than asserted in prose, and
it is honestly labelled a bound rather than a stopwatch.

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

#: The worst-case wall clock a complete run may occupy, in seconds.
WALL_CLOCK_CEILING_SECONDS: Final = 1_800

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
    WALL_CLOCK_UNSATISFIABLE = "WALL_CLOCK_UNSATISFIABLE"


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


def worst_case_wall_clock_seconds(
    *,
    request_count: int = EMPIRICAL_REQUEST_COUNT,
    timeout_seconds: float = TIMEOUT_SECONDS,
    min_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
) -> float:
    """The longest a sequential run of ``request_count`` requests can take.

    Every request may occupy its full timeout, and every request after the first
    may wait a full pacing interval. There are ``request_count - 1`` gaps, not
    ``request_count``: the pacer has nothing to wait for before the first request.

    **This is a bound, not a measurement.** It says what the configuration cannot
    exceed; it does not stop a run that somehow does, and nothing here claims it
    would. A run is sequential by construction -- there is no concurrency anywhere
    on this path -- which is what makes the sum, rather than a maximum, correct.
    """
    if request_count < 1:
        return 0.0
    return request_count * timeout_seconds + (request_count - 1) * min_interval_seconds


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
    worst_case_seconds: float

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
            ``WALL_CLOCK_UNSATISFIABLE`` if the worst case exceeds the ceiling.
            The accepted plan model's own refusals -- which can quote a subject --
            are converted to ``INVENTORY_MALFORMED`` ``from None``.
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

    worst_case = worst_case_wall_clock_seconds(request_count=plan.request_count)
    if worst_case > WALL_CLOCK_CEILING_SECONDS:
        raise _refuse(PlanDefect.WALL_CLOCK_UNSATISFIABLE) from None

    return EmpiricalPlan(
        plan=plan,
        inventory_digest=inventory.digest,
        worst_case_seconds=worst_case,
    )


__all__ = [
    "ACTIONS_PAGE_LIMIT",
    "EMPIRICAL_DATASETS",
    "EMPIRICAL_MAX_PAGES",
    "EMPIRICAL_REQUEST_COUNT",
    "EMPIRICAL_RESPONSE_FORMAT",
    "EMPIRICAL_SCHEMA_VERSION",
    "HISTORY_START",
    "MAX_RESPONSE_BYTES",
    "MAX_RUN_BYTES",
    "MIN_REQUEST_INTERVAL_SECONDS",
    "PAGE_LIMITS",
    "PROVIDER_MAX_ATTEMPTS",
    "STOCKS_PAGE_LIMIT",
    "TICKERS_PAGE_LIMIT",
    "TIMEOUT_SECONDS",
    "WALL_CLOCK_CEILING_SECONDS",
    "EmpiricalPlan",
    "EmpiricalPlanError",
    "PlanDefect",
    "build_empirical_plan",
    "empirical_dataset_plans",
    "empirical_limits",
    "empirical_window",
    "worst_case_wall_clock_seconds",
]
