"""Pagination admission for verified build inputs, v2: one proven-complete data page per group.

**What a COMPLETE v2 locator proves, and what the build still checks.** A COMPLETE
acquisition locator proves that every compiled data coordinate has confirmed publication
dispositions and carries closed completion evidence -- a short page that needed no probe,
or an exactly-full page whose completion probe passed (ADR-0053 §11.2, §13.3). The
build re-derives that evidence from the bytes it verified rather than trusting it: every
group's one data page is parsed, its raw row count and schema digest must equal what the
record and the locator recorded, and the completion outcome must be the one the state
machine assigns to those facts.

**The supported shape**, applied per group -- one acquisition run, one dataset, one exact
compiled window, one predicate, never combined across runs or windows:

- exactly **one** page, at offset zero, at the dataset's governed limit ``L``;
- its raw row count strictly below ``L``, with ``SHORT_PAGE_COMPLETE`` and no probe; or
- its raw row count exactly ``L``, with ``PROBE_PASSED`` -- a retained probe of zero rows,
  the same schema digest, at offset ``L``.

**Row counts are raw** -- taken from the parsed page before any deduplication, revision
consolidation, symbol mapping or filtering -- so a full page of repeated rows is a full page.

**Refused**, each with its own closed member: a page carrying more rows than its
governed limit (``PAGE_OVER_LIMIT``); a group carrying more than one page, or any page at a
positive offset -- the multi-page delivery no accepted contract can make safe
(``PAGINATION_UNSUPPORTED``); recorded evidence that disagrees with the parsed page's row
count, schema digest or limit, or a probe on a short page (``PAGINATION_INCONSISTENT``); an
exactly-full page whose probe evidence is absent (``COMPLETION_UNPROVEN``); an exactly-full
page whose probe was data-bearing, mismatched or otherwise failed (``DELIVERY_TRUNCATED``).
Missing, duplicated or altered coordinates are refused earlier by the accepted locator
validator and never reach this gate.

**The limits of the supported shape are stated, not implied.** A passed probe proves that
no row remained beyond ``L`` at the instant of the probe under the same shape; it does
**not** establish vendor completeness of the window, the inclusivity of the window's
dates, or the consistency of a snapshot delivered across several requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.production.sharadar.build_inputs import AcquiredPage
from kalpamani.data.production.sharadar.completion import CompletionOutcome, ProbeOutcome
from kalpamani.data.qualify.sharadar.parser import ParsedPage

#: The pagination admission policy version. Recorded in every manifest. The v1 policy
#: (``sharadar-pagination-admission-v1``: a short first page and header-only later pages)
#: is superseded and no longer admits anything.
PAGINATION_POLICY_VERSION: Final = "sharadar-pagination-admission-v2"
SUPERSEDED_PAGINATION_POLICY_VERSIONS: Final[frozenset[str]] = frozenset(
    {"sharadar-pagination-admission-v1"}
)


class PaginationDefect(StrEnum):
    """Why a page group was refused. Closed; never a value, never a row."""

    PAGE_OVER_LIMIT = "PAGE_OVER_LIMIT"
    PAGINATION_INCONSISTENT = "PAGINATION_INCONSISTENT"
    DELIVERY_TRUNCATED = "DELIVERY_TRUNCATED"
    PAGINATION_UNSUPPORTED = "PAGINATION_UNSUPPORTED"
    COMPLETION_UNPROVEN = "COMPLETION_UNPROVEN"


class PaginationError(Exception):
    """One closed defect, raised ``from None``."""

    __slots__ = ("defect",)

    def __init__(self, defect: PaginationDefect) -> None:
        if type(defect) is not PaginationDefect:
            raise TypeError("defect must be an exact PaginationDefect member")
        self.defect = defect
        super().__init__(f"pagination refused: {defect.value}")


def _refuse(defect: PaginationDefect) -> PaginationError:
    return PaginationError(defect)


GroupKey = tuple[str, str, str, tuple[tuple[str, str], ...]]


@dataclass(frozen=True, slots=True, kw_only=True)
class GroupAdmission:
    """One admitted group: its key, its raw row count and how completion was proved."""

    run_id: str
    dataset: str
    window: str
    predicate: tuple[tuple[str, str], ...]
    rows: int
    governed_limit: int
    completion: CompletionOutcome

    @property
    def is_empty(self) -> bool:
        """A header-only page: pagination-consistent, and no claim about the window."""
        return self.rows == 0

    @property
    def probed(self) -> bool:
        """Whether completion was proved by a passed probe rather than a short page."""
        return self.completion is CompletionOutcome.PROBE_PASSED


@dataclass(frozen=True, slots=True, kw_only=True)
class PaginationSummary:
    """Per dataset: how many groups were admitted, how many were empty, how many probed."""

    policy_version: str
    groups_admitted: dict[str, int]
    groups_empty: dict[str, int]
    groups_probed: dict[str, int]

    def document(self) -> dict[str, Any]:
        """The manifest's pagination record."""
        return {
            "policy_version": self.policy_version,
            "supported_shape": (
                "one data page per group at offset zero and the governed limit; "
                "fewer rows than the limit complete without a probe; exactly the limit "
                "complete only with a passed zero-row completion probe of equal schema"
            ),
            "groups_admitted": dict(sorted(self.groups_admitted.items())),
            "groups_empty": dict(sorted(self.groups_empty.items())),
            "groups_probed": dict(sorted(self.groups_probed.items())),
            "establishes": [
                "no row remained beyond the governed limit at the probe instant, "
                "for every probed group"
            ],
            "does_not_establish": [
                "vendor completeness of the window",
                "inclusivity of the window's dates",
                "snapshot consistency across requests",
                "stable ordering across offsets",
            ],
        }


def _admit_group(pages: list[tuple[AcquiredPage, ParsedPage]]) -> GroupAdmission:
    if len(pages) != 1:
        raise _refuse(PaginationDefect.PAGINATION_UNSUPPORTED)
    page, parsed = pages[0]
    if page.page_offset != 0:
        raise _refuse(PaginationDefect.PAGINATION_UNSUPPORTED)
    evidence = page.pagination
    limit = page.page_limit
    if parsed.row_count > limit:
        raise _refuse(PaginationDefect.PAGE_OVER_LIMIT)
    # The recorded evidence must be the parsed facts: the same limit, the same raw row
    # count, the same schema digest. A disagreement is a contradiction, not a choice.
    if (
        evidence.governed_limit != limit
        or evidence.row_count != parsed.row_count
        or evidence.schema_digest != parsed.schema_digest
    ):
        raise _refuse(PaginationDefect.PAGINATION_INCONSISTENT)
    if parsed.row_count < limit:
        if evidence.completion is not CompletionOutcome.SHORT_PAGE_COMPLETE:
            raise _refuse(PaginationDefect.PAGINATION_INCONSISTENT)
        if evidence.probe is not None:
            raise _refuse(PaginationDefect.PAGINATION_INCONSISTENT)
    else:
        probe = evidence.probe
        if probe is None:
            raise _refuse(PaginationDefect.COMPLETION_UNPROVEN)
        if (
            probe.outcome is not ProbeOutcome.PROBE_PASSED
            or probe.row_count != 0
            or probe.schema_digest != parsed.schema_digest
            or probe.page_offset != limit
            or probe.page_limit != limit
            or evidence.completion is not CompletionOutcome.PROBE_PASSED
        ):
            raise _refuse(PaginationDefect.DELIVERY_TRUNCATED)
    return GroupAdmission(
        run_id=page.run_id,
        dataset=page.dataset,
        window=page.window,
        predicate=page.predicate,
        rows=parsed.row_count,
        governed_limit=limit,
        completion=evidence.completion,
    )


def admit_pagination(pages: list[tuple[AcquiredPage, ParsedPage]]) -> PaginationSummary:
    """Admit every (run, dataset, window, predicate) group of parsed pages, or refuse the input.

    Groups are formed from the pages' own compiled coordinates -- never across runs or
    windows -- and each is held to the supported shape independently. One refused group
    refuses the whole input; nothing is dropped and published without it.

    Raises:
        PaginationError: one closed defect for the first refused group, groups taken in
            sorted key order so the refusal is deterministic.
    """
    groups: dict[GroupKey, list[tuple[AcquiredPage, ParsedPage]]] = {}
    for page, parsed in pages:
        if type(page) is not AcquiredPage or type(parsed) is not ParsedPage:
            raise TypeError("pages must be exact (AcquiredPage, ParsedPage) pairs")
        key = (page.run_id, page.dataset, page.window, tuple(sorted(page.predicate)))
        groups.setdefault(key, []).append((page, parsed))
    admitted: dict[str, int] = {}
    empty: dict[str, int] = {}
    probed: dict[str, int] = {}
    for key in sorted(groups):
        group = _admit_group(groups[key])
        admitted[group.dataset] = admitted.get(group.dataset, 0) + 1
        empty[group.dataset] = empty.get(group.dataset, 0) + int(group.is_empty)
        probed[group.dataset] = probed.get(group.dataset, 0) + int(group.probed)
    return PaginationSummary(
        policy_version=PAGINATION_POLICY_VERSION,
        groups_admitted=admitted,
        groups_empty=empty,
        groups_probed=probed,
    )


__all__ = [
    "PAGINATION_POLICY_VERSION",
    "SUPERSEDED_PAGINATION_POLICY_VERSIONS",
    "GroupAdmission",
    "PaginationDefect",
    "PaginationError",
    "PaginationSummary",
    "admit_pagination",
]
