"""The bounded qualification plan: what a run may ask for, decided before it runs.

**Dormant. Constructing, validating, importing or rendering a plan sends nothing.**
A plan is a description; :mod:`kalpamani.data.ingest.sharadar.runtime` is the only
thing that acts on one, and it acts on dependencies a caller hands it. There is no
composition root here, no credential, no bucket, no client and no transport
(ADR-0012).

**Every ceiling is compiled in, and a caller may only move downward.** A limit a
caller supplies is checked against the constant beside it, so the worst a
misconfigured or hostile plan can do is ask for *less*. That is the whole point of
putting the ceilings in the type rather than in a runbook: a run cannot be widened
by editing a configuration file, only by editing this module under review.

**Validation happens once, completely, before anything is fetched or stored.** A
plan that is partly wrong is refused whole. The alternative -- discovering the
eighth request is malformed after seven have been published -- leaves immutable
objects in a licensed bucket that nobody decided to create, and immutable means
they stay.

**Three datasets, and the refusal of the fourth is the point.** ``tickers``,
``stocks`` and ``actions`` are what Stage 3A has authority for.
``fundamentals``, ``daily``, holdings, events, funds and metrics are Phase-3B
domains: a plan that could name one would be authority this slice does not have,
hidden inside a convenience. Unknown names are refused for the same reason, not
merely because they would fail later.

**Nothing defaults, and no symbol is compiled in.** Every request names a subject
the caller supplied explicitly. There is no default ticker, no "the usual
sample", and no implicit window -- the vendor defaults ``from`` to one year ago
and ``to`` to the prior day (`PSR-SHD-121`), so an omitted window silently means
something narrower than it looks.

**Point-in-time consequences travel with the plan, not beside it.** Sharadar
price data is ``PROVIDER_DERIVED`` and usable only under
``PROVIDER_REALISTIC_PIT``; Q7 is publicly unresolved and Q8 publicly bounded
(ADR-0010). :data:`PERMITTED_PROFILE` and :func:`refuse_public_pit` put those in
the type system rather than in a comment, and nothing here resolves any of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from kalpamani.data.contracts.errors import PointInTimeError
from kalpamani.data.contracts.vocabulary import InformationSetProfile, closed_member
from kalpamani.data.ingest.sharadar.client import MAX_ATTEMPTS_CEILING
from kalpamani.data.ingest.sharadar.datasets import (
    MAX_PAGE_LIMIT,
    WINDOWED_DATASETS,
    DateWindow,
    Page,
    ResponseFormat,
    SharadarDataset,
    SharadarRequest,
)
from kalpamani.data.ingest.sharadar.transport import DEFAULT_MAX_RESPONSE_BYTES

# ---------------------------------------------------------------------------
# Hard ceilings
# ---------------------------------------------------------------------------
#
# Each is a bound on a bound: a caller may configure any value at or below it and
# nothing at all above it. The rationale beside each is the review record -- a
# number with no stated reason is a number the next session will raise.

#: At most eight subjects in one qualification run.
#:
#: Qualification measures whether a provider's data behaves as documented; it is
#: not a backfill, and a wide subject list is how one quietly becomes the other.
#: Eight is enough to cover the shapes qualification cares about -- a large cap, a
#: small cap, a delisted name, a renamed name, a split, a dividend -- while staying
#: small enough that a whole run is reviewable by reading its result.
MAX_SUBJECTS: Final = 8

#: There are exactly three Stage-3A datasets, so this is a bound that cannot be
#: exceeded by arithmetic -- it is here so the ceiling table is complete and so a
#: fourth dataset appearing in the enum does not silently widen a plan.
MAX_DATASETS: Final = 3

#: At most four pages walked per (subject, dataset).
#:
#: Pagination is how a bounded request becomes an unbounded one. Four pages at the
#: default page size is a sample; forty is a download. A qualification run that
#: needs more pages than this is asking a question about volume, which is Q8's
#: empirical verification and is not authorized.
MAX_PAGES_PER_REQUEST: Final = 4

#: The arithmetic ceiling on requests: subjects x datasets x pages.
#:
#: Stated as its own constant rather than computed at the call site, so the number
#: a reviewer checks is the number the code enforces.
MAX_REQUESTS: Final = MAX_SUBJECTS * MAX_DATASETS * MAX_PAGES_PER_REQUEST

#: The largest single response a plan may accept, inherited from the transport's
#: own default rather than restated.
#:
#: Tying it to :data:`~kalpamani.data.ingest.sharadar.transport.DEFAULT_MAX_RESPONSE_BYTES`
#: means the plan cannot authorize a response the transport would refuse, and the
#: two cannot drift apart in a later edit.
MAX_RESPONSE_BYTES: Final = DEFAULT_MAX_RESPONSE_BYTES

#: The largest total a whole run may accumulate.
#:
#: A per-response ceiling bounds one answer; without a run ceiling, ninety-six
#: maximum-size answers are still authorized. This is the number that makes a
#: run's cost knowable in advance, and it is enforced as bytes are published
#: rather than estimated beforehand.
MAX_RUN_BYTES: Final = 512 * 1024 * 1024

#: The largest total number of retries a run may authorize across every request.
#:
#: The vendor publishes no rate limit (`PSR-SHD-109`), and *no documented limit is
#: not an absent limit*. A run that may retry every request to the client's
#: ceiling can multiply its request count several-fold, which is how a courteous
#: integration becomes a rate-limit incident on its first real use.
MAX_RETRY_BUDGET: Final = 32

#: The only profile Sharadar-derived evidence may be used under (ADR-0010).
PERMITTED_PROFILE: Final = InformationSetProfile.PROVIDER_REALISTIC_PIT

#: The profile Sharadar-derived evidence may never be represented as. Q7 is
#: publicly unresolved: no first-party page states whether the daily bars are
#: officially disseminated or provider-aggregated, so the only safe reading is
#: the conservative one.
REFUSED_PROFILE: Final = InformationSetProfile.PUBLIC_PIT

#: Datasets this slice will never plan. Named individually rather than left to
#: "anything not in the enum", because a name a reader recognises is a name a
#: reviewer can check against the phase that owns it.
OUT_OF_PHASE_DATASETS: Final[frozenset[str]] = frozenset(
    {
        "fundamentals",
        "daily",
        "sf1",
        "sf2",
        "sf3",
        "sf3a",
        "sf3b",
        "sfp",
        "events",
        "metrics",
        "indicators",
        "sp500",
        "institutions",
        "insiders",
        "holdings",
        "funds",
    }
)

#: Query parameters a plan may never carry. A superset of the request builder's
#: own refusal list, restated here because a plan is refused *before* a request is
#: built and the earlier refusal is the one that costs nothing.
UNSUPPORTED_PLAN_PARAMETERS: Final[frozenset[str]] = frozenset(
    {"years", "fields", "sort", "lastupdated", "lastupdated.gte", "columns", "order", "qopts"}
)

#: What a qualification subject is allowed to look like. Identical in spirit to
#: the request builder's grammar; restated so a plan is refused at construction
#: rather than at request time.
_SUBJECT: Final = re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")

#: The canonical dataset ordering for generated requests. Snapshot metadata first,
#: then prices, then corporate actions -- a fixed sequence so two plans holding the
#: same datasets emit the same request order regardless of how they were built.
CANONICAL_DATASET_ORDER: Final[tuple[SharadarDataset, ...]] = (
    SharadarDataset.TICKERS,
    SharadarDataset.STOCKS,
    SharadarDataset.ACTIONS,
)


class QualificationDefect(StrEnum):
    """Why a plan was refused. A closed vocabulary, so nothing caller-supplied
    can reach a message.

    Deliberately structural: every member names a rule of the plan model, never a
    value. A defect cannot carry a ticker, a window, a URL or a payload, because
    there is no member shaped to hold one.
    """

    SUBJECT_MISSING = "SUBJECT_MISSING"
    SUBJECT_MALFORMED = "SUBJECT_MALFORMED"
    SUBJECT_DUPLICATED = "SUBJECT_DUPLICATED"
    DATASET_UNKNOWN = "DATASET_UNKNOWN"
    DATASET_OUT_OF_PHASE = "DATASET_OUT_OF_PHASE"
    DATASET_DUPLICATED = "DATASET_DUPLICATED"
    DATASET_MISSING = "DATASET_MISSING"
    WINDOW_REQUIRED = "WINDOW_REQUIRED"
    WINDOW_FORBIDDEN = "WINDOW_FORBIDDEN"
    WINDOW_CONFLICTING = "WINDOW_CONFLICTING"
    WINDOW_MALFORMED = "WINDOW_MALFORMED"
    PARAMETER_UNSUPPORTED = "PARAMETER_UNSUPPORTED"
    LIMIT_EXCEEDS_CEILING = "LIMIT_EXCEEDS_CEILING"
    LIMIT_MALFORMED = "LIMIT_MALFORMED"
    RETRY_BUDGET_EXCEEDED = "RETRY_BUDGET_EXCEEDED"
    PLAN_MALFORMED = "PLAN_MALFORMED"
    PROFILE_REFUSED = "PROFILE_REFUSED"
    IDENTITY_MALFORMED = "IDENTITY_MALFORMED"


class QualificationPlanError(PointInTimeError):
    """A plan was refused, described only by a closed defect code.

    **Assembled from a vocabulary, not filtered afterwards.** There is no
    parameter here for a ticker, a window, a URL, a response body or an
    originating exception, so none of them has a route into a message, a log line
    or a traceback.
    """

    __slots__ = ("defect",)

    def __init__(self, defect: QualificationDefect) -> None:
        """Carry one defect. Nothing else has a home here."""
        self.defect = closed_member(QualificationDefect, defect) or (
            QualificationDefect.PLAN_MALFORMED
        )
        super().__init__(f"sharadar qualification plan refused: {self.defect.value}")


def _refuse(defect: QualificationDefect) -> QualificationPlanError:
    return QualificationPlanError(defect)


def refuse_public_pit(profile: InformationSetProfile) -> InformationSetProfile:
    """``profile`` if Sharadar evidence may be used under it, else a refusal.

    Q7 is ``PUBLICLY_UNRESOLVED`` (ADR-0010): no first-party page states whether
    the daily bars are officially disseminated or provider-aggregated. An
    unresolved origin has exactly one safe classification, so this function admits
    :data:`PERMITTED_PROFILE` and nothing else -- **``PUBLIC_PIT`` in particular**.

    Written as a function rather than a comment because a rule that has to be
    remembered is a rule that will be forgotten at the one call site that matters.

    Raises:
        QualificationPlanError: ``PROFILE_REFUSED`` for ``PUBLIC_PIT`` and for
            every other profile, including one that is not a member at all.
    """
    resolved = closed_member(InformationSetProfile, profile)
    if resolved is not PERMITTED_PROFILE:
        raise _refuse(QualificationDefect.PROFILE_REFUSED) from None
    return resolved


def _exact_str(value: object) -> str:
    """``value`` as an exact plain ``str``, or a refusal.

    A ``str`` subclass can override ``__eq__``, ``__hash__`` and ``__str__``, so a
    subject that passed a grammar check could compare equal to something else
    afterwards. Copying into a plain ``str`` ends that.
    """
    if type(value) is not str:
        raise _refuse(QualificationDefect.SUBJECT_MALFORMED) from None
    return str(value)


@dataclass(frozen=True, slots=True)
class QualificationSubject:
    """One explicitly supplied subject of a qualification run.

    **There is no default.** A qualification run measures named things; a default
    symbol would mean a run that nobody chose the subject of, and a compiled-in
    real ticker would put a listed security into this repository for no reason.
    """

    ticker: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so ``ticker`` cannot be overridden after validation."""
        raise _refuse(QualificationDefect.SUBJECT_MALFORMED) from None

    def __post_init__(self) -> None:
        """Hold the subject to the wire grammar, as an exact plain string."""
        ticker = _exact_str(self.ticker)
        if not _SUBJECT.match(ticker):
            raise _refuse(QualificationDefect.SUBJECT_MALFORMED) from None
        object.__setattr__(self, "ticker", ticker)


@dataclass(frozen=True, slots=True, kw_only=True)
class DatasetPlan:
    """What one dataset is asked for, across every subject.

    ``window`` is required on a windowed dataset and forbidden on the snapshot
    one, which is the request builder's rule enforced a step earlier so a bad plan
    costs nothing.
    """

    dataset: SharadarDataset
    window: DateWindow | None = None
    page_limit: int = 500
    max_pages: int = 1

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a stand-in could present a dataset never validated."""
        raise _refuse(QualificationDefect.PLAN_MALFORMED) from None

    def __post_init__(self) -> None:
        """Normalise the dataset and enforce the window and pagination rules."""
        if type(self.dataset) is str and self.dataset in OUT_OF_PHASE_DATASETS:
            # Named before the general unknown-member refusal purely so the
            # failure says *why*: this is a real vendor table owned by a later
            # phase, not a typo.
            raise _refuse(QualificationDefect.DATASET_OUT_OF_PHASE) from None
        dataset = closed_member(SharadarDataset, self.dataset)
        if dataset is None:
            raise _refuse(QualificationDefect.DATASET_UNKNOWN) from None
        object.__setattr__(self, "dataset", dataset)

        if self.window is not None and type(self.window) is not DateWindow:
            raise _refuse(QualificationDefect.WINDOW_MALFORMED) from None
        windowed = dataset in WINDOWED_DATASETS
        if windowed and self.window is None:
            raise _refuse(QualificationDefect.WINDOW_REQUIRED) from None
        if not windowed and self.window is not None:
            raise _refuse(QualificationDefect.WINDOW_FORBIDDEN) from None

        if type(self.page_limit) is not int or not 1 <= self.page_limit <= MAX_PAGE_LIMIT:
            raise _refuse(QualificationDefect.LIMIT_MALFORMED) from None
        if type(self.max_pages) is not int or self.max_pages < 1:
            raise _refuse(QualificationDefect.LIMIT_MALFORMED) from None
        if self.max_pages > MAX_PAGES_PER_REQUEST:
            raise _refuse(QualificationDefect.LIMIT_EXCEEDS_CEILING) from None

    def pages(self) -> tuple[Page, ...]:
        """Every page this dataset plan walks, in ascending offset order."""
        first = Page(limit=self.page_limit, skip=0)
        walk = [first]
        for _ in range(self.max_pages - 1):
            walk.append(walk[-1].advanced())
        return tuple(walk)


@dataclass(frozen=True, slots=True, kw_only=True)
class QualificationLimits:
    """The run-level ceilings a caller may lower and may never raise.

    Every field is compared against the module constant of the same meaning, so a
    plan that asks for more than the compiled bound is refused rather than
    clamped. Clamping would let a plan claim a budget it does not have and then
    behave differently from what it says.
    """

    max_subjects: int = MAX_SUBJECTS
    max_datasets: int = MAX_DATASETS
    max_requests: int = MAX_REQUESTS
    max_pages_per_request: int = MAX_PAGES_PER_REQUEST
    max_response_bytes: int = MAX_RESPONSE_BYTES
    max_run_bytes: int = MAX_RUN_BYTES
    retry_budget: int = MAX_RETRY_BUDGET

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so a ceiling cannot be overridden upward."""
        raise _refuse(QualificationDefect.PLAN_MALFORMED) from None

    def __post_init__(self) -> None:
        """Check every field is an exact positive ``int`` at or below its ceiling."""
        ceilings = (
            (self.max_subjects, MAX_SUBJECTS),
            (self.max_datasets, MAX_DATASETS),
            (self.max_requests, MAX_REQUESTS),
            (self.max_pages_per_request, MAX_PAGES_PER_REQUEST),
            (self.max_response_bytes, MAX_RESPONSE_BYTES),
            (self.max_run_bytes, MAX_RUN_BYTES),
            (self.retry_budget, MAX_RETRY_BUDGET),
        )
        for value, ceiling in ceilings:
            # Exact int: `True` is an int in Python, and a max_subjects of True
            # would silently mean one.
            if type(value) is not int:
                raise _refuse(QualificationDefect.LIMIT_MALFORMED) from None
            if value < 0:
                raise _refuse(QualificationDefect.LIMIT_MALFORMED) from None
            if value > ceiling:
                raise _refuse(QualificationDefect.LIMIT_EXCEEDS_CEILING) from None
        # A retry budget of zero is a legitimate choice -- no retries at all. Every
        # other ceiling describes a quantity a run must be able to have at least
        # one of, so zero there is a plan that cannot do anything.
        for value, _ in ceilings[:-1]:
            if value < 1:
                raise _refuse(QualificationDefect.LIMIT_MALFORMED) from None


#: A run identity is a path segment and a metadata field. Held to a grammar here
#: so a malformed one is refused before it can reach an object key.
_IDENTITY: Final = re.compile(r"^[a-z0-9][a-z0-9._\-]{0,63}$")


@dataclass(frozen=True, slots=True, kw_only=True)
class QualificationPlan:
    """A complete, bounded, deterministic description of one qualification run.

    **Constructing this reaches nothing.** No client, no transport, no store, no
    credential and no bucket appears in the type. A plan is what a future
    authorized composition root would hand to
    :class:`~kalpamani.data.ingest.sharadar.runtime.QualificationRuntime` along
    with the dependencies it built.
    """

    subjects: tuple[QualificationSubject, ...]
    datasets: tuple[DatasetPlan, ...]
    response_format: ResponseFormat = ResponseFormat.CSV
    limits: QualificationLimits = field(default_factory=QualificationLimits)
    profile: InformationSetProfile = PERMITTED_PROFILE
    ingestion_run_id: str = "qualification-run"
    source_schema_version: str = "sharadar-qualification-v0"
    is_backfill: bool = False

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a stand-in could present requests never validated."""
        raise _refuse(QualificationDefect.PLAN_MALFORMED) from None

    def __post_init__(self) -> None:
        """Validate the whole plan. Nothing is left to be discovered at run time."""
        subjects = self._frozen_subjects()
        datasets = self._frozen_datasets()

        if type(self.limits) is not QualificationLimits:
            raise _refuse(QualificationDefect.PLAN_MALFORMED) from None
        response_format = closed_member(ResponseFormat, self.response_format)
        if response_format is None:
            raise _refuse(QualificationDefect.PLAN_MALFORMED) from None
        object.__setattr__(self, "response_format", response_format)
        object.__setattr__(self, "profile", refuse_public_pit(self.profile))

        if type(self.is_backfill) is not bool:
            raise _refuse(QualificationDefect.PLAN_MALFORMED) from None
        for identity in (self.ingestion_run_id, self.source_schema_version):
            if type(identity) is not str or not _IDENTITY.match(identity):
                raise _refuse(QualificationDefect.IDENTITY_MALFORMED) from None

        if len(subjects) > self.limits.max_subjects:
            raise _refuse(QualificationDefect.LIMIT_EXCEEDS_CEILING) from None
        if len(datasets) > self.limits.max_datasets:
            raise _refuse(QualificationDefect.LIMIT_EXCEEDS_CEILING) from None
        for plan in datasets:
            if plan.max_pages > self.limits.max_pages_per_request:
                raise _refuse(QualificationDefect.LIMIT_EXCEEDS_CEILING) from None

        request_count = len(subjects) * sum(plan.max_pages for plan in datasets)
        if request_count > self.limits.max_requests:
            raise _refuse(QualificationDefect.LIMIT_EXCEEDS_CEILING) from None

    def _frozen_subjects(self) -> tuple[QualificationSubject, ...]:
        """Copy the subjects into a fresh plain tuple, refusing duplicates."""
        if type(self.subjects) is not tuple:
            raise _refuse(QualificationDefect.PLAN_MALFORMED) from None
        if not self.subjects:
            raise _refuse(QualificationDefect.SUBJECT_MISSING) from None
        for subject in self.subjects:
            if type(subject) is not QualificationSubject:
                raise _refuse(QualificationDefect.SUBJECT_MALFORMED) from None
        tickers = [subject.ticker for subject in self.subjects]
        if len(set(tickers)) != len(tickers):
            # Two identical subjects would produce two identical requests, and the
            # second publication would be an idempotent no-op that looks like
            # progress. Refuse the ambiguity rather than report it later.
            raise _refuse(QualificationDefect.SUBJECT_DUPLICATED) from None
        frozen = tuple(QualificationSubject(ticker) for ticker in tickers)
        object.__setattr__(self, "subjects", frozen)
        return frozen

    def _frozen_datasets(self) -> tuple[DatasetPlan, ...]:
        """Copy the dataset plans, refusing duplicates and conflicting windows."""
        if type(self.datasets) is not tuple:
            raise _refuse(QualificationDefect.PLAN_MALFORMED) from None
        if not self.datasets:
            raise _refuse(QualificationDefect.DATASET_MISSING) from None
        for plan in self.datasets:
            if type(plan) is not DatasetPlan:
                raise _refuse(QualificationDefect.PLAN_MALFORMED) from None
        named = [plan.dataset for plan in self.datasets]
        if len(set(named)) != len(named):
            # Two entries for one dataset are either a duplicate or two different
            # windows for the same table. The first is redundant; the second is a
            # plan that does not say what range it covers.
            windows = {(plan.dataset, plan.window) for plan in self.datasets}
            defect = (
                QualificationDefect.WINDOW_CONFLICTING
                if len(windows) != len(set(named))
                else QualificationDefect.DATASET_DUPLICATED
            )
            raise _refuse(defect) from None
        frozen = tuple(self.datasets)
        object.__setattr__(self, "datasets", frozen)
        return frozen

    @property
    def request_count(self) -> int:
        """Exactly how many requests :meth:`requests` will yield."""
        return len(self.subjects) * sum(plan.max_pages for plan in self.datasets)

    def requests(self) -> tuple[SharadarRequest, ...]:
        """Every request, in one canonical order that does not depend on input order.

        Ordered by dataset (:data:`CANONICAL_DATASET_ORDER`), then subject
        lexicographically, then page offset ascending. Two plans holding the same
        subjects and dataset plans therefore emit byte-identical request
        sequences, which is what makes a resumed run comparable to the run it
        resumes.

        Building a request constructs no URL and touches no credential: that
        happens inside the client, at fetch time, and the string never leaves it.
        """
        by_dataset = {plan.dataset: plan for plan in self.datasets}
        tickers = sorted(subject.ticker for subject in self.subjects)
        built: list[SharadarRequest] = []
        for dataset in CANONICAL_DATASET_ORDER:
            plan = by_dataset.get(dataset)
            if plan is None:
                continue
            for ticker in tickers:
                for page in plan.pages():
                    built.append(
                        SharadarRequest(
                            dataset=dataset,
                            ticker=ticker,
                            response_format=self.response_format,
                            page=page,
                            window=plan.window,
                        )
                    )
        return tuple(built)


def refuse_unsupported_parameters(names: object) -> None:
    """Refuse any query parameter this slice will not plan.

    Called by the plan-check command and by the runtime before the first fetch, so
    a caller assembling parameters by hand meets the same rule the request builder
    applies -- one step earlier, where the refusal is free.

    Raises:
        QualificationPlanError: ``PARAMETER_UNSUPPORTED`` for ``years`` (a
            table-wide bulk download), ``fields``/``sort``/``columns``/``order``
            (which make two requests for one range return differently-shaped
            bytes, and Bronze identity *is* the bytes), and ``lastupdated``
            (incremental sync, which is production ingestion).
    """
    if not isinstance(names, (list, tuple, set, frozenset)):
        raise _refuse(QualificationDefect.PLAN_MALFORMED) from None
    for name in names:
        if type(name) is not str:
            raise _refuse(QualificationDefect.PLAN_MALFORMED) from None
        if name.lower() in UNSUPPORTED_PLAN_PARAMETERS:
            raise _refuse(QualificationDefect.PARAMETER_UNSUPPORTED) from None


def refuse_retry_budget(*, request_count: int, max_attempts: int, budget: int) -> None:
    """Refuse a plan whose worst case exceeds its declared retry budget.

    ``max_attempts`` is read from the injected client, so the budget is a bound on
    what will actually happen rather than a number written down beside it. The
    worst case is every request exhausting its attempts:
    ``request_count * (max_attempts - 1)`` retries.

    Raises:
        QualificationPlanError: ``RETRY_BUDGET_EXCEEDED`` when the worst case
            exceeds the budget, or ``LIMIT_MALFORMED`` for a non-exact or
            out-of-range attempt count.
    """
    if type(request_count) is not int or type(max_attempts) is not int or type(budget) is not int:
        raise _refuse(QualificationDefect.LIMIT_MALFORMED) from None
    if not 1 <= max_attempts <= MAX_ATTEMPTS_CEILING:
        raise _refuse(QualificationDefect.LIMIT_MALFORMED) from None
    if request_count * (max_attempts - 1) > budget:
        raise _refuse(QualificationDefect.RETRY_BUDGET_EXCEEDED) from None


__all__ = [
    "CANONICAL_DATASET_ORDER",
    "MAX_DATASETS",
    "MAX_PAGES_PER_REQUEST",
    "MAX_REQUESTS",
    "MAX_RESPONSE_BYTES",
    "MAX_RETRY_BUDGET",
    "MAX_RUN_BYTES",
    "MAX_SUBJECTS",
    "OUT_OF_PHASE_DATASETS",
    "PERMITTED_PROFILE",
    "REFUSED_PROFILE",
    "UNSUPPORTED_PLAN_PARAMETERS",
    "DatasetPlan",
    "QualificationDefect",
    "QualificationLimits",
    "QualificationPlan",
    "QualificationPlanError",
    "QualificationSubject",
    "refuse_public_pit",
    "refuse_retry_budget",
    "refuse_unsupported_parameters",
]
