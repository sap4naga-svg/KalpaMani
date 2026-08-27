"""Exact, replayable lineage selectors.

Lineage is "the set a rebuild would read" -- not a summary, and not a description
of the neighbourhood the rows came from. This module makes that literal: a
selector names *exactly* the rows one decision consumed, and
:func:`resolve_lineage` turns it back into exactly those rows or refuses.

**Why exact rather than predicate.** A universe membership decision for one
security consumes one listing revision, one attribute row and a handful of that
security's own bars. Attaching every admissible input in the build to every
membership row would make lineage true-but-useless: it could not distinguish the
rows that produced the decision from the rows that happened to be in the same
build, so a rebuild could not prove it read the same thing, and a changed input
for a *different* security would look like a changed input for this one.

**Four failure modes, all refusals.** A selector that resolves to nothing is
*missing*; to more rows than it names is *broader*; to fewer is *narrower*; to
rows that contradict the selector's own key is *contradictory*. Each is a
refusal, because a lineage that cannot be replayed cannot prove an artifact
reproduced -- and an artifact that cannot prove that is a number with a hash
attached.

**The dataset version selects the candidate; it is not checked afterwards.** A
row with a matching key from a *different build* is not the row the artifact
read: the same security on the same session can carry a corrected price in a
later version, and resolving to it would let an artifact verify against evidence
it never saw.

Checking the version *after* matching was not enough, and failed in the ordinary
direction. Given two builds of one listing, matching on the logical key alone
found both, the uniqueness rule fired first, and replay refused with "the key is
not unique" -- against lineage that named exactly one of them and was never
ambiguous. Version is now part of the match, so uniqueness is evaluated **within
the named version**, where a genuine duplicate is still a refusal.

**An absence is proved, not asserted.** A security with no prior bars used to be
recorded as a sentinel version with an empty endpoint list, which replay resolved
to an empty tuple without consulting anything. It could not fail, so it proved
nothing.

A no-history claim now names a governed window, the publications it was
established against, **and the information-set profile it was established
under** -- because "no bar existed" is not the decision the rule made. The rule
saw the *admissible* set: a bar whose origin is ineligible under the profile, or
whose availability had not resolved by the cutoff, was not history the decision
could have used. Replay reapplies exactly that admissibility and refuses if an
admissible bar turns up inside the window. Without the profile the claim would be
tested against a different question than the one it answers, which is how a
correct build would be refused and an incorrect one waved through.

**Selector shape is validated too.** Each entity has an exact required key set:
a missing key makes a selector ambiguous, and an unknown extra key means the
writer believed it was pinning something the reader silently ignores. Both are
refusals, and both come back as :class:`ArtifactIntegrityError` rather than as a
raw ``KeyError`` from a dictionary lookup -- a lineage failure is a lineage
failure whatever shape it arrives in.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Final

from kalpamani.data.contracts.entities import Listing, PriceBar, SecurityAttribute
from kalpamani.data.contracts.envelope import LineageRef
from kalpamani.data.contracts.errors import ArtifactIntegrityError
from kalpamani.data.contracts.instants import normalize_instant
from kalpamani.data.contracts.resolution import (
    BoundApprovals,
    PitRecord,
    decision_available_time,
    is_eligible,
)
from kalpamani.data.contracts.vocabulary import BarResolution, InformationSetProfile

#: Separator for a selector value that names several rows. Chosen because it
#: cannot occur inside an ISO instant, a security id or a listing id.
_JOIN: Final = "|"

#: The entity a negative-coverage reference names. Not ``price_bar``: it is a
#: claim *about* the bar dataset rather than a reference to rows in it, and
#: conflating the two is what let an empty selector stand in for evidence.
NEGATIVE_COVERAGE_ENTITY: Final = "price_bar_absence"


def listing_selector(listing: Listing) -> dict[str, str]:
    """Name exactly one listing revision."""
    return {
        "listing_id": listing.listing_id,
        "listing_fact_kind": listing.listing_fact_kind.value,
        "revision_sequence": str(listing.envelope.revision_sequence),
    }


def attribute_selector(attribute: SecurityAttribute) -> dict[str, str]:
    """Name exactly one time-varying attribute row."""
    return {
        "security_id": attribute.security_id,
        "attribute": attribute.attribute,
        "valid_from": attribute.valid_from.isoformat(),
    }


def bar_selector(
    security_id: str, resolution: BarResolution, bars: Sequence[PriceBar]
) -> dict[str, str]:
    """Name exactly the bars one decision consumed, by their own endpoints.

    The endpoints are the bars' primary-key component, so the selector is the key
    set rather than a range that might later match a different number of rows.
    """
    endpoints = sorted(bar.bar_end_time.isoformat() for bar in bars)
    return {
        "security_id": security_id,
        "resolution": resolution.value,
        "bar_end_times": _JOIN.join(endpoints),
    }


#: The exact key set each entity's selector must carry -- no more, no fewer.
SELECTOR_KEYS: Final[dict[str, frozenset[str]]] = {
    "listing": frozenset({"listing_id", "listing_fact_kind", "revision_sequence"}),
    "security_attribute": frozenset({"security_id", "attribute", "valid_from"}),
    "price_bar": frozenset({"security_id", "resolution", "bar_end_times"}),
    "corporate_action": frozenset({"action_id"}),
    NEGATIVE_COVERAGE_ENTITY: frozenset(
        {"security_id", "resolution", "window_start", "window_end", "resolved_profile"}
    ),
}

#: Entities whose selector may legitimately name zero rows.
#:
#: Deliberately empty. ``price_bar`` used to be here, which is how an empty
#: endpoint list came to mean "no history" -- a claim replay could not test. A
#: security with no prior bars now carries a ``price_bar_absence`` reference,
#: whose selector names a window and whose replay verifies it.
MAY_BE_EMPTY: Final[frozenset[str]] = frozenset()


def _refuse(detail: str) -> ArtifactIntegrityError:
    return ArtifactIntegrityError(
        f"Lineage does not replay: {detail}. Lineage is the set a rebuild would read; one "
        "that resolves to different rows cannot prove an artifact reproduced."
    )


def negative_coverage_version(publication_versions: Sequence[str]) -> str:
    """The canonical version string a no-history claim is pinned to.

    A tuple rather than a single version, because a history window can span
    several immutable source builds and the absence has to be true of all of
    them. Sorted and deduplicated so the same set of builds always produces the
    same string.
    """
    unique = sorted(set(publication_versions))
    if not unique:
        raise _refuse(
            "a negative-coverage claim names no source publication; an absence that is not "
            "pinned to a build is not a fact about anything"
        )
    return _JOIN.join(unique)


def negative_coverage_selector(
    *,
    security_id: str,
    resolution: BarResolution,
    window_start: datetime,
    window_end: datetime,
    resolved_profile: InformationSetProfile,
) -> dict[str, str]:
    """Name the governed window in which no **admissible** bar existed.

    Three things make the claim falsifiable, and it needs all three:

    ``window_start``/``window_end``
        Without a window the claim is unfalsifiable in both directions: any bar
        found could be dismissed as outside whatever window the writer had in
        mind, and none found proves nothing about the window the reader cares
        about.
    ``resolved_profile``
        The rule saw the admissible set, not the stored set. A
        ``PROVIDER_DERIVED`` bar is not history a ``PUBLIC_PIT`` decision could
        have used, so testing the claim against every stored row would refuse a
        build that was right.
    the reference's ``dataset_version``
        An absence is only true of particular builds.
    """
    if window_end < window_start:
        raise _refuse(
            f"a negative-coverage window {window_start.isoformat()}..{window_end.isoformat()} "
            "is inverted; an empty window is satisfied by everything"
        )
    return {
        "security_id": security_id,
        "resolution": resolution.value,
        "window_start": normalize_instant(window_start).isoformat(),
        "window_end": normalize_instant(window_end).isoformat(),
        "resolved_profile": resolved_profile.value,
    }


def bar_lineage_refs(
    security_id: str,
    resolution: BarResolution,
    bars: Sequence[PriceBar],
    *,
    absence_window: tuple[datetime, datetime] | None = None,
    absence_versions: Sequence[str] = (),
    absence_profile: InformationSetProfile | None = None,
) -> tuple[LineageRef, ...]:
    """One reference per source dataset version the bars came from.

    A history spanning two immutable source versions is two lineage facts, not
    one: a single reference would look for every endpoint in one version and
    either miss them or resolve the wrong rows.

    An **empty** history produces a ``price_bar_absence`` reference naming the
    governed window and the publications the absence was established against.
    The sentinel it replaces (version ``"none"``, empty endpoint list) always
    resolved to an empty tuple whatever the store held, so it recorded a belief
    rather than evidence for one.

    Raises:
        ArtifactIntegrityError: if ``bars`` is empty and no window or no source
            publication is supplied. A no-history claim nobody can test is worse
            than no claim, because it looks like one that was tested.
    """
    by_version: dict[str, list[PriceBar]] = {}
    for bar in bars:
        by_version.setdefault(bar.envelope.dataset_version, []).append(bar)
    if by_version:
        return tuple(
            LineageRef.of(
                entity="price_bar",
                dataset_version=version,
                selector=bar_selector(security_id, resolution, rows),
            )
            for version, rows in sorted(by_version.items())
        )

    if absence_window is None or absence_profile is None:
        raise _refuse(
            f"{security_id} has no {resolution.value} history, and establishing that needs "
            "both a governed window and the profile it was established under. An absence with "
            "neither is unfalsifiable in both directions"
        )
    window_start, window_end = absence_window
    return (
        LineageRef.of(
            entity=NEGATIVE_COVERAGE_ENTITY,
            dataset_version=negative_coverage_version(absence_versions),
            selector=negative_coverage_selector(
                security_id=security_id,
                resolution=resolution,
                window_start=window_start,
                window_end=window_end,
                resolved_profile=absence_profile,
            ),
        ),
    )


def _selector_map(ref: LineageRef) -> dict[str, str]:
    """Validate the selector's shape, then return it as a mapping.

    Raises:
        ArtifactIntegrityError: on an unknown entity, a missing key, or an extra
            one. An extra key means the writer believed it was pinning something
            the reader ignores, which is a silent disagreement about what the
            lineage says.
    """
    required = SELECTOR_KEYS.get(ref.entity)
    if required is None:
        raise _refuse(f"no resolver for lineage entity {ref.entity!r}")
    if not ref.dataset_version:
        raise _refuse(f"a {ref.entity!r} selector names no dataset_version")
    selector = dict(ref.selector)
    present = frozenset(selector)
    missing = sorted(required - present)
    extra = sorted(present - required)
    if missing or extra:
        raise _refuse(
            f"a {ref.entity!r} selector has the wrong shape (missing {missing}, unexpected "
            f"{extra}); the required keys are {sorted(required)}"
        )
    return selector


def _in_version(records: Sequence[object], ref: LineageRef) -> list[object]:
    """Only the records that came from the build the reference names.

    Version filtering happens **here**, before uniqueness is evaluated, and that
    ordering is the whole correction. Matching on the logical key across every
    build found the same listing twice whenever two immutable versions were in
    play, the uniqueness rule fired, and replay refused as ambiguous against
    lineage that named exactly one of them. Within the named version a duplicate
    is still ambiguous, and still refuses.
    """
    return [
        record
        for record in records
        if getattr(getattr(record, "envelope", None), "dataset_version", None)
        == ref.dataset_version
    ]


def _one(
    matches: Sequence[object],
    ref: LineageRef,
    selector: Mapping[str, str],
    *,
    described: str,
) -> object:
    """Exactly one row in the named version, or a refusal that says which failure."""
    if not matches:
        raise _refuse(
            f"no {described} matches {dict(selector)} in dataset version "
            f"{ref.dataset_version!r}. The same key in another build is not the row the "
            "artifact read"
        )
    if len(matches) > 1:
        raise _refuse(
            f"{len(matches)} {described} rows match {dict(selector)} within dataset version "
            f"{ref.dataset_version!r}; the key is not unique inside the build that was named"
        )
    return matches[0]


def _resolve_listing(
    selector: Mapping[str, str], listings: Sequence[Listing], ref: LineageRef
) -> Listing:
    candidates = [
        listing
        for listing in _in_version(listings, ref)
        if isinstance(listing, Listing)
        and listing.listing_id == selector["listing_id"]
        and listing.listing_fact_kind.value == selector["listing_fact_kind"]
        and str(listing.envelope.revision_sequence) == selector["revision_sequence"]
    ]
    resolved = _one(candidates, ref, selector, described="listing")
    assert isinstance(resolved, Listing)
    return resolved


def _resolve_attribute(
    selector: Mapping[str, str],
    attributes: Sequence[SecurityAttribute],
    ref: LineageRef,
) -> SecurityAttribute:
    try:
        wanted = date.fromisoformat(selector["valid_from"])
    except ValueError as exc:
        raise _refuse(
            f"a security_attribute selector carries a malformed valid_from "
            f"{selector['valid_from']!r}"
        ) from exc
    candidates = [
        attribute
        for attribute in _in_version(attributes, ref)
        if isinstance(attribute, SecurityAttribute)
        and attribute.security_id == selector["security_id"]
        and attribute.attribute == selector["attribute"]
        and attribute.valid_from == wanted
    ]
    resolved = _one(candidates, ref, selector, described="security_attribute")
    assert isinstance(resolved, SecurityAttribute)
    return resolved


def _resolve_bars(
    selector: Mapping[str, str], bars: Sequence[PriceBar], ref: LineageRef
) -> tuple[PriceBar, ...]:
    raw = selector["bar_end_times"]
    if not raw:
        raise _refuse(
            "a price_bar selector names no endpoints. An empty selector used to mean 'no "
            f"history', which replay could not test; a no-history claim is a "
            f"{NEGATIVE_COVERAGE_ENTITY!r} reference with a governed window"
        )
    try:
        wanted: list[datetime] = [
            normalize_instant(datetime.fromisoformat(item)) for item in raw.split(_JOIN)
        ]
    except (ValueError, TypeError) as exc:
        raise _refuse(f"a price_bar selector carries a malformed endpoint in {raw!r}") from exc
    if len(set(wanted)) != len(wanted):
        raise _refuse(
            "a price_bar selector names the same endpoint twice; a duplicated key would count "
            "one bar as two inputs"
        )
    if wanted != sorted(wanted):
        raise _refuse(
            "a price_bar selector is not in canonical endpoint order; an order-dependent "
            "selector would hash two identical input sets differently"
        )
    resolution = _selector_resolution(selector)
    security_id = selector["security_id"]

    by_endpoint: dict[datetime, list[PriceBar]] = {}
    for bar in _in_version(bars, ref):
        if not isinstance(bar, PriceBar):  # pragma: no cover - defensive
            continue
        if bar.security_id != security_id or bar.resolution is not resolution:
            continue
        by_endpoint.setdefault(bar.bar_end_time, []).append(bar)

    resolved: list[PriceBar] = []
    for endpoint in wanted:
        candidates = by_endpoint.get(endpoint, [])
        if not candidates:
            raise _refuse(
                f"no {resolution.value} bar for {security_id} ending {endpoint.isoformat()} in "
                f"dataset version {ref.dataset_version!r}"
            )
        if len(candidates) > 1:
            raise _refuse(
                f"{len(candidates)} bars share the key ({security_id}, {resolution.value}, "
                f"{endpoint.isoformat()}) within dataset version {ref.dataset_version!r}"
            )
        resolved.append(candidates[0])
    return tuple(resolved)


def _selector_resolution(selector: Mapping[str, str]) -> BarResolution:
    try:
        return BarResolution(selector["resolution"])
    except ValueError as exc:
        raise _refuse(f"a selector names an unknown resolution {selector['resolution']!r}") from exc


def _verify_absence(
    selector: Mapping[str, str],
    bars: Sequence[PriceBar],
    ref: LineageRef,
    *,
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
) -> None:
    """Go looking for the admissible bars a no-history claim says are not there.

    The claim names a window, the publications it was established against and the
    profile it was established under, so replay can do the one thing the old
    sentinel could not: search, under exactly the rule that produced the claim.

    Three things are deliberately **not** contradictions:

    - a bar outside the governed window. The window is what the decision looked
      at, and a later bar says nothing about what was known when it was made.
    - a bar from a publication the claim does not name. An absence is a fact about
      particular builds.
    - a bar the profile could not have used -- ineligible origin, or availability
      unresolved at the window's end. That bar was not history to this decision,
      and faulting the claim for it would refuse a build that was right.

    Raises:
        ArtifactIntegrityError: if the claim's profile is not the one being
            replayed, or an admissible bar exists inside the governed window.
    """
    resolution = _selector_resolution(selector)
    security_id = selector["security_id"]
    claimed_profile = selector["resolved_profile"]
    if claimed_profile != resolved_profile.value:
        raise _refuse(
            f"a {NEGATIVE_COVERAGE_ENTITY} claim for {security_id} was established under "
            f"{claimed_profile}, and is being replayed under {resolved_profile.value}. The "
            "admissible set differs by profile, so this would test a different claim than the "
            "one that was made"
        )
    try:
        window_start = normalize_instant(datetime.fromisoformat(selector["window_start"]))
        window_end = normalize_instant(datetime.fromisoformat(selector["window_end"]))
    except (ValueError, TypeError) as exc:
        raise _refuse(
            f"a {NEGATIVE_COVERAGE_ENTITY} selector carries a malformed window "
            f"({selector['window_start']!r}..{selector['window_end']!r})"
        ) from exc
    if window_end < window_start:
        raise _refuse(
            f"a {NEGATIVE_COVERAGE_ENTITY} window "
            f"{window_start.isoformat()}..{window_end.isoformat()} is inverted; an empty "
            "window is satisfied by everything"
        )
    if not ref.dataset_version:
        raise _refuse(
            "a negative-coverage claim names no source publication; an absence that is not "
            "pinned to a build is not a fact about anything"
        )

    pinned = set(ref.dataset_version.split(_JOIN))
    contradicting: list[PriceBar] = []
    for bar in bars:
        if bar.envelope.dataset_version not in pinned:
            continue
        if bar.security_id != security_id or bar.resolution is not resolution:
            continue
        if not (window_start <= bar.bar_end_time <= window_end):
            continue
        if not is_eligible(bar, resolved_profile):
            continue
        available = decision_available_time(bar, resolved_profile, approvals)
        if available is None or available > window_end:
            continue
        contradicting.append(bar)

    if contradicting:
        first = min(bar.bar_end_time for bar in contradicting)
        raise _refuse(
            f"a {NEGATIVE_COVERAGE_ENTITY} claim for {security_id} says no {resolution.value} "
            f"bar was admissible under {resolved_profile.value} in "
            f"{window_start.isoformat()}..{window_end.isoformat()} across {sorted(pinned)}, and "
            f"{len(contradicting)} were (first {first.isoformat()}). The decision was made on "
            "the belief that this security had no usable history"
        )


def resolve_lineage(
    refs: Sequence[LineageRef],
    *,
    listings: Sequence[Listing],
    attributes: Sequence[SecurityAttribute],
    bars: Sequence[PriceBar],
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
) -> tuple[PitRecord, ...]:
    """Replay ``refs`` against the dataset, returning exactly the rows they name.

    ``dataset_version`` participates in **selecting** each candidate, so a build
    holding two immutable versions of one logical key resolves the version the
    reference names instead of refusing as ambiguous.

    A ``price_bar_absence`` reference contributes no rows -- it is the claim that
    there are none -- and is verified by searching its governed window under
    ``resolved_profile`` rather than assumed. The profile is required because the
    claim is about the *admissible* set: a row the profile could not have used was
    never history to the decision.

    Raises:
        ArtifactIntegrityError: if a selector has the wrong shape, names an
            unknown entity, resolves to nothing **within the version it names**,
            resolves to more rows than it names, resolves to a row contradicting
            its own key, or asserts an absence a bar inside the governed window
            contradicts. Malformed values arrive here as the same typed refusal
            rather than as a raw parse error.
    """
    resolved: list[PitRecord] = []
    for ref in refs:
        selector = _selector_map(ref)
        match ref.entity:
            case "listing":
                resolved.append(_resolve_listing(selector, listings, ref))
            case "security_attribute":
                resolved.append(_resolve_attribute(selector, attributes, ref))
            case "price_bar":
                resolved.extend(_resolve_bars(selector, bars, ref))
            case _ if ref.entity == NEGATIVE_COVERAGE_ENTITY:
                # Contributes no rows by construction -- it is the claim that
                # there are none -- but it is verified rather than assumed.
                _verify_absence(
                    selector,
                    bars,
                    ref,
                    resolved_profile=resolved_profile,
                    approvals=approvals,
                )
            case _:  # pragma: no cover - _selector_map already refused
                raise _refuse(f"no resolver for lineage entity {ref.entity!r}")
    return tuple(resolved)


def lineage_fingerprint(refs: Sequence[LineageRef]) -> tuple[tuple[str, str, str], ...]:
    """A canonical, order-stable rendering of lineage for hashing and comparison."""
    return tuple(
        sorted(
            (
                ref.entity,
                ref.dataset_version,
                _JOIN.join(f"{key}={value}" for key, value in ref.selector),
            )
            for ref in refs
        )
    )


__all__ = [
    "MAY_BE_EMPTY",
    "NEGATIVE_COVERAGE_ENTITY",
    "SELECTOR_KEYS",
    "attribute_selector",
    "bar_lineage_refs",
    "bar_selector",
    "lineage_fingerprint",
    "listing_selector",
    "negative_coverage_selector",
    "negative_coverage_version",
    "resolve_lineage",
]
