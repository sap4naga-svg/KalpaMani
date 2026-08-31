"""The strict private parser. **The ingestion path cannot import this module.**

**Parsing lives here precisely so it does not live there.** The acquisition path
publishes vendor responses byte for byte and never decodes them, which is what
keeps a malformed, truncated or unexpectedly-encoded response preservable as
evidence. A parser on that path would put an interpretation between the wire and
the store, and the one case where evidence matters most is the case where the
interpretation fails. A static test refuses any import from ``data/ingest/`` into
this package.

**Strict UTF-8, and no replacement decoding.** A replacement character is silent
corruption of the material every later conclusion rests on. A byte-order mark is
refused rather than stripped: stripping would change the observed header, and the
schema digest has to be taken over what was actually delivered.

**No dataset has an exhaustively documented header.** The vendor publishes field
names in prose for the snapshot table and describes the corporate-action table's
contents without enumerating its action-code vocabulary at all -- which the source
register records explicitly, and which is exactly why this parser observes codes
rather than compiling a list of them. Every dataset therefore takes a
**required-subset** contract: the few fields without which a row cannot be
interpreted at all, plus every observed extra recorded rather than discarded.

**Values stay as delivered text, and typing is a separate, explicit act.** Coercing
unknown columns would mean guessing their types; a guess that read an empty field as
zero would make *missing* and *zero* the same value, which is the one confusion a
reconciliation check cannot survive. Empty is ``None``; numbers become
:class:`~decimal.Decimal` only where a caller asks for one, and never a binary
float; a date-only value becomes a :class:`~datetime.date` and is never coerced into
an instant.

**Delivered order is evidence.** Sorting is a forbidden request parameter, so the
order rows arrive in is the vendor's own. Nothing here reorders, and duplicates are
detected and reported rather than silently collapsed.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset

#: The fields without which a row of each dataset cannot be interpreted at all.
#:
#: **A required subset, not an exhaustive header.** The vendor documents no
#: complete column list for any of these three tables, so an exact-header contract
#: would be this package inventing a vendor fact. Everything delivered beyond these
#: is recorded as an observed extra.
REQUIRED_FIELDS: Final[dict[SharadarDataset, frozenset[str]]] = {
    SharadarDataset.TICKERS: frozenset({"ticker", "permaticker", "isdelisted"}),
    SharadarDataset.STOCKS: frozenset({"ticker", "date", "close"}),
    SharadarDataset.ACTIONS: frozenset({"ticker", "date", "action"}),
}

#: Largest response this parser will decode, matching the acquisition ceiling.
MAX_PARSE_BYTES: Final = 4 * 1024 * 1024

#: Largest row count a single page may yield, matching the vendor's documented
#: row-limit maximum. A page above it is not a page this package asked for.
MAX_ROWS_PER_PAGE: Final = 10_000

#: Longest single field this parser accepts, and the CSV module's own field limit
#: is left alone: this is checked per value, after parsing, so an enormous field is
#: refused as evidence rather than by an interpreter setting.
MAX_FIELD_LENGTH: Final = 4096


class ParseDefect(StrEnum):
    """Why a payload was refused. Closed, structural, and carrying no value.

    **No member can hold a row, a field or a cause.** A refusal that quoted the
    offending line would put a vendor row into a traceback, and a vendor row is the
    one thing that may never leave the private boundary.
    """

    PAYLOAD_MALFORMED = "PAYLOAD_MALFORMED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    ENCODING_INVALID = "ENCODING_INVALID"
    BYTE_ORDER_MARK = "BYTE_ORDER_MARK"
    CSV_MALFORMED = "CSV_MALFORMED"
    HEADER_MISSING = "HEADER_MISSING"
    HEADER_DUPLICATED = "HEADER_DUPLICATED"
    HEADER_BLANK = "HEADER_BLANK"
    REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
    ROW_RAGGED = "ROW_RAGGED"
    ROW_COUNT_EXCEEDED = "ROW_COUNT_EXCEEDED"
    FIELD_TOO_LONG = "FIELD_TOO_LONG"
    DATASET_UNKNOWN = "DATASET_UNKNOWN"


class ParseError(Exception):
    """A refusal carrying exactly one :class:`ParseDefect`, raised ``from None``."""

    __slots__ = ("defect",)

    def __init__(self, defect: ParseDefect) -> None:
        """Bind the defect. The message is the member's token, nothing more."""
        if type(defect) is not ParseDefect:  # pragma: no cover - type guard
            raise TypeError("a defect must be an exact ParseDefect member")
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: ParseDefect) -> ParseError:
    return ParseError(defect)


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedPage:
    """One parsed page of one dataset for one subject. **Private material.**

    ``rows`` holds vendor rows and is never rendered, logged or returned to public
    output. ``__repr__`` is a constant naming counts so no accidental logging call
    can spill one.

    ``header`` is the delivered header **in delivered order**, and ``schema_digest``
    is taken over it -- so a later run detects a silent column change, an added
    field or a reordering, none of which the vendor announces.
    """

    dataset: SharadarDataset
    header: tuple[str, ...]
    rows: tuple[tuple[str | None, ...], ...]
    schema_digest: str
    observed_extras: tuple[str, ...]
    duplicate_row_count: int

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass could give the rows a ``__repr__``."""
        raise TypeError("ParsedPage may not be subclassed")

    def __repr__(self) -> str:
        """Counts and a digest prefix. **Never a row, never a field value.**"""
        return (
            f"ParsedPage(dataset={self.dataset.value}, rows={len(self.rows)}, "
            f"schema={self.schema_digest[:8]}...)"
        )

    @property
    def row_count(self) -> int:
        """How many data rows were delivered. Zero is a legitimate answer."""
        return len(self.rows)

    @property
    def is_header_only(self) -> bool:
        """Whether the page carried a header and no rows.

        **Valid, and not a fault.** A delisted name queried outside its listing life
        legitimately returns no rows, and treating that as an error would turn the
        single most informative P2 observation into a failure.
        """
        return not self.rows

    def column(self, name: str) -> tuple[str | None, ...]:
        """Every delivered value of one column, in delivered order.

        Returns an empty tuple when the column was not delivered, which the caller
        must distinguish from a column of empty values -- the first means the vendor
        did not send the field, the second means the field was blank.
        """
        if name not in self.header:
            return ()
        index = self.header.index(name)
        return tuple(row[index] for row in self.rows)

    def has_column(self, name: str) -> bool:
        """Whether the vendor delivered this column at all."""
        return name in self.header


def decimal_field(value: str | None) -> Decimal | None:
    """``value`` as an exact :class:`~decimal.Decimal`, or ``None`` if missing.

    **Never a binary float.** A float tolerance makes a split or dividend
    reconciliation meaningless: the question is whether an adjusted price equals a
    raw price times a published ratio, and a comparison that is approximately true
    of everything answers nothing.

    ``None`` in, ``None`` out. A value that is not a number is also ``None``, and it
    is the caller's job to treat *not delivered*, *blank* and *unparseable* as the
    absence of evidence rather than as a zero.
    """
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        # A NaN or an infinity compares false against everything, which would
        # silently disable a reconciliation rather than fail it.
        return None
    return parsed


def date_field(value: str | None) -> date | None:
    """``value`` as a real calendar :class:`~datetime.date`, or ``None``.

    **Parsed, not pattern-matched**, so ``2026-13-45`` is refused rather than
    recorded. **Never coerced into an instant**: the vendor's date columns are
    date-granular, and manufacturing a midnight would state a precision the source
    does not have -- which is exactly the bound the availability test must keep.
    """
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def schema_digest_of(header: tuple[str, ...]) -> str:
    """A deterministic digest of one delivered header, **in delivered order**.

    Order-sensitive on purpose: a vendor that reorders its columns has changed the
    delivery, and a digest that ignored the order would not notice.
    """
    return sha256_hex(canonical_bytes(list(header)))


def parse_payload(payload: bytes, *, dataset: SharadarDataset) -> ParsedPage:
    """Parse one retained CSV payload for one dataset.

    Raises:
        ParseError: for a payload that is not exact bytes, over the ceiling, not
            valid UTF-8, carrying a byte-order mark, not well-formed CSV, missing a
            header, carrying a duplicated or blank header field, missing a required
            field, ragged, over the row ceiling, or carrying an over-long field.
            **Every refusal names a rule and never a value.**
    """
    if type(dataset) is not SharadarDataset:
        raise _refuse(ParseDefect.DATASET_UNKNOWN) from None
    if type(payload) is not bytes:
        raise _refuse(ParseDefect.PAYLOAD_MALFORMED) from None
    if len(payload) > MAX_PARSE_BYTES:
        raise _refuse(ParseDefect.PAYLOAD_TOO_LARGE) from None
    if payload.startswith(b"\xef\xbb\xbf"):
        # Refused rather than stripped. Stripping would change the observed header,
        # and the schema digest must describe what was actually delivered.
        raise _refuse(ParseDefect.BYTE_ORDER_MARK) from None
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse(ParseDefect.ENCODING_INVALID) from None

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        records = list(reader)
    except csv.Error:
        raise _refuse(ParseDefect.CSV_MALFORMED) from None

    if not records:
        # An entirely empty body is not a header-only page: a header-only page has
        # a header, and this has nothing to say what the columns were.
        raise _refuse(ParseDefect.HEADER_MISSING) from None

    header = tuple(records[0])
    if not header:
        raise _refuse(ParseDefect.HEADER_MISSING) from None
    if any(not name.strip() for name in header):
        raise _refuse(ParseDefect.HEADER_BLANK) from None
    if len(set(header)) != len(header):
        # Two columns of one name make every value of that name ambiguous, and
        # picking one would be picking silently.
        raise _refuse(ParseDefect.HEADER_DUPLICATED) from None

    required = REQUIRED_FIELDS[dataset]
    if required - set(header):
        raise _refuse(ParseDefect.REQUIRED_FIELD_MISSING) from None

    body = records[1:]
    if len(body) > MAX_ROWS_PER_PAGE:
        raise _refuse(ParseDefect.ROW_COUNT_EXCEEDED) from None

    rows: list[tuple[str | None, ...]] = []
    for record in body:
        if len(record) != len(header):
            # Padding a short row invents values and truncating a long one discards
            # them. Both are edits to evidence, so neither happens.
            raise _refuse(ParseDefect.ROW_RAGGED) from None
        values: list[str | None] = []
        for cell in record:
            if len(cell) > MAX_FIELD_LENGTH:
                raise _refuse(ParseDefect.FIELD_TOO_LONG) from None
            # Empty stays absent. A blank field is the vendor not supplying a value,
            # and it must never become a zero, an empty string that compares equal
            # to one, or a default.
            values.append(cell if cell != "" else None)
        rows.append(tuple(values))

    seen: set[tuple[str | None, ...]] = set()
    duplicates = 0
    for row in rows:
        if row in seen:
            duplicates += 1
        else:
            seen.add(row)

    return ParsedPage(
        dataset=dataset,
        header=header,
        rows=tuple(rows),
        schema_digest=schema_digest_of(header),
        observed_extras=tuple(name for name in header if name not in required),
        duplicate_row_count=duplicates,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PagePair:
    """Both pages of one ``(subject, dataset)``, and what the second one proves.

    **The second page is a completeness probe, and it is nothing else.** An empty
    second page is the only available proof the first was complete, because sorting
    is a forbidden parameter and the row limit truncates silently. A **non-empty**
    second page establishes truncation, and every row-count-dependent conclusion for
    this pair is then refused rather than reported -- and it is still not permission
    to fetch a third.
    """

    dataset: SharadarDataset
    first: ParsedPage
    second: ParsedPage

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass could override :meth:`truncated`."""
        raise TypeError("PagePair may not be subclassed")

    def __repr__(self) -> str:
        """Counts only. **Never a row.**"""
        return (
            f"PagePair(dataset={self.dataset.value}, first={self.first.row_count}, "
            f"second={self.second.row_count})"
        )

    @property
    def truncated(self) -> bool:
        """Whether the delivery is known incomplete."""
        return self.second.row_count > 0

    @property
    def schema_stable(self) -> bool:
        """Whether both pages declared the same header.

        A pair whose two pages disagree is a delivery that changed shape mid-walk,
        and no row-count conclusion drawn across the two would mean anything.
        """
        return self.first.schema_digest == self.second.schema_digest

    @property
    def row_count_usable(self) -> bool:
        """Whether a row-count conclusion may be drawn from this pair at all."""
        return not self.truncated and self.schema_stable


__all__ = [
    "MAX_FIELD_LENGTH",
    "MAX_PARSE_BYTES",
    "MAX_ROWS_PER_PAGE",
    "REQUIRED_FIELDS",
    "PagePair",
    "ParseDefect",
    "ParseError",
    "ParsedPage",
    "date_field",
    "decimal_field",
    "parse_payload",
    "schema_digest_of",
]
