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
    BarResolution,
    CorporateActionType,
    InformationSetProfile,
    OutputValidity,
)
from kalpamani.data.curate.lineage import bar_lineage_refs, resolve_lineage

#: The convention this module implements. Named, not implied: an unnamed
#: "adjusted" series is a number whose meaning depends on which implementation
#: produced it, and the point of keying an artifact is that its meaning does not.
ADJUSTMENT_CONVENTION: Final = AdjustmentConvention.FORWARD_BASE_NORMALIZED

#: Conventions this implementation actually computes. A caller may name only
#: these: accepting a name the code does not compute would label a series with
#: something its own numbers contradict.
SUPPORTED_CONVENTIONS: Final[frozenset[AdjustmentConvention]] = frozenset(
    {AdjustmentConvention.FORWARD_BASE_NORMALIZED}
)

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

#: Which action types each policy consumes. A policy that ignores an action type
#: must not carry it in lineage: an ignored input still narrows the artifact's
#: availability and eligibility, which would make it less available than its own
#: numbers.
_POLICY_ACTION_TYPES: Final[dict[AdjustmentPolicy, frozenset[CorporateActionType]]] = {
    AdjustmentPolicy.SPLIT_ONLY: _SPLIT_TYPES,
}


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


def require_supported_convention(convention: AdjustmentConvention) -> None:
    """Refuse a convention this implementation does not compute.

    Raises:
        PendingContractError: naming what is computed instead. A builder that
            accepted an unsupported convention would produce a series under a
            label its own arithmetic contradicts, and the label is what later
            results cite.
    """
    if convention not in SUPPORTED_CONVENTIONS:
        raise PendingContractError(
            f"Adjustment convention {convention.value} is defined in the contract vocabulary "
            f"but this implementation computes "
            f"{sorted(item.value for item in SUPPORTED_CONVENTIONS)}. Refusing to produce a "
            "series under a convention it does not apply."
        )


def relevant_actions(
    actions: Sequence[CorporateAction],
    *,
    security_id_scope: str,
    policy: AdjustmentPolicy,
    valid_time_start: date,
    valid_time_end: date,
    securities: Sequence[str],
) -> tuple[CorporateAction, ...]:
    """The actions that can actually affect this artifact, and no others.

    Lineage naming an action the computation ignores is worse than lineage naming
    too few: the artifact's availability is the max over its inputs, so an
    unrelated action -- another security's, a dividend under ``SPLIT_ONLY``, one
    effective *after* the declared interval -- would push the artifact's
    availability later and its eligibility narrower for a row that changed
    nothing. The artifact would then be less available than the numbers it holds.

    An action **before** the interval is not unrelated. Under
    ``FORWARD_BASE_NORMALIZED`` every bar is expressed in the original base, so an
    earlier split scales every bar in the interval; it changes the numbers, so it
    belongs in the lineage and its availability legitimately governs the artifact.
    """
    if policy not in _POLICY_ACTION_TYPES:
        raise PendingContractError(
            f"Adjustment policy {policy.value} is defined in the contract vocabulary but its "
            "action set is not settled by the merged Phase-3 plan. Refusing to invent one -- "
            "and refusing in the documented way, rather than with a bare KeyError that reads "
            "like a bug in this module."
        )
    wanted_types = _POLICY_ACTION_TYPES[policy]
    scoped = set(securities)
    kept: list[CorporateAction] = []
    for action in actions:
        if action.security_id not in scoped:
            continue
        if action.action_type not in wanted_types:
            continue
        if action.ex_date is None:
            continue
        if action.action_type in _SPLIT_TYPES and action.ratio is None:
            # A split with no ratio adjusts nothing. Keeping it put an action in
            # the lineage, the inputs, the key and the source-version tuple that
            # changed no number -- and pushed the artifact's availability later
            # than the numbers it holds, which is the exact failure `relevant`
            # exists to prevent.
            continue
        # An action taking effect after the interval adjusts none of its bars.
        #
        # There is no lower bound, and that is the convention rather than an
        # oversight. FORWARD_BASE_NORMALIZED expresses every bar in the *original*
        # base, applying each split's factor to bars on or after its ex-date -- so
        # a split before the interval applies to every bar inside it, and dropping
        # it left the artifact's numbers disagreeing with the reader's over the
        # same bars.
        #
        # It is also what makes the convention worth the name: a bar's adjusted
        # value is a property of the bar and the actions, not of the interval a
        # caller happened to ask for. Excluding earlier splits made the same bar
        # 104.00 through the reader and 52.00 through an artifact whose interval
        # started after the split.
        if action.ex_date > valid_time_end:
            continue
        kept.append(action)
    return tuple(sorted(kept, key=lambda item: (item.ex_date or date.min, item.action_id)))


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
    convention: AdjustmentConvention,
    as_of_epoch: datetime,
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
) -> tuple[PriceBarValues, ...]:
    """Compute the adjusted series. Pure: same inputs, same output, every time.

    ``convention`` is required and has no default: the caller names what
    "adjusted" means, and this refuses any convention it does not compute.
    """
    require_supported_convention(convention)
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


def source_versions(records: Sequence[PitRecord]) -> tuple[str, ...]:
    """Every source build a set of rows came from, canonical and deduplicated.

    Derived from the rows rather than accepted from a caller. A caller-supplied
    version entered the artifact key unverified, so an artifact could be keyed to
    a build it had not read -- and the key is what a later result cites.
    """
    return tuple(sorted({record.envelope.dataset_version for record in records}))


def bar_lineage_hash(bars: Sequence[PriceBar]) -> str:
    """Canonical hash of exactly which raw bars an artifact consumed.

    Identity, not summary. Two artifacts over the same policy, profile, cutoff and
    dataset versions but different bar sets are different artifacts, and a key
    blind to the difference would let one overwrite the other in a cache and
    verify.
    """
    return content_hash(
        sorted(
            [
                bar.security_id,
                bar.resolution.value,
                bar.bar_end_time.isoformat(),
                bar.envelope.dataset_version,
            ]
            for bar in bars
        )
    )


def action_lineage_hash(actions: Sequence[CorporateAction]) -> str:
    """Canonical hash of the corporate actions an artifact consumed, and what they do.

    Identity plus effect. Hashing the id and version alone meant two artifacts
    over actions with materially different ratios shared a key, so a cache lookup
    could return prices computed from a different split.
    """
    return content_hash(
        sorted(
            [
                action.action_id,
                action.envelope.dataset_version,
                action.action_type.value,
                "" if action.ex_date is None else action.ex_date.isoformat(),
                "" if action.ratio is None else str(action.ratio),
            ]
            for action in actions
        )
    )


def artifact_key(
    *,
    adjustment_policy: AdjustmentPolicy,
    adjustment_convention: AdjustmentConvention,
    resolved_profile: InformationSetProfile,
    as_of_epoch: datetime,
    corporate_action_dataset_versions: tuple[str, ...],
    raw_bar_dataset_versions: tuple[str, ...],
    security_id_scope: str,
    bar_resolution: BarResolution,
    valid_time_start: date,
    valid_time_end: date,
    price_bar_lineage_hash: str,
    action_lineage_hash: str,
) -> dict[str, object]:
    """The complete identity of an adjusted artifact. Nothing else may key one.

    Four things were missing and each admitted a collision -- two genuinely
    different artifacts sharing one id, so a cache lookup could return the wrong
    series and verification would confirm it:

    ``valid_time_start``/``valid_time_end``
        The interval is what the artifact claims to be about. One month of a
        security and one year of it are not the same artifact.
    ``bar_resolution``
        A daily series and a minute series over the same span are different
        numbers.
    ``price_bar_lineage_hash``/``action_lineage_hash``
        Dataset versions say which *builds* were read, not which **rows**. Two
        artifacts reading different subsets of one version had identical keys.

    The two version fields are **tuples derived from the rows**, not scalars
    supplied by the caller. Exact lineage can span several immutable builds, so a
    single version could only be true of one of them, and nothing checked which.
    """
    return {
        "adjustment_policy": adjustment_policy.value,
        "adjustment_convention": adjustment_convention.value,
        "resolved_profile": resolved_profile.value,
        "as_of_epoch": as_of_epoch,
        "corporate_action_dataset_versions": list(corporate_action_dataset_versions),
        "raw_bar_dataset_versions": list(raw_bar_dataset_versions),
        "security_id_scope": security_id_scope,
        "bar_resolution": bar_resolution.value,
        "valid_time_start": valid_time_start,
        "valid_time_end": valid_time_end,
        "price_bar_lineage_hash": price_bar_lineage_hash,
        "action_lineage_hash": action_lineage_hash,
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

    resolutions = sorted({bar.resolution.value for bar in bars})
    if len(resolutions) > 1:
        raise ArtifactIntegrityError(
            f"An adjusted artifact was supplied bars at {resolutions}. A series mixing "
            "resolutions is not a series, and one key cannot describe both."
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
    adjustment_convention: AdjustmentConvention,
    resolved_profile: InformationSetProfile,
    as_of_epoch: datetime,
    approvals: BoundApprovals,
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
    require_supported_convention(adjustment_convention)
    securities = sorted({bar.security_id for bar in bars})
    # Lineage names only what the computation can actually consume. An ignored
    # action still pushes the artifact's availability later and its eligibility
    # narrower, which would make the artifact less available than its own numbers.
    candidate_actions = relevant_actions(
        actions,
        security_id_scope=security_id_scope,
        policy=adjustment_policy,
        valid_time_start=valid_time_start,
        valid_time_end=valid_time_end,
        securities=securities,
    )
    series = adjusted_series(
        bars,
        candidate_actions,
        policy=adjustment_policy,
        convention=adjustment_convention,
        as_of_epoch=as_of_epoch,
        resolved_profile=resolved_profile,
        approvals=approvals,
    )
    admitted = admissible_actions(
        candidate_actions,
        as_of_epoch=as_of_epoch,
        resolved_profile=resolved_profile,
        approvals=approvals,
    )
    resolution = bars[0].resolution
    bar_versions = source_versions(bars)
    action_versions = source_versions(admitted)
    key = artifact_key(
        adjustment_policy=adjustment_policy,
        adjustment_convention=adjustment_convention,
        resolved_profile=resolved_profile,
        as_of_epoch=as_of_epoch,
        corporate_action_dataset_versions=action_versions,
        raw_bar_dataset_versions=bar_versions,
        security_id_scope=security_id_scope,
        bar_resolution=resolution,
        valid_time_start=valid_time_start,
        valid_time_end=valid_time_end,
        price_bar_lineage_hash=bar_lineage_hash(bars),
        action_lineage_hash=action_lineage_hash(admitted),
    )
    inputs: tuple[PitRecord, ...] = (*sorted(bars, key=_bar_sort), *admitted)

    return AdjustedBarArtifact(
        artifact_id=artifact_id_for(key),
        adjustment_policy=adjustment_policy,
        adjustment_convention=adjustment_convention,
        resolved_profile=resolved_profile,
        as_of_epoch=as_of_epoch,
        corporate_action_dataset_versions=action_versions,
        raw_bar_dataset_versions=bar_versions,
        security_id_scope=security_id_scope,
        series=series,
        inputs=inputs,
        envelope=DerivedEnvelope(
            lineage=(
                # Exact endpoints, per security and per source version. The
                # earlier selector named a scope and a date range, which is a
                # predicate: replaying it would re-evaluate "whatever matches
                # now" instead of resolving the rows the artifact actually read,
                # so a bar added to the range later would still satisfy it.
                *_bar_lineage(bars, resolution),
                *(
                    LineageRef.of(
                        entity="corporate_action",
                        dataset_version=action.envelope.dataset_version,
                        selector={"action_id": action.action_id},
                    )
                    for action in admitted
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


def _bar_lineage(bars: Sequence[PriceBar], resolution: BarResolution) -> tuple[LineageRef, ...]:
    """One reference per security **per source dataset version**, naming endpoints.

    A history spanning two immutable source versions is two lineage facts. One
    reference covering both would look for every endpoint in one version and
    either miss them or resolve the wrong rows.
    """
    by_security: dict[str, list[PriceBar]] = {}
    for bar in bars:
        by_security.setdefault(bar.security_id, []).append(bar)
    refs: list[LineageRef] = []
    for security_id, rows in sorted(by_security.items()):
        refs.extend(bar_lineage_refs(security_id, resolution, rows))
    return tuple(refs)


def _resolved_lineage(
    artifact: AdjustedBarArtifact,
    bars: Sequence[PriceBar],
    actions: Sequence[CorporateAction],
    *,
    approvals: BoundApprovals,
) -> tuple[tuple[PriceBar, ...], tuple[CorporateAction, ...]]:
    """Resolve the artifact's own lineage to exactly the rows it names.

    Every reference is resolved by selector, in the dataset version it names.
    Verification then recomputes from **these** rows and nothing else: an artifact
    that reproduces from a different input set has not reproduced, and passing the
    caller's whole pool to the recomputation would let it.

    Raises:
        ArtifactIntegrityError: if a reference names a row that is absent, or one
            that resolves in a different dataset version than the artifact read.
    """
    by_action: dict[tuple[str, str], CorporateAction] = {}
    for action in actions:
        key = (action.action_id, action.envelope.dataset_version)
        existing = by_action.get(key)
        if existing is not None and existing != action:
            # A dict keeps the last write, so which of two conflicting rows an
            # artifact verified against would be decided by the order the caller
            # happened to pass them in. Neither is used.
            raise ArtifactIntegrityError(
                f"Two different corporate actions share the key {key}. Which one this "
                "artifact verified against would be decided by list order, so neither is "
                "used."
            )
        by_action[key] = action
    resolved_bars: list[PriceBar] = []
    resolved_actions: list[CorporateAction] = []

    for ref in artifact.envelope.lineage:
        if ref.entity == "corporate_action":
            action_id = dict(ref.selector).get("action_id")
            if action_id is None:
                raise ArtifactIntegrityError(
                    f"Artifact {artifact.artifact_id} carries a corporate_action lineage "
                    "reference with no action_id; a predicate cannot say which action was "
                    "consumed."
                )
            # Keyed by (action_id, dataset_version), so the version selects the
            # row rather than being checked after one was chosen. A corrected
            # ratio in a later build shares the action_id, and matching on that
            # alone found whichever copy happened to be last in the mapping.
            resolved_action = by_action.get((action_id, ref.dataset_version))
            if resolved_action is None:
                raise ArtifactIntegrityError(
                    f"Artifact {artifact.artifact_id} names corporate action {action_id!r} in "
                    f"dataset version {ref.dataset_version!r}, which is not among the actions "
                    "supplied for verification. A later build can carry a corrected ratio, and "
                    "verifying against it would prove nothing about what the artifact read."
                )
            resolved_actions.append(resolved_action)
        elif ref.entity == "price_bar":
            resolved_bars.extend(_resolve_bar_ref(artifact, ref, bars, approvals=approvals))
        else:
            raise ArtifactIntegrityError(
                f"Artifact {artifact.artifact_id} carries a lineage reference to "
                f"{ref.entity!r}, which an adjusted series does not read."
            )

    return (
        tuple(sorted(resolved_bars, key=_bar_sort)),
        tuple(sorted(resolved_actions, key=lambda a: a.action_id)),
    )


def _resolve_bar_ref(
    artifact: AdjustedBarArtifact,
    ref: LineageRef,
    bars: Sequence[PriceBar],
    *,
    approvals: BoundApprovals,
) -> tuple[PriceBar, ...]:
    """The exact bars one price_bar reference names, or a refusal."""
    selector = dict(ref.selector)
    missing_keys = sorted({"security_id", "resolution", "bar_end_times"} - set(selector))
    if missing_keys:
        raise ArtifactIntegrityError(
            f"Artifact {artifact.artifact_id} carries a price_bar lineage reference missing "
            f"{missing_keys}. A reference that names a range rather than endpoints is a "
            "predicate: replaying it would re-evaluate whatever matches now."
        )
    resolved = resolve_lineage(
        (ref,),
        listings=(),
        attributes=(),
        bars=bars,
        resolved_profile=artifact.resolved_profile,
        approvals=approvals,
    )
    return tuple(row for row in resolved if isinstance(row, PriceBar))


def _recomputed_key(
    artifact: AdjustedBarArtifact,
    bars: Sequence[PriceBar],
    actions: Sequence[CorporateAction],
) -> dict[str, object]:
    """The key the resolved lineage implies, rebuilt from scratch.

    Every part comes from the rows the lineage resolved to, including the source
    version tuples. A version the artifact merely *claims* cannot enter the
    recomputation, so a false one fails to rebuild the id rather than being
    carried into it.
    """
    validity = artifact.envelope.validity
    if (
        validity.output_validity is not OutputValidity.INTERVAL
        or validity.valid_time_start is None
        or validity.valid_time_end is None
    ):
        raise ArtifactIntegrityError(
            f"Artifact {artifact.artifact_id} declares {validity.output_validity.value} "
            "validity without an interval. The interval is part of the key, so an artifact "
            "without one cannot be identified."
        )
    resolutions = sorted({bar.resolution for bar in bars}, key=lambda item: item.value)
    if len(resolutions) != 1:
        raise ArtifactIntegrityError(
            f"Artifact {artifact.artifact_id} resolves to bars at "
            f"{[item.value for item in resolutions]}. A series mixing resolutions is not a "
            "series."
        )
    return artifact_key(
        adjustment_policy=artifact.adjustment_policy,
        adjustment_convention=artifact.adjustment_convention,
        resolved_profile=artifact.resolved_profile,
        as_of_epoch=artifact.as_of_epoch,
        corporate_action_dataset_versions=source_versions(actions),
        raw_bar_dataset_versions=source_versions(bars),
        security_id_scope=artifact.security_id_scope,
        bar_resolution=resolutions[0],
        valid_time_start=validity.valid_time_start,
        valid_time_end=validity.valid_time_end,
        price_bar_lineage_hash=bar_lineage_hash(bars),
        action_lineage_hash=action_lineage_hash(actions),
    )


def verify_adjusted_bar_artifact(
    artifact: AdjustedBarArtifact,
    bars: Sequence[PriceBar],
    actions: Sequence[CorporateAction],
    *,
    approvals: BoundApprovals,
) -> None:
    """Resolve the recorded lineage, rebuild the key, recompute, refuse any divergence.

    Four steps, in this order, because each depends on the one before it:

    1. **resolve** every lineage reference to the exact rows it names, in the
       dataset version it names -- a matching key from a later build is not the
       row the artifact read, and the artifact's own claimed source versions must
       agree with what resolved;
    2. **rebuild the key** from those rows and compare the derived
       ``artifact_id``, so an artifact whose identity does not follow from its own
       lineage is refused before its numbers are examined;
    3. **recompute** the series from **only** the resolved rows, not from the
       pool the caller happened to pass;
    4. **compare** the recomputed hash and the stored series to the recorded
       content hash.

    Raises:
        ArtifactIntegrityError: if the lineage does not resolve, if the key does
            not rebuild, if the recomputed series does not reproduce the recorded
            hash, or if the stored series has been altered. A mismatch is a
            BLOCKING quality issue, not a cache miss.
    """
    if artifact.adjustment_convention is not ADJUSTMENT_CONVENTION:
        raise ArtifactIntegrityError(
            f"Artifact {artifact.artifact_id} declares convention "
            f"{artifact.adjustment_convention.value}; this implementation produces "
            f"{ADJUSTMENT_CONVENTION.value}. Recomputing it under a different convention "
            "would compare two different series and call the difference corruption."
        )
    lineage_bars, lineage_actions = _resolved_lineage(artifact, bars, actions, approvals=approvals)
    if not lineage_bars:
        raise ArtifactIntegrityError(
            f"Artifact {artifact.artifact_id} resolves to no price bars. An artifact whose "
            "lineage names nothing cannot be shown to have read anything."
        )

    derived_bars = source_versions(lineage_bars)
    derived_actions = source_versions(lineage_actions)
    if (
        artifact.raw_bar_dataset_versions != derived_bars
        or artifact.corporate_action_dataset_versions != derived_actions
    ):
        raise ArtifactIntegrityError(
            f"Adjusted artifact {artifact.artifact_id} claims source versions "
            f"{list(artifact.raw_bar_dataset_versions)} for bars and "
            f"{list(artifact.corporate_action_dataset_versions)} for actions, and its lineage "
            f"resolves in {list(derived_bars)} and {list(derived_actions)}. The recomputed key "
            "is built from the rows, so a false claim here would otherwise be ignored rather "
            "than refused -- and the claim is what a later result cites."
        )

    rebuilt = artifact_id_for(_recomputed_key(artifact, lineage_bars, lineage_actions))
    if rebuilt != artifact.artifact_id:
        raise ArtifactIntegrityError(
            f"Adjusted artifact {artifact.artifact_id} does not rebuild its own identity from "
            f"its lineage (recomputed {rebuilt}). The key covers the interval, the bar "
            "resolution and the exact rows consumed, so an id that no longer follows from "
            "them describes a different artifact than the one stored."
        )

    recomputed = adjusted_series(
        lineage_bars,
        lineage_actions,
        policy=artifact.adjustment_policy,
        convention=artifact.adjustment_convention,
        as_of_epoch=artifact.as_of_epoch,
        resolved_profile=artifact.resolved_profile,
        approvals=approvals,
    )
    expected = artifact.envelope.artifact_content_hash
    if series_content_hash(recomputed) != expected:
        raise ArtifactIntegrityError(
            f"Adjusted artifact {artifact.artifact_id} does not reproduce from its key. "
            "Recomputing from the recorded adjustment policy, resolved profile, as_of epoch "
            "and the exact rows its lineage names produced a different series. This is a "
            "BLOCKING quality issue, not a cache miss."
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
    "SUPPORTED_CONVENTIONS",
    "adjusted_series",
    "adjustment_factor",
    "admissible_actions",
    "artifact_id_for",
    "artifact_key",
    "build_adjusted_bar_artifact",
    "encode_artifact_inputs",
    "raw_series",
    "relevant_actions",
    "require_supported_convention",
    "series_content_hash",
    "source_versions",
    "verify_adjusted_bar_artifact",
]
