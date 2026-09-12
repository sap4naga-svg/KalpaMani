"""Pagination admission for verified build inputs: the one supported page shape, or a refusal.

**What a COMPLETE locator proves, and what it does not.** A COMPLETE acquisition locator
proves that every compiled request has confirmed publication dispositions -- every page
the plan asked for was delivered and written. It says nothing about whether those pages,
read together, are the vendor's whole answer to the window: the vendor documents offset
pagination but no terminal-page signal and no stable order across offsets
(`PSR-SHD-133`), so two data-bearing pages of one window cannot be shown to partition the
result without duplication or omission. **An empty terminal page does not establish
stable ordering or snapshot consistency across earlier pages** -- it proves only that no
rows remained beyond the last offset asked for.

**The supported shape**, applied per group -- one acquisition run, one dataset, one exact
compiled window, never combined across runs or windows:

- the offset-zero page carries **fewer raw data rows than its requested limit**;
- every later compiled page of the group is present, validly parsed and **header-only**.

A group whose every page is header-only is *pagination-consistent* and nothing more: it
does not prove the window should be empty, and the calendar, completeness and
empty-result rules downstream still apply. **Row counts are raw** -- taken from the
parsed page before any deduplication, revision consolidation, symbol mapping or
filtering -- so a full page of repeated rows is a full page.

**Refused**, each with its own closed member: a page carrying more rows than its
requested limit; an offset-zero page at or above its limit (truncated/full-page
uncertainty -- an empty later page does not rescue it); a non-empty page at a positive
offset (unsupported multi-page delivery, for all three datasets); an empty earlier page
followed by a non-empty later one, or offsets that are not the compiled sequence
(structural inconsistency). Missing, duplicated or altered coordinates are refused
earlier by the accepted locator validator and never reach this gate.

**The limits of the supported shape are stated, not implied.** It avoids reliance on
multiple data-bearing offset pages. It does **not** establish vendor completeness, the
inclusivity of the window's dates, or the consistency of a snapshot delivered across
several requests; unique rows across pages do not establish that no rows were omitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.production.sharadar.build_inputs import AcquiredPage
from kalpamani.data.qualify.sharadar.parser import ParsedPage

#: The pagination admission policy version. Recorded in every manifest.
PAGINATION_POLICY_VERSION: Final = "sharadar-pagination-admission-v1"


class PaginationDefect(StrEnum):
    """Why a page group was refused. Closed; never a value, never a row."""

    PAGE_OVER_LIMIT = "PAGE_OVER_LIMIT"
    PAGINATION_INCONSISTENT = "PAGINATION_INCONSISTENT"
    DELIVERY_TRUNCATED = "DELIVERY_TRUNCATED"
    PAGINATION_UNSUPPORTED = "PAGINATION_UNSUPPORTED"


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


GroupKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True, kw_only=True)
class GroupAdmission:
    """One admitted group: its key, its raw first-page count and its page count."""

    run_id: str
    dataset: str
    window: str
    pages: int
    first_page_rows: int

    @property
    def is_empty(self) -> bool:
        """Every page header-only: pagination-consistent, and no claim about the window."""
        return self.first_page_rows == 0


@dataclass(frozen=True, slots=True, kw_only=True)
class PaginationSummary:
    """Per dataset: how many groups were admitted, and how many of them were empty."""

    policy_version: str
    groups_admitted: dict[str, int]
    groups_empty: dict[str, int]

    def document(self) -> dict[str, Any]:
        """The manifest's pagination record."""
        return {
            "policy_version": self.policy_version,
            "supported_shape": "first page below its limit; every later page header-only",
            "groups_admitted": dict(sorted(self.groups_admitted.items())),
            "groups_empty": dict(sorted(self.groups_empty.items())),
            "establishes": [],
            "does_not_establish": [
                "vendor completeness of the window",
                "inclusivity of the window's dates",
                "snapshot consistency across requests",
                "stable ordering across offsets",
            ],
        }


def _admit_group(pages: list[tuple[AcquiredPage, ParsedPage]]) -> GroupAdmission:
    ordered = sorted(pages, key=lambda item: item[0].page_offset)
    first_page, _ = ordered[0]
    limit = first_page.page_limit
    # Every page is held to its own requested limit before anything else is read.
    for page, parsed in ordered:
        if parsed.row_count > page.page_limit:
            raise _refuse(PaginationDefect.PAGE_OVER_LIMIT)
    # The compiled sequence: offsets 0, limit, 2*limit, ... with one limit throughout.
    for index, (page, _) in enumerate(ordered):
        if page.page_limit != limit or page.page_offset != index * limit:
            raise _refuse(PaginationDefect.PAGINATION_INCONSISTENT)
    counts = [parsed.row_count for _, parsed in ordered]
    later_with_rows = [count for count in counts[1:] if count > 0]
    if later_with_rows:
        # Data beyond the first page. After an empty first page it is a structural
        # contradiction; otherwise it is the multi-page delivery no accepted contract
        # can make safe, whatever the rows look like.
        if counts[0] == 0:
            raise _refuse(PaginationDefect.PAGINATION_INCONSISTENT)
        raise _refuse(PaginationDefect.PAGINATION_UNSUPPORTED)
    if counts[0] >= limit:
        raise _refuse(PaginationDefect.DELIVERY_TRUNCATED)
    return GroupAdmission(
        run_id=first_page.run_id,
        dataset=first_page.dataset,
        window=first_page.window,
        pages=len(ordered),
        first_page_rows=counts[0],
    )


def admit_pagination(pages: list[tuple[AcquiredPage, ParsedPage]]) -> PaginationSummary:
    """Admit every (run, dataset, window) group of parsed pages, or refuse the input.

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
        groups.setdefault((page.run_id, page.dataset, page.window), []).append((page, parsed))
    admitted: dict[str, int] = {}
    empty: dict[str, int] = {}
    for key in sorted(groups):
        group = _admit_group(groups[key])
        admitted[group.dataset] = admitted.get(group.dataset, 0) + 1
        empty[group.dataset] = empty.get(group.dataset, 0) + int(group.is_empty)
    return PaginationSummary(
        policy_version=PAGINATION_POLICY_VERSION, groups_admitted=admitted, groups_empty=empty
    )


__all__ = [
    "PAGINATION_POLICY_VERSION",
    "GroupAdmission",
    "PaginationDefect",
    "PaginationError",
    "PaginationSummary",
    "admit_pagination",
]
