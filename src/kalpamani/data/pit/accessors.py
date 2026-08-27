"""The anti-look-ahead query interface.

Every historical accessor takes an explicit ``as_of`` **and** an explicit
information-set profile. No defaults. No ``latest`` convenience. No overload
without them. A default here is a decision made silently by whoever wrote the
accessor rather than by whoever asked the question -- and the question is the
whole point: "as of 2015-06-30" is not one question, it is three, and which one
was answered has to be stated.

Enforced structurally, by test, in the manner ADR-0004 s.10 already uses for the
execution boundary:

- ``as_of``, ``profile``, ``resolution`` and ``adjustment_mode`` are
  **keyword-only with no defaults**, so omitting one is a ``TypeError`` at the
  call site rather than a quiet fallback.
- **A price series is one resolution.** Mixing daily and minute rows is not a
  series; it is two series stacked, and every statistic over it is wrong.
- No ``latest`` / ``current`` / ``most_recent`` / ``today`` identifier exists in
  this package, and a static test asserts it.
- Ineligible rows are **excluded and counted**, never substituted.
- Every result carries its own provenance: dataset version, ``as_of``, requested
  and resolved profile, the resolution served, and the limitations that applied.

**A partial answer is refused, not truncated.** These are the four situations a
price query can be in, and they are deliberately four different answers:

======================================  ===================================
situation                               outcome
======================================  ===================================
valid session, security did not trade   **served** -- a zero-volume or stale
                                        bar is an answer
a required bar is missing               ``IncompleteCoverageError``
the security is unknown here            ``SecurityNotInDatasetError``
the range is outside declared coverage  ``DatasetCoverageError``
======================================  ===================================

A short series and a gap-ridden one look identical downstream, and only one of
them is a result.

**The reader verifies the dataset it was handed.** A build carries the profile
and resolution policy it was curated under; a reader configured differently is
refused at construction rather than served something relabelled.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from kalpamani.data.contracts.dataset import GoldDataset
from kalpamani.data.contracts.entities import DataQualityIssue, PriceBar, PriceBarValues
from kalpamani.data.contracts.envelope import SourceEnvelope
from kalpamani.data.contracts.errors import (
    BlockingQualityIssueError,
    DatasetCoverageError,
    DatasetPublicationError,
    IncompleteCoverageError,
    MissingHistoricalSnapshotError,
    NonPointInTimeViewError,
    PendingContractError,
    ProfileResolutionError,
    QueryRangeError,
    SecurityNotInDatasetError,
)
from kalpamani.data.contracts.profiles import ProfileResolutionConfig
from kalpamani.data.contracts.resolution import (
    BoundApprovals,
    PitRecord,
    decision_available_time,
    is_eligible,
)
from kalpamani.data.contracts.vocabulary import (
    AdjustmentMode,
    BarResolution,
    InformationSetProfile,
    LimitationToken,
    RevisionView,
)
from kalpamani.data.curate.adjustment import adjusted_series, raw_series
from kalpamani.data.curate.resolution_run import evidence_limitation_tokens
from kalpamani.data.curate.universe import current_listings

#: Datasets a price query reads directly, in canonical order.
PRICE_HISTORY_DATASETS = ("corporate_action", "price_bar")

#: Datasets a universe query reads directly.
UNIVERSE_DATASETS = ("universe_membership",)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResultProvenance:
    """Where a result came from, and under what question it was asked."""

    dataset_version: str
    as_of: datetime
    requested_profile: InformationSetProfile
    resolved_profile: InformationSetProfile
    revision_view: RevisionView | None
    limitations: tuple[LimitationToken, ...]
    resolution: BarResolution | None = None

    @property
    def was_downgraded(self) -> bool:
        """Whether the run executed under a different profile than it asked for."""
        return self.resolved_profile is not self.requested_profile


@dataclass(frozen=True, slots=True, kw_only=True)
class OriginExclusionCount:
    """Rows dropped for ineligibility, counted by dataset and origin."""

    dataset: str
    information_origin: str
    rows: int


@dataclass(frozen=True, slots=True, kw_only=True)
class UniverseSnapshotResult:
    """Membership as **recorded** for a session, never as recomputed today."""

    session_date: date
    universe_definition_version: str
    members: tuple[str, ...]
    non_members: tuple[str, ...]
    provenance: ResultProvenance
    origin_exclusions: tuple[OriginExclusionCount, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class BarSeriesResult:
    """A price series, with the question it answered stated on it."""

    security_id: str
    resolution: BarResolution
    adjustment_mode: AdjustmentMode
    bars: tuple[PriceBarValues, ...]
    provenance: ResultProvenance
    origin_exclusions: tuple[OriginExclusionCount, ...] = ()


class PointInTimeReader:
    """Serves historical queries from one published, versioned Gold dataset.

    Bound at construction to the dataset, the run's profile resolution, the
    approved-bound policy and the open quality issues -- so a caller cannot vary
    any of them per query and produce a result set that mixes profiles or admits
    rows the resolution excluded.
    """

    def __init__(
        self,
        dataset: GoldDataset,
        *,
        resolution: ProfileResolutionConfig,
        approvals: BoundApprovals,
        open_issues: Sequence[DataQualityIssue] = (),
    ) -> None:
        """Bind the reader, refusing a dataset this run cannot legitimately read.

        Raises:
            DatasetPublicationError: if the dataset was curated under a different
                resolved profile or a different resolution policy. Serving it
                anyway would relabel a build as something it is not, which is the
                profile substitution the contract exists to prevent.
        """
        if dataset.resolved_profile is not resolution.resolved_profile:
            raise DatasetPublicationError(
                f"Dataset {dataset.dataset_version} was curated under "
                f"{dataset.resolved_profile.value}; this run resolved to "
                f"{resolution.resolved_profile.value}. A dataset cannot answer a question it "
                "was not built for."
            )
        if dataset.resolution_policy_version != resolution.resolution_policy_version:
            raise DatasetPublicationError(
                f"Dataset {dataset.dataset_version} was resolved under policy "
                f"{dataset.resolution_policy_version!r}; this run declares "
                f"{resolution.resolution_policy_version!r}. Two runs that resolved the same "
                "gaps differently admit different rows."
            )
        self._dataset = dataset
        self._resolution = resolution
        self._approvals = approvals
        self._open_issues = tuple(open_issues)

    @property
    def resolved_profile(self) -> InformationSetProfile:
        """The profile every query on this reader actually executes under."""
        return self._resolution.resolved_profile

    # -- accessors ---------------------------------------------------------

    def get_security_universe(
        self,
        *,
        as_of: datetime,
        profile: InformationSetProfile,
    ) -> UniverseSnapshotResult:
        """Membership as recorded for the session that ``as_of`` falls on or after.

        Returns the **stored** snapshot for the latest session at or before
        ``as_of`` whose membership was admissible by then. It is never recomputed
        from current data and never derived by filtering today's listed
        securities: a security delisted before ``as_of`` is absent, and one
        delisted after it but active then is present.

        A snapshot whose rule genuinely selected nobody is a **valid** result: its
        rows are all non-members, each with an exclusion reason. That is different
        from a snapshot that does not exist, and different again from one no row
        of which is admissible yet -- both of which are refusals.

        Raises:
            MissingHistoricalSnapshotError: if no snapshot exists at or before
                that date, or none of its rows is admissible at ``as_of``.
        """
        self._guard(profile, as_of, UNIVERSE_DATASETS)
        resolved = self.resolved_profile

        candidates = [
            session for session in sorted(self._dataset.universe) if session <= as_of.date()
        ]
        if not candidates:
            raise MissingHistoricalSnapshotError(
                f"No universe_membership snapshot exists at or before {as_of.isoformat()} in "
                f"dataset {self._dataset.dataset_version}. A universe query for a date with "
                "no recorded membership is a refusal, not an empty result."
            )
        session_date = candidates[-1]
        rows = self._dataset.universe[session_date]

        admitted = []
        excluded: dict[tuple[str, str], int] = {}
        for row in rows:
            if not is_eligible(row, resolved):
                key = ("universe_membership", row.envelope.information_origin.value)
                excluded[key] = excluded.get(key, 0) + 1
                continue
            available = decision_available_time(row, resolved, self._approvals)
            if available is None or available > as_of:
                continue
            admitted.append(row)

        if not admitted:
            raise MissingHistoricalSnapshotError(
                f"The universe snapshot for {session_date.isoformat()} exists but no row in it "
                f"is admissible at {as_of.isoformat()} under {resolved.value}. Serving an "
                "empty universe here would be indistinguishable from a rule that selected "
                "nobody, and the two mean opposite things."
            )

        definition_versions = {row.universe_definition_version for row in admitted}
        if len(definition_versions) != 1:
            raise ProfileResolutionError(
                f"The snapshot for {session_date.isoformat()} mixes universe definition "
                f"versions {sorted(definition_versions)}. Changing the rule creates a new "
                "version; it does not retroactively change history."
            )

        return UniverseSnapshotResult(
            session_date=session_date,
            universe_definition_version=definition_versions.pop(),
            members=tuple(sorted(row.security_id for row in admitted if row.is_member)),
            non_members=tuple(sorted(row.security_id for row in admitted if not row.is_member)),
            provenance=self._provenance(as_of, profile, None, bool(excluded), None),
            origin_exclusions=_counts(excluded),
        )

    def get_price_history(
        self,
        *,
        security_id: str,
        start: date,
        end: date,
        resolution: BarResolution,
        adjustment_mode: AdjustmentMode,
        as_of: datetime,
        profile: InformationSetProfile,
    ) -> BarSeriesResult:
        """Raw or explicitly-policied adjusted bars for one security, at one resolution.

        ``adjustment_mode`` is required. "The adjusted close on a date" is not a
        number -- it is a number *per information set and per convention* -- so
        the policy, the convention, the resolved profile and the ``as_of`` that
        fixed which actions are admissible all have to be named before the
        question has an answer.

        Raises:
            QueryRangeError: if ``start`` is after ``end``.
            DatasetCoverageError: if the range falls outside declared coverage.
            SecurityNotInDatasetError: if the dataset has no evidence of this
                security at all.
            IncompleteCoverageError: if a bar the range requires is missing.
        """
        self._guard(profile, as_of, PRICE_HISTORY_DATASETS)
        self._validate_range(start, end)
        if not self._dataset.knows_security(security_id):
            raise SecurityNotInDatasetError(
                f"Dataset {self._dataset.dataset_version} holds no listing, bar or attribute "
                f"for {security_id!r}. That is a question this dataset cannot answer, which "
                "is not the same as a security that simply did not trade."
            )

        held = self._dataset.bars_for(security_id, resolution.value)
        in_range = [bar for bar in held if start <= bar.session_date <= end]
        self._require_complete_series(
            security_id=security_id,
            resolution=resolution,
            start=start,
            end=end,
            held=in_range,
        )

        resolved = self.resolved_profile
        excluded: dict[tuple[str, str], int] = {}
        bars = []
        for bar in in_range:
            if not is_eligible(bar, resolved):
                key = ("price_bar", bar.envelope.information_origin.value)
                excluded[key] = excluded.get(key, 0) + 1
                continue
            available = decision_available_time(bar, resolved, self._approvals)
            if available is None or available > as_of:
                continue
            bars.append(bar)

        actions = [
            action
            for action in self._dataset.actions_for(security_id)
            if is_eligible(action, resolved)
        ]

        if adjustment_mode.is_raw:
            series = raw_series(bars)
        else:
            assert adjustment_mode.policy is not None
            series = adjusted_series(
                bars,
                actions,
                policy=adjustment_mode.policy,
                as_of_epoch=as_of,
                resolved_profile=resolved,
                approvals=self._approvals,
            )

        return BarSeriesResult(
            security_id=security_id,
            resolution=resolution,
            adjustment_mode=adjustment_mode,
            bars=series,
            provenance=self._provenance(as_of, profile, None, bool(excluded), resolution),
            origin_exclusions=_counts(excluded),
        )

    def get_classification(
        self,
        *,
        security_id: str,
        as_of: datetime,
        profile: InformationSetProfile,
    ) -> None:
        """Sector and industry as classified at ``as_of``. **Pending in this slice.**

        The interface contract is retained here so its shape -- mandatory
        ``as_of``, mandatory profile, no defaults -- is fixed before anything
        populates it, rather than negotiated later by whoever needs the data
        first.

        ``classification_history`` is not in the Phase-3A entity subset and no
        fixture carries it, so there is nothing to serve.

        Raises:
            PendingContractError: always, naming what is missing. The contract is
                settled; the data is not present. Returning ``None`` or an empty
                result would say the opposite.
        """
        self._guard(profile, as_of, ())
        raise PendingContractError(
            "get_classification is contractually defined but classification_history is not "
            "in the Phase-3A entity subset and no Phase-3A fixture carries it. This is a "
            "declared gap, not an empty result: a caller must be able to tell 'not built "
            f"yet' from 'this security has no sector' (requested security_id={security_id!r})."
        )

    # -- shared guards -----------------------------------------------------

    def _validate_range(self, start: date, end: date) -> None:
        if start > end:
            raise QueryRangeError(
                f"start {start.isoformat()} is after end {end.isoformat()}. An inverted range "
                "is not an empty range; it is a mistake, and serving nothing would hide it."
            )
        if start < self._dataset.coverage_start:
            raise DatasetCoverageError(
                f"start {start.isoformat()} precedes the declared coverage start of dataset "
                f"{self._dataset.dataset_version} ({self._dataset.coverage_start.isoformat()}). "
                "An empty result here would look like a market with no securities in it."
            )
        if end > self._dataset.coverage_end:
            raise DatasetCoverageError(
                f"end {end.isoformat()} is past the declared coverage end of dataset "
                f"{self._dataset.dataset_version} ({self._dataset.coverage_end.isoformat()}). "
                "A partially covered request is refused rather than silently truncated."
            )

    def _require_complete_series(
        self,
        *,
        security_id: str,
        resolution: BarResolution,
        start: date,
        end: date,
        held: Sequence[PriceBar],
    ) -> None:
        """Every trading session the security was listed for must have a bar.

        Deliberately independent of ``as_of``: dataset completeness and
        point-in-time availability are different questions. A bar that exists but
        was not yet knowable is filtered afterwards, correctly. A bar that does
        not exist at all is a gap, and a gap is a refusal.
        """
        listed = _listing_sessions(self._dataset, security_id, start, end)
        if not listed:
            return
        covered = {bar.session_date for bar in held}
        missing = sorted(session for session in listed if session not in covered)
        if missing:
            raise IncompleteCoverageError(
                f"Dataset {self._dataset.dataset_version} has no {resolution.value} bar for "
                f"{security_id} on {len(missing)} listed trading session(s) in "
                f"{start.isoformat()}..{end.isoformat()}: {[d.isoformat() for d in missing[:5]]}"
                f"{' ...' if len(missing) > 5 else ''}. Refused rather than truncated: a short "
                "series and a gap-ridden one look identical downstream."
            )

    def _guard(
        self,
        profile: InformationSetProfile,
        as_of: datetime,
        datasets: Sequence[str],
    ) -> None:
        if profile is not self._resolution.requested_profile:
            raise ProfileResolutionError(
                f"This reader was bound to a run that requested "
                f"{self._resolution.requested_profile.value}; the query asks for "
                f"{profile.value}. A single result may not mix profiles, so the reader "
                "refuses rather than silently serving a second information set."
            )
        if as_of > self._dataset.build_time:
            raise DatasetCoverageError(
                f"as_of {as_of.isoformat()} is later than the build time of dataset "
                f"{self._dataset.dataset_version} ({self._dataset.build_time.isoformat()}). "
                "A cutoff after the build cannot be answered by it."
            )
        if as_of.date() < self._dataset.coverage_start:
            raise DatasetCoverageError(
                f"as_of {as_of.isoformat()} precedes the declared coverage start of dataset "
                f"{self._dataset.dataset_version} ({self._dataset.coverage_start.isoformat()}). "
                "An empty result here would look like a market with no securities in it."
            )
        blocking = [
            issue
            for issue in self._open_issues
            if issue.is_blocking_open and (not datasets or issue.dataset in datasets)
        ]
        if blocking:
            names = sorted({issue.check_name for issue in blocking})
            raise BlockingQualityIssueError(
                f"{len(blocking)} open BLOCKING quality issue(s) stand against datasets this "
                f"query touches ({names}). Every dependent result is refused, not annotated."
            )

    def _provenance(
        self,
        as_of: datetime,
        requested: InformationSetProfile,
        revision_view: RevisionView | None,
        had_exclusions: bool,
        resolution: BarResolution | None,
    ) -> ResultProvenance:
        limitations = list(
            evidence_limitation_tokens(
                self._dataset.resolution_evidence,
                downgraded=self.resolved_profile is not self._resolution.requested_profile,
            )
        )
        if had_exclusions:
            limitations.append(LimitationToken.ORIGIN_INELIGIBLE_ROWS_EXCLUDED)
        return ResultProvenance(
            dataset_version=self._dataset.dataset_version,
            as_of=as_of,
            requested_profile=requested,
            resolved_profile=self.resolved_profile,
            revision_view=revision_view,
            limitations=tuple(limitations),
            resolution=resolution,
        )


def _listing_sessions(
    dataset: GoldDataset,
    security_id: str,
    start: date,
    end: date,
) -> tuple[date, ...]:
    """Trading sessions in range on which the security was listed."""
    listings = [
        listing
        for listing in current_listings(dataset.listings)
        if listing.security_id == security_id
    ]
    if not listings:
        return ()
    return tuple(
        session
        for session in dataset.trading_sessions_between(start, end)
        if any(listing.is_listed_on(session) for listing in listings)
    )


def select_revision(
    revisions: Sequence[PitRecord],
    *,
    revision_view: RevisionView,
    as_of: datetime,
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
) -> PitRecord | None:
    """Pick one revision of a revisable fact under an explicitly named view.

    ``revision_view`` is required and never defaulted, for the same reason
    ``as_of`` is: a default here answers the question on the caller's behalf and
    does not tell them which question it answered.

    Raises:
        NonPointInTimeViewError: for ``LATEST_RESTATED``, which ignores ``as_of``
            entirely and is therefore not point-in-time. It is unreachable from
            research and backtest paths by static test, and refused here at
            runtime so the two enforcements agree.
    """
    if revision_view is RevisionView.LATEST_RESTATED:
        raise NonPointInTimeViewError(
            "LATEST_RESTATED ignores as_of entirely, so it is not a point-in-time view and "
            "is unreachable from research and backtest code. It exists for accounting-style "
            "analysis of restatement behaviour, which is a legitimate question that simply "
            "is not a simulation."
        )

    admissible = []
    for record in revisions:
        if not is_eligible(record, resolved_profile):
            continue
        available = decision_available_time(record, resolved_profile, approvals)
        if available is None or available > as_of:
            continue
        admissible.append(record)

    if not admissible:
        return None
    if revision_view is RevisionView.ORIGINAL_FILING_ONLY:
        originals = [r for r in admissible if _revision_sequence(r) == 0]
        return originals[0] if originals else None
    return max(admissible, key=_revision_sequence)


def _revision_sequence(record: PitRecord) -> int:
    envelope = record.envelope
    if isinstance(envelope, SourceEnvelope):
        return envelope.revision_sequence
    # A derived artifact has no revision chain: a rebuild from different lineage
    # is a different artifact with its own key, not a later revision of this one.
    return 0


def _counts(excluded: dict[tuple[str, str], int]) -> tuple[OriginExclusionCount, ...]:
    return tuple(
        OriginExclusionCount(dataset=dataset, information_origin=origin, rows=rows)
        for (dataset, origin), rows in sorted(excluded.items())
    )


__all__ = [
    "PRICE_HISTORY_DATASETS",
    "UNIVERSE_DATASETS",
    "BarSeriesResult",
    "OriginExclusionCount",
    "PointInTimeReader",
    "ResultProvenance",
    "UniverseSnapshotResult",
    "select_revision",
]
