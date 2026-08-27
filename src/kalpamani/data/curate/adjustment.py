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
from typing import Final

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
    AdjustmentConvention,
    AdjustmentPolicy,
    CorporateActionType,
    InformationSetProfile,
)

#: The convention this module implements. Named, not implied: an unnamed
#: "adjusted" series is a number whose meaning depends on which implementation
#: produced it, and the point of keying an artifact is that its meaning does not.
ADJUSTMENT_CONVENTION: Final = AdjustmentConvention.FORWARD_BASE_NORMALIZED

#: Version of this computation. Change it -- or the convention -- and every
#: artifact it produces is a different artifact with a different hash.
ADJUSTMENT_SPEC_VERSION = f"adj/a1.2+{ADJUSTMENT_CONVENTION.value}"

#: A scope beginning with this prefix authorizes more than one security. Anything
#: else is a single security id, and a build spanning two of them is refused.
MULTI_SECURITY_SCOPE_PREFIX: Final = "universe:"

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
    adjustment_convention: AdjustmentConvention = ADJUSTMENT_CONVENTION,
    resolved_profile: InformationSetProfile,
    as_of_epoch: datetime,
    corporate_action_dataset_version: str,
    raw_bar_dataset_version: str,
    security_id_scope: str,
) -> dict[str, object]:
    """The complete identity of an adjusted artifact. Nothing else may key one."""
    return {
        "adjustment_policy": adjustment_policy.value,
        "adjustment_convention": adjustment_convention.value,
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


def _validate_artifact_inputs(
    bars: Sequence[PriceBar],
    *,
    resolved_profile: InformationSetProfile,
    as_of_epoch: datetime,
    approvals: BoundApprovals,
    security_id_scope: str,
    valid_time_start: date,
    valid_time_end: date,
) -> None:
    """Refuse the four ways an artifact key can describe something it does not contain."""
    if not bars:
        raise ArtifactIntegrityError(
            "Refusing to build an adjusted artifact from zero bars. An empty series still "
            "gets a key and a hash, and downstream nothing distinguishes it from a series "
            "that genuinely had no trading."
        )
    if valid_time_start > valid_time_end:
        raise ArtifactIntegrityError(
            f"Declared validity interval {valid_time_start.isoformat()}.."
            f"{valid_time_end.isoformat()} is empty."
        )

    securities = sorted({bar.security_id for bar in bars})
    if not security_id_scope.startswith(MULTI_SECURITY_SCOPE_PREFIX):
        if len(securities) > 1:
            raise ArtifactIntegrityError(
                f"Scope {security_id_scope!r} names a single security but the bars span "
                f"{securities}. A multi-security artifact needs a scope that authorizes one, "
                f"prefixed {MULTI_SECURITY_SCOPE_PREFIX!r}, so the key describes what the "
                "artifact actually contains."
            )
        if securities[0] != security_id_scope:
            raise ArtifactIntegrityError(
                f"Scope {security_id_scope!r} does not match the security in the bars "
                f"({securities[0]!r})."
            )

    outside = sorted(
        {
            bar.session_date
            for bar in bars
            if not (valid_time_start <= bar.session_date <= valid_time_end)
        }
    )
    if outside:
        raise ArtifactIntegrityError(
            f"{len(outside)} session(s) fall outside the declared validity interval "
            f"{valid_time_start.isoformat()}..{valid_time_end.isoformat()}: {outside[:5]}. The "
            "interval is what the artifact claims to be about; bars beyond it are not in it."
        )

    inadmissible = 0
    for bar in bars:
        if not is_eligible(bar, resolved_profile):
            inadmissible += 1
            continue
        available = decision_available_time(bar, resolved_profile, approvals)
        if available is None or available > as_of_epoch:
            inadmissible += 1
    if inadmissible:
        raise ArtifactIntegrityError(
            f"{inadmissible} bar(s) are not admissible at {as_of_epoch.isoformat()} under "
            f"{resolved_profile.value}, yet were supplied to an artifact keyed by that "
            "cutoff. An artifact built from information its own key says was unavailable is "
            "look-ahead with a hash attached."
        )


def build_adjusted_bar_artifact(
    bars: Sequence[PriceBar],
    actions: Sequence[CorporateAction],
    *,
    adjustment_policy: AdjustmentPolicy,
    adjustment_convention: AdjustmentConvention = ADJUSTMENT_CONVENTION,
    resolved_profile: InformationSetProfile,
    as_of_epoch: datetime,
    approvals: BoundApprovals,
    corporate_action_dataset_version: str,
    raw_bar_dataset_version: str,
    security_id_scope: str,
    valid_time_start: date,
    valid_time_end: date,
    artifact_first_built_time: datetime,
    ingestion_time: datetime,
    dataset_version: str,
) -> AdjustedBarArtifact:
    """Materialise an adjusted series as a keyed, immutable, verifiable cache artifact.

    ``artifact_first_built_time`` is passed in rather than read from a clock, so a
    rebuild from identical lineage keeps it: recomputing a value we already had
    does not move when we had it.

    The validity interval is **declared, not inferred**. Deriving it from whatever
    bars happened to arrive would make it unfalsifiable: any input set would fit,
    including one silently missing its first month.

    Raises:
        ArtifactIntegrityError: on zero bars; on a bar not admissible at
            ``as_of_epoch`` under ``resolved_profile``; on more than one security
            when the declared scope authorizes only one; or on a bar outside the
            declared validity interval. Each would produce an artifact whose key
            describes something other than its contents.
    """
    _validate_artifact_inputs(
        bars,
        resolved_profile=resolved_profile,
        as_of_epoch=as_of_epoch,
        approvals=approvals,
        security_id_scope=security_id_scope,
        valid_time_start=valid_time_start,
        valid_time_end=valid_time_end,
    )
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
        adjustment_convention=adjustment_convention,
        resolved_profile=resolved_profile,
        as_of_epoch=as_of_epoch,
        corporate_action_dataset_version=corporate_action_dataset_version,
        raw_bar_dataset_version=raw_bar_dataset_version,
        security_id_scope=security_id_scope,
    )
    inputs: tuple[PitRecord, ...] = (*sorted(bars, key=_bar_sort), *admitted)

    return AdjustedBarArtifact(
        artifact_id=artifact_id_for(key),
        adjustment_policy=adjustment_policy,
        adjustment_convention=adjustment_convention,
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
                        "sessions": (
                            f"{valid_time_start.isoformat()}..{valid_time_end.isoformat()}"
                        ),
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
            validity=OutputValidityDeclaration.interval(valid_time_start, valid_time_end),
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
    if artifact.adjustment_convention is not ADJUSTMENT_CONVENTION:
        raise ArtifactIntegrityError(
            f"Artifact {artifact.artifact_id} declares convention "
            f"{artifact.adjustment_convention.value}; this implementation produces "
            f"{ADJUSTMENT_CONVENTION.value}. Recomputing it under a different convention "
            "would compare two different series and call the difference corruption."
        )
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
    "ADJUSTMENT_CONVENTION",
    "ADJUSTMENT_SPEC_VERSION",
    "MULTI_SECURITY_SCOPE_PREFIX",
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
