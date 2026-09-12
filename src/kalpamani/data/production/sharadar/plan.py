"""The compiled production acquisition plan (ADR-0035 §3.1, ADR-0036 §2.6).

**Deterministic, compiled and bounded — the qualification plan's discipline at
production scale.** Requests are generated in one canonical order (dataset, then
window, then page) from a slice whose ceilings are compiled constants that a slice
may lower and never raise. The plan's digest is the SHA-256 of the canonical
serialization of every request coordinate and every ceiling, so two plans that
would ask the provider for anything different have different digests, and an
input whose ``plan_digest`` does not equal the digest compiled **from its own
slice** is refused -- the comparison is against the compiled plan, never merely
against a supplied number.

**No implicit expansion, no unbounded pagination, no additional retry budget.**
Every window and every page is stated in the request list before the first
request is issued; the page count per window is a compiled constant rather than a
value read from a response, because the acquisition path never parses a payload
and therefore cannot count rows (ADR-0012's opaque-payload boundary). Whether a
final page was truncated is the **build actor's** finding (ADR-0035 §3.1
``DELIVERY_TRUNCATED``), made where parsing is permitted.

**No provider request model of this package reaches the wire.** The accepted
:class:`~kalpamani.data.ingest.sharadar.datasets.SharadarRequest` requires a
ticker on every request (ADR-0009: *no default subject*), and ADR-0035 §3.1
designs production requests as whole cross-sections by window and by session
date with no ticker. That is an accepted-contract conflict this module does not
resolve by widening either side: it emits :class:`ProductionRequest` coordinates
for an **injected** provider adapter, and no adapter that could send them exists
in this repository. See the pull request's finding dispositions.

**This module allocates no live acquisition budget.** Its ceilings bound what a
plan may describe; whether any run may happen is a separate written authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.ingest.sharadar.datasets import (
    MAX_PAGE_LIMIT,
    WINDOWED_DATASETS,
    SharadarDataset,
)
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

#: The one plan contract. Matched exactly by the digest's serialization.
PLAN_CONTRACT_ID: Final = "kalpamani-production-acquisition-plan/v1"

#: Compiled ceilings. Each may be lowered by a slice and never raised.
PAGE_LIMIT: Final = MAX_PAGE_LIMIT
PAGES_PER_WINDOW: Final[dict[str, int]] = {
    SharadarDataset.TICKERS.value: 4,
    SharadarDataset.ACTIONS.value: 2,
    SharadarDataset.STOCKS.value: 2,
}
#: A canonical ``actions`` window is one calendar year, cut from 1998-01-01; a
#: ``stocks`` window is one session date (ADR-0035 §3.1). A calendar day that is
#: not a session returns a header-only page, which is bounded and honest; a
#: trading calendar is a later refinement, not an assumption made here.
ACTIONS_WINDOW_DAYS: Final = 366
ACTIONS_EARLIEST: Final = date(1998, 1, 1)
MAX_REQUESTS_PER_RUN: Final = MAX_SLICE_REQUESTS
MAX_RESPONSE_BYTES: Final = 16 * 1024 * 1024
MAX_RUN_BYTES: Final = 512 * 1024 * 1024
SNAPSHOT_WINDOW: Final = "SNAPSHOT"

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
    """One fully-stated request coordinate: dataset, window, page. No ticker.

    ``window`` is ``SNAPSHOT`` for the untimed dataset or ``YYYY-MM-DD/YYYY-MM-DD``
    inclusive; ``page_offset`` is the vendor's ``skip``; ``page_limit`` its ``limit``.
    """

    ordinal: int
    dataset: str
    window: str
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
            "page_offset": self.page_offset,
            "page_limit": self.page_limit,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class CompiledPlan:
    """A compiled plan: the ordered requests, every ceiling, the mode, one digest."""

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
        return f"CompiledPlan(requests={len(self.requests)}, mode={self.acquisition_mode.value!r})"

    @property
    def request_count(self) -> int:
        """How many provider requests the plan issues, exactly."""
        return len(self.requests)


def _windows_for(dataset: str, window: str) -> list[str]:
    """The canonical windows one slice window decomposes into, in order."""
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


def _digest(document: dict[str, Any]) -> str:
    return sha256_hex(canonical_bytes(document))


def compile_plan(covered: Slice, *, acquisition_mode: AcquisitionMode) -> CompiledPlan:
    """Compile the plan one slice describes. **Deterministic, and nothing is fetched.**

    The request list is generated in canonical order -- dataset (as the slice lists
    them, which is sorted), then window, then page -- and refused if it would exceed
    the compiled per-run ceiling. The slice's response ceiling may lower the compiled
    one and never raise it.

    Raises:
        ProductionPlanError: for a mode outside the two production modes, a window
            the dataset cannot take, a slice over the request ceiling, or a slice
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
        pages = PAGES_PER_WINDOW[dataset]
        for window in _windows_for(dataset, windows[dataset]):
            for page in range(pages):
                if len(requests) >= MAX_REQUESTS_PER_RUN:
                    raise ProductionPlanError() from None
                requests.append(
                    ProductionRequest(
                        ordinal=len(requests),
                        dataset=dataset,
                        window=window,
                        page_offset=page * PAGE_LIMIT,
                        page_limit=PAGE_LIMIT,
                    )
                )
    if not requests or len(requests) != covered.request_count:
        raise ProductionPlanError() from None
    document = {
        "contract_id": PLAN_CONTRACT_ID,
        "acquisition_mode": acquisition_mode.value,
        "requests": [request.coordinates() for request in requests],
        "max_response_bytes": covered.max_response_bytes,
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


def plan_digest_for(covered: Slice, *, acquisition_mode: AcquisitionMode) -> str:
    """The digest the compiled plan of ``covered`` carries. Compiles; fetches nothing."""
    return compile_plan(covered, acquisition_mode=acquisition_mode).digest


def bind_plan(admitted: AcquisitionInput) -> CompiledPlan:
    """The compiled plan an admitted input authorizes -- or a refusal.

    Compiles the plan **from the input's own slice** and requires the input's
    ``plan_digest`` to equal the compiled digest. A slice the compiler refuses is
    ``PLAN_NOT_COMPILABLE``; a digest that is not the compiled one is
    ``PLAN_DIGEST_MISMATCH``. Nothing is fetched.

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
    "MAX_REQUESTS_PER_RUN",
    "MAX_RESPONSE_BYTES",
    "MAX_RUN_BYTES",
    "PAGES_PER_WINDOW",
    "PAGE_LIMIT",
    "PLAN_CONTRACT_ID",
    "PRODUCTION_MODES",
    "SNAPSHOT_WINDOW",
    "CompiledPlan",
    "ProductionPlanError",
    "ProductionRequest",
    "bind_plan",
    "compile_plan",
    "plan_digest_for",
]
