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

**A completed acquisition is completion of its request plan, not proof of market
coverage.** The rows normalized here are the rows the vendor delivered to those
requests; the census and completeness checks say how much of the calendar they cover,
and nothing here claims more.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.ingest.sharadar.datasets import PROVIDER, SharadarDataset
from kalpamani.data.production.sharadar.build_inputs import AcquiredPage, VerifiedBuildInputs
from kalpamani.data.qualify.sharadar.parser import ParsedPage, ParseError, parse_payload

#: The Silver normalization version. Part of every manifest and of the build ``run_id``.
SILVER_NORMALIZATION_VERSION: Final = "sharadar-silver-v1"

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
    ROW_CONFLICT_IN_RUN = "ROW_CONFLICT_IN_RUN"
    IDENTITY_SNAPSHOT_MISSING = "IDENTITY_SNAPSHOT_MISSING"
    ROW_KEY_MALFORMED = "ROW_KEY_MALFORMED"
    DATASET_UNKNOWN = "DATASET_UNKNOWN"


class SilverError(Exception):
    """One closed defect, raised ``from None``."""

    __slots__ = ("defect",)

    def __init__(self, defect: SilverDefect) -> None:
        if type(defect) is not SilverDefect:
            raise TypeError("defect must be an exact SilverDefect member")
        self.defect = defect
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
    """One distinct content for one row key. **Private material**: never rendered.

    ``system_first_seen_time`` is the retrieval instant of the **earliest acquisition
    delivering these bytes**; a later revision of the same key has its own.
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
    seen_count: int

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


def _parse(page: AcquiredPage, *, schemas: AcceptedSchemas) -> ParsedPage:
    try:
        dataset = SharadarDataset(page.dataset)
    except ValueError:
        raise _refuse(SilverDefect.DATASET_UNKNOWN) from None
    try:
        parsed = parse_payload(page.payload, dataset=dataset)
    except ParseError:
        raise _refuse(SilverDefect.PAYLOAD_UNPARSEABLE) from None
    if not schemas.admits(page.dataset, parsed.schema_digest):
        raise _refuse(SilverDefect.SCHEMA_UNSTABLE)
    return parsed


def _check_truncation(pages: list[tuple[AcquiredPage, ParsedPage]]) -> None:
    """The final page of every window must not be at the page limit."""
    by_window: dict[tuple[str, str, str], list[tuple[AcquiredPage, ParsedPage]]] = {}
    for page, parsed in pages:
        by_window.setdefault((page.run_id, page.dataset, page.window), []).append((page, parsed))
    for group in by_window.values():
        last_page, last_parsed = max(group, key=lambda item: item[0].page_offset)
        if last_parsed.row_count >= last_page.page_limit:
            raise _refuse(SilverDefect.DELIVERY_TRUNCATED)


class _Versions:
    """Row versions per key, in acquisition order; conflicts within one run refused."""

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
        # One run may deliver one content for one key. Two different contents
        # inside one acquisition are a structural conflict, whatever earlier runs
        # delivered, and the conflict is refused rather than ordered away.
        first = self.in_run.setdefault((row_key, page.run_id), digest)
        if first != digest:
            raise _refuse(SilverDefect.ROW_CONFLICT_IN_RUN)
        existing = self.versions.setdefault(row_key, [])
        for index, version in enumerate(existing):
            if version.content_sha256 == digest:
                # Identical bytes seen again: the earliest first-seen stands, and
                # the sighting is counted. Deterministic, and never an overwrite.
                self.duplicates += 1
                existing[index] = RowVersion(
                    dataset=version.dataset,
                    row_key=version.row_key,
                    security_id=version.security_id,
                    symbol=version.symbol,
                    revision_sequence=version.revision_sequence,
                    content_sha256=version.content_sha256,
                    fields=version.fields,
                    provenance=version.provenance,
                    system_first_seen_time=min(version.system_first_seen_time, page.retrieved_at),
                    seen_count=version.seen_count + 1,
                )
                return
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
                seen_count=1,
            )
        )

    def ordered(self) -> tuple[RowVersion, ...]:
        rows: list[RowVersion] = []
        for key in sorted(self.versions):
            rows.extend(self.versions[key])
        return tuple(rows)


def _snapshot_mapping(
    tickers_pages: list[tuple[AcquiredPage, ParsedPage]],
) -> dict[str, dict[str, set[str]]]:
    """Per run: symbol -> the set of ``permaticker`` values the run's snapshot delivered."""
    mapping: dict[str, dict[str, set[str]]] = {}
    for page, parsed in tickers_pages:
        per_run = mapping.setdefault(page.run_id, {})
        for row in parsed.rows:
            fields = _fields(parsed, row)
            symbol, permaticker = fields.get("ticker"), fields.get("permaticker")
            if symbol is None or permaticker is None:
                continue
            per_run.setdefault(symbol, set()).add(permaticker)
    return mapping


def _normalize_tickers(pages: list[tuple[AcquiredPage, ParsedPage]]) -> SilverDataset:
    versions = _Versions()
    digests: set[str] = set()
    for page, parsed in sorted(pages, key=lambda item: _order_key(item[0])):
        digests.add(parsed.schema_digest)
        for row in parsed.rows:
            fields = _fields(parsed, row)
            permaticker = fields.get("permaticker")
            symbol = fields.get("ticker")
            if permaticker is None or symbol is None:
                raise _refuse(SilverDefect.ROW_KEY_MALFORMED)
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


def _normalize_keyed(
    dataset: SharadarDataset,
    pages: list[tuple[AcquiredPage, ParsedPage]],
    *,
    mapping: dict[str, dict[str, set[str]]],
    key_columns: tuple[str, ...],
) -> SilverDataset:
    versions = _Versions()
    digests: set[str] = set()
    unmapped: set[tuple[str, str]] = set()
    ambiguous: set[tuple[str, str]] = set()
    excluded = 0
    for page, parsed in sorted(pages, key=lambda item: _order_key(item[0])):
        digests.add(parsed.schema_digest)
        if page.run_id not in mapping:
            raise _refuse(SilverDefect.IDENTITY_SNAPSHOT_MISSING)
        snapshot = mapping[page.run_id]
        for row in parsed.rows:
            fields = _fields(parsed, row)
            symbol = fields.get("ticker")
            if symbol is None or any(fields.get(column) is None for column in key_columns):
                raise _refuse(SilverDefect.ROW_KEY_MALFORMED)
            permatickers = snapshot.get(symbol, set())
            if len(permatickers) != 1:
                (unmapped if not permatickers else ambiguous).add((page.run_id, symbol))
                excluded += 1
                continue
            security_id = security_id_for(next(iter(permatickers)))
            row_key = (security_id, *[str(fields[column]) for column in key_columns])
            versions.observe(
                dataset=dataset.value,
                row_key=row_key,
                security_id=security_id,
                symbol=symbol,
                fields=fields,
                page=page,
                parsed=parsed,
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
    for page in inputs.pages():
        parsed_pages[page.dataset].append((page, _parse(page, schemas=schemas)))
    _check_truncation([item for pages in parsed_pages.values() for item in pages])
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
    )


__all__ = [
    "ACTIONS_COLUMNS",
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
    "security_id_for",
]
