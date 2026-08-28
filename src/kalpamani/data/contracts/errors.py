"""Point-in-time data-platform errors.

Every error here is a **refusal**, not a degradation. The distinction the whole
contract rests on: an empty result and a refusal are different answers, and a
data layer that returns the first when it means the second produces a backtest
that looks merely unprofitable rather than broken (contract 10, rule 7).

These inherit from :class:`~kalpamani.common.errors.KalpaManiError` so the
existing exception hierarchy stays single-rooted. They are deliberately **not**
:class:`~kalpamani.common.errors.SafetyViolationError` subclasses: that class
means an operation would have breached a *brokerage* safety rule, and the data
platform has no brokerage boundary to breach (schema 19 rule 9).
"""

from __future__ import annotations

from kalpamani.common.errors import KalpaManiError
from kalpamani.data.contracts.vocabulary import (
    ObjectStoreFailure,
    ObjectStoreOperation,
    closed_member,
)


class PointInTimeError(KalpaManiError):
    """Base class for every point-in-time data-platform refusal."""


class EnvelopeError(PointInTimeError):
    """A record's availability envelope is malformed at construction.

    Raised only for defects the type system can catch outright -- a source
    envelope declaring ``DERIVED_ARTIFACT``, or a derived envelope with empty
    lineage. Defects that a legitimate adversarial fixture must be able to
    *express* so a check can *catch* them are quality findings, not construction
    errors: a check that can never see the row it exists to reject protects
    nothing.
    """


class ProfileResolutionError(PointInTimeError):
    """A profile resolution configuration is incomplete or self-contradictory."""


class IneligibleUnderProfileError(PointInTimeError):
    """A record was requested under a profile its information origin cannot serve."""


class MissingHistoricalSnapshotError(PointInTimeError):
    """A required historical snapshot does not exist for the requested date.

    Refused rather than returned empty. A universe query for a date with no
    stored membership snapshot is unanswerable, not answerable with nothing
    (contract 10, rule 9).
    """


class BlockingQualityIssueError(PointInTimeError):
    """An open BLOCKING quality issue stands against a dataset the query touches.

    Every dependent result is refused, not annotated (data-quality-plan 8).
    """


class DatasetCoverageError(PointInTimeError):
    """The requested range falls outside a dataset's declared coverage."""


class RequiredInputUnavailableError(PointInTimeError):
    """A REQUIRED input domain emptied, or failed its coverage contract.

    Computing anyway would publish a different quantity under the original name
    and version, and nothing downstream would say so (contract 13.3).
    """


class NonPointInTimeViewError(PointInTimeError):
    """``LATEST_RESTATED`` was reached from a research or backtest path."""


class ArtifactIntegrityError(PointInTimeError):
    """A materialised artifact does not reproduce from its key.

    A mismatch is a BLOCKING quality issue, not a cache miss (contract 8).
    """


class BronzeIntegrityError(PointInTimeError):
    """A Bronze object identity already holds different bytes.

    Bronze is content-addressed and append-only. Two different payloads cannot
    share one identity, and the write is refused rather than resolved.
    """


class UnresolvedProviderAvailabilityError(ProfileResolutionError):
    """A dataset's provider timing is unresolvable and its policy does not resolve it.

    Quality check ``4.3.2_unresolved_provider_availability``, raised at the
    resolution boundary rather than discovered later. Policy ``NONE`` on a dataset
    with unresolved provider timing under ``PROVIDER_REALISTIC_PIT`` is not a
    silent pass-through: the rows stay, and the run refuses by name.
    """


class QueryRangeError(PointInTimeError):
    """A requested range is malformed -- a start after its end, for instance."""


class SecurityNotInDatasetError(PointInTimeError):
    """The dataset holds no evidence of this security at all.

    Distinct from a security that exists and simply did not trade: one is a
    question the dataset cannot answer, the other is an answer.
    """


class IncompleteCoverageError(PointInTimeError):
    """The dataset is missing bars the requested range requires.

    Refused rather than silently truncated. A short series and a gap-ridden one
    look identical downstream, and only one of them is a result.
    """


class DatasetPublicationError(PointInTimeError):
    """A dataset version is unpublished, partially published, or fails verification.

    A half-written build is not a smaller build. Reading one would produce a
    result nobody could reproduce, from inputs nobody could name.
    """


class AcquisitionIncompleteError(PointInTimeError):
    """A Bronze payload exists without its acquisition record, or vice versa.

    Recoverable by repair, never by pretending. Returning success while the
    acquisition metadata is absent would leave a payload nothing can explain.
    """


class ObjectStoreError(PointInTimeError):
    """A research object-store refusal.

    Storage-shaped rather than query-shaped, and still a refusal: a publisher that
    degraded here would leave the store holding something other than what the
    caller believes it holds.
    """


class ObjectContentMismatchError(ObjectStoreError):
    """A payload does not hash to the content address its key claims.

    Refused rather than corrected. Correcting it would mean minting a second
    identity for bytes a caller has already named, and every downstream reference
    to the first would then point at nothing.
    """


class ObjectAlreadyExistsError(ObjectStoreError):
    """Different bytes are already stored under this logical key.

    The research object store is append-only, so this is either a hash collision
    or a corrupted store. Neither is resolved by overwriting.
    """


class ObjectStoreBackendError(ObjectStoreError):
    """A storage backend refused or failed, described only by closed categories.

    **Assembled from a vocabulary, not redacted after the fact.** A cloud SDK's
    exception carries the bucket name, the physical object key, the endpoint,
    the request id, the host id, response headers and sometimes credential-shaped
    text. There is no parameter here for any of it: the message is built from an
    :class:`~kalpamani.data.contracts.vocabulary.ObjectStoreOperation` and an
    :class:`~kalpamani.data.contracts.vocabulary.ObjectStoreFailure`, and the
    originating exception is suppressed rather than chained.

    Both fields are normalised on the way in, so a bare string or a hostile
    object cannot make a later ``.value`` raise from inside exception handling.
    """

    __slots__ = ("failure", "operation")

    def __init__(
        self,
        *,
        operation: ObjectStoreOperation,
        failure: ObjectStoreFailure,
    ) -> None:
        """Carry an operation and a failure category. Nothing else has a home here."""
        self.operation = closed_member(ObjectStoreOperation, operation) or (
            ObjectStoreOperation.HEAD
        )
        self.failure = closed_member(ObjectStoreFailure, failure) or ObjectStoreFailure.UNKNOWN
        super().__init__(f"research object store {self.operation.value}: {self.failure.value}")


class ObjectPayloadTypeError(ObjectStoreError):
    """A payload was not exact, immutable :class:`bytes`.

    A ``bytearray`` or ``memoryview`` can be changed by whoever still holds it
    after the store has hashed it and filed it under that hash, leaving an object
    whose content address no longer describes its content. Refused rather than
    copied, so the caller's mistake surfaces instead of being papered over.
    """


class ObjectClassificationError(ObjectStoreError):
    """A research object's classification, shape or routing was refused.

    Three families of defect, all of which would put an object somewhere nobody
    chose:

    - **an unrecognised classification** -- a value that names no member of
      :class:`~kalpamani.data.contracts.vocabulary.DataClassification`, which
      cannot be resolved to a store and must not be guessed at;
    - **a classification this slice cannot publish.** ``CONTROL`` publication is
      **withdrawn**, not merely gated: there is no constructor for it, and
      supplying an attestation would not make it valid. A control-plane object
      survives a vendor deletion, so clearing one needs a structured, durably
      bound attestation that does not exist yet -- a free-text string was never
      auditable clearance;
    - **a malformed or unusable key** -- no segments, an over-long logical key, a
      non-string segment, or a key handed to the store that is not an exact
      :class:`~kalpamani.data.objectstore.ObjectKey`.

    ADR-0007 classifies by one question -- *can vendor rows be recovered from this
    artifact?* -- under which uncertain resolves to LICENSED. With no CONTROL
    constructor, uncertain is the only answer expressible.
    """


class ProviderMetadataDisclosureError(PointInTimeError):
    """Ingestion metadata carried something that must never be recorded.

    A credential, a request URL, a query string, a bucket or a cloud identifier.
    Recorded metadata outlives the process that wrote it, so the check is a
    refusal at write time rather than a redaction afterwards.
    """


class UnsafePathComponentError(PointInTimeError):
    """An identifier reaching the filesystem is not a safe path component.

    Refused rather than sanitised: rewriting a bad name would map two different
    identifiers onto one path, and two datasets sharing a directory is a
    corruption that verifies.
    """


class BuildBoundaryError(PointInTimeError):
    """A Gold dataset was assembled outside the sanctioned build path.

    Gold is built from :class:`ResolvedRunInputs`, which carry a resolution
    receipt. A dataset assembled from arbitrary rows has no receipt, so nothing
    can say which policy admitted them -- and a build nobody can account for is
    not publishable however correct its rows happen to be.
    """


class QualityGateError(PointInTimeError):
    """A publication or read was attempted without passing the quality gate.

    A missing quality report is not a clean one. Obtaining a publishable dataset
    by omitting the evidence is exactly the fail-open shape the gate exists to
    remove.
    """


class ExecutionSealError(PointInTimeError):
    """A result was offered without the evidence that produced it.

    A result and an inventory that travel separately can each be substituted for
    something else. Sealing them together makes the substitution a type error
    rather than a discrepancy nobody notices.
    """


class ManifestRefusedError(PointInTimeError):
    """A research manifest could not be emitted, so the result is inadmissible.

    Refusing rather than warning is the same trade ADR-0004 made throughout: an
    unreproducible result that *looks* reproducible is the unrecoverable one,
    because it gets cited later by someone who was not in the room.
    """


class PendingContractError(PointInTimeError):
    """An interface is contractually defined but its Phase-3A data does not exist.

    Distinct from :class:`NotImplementedError`: the contract is settled, the
    entity is simply outside the A1 fixture scope. Raising a named error keeps
    the difference between *unbuilt* and *undecided* legible.
    """


__all__ = [
    "AcquisitionIncompleteError",
    "ArtifactIntegrityError",
    "BlockingQualityIssueError",
    "BronzeIntegrityError",
    "BuildBoundaryError",
    "DatasetCoverageError",
    "DatasetPublicationError",
    "EnvelopeError",
    "ExecutionSealError",
    "IncompleteCoverageError",
    "IneligibleUnderProfileError",
    "ManifestRefusedError",
    "MissingHistoricalSnapshotError",
    "NonPointInTimeViewError",
    "PendingContractError",
    "PointInTimeError",
    "ProfileResolutionError",
    "QualityGateError",
    "QueryRangeError",
    "RequiredInputUnavailableError",
    "SecurityNotInDatasetError",
    "UnresolvedProviderAvailabilityError",
    "UnsafePathComponentError",
]
