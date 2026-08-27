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

**A partial answer is refused, not truncated -- after point-in-time filtering,
not only before it.** Physical coverage is necessary and was never sufficient.
The dataset holding five bars said nothing about how many of them a query at a
given ``as_of`` was entitled to see, so a series whose middle bar had not yet been
published came back four bars long with no indication that anything was missing.
A caller averaging it got a number.

Completeness is therefore checked **twice**, against the same expected endpoint
grid: once against what the dataset physically holds, and again against what
survived origin eligibility, availability resolution and the ``as_of`` cutoff. A
``REQUIRED`` series that loses an endpoint to either is refused, and the refusal
names why that endpoint went -- missing, ineligible, unresolvable, or not yet
published -- because those are four different problems with four different fixes.

A caller who genuinely wants whatever was knowable says so with
``SeriesRequirement.OPTIONAL`` and gets a labelled short series. Neither is a
default: like ``as_of`` and ``profile``, it is named at the call site.

These are the situations a price query can be in, and they are deliberately
different answers:

======================================  ====================================
situation                               outcome
======================================  ====================================
valid session, security did not trade   **served** -- a zero-volume or stale
                                        bar is an answer
a required bar is missing               ``IncompleteCoverageError``
a required bar is not yet available     ``IncompleteCoverageError`` -- shorten
                                        ``end``, or move ``as_of``
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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum

from kalpamani.data.contracts.dataset import UniverseSnapshotHeader
from kalpamani.data.contracts.entities import (
    CorporateAction,
    Listing,
    MarketSession,
    PriceBar,
    PriceBarValues,
    UniverseMembership,
)
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
    ListingFactKind,
    RevisionView,
)
from kalpamani.data.curate.adjustment import SUPPORTED_CONVENTIONS, adjusted_series, raw_series
from kalpamani.data.curate.lineage import lineage_fingerprint
from kalpamani.data.curate.publication import DatasetManifest, VerifiedPublication
from kalpamani.data.curate.resolution_run import evidence_limitation_tokens
from kalpamani.data.pit.execution import (
    _EXECUTION_TOKEN,
    ConsumedArtifactRecord,
    ExecutedResult,
    ExecutionEvidence,
    ExecutionRecorder,
    seal_executed_result,
)
from kalpamani.data.quality.report import QualityReport

#: Datasets an **adjusted** price query reads directly, in canonical order.
PRICE_HISTORY_DATASETS = ("corporate_action", "price_bar")

#: Datasets a **raw** price query reads. Deliberately narrower: a raw series does
#: not consult corporate actions, so recording one as read would put a dataset in
#: the run's inventory that the run never opened -- and would then demand
#: resolution evidence for it.
RAW_PRICE_DATASETS = ("price_bar",)

#: Datasets a universe query reads directly.
UNIVERSE_DATASETS = ("universe_membership",)

#: One minute. The grid a dense minute series is expected to cover.
_MINUTE = timedelta(minutes=1)


class SeriesRequirement(Enum):
    """Whether a caller will accept a series shorter than the range it asked for.

    Named explicitly at every call site, like every other decision a historical
    query makes. A truncated series is indistinguishable from a complete one once
    it is a list of numbers, so whether one is acceptable is the caller's
    question to answer out loud.
    """

    #: Every expected endpoint must survive point-in-time filtering, or refuse.
    REQUIRED = "REQUIRED"
    #: A short series is an acceptable answer. It is labelled as one.
    OPTIONAL = "OPTIONAL"


#: A position on the expected grid: a session date for DAILY, a bar endpoint for
#: MINUTE. Both render with ``isoformat``, and ``datetime`` is a subclass of
#: ``date`` -- so anything that needs to tell them apart must test ``datetime``
#: first, or every minute endpoint will answer to ``isinstance(x, date)``.
Endpoint = date | datetime


class _Withheld(Enum):
    """Why an endpoint the dataset holds did not reach the result."""

    INELIGIBLE_ORIGIN = "its origin is not eligible under this profile"
    UNRESOLVED_AVAILABILITY = "its availability does not resolve under this profile"
    NOT_YET_AVAILABLE = "it was not yet available at this as_of"


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
    #: The membership content hash the snapshot was published with. A caller
    #: citing this result can name exactly which snapshot it was.
    snapshot_content_hash: str = ""
    #: The derived artifact this result came from, by its derived identity.
    snapshot_artifact_id: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class BarSeriesResult:
    """A price series, with the question it answered stated on it."""

    security_id: str
    resolution: BarResolution
    adjustment_mode: AdjustmentMode
    bars: tuple[PriceBarValues, ...]
    provenance: ResultProvenance
    origin_exclusions: tuple[OriginExclusionCount, ...] = ()
    #: What the caller asked for. An ``OPTIONAL`` result may be shorter than the
    #: range, and says so here rather than leaving the reader to notice.
    requirement: SeriesRequirement = SeriesRequirement.REQUIRED
    #: Endpoints the dataset holds that this query was not entitled to see. Zero
    #: for a ``REQUIRED`` result, and that is enforced rather than asserted: a
    #: REQUIRED result carrying a withheld endpoint was the invariant's own
    #: counter-example, reached through bars the expected grid did not cover.
    withheld_endpoints: int = 0


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

    def seal(self, result: object, *, result_bytes: bytes) -> ExecutedResult:
        """Bind a result to the evidence this reader recorded while producing it.

        The only way to obtain an :class:`ExecutedResult`, and the only thing the
        research manifest accepts. A result and an inventory that travel
        separately can each be substituted; sealed together they cannot.

        ``result_bytes`` are the exact bytes the caller will emit, hashed here so
        the manifest's claim about what was produced is checked against the thing
        produced rather than against a description of it.
        """
        evidence = self._recorder.evidence()
        return seal_executed_result(
            result=result,
            result_bytes=result_bytes,
            evidence=evidence,
            dataset_version=self._manifest.dataset_version,
            publication_manifest_hash=self._manifest.manifest_hash,
            quality_report_hash=self._quality.report_hash,
            origin_exclusions=self._recorder.origin_exclusions(),
            bounds_relied_upon=evidence.bounds_relied_upon,
            token=_EXECUTION_TOKEN,
        )

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
        """The latest stored snapshot this query was entitled to, served **whole**.

        Returns the **stored** snapshot. It is never recomputed from current data
        and never derived by filtering today's listed securities: a security
        delisted before ``as_of`` is absent, one delisted after it but active then
        is present.

        **A snapshot is one derived artifact, and it is served or it is not.** The
        earlier implementation picked a session by UTC date and then filtered
        membership rows individually, which meant a row whose decision became
        available a moment later than its siblings simply vanished -- and the
        result was a membership set that had never existed at any instant. Nothing
        in it said so.

        Selection now works the other way round. A session is a candidate when its
        own ``evaluation_cutoff`` -- an absolute instant, so no UTC date
        truncation is involved -- is at or before ``as_of``. Candidates are tried
        latest-first, and the first whose snapshot is available **in its entirety**
        is served. If the latest is not yet complete at ``as_of``, the query falls
        back to the latest earlier one that is; if none is, it refuses.

        A snapshot whose rule genuinely selected nobody is a **valid** result --
        every row a non-member with its reason, or zero rows against a header
        saying the session was built. That is different from a session never
        built, and different again from one not yet complete at ``as_of``.

        Raises:
            MissingHistoricalSnapshotError: if no snapshot's evaluation cutoff had
                passed at ``as_of``, or none of those that had was completely
                available then. The refusal names why each candidate was rejected.
        """
        cutoff = normalize_instant(as_of)
        self._guard(profile, cutoff, UNIVERSE_DATASETS)
        resolved = self.resolved_profile

        governed = [
            (session, header)
            for session, header in sorted(self._dataset.universe_headers.items())
            if header.evaluation_cutoff <= cutoff
        ]
        if not governed:
            raise MissingHistoricalSnapshotError(
                f"No universe snapshot's evaluation cutoff had passed at {cutoff.isoformat()} "
                f"in dataset {self._dataset.dataset_version}. Candidacy is decided by the "
                "session's own cutoff rather than by truncating the instant to a UTC date, so "
                "a session that has not opened in its own venue's terms is not a candidate. A "
                "universe query for a date with no recorded membership is a refusal, not an "
                "empty result."
            )

        rejected: list[str] = []
        for session, header in reversed(governed):
            rows = self._dataset.universe.get(session, ())
            problems = self._snapshot_unavailable(header, rows, cutoff, resolved)
            if not problems:
                return self._serve_snapshot(session, header, rows, cutoff, profile)
            rejected.append(f"{session.isoformat()}: {'; '.join(problems)}")

        raise MissingHistoricalSnapshotError(
            f"No universe snapshot was completely available at {cutoff.isoformat()} under "
            f"{resolved.value} in dataset {self._dataset.dataset_version}. Candidates, latest "
            "first:\n  - "
            + "\n  - ".join(rejected)
            + "\nA snapshot is one derived artifact: serving the rows that happened to be "
            "available would produce a membership set that existed at no instant, and nothing "
            "in it would say so."
        )

    def _snapshot_unavailable(
        self,
        header: UniverseSnapshotHeader,
        rows: Sequence[UniverseMembership],
        cutoff: datetime,
        resolved: InformationSetProfile,
    ) -> list[str]:
        """Every reason this snapshot cannot be served whole at ``cutoff``.

        The header carries the fact of the build; the rows carry the decisions.
        Both have to have been available, because the snapshot is the conjunction
        of them -- which is exactly what makes serving a subset wrong rather than
        merely incomplete.

        Under ``FORWARD_SYSTEM`` the header's own first-built time binds even when
        there are no rows: before we ran the rule we did not know it selected
        nobody, we knew nothing.
        """
        problems: list[str] = []
        if not header.is_complete:
            problems.append(f"the header declares status {header.status!r}, not COMPLETE")
        if header.resolved_profile is not resolved:
            problems.append(
                f"the header is keyed to {header.resolved_profile.value}, not {resolved.value}"
            )
        if (
            resolved is InformationSetProfile.FORWARD_SYSTEM
            and header.envelope.artifact_first_built_time > cutoff
        ):
            problems.append(
                "it was first built at "
                f"{header.envelope.artifact_first_built_time.isoformat()}, after the cutoff"
            )

        ineligible = 0
        unresolved = 0
        pending: datetime | None = None
        for row in rows:
            if not is_eligible(row, resolved):
                ineligible += 1
                continue
            available = decision_available_time(row, resolved, self._approvals)
            if available is None:
                unresolved += 1
            elif available > cutoff:
                pending = available if pending is None else max(pending, available)
        if ineligible:
            problems.append(f"{ineligible} membership row(s) are ineligible under this profile")
        if unresolved:
            problems.append(f"{unresolved} membership row(s) have unresolvable availability")
        if pending is not None:
            problems.append(f"membership decisions were still arriving until {pending.isoformat()}")

        definitions = {row.universe_definition_version for row in rows}
        if len(definitions) > 1:
            problems.append(
                f"it mixes universe definition versions {sorted(definitions)}; changing the "
                "rule creates a new version rather than retroactively changing history"
            )
        elif definitions and header.universe_definition_version not in definitions:
            problems.append(
                f"its rows are keyed to {sorted(definitions)} and the header declares "
                f"{header.universe_definition_version!r}"
            )
        return problems

    def _serve_snapshot(
        self,
        session: date,
        header: UniverseSnapshotHeader,
        rows: Sequence[UniverseMembership],
        cutoff: datetime,
        requested: InformationSetProfile,
    ) -> UniverseSnapshotResult:
        """Return the whole snapshot, and record the derived artifact it came from.

        No source dataset is recorded. A universe query reads a **stored derived
        artifact**; it does not open the listing, attribute or bar tables, and
        recording ``universe_membership`` as a directly-read source dataset made
        the manifest demand provider-resolution evidence for a table no resolution
        ever produces evidence about.
        """
        self._recorder.record_read((), excluded_rows=0)
        self._recorder.record_artifact(_snapshot_artifact(header))

        return UniverseSnapshotResult(
            session_date=session,
            universe_definition_version=header.universe_definition_version,
            members=tuple(sorted(row.security_id for row in rows if row.is_member)),
            non_members=tuple(sorted(row.security_id for row in rows if not row.is_member)),
            provenance=self._provenance(cutoff, requested, None, False, None, None),
            origin_exclusions=(),
            snapshot_content_hash=header.snapshot_content_hash,
            snapshot_artifact_id=header.artifact_id,
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
        requirement: SeriesRequirement,
        revision_view: RevisionView | None,
    ) -> BarSeriesResult:
        """Raw or explicitly-policied adjusted bars for one security, at one resolution.

        ``adjustment_mode`` is required, and an adjusted mode must name both a
        policy and a convention. "The adjusted close on a date" is not a number --
        it is a number *per information set and per convention* -- so all of it
        has to be named before the question has an answer.

        ``revision_view`` follows the same rule, and only an **adjusted** query
        takes one. A raw series reads no corporate actions, so there are no
        revisions to choose between and supplying a view would suggest it did
        something. An adjusted series does read them, and a corporate action can
        be restated -- a ratio corrected, an ex-date moved -- so which revision was
        used is part of what the answer means.

        Completeness is enforced **after** point-in-time filtering as well as
        before it. Under ``SeriesRequirement.REQUIRED`` an endpoint lost to
        ineligibility, unresolvable availability or an ``as_of`` that precedes its
        publication refuses the whole series rather than shortening it.

        ``requirement`` has no default, for the reason nothing else here does: a
        default would answer on the caller's behalf whether a short series is an
        acceptable answer, and a short series is indistinguishable from a
        complete one once it is a list of numbers.

        Raises:
            QueryRangeError: if ``start`` is after ``end``, an adjusted mode names
                no convention, or ``revision_view`` disagrees with the mode.
            DatasetCoverageError: if the range falls outside declared coverage.
            SecurityNotInDatasetError: if the dataset has no evidence of this
                security at all.
            IncompleteCoverageError: if a bar the range requires is missing from
                the dataset, or was not servable at ``as_of``.
            RequiredInputUnavailableError: if every bar in range is ineligible or
                unresolvable under the resolved profile.
            NonPointInTimeViewError: if ``revision_view`` is ``LATEST_RESTATED``.
        """
        cutoff = normalize_instant(as_of)
        convention = _validate_adjustment_mode(adjustment_mode)
        view = _validate_revision_view(adjustment_mode, revision_view)
        datasets = RAW_PRICE_DATASETS if adjustment_mode.is_raw else PRICE_HISTORY_DATASETS

        self._guard(profile, cutoff, datasets)
        self._validate_range(start, end)

        if not self._dataset.knows_security(security_id):
            raise SecurityNotInDatasetError(
                f"Dataset {self._dataset.dataset_version} holds no listing, bar or attribute "
                f"for {security_id!r}. That is a question this dataset cannot answer, which "
                "is not the same as a security that simply did not trade."
            )

        held = self._dataset.bars_for(security_id, resolution.value)
        in_range = tuple(bar for bar in held if start <= bar.session_date <= end)
        expected = self._expected_endpoints(security_id, resolution, start, end, cutoff)
        if requirement is SeriesRequirement.REQUIRED and not expected:
            raise IncompleteCoverageError(
                f"Dataset {self._dataset.dataset_version} has no listed trading session for "
                f"{security_id} on its own venue between {start.isoformat()} and "
                f"{end.isoformat()}, so there is no grid a complete series could be measured "
                f"against -- and it holds {len(in_range)} bar(s) in that range. Completeness "
                "cannot be certified against a calendar that says nothing, and serving the "
                "bars that happen to exist is the truncation this refusal exists to prevent. "
                "Pass SeriesRequirement.OPTIONAL to accept whatever was knowable."
            )
        self._require_physical_coverage(
            security_id=security_id,
            resolution=resolution,
            start=start,
            end=end,
            expected=expected,
            held=in_range,
        )
        if requirement is SeriesRequirement.REQUIRED:
            self._require_grid_explains_the_data(
                security_id=security_id,
                resolution=resolution,
                start=start,
                end=end,
                expected=expected,
                held=in_range,
            )

        resolved = self.resolved_profile
        excluded: dict[tuple[str, str], int] = {}
        withheld: dict[Endpoint, tuple[_Withheld, str]] = {}
        unresolvable = 0
        bars: list[PriceBar] = []
        for bar in in_range:
            key = _endpoint_key(bar, resolution)
            if not is_eligible(bar, resolved):
                origin = ("price_bar", bar.envelope.information_origin.value)
                excluded[origin] = excluded.get(origin, 0) + 1
                withheld[key] = (
                    _Withheld.INELIGIBLE_ORIGIN,
                    bar.envelope.information_origin.value,
                )
                continue
            available = decision_available_time(bar, resolved, self._approvals)
            if available is None:
                unresolvable += 1
                withheld[key] = (_Withheld.UNRESOLVED_AVAILABILITY, "")
                continue
            if available > cutoff:
                withheld[key] = (_Withheld.NOT_YET_AVAILABLE, available.isoformat())
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

        if requirement is SeriesRequirement.REQUIRED:
            self._require_servable_coverage(
                security_id=security_id,
                resolution=resolution,
                start=start,
                end=end,
                as_of=cutoff,
                expected=expected,
                served=bars,
                withheld=withheld,
            )

        actions: list[CorporateAction] = []
        if not adjustment_mode.is_raw:
            actions = self._admissible_action_revisions(
                security_id, view=view, as_of=cutoff, resolved=resolved
            )

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
            datasets,
            revisable=() if adjustment_mode.is_raw else ("corporate_action",),
            excluded_rows=sum(excluded.values()),
            exclusions=excluded,
        )
        self._record_bounds(datasets)

        return BarSeriesResult(
            security_id=security_id,
            resolution=resolution,
            adjustment_mode=adjustment_mode,
            bars=series,
            provenance=self._provenance(
                cutoff, profile, view, bool(excluded), resolution, convention
            ),
            origin_exclusions=_counts(excluded),
            requirement=requirement,
            withheld_endpoints=len(withheld),
        )

    def _admissible_action_revisions(
        self,
        security_id: str,
        *,
        view: RevisionView,
        as_of: datetime,
        resolved: InformationSetProfile,
    ) -> list[CorporateAction]:
        """One revision per corporate action, chosen under an explicitly named view.

        A corporate action is revisable -- a ratio gets corrected, an ex-date
        moves -- so the adjusted series depends on which revision was in force.
        The earlier code took every eligible action row, which meant a corrected
        and an uncorrected revision of the same action could both reach the
        arithmetic and multiply into the factor twice.

        Actions with no admissible revision at ``as_of`` are simply absent: the
        query was not entitled to know about them, which is the correct answer
        rather than a missing input.
        """
        by_action: dict[str, list[CorporateAction]] = {}
        for action in self._dataset.actions_for(security_id):
            by_action.setdefault(action.action_id, []).append(action)

        chosen: list[CorporateAction] = []
        for action_id, revisions in sorted(by_action.items()):
            selected = select_revision(
                revisions,
                revision_view=view,
                as_of=as_of,
                resolved_profile=resolved,
                approvals=self._approvals,
            )
            if selected is None:
                continue
            if not isinstance(selected, CorporateAction):  # pragma: no cover - defensive
                raise ProfileResolutionError(
                    f"Revision selection for corporate action {action_id!r} returned a "
                    f"{type(selected).__name__}, which is not a corporate action."
                )
            chosen.append(selected)
        return chosen

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

    def _listing_venues(self, security_id: str, as_of: datetime) -> tuple[Listing, ...]:
        """The listing revisions this query was entitled to see, one per listing.

        Point-in-time like every other input, and it was not. ``current_listings``
        takes the highest revision unconditionally, so a listing revision
        published *after* ``as_of`` still decided which sessions a query expected:
        a 2020 delisting shrank a 2019 query's grid, and a genuine gap inside the
        removed span stopped being a gap. That is look-ahead deciding what counts
        as complete.
        """
        by_listing: dict[str, list[Listing]] = {}
        for listing in self._dataset.listings:
            if listing.security_id != security_id:
                continue
            if listing.listing_fact_kind is not ListingFactKind.STATE:
                # An announcement that a listing will change is not a listing
                # state, and treating it as one would let an announced future
                # delisting decide today's expected sessions.
                continue
            by_listing.setdefault(listing.listing_id, []).append(listing)

        chosen: list[Listing] = []
        for revisions in by_listing.values():
            selected = select_revision(
                revisions,
                revision_view=RevisionView.AS_KNOWN_AT_AS_OF,
                as_of=as_of,
                resolved_profile=self.resolved_profile,
                approvals=self._approvals,
            )
            if isinstance(selected, Listing):
                chosen.append(selected)
        return tuple(chosen)

    def _required_sessions(
        self, security_id: str, start: date, end: date, as_of: datetime
    ) -> tuple[MarketSession, ...]:
        """Sessions the security's own venue traded, on which it was listed.

        Per exchange, deliberately. A NASDAQ security is not required to have bars
        on an NYSE-only session, and pooling calendars would fault it for absences
        that are not absences.
        """
        listings = self._listing_venues(security_id, as_of)
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

    def _expected_endpoints(
        self,
        security_id: str,
        resolution: BarResolution,
        start: date,
        end: date,
        as_of: datetime,
    ) -> tuple[Endpoint, ...]:
        """Every endpoint a complete series must carry, from the venue's calendar.

        Computed **once** and used by both coverage checks, so the physical and
        the point-in-time question are asked about exactly the same grid. Two
        separately derived grids would eventually disagree, and the disagreement
        would look like a data defect.

        Per exchange, deliberately: a NASDAQ security is not required to have bars
        on an NYSE-only session, and pooling calendars would fault it for absences
        that are not absences. Daily expects one bar per listed trading session;
        minute follows the dense contract and expects the session's whole endpoint
        grid, so one arbitrary bar cannot pass for an observed session.
        """
        sessions = self._required_sessions(security_id, start, end, as_of)
        if resolution is BarResolution.DAILY:
            return tuple(session.session_date for session in sessions)
        points: list[Endpoint] = []
        for session in sessions:
            points.extend(_minute_endpoints(session))
        return tuple(points)

    def _require_physical_coverage(
        self,
        *,
        security_id: str,
        resolution: BarResolution,
        start: date,
        end: date,
        expected: Sequence[Endpoint],
        held: Sequence[PriceBar],
    ) -> None:
        """The dataset holds a bar for every expected endpoint, or refuses.

        Deliberately independent of ``as_of``: a bar that does not exist at all is
        a gap in the data, which is a different problem from a bar that exists and
        was not yet knowable. Both refuse a REQUIRED series, and the two refusals
        say different things because they have different fixes.
        """
        if not expected:
            return
        covered = {_endpoint_key(bar, resolution) for bar in held}
        missing = [point for point in expected if point not in covered]
        if not missing:
            return
        raise IncompleteCoverageError(
            f"Dataset {self._dataset.dataset_version} has no {resolution.value} bar for "
            f"{security_id} at {len(missing)} of {len(expected)} expected endpoint(s) in "
            f"{start.isoformat()}..{end.isoformat()} "
            f"({_render_endpoints(missing)}). Refused rather than truncated: a short series "
            "and a gap-ridden one look identical downstream. A session the security did not "
            "trade is still covered by an explicit no-trade bar."
        )

    def _require_grid_explains_the_data(
        self,
        *,
        security_id: str,
        resolution: BarResolution,
        start: date,
        end: date,
        expected: Sequence[Endpoint],
        held: Sequence[PriceBar],
    ) -> None:
        """Every bar in range sits on the expected grid, or the grid is wrong.

        Coverage was checked in one direction only -- every expected endpoint has
        a bar -- and that is half the question. A bar the grid does **not** expect
        means the calendar and the data disagree: a session row missing or flagged
        as a holiday, or a listing that says the security was not trading then.

        The asymmetry was exploitable in exactly the way the round set out to
        close. Deleting one session row shrank the grid past a genuine gap, so a
        REQUIRED series that had refused began returning a hole in the middle --
        the completeness check measuring itself against a calendar that had been
        edited to agree with the data.

        Raises:
            IncompleteCoverageError: naming the off-grid endpoints. Completeness
                cannot be certified while the calendar and the bars contradict
                each other.
        """
        if not held:
            return
        grid = set(expected)
        stray = sorted(
            {_endpoint_key(bar, resolution) for bar in held} - grid,
            key=str,
        )
        if not stray:
            return
        raise IncompleteCoverageError(
            f"Dataset {self._dataset.dataset_version} holds {len(stray)} {resolution.value} "
            f"bar(s) for {security_id} in {start.isoformat()}..{end.isoformat()} that its own "
            f"calendar and listings do not expect ({_render_endpoints(stray)}). A session row "
            "that is absent or flagged as a holiday, or a listing that says the security was "
            "not trading, shrinks the grid a complete series is measured against -- so a "
            "genuine gap elsewhere in the range would stop being a gap. Completeness cannot be "
            "certified while the calendar and the bars contradict each other."
        )

    def _require_servable_coverage(
        self,
        *,
        security_id: str,
        resolution: BarResolution,
        start: date,
        end: date,
        as_of: datetime,
        expected: Sequence[Endpoint],
        served: Sequence[PriceBar],
        withheld: Mapping[Endpoint, tuple[_Withheld, str]],
    ) -> None:
        """Every expected endpoint survived point-in-time filtering, or refuses.

        This is the check whose absence let a five-bar request come back four bars
        long. Physical coverage proved the dataset held the bar; nothing then
        asked whether *this* query was entitled to it, so an unpublished middle
        bar simply vanished from the result.

        The refusal names why each endpoint went, because the four reasons have
        four different fixes: a missing bar is a data problem, an ineligible
        origin is a profile problem, an unresolvable availability is a resolution
        problem, and a not-yet-published bar means the caller asked for a range
        their ``as_of`` does not reach -- which they fix by shortening ``end``.

        Raises:
            IncompleteCoverageError: naming the missing endpoints and their
                reasons, and -- where the only problem is that the series runs
                past what ``as_of`` could see -- the ``end`` that would work.
        """
        if not expected:
            return
        covered = {_endpoint_key(bar, resolution) for bar in served}
        missing = [point for point in expected if point not in covered]
        if not missing:
            return

        reasons: dict[str, list[Endpoint]] = {}
        for point in missing:
            entry = withheld.get(point)
            label = "it is absent from the dataset" if entry is None else entry[0].value
            reasons.setdefault(label, []).append(point)

        detail = "; ".join(
            f"{len(points)} because {label} ({_render_endpoints(points)})"
            for label, points in sorted(reasons.items())
        )
        raise IncompleteCoverageError(
            f"A REQUIRED {resolution.value} series for {security_id} over "
            f"{start.isoformat()}..{end.isoformat()} is missing {len(missing)} of "
            f"{len(expected)} expected endpoint(s) as of {as_of.isoformat()}: {detail}."
            f"{self._shorten_hint(resolution, expected, covered)} Refused rather than "
            "returned short: a series that silently drops the endpoints this query was not "
            "entitled to see is indistinguishable from a complete one, and a caller "
            "averaging it gets a number. Pass SeriesRequirement.OPTIONAL to accept whatever "
            "was knowable."
        )

    def _shorten_hint(
        self,
        resolution: BarResolution,
        expected: Sequence[Endpoint],
        covered: set[Endpoint],
    ) -> str:
        """Name the ``end`` that would have worked, when a prefix is intact.

        Only offered when the served endpoints are a genuine prefix of the
        expected grid. Suggesting an end that still has holes behind it would send
        the caller round the loop a second time.
        """
        prefix: list[Endpoint] = []
        for point in expected:
            if point not in covered:
                break
            prefix.append(point)
        if not prefix or len(prefix) == len(expected):
            return ""
        last = prefix[-1]
        # datetime first: it is a subclass of date, so testing date first would
        # match every minute endpoint and render a full timestamp as an "end".
        boundary = last.date() if isinstance(last, datetime) else last
        return (
            f" Everything up to {boundary.isoformat()} was servable, so an end of "
            f"{boundary.isoformat()} would answer."
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


def _snapshot_artifact(header: UniverseSnapshotHeader) -> ConsumedArtifactRecord:
    """The universe snapshot, described as the derived artifact it is.

    Every field the manifest needs comes from the header itself, so a run cannot
    cite a snapshot it did not read or describe one it did read inaccurately.
    """
    return ConsumedArtifactRecord(
        artifact_id=header.artifact_id,
        entity="universe_snapshot_header",
        output_validity=header.envelope.output_validity.value,
        derivation_spec_version=header.derivation_spec_version,
        artifact_content_hash=header.snapshot_content_hash,
        artifact_first_built_time=header.envelope.artifact_first_built_time,
        lineage_selectors=lineage_fingerprint(header.envelope.lineage),
    )


def _endpoint_key(bar: PriceBar, resolution: BarResolution) -> Endpoint:
    """The grid position a bar occupies, at the resolution being served.

    Daily coverage is per session; minute coverage is per endpoint. One function
    so both completeness checks index the same way, because a physical check and
    a servability check that disagreed about what an endpoint *is* would report
    phantom gaps.
    """
    if resolution is BarResolution.DAILY:
        return bar.session_date
    return bar.bar_end_time


def _render_endpoints(points: Sequence[Endpoint]) -> str:
    """A short, ordered rendering of endpoints for a refusal message."""
    shown = [point.isoformat() for point in points[:5]]
    return ", ".join(shown) + (" ..." if len(points) > 5 else "")


def _validate_revision_view(
    mode: AdjustmentMode, revision_view: RevisionView | None
) -> RevisionView:
    """Require a view exactly where revisions can change the answer.

    A raw series reads no corporate actions, so there is nothing to choose a
    revision of; accepting a view there would let a caller believe the query
    honoured something it never consulted. An adjusted series does read them, and
    a restated ratio changes every adjusted number after its ex-date, so the view
    is part of the question rather than a preference.

    Raises:
        QueryRangeError: if an adjusted query names no view, or a raw query names
            one.
    """
    if mode.is_raw:
        if revision_view is not None:
            raise QueryRangeError(
                f"A RAW series names revision_view={revision_view.value}, but a raw series "
                "reads no corporate actions and therefore chooses no revision. Accepting it "
                "would report that the query honoured a view it never consulted."
            )
        return RevisionView.AS_KNOWN_AT_AS_OF
    if revision_view is None:
        raise QueryRangeError(
            "An adjusted series must name its revision_view. A corporate action can be "
            "restated -- a corrected ratio, a moved ex-date -- and which revision was in "
            "force changes every adjusted number after it. There is no default, because a "
            "default would answer that on the caller's behalf without telling them."
        )
    return revision_view


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
    "RAW_PRICE_DATASETS",
    "UNIVERSE_DATASETS",
    "BarSeriesResult",
    "Endpoint",
    "ExecutedResult",
    "OriginExclusionCount",
    "PointInTimeReader",
    "ResultProvenance",
    "SeriesRequirement",
    "UniverseSnapshotResult",
    "select_revision",
]
