"""The anti-look-ahead query interface.

Every historical accessor takes an explicit ``as_of`` **and** an explicit
information-set profile. No defaults. No ``latest`` convenience. No overload
without them. A default here is a decision made silently by whoever wrote the
accessor rather than by whoever asked the question -- and the question is the
whole point: "as of 2015-06-30" is not one question, it is three, and which one
was answered has to be stated.

**Every accessor returns a sealed result, and seals it itself.** There is no
``reader.seal(result, bytes)``: that method took *any* object and *any* bytes and
stamped them with whatever evidence the reader had accumulated across every
earlier query -- three separate ways for a result, its encoding and its evidence
to be about different things. Each accessor now runs against a **fresh recorder**,
encodes its own result canonically, records the ``QuerySpec`` it served, and
returns the :class:`~kalpamani.data.pit.execution.ExecutedResult`. A later query
inherits nothing from an earlier one, because it does not share the recorder that
would have carried it.

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

``OPTIONAL`` relaxes **availability and nothing else**. A missing bar, a bar the
calendar does not expect, a grid that cannot be determined at all -- those are
defects in the dataset, not facts about what this query was entitled to see, and
they refuse under both. Letting ``OPTIONAL`` serve through them would have made it
a way of asking the system to stop checking.

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

from kalpamani.data.contracts.canonical import content_hash
from kalpamani.data.contracts.dataset import UniverseSnapshotHeader
from kalpamani.data.contracts.entities import (
    CorporateAction,
    Listing,
    MarketSession,
    PriceBar,
    PriceBarValues,
    UniverseMembership,
)
from kalpamani.data.contracts.envelope import DerivedEnvelope, SourceEnvelope
from kalpamani.data.contracts.errors import (
    BlockingQualityIssueError,
    DatasetCoverageError,
    DatasetPublicationError,
    ExecutionSealError,
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
from kalpamani.data.contracts.profiles import ProfileResolutionConfig
from kalpamani.data.contracts.resolution import (
    BoundApprovals,
    PitRecord,
    TimingBasisUsed,
    decision_available_time,
    derived_inputs,
    governing_timing_bases,
    is_eligible,
    origin_eligible,
    required_timing_bases,
)
from kalpamani.data.contracts.vocabulary import (
    AdjustmentConvention,
    AdjustmentMode,
    AdjustmentPolicy,
    BarResolution,
    Exchange,
    InformationOrigin,
    InformationSetProfile,
    LimitationToken,
    ListingFactKind,
    RevisionView,
)
from kalpamani.data.curate.adjustment import (
    SUPPORTED_CONVENTIONS,
    adjusted_series,
    raw_series,
    relevant_actions,
)
from kalpamani.data.curate.lineage import lineage_fingerprint
from kalpamani.data.curate.publication import DatasetManifest, VerifiedPublication
from kalpamani.data.pit.execution import (
    _EXECUTION_TOKEN,
    ConsumedArtifactRecord,
    ExecutedResult,
    ExecutionEvidence,
    ExecutionRecorder,
    seal_executed_result,
)
from kalpamani.data.pit.query import (
    PriceQuerySpec,
    QuerySpec,
    SeriesRequirement,
    UniverseQuerySpec,
)
from kalpamani.data.quality.report import QualityReport

#: Datasets an **adjusted** price query reads directly, in canonical order.
#:
#: The raw set plus corporate actions. Listing states and the venue calendar are
#: in both, because both kinds of query measure completeness against a grid those
#: two tables produce -- an adjusted query that named only its actions and bars
#: left the same two inputs out of the inventory, and the manifest then demanded
#: no resolution evidence for either.
PRICE_HISTORY_DATASETS = ("corporate_action", "listing", "market_session", "price_bar")

#: Datasets a **raw** price query reads. Deliberately narrower than the adjusted
#: set: a raw series does not consult corporate actions, so recording one as read
#: would put a dataset in the run's inventory that the run never opened -- and
#: would then demand resolution evidence for it.
#:
#: ``listing`` and ``market_session`` are here because a price series is not only
#: its bars. The expected endpoint grid -- the thing completeness is measured
#: against -- is computed from the security's listing states and its venue's
#: calendar, so both decide the answer as directly as the bars do. Recording only
#: ``price_bar`` left a run's inventory silent about two inputs that could change
#: the result, and one of them was not point-in-time filtered at all.
RAW_PRICE_DATASETS = ("listing", "market_session", "price_bar")

#: Datasets a universe query reads directly.
UNIVERSE_DATASETS = ("universe_membership",)

#: One minute. The grid a dense minute series is expected to cover.
_MINUTE = timedelta(minutes=1)


@dataclass(frozen=True, slots=True, kw_only=True)
class _GridBasis:
    """The exact rows that decided which endpoints a price series must carry.

    A grid is a conclusion. The evidence for it is the listing states that said
    where and when the security traded and the calendar rows that said which days
    its venue opened -- and until this existed, neither appeared anywhere in a
    run's inventory, so two runs reaching the same grid from different revisions
    were indistinguishable.
    """

    #: Listing STATE revisions admissible at ``as_of``, one per listing.
    listings: tuple[Listing, ...]
    #: Calendar rows admissible at ``as_of`` in the requested window.
    sessions: tuple[MarketSession, ...]
    #: The subset of those the security was actually listed for and that traded.
    required: tuple[MarketSession, ...]
    #: The endpoints a complete series must carry.
    endpoints: tuple[Endpoint, ...]

    def identity(self) -> str:
        """A canonical hash of the rows themselves, not of the grid they produce.

        Two windows can expect the same endpoints from different evidence. Hashing
        the endpoints would call those one question; hashing the rows does not.
        """
        return content_hash(
            {
                "listings": sorted(
                    [
                        listing.listing_id,
                        listing.envelope.dataset_version,
                        str(listing.envelope.revision_sequence),
                    ]
                    for listing in self.listings
                ),
                "sessions": sorted(
                    [
                        session.exchange.value,
                        session.session_date.isoformat(),
                        session.envelope.dataset_version,
                        str(session.envelope.revision_sequence),
                    ]
                    for session in self.sessions
                ),
            }
        )


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


def _price_result_payload(result: BarSeriesResult) -> dict[str, object]:
    """The canonical bytes a price result is identified by.

    Derived from the result, never handed in. Accepting bytes from a caller meant
    the hash the manifest checks and the numbers the caller emits could describe
    different things -- and nothing would have said so.
    """
    return {
        "kind": "price_history",
        "security_id": result.security_id,
        "resolution": result.resolution.value,
        "requirement": result.requirement.value,
        "withheld_endpoints": result.withheld_endpoints,
        "adjustment_mode": "RAW" if result.adjustment_mode.is_raw else "ADJUSTED",
        "adjustment_policy": (
            None if result.adjustment_mode.policy is None else result.adjustment_mode.policy.value
        ),
        "adjustment_convention": (
            None
            if result.adjustment_mode.convention is None
            else result.adjustment_mode.convention.value
        ),
        "bars": [
            {
                "security_id": value.security_id,
                "session_date": value.session_date,
                "bar_end_time": value.bar_end_time,
                "open": value.open,
                "high": value.high,
                "low": value.low,
                "close": value.close,
                "volume": value.volume,
            }
            for value in result.bars
        ],
        "origin_exclusions": [
            [item.dataset, item.information_origin, item.rows] for item in result.origin_exclusions
        ],
    }


def _universe_result_payload(result: UniverseSnapshotResult) -> dict[str, object]:
    """The canonical bytes a universe result is identified by."""
    return {
        "kind": "security_universe",
        "session_date": result.session_date,
        "universe_definition_version": result.universe_definition_version,
        "members": list(result.members),
        "non_members": list(result.non_members),
        "snapshot_artifact_id": result.snapshot_artifact_id,
        "snapshot_content_hash": result.snapshot_content_hash,
    }


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
            DatasetPublicationError: if the publication's own identities no longer
                reconcile, or if the run's resolution disagrees with the
                publication's -- profile, policy version, or the complete map with
                its reasons.
        """
        for value, expected in (
            (publication, VerifiedPublication),
            (resolution, ProfileResolutionConfig),
            (approvals, BoundApprovals),
        ):
            if type(value) is not expected:
                # The exact type, not an instance of it. ``isinstance`` admits a
                # subclass, and a subclass supplies its own ``__init__``, its own
                # properties and its own methods -- so every check below would be
                # the object vouching for itself. All three are refused from
                # subclassing at the contract type; checking here as well means a
                # future relaxation of any of those refusals cannot silently
                # reopen the door.
                #
                # First, before anything is dereferenced: a wrong type must be
                # reported as a wrong type, not as an AttributeError from whatever
                # happened to be read first.
                raise DatasetPublicationError(
                    f"A reader was offered a {type(value).__name__} where a "
                    f"{expected.__name__} is required. The reader compares these values "
                    "against the publication once and consults them on every query, so a "
                    "type that can answer the two differently is not one it can bind to."
                )
        # Revalidated here rather than assumed. Construction established it, and
        # "it was established once" is a different claim from "it holds now" --
        # the first is what a Boolean or a token can carry, and the second is what
        # a reader actually depends on.
        publication.require_internally_consistent()
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
        recorded = publication.quality_report.quality_context.approvals
        declared = approvals.canonical()
        if declared != recorded:
            # The approvals decide which rows resolve at all, so they decide what a
            # query returns. The publication records the ones the build was judged
            # under, and the reader took its own from a parameter that nothing
            # compared to them: the standard was persisted and verified, and the
            # one component that applies a standard at query time ignored it.
            raise DatasetPublicationError(
                f"This run approves bound derivations {list(declared)} and "
                f"{publication.dataset_version} was built and judged under {list(recorded)}. "
                "An approved bound is what lets a row resolve at all, so two runs approving "
                "different derivations read different data from one published dataset."
            )
        # Compared **once**, and once is enough because ``BoundApprovals`` is
        # deep-frozen: the mapping is copied and proxied at construction, its
        # nested policies are frozen dataclasses over frozensets, and there is no
        # route by which the value this reader holds can differ later from the
        # value compared here. Re-deriving the same identity before every accessor
        # call would be a check that cannot fail -- which is how a guard becomes
        # decoration. The identity is kept instead, so a test can observe that it
        # does not move rather than trusting that it cannot.
        self._approvals_identity = approvals.identity()
        self._publication = publication
        self._dataset = publication.dataset
        self._manifest = manifest
        self._quality = publication.quality_report
        self._resolution = resolution
        self._approvals = approvals

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

    @property
    def approvals_identity(self) -> str:
        """The canonical identity of the approvals every query on this reader uses.

        Fixed for the reader's lifetime. It is the value that was compared against
        the publication's persisted standard at construction, kept so the fact can
        be observed rather than assumed.
        """
        return self._approvals_identity

    def _recorder(self) -> ExecutionRecorder:
        """A fresh recorder for one query.

        Per call, deliberately. A reader-lifetime recorder meant the second
        query's inventory named the first query's datasets, so a manifest for a
        universe query truthfully claimed to have read price bars -- and every
        evidence rule downstream was then enforced against a set of reads that was
        not this result's.
        """
        return ExecutionRecorder(
            dataset_version=self._manifest.dataset_version,
            manifest_hash=self._manifest.manifest_hash,
            build_identity=self._dataset.build_identity,
            layer=self._manifest.layer.value,
            resolution_policy_version=self._manifest.resolution_policy_version,
            resolution_map=self._manifest.resolution_map,
            quality_hash=self._quality.report_hash,
            quality_blocking_open=len(self._quality.blocking),
            quality_warnings_open=len(self._quality.warnings),
            quality_checks_not_run=tuple(item.check_name for item in self._quality.checks_not_run),
        )

    # -- accessors ---------------------------------------------------------

    def get_security_universe(
        self,
        *,
        as_of: datetime,
        profile: InformationSetProfile,
    ) -> ExecutedResult[UniverseSnapshotResult]:
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

        Returns the sealed result: the snapshot, its canonical bytes, the
        :class:`~kalpamani.data.pit.query.QuerySpec` this accessor served, and the
        evidence this one query recorded.

        Raises:
            MissingHistoricalSnapshotError: if no snapshot's evaluation cutoff had
                passed at ``as_of``, or none of those that had was completely
                available then. The refusal names why each candidate was rejected.
        """
        cutoff = normalize_instant(as_of)
        self._guard(profile, cutoff, UNIVERSE_DATASETS)
        resolved = self.resolved_profile
        recorder = self._recorder()

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
                return self._serve_snapshot(session, header, rows, cutoff, profile, recorder)
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

        **The header decides.** It is a real derived artifact carrying every row
        the build consumed -- each considered listing state and each membership
        decision -- so its own ``decision_available_time`` is the instant the
        snapshot as a whole became usable. Filtering membership rows individually
        answered a different question and answered it wrongly twice over: a
        considered security that produced no row could not delay anything, and a
        snapshot with no rows at all had no availability to speak of, so it looked
        available from the beginning of time.

        Membership-row checks remain, and remain **integrity** checks: rows keyed
        to another definition version contradict their header. They do not turn one
        stored snapshot into a partially available one, because a snapshot is one
        artifact and is served whole or not at all.
        """
        problems: list[str] = []
        if not header.is_complete:
            problems.append(f"the header declares status {header.status!r}, not COMPLETE")
        if header.resolved_profile is not resolved:
            problems.append(
                f"the header is keyed to {header.resolved_profile.value}, not {resolved.value}"
            )
        if header.evaluation_cutoff > cutoff:
            problems.append(
                f"its evaluation cutoff {header.evaluation_cutoff.isoformat()} is after this query"
            )

        if not header.inputs:
            problems.append(
                "the header records no inputs, so the snapshot has no availability to compute; "
                "a build that consumed nothing decided nothing"
            )
        elif not is_eligible(header, resolved):
            problems.append(
                "an input the snapshot consumed has an origin this profile cannot describe, so "
                "the snapshot is ineligible as a whole -- no amount of arithmetic makes a "
                "proprietary input public"
            )
        else:
            available = decision_available_time(header, resolved, self._approvals)
            if available is None:
                problems.append(
                    "the snapshot's availability is unresolvable: an input this profile "
                    "requires has neither an exact time nor an approved bound"
                )
            elif available > cutoff:
                problems.append(
                    f"the snapshot became available at {available.isoformat()}, after this "
                    "query -- one input arriving late delays the whole artifact, because a "
                    "snapshot is the conjunction of its decisions"
                )

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
        recorder: ExecutionRecorder,
    ) -> ExecutedResult[UniverseSnapshotResult]:
        """Return the whole snapshot, sealed to the query and evidence that produced it.

        No source dataset is recorded. A universe query reads a **stored derived
        artifact**; it does not open the listing, attribute or bar tables, and
        recording ``universe_membership`` as a directly-read source dataset made
        the manifest demand provider-resolution evidence for a table no resolution
        ever produces evidence about.

        The **header's** timing basis is what the result carries, because the
        header is what decided the answer. Recording only the membership rows left
        a zero-row snapshot with no timing evidence at all -- a served result whose
        run said nothing about how it had been admitted -- and left a considered
        security that produced no row invisible even though it delayed the build.

        Approval is derived, never assumed. The hard-coded ``approved=True`` here
        asserted the thing it was supposed to establish.
        """
        recorder.record_read((), excluded_rows=0)
        recorder.record_artifact(_snapshot_artifact(header))
        resolved = self.resolved_profile
        self._record_row(recorder, "universe_snapshot_header", header, resolved)
        for row in rows:
            self._record_row(recorder, "universe_membership", row, resolved)

        result = UniverseSnapshotResult(
            session_date=session,
            universe_definition_version=header.universe_definition_version,
            members=tuple(sorted(row.security_id for row in rows if row.is_member)),
            non_members=tuple(sorted(row.security_id for row in rows if not row.is_member)),
            provenance=self._provenance(cutoff, requested, None, False, None, None, recorder),
            origin_exclusions=(),
            snapshot_content_hash=header.snapshot_content_hash,
            snapshot_artifact_id=header.artifact_id,
        )
        universe_query = UniverseQuerySpec(
            as_of=cutoff,
            requested_profile=requested,
            resolved_profile=self.resolved_profile,
            session_date=session,
            evaluation_cutoff=header.evaluation_cutoff,
            snapshot_artifact_id=header.artifact_id,
            snapshot_content_hash=header.snapshot_content_hash,
            universe_definition_version=header.universe_definition_version,
            universe_definition_hash=header.universe_definition_hash,
        )
        require_query_describes_result(universe_query, result)
        return seal_executed_result(
            result=result,
            result_payload=_universe_result_payload(result),
            query=universe_query,
            recorder=recorder,
            dataset_version=self._manifest.dataset_version,
            publication_manifest_hash=self._manifest.manifest_hash,
            quality_report_hash=self._quality.report_hash,
            token=_EXECUTION_TOKEN,
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
    ) -> ExecutedResult[BarSeriesResult]:
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

        ``OPTIONAL`` relaxes that second check and **only** that one. The data must
        still be intact under either: a determinable grid, a bar for every expected
        endpoint, no bar the grid does not expect, and a point-in-time listing and
        calendar basis. Those are properties of the dataset rather than of what
        this query was entitled to see, and letting ``OPTIONAL`` serve through them
        would have made it a way of asking the system to stop checking.

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
        # Refused here, not inside the per-action loop below. `select_revision`
        # was the only runtime enforcement, and a security with no corporate
        # action rows -- the majority of them -- never entered that loop, so the
        # documented refusal fired only when the data happened to contain an
        # action. A safety rule that depends on the data is not a rule.
        require_point_in_time_view(view)
        datasets = RAW_PRICE_DATASETS if adjustment_mode.is_raw else PRICE_HISTORY_DATASETS

        self._guard(profile, cutoff, datasets)
        self._validate_range(start, end)

        if not self._dataset.knows_security(security_id):
            raise SecurityNotInDatasetError(
                f"Dataset {self._dataset.dataset_version} holds no listing, bar or attribute "
                f"for {security_id!r}. That is a question this dataset cannot answer, which "
                "is not the same as a security that simply did not trade."
            )

        resolved = self.resolved_profile
        recorder = self._recorder()
        held = self._dataset.bars_for(security_id, resolution.value)
        in_range = tuple(bar for bar in held if start <= bar.session_date <= end)
        # The grid's own evidence, recorded before the bars. A price series is not
        # only its bars: the endpoints completeness is measured against come from
        # listing states and calendar rows, and until both were recorded a run's
        # inventory was silent about two inputs that decide the answer.
        basis = self._grid_basis(security_id, resolution, start, end, cutoff)
        expected = basis.endpoints
        for listing in basis.listings:
            self._record_row(recorder, "listing", listing, resolved)
        for session in basis.sessions:
            self._record_row(recorder, "market_session", session, resolved)
        # Integrity, under both requirements. OPTIONAL is a statement about what
        # this query was entitled to *see*; it says nothing about whether the data
        # underneath is sound, and treating it as permission to skip these made it
        # a way of asking the system to stop checking.
        if not expected:
            raise IncompleteCoverageError(
                f"Dataset {self._dataset.dataset_version} has no listed trading session for "
                f"{security_id} on its own venue between {start.isoformat()} and "
                f"{end.isoformat()}, so there is no grid a series could be measured against "
                f"-- and it holds {len(in_range)} bar(s) in that range. Serving the bars that "
                "happen to exist would answer a question nobody can state, and OPTIONAL does "
                "not relax that: it relaxes availability, not the integrity of the data."
            )
        self._require_unique_endpoints(
            security_id=security_id, resolution=resolution, held=in_range
        )
        self._require_physical_coverage(
            security_id=security_id,
            resolution=resolution,
            start=start,
            end=end,
            expected=expected,
            held=in_range,
        )
        self._require_grid_explains_the_data(
            security_id=security_id,
            resolution=resolution,
            start=start,
            end=end,
            expected=expected,
            held=in_range,
        )

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
                self._record_unresolvable(recorder, "price_bar", bar, resolved)
                continue
            if available > cutoff:
                withheld[key] = (_Withheld.NOT_YET_AVAILABLE, available.isoformat())
                continue
            # Recorded per served row, not per dataset. Reading the build's
            # dataset-wide evidence reported a query as having leant on a bound
            # when every row it served carried an exact time.
            self._record_row(recorder, "price_bar", bar, resolved)
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
            assert adjustment_mode.policy is not None
            actions = self._admissible_action_revisions(
                security_id,
                view=view,
                as_of=cutoff,
                resolved=resolved,
                policy=adjustment_mode.policy,
                start=start,
                end=end,
            )
            for action in actions:
                self._record_row(recorder, "corporate_action", action, resolved)

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

        recorder.record_read(
            datasets,
            revisable=() if adjustment_mode.is_raw else ("corporate_action",),
            excluded_rows=sum(excluded.values()),
            exclusions=excluded,
        )

        result = BarSeriesResult(
            security_id=security_id,
            resolution=resolution,
            adjustment_mode=adjustment_mode,
            bars=series,
            provenance=self._provenance(
                cutoff,
                profile,
                # A raw series consulted no revision, so its provenance records
                # none either. The validator returns a view for the adjustment
                # path; reporting that value to a caller told them the answer had
                # honoured something it never read.
                None if adjustment_mode.is_raw else view,
                bool(excluded),
                resolution,
                convention,
                recorder,
            ),
            origin_exclusions=_counts(excluded),
            requirement=requirement,
            withheld_endpoints=len(withheld),
        )
        price_query = PriceQuerySpec(
            security_id=security_id,
            start=start,
            end=end,
            resolution=resolution,
            adjustment_mode="RAW" if adjustment_mode.is_raw else "ADJUSTED",
            adjustment_policy=adjustment_mode.policy,
            adjustment_convention=convention,
            requirement=requirement,
            grid_basis_hash=basis.identity(),
            # A raw series consulted no revision, so it records none. The
            # validator returns a view for the adjustment path to use; putting
            # that value in the spec made a raw query describe itself as having
            # honoured a view it never read.
            revision_view=None if adjustment_mode.is_raw else view,
            as_of=cutoff,
            requested_profile=profile,
            resolved_profile=resolved,
        )
        require_query_describes_result(price_query, result)
        return seal_executed_result(
            result=result,
            result_payload=_price_result_payload(result),
            query=price_query,
            recorder=recorder,
            dataset_version=self._manifest.dataset_version,
            publication_manifest_hash=self._manifest.manifest_hash,
            quality_report_hash=self._quality.report_hash,
            token=_EXECUTION_TOKEN,
        )

    def _admissible_action_revisions(
        self,
        security_id: str,
        *,
        view: RevisionView,
        as_of: datetime,
        resolved: InformationSetProfile,
        policy: AdjustmentPolicy,
        start: date,
        end: date,
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

        Only actions that can **affect this series** are returned, because every
        one of them is recorded as a read and pushes the result's availability to
        the max over its inputs. A dividend under ``SPLIT_ONLY``, or a split after
        the requested end, would make the answer less available for a row that
        changed none of its numbers. A split *before* the start is kept: under
        ``FORWARD_BASE_NORMALIZED`` every bar is expressed in the original base, so
        an earlier split scales the whole window.
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
        # One implementation of "relevant", shared with the materialised artifact
        # path. Restating the rules here is how the two came to disagree about the
        # convention's lower bound, and the same bar came back 104.00 from one
        # route and 52.00 from the other.
        return list(
            relevant_actions(
                chosen,
                security_id_scope=security_id,
                policy=policy,
                valid_time_start=start,
                valid_time_end=end,
                securities=(security_id,),
            )
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

    def _record_row(
        self,
        recorder: ExecutionRecorder,
        dataset: str,
        record: PitRecord,
        resolved: InformationSetProfile,
    ) -> None:
        """Record one served row's timing evidence, both sets, with real approval.

        The two basis sets answer different questions -- what the profile needed
        and what actually set the cutoff -- and a union over them described
        neither.

        No approval flag: a **served** row cannot have leant on an unapproved
        bound, because an unapproved bound resolves no axis and the row would not
        have been served. The reachable case is a row the query could not resolve,
        recorded by :meth:`_record_unresolvable`.
        """
        recorder.record_served_row(
            dataset,
            required=required_timing_bases(record, resolved, self._approvals),
            governing=governing_timing_bases(record, resolved, self._approvals),
        )

    def _record_unresolvable(
        self,
        recorder: ExecutionRecorder,
        dataset: str,
        record: PitRecord,
        resolved: InformationSetProfile,
    ) -> None:
        """Record a row this query could not admit because of an unapproved bound.

        The only reachable form of "an unapproved bound affected this result". It
        did not admit a row -- it prevented one -- and a caller reading a short
        series is entitled to know that a policy decision, not the data, is why.
        """
        if unapproved_bound_blocked(record, resolved, self._approvals):
            recorder.record_unapproved_bound(dataset)

    def _admissible_sessions(
        self, start: date, end: date, as_of: datetime
    ) -> tuple[MarketSession, ...]:
        """Calendar rows this query was entitled to see, one per exchange-session.

        The calendar was the one grid input never filtered point-in-time. Every
        session row the build happened to hold decided which endpoints an earlier
        query expected, so a calendar correction or a backfill published in 2020 --
        a session added, a holiday reclassified -- retroactively changed what a
        2019 query considered complete. A grid assembled from facts that did not
        exist yet is look-ahead deciding what counts as missing.

        Raises:
            IncompleteCoverageError: if the window holds **any** trading session
                the query could not see. Refusing only when *none* was visible left
                the worse half open: a partial calendar silently shrank the grid
                past a genuine gap, so a query that had been refusing a hole began
                returning a shorter series that looked complete. That is the same
                defect as measuring completeness against a calendar edited to agree
                with the data, arrived at from the other direction.
        """
        by_key: dict[tuple[Exchange, date], list[MarketSession]] = {}
        for session in self._dataset.sessions:
            if start <= session.session_date <= end:
                by_key.setdefault((session.exchange, session.session_date), []).append(session)

        admissible: list[MarketSession] = []
        unseen: list[tuple[Exchange, date]] = []
        for key, revisions in sorted(by_key.items(), key=lambda item: (item[0][1], item[0][0])):
            selected = select_revision(
                revisions,
                revision_view=RevisionView.AS_KNOWN_AT_AS_OF,
                as_of=as_of,
                resolved_profile=self.resolved_profile,
                approvals=self._approvals,
            )
            if isinstance(selected, MarketSession):
                admissible.append(selected)
            else:
                unseen.append(key)

        # Counted per calendar **day**, not per row. A day whose admissible
        # revision says "holiday" is a complete answer about that day; a day with
        # no admissible revision at all is a day this query knows nothing about.
        if unseen:
            named = [f"{exchange.value} {day.isoformat()}" for exchange, day in unseen[:5]]
            raise IncompleteCoverageError(
                f"Dataset {self._dataset.dataset_version} holds no calendar row this query was "
                f"entitled to see for {len(unseen)} exchange-session(s) between "
                f"{start.isoformat()} and {end.isoformat()} (first {named}) at "
                f"{as_of.isoformat()} under {self.resolved_profile.value}. Serving the days that "
                "happened to be visible would shrink the grid to fit them, so a genuine gap in "
                "the remainder would stop being a gap -- and an empty grid would report that the "
                "security traded on no session at all. Both answer a question nobody can state."
            )
        return tuple(sorted(admissible, key=lambda item: (item.session_date, item.exchange.value)))

    def _grid_basis(
        self,
        security_id: str,
        resolution: BarResolution,
        start: date,
        end: date,
        as_of: datetime,
    ) -> _GridBasis:
        """The exact listing and calendar rows that decide this series' grid.

        Both are returned rather than only their product, because "which endpoints
        were expected" is not evidence -- "which rows said so" is. Two runs
        expecting the same endpoints from different listing revisions asked
        different questions and could not be told apart.

        Per exchange, deliberately: a NASDAQ security is not required to have bars
        on an NYSE-only session, and pooling calendars would fault it for absences
        that are not absences. Daily expects one bar per listed trading session;
        minute follows the dense contract and expects the session's whole endpoint
        grid, so one arbitrary bar cannot pass for an observed session.
        """
        listings = self._listing_venues(security_id, as_of)
        sessions = self._admissible_sessions(start, end, as_of)
        required = tuple(
            session
            for session in sessions
            if not session.is_holiday
            and any(
                listing.exchange is session.exchange and listing.is_listed_on(session.session_date)
                for listing in listings
            )
        )
        if resolution is BarResolution.DAILY:
            endpoints: tuple[Endpoint, ...] = tuple(session.session_date for session in required)
        else:
            points: list[Endpoint] = []
            for session in required:
                points.extend(_minute_endpoints(session))
            endpoints = tuple(points)
        return _GridBasis(
            listings=listings, sessions=sessions, required=required, endpoints=endpoints
        )

    def _require_unique_endpoints(
        self,
        *,
        security_id: str,
        resolution: BarResolution,
        held: Sequence[PriceBar],
    ) -> None:
        """One bar per grid position, under either requirement.

        Two rows at one endpoint make every aggregate over the series ambiguous,
        and the ambiguity is invisible in the numbers. That is a defect in the
        data rather than a fact about what this query was entitled to see, so
        ``OPTIONAL`` does not relax it.

        Raises:
            IncompleteCoverageError: naming the duplicated endpoints.
        """
        seen: dict[Endpoint, int] = {}
        for bar in held:
            key = _endpoint_key(bar, resolution)
            seen[key] = seen.get(key, 0) + 1
        duplicated = sorted((key for key, count in seen.items() if count > 1), key=str)
        if not duplicated:
            return
        raise IncompleteCoverageError(
            f"Dataset {self._dataset.dataset_version} holds more than one {resolution.value} "
            f"bar for {security_id} at {len(duplicated)} endpoint(s) "
            f"({_render_endpoints(duplicated)}). Two rows at one grid position make every "
            "aggregate over the series ambiguous, and nothing in the numbers would say so."
        )

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
        recorder: ExecutionRecorder,
    ) -> ResultProvenance:
        """What this result is, and what it cost to produce it.

        Limitations come from ``recorder`` -- this query's own served rows --
        rather than from the build's dataset-wide evidence, which described a
        different set of rows than the one being returned.
        """
        return ResultProvenance(
            dataset_version=self._dataset.dataset_version,
            manifest_hash=self._manifest.manifest_hash,
            quality_report_hash=self._quality.report_hash,
            as_of=as_of,
            requested_profile=requested,
            resolved_profile=self.resolved_profile,
            revision_view=revision_view,
            limitations=_query_limitations(
                recorder.evidence(),
                downgraded=self.resolved_profile is not self._resolution.requested_profile,
                had_exclusions=had_exclusions,
            ),
            resolution=resolution,
            adjustment_convention=convention,
        )


def require_query_describes_result(query: QuerySpec, result: object) -> None:
    """The spec and the answer must be about the same thing.

    Both are produced by the same accessor call, so a disagreement is a bug rather
    than a caller's doing -- which is exactly why it needs checking here and
    nowhere else. A spec that drifts from its result is undetectable downstream:
    the manifest cross-checks the spec, the spec looks coherent, and it describes
    a question the numbers beside it do not answer.

    Raises:
        ExecutionSealError: naming the field that disagrees.
    """
    if isinstance(result, BarSeriesResult):
        _require_price_query_matches(query, result)
        return
    if isinstance(result, UniverseSnapshotResult):
        _require_universe_query_matches(query, result)
        return
    raise ExecutionSealError(
        f"No agreement rule exists for a {type(result).__name__}. Falling off the end and "
        "returning silently would make this check vacuous for every result type added after "
        "it was written -- which is how a check quietly stops covering what it names."
    )


def _require_price_query_matches(query: QuerySpec, result: BarSeriesResult) -> None:
    if not isinstance(query, PriceQuerySpec):
        raise ExecutionSealError(
            f"A bar series was sealed to a {query.kind!r} query. The spec is what a run "
            "records having asked, and it is not about this answer."
        )
    provenance = result.provenance
    for label, asked, answered in (
        ("security_id", query.security_id, result.security_id),
        ("resolution", query.resolution.value, result.resolution.value),
        (
            "adjustment_mode",
            query.adjustment_mode,
            "RAW" if result.adjustment_mode.is_raw else "ADJUSTED",
        ),
        ("requirement", query.requirement.value, result.requirement.value),
        ("as_of", query.as_of.isoformat(), provenance.as_of.isoformat()),
        ("requested_profile", query.requested_profile.value, provenance.requested_profile.value),
        ("resolved_profile", query.resolved_profile.value, provenance.resolved_profile.value),
    ):
        if asked != answered:
            raise ExecutionSealError(
                f"The sealed query says {label}={asked!r} and the result it seals reports "
                f"{answered!r}. A spec that does not describe its own answer records a "
                "question nobody asked."
            )
    if query.adjustment_mode == "RAW":
        if query.revision_view is not None or provenance.revision_view is not None:
            raise ExecutionSealError(
                "A RAW series reads no corporate actions and chooses no revision, and this "
                "one records one. Reporting a view the query never consulted claims the "
                "answer honoured something it never read."
            )
        return
    if query.revision_view is None or provenance.revision_view is None:
        raise ExecutionSealError(
            "An adjusted series names no revision view. A restated ratio changes every "
            "adjusted number after its ex-date, so which revision was in force is part of "
            "the question."
        )
    if query.adjustment_convention is None or provenance.adjustment_convention is None:
        raise ExecutionSealError(
            "An adjusted series names no convention. Two conventions produce two different "
            "numbers for one bar, and the label is what later results cite."
        )


def _require_universe_query_matches(query: QuerySpec, result: UniverseSnapshotResult) -> None:
    if not isinstance(query, UniverseQuerySpec):
        raise ExecutionSealError(f"A universe snapshot was sealed to a {query.kind!r} query.")
    for label, asked, answered in (
        ("session_date", query.session_date, result.session_date),
        (
            "universe_definition_version",
            query.universe_definition_version,
            result.universe_definition_version,
        ),
        ("snapshot_artifact_id", query.snapshot_artifact_id, result.snapshot_artifact_id),
        ("snapshot_content_hash", query.snapshot_content_hash, result.snapshot_content_hash),
        ("as_of", query.as_of, result.provenance.as_of),
        (
            "requested_profile",
            query.requested_profile,
            result.provenance.requested_profile,
        ),
        ("resolved_profile", query.resolved_profile, result.provenance.resolved_profile),
    ):
        if asked != answered:
            raise ExecutionSealError(
                f"The sealed query says {label}={asked!r} and the snapshot it seals reports "
                f"{answered!r}."
            )
    if query.revision_view is not None:
        raise ExecutionSealError(
            "A universe snapshot is not a revisable fact and chooses no revision view."
        )


def unapproved_bound_blocked(
    record: PitRecord,
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
) -> bool:
    """Whether an **unapproved** bound is why this row could not be admitted.

    The previous derivation could not fail, and it took a careful reading to see
    why. It asked whether ``PUBLIC_BOUNDED``/``PROVIDER_BOUNDED`` appeared in the
    row's bases and, if so, whether the derivation was approved -- but a bounded
    basis only arises because :func:`resolved_public_time` already found the
    derivation in the approved set. The guard tested a condition its own
    precondition had excluded, and returned ``True`` for every row that has ever
    existed. "Derived, never assumed" had become an assumption with arithmetic in
    front of it.

    A **served** row genuinely cannot have leant on an unapproved bound: an
    unapproved bound resolves no axis, so the row is either admitted some other
    way or not admitted at all. The reachable and useful question is the one asked
    here, about a row the query could **not** resolve: it carries an upper bound
    on an axis this profile consults, has no exact time on that axis, and the
    bound's derivation is not approved for its dataset. That is a result shortened
    by a policy decision, and a caller is entitled to know it.
    """
    envelope = record.envelope
    if isinstance(envelope, DerivedEnvelope):
        return any(
            unapproved_bound_blocked(item, resolved_profile, approvals)
            for item in derived_inputs(record)
        )
    if not origin_eligible(envelope.information_origin, resolved_profile):
        return False
    policy = approvals.for_dataset(record.dataset)

    public_blocked = (
        envelope.public_available_time is None
        and envelope.public_available_upper_bound is not None
        and envelope.public_bound_derivation not in policy.public
    )
    provider_blocked = (
        envelope.provider_available_time is None
        and envelope.provider_available_upper_bound is not None
        and envelope.provider_bound_derivation not in policy.provider
    )

    match resolved_profile:
        case InformationSetProfile.PUBLIC_PIT:
            return public_blocked
        case InformationSetProfile.PROVIDER_REALISTIC_PIT:
            if envelope.information_origin is InformationOrigin.PROVIDER_DERIVED:
                return provider_blocked
            return public_blocked or provider_blocked
        case _:
            # FORWARD_SYSTEM takes the max over whichever axes resolve, and
            # system_first_seen_time always does -- so an unapproved bound narrows
            # the answer without ever blocking the row.
            return False


def _query_limitations(
    evidence: ExecutionEvidence,
    *,
    downgraded: bool,
    had_exclusions: bool,
) -> tuple[LimitationToken, ...]:
    """The limitations **this result** actually incurred.

    Derived from the rows this query served, not from the build's dataset-wide
    resolution evidence. A dataset containing bounded rows and a result that leant
    on one are different claims, and reporting the first as the second put a
    ``PROVIDER_TIME_BOUNDED`` limitation on results computed entirely from exact
    times -- a token with nothing behind it, which is the failure the token rules
    exist to prevent, arrived at from the generous direction.
    """
    # The **required** set, matching the manifest's own derivation exactly. A
    # token here and a token there computed from different sets would refuse
    # every manifest, and the one that is right is the one about admission.
    bases = {basis for entry in evidence.timing_evidence for basis in entry.required_bases}
    tokens: list[LimitationToken] = []
    if had_exclusions:
        tokens.append(LimitationToken.ORIGIN_INELIGIBLE_ROWS_EXCLUDED)
    if TimingBasisUsed.PUBLIC_BOUNDED in bases:
        tokens.append(LimitationToken.PUBLIC_TIME_BOUNDED)
    if TimingBasisUsed.PROVIDER_BOUNDED in bases:
        tokens.append(LimitationToken.PROVIDER_TIME_BOUNDED)
        tokens.append(LimitationToken.PROVIDER_AVAILABILITY_UNKNOWN)
    if downgraded:
        tokens.append(LimitationToken.PROFILE_DOWNGRADED_TO_PUBLIC)
    return tuple(sorted(set(tokens), key=lambda token: token.value))


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


def require_point_in_time_view(revision_view: RevisionView | None) -> None:
    """Refuse ``LATEST_RESTATED`` wherever a query names one.

    Raises:
        NonPointInTimeViewError: it ignores ``as_of`` entirely, so it is not a
            point-in-time view and is unreachable from research and backtest code.
    """
    if revision_view is RevisionView.LATEST_RESTATED:
        raise NonPointInTimeViewError(
            "LATEST_RESTATED ignores as_of entirely, so it is not a point-in-time view and "
            "is unreachable from research and backtest code. It exists for accounting-style "
            "analysis of restatement behaviour, which is a legitimate question that simply "
            "is not a simulation."
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
    require_point_in_time_view(revision_view)

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
        originals = [record for record in admissible if _revision_sequence(record) == 0]
        return _only_revision(originals, sequence=0) if originals else None
    highest = max(_revision_sequence(record) for record in admissible)
    return _only_revision(
        [record for record in admissible if _revision_sequence(record) == highest],
        sequence=highest,
    )


def _only_revision(tied: Sequence[PitRecord], *, sequence: int) -> PitRecord:
    """The one row at this revision, refusing when two different rows claim it.

    ``max`` returns whichever tied row it saw first, so the order rows happened to
    arrive in chose which revision was in force -- a ratio, an ex-date, a listing
    status. Two contradictory rows at one revision sequence are a defect in the
    data: the revision chain says they are the same statement and they are not.

    Identical duplicates are one row and pass through; only a genuine
    contradiction refuses.

    Raises:
        ProfileResolutionError: naming the contradicting rows.
    """
    first = tied[0]
    contradictions = [record for record in tied[1:] if record != first]
    if not contradictions:
        return first
    raise ProfileResolutionError(
        f"{len(contradictions) + 1} different {first.dataset} rows share revision sequence "
        f"{sequence}. A revision sequence says which statement "
        "was in force, so two different statements at one sequence leave the question "
        "unanswerable -- and taking whichever arrived first would let input order decide it."
    )


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
    "require_point_in_time_view",
    "select_revision",
]
