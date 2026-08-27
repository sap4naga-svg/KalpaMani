"""Lossless, deterministic encoding of Phase-3A entities to and from plain rows.

Pure functions, no I/O. A "row" is a JSON-safe mapping that
:mod:`kalpamani.data.contracts.canonical` can render to identical bytes every
time, which is what makes a stored table's content hash mean something.

**Round-tripping is a correctness property, not a convenience.** A curated table
whose rows decode to something other than what was encoded would let an artifact
hash verify while the values behind it drifted. The tests assert the round trip
for every entity with a decoder here.

Decoders exist for the entities the A1 point-in-time query path actually reads
back from storage: price bars, corporate actions, market sessions and universe
membership. Encoding is available for every Phase-3A entity, because the
determinism and hashing properties are worth proving even where nothing reads
the rows back yet -- and a decoder written for a reader that does not exist is a
decoder nothing tests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from kalpamani.data.contracts.entities import (
    CorporateAction,
    Listing,
    MarketSession,
    PriceBar,
    SecurityAttribute,
    TickerHistory,
    UniverseMembership,
)
from kalpamani.data.contracts.envelope import (
    DerivedEnvelope,
    FactAnchor,
    LineageRef,
    OutputValidityDeclaration,
    SourceEnvelope,
    source_vocabulary_defects,
)
from kalpamani.data.contracts.errors import EnvelopeError
from kalpamani.data.contracts.resolution import PitRecord
from kalpamani.data.contracts.vocabulary import (
    AnnouncementBoundDerivation,
    BarConstruction,
    BarResolution,
    CorporateActionType,
    DelistingReason,
    Exchange,
    InformationOrigin,
    InformationSetProfile,
    ListingFactKind,
    OutputValidity,
    ProviderBoundDerivation,
    ProviderTimeDerivation,
    PublicBoundDerivation,
    PublicTimeDerivation,
    QualityStatus,
    TemporalFactClass,
    TickerChangeReason,
    UniverseExclusionReason,
)

Row = dict[str, Any]


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------


def _enc_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise TypeError("Refusing to encode a naive datetime; every instant is aware UTC.")
    return value.isoformat()


def _dec_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"Expected an ISO instant string, got {type(value).__name__}.")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Stored instant {value!r} has no offset; it cannot be trusted as UTC.")
    return parsed


def _req_dt(value: object) -> datetime:
    parsed = _dec_dt(value)
    if parsed is None:
        raise ValueError("A required instant was null in storage.")
    return parsed


def _enc_date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _dec_date(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"Expected an ISO date string, got {type(value).__name__}.")
    return date.fromisoformat(value)


def _req_date(value: object) -> date:
    parsed = _dec_date(value)
    if parsed is None:
        raise ValueError("A required date was null in storage.")
    return parsed


def _enc_dec(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _dec_dec(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"Expected a decimal string, got {type(value).__name__}.")
    return Decimal(value)


def _req_dec(value: object) -> Decimal:
    parsed = _dec_dec(value)
    if parsed is None:
        raise ValueError("A required decimal was null in storage.")
    return parsed


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"Expected a string, got {type(value).__name__}.")
    return value


def _int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"Expected an integer, got {type(value).__name__}.")
    return value


def _bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"Expected a boolean, got {type(value).__name__}.")
    return value


# ---------------------------------------------------------------------------
# Envelopes
# ---------------------------------------------------------------------------


def encode_fact_anchor(anchor: FactAnchor) -> Row:
    """Encode a source fact's temporal declaration and its anchor instants."""
    return {
        "temporal_fact_class": anchor.temporal_fact_class.value,
        "observation_time": _enc_dt(anchor.observation_time),
        "announcement_time": _enc_dt(anchor.announcement_time),
        "announcement_time_upper_bound": _enc_dt(anchor.announcement_time_upper_bound),
        "announcement_bound_derivation": anchor.announcement_bound_derivation.value,
        "sample_time": _enc_dt(anchor.sample_time),
    }


def decode_fact_anchor(row: Mapping[str, Any]) -> FactAnchor:
    """Decode a source fact's temporal declaration."""
    return FactAnchor(
        temporal_fact_class=TemporalFactClass(_str(row["temporal_fact_class"])),
        observation_time=_dec_dt(row["observation_time"]),
        announcement_time=_dec_dt(row["announcement_time"]),
        announcement_time_upper_bound=_dec_dt(row["announcement_time_upper_bound"]),
        announcement_bound_derivation=AnnouncementBoundDerivation(
            _str(row["announcement_bound_derivation"])
        ),
        sample_time=_dec_dt(row["sample_time"]),
    )


def encode_source_envelope(envelope: SourceEnvelope) -> Row:
    """Encode the four information times, the derivations and the anchor.

    Raises:
        EnvelopeError: if any closed vocabulary is not an exact member. Every one
            of them is stored as ``.value``, so an untyped value fails *here*, in
            the middle of a write, with a bare ``AttributeError`` naming neither
            the field nor the row. It is refused instead, and named.
    """
    defects = source_vocabulary_defects(envelope)
    if defects:
        listed = "; ".join(
            f"{name} must be a {expected}, found {actual}" for name, expected, actual in defects
        )
        raise EnvelopeError(
            f"Source envelope {envelope.source_id!r} cannot be encoded -- {listed}. Storage "
            "reads each vocabulary's .value, which a value that merely spells a member does "
            "not have, so this is refused rather than raised from inside a write."
        )
    return {
        "information_origin": envelope.information_origin.value,
        "public_available_time": _enc_dt(envelope.public_available_time),
        "public_available_upper_bound": _enc_dt(envelope.public_available_upper_bound),
        "public_time_derivation": envelope.public_time_derivation.value,
        "public_bound_derivation": envelope.public_bound_derivation.value,
        "provider_available_time": _enc_dt(envelope.provider_available_time),
        "provider_available_upper_bound": _enc_dt(envelope.provider_available_upper_bound),
        "provider_time_derivation": envelope.provider_time_derivation.value,
        "provider_bound_derivation": envelope.provider_bound_derivation.value,
        "system_first_seen_time": _enc_dt(envelope.system_first_seen_time),
        "anchor": encode_fact_anchor(envelope.anchor),
        "revision_sequence": envelope.revision_sequence,
        "valid_from": _enc_dt(envelope.valid_from),
        "valid_to": _enc_dt(envelope.valid_to),
        "source_id": envelope.source_id,
        "vendor_record_id": envelope.vendor_record_id,
        "ingestion_time": _enc_dt(envelope.ingestion_time),
        "dataset_version": envelope.dataset_version,
        "quality_status": envelope.quality_status.value,
        "provider": envelope.provider,
    }


def decode_source_envelope(row: Mapping[str, Any]) -> SourceEnvelope:
    """Decode a source envelope, refusing anything that lost its timezone."""
    vendor_record_id = row["vendor_record_id"]
    provider = row["provider"]
    return SourceEnvelope(
        information_origin=InformationOrigin(_str(row["information_origin"])),
        public_available_time=_dec_dt(row["public_available_time"]),
        public_available_upper_bound=_dec_dt(row["public_available_upper_bound"]),
        public_time_derivation=PublicTimeDerivation(_str(row["public_time_derivation"])),
        public_bound_derivation=PublicBoundDerivation(_str(row["public_bound_derivation"])),
        provider_available_time=_dec_dt(row["provider_available_time"]),
        provider_available_upper_bound=_dec_dt(row["provider_available_upper_bound"]),
        provider_time_derivation=ProviderTimeDerivation(_str(row["provider_time_derivation"])),
        provider_bound_derivation=ProviderBoundDerivation(_str(row["provider_bound_derivation"])),
        system_first_seen_time=_req_dt(row["system_first_seen_time"]),
        anchor=decode_fact_anchor(row["anchor"]),
        revision_sequence=_int(row["revision_sequence"]),
        valid_from=_dec_dt(row["valid_from"]),
        valid_to=_dec_dt(row["valid_to"]),
        source_id=_str(row["source_id"]),
        vendor_record_id=None if vendor_record_id is None else _str(vendor_record_id),
        ingestion_time=_req_dt(row["ingestion_time"]),
        dataset_version=_str(row["dataset_version"]),
        quality_status=QualityStatus(_str(row["quality_status"])),
        provider=None if provider is None else _str(provider),
    )


def encode_lineage(lineage: Sequence[LineageRef]) -> list[Row]:
    """Encode complete input lineage -- the set a rebuild would read, not a summary."""
    return [
        {
            "entity": ref.entity,
            "dataset_version": ref.dataset_version,
            "selector": [list(pair) for pair in ref.selector],
            "upstream_artifact_id": ref.upstream_artifact_id,
        }
        for ref in lineage
    ]


def decode_lineage(rows: Sequence[Mapping[str, Any]]) -> tuple[LineageRef, ...]:
    """Decode complete input lineage."""
    refs: list[LineageRef] = []
    for row in rows:
        upstream = row["upstream_artifact_id"]
        refs.append(
            LineageRef(
                entity=_str(row["entity"]),
                dataset_version=_str(row["dataset_version"]),
                selector=tuple((_str(k), _str(v)) for k, v in row["selector"]),
                upstream_artifact_id=None if upstream is None else _str(upstream),
            )
        )
    return tuple(refs)


def encode_output_validity(validity: OutputValidityDeclaration) -> Row:
    """Encode what a derived artifact is *about*."""
    return {
        "output_validity": validity.output_validity.value,
        "effective_session": _enc_date(validity.effective_session),
        "valid_time_start": _enc_date(validity.valid_time_start),
        "valid_time_end": _enc_date(validity.valid_time_end),
        "period_end": _enc_date(validity.period_end),
        "observation_reference": list(validity.observation_reference),
    }


def decode_output_validity(row: Mapping[str, Any]) -> OutputValidityDeclaration:
    """Decode what a derived artifact is *about*."""
    return OutputValidityDeclaration(
        output_validity=OutputValidity(_str(row["output_validity"])),
        effective_session=_dec_date(row["effective_session"]),
        valid_time_start=_dec_date(row["valid_time_start"]),
        valid_time_end=_dec_date(row["valid_time_end"]),
        period_end=_dec_date(row["period_end"]),
        observation_reference=tuple(_str(item) for item in row["observation_reference"]),
    )


def encode_derived_envelope(envelope: DerivedEnvelope) -> Row:
    """Encode lineage, first-built time, spec version and content hash.

    No source availability field appears here, and none may: a derived artifact
    never invents public or provider availability.
    """
    return {
        "information_origin": envelope.information_origin.value,
        "lineage": encode_lineage(envelope.lineage),
        "artifact_first_built_time": _enc_dt(envelope.artifact_first_built_time),
        "derivation_spec_version": envelope.derivation_spec_version,
        "artifact_content_hash": envelope.artifact_content_hash,
        "validity": encode_output_validity(envelope.validity),
        "ingestion_time": _enc_dt(envelope.ingestion_time),
        "dataset_version": envelope.dataset_version,
        "quality_status": envelope.quality_status.value,
        "provider": envelope.provider,
    }


def decode_derived_envelope(row: Mapping[str, Any]) -> DerivedEnvelope:
    """Decode a derived envelope."""
    provider = row["provider"]
    return DerivedEnvelope(
        lineage=decode_lineage(row["lineage"]),
        artifact_first_built_time=_req_dt(row["artifact_first_built_time"]),
        derivation_spec_version=_str(row["derivation_spec_version"]),
        artifact_content_hash=_str(row["artifact_content_hash"]),
        validity=decode_output_validity(row["validity"]),
        ingestion_time=_req_dt(row["ingestion_time"]),
        dataset_version=_str(row["dataset_version"]),
        quality_status=QualityStatus(_str(row["quality_status"])),
        provider=None if provider is None else _str(provider),
    )


def encode_envelope(record: PitRecord) -> Row:
    """Encode whichever envelope ``record`` carries."""
    envelope = record.envelope
    if isinstance(envelope, SourceEnvelope):
        return encode_source_envelope(envelope)
    return encode_derived_envelope(envelope)


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


def encode_price_bar(bar: PriceBar) -> Row:
    """Encode a raw traded bar."""
    return {
        "security_id": bar.security_id,
        "resolution": bar.resolution.value,
        "bar_end_time": _enc_dt(bar.bar_end_time),
        "bar_start_time": _enc_dt(bar.bar_start_time),
        "session_date": _enc_date(bar.session_date),
        "open": _enc_dec(bar.open),
        "high": _enc_dec(bar.high),
        "low": _enc_dec(bar.low),
        "close": _enc_dec(bar.close),
        "volume": bar.volume,
        "trade_count": bar.trade_count,
        "vwap": _enc_dec(bar.vwap),
        "is_stale": bar.is_stale,
        "had_halt": bar.had_halt,
        "curation_source": bar.curation_source,
        "bar_construction": bar.bar_construction.value,
        "envelope": encode_source_envelope(bar.envelope),
    }


def decode_price_bar(row: Mapping[str, Any]) -> PriceBar:
    """Decode a raw traded bar."""
    trade_count = row["trade_count"]
    return PriceBar(
        security_id=_str(row["security_id"]),
        resolution=BarResolution(_str(row["resolution"])),
        bar_end_time=_req_dt(row["bar_end_time"]),
        bar_start_time=_req_dt(row["bar_start_time"]),
        session_date=_req_date(row["session_date"]),
        open=_req_dec(row["open"]),
        high=_req_dec(row["high"]),
        low=_req_dec(row["low"]),
        close=_req_dec(row["close"]),
        volume=_int(row["volume"]),
        trade_count=None if trade_count is None else _int(trade_count),
        vwap=_dec_dec(row["vwap"]),
        is_stale=_bool(row["is_stale"]),
        had_halt=_bool(row["had_halt"]),
        curation_source=_str(row["curation_source"]),
        bar_construction=BarConstruction(_str(row["bar_construction"])),
        envelope=decode_source_envelope(row["envelope"]),
    )


def encode_corporate_action(action: CorporateAction) -> Row:
    """Encode an announced corporate action."""
    return {
        "action_id": action.action_id,
        "security_id": action.security_id,
        "action_type": action.action_type.value,
        "announcement_date": _enc_date(action.announcement_date),
        "ex_date": _enc_date(action.ex_date),
        "record_date": _enc_date(action.record_date),
        "pay_date": _enc_date(action.pay_date),
        "effective_date": _enc_date(action.effective_date),
        "ratio": _enc_dec(action.ratio),
        "cash_amount": _enc_dec(action.cash_amount),
        "envelope": encode_source_envelope(action.envelope),
    }


def decode_corporate_action(row: Mapping[str, Any]) -> CorporateAction:
    """Decode an announced corporate action."""
    return CorporateAction(
        action_id=_str(row["action_id"]),
        security_id=_str(row["security_id"]),
        action_type=CorporateActionType(_str(row["action_type"])),
        announcement_date=_dec_date(row["announcement_date"]),
        ex_date=_dec_date(row["ex_date"]),
        record_date=_dec_date(row["record_date"]),
        pay_date=_dec_date(row["pay_date"]),
        effective_date=_dec_date(row["effective_date"]),
        ratio=_dec_dec(row["ratio"]),
        cash_amount=_dec_dec(row["cash_amount"]),
        envelope=decode_source_envelope(row["envelope"]),
    )


def encode_market_session(session: MarketSession) -> Row:
    """Encode one exchange session."""
    return {
        "exchange": session.exchange.value,
        "session_date": _enc_date(session.session_date),
        "regular_open": _enc_dt(session.regular_open),
        "regular_close": _enc_dt(session.regular_close),
        "extended_open": _enc_dt(session.extended_open),
        "extended_close": _enc_dt(session.extended_close),
        "is_half_day": session.is_half_day,
        "is_holiday": session.is_holiday,
        "envelope": encode_source_envelope(session.envelope),
    }


def decode_market_session(row: Mapping[str, Any]) -> MarketSession:
    """Decode one exchange session."""
    return MarketSession(
        exchange=Exchange(_str(row["exchange"])),
        session_date=_req_date(row["session_date"]),
        regular_open=_req_dt(row["regular_open"]),
        regular_close=_req_dt(row["regular_close"]),
        extended_open=_req_dt(row["extended_open"]),
        extended_close=_req_dt(row["extended_close"]),
        is_half_day=_bool(row["is_half_day"]),
        is_holiday=_bool(row["is_holiday"]),
        envelope=decode_source_envelope(row["envelope"]),
    )


def encode_listing(listing: Listing) -> Row:
    """Encode a listing state or a change announcement."""
    return {
        "listing_id": listing.listing_id,
        "security_id": listing.security_id,
        "exchange": listing.exchange.value,
        "listing_start": _enc_date(listing.listing_start),
        "listing_end": _enc_date(listing.listing_end),
        "delisting_reason": (
            None if listing.delisting_reason is None else listing.delisting_reason.value
        ),
        "successor_security_id": listing.successor_security_id,
        "listing_fact_kind": listing.listing_fact_kind.value,
        "envelope": encode_source_envelope(listing.envelope),
    }


def decode_listing(row: Mapping[str, Any]) -> Listing:
    """Decode a listing row."""
    reason = row["delisting_reason"]
    successor = row["successor_security_id"]
    return Listing(
        listing_id=_str(row["listing_id"]),
        security_id=_str(row["security_id"]),
        exchange=Exchange(_str(row["exchange"])),
        listing_start=_req_date(row["listing_start"]),
        listing_end=_dec_date(row["listing_end"]),
        delisting_reason=None if reason is None else DelistingReason(_str(reason)),
        successor_security_id=None if successor is None else _str(successor),
        listing_fact_kind=ListingFactKind(_str(row["listing_fact_kind"])),
        envelope=decode_source_envelope(row["envelope"]),
    )


def encode_security_attribute(attribute: SecurityAttribute) -> Row:
    """Encode one time-varying, externally sourced attribute."""
    return {
        "security_id": attribute.security_id,
        "attribute": attribute.attribute,
        "valid_from": _enc_date(attribute.valid_from),
        "valid_to": _enc_date(attribute.valid_to),
        "value": attribute.value,
        "envelope": encode_source_envelope(attribute.envelope),
    }


def decode_security_attribute(row: Mapping[str, Any]) -> SecurityAttribute:
    """Decode one time-varying attribute."""
    return SecurityAttribute(
        security_id=_str(row["security_id"]),
        attribute=_str(row["attribute"]),
        valid_from=_req_date(row["valid_from"]),
        valid_to=_dec_date(row["valid_to"]),
        value=_str(row["value"]),
        envelope=decode_source_envelope(row["envelope"]),
    )


def encode_ticker_history(row: TickerHistory) -> Row:
    """Encode one ticker-to-security mapping interval."""
    return {
        "security_id": row.security_id,
        "ticker": row.ticker,
        "valid_from": _enc_date(row.valid_from),
        "valid_to": _enc_date(row.valid_to),
        "change_reason": None if row.change_reason is None else row.change_reason.value,
        "envelope": encode_source_envelope(row.envelope),
    }


def decode_ticker_history(row: Mapping[str, Any]) -> TickerHistory:
    """Decode one ticker-to-security mapping interval."""
    reason = row["change_reason"]
    return TickerHistory(
        security_id=_str(row["security_id"]),
        ticker=_str(row["ticker"]),
        valid_from=_req_date(row["valid_from"]),
        valid_to=_dec_date(row["valid_to"]),
        change_reason=None if reason is None else TickerChangeReason(_str(reason)),
        envelope=decode_source_envelope(row["envelope"]),
    )


def encode_universe_membership(row: UniverseMembership) -> Row:
    """Encode one stored membership decision, with the values that produced it."""
    return {
        "session_date": _enc_date(row.session_date),
        "security_id": row.security_id,
        "universe_definition_version": row.universe_definition_version,
        "resolved_profile": row.resolved_profile.value,
        "is_member": row.is_member,
        "price_at_eval": _enc_dec(row.price_at_eval),
        "market_cap_at_eval": _enc_dec(row.market_cap_at_eval),
        "addv_at_eval": _enc_dec(row.addv_at_eval),
        "history_sessions_at_eval": row.history_sessions_at_eval,
        "exclusion_reason": None if row.exclusion_reason is None else row.exclusion_reason.value,
        "is_common_stock_eligible": row.is_common_stock_eligible,
        "envelope": encode_derived_envelope(row.envelope),
    }


def decode_universe_membership(
    row: Mapping[str, Any],
    inputs: tuple[PitRecord, ...],
) -> UniverseMembership:
    """Decode one membership decision.

    ``inputs`` are supplied by the caller: the stored row carries **lineage**,
    which is the replayable description, while the resolved input records exist
    only in memory during a build. Requiring them here rather than defaulting to
    an empty tuple keeps a decoded artifact from quietly claiming an availability
    it cannot compute.
    """
    reason = row["exclusion_reason"]
    return UniverseMembership(
        session_date=_req_date(row["session_date"]),
        security_id=_str(row["security_id"]),
        universe_definition_version=_str(row["universe_definition_version"]),
        resolved_profile=InformationSetProfile(_str(row["resolved_profile"])),
        is_member=_bool(row["is_member"]),
        price_at_eval=_dec_dec(row["price_at_eval"]),
        market_cap_at_eval=_dec_dec(row["market_cap_at_eval"]),
        addv_at_eval=_dec_dec(row["addv_at_eval"]),
        history_sessions_at_eval=_int(row["history_sessions_at_eval"]),
        exclusion_reason=None if reason is None else UniverseExclusionReason(_str(reason)),
        is_common_stock_eligible=_bool(row["is_common_stock_eligible"]),
        envelope=decode_derived_envelope(row["envelope"]),
        inputs=inputs,
    )


__all__ = [
    "Row",
    "decode_corporate_action",
    "decode_derived_envelope",
    "decode_fact_anchor",
    "decode_lineage",
    "decode_listing",
    "decode_market_session",
    "decode_output_validity",
    "decode_price_bar",
    "decode_security_attribute",
    "decode_source_envelope",
    "decode_ticker_history",
    "decode_universe_membership",
    "encode_corporate_action",
    "encode_derived_envelope",
    "encode_envelope",
    "encode_fact_anchor",
    "encode_lineage",
    "encode_listing",
    "encode_market_session",
    "encode_output_validity",
    "encode_price_bar",
    "encode_security_attribute",
    "encode_source_envelope",
    "encode_ticker_history",
    "encode_universe_membership",
]
