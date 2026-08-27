"""The anti-look-ahead query interface.

Every historical accessor takes an explicit ``as_of`` **and** an explicit
information-set profile. No defaults. No ``latest`` convenience. No overload
without them. A default here is a decision made silently by whoever wrote the
accessor rather than by whoever asked the question -- and the question is the
whole point: "as of 2015-06-30" is not one question, it is three, and which one
was answered has to be stated.

**A reader is bound to a verified publication.** It takes a
:class:`~kalpamani.data.curate.publication.VerifiedPublication` and nothing else
-- not a dataset, a manifest and a report passed side by side. Those three used
to be separate parameters, which meant the reader could only check them against
*each other*: that the manifest named the dataset, that the report hash matched.
A triplet assembled at a call site passes all of that, because none of it
compares anything to storage. Only the verified read path can produce a
``VerifiedPublication``, so a reader exists only where a verification happened.

There is no ``open_issues=()`` fallback either: a reader with no issue list used
to be a clean reader, which meant a caller obtained a clean result by omitting
evidence rather than by producing it. The report travels with the publication,
and its blocking findings are enforced automatically.

**A partial answer is refused, not truncated.** These are the situations a price
query can be in, and they are deliberately different answers:

======================================  ====================================
situation                               outcome
======================================  ====================================
valid session, security did not trade   **served** -- a zero-volume or stale
                                        bar is an answer
a required bar is missing               ``IncompleteCoverageError``
the security is unknown here            ``SecurityNotInDatasetError``
the range is outside declared coverage  ``DatasetCoverageError``
every admissible row is ineligible      ``RequiredInputUnavailableError``
======================================  ====================================

The last matters as much as the rest. A requested series emptied by origin
ineligibility is not a short series with a token attached -- it is a series that
could not be computed, and publishing an empty one would let a caller average
over nothing and get a number.

**Coverage is defined per resolution, and per exchange.** A security listed on
one venue is not required to have bars on another venue's sessions. Daily
coverage expects one bar per listed trading session; minute coverage requires the
session's whole endpoint grid, because one minute bar is not evidence that a
session was observed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from kalpamani.data.contracts.dataset import UniverseSnapshotHeader
from kalpamani.data.contracts.entities import Listing, MarketSession, PriceBar, PriceBarValues
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
    RequiredInputUnavailableError,
    SecurityNotInDatasetError,
)
from kalpamani.data.contracts.instants import normalize_instant
from kalpamani.data.contracts.profiles import DatasetResolutionEvidence, ProfileResolutionConfig
from kalpamani.data.contracts.resolution import (
    BoundApprovals,
    PitRecord,
    decision_available_time,
    is_eligible,
)
from kalpamani.data.contracts.vocabulary import (
    AdjustmentConvention,
    AdjustmentMode,
    BarResolution,
    InformationSetProfile,
    LimitationToken,
    RevisionView,
)
from kalpamani.data.curate.adjustment import SUPPORTED_CONVENTIONS, adjusted_series, raw_series
from kalpamani.data.curate.publication import DatasetManifest, VerifiedPublication
from kalpamani.data.curate.resolution_run import evidence_limitation_tokens
from kalpamani.data.curate.universe import current_listings
from kalpamani.data.pit.execution import ExecutionEvidence, ExecutionRecorder
from kalpamani.data.quality.report import QualityReport

#: Datasets a price query reads directly, in canonical order.
PRICE_HISTORY_DATASETS = ("corporate_action", "price_bar")

#: Datasets a universe query reads directly.
UNIVERSE_DATASETS = ("universe_membership",)

#: One minute. The grid a dense minute series is expected to cover.
_MINUTE = timedelta(minutes=1)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResultProvenance:
    """Where a result came from, and under what question it was asked."""

    dataset_version: str
    manifest_hash: str
    quality_report_hash: str
    as_of: datetime
    requested_profile: InformationSetProfile
    resolved_profile: InformationSetProfile
    revision_view: RevisionView | None
    limitations: tuple[LimitationToken, ...]
    resolution: BarResolution | None = None
    adjustment_convention: AdjustmentConvention | None = None

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
    """Serves historical queries from one verified, published Gold dataset.

    Constructed from the dataset, its manifest and its quality report together --
    the three things :func:`read_published_dataset` returns as a unit. A caller
    cannot hold the data without the evidence, and cannot vary either per query.
    """

    def __init__(
        self,
        publication: VerifiedPublication,
        *,
        resolution: ProfileResolutionConfig,
        approvals: BoundApprovals,
    ) -> None:
        """Bind the reader, refusing anything the publication does not support.

        Raises:
            DatasetPublicationError: if the run's resolution disagrees with the
                publication's -- profile, policy version, or the complete map
                with its reasons. The dataset/manifest/report agreement that used
                to be checked here is now a precondition of the type: a
                ``VerifiedPublication`` cannot exist without it.
        """
        manifest = publication.manifest
        if manifest.resolved_profile is not resolution.resolved_profile:
            raise DatasetPublicationError(
                f"Dataset {manifest.dataset_version} was curated under "
                f"{manifest.resolved_profile.value}; this run resolved to "
                f"{resolution.resolved_profile.value}. A dataset cannot answer a question it "
                "was not built for."
            )
        if manifest.resolution_policy_version != resolution.resolution_policy_version:
            raise DatasetPublicationError(
                f"Dataset {manifest.dataset_version} was resolved under policy "
                f"{manifest.resolution_policy_version!r}; this run declares "
                f"{resolution.resolution_policy_version!r}."
            )
        if manifest.resolution_map != resolution.canonical_map():
            raise DatasetPublicationError(
                f"Dataset {manifest.dataset_version} was built under a different resolution "
                "map than this run declares. The whole map is compared, reasons included: two "
                "runs that bounded the same dataset for different stated reasons resolved it "
                "differently and admitted different rows."
            )
        self._publication = publication
        self._dataset = publication.dataset
        self._manifest = manifest
        self._quality = publication.quality_report
        self._resolution = resolution
        self._approvals = approvals
        self._recorder = ExecutionRecorder(
            dataset_version=manifest.dataset_version,
            manifest_hash=manifest.manifest_hash,
            quality_hash=publication.quality_report.report_hash,
        )

    @property
    def resolved_profile(self) -> InformationSetProfile:
        """The profile every query on this reader actually executes under."""
        return self._resolution.resolved_profile

    @property
    def manifest(self) -> DatasetManifest:
        """The verified publication manifest this reader serves from."""
        return self._manifest

    @property
    def quality_report(self) -> QualityReport:
        """The quality evidence the publication was gated on."""
        return self._quality

    @property
    def publication(self) -> VerifiedPublication:
        """The verified publication this reader serves, seal included."""
        return self._publication

    def execution_evidence(self) -> ExecutionEvidence:
        """What this reader actually read, recorded as it read it.

        The research manifest is built from this rather than from arguments a
        caller supplies. An inventory the run produces cannot be shortened by
        omission: a dataset the query path did not record is a bug here, not a
        caller's prerogative.
        """
        return self._recorder.evidence()

    # -- accessors ---------------------------------------------------------

    def get_security_universe(
        self,
        *,
        as_of: datetime,
        profile: InformationSetProfile,
    ) -> UniverseSnapshotResult:
        """Membership as recorded for the latest built session at or before ``as_of``.

        Returns the **stored** snapshot. It is never recomputed from current data
        and never derived by filtering today's listed securities: a security
        delisted before ``as_of`` is absent, one delisted after it but active then
        is present.

        A snapshot whose rule genuinely selected nobody is a **valid** result --
        every row a non-member with its reason, or zero rows against a header
        saying the session was built. That is different from a session never
        built, and different again from one no row of which is admissible yet.

        Raises:
            MissingHistoricalSnapshotError: if no snapshot was **built** at or
                before that date, or none of its rows is admissible at ``as_of``.
        """
        cutoff = normalize_instant(as_of)
        self._guard(profile, cutoff, UNIVERSE_DATASETS)
        resolved = self.resolved_profile

        candidates = [
            session
            for session in self._dataset.built_snapshot_sessions()
            if session <= cutoff.date()
        ]
        if not candidates:
            raise MissingHistoricalSnapshotError(
                f"No universe snapshot was built at or before {cutoff.isoformat()} in dataset "
                f"{self._dataset.dataset_version}. A universe query for a date with no "
                "recorded membership is a refusal, not an empty result."
            )
        session_date = candidates[-1]
        header = self._dataset.universe_headers[session_date]
        rows = self._dataset.universe.get(session_date, ())
        self._require_snapshot_available(header, cutoff, resolved)

        admitted = []
        excluded: dict[tuple[str, str], int] = {}
        for row in rows:
            if not is_eligible(row, resolved):
                key = ("universe_membership", row.envelope.information_origin.value)
                excluded[key] = excluded.get(key, 0) + 1
                continue
            available = decision_available_time(row, resolved, self._approvals)
            if available is None or available > cutoff:
                continue
            admitted.append(row)

        if rows and not admitted:
            raise MissingHistoricalSnapshotError(
                f"The universe snapshot for {session_date.isoformat()} exists but no row in it "
                f"is admissible at {cutoff.isoformat()} under {resolved.value}. Serving an "
                "empty universe here would be indistinguishable from a rule that selected "
                "nobody, and the two mean opposite things."
            )

        definition_versions = {row.universe_definition_version for row in admitted}
        if len(definition_versions) > 1:
            raise ProfileResolutionError(
                f"The snapshot for {session_date.isoformat()} mixes universe definition "
                f"versions {sorted(definition_versions)}. Changing the rule creates a new "
                "version; it does not retroactively change history."
            )

        self._recorder.record_read(
            UNIVERSE_DATASETS,
            excluded_rows=sum(excluded.values()),
        )
        self._record_bounds(UNIVERSE_DATASETS)

        return UniverseSnapshotResult(
            session_date=session_date,
            universe_definition_version=(
                definition_versions.pop()
                if definition_versions
                else header.universe_definition_version
            ),
            members=tuple(sorted(row.security_id for row in admitted if row.is_member)),
            non_members=tuple(sorted(row.security_id for row in admitted if not row.is_member)),
            provenance=self._provenance(cutoff, profile, None, bool(excluded), None, None),
            origin_exclusions=_counts(excluded),
        )

    def _require_snapshot_available(
        self,
        header: UniverseSnapshotHeader,
        cutoff: datetime,
        resolved: InformationSetProfile,
    ) -> None:
        """Refuse a snapshot the run could not yet have held.

        The header is a derived artifact and therefore has an availability of its
        own. It matters most in the case that has no rows to carry the constraint
        instead: a snapshot whose rule selected nobody. Under ``FORWARD_SYSTEM``
        -- the profile that asks what *we* held -- we did not know the rule
        selected nobody before we ran it. We knew nothing.

        Raises:
            MissingHistoricalSnapshotError: if the snapshot was not yet built at
                ``cutoff``, or does not assert a complete build.
        """
        if not header.is_complete:
            raise MissingHistoricalSnapshotError(
                f"The universe snapshot for {header.session_date.isoformat()} declares status "
                f"{header.status!r}. A partial snapshot answers the membership question with a "
                "subset, and nothing in the answer would say so."
            )
        if (
            resolved is InformationSetProfile.FORWARD_SYSTEM
            and header.envelope.artifact_first_built_time > cutoff
        ):
            raise MissingHistoricalSnapshotError(
                f"The universe snapshot for {header.session_date.isoformat()} was first built "
                f"at {header.envelope.artifact_first_built_time.isoformat()}, after "
                f"{cutoff.isoformat()}. Under FORWARD_SYSTEM the question is what this system "
                "held at that moment, and it held no snapshot -- serving one now would answer "
                "a different question, and a zero-row snapshot would answer it invisibly."
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

        ``adjustment_mode`` is required, and an adjusted mode must name both a
        policy and a convention. "The adjusted close on a date" is not a number --
        it is a number *per information set and per convention* -- so all of it
        has to be named before the question has an answer.

        Raises:
            QueryRangeError: if ``start`` is after ``end``, or an adjusted mode
                names no convention.
            DatasetCoverageError: if the range falls outside declared coverage.
            SecurityNotInDatasetError: if the dataset has no evidence of this
                security at all.
            IncompleteCoverageError: if a bar the range requires is missing.
            RequiredInputUnavailableError: if every bar in range is ineligible or
                unresolvable under the resolved profile.
        """
        cutoff = normalize_instant(as_of)
        self._guard(profile, cutoff, PRICE_HISTORY_DATASETS)
        self._validate_range(start, end)
        convention = _validate_adjustment_mode(adjustment_mode)

        if not self._dataset.knows_security(security_id):
            raise SecurityNotInDatasetError(
                f"Dataset {self._dataset.dataset_version} holds no listing, bar or attribute "
                f"for {security_id!r}. That is a question this dataset cannot answer, which "
                "is not the same as a security that simply did not trade."
            )

        held = self._dataset.bars_for(security_id, resolution.value)
        in_range = tuple(bar for bar in held if start <= bar.session_date <= end)
        self._require_complete_series(
            security_id=security_id,
            resolution=resolution,
            start=start,
            end=end,
            held=in_range,
        )

        resolved = self.resolved_profile
        excluded: dict[tuple[str, str], int] = {}
        unresolvable = 0
        bars: list[PriceBar] = []
        for bar in in_range:
            if not is_eligible(bar, resolved):
                key = ("price_bar", bar.envelope.information_origin.value)
                excluded[key] = excluded.get(key, 0) + 1
                continue
            available = decision_available_time(bar, resolved, self._approvals)
            if available is None:
                unresolvable += 1
                continue
            if available > cutoff:
                continue
            bars.append(bar)

        if in_range and not bars and (excluded or unresolvable):
            raise RequiredInputUnavailableError(
                f"REQUIRED_INPUT_UNAVAILABLE: every {resolution.value} bar for {security_id} "
                f"in {start.isoformat()}..{end.isoformat()} is ineligible under "
                f"{resolved.value} or has unresolvable availability "
                f"({sum(excluded.values())} ineligible, {unresolvable} unresolvable). A series "
                "that could not be computed is not a short series with a token attached: "
                "publishing an empty one would let a caller average over nothing and get a "
                "number."
            )

        actions = [
            action
            for action in self._dataset.actions_for(security_id)
            if is_eligible(action, resolved)
        ]

        if adjustment_mode.is_raw:
            series = raw_series(bars)
        else:
            assert adjustment_mode.policy is not None
            assert adjustment_mode.convention is not None
            series = adjusted_series(
                bars,
                actions,
                policy=adjustment_mode.policy,
                convention=adjustment_mode.convention,
                as_of_epoch=cutoff,
                resolved_profile=resolved,
                approvals=self._approvals,
            )

        self._recorder.record_read(
            PRICE_HISTORY_DATASETS,
            revisable=("corporate_action",),
            excluded_rows=sum(excluded.values()),
        )
        self._record_bounds(PRICE_HISTORY_DATASETS)

        return BarSeriesResult(
            security_id=security_id,
            resolution=resolution,
            adjustment_mode=adjustment_mode,
            bars=series,
            provenance=self._provenance(
                cutoff, profile, None, bool(excluded), resolution, convention
            ),
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

        The interface contract is retained so its shape -- mandatory ``as_of``,
        mandatory profile, no defaults -- is fixed before anything populates it,
        rather than negotiated later by whoever needs the data first.

        Raises:
            PendingContractError: always, naming what is missing. The contract is
                settled; the data is not present. Returning ``None`` or an empty
                result would say the opposite.
        """
        self._guard(profile, normalize_instant(as_of), ())
        raise PendingContractError(
            "get_classification is contractually defined but classification_history is not "
            "in the Phase-3A entity subset and no Phase-3A fixture carries it. This is a "
            "declared gap, not an empty result: a caller must be able to tell 'not built "
            f"yet' from 'this security has no sector' (requested security_id={security_id!r})."
        )

    # -- shared guards -----------------------------------------------------

    def _record_bounds(self, datasets: Sequence[str]) -> None:
        """Record every bounded availability an answer over ``datasets`` leant on.

        Read from the publication's own resolution evidence, not from a caller's
        declaration. A bound is unapproved when its derivation is not approved
        for that dataset -- which resolution refuses at build time, so a run
        recording one here means the publication should not have existed.
        """
        wanted = set(datasets)
        for entry in self._dataset.resolution_evidence:
            if entry.dataset not in wanted:
                continue
            if entry.provider_bounded_rows or entry.public_bounded_rows:
                self._recorder.record_bound(
                    entry.dataset,
                    approved=_bounds_are_approved(self._approvals, entry),
                )

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

    def _listing_venues(self, security_id: str) -> tuple[Listing, ...]:
        return tuple(
            listing
            for listing in current_listings(self._dataset.listings)
            if listing.security_id == security_id
        )

    def _required_sessions(
        self, security_id: str, start: date, end: date
    ) -> tuple[MarketSession, ...]:
        """Sessions the security's own venue traded, on which it was listed.

        Per exchange, deliberately. A NASDAQ security is not required to have bars
        on an NYSE-only session, and pooling calendars would fault it for absences
        that are not absences.
        """
        listings = self._listing_venues(security_id)
        if not listings:
            return ()
        required = [
            session
            for session in self._dataset.sessions
            if not session.is_holiday
            and start <= session.session_date <= end
            and any(
                listing.exchange is session.exchange and listing.is_listed_on(session.session_date)
                for listing in listings
            )
        ]
        return tuple(sorted(required, key=lambda item: item.session_date))

    def _require_complete_series(
        self,
        *,
        security_id: str,
        resolution: BarResolution,
        start: date,
        end: date,
        held: Sequence[PriceBar],
    ) -> None:
        """Coverage is defined per resolution, and checked against the venue's calendar.

        Deliberately independent of ``as_of``: dataset completeness and
        point-in-time availability are different questions. A bar that exists but
        was not yet knowable is filtered afterwards, correctly. A bar that does
        not exist at all is a gap, and a gap is a refusal.
        """
        sessions = self._required_sessions(security_id, start, end)
        if not sessions:
            return
        if resolution is BarResolution.DAILY:
            covered = {bar.session_date for bar in held}
            missing = [s.session_date for s in sessions if s.session_date not in covered]
            if missing:
                raise IncompleteCoverageError(
                    f"Dataset {self._dataset.dataset_version} has no DAILY bar for "
                    f"{security_id} on {len(missing)} listed trading session(s) in "
                    f"{start.isoformat()}..{end.isoformat()}: "
                    f"{[d.isoformat() for d in missing[:5]]}"
                    f"{' ...' if len(missing) > 5 else ''}. Refused rather than truncated: a "
                    "short series and a gap-ridden one look identical downstream. A session "
                    "the security did not trade is still covered by an explicit no-trade bar."
                )
            return

        # MINUTE follows contract A -- dense bars. The expected endpoint grid comes
        # from the session itself, so "at least one minute bar that day" cannot
        # pass for a session that was actually observed.
        endpoints = {bar.bar_end_time for bar in held}
        for session in sessions:
            expected = _minute_endpoints(session)
            missing_points = sorted(point for point in expected if point not in endpoints)
            if missing_points:
                raise IncompleteCoverageError(
                    f"Dataset {self._dataset.dataset_version} covers "
                    f"{len(expected) - len(missing_points)} of {len(expected)} expected MINUTE "
                    f"endpoints for {security_id} on session "
                    f"{session.session_date.isoformat()} (first missing "
                    f"{missing_points[0].isoformat()}). One minute bar in a session is not "
                    "evidence that the session was observed, so a dense minute series must "
                    "cover the whole regular grid."
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
        blocking = self._quality.blocking_for(datasets)
        if blocking:
            names = sorted({finding.check_name for finding in blocking})
            raise BlockingQualityIssueError(
                f"{len(blocking)} open BLOCKING quality finding(s) stand against datasets this "
                f"query touches ({names}). Every dependent result is refused, not annotated, "
                "and the evidence travels with the publication so it cannot be omitted."
            )

    def _provenance(
        self,
        as_of: datetime,
        requested: InformationSetProfile,
        revision_view: RevisionView | None,
        had_exclusions: bool,
        resolution: BarResolution | None,
        convention: AdjustmentConvention | None,
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
            manifest_hash=self._manifest.manifest_hash,
            quality_report_hash=self._quality.report_hash,
            as_of=as_of,
            requested_profile=requested,
            resolved_profile=self.resolved_profile,
            revision_view=revision_view,
            limitations=tuple(limitations),
            resolution=resolution,
            adjustment_convention=convention,
        )


def _bounds_are_approved(approvals: BoundApprovals, entry: DatasetResolutionEvidence) -> bool:
    """Whether the bounds a dataset relied on were approved for it.

    A bounded availability with no approved derivation for its dataset is a bound
    nobody sanctioned. Resolution refuses those at build time, so a run that
    records one is telling the manifest that the publication should not exist --
    which is exactly the thing a caller-supplied list could previously omit.
    """
    policy = approvals.for_dataset(entry.dataset)
    if entry.provider_bounded_rows and not policy.provider:
        return False
    return not (entry.public_bounded_rows and not policy.public)


def _minute_endpoints(session: MarketSession) -> tuple[datetime, ...]:
    """Every minute endpoint a dense series is expected to cover for a session."""
    points: list[datetime] = []
    point = session.regular_open + _MINUTE
    while point <= session.regular_close:
        points.append(point)
        point += _MINUTE
    return tuple(points)


def _validate_adjustment_mode(mode: AdjustmentMode) -> AdjustmentConvention | None:
    """Refuse a mode whose convention this reader cannot compute.

    ``RAW`` names no convention because there is nothing to convene about.
    Anything adjusted names one, and it must be one the implementation actually
    produces -- accepting a name it does not compute would put a label on a series
    the numbers contradict.
    """
    if mode.is_raw:
        return None
    if mode.convention is None:
        raise QueryRangeError(
            "An adjusted series must name its convention. Two conventions over the same "
            "actions produce two different series, and a result labelled only by policy "
            "cannot say which one it is."
        )
    if mode.convention not in SUPPORTED_CONVENTIONS:
        raise PendingContractError(
            f"Adjustment convention {mode.convention.value} is defined in the vocabulary but "
            f"this implementation computes {sorted(c.value for c in SUPPORTED_CONVENTIONS)}. "
            "Accepting a convention it does not compute would label a series with something "
            "the numbers contradict."
        )
    return mode.convention


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

    cutoff = normalize_instant(as_of)
    admissible = []
    for record in revisions:
        if not is_eligible(record, resolved_profile):
            continue
        available = decision_available_time(record, resolved_profile, approvals)
        if available is None or available > cutoff:
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
