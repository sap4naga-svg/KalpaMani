"""The licensed S3 :class:`~kalpamani.data.objectstore.ResearchObjectStore`.

**Code only. This has never been invoked against AWS.** No credential exists, no
bucket is bound, no client is constructed anywhere in this repository, and no
runner or composition root is authorized to build one (ADR-0011). What is here is
the adapter a future authorized runner would inject a client into -- reviewed
calmly, before a credential exists and before a bill is running.

**The whole module is one seam.** Everything above it -- the neutral Bronze
publisher, every provider adapter -- depends on the ``ResearchObjectStore``
protocol and knows no bucket, no ARN, no account, no profile and no SDK type. A
static test enforces that, and this is the only module permitted to speak S3 at
all.

**No SDK is imported here, deliberately.** The client is *injected*
(:class:`S3Client`), so this module never constructs one -- which means importing
the data platform pulls in no AWS SDK, opens no socket and performs no ambient
credential discovery. The SDK remains a declared dependency because something has
to *build* that client, and signing, credential resolution and retry behaviour
must be the official SDK's rather than anything written here. Exceptions are
classified structurally, by the shape a ``ClientError`` actually has, so a stub, a
real error and a subclass are all handled without an import.

**Append-only is enforced by one conditional request, not by looking first.**

.. code-block:: text

    HEAD -> if absent -> PUT          <- REJECTED: time-of-check/time-of-use race
    PUT with IfNoneMatch="*"          <- what this does

The licensed bucket carries **no versioning** by design (ADR-0007, CLAUDE.md
§4.23): a vendor termination arriving without notice must be honourable inside 30
days, and versioning would leave copies behind. That makes S3 unable to protect
an overwrite for us, so *conditional publication in software is the immutability
boundary*. Between a HEAD and a PUT another writer can land an object, and the
PUT would then destroy evidence that verified a moment earlier.

**Integrity is SHA-256, never ETag.** An ETag is a multipart-dependent opaque
token, not a content hash; treating it as one would make every identity claim in
this system conditional on how the object happened to be uploaded. Every write
carries a full-object SHA-256 checksum, and every read-back verifies one.

**A collision is resolved by metadata, never by downloading.** When the
conditional write reports the name occupied, the stored object's checksum and
length are fetched with ``HeadObject`` and compared. The bytes are never
retrieved: this store has no read surface, a producer has no reason to read the
store back, and downloading vendor payloads to compare them would put licensed
rows into a process that has no business holding them.

**Fail closed, everywhere.** An occupied name that cannot be *proven* identical is
a refusal, not an assumption -- not "probably the same", not "treat as absent",
and not "download and see". A permission failure is never absence.

**CONTROL has no route through this module.** There is no classification
parameter anywhere below, and
:func:`~kalpamani.data.objectstore.require_exact_key` refuses a non-LICENSED key
before a request is built. Publishing to the control store stays deferred until a
structured, durably bound attestation exists.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping
from typing import Any, Final, Protocol

from kalpamani.data.contracts.errors import (
    ObjectAlreadyExistsError,
    ObjectStoreBackendError,
)
from kalpamani.data.contracts.vocabulary import ObjectStoreFailure, ObjectStoreOperation
from kalpamani.data.objectstore import (
    ObjectKey,
    PutOutcome,
    physical_key,
    require_exact_key,
    require_publishable,
)

#: Server-side encryption every object is written with. SSE-S3, stated explicitly
#: rather than relied on from a bucket default, so an object is encrypted because
#: this code asked rather than because a setting happened to survive.
SERVER_SIDE_ENCRYPTION: Final = "AES256"

#: Payloads are opaque bytes. Naming a media type would invite a reader to parse
#: them, and Bronze exists precisely so nothing has to.
CONTENT_TYPE: Final = "application/octet-stream"

#: The checksum algorithm. Full-object SHA-256, which is the same digest the
#: :class:`~kalpamani.data.objectstore.ObjectKey` is named by.
CHECKSUM_ALGORITHM: Final = "SHA256"

#: S3 bucket naming: 3-63 characters, lowercase letters, digits, dots and hyphens,
#: starting and ending alphanumeric. Deliberately *not* an exhaustive AWS
#: validator -- it exists to refuse an ARN, an ``s3://`` URI, a path or a typo
#: before any of them reaches a request.
_BUCKET_NAME: Final = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$")

#: Backend error codes that mean the name is already taken. ``PreconditionFailed``
#: is what a conditional ``PutObject`` returns; ``ConditionalRequestConflict``
#: appears when a concurrent write is in flight against the same key.
_OCCUPIED_CODES: Final[frozenset[str]] = frozenset(
    {"PreconditionFailed", "ConditionalRequestConflict"}
)

_NOT_FOUND_CODES: Final[frozenset[str]] = frozenset({"404", "NoSuchKey", "NotFound"})
_DENIED_CODES: Final[frozenset[str]] = frozenset(
    {"AccessDenied", "403", "AllAccessDisabled", "InvalidAccessKeyId", "SignatureDoesNotMatch"}
)
_THROTTLED_CODES: Final[frozenset[str]] = frozenset(
    {"SlowDown", "Throttling", "ThrottlingException", "RequestLimitExceeded", "503"}
)
_TRANSIENT_CODES: Final[frozenset[str]] = frozenset(
    {"InternalError", "ServiceUnavailable", "RequestTimeout", "500"}
)


class S3Client(Protocol):
    """The two S3 operations this store uses, and nothing else.

    Structurally satisfied by a ``boto3`` S3 client. Narrow on purpose: there is
    no ``get_object``, ``delete_object``, ``list_objects_v2`` or ``copy_object``
    in the shape, so this store could not read, delete, enumerate or duplicate an
    object even if a future edit tried to. Deletion belongs to the separately
    roled deletion path under ADR-0007, and a routine research writer must never
    hold it.
    """

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]:
        """Write one object."""
        ...

    def head_object(self, **kwargs: Any) -> Mapping[str, Any]:
        """Read one object's metadata. Never its body."""
        ...


def _error_code(exception: BaseException) -> str:
    """The backend's error code, read structurally so no SDK import is needed.

    A ``botocore`` ``ClientError`` carries ``response["Error"]["Code"]``. Read
    defensively: every access is guarded, because an exception that raised while
    being *classified* would escape carrying its own message -- which is the one
    thing this module exists to prevent.
    """
    try:
        response = getattr(exception, "response", None)
        if not isinstance(response, Mapping):
            return ""
        error = response.get("Error")
        if not isinstance(error, Mapping):
            return ""
        code = error.get("Code")
        return code if type(code) is str else ""
    except Exception:
        return ""


def classify_backend_failure(exception: BaseException) -> ObjectStoreFailure:
    """Reduce a backend exception to one closed category.

    Nothing from ``exception`` survives this call. The code is matched against
    fixed sets; anything unrecognised is ``UNKNOWN``, never optimistic.
    """
    code = _error_code(exception)
    if code in _OCCUPIED_CODES:
        return ObjectStoreFailure.PRECONDITION_FAILED
    if code in _NOT_FOUND_CODES:
        return ObjectStoreFailure.NOT_FOUND
    if code in _DENIED_CODES:
        return ObjectStoreFailure.ACCESS_DENIED
    if code in _THROTTLED_CODES:
        return ObjectStoreFailure.THROTTLED
    if code in _TRANSIENT_CODES:
        return ObjectStoreFailure.TRANSIENT
    return ObjectStoreFailure.UNKNOWN


def _refuse(
    operation: ObjectStoreOperation, failure: ObjectStoreFailure
) -> ObjectStoreBackendError:
    return ObjectStoreBackendError(operation=operation, failure=failure)


def checksum_of(digest_hex: str) -> str:
    """The base64 form S3 expects of a hex SHA-256 digest.

    S3 carries checksums base64-encoded over the raw digest bytes; the
    :class:`~kalpamani.data.objectstore.ObjectKey` carries the same digest as
    lowercase hex. One conversion, in one place, so the two spellings cannot
    drift.
    """
    return base64.b64encode(bytes.fromhex(digest_hex)).decode("ascii")


def _verified_stored_identity(response: object, operation: ObjectStoreOperation) -> tuple[str, int]:
    """The ``(sha256 hex, byte count)`` a ``HeadObject`` response proves.

    Raises:
        ObjectStoreBackendError: ``INVALID_RESPONSE`` if the response is not a
            mapping, carries no full-object SHA-256, carries one that is not
            canonical base64 of 32 bytes, or carries no usable length. **An
            object whose stored identity cannot be verified is never treated as
            identical and never treated as absent** -- both guesses would be
            wrong in the direction that loses evidence.
    """
    if not isinstance(response, Mapping):
        raise _refuse(operation, ObjectStoreFailure.INVALID_RESPONSE)

    encoded = response.get("ChecksumSHA256")
    if type(encoded) is not str or not encoded:
        raise _refuse(operation, ObjectStoreFailure.INVALID_RESPONSE)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        raise _refuse(operation, ObjectStoreFailure.INVALID_RESPONSE) from None
    if len(raw) != 32 or base64.b64encode(raw).decode("ascii") != encoded:
        # Non-canonical encoding is refused too: two spellings of one digest
        # would be two identities for one object.
        raise _refuse(operation, ObjectStoreFailure.INVALID_RESPONSE)

    length = response.get("ContentLength")
    if type(length) is not int or length < 0:
        raise _refuse(operation, ObjectStoreFailure.INVALID_RESPONSE)

    return raw.hex(), length


class S3ResearchObjectStore:
    """LICENSED-only, append-only object storage backed by one S3 bucket.

    Implements :class:`~kalpamani.data.objectstore.ResearchObjectStore` and adds
    **nothing** to that surface: two methods, no read, no list, no delete, no
    copy, no overwrite.

    The client and the bucket are injected. This class discovers neither, so it
    cannot be pointed at a bucket by an environment variable, a profile or a
    module-level default -- the binding is a decision made by whoever constructs
    it, and no such construction is authorized yet.
    """

    __slots__ = ("_bucket", "_client")

    def __init__(self, *, client: S3Client, licensed_bucket: str) -> None:
        """Bind an injected S3 client to one licensed bucket.

        Raises:
            ObjectStoreBackendError: ``BIND: INVALID_CONFIGURATION`` if
                ``licensed_bucket`` is not an exact plain string with a valid S3
                bucket-name shape, or if ``client`` cannot serve the two
                operations this store uses. **The refusal never echoes the
                value** -- a bucket name is a private identifier under CLAUDE.md
                §3, so it may not appear in an error any more than in a log.
        """
        if type(licensed_bucket) is not str or not _BUCKET_NAME.match(licensed_bucket):
            raise _refuse(ObjectStoreOperation.BIND, ObjectStoreFailure.INVALID_CONFIGURATION)
        if not callable(getattr(client, "put_object", None)) or not callable(
            getattr(client, "head_object", None)
        ):
            raise _refuse(ObjectStoreOperation.BIND, ObjectStoreFailure.INVALID_CONFIGURATION)
        self._bucket = licensed_bucket
        self._client = client

    def __repr__(self) -> str:
        """Names the class and its classification. **Never the bucket or client.**

        There is nothing caller-supplied in this string, which is what makes it
        safe to log without anyone having to think about it.
        """
        return "S3ResearchObjectStore(classification=LICENSED)"

    def put_if_absent(self, *, key: ObjectKey, payload: bytes) -> PutOutcome:
        """Publish ``payload`` under ``key`` unless the name is already occupied.

        One conditional ``PutObject``. No preflight ``HeadObject``: checking first
        and writing second is a race that overwrites whatever landed in between,
        and on a bucket with no versioning an overwrite is unrecoverable.

        Raises:
            ObjectClassificationError: if ``key`` is not an exact, publishable key.
            ObjectPayloadTypeError: if ``payload`` is not exact, immutable bytes.
            ObjectContentMismatchError: if ``payload`` does not hash to ``key``.
            ObjectAlreadyExistsError: if the name holds *different*, verified
                content. Append-only: never overwritten, never renamed, never
                silently reported as an idempotent no-op.
            ObjectStoreBackendError: for any backend refusal, and for an occupied
                name whose content cannot be verified.
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
            if failure is not ObjectStoreFailure.PRECONDITION_FAILED:
                # `from None`: the SDK exception carries the bucket, the key, the
                # endpoint and the request id, and a chained traceback would
                # print all of it.
                raise _refuse(ObjectStoreOperation.PUT, failure) from None
            return self._resolve_occupied(key=key, location=location, byte_count=len(exact))
        return PutOutcome(key=key, stored=True, byte_count=len(exact))

    def _resolve_occupied(self, *, key: ObjectKey, location: str, byte_count: int) -> PutOutcome:
        """Decide what an occupied name means, from metadata alone.

        Identical content is an ordinary idempotent re-publication. Different
        content is a refusal. Content that cannot be *proven* either way is also
        a refusal -- the one answer that is never available here is a guess.
        """
        try:
            response = self._client.head_object(
                Bucket=self._bucket, Key=location, ChecksumMode="ENABLED"
            )
        except Exception as exception:
            failure = classify_backend_failure(exception)
            if failure is ObjectStoreFailure.NOT_FOUND:
                # The conditional write said occupied and the HEAD says absent.
                # Both cannot be true of one moment. Refuse rather than retry
                # unconditionally: the retry that "fixes" this is an overwrite.
                raise _refuse(
                    ObjectStoreOperation.HEAD, ObjectStoreFailure.INVALID_RESPONSE
                ) from None
            raise _refuse(ObjectStoreOperation.HEAD, failure) from None

        stored_digest, stored_length = _verified_stored_identity(
            response, ObjectStoreOperation.HEAD
        )
        if stored_digest == key.content_sha256 and stored_length == byte_count:
            return PutOutcome(key=key, stored=False, byte_count=byte_count)
        raise ObjectAlreadyExistsError(
            f"{key.logical_key} already holds different content. This store is append-only: "
            "a second payload under one name is either a collision or a corruption, and "
            "neither is resolved by overwriting."
        )

    def exists(self, *, key: ObjectKey) -> bool:
        """Whether this exact object -- name **and** content address -- is stored.

        ``False`` when the name is occupied by different content: the object that
        was asked about is not there. That is not the same as the name being
        free, and :meth:`put_if_absent` will still refuse such a write.

        Raises:
            ObjectClassificationError: if ``key`` is not an exact, publishable key.
            ObjectStoreBackendError: for a denied, throttled, transient or
                unverifiable response. **A permission failure is not absence** --
                answering ``False`` there would let a misconfigured role
                re-publish over objects it simply could not see.
        """
        require_exact_key(key)
        try:
            response = self._client.head_object(
                Bucket=self._bucket, Key=physical_key(key), ChecksumMode="ENABLED"
            )
        except Exception as exception:
            failure = classify_backend_failure(exception)
            if failure is ObjectStoreFailure.NOT_FOUND:
                return False
            raise _refuse(ObjectStoreOperation.HEAD, failure) from None

        stored_digest, _ = _verified_stored_identity(response, ObjectStoreOperation.HEAD)
        return stored_digest == key.content_sha256


__all__ = [
    "CHECKSUM_ALGORITHM",
    "CONTENT_TYPE",
    "SERVER_SIDE_ENCRYPTION",
    "S3Client",
    "S3ResearchObjectStore",
    "checksum_of",
    "classify_backend_failure",
]
