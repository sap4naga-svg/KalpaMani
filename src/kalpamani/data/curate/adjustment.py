"""Adjusted prices: a pure function, with materialisation only as a keyed cache.

> ``adjusted = f(raw_bars, corporate_actions admissible at as_of under the
> resolved profile, adjustment_policy)``

No adjusted series is a stored fact. There is no implicit adjustment mode and no
unkeyed adjusted table anywhere in the system.

**The direction is the contract's, and it is deliberate.** An adjustment factor
is applied only to bars **on or after** the ex-date (schema 7; a factor applied
to a bar with ``session_date < ex_date`` is BLOCKING check 4.5.2). That is not
the more familiar back-adjustment, and the difference matters here: back-adjusted
history is rewritten every time a new split arrives, so "the adjusted close on
2020-06-01" silently changes underneath a result that already cited it. Adjusting
forward from a fixed base leaves settled history settled, which is the property
this whole layer exists to protect.

For a split with ``ratio`` new shares per old share, prices from the ex-date
onward are quoted in post-split terms; multiplying them by ``ratio`` re-expresses
the whole series in the base (pre-split) terms, and volume is divided by the same
factor. A reverse split is the same arithmetic with ``ratio < 1``.

**Two rules that read alike and are not.** A corporate action becomes *knowable*
at announcement and *effective* at its ex-date. An action announced after
``as_of`` has adjusted nothing, so it cannot enter the computation at all --
that is admissibility. An action admissible at ``as_of`` still adjusts no bar
before its ex-date -- that is effectivity. Only the first is look-ahead; both are
enforced.

``SPLIT_AND_DIVIDEND`` and ``TOTAL_RETURN`` are **refused**, not approximated.
The merged contract names the policies but does not fix a dividend convention,
and inventing one here would settle a question nobody asked -- then bury the
answer in a hash that later results would cite as if it had been decided.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from kalpamani.data.contracts.canonical import canonical_bytes, content_hash, sha256_hex
from kalpamani.data.contracts.entities import (
    AdjustedBarArtifact,
    CorporateAction,
    PriceBar,
    PriceBarValues,
)
from kalpamani.data.contracts.envelope import (
    DerivedEnvelope,
    LineageRef,
    OutputValidityDeclaration,
)
from kalpamani.data.contracts.errors import ArtifactIntegrityError, PendingContractError
from kalpamani.data.contracts.resolution import (
    BoundApprovals,
    PitRecord,
    decision_available_time,
    is_eligible,
)
from kalpamani.data.contracts.serde import encode_corporate_action, encode_price_bar
from kalpamani.data.contracts.vocabulary import (
    AdjustmentPolicy,
    CorporateActionType,
    InformationSetProfile,
)

#: Version of this computation. Change it and every artifact it produces is a
#: different artifact with a different hash -- which is the point.
ADJUSTMENT_SPEC_VERSION = "adj/a1.1"

#: Price precision for adjusted output. Fixed so two builds agree exactly.
_PRICE_QUANTUM = Decimal("0.000001")

#: Action types this slice adjusts for.
_SPLIT_TYPES = frozenset({CorporateActionType.SPLIT, CorporateActionType.REVERSE_SPLIT})


def admissible_actions(
    actions: Sequence[CorporateAction],
    *,
    as_of_epoch: datetime,
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
) -> tuple[CorporateAction, ...]:
    """The actions a query at ``as_of_epoch`` was entitled to know about.

    An action ineligible under the profile, or whose governing availability is
    unresolvable, or which was announced after the cutoff, is excluded. Order is
    canonical so the result is deterministic.
    """
    admitted: list[CorporateAction] = []
    for action in actions:
        if not is_eligible(action, resolved_profile):
            continue
        available = decision_available_time(action, resolved_profile, approvals)
        if available is None or available > as_of_epoch:
            continue
        admitted.append(action)
    return tuple(sorted(admitted, key=lambda a: (a.ex_date or date.min, a.action_id)))


def adjustment_factor(
    actions: Sequence[CorporateAction],
    *,
    security_id: str,
    session_date: date,
    policy: AdjustmentPolicy,
) -> Decimal:
    """The cumulative factor re-expressing ``session_date`` in base terms.

    Only actions **on or before** the session contribute: an action adjusts no bar
    before its own ex-date.

    Raises:
        PendingContractError: for a policy whose convention the merged contract
            has not fixed.
    """
    if policy is not AdjustmentPolicy.SPLIT_ONLY:
        raise PendingContractError(
            f"Adjustment policy {policy.value} is defined in the contract vocabulary but its "
            "convention is not settled by the merged Phase-3 plan. Refusing to invent one: an "
            "invented convention would be baked into an artifact hash and cited later as "
            "though it had been decided. Implementing it is a Phase-3B decision."
        )
    factor = Decimal(1)
    for action in actions:
        if action.security_id != security_id:
            continue
        if action.action_type not in _SPLIT_TYPES:
            continue
        if action.ex_date is None or action.ratio is None:
            continue
        if session_date >= action.ex_date:
            factor *= action.ratio
    return factor


def adjusted_series(
    bars: Sequence[PriceBar],
    actions: Sequence[CorporateAction],
    *,
    policy: AdjustmentPolicy,
    as_of_epoch: datetime,
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
) -> tuple[PriceBarValues, ...]:
    """Compute the adjusted series. Pure: same inputs, same output, every time."""
    admitted = admissible_actions(
        actions,
        as_of_epoch=as_of_epoch,
        resolved_profile=resolved_profile,
        approvals=approvals,
    )
    ordered = sorted(bars, key=lambda b: (b.security_id, b.bar_end_time))
    out: list[PriceBarValues] = []
    for bar in ordered:
        factor = adjustment_factor(
            admitted,
            security_id=bar.security_id,
            session_date=bar.session_date,
            policy=policy,
        )
        out.append(
            PriceBarValues(
                security_id=bar.security_id,
                session_date=bar.session_date,
                bar_end_time=bar.bar_end_time,
                open=_price(bar.open * factor),
                high=_price(bar.high * factor),
                low=_price(bar.low * factor),
                close=_price(bar.close * factor),
                volume=_volume(bar.volume, factor),
            )
        )
    return tuple(out)


def _price(value: Decimal) -> Decimal:
    return value.quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _volume(volume: int, factor: Decimal) -> int:
    if factor == 1:
        return volume
    scaled = (Decimal(volume) / factor).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)
    return int(scaled)


def series_content_hash(series: Sequence[PriceBarValues]) -> str:
    """SHA-256 over the produced series, in canonical form."""
    return content_hash(
        [
            {
                "security_id": v.security_id,
                "session_date": v.session_date,
                "bar_end_time": v.bar_end_time,
                "open": v.open,
                "high": v.high,
                "low": v.low,
                "close": v.close,
                "volume": v.volume,
            }
            for v in series
        ]
    )


def artifact_key(
    *,
    adjustment_policy: AdjustmentPolicy,
    resolved_profile: InformationSetProfile,
    as_of_epoch: datetime,
    corporate_action_dataset_version: str,
    raw_bar_dataset_version: str,
    security_id_scope: str,
) -> dict[str, object]:
    """The complete identity of an adjusted artifact. Nothing else may key one."""
    return {
        "adjustment_policy": adjustment_policy.value,
        "resolved_profile": resolved_profile.value,
        "as_of_epoch": as_of_epoch,
        "corporate_action_dataset_version": corporate_action_dataset_version,
        "raw_bar_dataset_version": raw_bar_dataset_version,
        "security_id_scope": security_id_scope,
        "derivation_spec_version": ADJUSTMENT_SPEC_VERSION,
    }


def artifact_id_for(key: dict[str, object]) -> str:
    """A derived identity, not a generated one. No ``uuid4()``, no timestamps."""
    return "adj-" + sha256_hex(canonical_bytes(key))[:16]


def build_adjusted_bar_artifact(
    bars: Sequence[PriceBar],
    actions: Sequence[CorporateAction],
    *,
    adjustment_policy: AdjustmentPolicy,
    resolved_profile: InformationSetProfile,
    as_of_epoch: datetime,
    approvals: BoundApprovals,
    corporate_action_dataset_version: str,
    raw_bar_dataset_version: str,
    security_id_scope: str,
    artifact_first_built_time: datetime,
    ingestion_time: datetime,
    dataset_version: str,
) -> AdjustedBarArtifact:
    """Materialise an adjusted series as a keyed, immutable, verifiable cache artifact.

    ``artifact_first_built_time`` is passed in rather than read from a clock, so a
    rebuild from identical lineage keeps it: recomputing a value we already had
    does not move when we had it.
    """
    series = adjusted_series(
        bars,
        actions,
        policy=adjustment_policy,
        as_of_epoch=as_of_epoch,
        resolved_profile=resolved_profile,
        approvals=approvals,
    )
    admitted = admissible_actions(
        actions,
        as_of_epoch=as_of_epoch,
        resolved_profile=resolved_profile,
        approvals=approvals,
    )
    key = artifact_key(
        adjustment_policy=adjustment_policy,
        resolved_profile=resolved_profile,
        as_of_epoch=as_of_epoch,
        corporate_action_dataset_version=corporate_action_dataset_version,
        raw_bar_dataset_version=raw_bar_dataset_version,
        security_id_scope=security_id_scope,
    )
    sessions = sorted({bar.session_date for bar in bars})
    inputs: tuple[PitRecord, ...] = (*sorted(bars, key=_bar_sort), *admitted)

    return AdjustedBarArtifact(
        artifact_id=artifact_id_for(key),
        adjustment_policy=adjustment_policy,
        resolved_profile=resolved_profile,
        as_of_epoch=as_of_epoch,
        corporate_action_dataset_version=corporate_action_dataset_version,
        raw_bar_dataset_version=raw_bar_dataset_version,
        security_id_scope=security_id_scope,
        series=series,
        inputs=inputs,
        envelope=DerivedEnvelope(
            lineage=(
                LineageRef.of(
                    entity="price_bar",
                    dataset_version=raw_bar_dataset_version,
                    selector={
                        "scope": security_id_scope,
                        "sessions": f"{sessions[0].isoformat()}..{sessions[-1].isoformat()}"
                        if sessions
                        else "",
                    },
                ),
                LineageRef.of(
                    entity="corporate_action",
                    dataset_version=corporate_action_dataset_version,
                    selector={
                        "scope": security_id_scope,
                        "announced_through": as_of_epoch.isoformat(),
                    },
                ),
            ),
            artifact_first_built_time=artifact_first_built_time,
            derivation_spec_version=ADJUSTMENT_SPEC_VERSION,
            artifact_content_hash=series_content_hash(series),
            validity=OutputValidityDeclaration.interval(
                sessions[0] if sessions else date.min,
                sessions[-1] if sessions else date.min,
            ),
            ingestion_time=ingestion_time,
            dataset_version=dataset_version,
        ),
    )


def _bar_sort(bar: PriceBar) -> tuple[str, datetime]:
    return (bar.security_id, bar.bar_end_time)


def verify_adjusted_bar_artifact(
    artifact: AdjustedBarArtifact,
    bars: Sequence[PriceBar],
    actions: Sequence[CorporateAction],
    *,
    approvals: BoundApprovals,
) -> None:
    """Recompute the artifact from its key and refuse any divergence.

    Raises:
        ArtifactIntegrityError: if the recomputed series does not reproduce the
            recorded hash, or if the stored series itself has been altered. A
            mismatch is a BLOCKING quality issue, not a cache miss.
    """
    recomputed = adjusted_series(
        bars,
        actions,
        policy=artifact.adjustment_policy,
        as_of_epoch=artifact.as_of_epoch,
        resolved_profile=artifact.resolved_profile,
        approvals=approvals,
    )
    expected = artifact.envelope.artifact_content_hash
    if series_content_hash(recomputed) != expected:
        raise ArtifactIntegrityError(
            f"Adjusted artifact {artifact.artifact_id} does not reproduce from its key. "
            "Recomputing from the recorded adjustment policy, resolved profile, as_of epoch "
            "and input dataset versions produced a different series. This is a BLOCKING "
            "quality issue, not a cache miss."
        )
    if series_content_hash(artifact.series) != expected:
        raise ArtifactIntegrityError(
            f"Adjusted artifact {artifact.artifact_id} carries a series that does not match "
            "its own content hash. The stored bytes were altered after materialisation."
        )


def raw_series(bars: Sequence[PriceBar]) -> tuple[PriceBarValues, ...]:
    """The traded prices, untouched, in canonical order."""
    return tuple(
        PriceBarValues(
            security_id=bar.security_id,
            session_date=bar.session_date,
            bar_end_time=bar.bar_end_time,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        for bar in sorted(bars, key=_bar_sort)
    )


def encode_artifact_inputs(artifact: AdjustedBarArtifact) -> list[dict[str, object]]:
    """Encode the artifact's consumed records, for storage beside the artifact."""
    rows: list[dict[str, object]] = []
    for record in artifact.inputs:
        if isinstance(record, PriceBar):
            rows.append(encode_price_bar(record))
        elif isinstance(record, CorporateAction):
            rows.append(encode_corporate_action(record))
    return rows


__all__ = [
    "ADJUSTMENT_SPEC_VERSION",
    "adjusted_series",
    "adjustment_factor",
    "admissible_actions",
    "artifact_id_for",
    "artifact_key",
    "build_adjusted_bar_artifact",
    "encode_artifact_inputs",
    "raw_series",
    "series_content_hash",
    "verify_adjusted_bar_artifact",
]
