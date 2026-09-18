"""The compiled production acquisition plan, pagination v2 (ADR-0053 §2, §11, §13).

**Deterministic, compiled and bounded — the qualification plan's discipline at
production scale.** Data coordinates are generated in one canonical order (dataset,
then window) from a slice whose ceilings are compiled constants that a slice may lower
and never raise. The plan's digest is the SHA-256 of the canonical serialization of
every data coordinate, every governed limit, the probe policy and every ceiling, so two
plans that would ask the provider for anything different have different digests, and an
input whose ``plan_digest`` does not equal the digest compiled **from its own slice** is
refused -- the comparison is against the compiled plan, never merely against a supplied
number.

**One data coordinate per group, and no offset page after it.** Under pagination v2
every group -- the ``table=stocks`` tickers snapshot, one actions year window, one stocks
session date -- is exactly one governed data request at offset 0 and its dataset's
qualified limit (tickers and actions 100,000; stocks 10,000). Offset-based assembly of
two data-bearing pages is prohibited, so the plan emits no second page; what it emits
instead is a **conditional-probe authorization**: a completion probe at offset ``L`` may
be issued for a coordinate only when its data response carries exactly ``L`` rows
(:mod:`~kalpamani.data.production.sharadar.completion`). The plan therefore carries two
counts -- the planned data-coordinate count ``N`` and the worst-case provider-call ceiling
``2N`` -- and the conditional S3 write ceiling ``1 + 3N + 1``, and no operation may exceed
either bound.

**The ceilings are the accepted D-21 envelope (ADR-0053 §13.2).** A complete provider
body is admitted up to 32 MiB and refused whole above it; the per-request timeout stays
30 s, the task deadline 1,800 s, one attempt, 1 s pacing. The process-memory target
(1,024 MiB) and the task memory (2,048 MiB) are configuration and task-definition
contracts, recorded beside the plan rather than measured by it.

**Nothing here reaches a provider, and this module allocates no live acquisition
budget.** Its ceilings bound what a plan may describe; whether any run may happen is a
separate written authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.ingest.sharadar.datasets import (
    PRODUCTION_PAGE_LIMITS,
    TICKERS_TABLE_PARAMETER,
    TICKERS_TABLE_STOCKS,
    WINDOWED_DATASETS,
    SharadarDataset,
)
from kalpamani.data.production.sharadar.completion import PROBE_POLICY
from kalpamani.data.production.sharadar.inputs import (
    MAX_RESPONSE_BYTES as SLICE_MAX_RESPONSE_BYTES,
)
from kalpamani.data.production.sharadar.inputs import (
    MAX_SLICE_REQUESTS,
    AcquisitionInput,
    InputDefect,
    InputError,
    Slice,
)
from kalpamani.data.qualify.sharadar.plan import (
    ACQUISITION_DEADLINE_SECONDS,
    MIN_REQUEST_INTERVAL_SECONDS,
    PROVIDER_MAX_ATTEMPTS,
    TIMEOUT_SECONDS,
)

#: The one plan contract. Matched exactly by the digest's serialization. The v1
#: contract (``.../v1``: two-to-four offset pages per group at limit 10,000) is
#: superseded; a v1 digest never equals a v2 digest, so a v1 input is refused by
#: :func:`bind_plan` as ``PLAN_DIGEST_MISMATCH`` rather than reinterpreted.
PLAN_CONTRACT_ID: Final = "kalpamani-production-acquisition-plan/v2"
SUPERSEDED_PLAN_CONTRACT_IDS: Final[frozenset[str]] = frozenset(
    {"kalpamani-production-acquisition-plan/v1"}
)

#: The governed page limit per dataset (ADR-0053 §13.2). One data coordinate per group.
PAGE_LIMITS: Final[dict[str, int]] = dict(PRODUCTION_PAGE_LIMITS)
#: The tickers predicate every production tickers coordinate carries (§11.3).
TICKERS_PREDICATE: Final[tuple[tuple[str, str], ...]] = (
    (TICKERS_TABLE_PARAMETER, TICKERS_TABLE_STOCKS),
)
NO_PREDICATE: Final[tuple[tuple[str, str], ...]] = ()
#: A canonical ``actions`` window is one calendar year, cut from 1998-01-01; a
#: ``stocks`` window is one session date (ADR-0035 §3.1). A calendar day that is
#: not a session returns a header-only page, which is bounded and honest; a
#: trading calendar is a later refinement, not an assumption made here.
ACTIONS_WINDOW_DAYS: Final = 366
ACTIONS_EARLIEST: Final = date(1998, 1, 1)
#: The per-run provider-call ceiling (the accepted 96), applied to the **worst case**
#: -- one conditional probe per data coordinate -- so a run plans at most 48 groups.
MAX_PROVIDER_CALLS_PER_RUN: Final = MAX_SLICE_REQUESTS
MAX_DATA_COORDINATES_PER_RUN: Final = MAX_PROVIDER_CALLS_PER_RUN // 2
#: Kept as the accepted name for the per-run request ceiling; it bounds provider calls.
MAX_REQUESTS_PER_RUN: Final = MAX_PROVIDER_CALLS_PER_RUN
#: The accepted payload / read / parse ceiling: the complete body before admission.
MAX_RESPONSE_BYTES: Final = 32 * 1024 * 1024
PAYLOAD_CEILING_BYTES: Final = MAX_RESPONSE_BYTES
MAX_RUN_BYTES: Final = 512 * 1024 * 1024
SNAPSHOT_WINDOW: Final = "SNAPSHOT"
#: Documented deployment targets (ADR-0053 §13.2), enforced through the compiled
#: configuration and the task definition rather than measured at runtime.
PROCESS_MEMORY_CEILING_BYTES: Final = 1024 * 1024 * 1024
TASK_MEMORY_MIB: Final = 2048
#: Conditional S3 writes of a complete run of ``N`` data coordinates: the reservation,
#: three per coordinate (claim, payload, record) and the locator.
FIXED_WRITES_PER_RUN: Final = 2
WRITES_PER_COORDINATE: Final = 3

#: The two production modes a plan may declare. Never a qualification.
PRODUCTION_MODES: Final[frozenset[AcquisitionMode]] = frozenset(
    {AcquisitionMode.BACKFILL, AcquisitionMode.UPDATE}
)


class ProductionPlanError(ValueError):
    """A plan could not be compiled from a slice. **Carries no value.**"""

    __slots__ = ()

    def __init__(self) -> None:
        """Carry the fixed sentence."""
        super().__init__("a production acquisition plan could not be compiled from this slice")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductionRequest:
    """One fully-stated data coordinate: dataset, window, predicate, page. No ticker.

    ``window`` is ``SNAPSHOT`` for the untimed dataset or ``YYYY-MM-DD/YYYY-MM-DD``
    inclusive; ``predicate`` is the closed pairs the request transmits beyond the
    window (the tickers ``table``); ``page_offset`` is the vendor's ``skip`` (0 for a
    data coordinate, ``L`` for its probe); ``page_limit`` its governed ``limit``.
    """

    ordinal: int
    dataset: str
    window: str
    predicate: tuple[tuple[str, str], ...]
    page_offset: int
    page_limit: int

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("ProductionRequest may not be subclassed")

    def coordinates(self) -> dict[str, Any]:
        """The closed, serializable coordinate set the digest and the locator carry."""
        return {
            "ordinal": self.ordinal,
            "dataset": self.dataset,
            "window": self.window,
            "predicate": dict(self.predicate),
            "page_offset": self.page_offset,
            "page_limit": self.page_limit,
        }

    def probe(self) -> ProductionRequest:
        """The completion probe this data coordinate authorizes: the same shape at offset ``L``.

        Issued only when the data response carries exactly ``page_limit`` rows; never a
        second data page, and never planned as one.
        """
        return ProductionRequest(
            ordinal=self.ordinal,
            dataset=self.dataset,
            window=self.window,
            predicate=self.predicate,
            page_offset=self.page_limit,
            page_limit=self.page_limit,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CompiledPlan:
    """A compiled plan: the ordered data coordinates, every ceiling, the mode, one digest."""

    contract_id: str
    acquisition_mode: AcquisitionMode
    requests: tuple[ProductionRequest, ...]
    max_response_bytes: int
    max_run_bytes: int
    deadline_seconds: float
    min_request_interval_seconds: float
    timeout_seconds: float
    provider_max_attempts: int
    digest: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("CompiledPlan may not be subclassed")

    def __repr__(self) -> str:
        """Counts only. **Never the digest.**"""
        return (
            f"CompiledPlan(data_coordinates={len(self.requests)}, "
            f"max_provider_calls={self.max_provider_calls}, "
            f"mode={self.acquisition_mode.value!r})"
        )

    @property
    def request_count(self) -> int:
        """How many data coordinates the plan issues, exactly. One data request each."""
        return len(self.requests)

    @property
    def data_coordinates(self) -> int:
        """The planned data-coordinate count ``N``."""
        return len(self.requests)

    @property
    def max_provider_calls(self) -> int:
        """The worst-case provider-call ceiling: one conditional probe per data coordinate."""
        return 2 * len(self.requests)

    @property
    def expected_writes(self) -> int:
        """The conditional S3 writes of a complete run: ``1 + 3N + 1``."""
        return FIXED_WRITES_PER_RUN + WRITES_PER_COORDINATE * len(self.requests)

    @property
    def page_limits(self) -> dict[str, int]:
        """The governed limit per dataset the plan compiled."""
        return dict(PAGE_LIMITS)

    @property
    def probe_policy(self) -> str:
        """The conditional-probe policy every v2 plan declares."""
        return PROBE_POLICY


def canonical_windows(dataset: str, window: str) -> list[str]:
    """The canonical windows one slice window decomposes into, in order.

    Raises:
        ProductionPlanError: for a window the dataset cannot take.
    """
    if dataset not in WINDOWED_DATASETS:
        if window != SNAPSHOT_WINDOW:
            raise ProductionPlanError() from None
        return [SNAPSHOT_WINDOW]
    if window == SNAPSHOT_WINDOW:
        raise ProductionPlanError() from None
    try:
        start_text, end_text = window.split("/")
        start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
    except ValueError:
        raise ProductionPlanError() from None
    if start > end:
        raise ProductionPlanError() from None
    if dataset == SharadarDataset.ACTIONS.value:
        if start < ACTIONS_EARLIEST:
            raise ProductionPlanError() from None
        windows: list[str] = []
        cursor = start
        while cursor <= end:
            last = min(cursor + timedelta(days=ACTIONS_WINDOW_DAYS - 1), end)
            windows.append(f"{cursor.isoformat()}/{last.isoformat()}")
            cursor = last + timedelta(days=1)
        return windows
    # stocks: one window per session date.
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    return [f"{day.isoformat()}/{day.isoformat()}" for day in days]


def _predicate_for(dataset: str) -> tuple[tuple[str, str], ...]:
    return TICKERS_PREDICATE if dataset == SharadarDataset.TICKERS.value else NO_PREDICATE


def _digest(document: dict[str, Any]) -> str:
    return sha256_hex(canonical_bytes(document))


def compile_plan(covered: Slice, *, acquisition_mode: AcquisitionMode) -> CompiledPlan:
    """Compile the plan one slice describes. **Deterministic, and nothing is fetched.**

    The data coordinates are generated in canonical order -- dataset (as the slice
    lists them, which is sorted), then window -- one per group at offset 0 and the
    dataset's governed limit, and refused if the worst-case provider-call ceiling
    (``2N``) would exceed the compiled per-run ceiling. The slice's response ceiling
    may lower the compiled one and never raise it. The slice's ``request_count`` is
    the planned data-coordinate count.

    Raises:
        ProductionPlanError: for a mode outside the two production modes, a window
            the dataset cannot take, a slice over the coordinate ceiling, or a slice
            whose ``request_count`` is not the count this plan actually issues.
    """
    if type(covered) is not Slice:
        raise ProductionPlanError() from None
    if type(acquisition_mode) is not AcquisitionMode or acquisition_mode not in PRODUCTION_MODES:
        raise ProductionPlanError() from None
    if not 1 <= covered.max_response_bytes <= min(MAX_RESPONSE_BYTES, SLICE_MAX_RESPONSE_BYTES):
        raise ProductionPlanError() from None
    windows = dict(covered.windows)
    requests: list[ProductionRequest] = []
    for dataset in covered.datasets:
        limit = PAGE_LIMITS[dataset]
        for window in canonical_windows(dataset, windows[dataset]):
            if len(requests) >= MAX_DATA_COORDINATES_PER_RUN:
                raise ProductionPlanError() from None
            requests.append(
                ProductionRequest(
                    ordinal=len(requests),
                    dataset=dataset,
                    window=window,
                    predicate=_predicate_for(dataset),
                    page_offset=0,
                    page_limit=limit,
                )
            )
    if not requests or len(requests) != covered.request_count:
        raise ProductionPlanError() from None
    if 2 * len(requests) > MAX_PROVIDER_CALLS_PER_RUN:
        raise ProductionPlanError() from None
    document = {
        "contract_id": PLAN_CONTRACT_ID,
        "acquisition_mode": acquisition_mode.value,
        "requests": [request.coordinates() for request in requests],
        "data_coordinates": len(requests),
        "probe_policy": PROBE_POLICY,
        "max_provider_calls": 2 * len(requests),
        "expected_writes": FIXED_WRITES_PER_RUN + WRITES_PER_COORDINATE * len(requests),
        "page_limits": dict(sorted(PAGE_LIMITS.items())),
        "max_response_bytes": covered.max_response_bytes,
        "payload_ceiling_bytes": PAYLOAD_CEILING_BYTES,
        "max_run_bytes": MAX_RUN_BYTES,
        # Seconds are rendered as decimal text: the canonical serializer refuses a
        # float, and a digest over ``"1800.0"`` is a digest over the value.
        "deadline_seconds": str(ACQUISITION_DEADLINE_SECONDS),
        "min_request_interval_seconds": str(MIN_REQUEST_INTERVAL_SECONDS),
        "timeout_seconds": str(TIMEOUT_SECONDS),
        "provider_max_attempts": PROVIDER_MAX_ATTEMPTS,
    }
    return CompiledPlan(
        contract_id=PLAN_CONTRACT_ID,
        acquisition_mode=acquisition_mode,
        requests=tuple(requests),
        max_response_bytes=covered.max_response_bytes,
        max_run_bytes=MAX_RUN_BYTES,
        deadline_seconds=ACQUISITION_DEADLINE_SECONDS,
        min_request_interval_seconds=MIN_REQUEST_INTERVAL_SECONDS,
        timeout_seconds=TIMEOUT_SECONDS,
        provider_max_attempts=PROVIDER_MAX_ATTEMPTS,
        digest=_digest(document),
    )


#: The pagination-v2 deployment targets contract, carried by the acquisition entry's
#: compiled configuration (ADR-0053 §13.2). Pinned to these constants: an image whose
#: configuration names other targets cannot run this code.
PAGINATION_TARGETS_CONTRACT_ID: Final = "kalpamani-pagination-v2-targets/v1"


def pagination_targets_document() -> dict[str, Any]:
    """The closed targets document: limits, ceilings, timeouts, memory, probe policy."""
    return {
        "contract_id": PAGINATION_TARGETS_CONTRACT_ID,
        "page_limits": dict(sorted(PAGE_LIMITS.items())),
        "tickers_predicate": dict(TICKERS_PREDICATE),
        "probe_policy": PROBE_POLICY,
        "payload_ceiling_bytes": PAYLOAD_CEILING_BYTES,
        "max_run_bytes": MAX_RUN_BYTES,
        "process_memory_ceiling_bytes": PROCESS_MEMORY_CEILING_BYTES,
        "task_memory_mib": TASK_MEMORY_MIB,
        "provider_timeout_seconds": str(TIMEOUT_SECONDS),
        "task_deadline_seconds": str(ACQUISITION_DEADLINE_SECONDS),
        "max_data_coordinates_per_run": MAX_DATA_COORDINATES_PER_RUN,
        "max_provider_calls_per_run": MAX_PROVIDER_CALLS_PER_RUN,
        "writes_per_run": f"{FIXED_WRITES_PER_RUN - 1} + {WRITES_PER_COORDINATE}N + 1",
    }


def plan_digest_for(covered: Slice, *, acquisition_mode: AcquisitionMode) -> str:
    """The digest the compiled plan of ``covered`` carries. Compiles; fetches nothing."""
    return compile_plan(covered, acquisition_mode=acquisition_mode).digest


def bind_plan(admitted: AcquisitionInput) -> CompiledPlan:
    """The compiled plan an admitted input authorizes -- or a refusal.

    Compiles the plan **from the input's own slice** and requires the input's
    ``plan_digest`` to equal the compiled digest. A slice the compiler refuses is
    ``PLAN_NOT_COMPILABLE``; a digest that is not the compiled one -- a superseded v1
    specification included -- is ``PLAN_DIGEST_MISMATCH``. Nothing is fetched.

    Raises:
        InputError: one of the two defects above.
    """
    if type(admitted) is not AcquisitionInput:
        raise InputError(InputDefect.DOCUMENT_MALFORMED) from None
    try:
        plan = compile_plan(
            admitted.slice, acquisition_mode=AcquisitionMode(admitted.slice.acquisition_mode)
        )
    except (ProductionPlanError, ValueError):
        raise InputError(InputDefect.PLAN_NOT_COMPILABLE) from None
    if plan.digest != admitted.plan_digest:
        raise InputError(InputDefect.PLAN_DIGEST_MISMATCH) from None
    return plan


__all__ = [
    "ACTIONS_EARLIEST",
    "ACTIONS_WINDOW_DAYS",
    "FIXED_WRITES_PER_RUN",
    "MAX_DATA_COORDINATES_PER_RUN",
    "MAX_PROVIDER_CALLS_PER_RUN",
    "MAX_REQUESTS_PER_RUN",
    "MAX_RESPONSE_BYTES",
    "MAX_RUN_BYTES",
    "NO_PREDICATE",
    "PAGE_LIMITS",
    "PAGINATION_TARGETS_CONTRACT_ID",
    "PAYLOAD_CEILING_BYTES",
    "PLAN_CONTRACT_ID",
    "PROCESS_MEMORY_CEILING_BYTES",
    "PRODUCTION_MODES",
    "SNAPSHOT_WINDOW",
    "SUPERSEDED_PLAN_CONTRACT_IDS",
    "TASK_MEMORY_MIB",
    "TICKERS_PREDICATE",
    "WRITES_PER_COORDINATE",
    "CompiledPlan",
    "ProductionPlanError",
    "ProductionRequest",
    "bind_plan",
    "canonical_windows",
    "compile_plan",
    "pagination_targets_document",
    "plan_digest_for",
]
