"""Silver normalization: verified payloads into versioned, permaticker-identified rows.

**The accepted parser does the parsing.** Every payload goes through
:func:`~kalpamani.data.qualify.sharadar.parser.parse_payload`, with its strict UTF-8,
RFC 4180, required-field, row-count and field-length ceilings; nothing here decodes
vendor bytes on its own. The observed schema digest of every page is compared with the
**pinned accepted set** for its dataset; a digest outside it is ``SCHEMA_UNSTABLE`` and
blocking (ADR-0035 §3.2), because a silently changed column set is not a payload this
build knows how to read.

**Identity is a deterministic function of ``permaticker``** (ADR-0035 §3.5):
``security_id = sharadar:<permaticker>``, never derived from a symbol. ``stocks`` and
``actions`` carry no ``permaticker`` and are keyed to the vendor's *current* symbol, so
each of their rows is mapped through the ``tickers`` snapshot **acquired in the same
run**, and the mapping must be one-to-one for every symbol present -- a symbol with zero
or two ``permaticker`` values in that snapshot is blocking for that symbol's rows and
for nothing else.

**Versions are never overwritten** (ADR-0035 §3.2). A row *version* is one distinct
content for one row key; the first acquisition delivering it fixes its
``system_first_seen_time``, later deliveries of identical bytes only count, and a later
acquisition delivering different bytes yields a **new revision** with its own first-seen
instant beside the earlier one. Two different contents for one key inside one
acquisition run are a structural conflict, and blocking. Acquisitions are consumed in
retrieval order, so revision sequences are deterministic for a given input set.

**Pagination is admitted per group before anything is consolidated** (pagination v2,
ADR-0053 §11.2, §13.3). Every (run, dataset, window, predicate) group of parsed pages
must be exactly one data page at offset zero whose raw row count and schema digest are
the ones its record and locator entry recorded, complete by a short page or by a passed
completion probe; a second page, a full page without a passed probe, a page over its
governed limit, or evidence that disagrees with the parsed page refuses the input
(:mod:`~kalpamani.data.production.sharadar.pagination`).

**The tickers group is the ``table=stocks`` group, and ``permaticker`` is its identity**
(ADR-0053 §11.3). A tickers page acquired without exactly that predicate is refused, and
a row whose delivered ``table`` value is not the predicate's contradicts the request and
refuses the input; within the group a repeated ``permaticker`` with differing content
is the structural conflict it always was.

**Every actions row is one event under ``sharadar-actions-event-identity/v1``** (ADR-0053
§12). The Silver identity of an actions row is the resolved ``security_id`` plus the
canonical full-row event identity of every governed field; two rows sharing ticker,
date and action stay distinct when any other field differs; an exact duplicate row
within one run and a digest collision are refused, never silently deduplicated.

**A completed acquisition is completion of its request plan, not proof of market
coverage.** The rows normalized here are the rows the vendor delivered to those
requests; the census and completeness checks say how much of the calendar they cover,
and nothing here claims more -- and an admitted page shape establishes neither vendor
completeness nor snapshot consistency.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.ingest.sharadar.datasets import (
    PROVIDER,
    TICKERS_TABLE_PARAMETER,
    SharadarDataset,
)
from kalpamani.data.production.sharadar.actions_identity import (
    ACTIONS_IDENTITY_CONTRACT_ID,
    ActionsIdentityDefect,
    ActionsIdentityRefusalError,
    EventAdmission,
)
from kalpamani.data.production.sharadar.build_inputs import AcquiredPage, VerifiedBuildInputs
from kalpamani.data.production.sharadar.pagination import (
    PaginationDefect,
    PaginationError,
    PaginationSummary,
    admit_pagination,
)
from kalpamani.data.production.sharadar.plan import PAYLOAD_CEILING_BYTES, TICKERS_PREDICATE
from kalpamani.data.production.sharadar.schema_observation import (
    OBSERVED_DATASETS,
    DatasetObservation,
    SchemaObservation,
)
from kalpamani.data.qualify.sharadar.parser import ParsedPage, ParseError, parse_payload

#: The Silver normalization version. Part of every manifest and of the build ``run_id``.
#: v3: pagination v2 admission, the tickers predicate group, the actions event identity.
SILVER_NORMALIZATION_VERSION: Final = "sharadar-silver-v3"
#: The actions identity contract every Silver actions row is keyed under.
ACTIONS_IDENTITY_VERSION: Final = ACTIONS_IDENTITY_CONTRACT_ID

#: The identity namespace. A ``security_id`` is ``sharadar:<permaticker>`` and nothing else.
SECURITY_ID_PREFIX: Final = PROVIDER + ":"

#: Column names this normalization reads, by dataset. Anything else delivered is
#: carried in the row's fields untouched and consumed by nothing.
TICKERS_COLUMNS: Final = (
    "permaticker",
    "ticker",
    "exchange",
    "category",
    "isdelisted",
    "sector",
    "industry",
    "firstpricedate",
    "lastpricedate",
    "lastupdated",
)
STOCKS_COLUMNS: Final = (
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "closeadj",
    "closeunadj",
    "lastupdated",
)
ACTIONS_COLUMNS: Final = ("date", "action", "ticker", "value", "contraticker")


class SilverDefect(StrEnum):
    """Why normalization refused the whole input. Closed; never a value."""

    PAYLOAD_UNPARSEABLE = "PAYLOAD_UNPARSEABLE"
    SCHEMA_UNSTABLE = "SCHEMA_UNSTABLE"
    DELIVERY_TRUNCATED = "DELIVERY_TRUNCATED"
    PAGINATION_UNSUPPORTED = "PAGINATION_UNSUPPORTED"
    PAGINATION_INCONSISTENT = "PAGINATION_INCONSISTENT"
    PAGE_OVER_LIMIT = "PAGE_OVER_LIMIT"
    COMPLETION_UNPROVEN = "COMPLETION_UNPROVEN"
    ROW_CONFLICT_IN_RUN = "ROW_CONFLICT_IN_RUN"
    IDENTITY_SNAPSHOT_MISSING = "IDENTITY_SNAPSHOT_MISSING"
    ROW_KEY_MALFORMED = "ROW_KEY_MALFORMED"
    DATASET_UNKNOWN = "DATASET_UNKNOWN"
    TICKERS_PREDICATE_MISSING = "TICKERS_PREDICATE_MISSING"
    TICKERS_TABLE_CONTRADICTED = "TICKERS_TABLE_CONTRADICTED"
    ACTIONS_SCHEMA_NOT_GOVERNED = "ACTIONS_SCHEMA_NOT_GOVERNED"
    ACTIONS_ROW_MALFORMED = "ACTIONS_ROW_MALFORMED"
    ACTIONS_DUPLICATE_EVENT = "ACTIONS_DUPLICATE_EVENT"
    ACTIONS_IDENTITY_COLLISION = "ACTIONS_IDENTITY_COLLISION"


class SilverError(Exception):
    """One closed defect, raised ``from None``.

    ``observation`` is the per-dataset schema observation collected before a
    ``SCHEMA_UNSTABLE`` refusal (proposed ADR-0045, Route B) -- evidence for owner
    review, never an accepted set -- and ``None`` for every other defect.
    """

    __slots__ = ("defect", "observation")

    def __init__(
        self, defect: SilverDefect, *, observation: SchemaObservation | None = None
    ) -> None:
        if type(defect) is not SilverDefect:
            raise TypeError("defect must be an exact SilverDefect member")
        if observation is not None and type(observation) is not SchemaObservation:
            raise TypeError("observation must be an exact SchemaObservation or None")
        if observation is not None and defect is not SilverDefect.SCHEMA_UNSTABLE:
            raise ValueError("an observation accompanies a schema refusal only")
        self.defect = defect
        self.observation = observation
        super().__init__(f"silver normalization refused: {defect.value}")


def _refuse(defect: SilverDefect) -> SilverError:
    return SilverError(defect)


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptedSchemas:
    """The pinned accepted schema digests per dataset. Configuration, versioned."""

    version: str
    digests: dict[str, frozenset[str]]

    def __post_init__(self) -> None:
        if type(self.version) is not str or not self.version:
            raise ValueError("an accepted-schema set carries a version")
        for dataset, digests in self.digests.items():
            if dataset not in {member.value for member in SharadarDataset}:
                raise ValueError("accepted schemas name only the three datasets")
            for digest in digests:
                if type(digest) is not str or len(digest) != 64:
                    raise ValueError("an accepted schema digest is 64 hex characters")

    def admits(self, dataset: str, digest: str) -> bool:
        """Whether ``digest`` is accepted for ``dataset``."""
        return digest in self.digests.get(dataset, frozenset())


@dataclass(frozen=True, slots=True, kw_only=True)
class Provenance:
    """Where one row version came from, exactly."""

    run_id: str
    ordinal: int
    payload_sha256: str
    schema_digest: str
    acquisition_mode: str
    retrieved_at: datetime

    def document(self) -> dict[str, Any]:
        """The closed provenance document carried by every Silver row."""
        return {
            "acquisition_id": self.run_id,
            "request_ordinal": self.ordinal,
            "source_digest": self.payload_sha256,
            "schema_digest": self.schema_digest,
            "acquisition_mode": self.acquisition_mode,
            "retrieved_at": self.retrieved_at.isoformat(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RowVersion:
    """One revision of one row key: a **transition** in the chronology of observations.

    **Private material**: never rendered.

    A revision begins when an observation delivers content different from the
    content the previous observation of the same key delivered. Consecutive
    observations of unchanged content extend the current revision's tenure and are
    counted; they create no false change. A **return to earlier content is a new
    revision** with its own sequence and its own instant, so ``A -> B -> A`` is three
    revisions and the last of them is current after its own observation -- content
    identity (``content_sha256``, ``content_first_seen_time``) is kept apart from
    the chronology (``revision_sequence``, ``system_first_seen_time``).

    ``system_first_seen_time`` is the retrieval instant of the observation that made
    this revision current -- the P-2 bound for **this revision**; a returning
    revision's bound is its own observation's instant, never the instant the same
    content was first seen. ``content_first_seen_time`` is the earliest observation
    of these bytes for this key, whichever revision delivered them.
    ``observed_at`` holds every observation of the revision, so a document served at
    an earlier ``as_of`` can be restricted to what was observed by then.
    ``redelivery_gaps`` names later runs (with the instant each was seen) whose
    request window covered the key and that did not deliver it -- the vendor's
    actions table carries no event identity, so a correction to a key field and a
    separate event cannot be told apart, and the gap is recorded rather than read
    as a deletion.
    """

    dataset: str
    row_key: tuple[str, ...]
    security_id: str
    symbol: str
    revision_sequence: int
    content_sha256: str
    fields: dict[str, str | None]
    provenance: Provenance
    system_first_seen_time: datetime
    content_first_seen_time: datetime
    observed_at: tuple[datetime, ...]
    redelivery_gaps: tuple[tuple[str, datetime], ...] = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass could render the fields."""
        raise TypeError("RowVersion may not be subclassed")

    def __repr__(self) -> str:
        """Dataset and revision only. **Never a field value, never an identity.**"""
        return f"RowVersion(dataset={self.dataset!r}, revision={self.revision_sequence})"

    @property
    def provider_last_updated_date(self) -> str | None:
        """The vendor's ``lastupdated`` stamp, carried as evidence and never as a bound."""
        return self.fields.get("lastupdated")

    @property
    def observation_count(self) -> int:
        """How many observations this revision's tenure holds, in total."""
        return len(self.observed_at)

    @property
    def last_observed_at(self) -> datetime:
        """The latest observation of this revision, in total."""
        return max(self.observed_at)

    def observations_through(self, cutoff: datetime) -> tuple[datetime, ...]:
        """The observations of this revision at or before ``cutoff`` -- what a build at
        that instant could have held, and all a document served at it may record."""
        return tuple(when for when in self.observed_at if when <= cutoff)

    def gaps_through(self, cutoff: datetime) -> tuple[str, ...]:
        """The covering runs seen at or before ``cutoff`` that did not deliver this key."""
        return tuple(run_id for run_id, seen_at in self.redelivery_gaps if seen_at <= cutoff)

    @property
    def is_return(self) -> bool:
        """Whether this revision returned to content an earlier revision of the key held."""
        return self.content_first_seen_time < self.system_first_seen_time


@dataclass(frozen=True, slots=True, kw_only=True)
class SilverDataset:
    """Every row version of one dataset, in canonical order, with identity findings."""

    dataset: str
    rows: tuple[RowVersion, ...]
    schema_digests: tuple[str, ...]
    duplicate_rows: int
    unmapped_symbols: int
    ambiguous_symbols: int
    rows_excluded_for_identity: int

    def __repr__(self) -> str:
        """Counts only."""
        return f"SilverDataset(dataset={self.dataset!r}, rows={len(self.rows)})"


@dataclass(frozen=True, slots=True, kw_only=True)
class SilverLayer:
    """The three normalized datasets of one build."""

    tickers: SilverDataset
    stocks: SilverDataset
    actions: SilverDataset
    schemas_version: str
    pagination: PaginationSummary

    def by_dataset(self, dataset: str) -> SilverDataset:
        """The dataset by its vendor name."""
        return {
            SharadarDataset.TICKERS.value: self.tickers,
            SharadarDataset.STOCKS.value: self.stocks,
            SharadarDataset.ACTIONS.value: self.actions,
        }[dataset]


def security_id_for(permaticker: str) -> str:
    """The deterministic identity of one ``permaticker``. Never from a symbol."""
    if type(permaticker) is not str or not permaticker.isdigit():
        raise _refuse(SilverDefect.ROW_KEY_MALFORMED)
    return SECURITY_ID_PREFIX + permaticker


def _fields(page: ParsedPage, row: tuple[str | None, ...]) -> dict[str, str | None]:
    return dict(zip(page.header, row, strict=True))


def _content_digest(fields: dict[str, str | None]) -> str:
    return sha256_hex(canonical_bytes({name: fields[name] for name in sorted(fields)}))


def _order_key(page: AcquiredPage) -> tuple[datetime, str, int]:
    return (page.retrieved_at, page.run_id, page.ordinal)


def _parse_only(page: AcquiredPage) -> ParsedPage:
    try:
        dataset = SharadarDataset(page.dataset)
    except ValueError:
        raise _refuse(SilverDefect.DATASET_UNKNOWN) from None
    try:
        # The production ceilings (ADR-0053 §13.2): the whole body under 32 MiB, the
        # page under its own governed limit. A body over either is refused, never cut.
        return parse_payload(
            page.payload,
            dataset=dataset,
            max_bytes=PAYLOAD_CEILING_BYTES,
            max_rows=page.page_limit,
        )
    except ParseError:
        raise _refuse(SilverDefect.PAYLOAD_UNPARSEABLE) from None


def observe_schemas(pages: Iterable[AcquiredPage]) -> SchemaObservation:
    """The per-dataset header digests of every page that parses, and the page accounting.

    Nothing here consults an accepted set: the observation is what the deliveries
    *say*, recorded before admission decides anything. A page that does not parse is
    counted and unobserved, which makes the observation **partial** rather than
    letting an unparseable header vanish into a claim of completeness.
    """
    digests: dict[str, set[str]] = {name: set() for name in OBSERVED_DATASETS}
    parsed_count: dict[str, int] = dict.fromkeys(OBSERVED_DATASETS, 0)
    total: dict[str, int] = dict.fromkeys(OBSERVED_DATASETS, 0)
    for page in pages:
        if page.dataset not in total:
            continue
        total[page.dataset] += 1
        try:
            parsed = _parse_only(page)
        except SilverError:
            continue
        parsed_count[page.dataset] += 1
        digests[page.dataset].add(parsed.schema_digest)
    return SchemaObservation(
        datasets={
            name: DatasetObservation(
                digests=tuple(sorted(digests[name])),
                pages_parsed=parsed_count[name],
                pages_total=total[name],
            )
            for name in OBSERVED_DATASETS
        }
    )


def _parse(page: AcquiredPage, *, schemas: AcceptedSchemas) -> ParsedPage:
    parsed = _parse_only(page)
    if not schemas.admits(page.dataset, parsed.schema_digest):
        raise _refuse(SilverDefect.SCHEMA_UNSTABLE)
    return parsed


#: The pagination gate's closed members, mapped one to one onto this module's. Total;
#: a test asserts it, so a member added to the gate cannot escape into an unmapped raise.
_PAGINATION_DEFECTS: Final[dict[PaginationDefect, SilverDefect]] = {
    PaginationDefect.PAGE_OVER_LIMIT: SilverDefect.PAGE_OVER_LIMIT,
    PaginationDefect.PAGINATION_INCONSISTENT: SilverDefect.PAGINATION_INCONSISTENT,
    PaginationDefect.DELIVERY_TRUNCATED: SilverDefect.DELIVERY_TRUNCATED,
    PaginationDefect.PAGINATION_UNSUPPORTED: SilverDefect.PAGINATION_UNSUPPORTED,
    PaginationDefect.COMPLETION_UNPROVEN: SilverDefect.COMPLETION_UNPROVEN,
}

#: The actions identity module's closed members, mapped one to one onto this module's.
#: Total; a test asserts it.
_ACTIONS_DEFECTS: Final[dict[ActionsIdentityDefect, SilverDefect]] = {
    ActionsIdentityDefect.ACTIONS_SCHEMA_NOT_GOVERNED: SilverDefect.ACTIONS_SCHEMA_NOT_GOVERNED,
    ActionsIdentityDefect.ACTIONS_REQUIRED_FIELD_NULL: SilverDefect.ACTIONS_ROW_MALFORMED,
    ActionsIdentityDefect.ACTIONS_DATE_MALFORMED: SilverDefect.ACTIONS_ROW_MALFORMED,
    ActionsIdentityDefect.ACTIONS_VALUE_NOT_DECIMAL: SilverDefect.ACTIONS_ROW_MALFORMED,
    ActionsIdentityDefect.ACTIONS_DUPLICATE_EVENT: SilverDefect.ACTIONS_DUPLICATE_EVENT,
    ActionsIdentityDefect.ACTIONS_IDENTITY_COLLISION: SilverDefect.ACTIONS_IDENTITY_COLLISION,
}


def _admit_pages(pages: list[tuple[AcquiredPage, ParsedPage]]) -> PaginationSummary:
    """The pagination gate: every (run, dataset, window, predicate) group in the v2 shape.

    Run after integrity, provenance and parsing, and **before** symbol mapping, revision
    consolidation and any deduplication, on raw parsed row counts. A refused group
    refuses the whole input.
    """
    try:
        return admit_pagination(pages)
    except PaginationError as error:
        raise _refuse(_PAGINATION_DEFECTS[error.defect]) from None


class _Versions:
    """The observation chronology per key; revisions are its transitions.

    Observations arrive in retrieval order. For each key the current content is
    compared with the observation's content: unchanged extends the current
    revision (counted, never a change); changed opens a new revision. Two different
    contents inside one acquisition run are refused, whatever earlier runs
    delivered.
    """

    __slots__ = ("duplicates", "in_run", "versions")

    def __init__(self) -> None:
        self.versions: dict[tuple[str, ...], list[RowVersion]] = {}
        self.in_run: dict[tuple[tuple[str, ...], str], str] = {}
        self.duplicates = 0

    def observe(
        self,
        *,
        dataset: str,
        row_key: tuple[str, ...],
        security_id: str,
        symbol: str,
        fields: dict[str, str | None],
        page: AcquiredPage,
        parsed: ParsedPage,
    ) -> None:
        digest = _content_digest(fields)
        first = self.in_run.setdefault((row_key, page.run_id), digest)
        if first != digest:
            raise _refuse(SilverDefect.ROW_CONFLICT_IN_RUN)
        existing = self.versions.setdefault(row_key, [])
        if existing and existing[-1].content_sha256 == digest:
            # Unchanged since the previous observation: the current revision's
            # tenure extends and the sighting is counted. No transition, no change.
            current = existing[-1]
            self.duplicates += 1
            existing[-1] = replace(current, observed_at=(*current.observed_at, page.retrieved_at))
            return
        # A transition: new content, or a return to content an earlier revision held.
        # Content identity is looked up across every earlier revision; the revision's
        # own instant is this observation's, never the content's first sighting.
        content_first_seen = min(
            [v.content_first_seen_time for v in existing if v.content_sha256 == digest]
            + [page.retrieved_at]
        )
        existing.append(
            RowVersion(
                dataset=dataset,
                row_key=row_key,
                security_id=security_id,
                symbol=symbol,
                revision_sequence=len(existing),
                content_sha256=digest,
                fields=fields,
                provenance=Provenance(
                    run_id=page.run_id,
                    ordinal=page.ordinal,
                    payload_sha256=page.payload_sha256,
                    schema_digest=parsed.schema_digest,
                    acquisition_mode=page.acquisition_mode,
                    retrieved_at=page.retrieved_at,
                ),
                system_first_seen_time=page.retrieved_at,
                content_first_seen_time=content_first_seen,
                observed_at=(page.retrieved_at,),
            )
        )

    def ordered(self) -> tuple[RowVersion, ...]:
        rows: list[RowVersion] = []
        for key in sorted(self.versions):
            rows.extend(self.versions[key])
        return tuple(rows)

    def mark_redelivery_gaps(
        self, gaps: dict[tuple[str, ...], tuple[tuple[str, datetime], ...]]
    ) -> None:
        """Record on every revision of a key the later covering runs that did not deliver it."""
        for row_key, runs in gaps.items():
            revisions = self.versions.get(row_key)
            if revisions:
                self.versions[row_key] = [replace(v, redelivery_gaps=runs) for v in revisions]


def _snapshot_mapping(
    tickers_pages: list[tuple[AcquiredPage, ParsedPage]],
) -> dict[str, dict[str, set[str]]]:
    """Per run: symbol -> the set of ``permaticker`` values the run's snapshot delivered."""
    mapping: dict[str, dict[str, set[str]]] = {}
    for page, parsed in tickers_pages:
        _require_tickers_predicate(page)
        per_run = mapping.setdefault(page.run_id, {})
        for row in parsed.rows:
            fields = _fields(parsed, row)
            symbol, permaticker = fields.get("ticker"), fields.get("permaticker")
            if symbol is None or permaticker is None:
                continue
            per_run.setdefault(symbol, set()).add(permaticker)
    return mapping


def _require_tickers_predicate(page: AcquiredPage) -> str:
    """The accepted table value a tickers page was acquired under, or a refusal."""
    if tuple(sorted(page.predicate)) != tuple(sorted(TICKERS_PREDICATE)):
        raise _refuse(SilverDefect.TICKERS_PREDICATE_MISSING)
    return dict(page.predicate)[TICKERS_TABLE_PARAMETER]


def _normalize_tickers(pages: list[tuple[AcquiredPage, ParsedPage]]) -> SilverDataset:
    versions = _Versions()
    digests: set[str] = set()
    for page, parsed in sorted(pages, key=lambda item: _order_key(item[0])):
        table = _require_tickers_predicate(page)
        digests.add(parsed.schema_digest)
        for row in parsed.rows:
            fields = _fields(parsed, row)
            permaticker = fields.get("permaticker")
            symbol = fields.get("ticker")
            if permaticker is None or symbol is None:
                raise _refuse(SilverDefect.ROW_KEY_MALFORMED)
            # A delivered ``table`` value that is not the request's predicate is the
            # provider contradicting the filter it was asked for.
            if TICKERS_TABLE_PARAMETER in fields and fields[TICKERS_TABLE_PARAMETER] != table:
                raise _refuse(SilverDefect.TICKERS_TABLE_CONTRADICTED)
            security_id = security_id_for(permaticker)
            versions.observe(
                dataset=SharadarDataset.TICKERS.value,
                row_key=(security_id,),
                security_id=security_id,
                symbol=symbol,
                fields=fields,
                page=page,
                parsed=parsed,
            )
    return SilverDataset(
        dataset=SharadarDataset.TICKERS.value,
        rows=versions.ordered(),
        schema_digests=tuple(sorted(digests)),
        duplicate_rows=versions.duplicates,
        unmapped_symbols=0,
        ambiguous_symbols=0,
        rows_excluded_for_identity=0,
    )


def _window_dates(window: str) -> tuple[date, date] | None:
    """The inclusive date window of one request, or ``None`` for the snapshot."""
    try:
        start, end = (date.fromisoformat(part) for part in window.split("/"))
    except ValueError:
        return None
    return (start, end)


def _redelivery_gaps(
    versions: _Versions,
    *,
    coverage: dict[str, list[tuple[date, date]]],
    delivered: dict[str, set[tuple[str, ...]]],
    run_seen_at: dict[str, datetime],
) -> dict[tuple[str, ...], tuple[tuple[str, datetime], ...]]:
    """Per key, the later runs whose request windows covered its date and did not deliver it.

    **Recorded, never read as a deletion.** The vendor delivers no identity that survives
    a change of content: a stocks bar is keyed by its session date and an actions event
    by its canonical full row, so a key absent from a later covering delivery may be a
    correction (the same underlying fact under a new key), a removal, or a delivery gap;
    nothing accepted distinguishes them. The gap is carried on the key's revisions so a
    consumer can represent the limitation conservatively. The key's date is read from
    the row's own ``date`` field, which every keyed dataset carries.
    """
    gaps: dict[tuple[str, ...], tuple[tuple[str, datetime], ...]] = {}
    for row_key, revisions in versions.versions.items():
        try:
            key_date = date.fromisoformat(str(revisions[0].fields["date"]))
        except (KeyError, ValueError):
            continue
        first_observed = min(v.system_first_seen_time for v in revisions)
        missing = sorted(
            (run_id, run_seen_at[run_id])
            for run_id, windows in coverage.items()
            if run_seen_at[run_id] > first_observed
            and row_key not in delivered.get(run_id, set())
            and any(start <= key_date <= end for start, end in windows)
        )
        if missing:
            gaps[row_key] = tuple(missing)
    return gaps


def _event_identity(
    admissions: dict[str, EventAdmission],
    *,
    page: AcquiredPage,
    parsed: ParsedPage,
    fields: dict[str, str | None],
) -> str:
    """The canonical full-row identity of one actions row, admitted within its run."""
    admission = admissions.setdefault(page.run_id, EventAdmission())
    try:
        return admission.admit(fields, schema_digest=parsed.schema_digest).identity
    except ActionsIdentityRefusalError as error:
        raise _refuse(_ACTIONS_DEFECTS[error.defect]) from None


def _normalize_keyed(
    dataset: SharadarDataset,
    pages: list[tuple[AcquiredPage, ParsedPage]],
    *,
    mapping: dict[str, dict[str, set[str]]],
    key_columns: tuple[str, ...],
) -> SilverDataset:
    """``stocks`` keyed by session date; ``actions`` keyed by the canonical event identity.

    For ``actions`` the row key is ``(security_id, event_identity)``: every governed field
    participates, exact duplicates within a run are refused before mapping, and the
    ``key_columns`` name only the fields that must be present for the row to be an event.
    """
    versions = _Versions()
    digests: set[str] = set()
    unmapped: set[tuple[str, str]] = set()
    ambiguous: set[tuple[str, str]] = set()
    excluded = 0
    coverage: dict[str, list[tuple[date, date]]] = {}
    delivered: dict[str, set[tuple[str, ...]]] = {}
    run_seen_at: dict[str, datetime] = {}
    admissions: dict[str, EventAdmission] = {}
    events = dataset is SharadarDataset.ACTIONS
    for page, parsed in sorted(pages, key=lambda item: _order_key(item[0])):
        digests.add(parsed.schema_digest)
        if page.run_id not in mapping:
            raise _refuse(SilverDefect.IDENTITY_SNAPSHOT_MISSING)
        snapshot = mapping[page.run_id]
        window = _window_dates(page.window)
        if window is not None:
            coverage.setdefault(page.run_id, []).append(window)
        delivered.setdefault(page.run_id, set())
        run_seen_at[page.run_id] = max(
            run_seen_at.get(page.run_id, page.retrieved_at), page.retrieved_at
        )
        for row in parsed.rows:
            fields = _fields(parsed, row)
            symbol = fields.get("ticker")
            if symbol is None or any(fields.get(column) is None for column in key_columns):
                raise _refuse(SilverDefect.ROW_KEY_MALFORMED)
            # The event identity is admitted for every delivered row, mapped or not: an
            # exact duplicate of an unmapped event is still a duplicate the vendor sent.
            identity = (
                _event_identity(admissions, page=page, parsed=parsed, fields=fields)
                if events
                else None
            )
            permatickers = snapshot.get(symbol, set())
            if len(permatickers) != 1:
                (unmapped if not permatickers else ambiguous).add((page.run_id, symbol))
                excluded += 1
                continue
            security_id = security_id_for(next(iter(permatickers)))
            row_key = (
                (security_id, identity)
                if identity is not None
                else (security_id, *[str(fields[column]) for column in key_columns])
            )
            delivered[page.run_id].add(row_key)
            versions.observe(
                dataset=dataset.value,
                row_key=row_key,
                security_id=security_id,
                symbol=symbol,
                fields=fields,
                page=page,
                parsed=parsed,
            )
    versions.mark_redelivery_gaps(
        _redelivery_gaps(versions, coverage=coverage, delivered=delivered, run_seen_at=run_seen_at)
    )
    return SilverDataset(
        dataset=dataset.value,
        rows=versions.ordered(),
        schema_digests=tuple(sorted(digests)),
        duplicate_rows=versions.duplicates,
        unmapped_symbols=len(unmapped),
        ambiguous_symbols=len(ambiguous),
        rows_excluded_for_identity=excluded,
    )


def normalize(inputs: VerifiedBuildInputs, *, schemas: AcceptedSchemas) -> SilverLayer:
    """Normalize every verified page into the three Silver datasets.

    Raises:
        SilverError: one closed defect; a refusal is of the whole input.
    """
    if type(inputs) is not VerifiedBuildInputs:
        raise TypeError("inputs must be an exact VerifiedBuildInputs")
    if type(schemas) is not AcceptedSchemas:
        raise TypeError("schemas must be an exact AcceptedSchemas")
    parsed_pages: dict[str, list[tuple[AcquiredPage, ParsedPage]]] = {
        member.value: [] for member in SharadarDataset
    }
    pages = list(inputs.pages())
    unadmitted = False
    unparseable = False
    for page in pages:
        try:
            parsed_pages[page.dataset].append((page, _parse(page, schemas=schemas)))
        except SilverError as error:
            if error.defect is SilverDefect.SCHEMA_UNSTABLE:
                unadmitted = True
            elif error.defect is SilverDefect.PAYLOAD_UNPARSEABLE:
                unparseable = True
            else:
                raise
    if unadmitted:
        # Route B (proposed ADR-0045): every page's header is observed before the
        # refusal, so an observation build reports what the deliveries carry -- as
        # evidence, never as an accepted set -- with zero writes. A page that did not
        # parse stays unobserved and makes the observation partial, never complete.
        raise SilverError(SilverDefect.SCHEMA_UNSTABLE, observation=observe_schemas(pages))
    if unparseable:
        raise _refuse(SilverDefect.PAYLOAD_UNPARSEABLE)
    pagination = _admit_pages([item for pages in parsed_pages.values() for item in pages])
    tickers_pages = parsed_pages[SharadarDataset.TICKERS.value]
    mapping = _snapshot_mapping(tickers_pages)
    return SilverLayer(
        tickers=_normalize_tickers(tickers_pages),
        stocks=_normalize_keyed(
            SharadarDataset.STOCKS,
            parsed_pages[SharadarDataset.STOCKS.value],
            mapping=mapping,
            key_columns=("date",),
        ),
        actions=_normalize_keyed(
            SharadarDataset.ACTIONS,
            parsed_pages[SharadarDataset.ACTIONS.value],
            mapping=mapping,
            key_columns=("date", "action"),
        ),
        schemas_version=schemas.version,
        pagination=pagination,
    )


__all__ = [
    "ACTIONS_COLUMNS",
    "ACTIONS_IDENTITY_VERSION",
    "SECURITY_ID_PREFIX",
    "SILVER_NORMALIZATION_VERSION",
    "STOCKS_COLUMNS",
    "TICKERS_COLUMNS",
    "AcceptedSchemas",
    "Provenance",
    "RowVersion",
    "SilverDataset",
    "SilverDefect",
    "SilverError",
    "SilverLayer",
    "normalize",
    "observe_schemas",
    "security_id_for",
]
