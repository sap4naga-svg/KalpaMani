"""The ADR-0018 acquisition's own **write-only** licensed publication surface.

**One operation exists here: a conditional ``PutObject``.** There is no
``head_object``, no ``get_object``, no ``get_object_attributes``, no listing, no
copy, no delete and no read of any kind -- not on the publisher, and not on the
client protocol it will accept. ADR-0019 removed the acquisition role's object-read
authority at the IAM layer, and this module is the application layer that matches
it, so a compromised process and a forgetful edit both fail on the same boundary.

**Why a second surface rather than the shared store.** ADR-0011's
:class:`~kalpamani.data.storage.s3.S3ResearchObjectStore` resolves an occupied name
by issuing a ``HeadObject`` after a ``412``, and ADR-0017's accepted accounting is
stated in terms of exactly that behaviour. AWS maps ``HeadObject`` onto the
``s3:GetObject`` permission and publishes no independent metadata action, so a role
permitted to resolve a collision is a role permitted to read every key it can name
-- and an acquisition process derives every key it writes. ADR-0019 §5 therefore
requires an **ADR-0018-specific** publication surface: the shared store keeps the
behaviour ADR-0017 was accepted with, and this one does without it.

**A 412 is a name, not a comparison.** It establishes exactly one thing: *this name
was occupied*. It does not establish that the occupying object is identical, that it
is different, that this execution wrote it, or that anything may be resumed from it.
:class:`NameOccupiedError` says that and nothing else, and it is a distinct type
from :class:`~kalpamani.data.contracts.errors.ObjectAlreadyExistsError` precisely
because that one's name asserts *different content* -- a claim this surface can
never make.

**The request shape is the accepted one, and it is not re-invented.** ``IfNoneMatch``,
SSE-S3, the SHA-256 checksum, the content length and the content type are the values
the accepted implementation already writes, imported from the module that owns them
rather than restated. What is dropped is the resolution *after* the failure, not
anything about the write itself.

**Importing this module does nothing.** No SDK, no environment, no file, no socket,
no client and no credential: the client is injected, exactly as everywhere else in
this architecture.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final, Protocol

from kalpamani.data.contracts.errors import ObjectStoreBackendError, ObjectStoreError
from kalpamani.data.contracts.vocabulary import (
    DataClassification,
    ObjectStoreFailure,
    ObjectStoreOperation,
)
from kalpamani.data.ingest.publication import BRONZE_NAMESPACE, CLAIM_NAMESPACE
from kalpamani.data.ingest.sharadar.datasets import PROVIDER
from kalpamani.data.ingest.sharadar.qualification import CANONICAL_DATASET_ORDER
from kalpamani.data.objectstore import ObjectKey, PutOutcome, physical_key, require_publishable
from kalpamani.data.qualify.sharadar.plan import EMPIRICAL_REQUEST_COUNT
from kalpamani.data.storage.s3 import (
    CHECKSUM_ALGORITHM,
    CONTENT_TYPE,
    SERVER_SIDE_ENCRYPTION,
    checksum_of,
    classify_backend_failure,
)

#: One request coordinate: the dataset name, the subject, and the page offset.
#: Exactly what the locked plan asks for and what a locator entry records, and
#: **never** a digest -- an ordinal is a position in the inventory, not a fact
#: about what came back.
RequestCoordinate = tuple[str, str, int]

#: The S3 bucket-name shape this publisher will bind to.
#:
#: **Spelled here rather than imported**, so this module does not reach into the
#: shared store's private names -- and a test asserts the two patterns are identical,
#: which is the check that would catch a drift an import would merely have hidden.
#: It exists to refuse an ARN, an ``s3://`` URI, a path or a typo before any of them
#: reaches a request, and it is deliberately not an exhaustive AWS validator.
_BUCKET_NAME: Final = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$")


class WriteOnlyS3Client(Protocol):
    """The **one** S3 operation this publisher uses.

    Structurally satisfied by a ``boto3`` S3 client, and by nothing narrower than a
    writer. There is no ``head_object``, ``get_object``, ``get_object_attributes``,
    ``list_objects_v2``, ``delete_object`` or ``copy_object`` in the shape, so an
    acquisition process could not read, enumerate, delete or duplicate an object even
    if a future edit tried to -- and a client that happens to *carry* those methods is
    still never called through them, because there is no call site.
    """

    def put_object(self, **kwargs: Any) -> Any:
        """Write one object."""
        ...


class NameOccupiedError(ObjectStoreError):
    """A conditional publication found the name occupied. **Nothing more.**

    Raised where the shared store would have issued a ``HeadObject`` and decided
    whether the occupying object was identical. This surface cannot decide that, so
    it does not claim to: the occupying object's content, digest, size, origin and
    age are all **undetermined**, and every one of them stays undetermined.

    It is **not** an
    :class:`~kalpamani.data.contracts.errors.ObjectAlreadyExistsError` and does not
    subclass one. That type's name asserts *different* content, which is a comparison
    this surface never performs, and reusing it would have smuggled the removed claim
    back in under an old name.

    The message is a constant. There is no parameter for a key, a digest, a bucket,
    a subject or a backend message, so none can arrive -- and the accepted runtime,
    which catches whatever a publication raises, therefore has nothing private to
    leak into its own halt.
    """

    __slots__ = ()

    def __init__(self) -> None:
        """Carry the fixed sentence, and no value of any kind."""
        super().__init__(
            "a conditional publication found the name occupied. This surface performs no "
            "object read, so what occupies the name was not determined."
        )


class LicensedWriteOnlyPublisher:
    """Append-only publication to one licensed bucket, with **no read surface**.

    Implements the one method the accepted Bronze publisher and the locator
    publication actually call -- ``put_if_absent`` -- and adds nothing to it. There
    is no ``exists`` here: the neutral protocol offers one, this surface has no
    authority to answer it, and a method that answered anyway would be either a read
    or a guess.

    The client and the bucket are injected. This class discovers neither, so it
    cannot be pointed at a bucket by an environment variable, a profile or a
    module-level default, and it constructs no SDK client of its own.

    ``name_occupied`` is an attribute rather than a return value because it has to
    survive the refusal: the publication raises, the run halts, and the acquisition
    still has to be able to say *why* without inspecting anything.

    **It keeps no operation counter of its own.** The authoritative count is the one
    the injected counting client observes, and a second counter beside it is a second
    number that can disagree with the first.
    """

    __slots__ = ("_bucket", "_client", "name_occupied")

    def __init__(self, *, client: WriteOnlyS3Client, licensed_bucket: str) -> None:
        """Bind an injected write-only client to one licensed bucket.

        Raises:
            ObjectStoreBackendError: ``BIND: INVALID_CONFIGURATION`` if
                ``licensed_bucket`` is not an exact plain string with a valid S3
                bucket-name shape, or if ``client`` cannot serve ``put_object``.
                **The refusal never echoes the value** -- a bucket name is a private
                identifier under CLAUDE.md §3, so it may not appear in an error any
                more than in a log.
        """
        if type(licensed_bucket) is not str or not _BUCKET_NAME.match(licensed_bucket):
            raise ObjectStoreBackendError(
                operation=ObjectStoreOperation.BIND,
                failure=ObjectStoreFailure.INVALID_CONFIGURATION,
            )
        if not callable(getattr(client, "put_object", None)):
            # **Only ``put_object`` is required, and that is the correction.** The
            # shared store demands ``head_object`` at construction, so a client that
            # genuinely cannot read could not be bound to it at all.
            raise ObjectStoreBackendError(
                operation=ObjectStoreOperation.BIND,
                failure=ObjectStoreFailure.INVALID_CONFIGURATION,
            )
        self._bucket = licensed_bucket
        self._client = client
        self.name_occupied = False

    def __repr__(self) -> str:
        """The class, its classification and its direction. **Never a bucket or key.**

        Nothing in this string is caller-supplied, which is what makes it safe to log
        without anyone having to think about it.
        """
        return "LicensedWriteOnlyPublisher(classification=LICENSED, direction=WRITE_ONLY)"

    def put_if_absent(self, *, key: ObjectKey, payload: bytes) -> PutOutcome:
        """Publish ``payload`` under ``key`` unless the name is already occupied.

        **Exactly one conditional ``PutObject`` per call.** No preflight, no
        resolution afterwards, no retry: checking first and writing second is a race
        that overwrites whatever landed in between, and on a bucket with no
        versioning an overwrite is unrecoverable.

        A ``412`` **fails closed**. Nothing is read, compared, hashed, adopted or
        resumed from, and the outcome is never reported as an idempotent
        re-publication -- that disposition required a metadata read this surface does
        not have, so it no longer exists here.

        Returns:
            The outcome of a write that happened. ``stored`` is always ``True``: this
            surface reaches no other success, so a caller cannot receive
            ``stored=False`` and read it as *already present and identical*.

        Raises:
            ObjectClassificationError: if ``key`` is not an exact, publishable key.
            ObjectPayloadTypeError: if ``payload`` is not exact, immutable bytes.
            ObjectContentMismatchError: if ``payload`` does not hash to ``key``.
            NameOccupiedError: on ``412``. The name was occupied, and **that is the
                whole claim**.
            ObjectStoreBackendError: ``PUT`` with a closed category for every other
                backend refusal, raised ``from None`` so the SDK exception's bucket,
                key, endpoint and request id cannot reach a traceback. A ``409``
                conflict arrives here as ``PUT: TRANSIENT`` -- **not** as an occupied
                name, because the condition was never resolved.
        """
        exact = require_publishable(key, payload)
        location = physical_key(key)
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=location,
                Body=exact,
                ContentLength=len(exact),
                ContentType=CONTENT_TYPE,
                ChecksumAlgorithm=CHECKSUM_ALGORITHM,
                ChecksumSHA256=checksum_of(key.content_sha256),
                ServerSideEncryption=SERVER_SIDE_ENCRYPTION,
                IfNoneMatch="*",
            )
        except Exception as exception:
            failure = classify_backend_failure(exception)
            if failure is ObjectStoreFailure.PRECONDITION_FAILED:
                self.name_occupied = True
                raise NameOccupiedError() from None
            raise ObjectStoreBackendError(
                operation=ObjectStoreOperation.PUT, failure=failure
            ) from None
        return PutOutcome(key=key, stored=True, byte_count=len(exact))


# -- ADR-0020: request-scoped qualification payload identity -------------------

#: The segment that separates qualification payloads from the general-purpose
#: content-addressed Bronze namespace. An ordinary segment with no leading
#: underscore, so it can never collide with the reserved claim namespace, which the
#: shared path grammar refuses to any provider.
QUALIFICATION_SEGMENT: Final = "qualification"

#: The segment that introduces the request ordinal.
REQUESTS_SEGMENT: Final = "requests"

#: The digest algorithm segment. The digest stays the **last** path segment, exactly
#: as the general-purpose namespace spells it.
DIGEST_SEGMENT: Final = "sha256"

#: The general-purpose payload segment, recognised on the way in and replaced.
OBJECTS_SEGMENT: Final = "objects"

#: The acquisition-record segment, recognised on the way in and forwarded unchanged.
ACQUISITIONS_SEGMENT: Final = "acquisitions"

#: Ordinals are zero-padded to two digits, so ``00``--``47`` covers the locked
#: inventory and lexical order equals numeric order.
ORDINAL_WIDTH: Final = 2

#: The suffix the accepted claim and acquisition-record builders append.
_JSON_SUFFIX: Final = ".json"

#: The canonical dataset order, by dataset *name*, resolved once. The locator and the
#: plan both speak dataset values rather than enum members on this boundary.
_DATASET_ORDER: Final[dict[str, int]] = {
    dataset.value: index for index, dataset in enumerate(CANONICAL_DATASET_ORDER)
}


class QualificationKeyError(ObjectStoreError):
    """A qualification payload identity could not be derived, or a publication did not
    present the accepted Bronze triple.

    **The message is a constant.** There is no parameter for a key, a digest, an
    ordinal, an execution identity, a subject or a dataset, so none can arrive -- and
    every refusal below is raised ``from None``, because the underlying key grammar's
    own message quotes the value it refused.

    It is an :class:`~kalpamani.data.contracts.errors.ObjectStoreError`, so the
    accepted runtime already treats it the way it treats any storage refusal: the run
    halts, durable state is reported unknown, and nothing is retried. It is
    deliberately **not** a :class:`NameOccupiedError` -- nothing here observed an
    occupied name, and a refusal that borrowed that name would report a collision that
    did not happen.
    """

    __slots__ = ()

    def __init__(self) -> None:
        """Carry the fixed sentence, and no value of any kind."""
        super().__init__(
            "a qualification payload identity could not be derived from the publication "
            "presented. No key, digest, ordinal or identity is disclosed."
        )


def request_ordinal_segment(ordinal: int) -> str:
    """The zero-padded path segment for one canonical request ordinal.

    Raises:
        QualificationKeyError: if ``ordinal`` is not an exact ``int`` inside the locked
            inventory. ``bool`` is refused with everything else, because
            ``type(...) is not int`` and ``True`` would otherwise pad to ``01``.
    """
    if type(ordinal) is not int or not 0 <= ordinal < EMPIRICAL_REQUEST_COUNT:
        raise QualificationKeyError() from None
    return f"{ordinal:0{ORDINAL_WIDTH}d}"


def qualification_payload_key(
    *, dataset: str, execution_id: str, request_ordinal: int, content_sha256: str
) -> ObjectKey:
    """The ADR-0020 key of one qualification payload. Always LICENSED.

    ``licensed/bronze/<provider>/<dataset>/qualification/<execution>/requests/<NN>/sha256/<digest>``

    **One pure canonical implementation, used by all three sides.** The acquisition
    router writes through it, the locator records what it produces, and the assessment
    reconstructs the expected key with it -- so a layout change cannot move one of the
    three without moving the other two.

    Every element answers an existing rule rather than a preference. It stays under
    ``bronze/`` so prefix deletion already covers it; it keeps ``<provider>/<dataset>``
    so a termination obligation for one vendor cannot reach another's evidence; and the
    digest stays last, exactly as the general-purpose namespace spells it.

    **It contains no subject, no requested range, no API path, no credential, no bucket
    and no account.** An ordinal is a position in the locked inventory, and a position
    discloses nothing about which security occupies it.

    Raises:
        QualificationKeyError: for an ordinal outside the inventory, a digest that is
            not 64 lowercase hex characters, or a dataset or execution identity the
            path grammar refuses. **Raised ``from None``**: the grammar's own message
            quotes the value, and this refusal may not.
    """
    ordinal = request_ordinal_segment(request_ordinal)
    try:
        return ObjectKey(
            classification=DataClassification.LICENSED,
            segments=(
                BRONZE_NAMESPACE,
                PROVIDER,
                dataset,
                QUALIFICATION_SEGMENT,
                execution_id,
                REQUESTS_SEGMENT,
                ordinal,
                DIGEST_SEGMENT,
                content_sha256,
            ),
            content_sha256=content_sha256,
        )
    except Exception:
        raise QualificationKeyError() from None


def request_ordinal_map(coordinates: Sequence[RequestCoordinate]) -> dict[RequestCoordinate, int]:
    """The canonical ordinal of every request coordinate, independent of input order.

    Ordered exactly as the locked plan emits requests -- dataset in
    :data:`~kalpamani.data.ingest.sharadar.qualification.CANONICAL_DATASET_ORDER`, then
    subject lexicographically, then page offset ascending. **Nothing a provider returns
    can select, shift or influence an ordinal**: the input is the coordinate tuple the
    plan asked for, and a response has no way into it.

    The acquisition derives its map from the locked plan and the assessment derives its
    map from the locator's own entries. Both call **this** function, so the two cannot
    drift, and a shuffled locator produces the same map as an ordered one.

    Raises:
        QualificationKeyError: unless the input is exactly the locked inventory --
            :data:`~kalpamani.data.qualify.sharadar.plan.EMPIRICAL_REQUEST_COUNT`
            distinct, well-formed coordinates naming known datasets. A partial or
            duplicated inventory has no canonical ordinal, and inventing one would name
            an object after a request that was never planned.
    """
    if type(coordinates) not in (tuple, list) or len(coordinates) != EMPIRICAL_REQUEST_COUNT:
        raise QualificationKeyError() from None
    exact: list[RequestCoordinate] = []
    for coordinate in coordinates:
        if type(coordinate) is not tuple or len(coordinate) != 3:
            raise QualificationKeyError() from None
        dataset, subject, page_skip = coordinate
        if type(dataset) is not str or type(subject) is not str or type(page_skip) is not int:
            raise QualificationKeyError() from None
        if dataset not in _DATASET_ORDER or page_skip < 0:
            raise QualificationKeyError() from None
        exact.append((dataset, subject, page_skip))
    if len(set(exact)) != len(exact):
        raise QualificationKeyError() from None
    ordered = sorted(exact, key=lambda item: (_DATASET_ORDER[item[0]], item[1], item[2]))
    return {coordinate: ordinal for ordinal, coordinate in enumerate(ordered)}


class QualificationPayloadRouter:
    """Binds the accepted Bronze publication triple to ADR-0020 payload identities.

    **The seam, and only the seam.** The accepted neutral publisher writes a claim,
    then a payload, then an acquisition record, and derives all three names itself. The
    claim and the record already bind the execution and the request; the payload did
    not, which is the collision ADR-0020 corrects. This router sits between the accepted
    runtime and the write-only publisher, recognises which of the three it was handed,
    and **replaces the payload name with the request-scoped one**. The claim and the
    record are forwarded byte for byte under their accepted names.

    **It reads nothing and can read nothing.** It forwards to
    :class:`LicensedWriteOnlyPublisher`, whose only operation is a conditional
    ``PutObject``, and it exposes no ``head_object``, ``get_object``,
    ``get_object_attributes``, ``exists``, listing, compare, adopt, resume or
    deduplicate path of its own. ADR-0019 is preserved exactly: a ``412`` still raises
    :class:`NameOccupiedError` from the publisher and still fails closed.

    **The triple is a protocol, and the protocol is verified rather than assumed.** The
    claim names the acquisition identity, so the ordinal is looked up from it against
    the locked plan; the payload must carry the claim's digest; the record must carry
    both the claim's identity and its digest. A publication that arrives out of order,
    twice, without a claim, or naming an identity the plan does not contain is **refused
    before it is written**. Every one of those refusals is a
    :class:`QualificationKeyError` -- a fail-closed halt that reports storage refusal,
    never a name collision.

    Ordinals are consumed **strictly increasing**, which is the canonical order the
    accepted runtime publishes in. So one governed request cannot yield two accepted
    terminal payloads: a second claim naming an already-consumed identity is refused
    before any write.
    """

    __slots__ = ("_execution_id", "_highest", "_ordinals", "_pending", "_publisher")

    def __init__(
        self,
        *,
        publisher: LicensedWriteOnlyPublisher,
        execution_id: str,
        ordinals: Mapping[str, int],
    ) -> None:
        """Bind one write-only publisher, one execution, and one acquisition map.

        Raises:
            QualificationKeyError: if ``publisher`` is not an exact
                :class:`LicensedWriteOnlyPublisher`, if ``execution_id`` is not an exact
                string, or if ``ordinals`` is not the locked inventory's acquisition
                identities mapped one-to-one onto ``0``--``47``. **The refusal names
                none of them.**
        """
        if type(publisher) is not LicensedWriteOnlyPublisher or type(execution_id) is not str:
            raise QualificationKeyError() from None
        if type(ordinals) is not dict or len(ordinals) != EMPIRICAL_REQUEST_COUNT:
            raise QualificationKeyError() from None
        if sorted(ordinals.values()) != list(range(EMPIRICAL_REQUEST_COUNT)):
            raise QualificationKeyError() from None
        if any(type(identity) is not str for identity in ordinals):
            raise QualificationKeyError() from None
        self._publisher = publisher
        self._execution_id = execution_id
        self._ordinals = dict(ordinals)
        # (acquisition identity, payload digest, ordinal, payload published yet).
        self._pending: tuple[str, str, int, bool] | None = None
        self._highest = -1

    def __repr__(self) -> str:
        """The class, its classification and its direction. **Never an identity.**"""
        return "QualificationPayloadRouter(classification=LICENSED, direction=WRITE_ONLY)"

    def put_if_absent(self, *, key: ObjectKey, payload: bytes) -> PutOutcome:
        """Route one publication of the accepted Bronze triple.

        Returns:
            The publisher's outcome. The payload's outcome names the **request-scoped
            key that was actually written**, so a caller reading the result gets the
            name that exists rather than the name it asked for.

        Raises:
            QualificationKeyError: for a key that is not one of the three accepted
                Bronze shapes, for a triple presented out of order, and for an
                acquisition identity the locked plan does not contain or has already
                completed. **Nothing is written on any of them.**
            NameOccupiedError: unchanged, from the publisher, on a ``412``.
            ObjectStoreBackendError: unchanged, from the publisher.
        """
        if type(key) is not ObjectKey:
            raise QualificationKeyError() from None
        segments = key.segments
        if len(segments) == 4 and segments[:2] == (BRONZE_NAMESPACE, CLAIM_NAMESPACE):
            return self._claim(key=key, payload=payload, digest=segments[2], leaf=segments[3])
        if len(segments) == 6 and segments[:2] == (BRONZE_NAMESPACE, PROVIDER):
            if segments[3] == OBJECTS_SEGMENT and segments[4] == DIGEST_SEGMENT:
                return self._payload(
                    key=key, payload=payload, dataset=segments[2], digest=segments[5]
                )
            if segments[3] == ACQUISITIONS_SEGMENT:
                return self._record(key=key, payload=payload, digest=segments[4], leaf=segments[5])
        raise QualificationKeyError() from None

    def _claim(self, *, key: ObjectKey, payload: bytes, digest: str, leaf: str) -> PutOutcome:
        """Open one triple, after checking the identity is one this run may still write."""
        if self._pending is not None or not leaf.endswith(_JSON_SUFFIX):
            raise QualificationKeyError() from None
        identity = leaf[: -len(_JSON_SUFFIX)]
        ordinal = self._ordinals.get(identity)
        if ordinal is None or ordinal <= self._highest:
            raise QualificationKeyError() from None
        outcome = self._publisher.put_if_absent(key=key, payload=payload)
        # Latched **after** the write, so a refused claim leaves no half-open triple
        # behind for a later publication to complete under the wrong ordinal.
        self._pending = (identity, digest, ordinal, False)
        return outcome

    def _payload(self, *, key: ObjectKey, payload: bytes, dataset: str, digest: str) -> PutOutcome:
        """Rename one payload onto its request-scoped identity, and publish it there."""
        if self._pending is None:
            raise QualificationKeyError() from None
        identity, claimed_digest, ordinal, published = self._pending
        # One payload per triple. A second would either overwrite the request's own
        # evidence or collide with it, and neither is something to discover at the
        # backend.
        if published or digest != claimed_digest or digest != key.content_sha256:
            raise QualificationKeyError() from None
        scoped = qualification_payload_key(
            dataset=dataset,
            execution_id=self._execution_id,
            request_ordinal=ordinal,
            content_sha256=digest,
        )
        outcome = self._publisher.put_if_absent(key=scoped, payload=payload)
        self._pending = (identity, claimed_digest, ordinal, True)
        return outcome

    def _record(self, *, key: ObjectKey, payload: bytes, digest: str, leaf: str) -> PutOutcome:
        """Close one triple, after checking the record names the claim's own request."""
        if self._pending is None or not leaf.endswith(_JSON_SUFFIX):
            raise QualificationKeyError() from None
        identity, claimed_digest, ordinal, published = self._pending
        # A record marks an acquisition complete, so it may not close a triple whose
        # payload was never published: an entry naming a payload that does not exist
        # is exactly the evidence the locator must never be able to carry.
        if not published or leaf[: -len(_JSON_SUFFIX)] != identity or digest != claimed_digest:
            raise QualificationKeyError() from None
        outcome = self._publisher.put_if_absent(key=key, payload=payload)
        self._pending = None
        self._highest = ordinal
        return outcome


__all__ = [
    "ACQUISITIONS_SEGMENT",
    "DIGEST_SEGMENT",
    "OBJECTS_SEGMENT",
    "ORDINAL_WIDTH",
    "QUALIFICATION_SEGMENT",
    "REQUESTS_SEGMENT",
    "LicensedWriteOnlyPublisher",
    "NameOccupiedError",
    "QualificationKeyError",
    "QualificationPayloadRouter",
    "RequestCoordinate",
    "WriteOnlyS3Client",
    "qualification_payload_key",
    "request_ordinal_map",
    "request_ordinal_segment",
]
