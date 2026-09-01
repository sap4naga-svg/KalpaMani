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
from typing import Any, Final, Protocol

from kalpamani.data.contracts.errors import ObjectStoreBackendError, ObjectStoreError
from kalpamani.data.contracts.vocabulary import ObjectStoreFailure, ObjectStoreOperation
from kalpamani.data.objectstore import ObjectKey, PutOutcome, physical_key, require_publishable
from kalpamani.data.storage.s3 import (
    CHECKSUM_ALGORITHM,
    CONTENT_TYPE,
    SERVER_SIDE_ENCRYPTION,
    checksum_of,
    classify_backend_failure,
)

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


__all__ = [
    "LicensedWriteOnlyPublisher",
    "NameOccupiedError",
    "WriteOnlyS3Client",
]
