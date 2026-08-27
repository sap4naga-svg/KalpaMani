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

**The dataset version is part of the identity, not decoration.** A row with a
matching key from a *different build* is not the row the artifact read: the same
security on the same session can carry a corrected price in a later version, and
resolving to it would let an artifact verify against evidence it never saw. Every
resolved record's ``envelope.dataset_version`` must equal the one its
``LineageRef`` names.

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
from kalpamani.data.contracts.resolution import PitRecord
from kalpamani.data.contracts.vocabulary import BarResolution

#: Separator for a selector value that names several rows. Chosen because it
#: cannot occur inside an ISO instant, a security id or a listing id.
_JOIN: Final = "|"


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
}

#: Entities whose selector may legitimately name zero rows. A security with no
#: prior bars has an empty price history, and that is a fact about the security
#: rather than a defect in the lineage.
MAY_BE_EMPTY: Final[frozenset[str]] = frozenset({"price_bar"})


def _refuse(detail: str) -> ArtifactIntegrityError:
    return ArtifactIntegrityError(
        f"Lineage does not replay: {detail}. Lineage is the set a rebuild would read; one "
        "that resolves to different rows cannot prove an artifact reproduced."
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


def _require_version(record: object, ref: LineageRef, *, described: str) -> None:
    """A matching key from a different build is not the same lineage."""
    envelope = getattr(record, "envelope", None)
    version = getattr(envelope, "dataset_version", None)
    if version != ref.dataset_version:
        raise _refuse(
            f"{described} resolves in dataset version {version!r}, not the "
            f"{ref.dataset_version!r} the lineage names. The same key in a later build can "
            "carry a corrected value, and resolving to it would let an artifact verify "
            "against evidence it never read"
        )


def _resolve_listing(
    selector: Mapping[str, str], listings: Sequence[Listing], ref: LineageRef
) -> Listing:
    matches = [
        listing
        for listing in listings
        if listing.listing_id == selector["listing_id"]
        and listing.listing_fact_kind.value == selector["listing_fact_kind"]
        and str(listing.envelope.revision_sequence) == selector["revision_sequence"]
    ]
    if not matches:
        raise _refuse(f"no listing matches {dict(selector)}")
    if len(matches) > 1:
        raise _refuse(f"{len(matches)} listings match {dict(selector)}; the key is not unique")
    _require_version(matches[0], ref, described=f"listing {selector['listing_id']!r}")
    return matches[0]


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
    matches = [
        attribute
        for attribute in attributes
        if attribute.security_id == selector["security_id"]
        and attribute.attribute == selector["attribute"]
        and attribute.valid_from == wanted
    ]
    if not matches:
        raise _refuse(f"no security_attribute matches {dict(selector)}")
    if len(matches) > 1:
        raise _refuse(f"{len(matches)} attributes match {dict(selector)}; the key is not unique")
    _require_version(matches[0], ref, described=f"attribute {selector['attribute']!r}")
    return matches[0]


def _resolve_bars(
    selector: Mapping[str, str], bars: Sequence[PriceBar], ref: LineageRef
) -> tuple[PriceBar, ...]:
    raw = selector["bar_end_times"]
    if not raw and ref.entity not in MAY_BE_EMPTY:
        raise _refuse(f"a {ref.entity!r} selector names no rows, and this entity requires some")
    try:
        wanted: list[datetime] = (
            [normalize_instant(datetime.fromisoformat(item)) for item in raw.split(_JOIN)]
            if raw
            else []
        )
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
    try:
        resolution = BarResolution(selector["resolution"])
    except ValueError as exc:
        raise _refuse(
            f"a price_bar selector names an unknown resolution {selector['resolution']!r}"
        ) from exc
    security_id = selector["security_id"]

    by_endpoint: dict[datetime, list[PriceBar]] = {}
    for bar in bars:
        if bar.security_id != security_id or bar.resolution is not resolution:
            continue
        by_endpoint.setdefault(bar.bar_end_time, []).append(bar)

    resolved: list[PriceBar] = []
    for endpoint in wanted:
        candidates = by_endpoint.get(endpoint, [])
        if not candidates:
            raise _refuse(
                f"no {resolution.value} bar for {security_id} ending {endpoint.isoformat()}"
            )
        if len(candidates) > 1:
            raise _refuse(
                f"{len(candidates)} bars share the key ({security_id}, {resolution.value}, "
                f"{endpoint.isoformat()})"
            )
        _require_version(
            candidates[0], ref, described=f"bar for {security_id} at {endpoint.isoformat()}"
        )
        resolved.append(candidates[0])
    return tuple(resolved)


def resolve_lineage(
    refs: Sequence[LineageRef],
    *,
    listings: Sequence[Listing],
    attributes: Sequence[SecurityAttribute],
    bars: Sequence[PriceBar],
) -> tuple[PitRecord, ...]:
    """Replay ``refs`` against the dataset, returning exactly the rows they name.

    Raises:
        ArtifactIntegrityError: if a selector has the wrong shape, names an
            unknown entity, resolves to nothing, resolves to more rows than it
            names, resolves to a row contradicting its own key, or resolves in a
            dataset version other than the one it names. Malformed values arrive
            here as the same typed refusal rather than as a raw parse error.
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
    "SELECTOR_KEYS",
    "attribute_selector",
    "bar_selector",
    "lineage_fingerprint",
    "listing_selector",
    "resolve_lineage",
]
