"""A curated Gold dataset: what a point-in-time query is served from.

An immutable container of contract entities. It lives in ``contracts`` because
both the curation layer that writes it and the point-in-time layer that reads it
need it, and neither should have to import the other.

**It carries the receipt that says which policy admitted its rows.** A dataset
assembled from arbitrary rows has none, and a build nobody can account for is not
publishable however correct its rows happen to be. ``resolved_profile`` and
``resolution_policy_version`` are properties of the build, not of the caller
reading it: a dataset curated under ``PUBLIC_PIT`` cannot answer a
``PROVIDER_REALISTIC_PIT`` question, and a reader configured differently is
refused rather than served something relabelled.

**A universe snapshot is stored here, not recomputed.** ``universe`` maps a
session date to the membership rows recorded for it, and ``universe_headers``
records that the session was *built* -- including when it legitimately produced
no rows. Without a header a zero-row snapshot vanishes the moment the membership
table is flattened, and "the rule selected nobody" becomes indistinguishable from
"no snapshot exists". Those are opposite answers.

**Frozen means frozen.** Mappings are wrapped in ``MappingProxyType`` at
construction, so ``frozen=True`` does not merely wrap a dict anyone can mutate
afterwards. An artifact whose contents can change after its hash was taken is not
an artifact.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from types import MappingProxyType

from kalpamani.data.contracts.canonical import content_hash
from kalpamani.data.contracts.entities import (
    CorporateAction,
    Listing,
    MarketSession,
    PriceBar,
    SecurityAttribute,
    TickerHistory,
    UniverseMembership,
)
from kalpamani.data.contracts.envelope import DerivedEnvelope
from kalpamani.data.contracts.errors import EnvelopeError
from kalpamani.data.contracts.instants import normalize_instant
from kalpamani.data.contracts.profiles import DatasetResolutionEvidence, ResolutionReceipt
from kalpamani.data.contracts.resolution import PitRecord, SourceRecord
from kalpamani.data.contracts.row_identity import row_fingerprint
from kalpamani.data.contracts.vocabulary import InformationSetProfile, OutputValidity


@dataclass(frozen=True, slots=True, kw_only=True)
class UniverseSnapshotHeader:
    """The snapshot itself, as a derived artifact -- not a row count beside one.

    Separate from the membership rows on purpose. A snapshot whose rule
    legitimately selected nobody has zero member rows, and a session that was
    never built has zero rows too. Only the header distinguishes them, and the
    distinction is the difference between "nobody qualified" and "we cannot
    answer".

    An earlier version made that distinction with an unattributed count, which
    left the zero-row case as the one assertion in the system with nothing behind
    it: a fabricated header claiming a session was built and selected nobody was
    indistinguishable from a real one. The header now carries a
    :class:`DerivedEnvelope` like every other computed value -- the lineage the
    build actually read, when it was first built, the spec version that produced
    it, its content hash, and ``SESSION_SCOPED`` validity -- and
    ``header_identity_hash`` binds all of it together with the session, the
    definition, the profile, the cutoff, the status and the membership hashes.

    Carrying the envelope has a second consequence, and it is the point: a header
    has an **availability**. Under ``FORWARD_SYSTEM`` a zero-row snapshot cannot
    be served before ``artifact_first_built_time``, because before we built it we
    did not know the rule selected nobody -- we knew nothing.

    **Its lineage is the whole build, not the part that produced rows.** An
    earlier version attached the considered listing states only when no membership
    row had lineage of its own, which made the evidence for "this security was
    looked at and produced nothing" appear exactly when there was nothing else and
    vanish the moment one other security qualified. A security that was considered
    and excluded is part of what the snapshot decided, so it is always named.
    """

    #: Fixed. The header is a row of this entity, and the quality checks select a
    #: dataset's approved-bound policy by it.
    dataset: str = "universe_snapshot_header"
    session_date: date
    universe_definition_version: str
    resolved_profile: InformationSetProfile
    evaluation_cutoff: datetime
    row_count: int
    snapshot_content_hash: str
    derivation_spec_version: str
    #: Canonical hash of the universe rule's **parameters**. The version string is
    #: a promise that two builds under one name used one rule, and nothing checked
    #: it: the same version with a different minimum price produced a different
    #: membership set under an identical label.
    universe_definition_hash: str
    envelope: DerivedEnvelope
    #: Per required domain: how many rows were supplied and how many were
    #: admissible at the evaluation cutoff. The build's own coverage evidence,
    #: carried here because a snapshot that selected nobody is only interpretable
    #: alongside what it had to work with.
    required_domain_coverage: tuple[tuple[str, int, int], ...] = ()
    #: The rows this snapshot consumed -- every considered listing state and every
    #: membership decision. In memory only, like a membership row's: lineage is
    #: what survives storage, and inputs are what an availability computation
    #: needs. Without them the header is not a derived artifact the quality checks
    #: can reason about, which is why they never examined it.
    inputs: tuple[PitRecord, ...] = ()
    status: str = "COMPLETE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluation_cutoff", normalize_instant(self.evaluation_cutoff))
        if self.row_count < 0:
            raise EnvelopeError(
                f"The snapshot header for {self.session_date.isoformat()} declares "
                f"{self.row_count} rows. A negative count is not a smaller snapshot."
            )
        if self.derivation_spec_version != self.envelope.derivation_spec_version:
            raise EnvelopeError(
                f"The snapshot header for {self.session_date.isoformat()} declares spec "
                f"{self.derivation_spec_version!r} while its envelope records "
                f"{self.envelope.derivation_spec_version!r}. Two spec versions on one artifact "
                "means one of them did not produce it."
            )
        if self.envelope.output_validity is not OutputValidity.SESSION_SCOPED:
            raise EnvelopeError(
                f"The snapshot header for {self.session_date.isoformat()} declares "
                f"{self.envelope.output_validity.value} validity. A universe snapshot governs "
                "exactly one session; anything wider would let it answer for sessions it was "
                "never evaluated against."
            )

    @property
    def header_identity_hash(self) -> str:
        """Identity of the whole snapshot claim, lineage included.

        Covers the session, the definition version, the resolved profile, the
        evaluation cutoff, the status, the row count, the canonical membership
        hashes and the lineage. A header differing in any of those is a different
        snapshot, so a fabricated one cannot borrow a real one's identity.
        """
        return content_hash(
            {
                "session_date": self.session_date,
                "universe_definition_version": self.universe_definition_version,
                "resolved_profile": self.resolved_profile.value,
                "evaluation_cutoff": self.evaluation_cutoff,
                "row_count": self.row_count,
                "snapshot_content_hash": self.snapshot_content_hash,
                "derivation_spec_version": self.derivation_spec_version,
                "universe_definition_hash": self.universe_definition_hash,
                "status": self.status,
                "required_domain_coverage": [
                    list(entry) for entry in sorted(self.required_domain_coverage)
                ],
                "lineage": [
                    [
                        ref.entity,
                        ref.dataset_version,
                        sorted(f"{key}={value}" for key, value in ref.selector),
                        ref.upstream_artifact_id,
                    ]
                    for ref in sorted(
                        self.envelope.lineage,
                        key=lambda ref: (ref.entity, ref.dataset_version, ref.selector),
                    )
                ],
            }
        )

    @property
    def artifact_id(self) -> str:
        """Derived, not generated. The same snapshot always has the same id.

        A universe query consumes this artifact, so a research manifest has to be
        able to name it. Deriving the id from the identity hash means two runs
        citing "the snapshot for that session" can be checked against each other
        rather than merely asserted to match.
        """
        digest = self.header_identity_hash.removeprefix("sha256:")
        return f"usnap-{digest[:16]}"

    @property
    def is_complete(self) -> bool:
        """Whether this header asserts a finished snapshot. Nothing else is served."""
        return self.status == "COMPLETE"


def _row_identity(row: PitRecord) -> str:
    """One identity string for a row of either kind.

    A derived artifact's ``inputs`` mix source rows -- the listings a snapshot
    considered -- with derived ones -- the membership decisions it made. Source
    rows are identified by their key and revision; derived rows by their content
    hash. ``row_fingerprint`` handles only the first, which is why it raised on
    the second.
    """
    envelope = row.envelope
    if isinstance(envelope, DerivedEnvelope):
        return f"{row.dataset}:{envelope.artifact_content_hash}"
    return f"{row.dataset}:{envelope.source_id}:{envelope.revision_sequence}"


@dataclass(frozen=True, slots=True, kw_only=True)
class GoldDataset:
    """One curated build, carrying the receipt that accounts for its rows."""

    dataset_version: str
    build_time: datetime
    coverage_start: date
    coverage_end: date
    #: The profile this build actually resolved to. A downgraded run produces
    #: PUBLIC_PIT artifacts, because that is what it computed.
    resolved_profile: InformationSetProfile
    #: Which policy resolved this build's provider-timing gaps.
    resolution_policy_version: str
    #: Proof of which policy admitted these rows. Publication verifies it.
    resolution_receipt: ResolutionReceipt
    resolution_evidence: tuple[DatasetResolutionEvidence, ...] = ()
    sessions: tuple[MarketSession, ...] = ()
    listings: tuple[Listing, ...] = ()
    attributes: tuple[SecurityAttribute, ...] = ()
    tickers: tuple[TickerHistory, ...] = ()
    bars: tuple[PriceBar, ...] = ()
    actions: tuple[CorporateAction, ...] = ()
    universe: Mapping[date, tuple[UniverseMembership, ...]] = field(default_factory=dict)
    universe_headers: Mapping[date, UniverseSnapshotHeader] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Deep-freeze: a frozen dataclass wrapping a mutable dict is not frozen.
        object.__setattr__(self, "universe", MappingProxyType(dict(sorted(self.universe.items()))))
        object.__setattr__(
            self,
            "universe_headers",
            MappingProxyType(dict(sorted(self.universe_headers.items()))),
        )
        object.__setattr__(self, "build_time", normalize_instant(self.build_time))

    @property
    def build_identity(self) -> str:
        """What a quality report is **about**, as a single hash.

        A report proves the checks ran. Without this it does not say what they ran
        over, so a clean build's report could gate a defective one: the plan is
        satisfied, the runner seal is genuine, and nothing compares the evidence
        to the thing it is evidence for.

        Covers the version, the build time, the resolved profile and policy, the
        content-bound resolution receipt -- which accounts for every source row --
        every snapshot header's identity, and the membership rows themselves.

        The last is not redundant with the headers. A header's
        ``snapshot_content_hash`` is a *claim* about its rows, so an identity
        built from headers alone stays the same when the rows beneath them are
        removed.
        """
        return content_hash(
            {
                "dataset_version": self.dataset_version,
                "build_time": self.build_time,
                "coverage_start": self.coverage_start,
                "coverage_end": self.coverage_end,
                "resolved_profile": self.resolved_profile.value,
                "resolution_policy_version": self.resolution_policy_version,
                "resolution_receipt_hash": self.resolution_receipt.receipt_hash,
                # The source rows themselves, for the same reason as the
                # membership rows below: the receipt is a claim *about* them, so
                # an identity built from the claim alone is unchanged when the
                # rows it describes are removed.
                "source_rows": [list(entry) for entry in row_fingerprint(self.source_rows())],
                "universe_headers": [
                    [session.isoformat(), header.header_identity_hash]
                    for session, header in sorted(self.universe_headers.items())
                ],
                # The rows themselves, not only the headers' claims about them.
                # A header's snapshot_content_hash is a claim, so an identity
                # built from headers alone is unchanged when the rows beneath
                # them are removed -- and a sealed publication could then be
                # emptied after it was verified.
                "universe_rows": [
                    [
                        session.isoformat(),
                        sorted(row.envelope.artifact_content_hash for row in rows),
                    ]
                    for session, rows in sorted(self.universe.items())
                ],
                # The rows each derived artifact was computed **from**, which
                # nothing hashed. ``inputs`` is what ``decision_available_time``
                # walks and what 6.6_eligibility_from_inadmissible_data examines,
                # so appending one late input changed what the checks looked at
                # and what the snapshot was available from while every identity
                # -- the header's, the build's, the descriptor's -- stayed put.
                "derived_inputs": self._derived_input_fingerprints(),
            }
        )

    def _derived_input_fingerprints(self) -> list[list[object]]:
        """One fingerprint per derived row, over the rows it consumed."""
        rows: list[tuple[str, PitRecord]] = [
            (session.isoformat(), header)
            for session, header in sorted(self.universe_headers.items())
        ]
        rows.extend(
            (session.isoformat(), member)
            for session, members in sorted(self.universe.items())
            for member in members
        )
        out: list[list[object]] = []
        for session, row in rows:
            consumed = getattr(row, "inputs", ())
            out.append(
                [
                    session,
                    row.dataset,
                    _row_identity(row),
                    sorted(_row_identity(item) for item in consumed),
                ]
            )
        return sorted(out, key=repr)

    def _derived_input_identity_note(self) -> None:  # pragma: no cover - documentation
        """See :func:`_row_identity`: inputs mix source rows and derived rows."""

    def source_rows(self) -> tuple[SourceRecord, ...]:
        """Every source row this build holds, in canonical entity order."""
        return (
            *self.sessions,
            *self.listings,
            *self.attributes,
            *self.tickers,
            *self.bars,
            *self.actions,
        )

    def bars_for(self, security_id: str, resolution: str | None = None) -> tuple[PriceBar, ...]:
        """Raw bars for one security, optionally at one resolution, in canonical order.

        ``resolution`` is not optional in practice -- the query layer always
        passes it, because a series mixing daily and minute rows is not a series.
        It stays optional here only for whole-security integrity checks.
        """
        selected = (
            bar
            for bar in self.bars
            if bar.security_id == security_id
            and (resolution is None or bar.resolution.value == resolution)
        )
        return tuple(sorted(selected, key=lambda bar: bar.bar_end_time))

    def actions_for(self, security_id: str) -> tuple[CorporateAction, ...]:
        """Every corporate action for one security, in canonical order."""
        return tuple(
            sorted(
                (action for action in self.actions if action.security_id == security_id),
                key=lambda action: action.action_id,
            )
        )

    def session_on(self, session_date: date) -> MarketSession | None:
        """The calendar row for one session, if the dataset holds it."""
        for session in self.sessions:
            if session.session_date == session_date:
                return session
        return None

    def trading_sessions_between(
        self,
        start: date,
        end: date,
        *,
        exchange: str | None = None,
    ) -> tuple[date, ...]:
        """Session dates on which the venue traded, within an inclusive range.

        ``exchange`` matters: a security listed on one venue is not required to
        have bars on another venue's sessions, and pooling calendars would fault
        it for absences that are not absences.
        """
        return tuple(
            sorted(
                session.session_date
                for session in self.sessions
                if not session.is_holiday
                and start <= session.session_date <= end
                and (exchange is None or session.exchange.value == exchange)
            )
        )

    def knows_security(self, security_id: str) -> bool:
        """Whether the dataset holds any evidence of this security at all.

        A security the dataset has never heard of is a question it cannot answer.
        A security it knows that simply did not trade is an answer.
        """
        if any(listing.security_id == security_id for listing in self.listings):
            return True
        if any(bar.security_id == security_id for bar in self.bars):
            return True
        return any(attribute.security_id == security_id for attribute in self.attributes)

    def snapshot_was_built(self, session_date: date) -> bool:
        """Whether a universe snapshot exists for this session, rows or no rows."""
        return session_date in self.universe_headers

    def built_snapshot_sessions(self) -> tuple[date, ...]:
        """Every session a snapshot was built for, in order."""
        return tuple(sorted(self.universe_headers))


__all__ = ["GoldDataset", "UniverseSnapshotHeader"]
