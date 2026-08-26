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
    "ArtifactIntegrityError",
    "BlockingQualityIssueError",
    "BronzeIntegrityError",
    "DatasetCoverageError",
    "EnvelopeError",
    "IneligibleUnderProfileError",
    "ManifestRefusedError",
    "MissingHistoricalSnapshotError",
    "NonPointInTimeViewError",
    "PendingContractError",
    "PointInTimeError",
    "ProfileResolutionError",
    "RequiredInputUnavailableError",
]
