"""Canonical identity for one source row, content and all.

A resolution receipt has to be about *these rows*, not about rows that happen to
share an identifier. Keying it on ``(dataset, source_id)`` alone made a whole
class of substitution invisible: the same vendor record id carrying a corrected
price, a revised availability time, or a value from a different build all
produced the same fingerprint, so a build could be published as though the
resolution had seen data it never saw.

The identity below therefore carries **both** the row's names and its contents:

======================  ===================================================
part                    why it is in the identity
======================  ===================================================
entity                  a listing and a bar with the same id are two rows
source dataset_version  the same key in a later build is a different row
source_id               the row's own name
vendor_record_id        retained for reconciliation, never branched on
logical primary key     the entity's own key, where it declares one
revision_sequence       revision 1 supersedes revision 0; both exist
full-row content hash   everything else -- envelope and domain values alike
======================  ===================================================

The content hash is taken over the row's canonical serialised form, so it covers
the availability envelope as well as the domain values. That is the point: a
price change and a timing change are both substitutions, and a fingerprint blind
to either would let one through.
"""

from __future__ import annotations

from collections.abc import Sequence

from kalpamani.data.contracts.canonical import content_hash
from kalpamani.data.contracts.entities import (
    CorporateAction,
    Listing,
    MarketSession,
    PriceBar,
    SecurityAttribute,
    TickerHistory,
)
from kalpamani.data.contracts.errors import BuildBoundaryError
from kalpamani.data.contracts.resolution import SourceRecord
from kalpamani.data.contracts.serde import (
    Row,
    encode_corporate_action,
    encode_listing,
    encode_market_session,
    encode_price_bar,
    encode_security_attribute,
    encode_ticker_history,
)

#: One canonical row identity: seven strings, in a fixed order.
RowIdentity = tuple[str, str, str, str, str, str, str]


def encode_source_record(record: SourceRecord) -> Row:
    """Encode any Phase-3A source row to its canonical stored form.

    Raises:
        BuildBoundaryError: for an entity with no encoder. A row nothing can
            serialise cannot be hashed, and a row that cannot be hashed cannot be
            bound to a receipt -- so it does not get to be published.
    """
    match record:
        case MarketSession():
            return encode_market_session(record)
        case Listing():
            return encode_listing(record)
        case SecurityAttribute():
            return encode_security_attribute(record)
        case TickerHistory():
            return encode_ticker_history(record)
        case PriceBar():
            return encode_price_bar(record)
        case CorporateAction():
            return encode_corporate_action(record)
        case _:
            raise BuildBoundaryError(
                f"{type(record).__name__} has no canonical encoder, so it cannot be bound to a "
                "resolution receipt. A row whose contents nothing can hash could be "
                "substituted without the receipt noticing."
            )


def _logical_key(record: SourceRecord) -> str:
    """The entity's own primary key, rendered canonically.

    Entities that declare one expose ``primary_key``; the rest fall back to their
    source id, which is their key by construction.
    """
    key = getattr(record, "primary_key", None)
    if key is None:
        return record.envelope.source_id
    return "|".join(str(part) for part in key)


def source_row_identity(record: SourceRecord) -> RowIdentity:
    """The canonical identity of one source row, contents included."""
    envelope = record.envelope
    return (
        record.dataset,
        envelope.dataset_version,
        envelope.source_id,
        envelope.vendor_record_id or "",
        _logical_key(record),
        str(envelope.revision_sequence),
        content_hash(encode_source_record(record)),
    )


def row_fingerprint(records: Sequence[SourceRecord]) -> tuple[RowIdentity, ...]:
    """A canonical, order-stable fingerprint over a set of source rows.

    Sorted, so the fingerprint is a property of the set rather than of whatever
    order the rows arrived in. Two builds holding the same rows agree; a build
    holding one substituted row does not.
    """
    return tuple(sorted(source_row_identity(record) for record in records))


__all__ = [
    "RowIdentity",
    "encode_source_record",
    "row_fingerprint",
    "source_row_identity",
]
