"""The exact-object read surface, and nothing that could become a search.

**This is a different surface for a different actor, and it widens nothing.** The
licensed research object store stays write-only: this module does not extend
:class:`~kalpamani.data.objectstore.ResearchObjectStore`, does not extend the
writer-side ``S3Client`` protocol, does not import either store implementation and
is unreachable from the acquisition path. The acquisition role has no object-byte
read, and nothing here changes that.

**What it can do is exactly what assessment needs and no more.**

- retrieve **one object by an exact validated key**, with an expected full-object
  digest and byte count;
- publish **one** private report, conditionally;
- resolve an occupied report name from **metadata only**, which is what a
  conditional write needs after a ``412``.

**What it cannot do is the point.** There is no ``list_objects_v2``, no prefix
enumeration, no delete, no copy, no bucket administration, no Bronze publication,
no CONTROL access, no credential source and no provider transport. A key is never
constructed from a pattern, a guess or a scan -- every read takes a reference that
came from a locator that was validated first, so there is no route by which this
could discover an object nobody named.

**Verification happens before interpretation, always.** The bytes are counted while
they are read, refused above the ceiling, then checked against the expected byte
count and hashed and checked against the expected digest. Only then may a caller
parse them. A parser that ran first would be interpreting unverified material,
which is how a corrupted or substituted object becomes a finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol

from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.contracts.vocabulary import DataClassification, ObjectStoreFailure
from kalpamani.data.objectstore import ObjectKey, physical_key
from kalpamani.data.storage.s3 import (
    CHECKSUM_ALGORITHM,
    CONTENT_TYPE,
    SERVER_SIDE_ENCRYPTION,
    checksum_of,
    classify_backend_failure,
)

#: The licensed classification prefix a logical key carries.
_LICENSED_PREFIX: Final = DataClassification.LICENSED.value.lower()

#: The only prefix :meth:`LicensedObjectReader.read_locator_by_name` will read from.
#: Spelled here rather than imported so this module stays independent of the locator
#: schema; a test asserts the two agree, which is the check that would catch a drift
#: an import would merely have hidden.
LOCATOR_KEY_PREFIX: Final = f"{_LICENSED_PREFIX}/qualification/sharadar/locators/"

#: Largest single object this reader will accept, in bytes. The acquisition path's
#: own per-response ceiling is 4 MiB, so no licensed payload it produced can exceed
#: this; the margin exists because a claim, a record and a payload are read through
#: one surface and only one of them is bounded by the transport.
MAX_READ_BYTES: Final = 8 * 1024 * 1024

#: How many bytes are pulled from the response stream per read call.
_CHUNK_BYTES: Final = 256 * 1024


class ReadOperation(StrEnum):
    """What the reader was doing when it refused.

    A vocabulary of this module's own, deliberately. The writer-side operation
    vocabulary has ``BIND``, ``PUT`` and ``HEAD`` and no ``GET`` -- because the
    store it describes has no read -- and adding one there would widen an accepted
    contract to describe a surface that is not its.
    """

    BIND = "BIND"
    GET = "GET"
    PUT = "PUT"
    HEAD = "HEAD"


class ReadFailure(StrEnum):
    """Why a read or a report publication refused. Closed and coarse.

    Coarse for the reason the whole redaction boundary exists: a finer vocabulary
    would have to come from the backend's own message, and that message carries the
    bucket, the key, the endpoint and the request id.
    """

    ACCESS_DENIED = "ACCESS_DENIED"
    NOT_FOUND = "NOT_FOUND"
    THROTTLED = "THROTTLED"
    TRANSIENT = "TRANSIENT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_KEY = "INVALID_KEY"
    TOO_LARGE = "TOO_LARGE"
    INTEGRITY_MISMATCH = "INTEGRITY_MISMATCH"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    COLLISION = "COLLISION"
    UNKNOWN = "UNKNOWN"


#: How a backend failure category maps onto this module's. **Total, and checked by
#: a test**: no ``.get`` default and no ``else``, so a category added to the shared
#: vocabulary later has no mapping at all and fails loudly rather than becoming an
#: optimistic guess.
_BACKEND_FAILURE: Final[dict[ObjectStoreFailure, ReadFailure]] = {
    ObjectStoreFailure.ACCESS_DENIED: ReadFailure.ACCESS_DENIED,
    ObjectStoreFailure.PRECONDITION_FAILED: ReadFailure.PRECONDITION_FAILED,
    ObjectStoreFailure.NOT_FOUND: ReadFailure.NOT_FOUND,
    ObjectStoreFailure.THROTTLED: ReadFailure.THROTTLED,
    ObjectStoreFailure.TRANSIENT: ReadFailure.TRANSIENT,
    ObjectStoreFailure.INVALID_RESPONSE: ReadFailure.INVALID_RESPONSE,
    ObjectStoreFailure.INVALID_CONFIGURATION: ReadFailure.INVALID_CONFIGURATION,
    ObjectStoreFailure.UNKNOWN: ReadFailure.UNKNOWN,
}


class LicensedReadError(Exception):
    """A refusal built from two closed vocabulary members and nothing else.

    There is no parameter for a bucket, a key, an endpoint, a request id or a
    backend message, so none of them can arrive. Raised ``from None`` everywhere.
    """

    __slots__ = ("failure", "operation")

    def __init__(self, *, operation: ReadOperation, failure: ReadFailure) -> None:
        """Carry an operation and a failure category. Nothing else has a home here."""
        if type(operation) is not ReadOperation or type(failure) is not ReadFailure:
            raise TypeError("operation and failure must be exact members")
        self.operation = operation
        self.failure = failure
        super().__init__(f"licensed read {operation.value}: {failure.value}")


def _refuse(operation: ReadOperation, failure: ReadFailure) -> LicensedReadError:
    return LicensedReadError(operation=operation, failure=failure)


def _classified(exception: BaseException, operation: ReadOperation) -> LicensedReadError:
    """Reduce a backend exception to a closed refusal. Nothing survives the call."""
    category = classify_backend_failure(exception)
    return _refuse(operation, _BACKEND_FAILURE.get(category, ReadFailure.UNKNOWN))


class AssessmentS3Client(Protocol):
    """The three operations assessment uses, and **not one more**.

    Structurally satisfied by a ``boto3`` S3 client. Deliberately a separate
    protocol from the writer-side one rather than an extension of it: the writer
    must never gain a read, and a shared protocol carrying both would be exactly
    that. There is no ``list_objects_v2``, ``delete_object`` or ``copy_object`` in
    the shape, so this surface could not enumerate, delete or duplicate an object
    even if a future edit tried to.
    """

    def get_object(self, **kwargs: Any) -> Any:
        """Read one object by exact key."""
        ...

    def put_object(self, **kwargs: Any) -> Any:
        """Write one object."""
        ...

    def head_object(self, **kwargs: Any) -> Any:
        """Read one object's metadata. Never its body."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ExactObjectReference:
    """One object named by a logical key, an expected digest and a byte count.

    **All three, always.** A reference carrying only a key would let a substituted
    object be read and parsed; a reference carrying only a digest could not be
    fetched without a search. The triple is what makes an exact read exact, and
    every one of them comes from a locator that was validated before any byte was
    requested.
    """

    logical_key: str
    expected_sha256: str
    expected_bytes: int

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a stand-in could relax its own expectations."""
        raise TypeError("ExactObjectReference may not be subclassed")

    def __post_init__(self) -> None:
        """Hold the triple to its grammar before anything can be requested with it."""
        if type(self.logical_key) is not str or not self.logical_key:
            raise _refuse(ReadOperation.GET, ReadFailure.INVALID_KEY) from None
        if type(self.expected_sha256) is not str or len(self.expected_sha256) != 64:
            raise _refuse(ReadOperation.GET, ReadFailure.INVALID_KEY) from None
        if any(character not in "0123456789abcdef" for character in self.expected_sha256):
            raise _refuse(ReadOperation.GET, ReadFailure.INVALID_KEY) from None
        if type(self.expected_bytes) is not int or self.expected_bytes < 0:
            raise _refuse(ReadOperation.GET, ReadFailure.INVALID_KEY) from None
        if not self.logical_key.startswith(f"{_LICENSED_PREFIX}/"):
            # Refused at construction rather than at first use. A reference naming a
            # non-licensed key should never exist, and a check that only fires when
            # somebody happens to build the key is a check that can be skipped.
            raise _refuse(ReadOperation.GET, ReadFailure.INVALID_KEY) from None

    def object_key(self) -> ObjectKey:
        """The validated :class:`~kalpamani.data.objectstore.ObjectKey` this names.

        Rebuilt through the accepted key type, so the classification rule, the
        path-segment grammar and the digest grammar are the store's own rather than
        a second opinion. This is the *name and expected digest* addressing the
        architecture requires: the bytes are not held, and could not be.

        Raises:
            LicensedReadError: ``GET: INVALID_KEY`` for a key that is not a licensed
                logical key this system could have minted.
        """
        prefix = f"{_LICENSED_PREFIX}/"
        if not self.logical_key.startswith(prefix):
            raise _refuse(ReadOperation.GET, ReadFailure.INVALID_KEY) from None
        segments = self.logical_key[len(prefix) :].split("/")
        try:
            return ObjectKey(
                classification=DataClassification.LICENSED,
                segments=tuple(segments),
                content_sha256=self.expected_sha256,
            )
        except Exception:
            raise _refuse(ReadOperation.GET, ReadFailure.INVALID_KEY) from None


def _bounded_body(response: Any, *, ceiling: int) -> bytes:
    """Every byte of a response body, refused above ``ceiling`` **while reading**.

    Read in chunks with a running total rather than in one call, so an object far
    larger than the ceiling is abandoned rather than materialised first. A ceiling
    enforced after the bytes are already in memory is not a ceiling.
    """
    body = getattr(response, "get", None)
    stream = response.get("Body") if callable(body) else None
    if stream is None or not callable(getattr(stream, "read", None)):
        raise _refuse(ReadOperation.GET, ReadFailure.INVALID_RESPONSE) from None

    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            chunk = stream.read(_CHUNK_BYTES)
        except Exception:
            raise _refuse(ReadOperation.GET, ReadFailure.INVALID_RESPONSE) from None
        if not chunk:
            break
        if type(chunk) is not bytes:
            raise _refuse(ReadOperation.GET, ReadFailure.INVALID_RESPONSE) from None
        total += len(chunk)
        if total > ceiling:
            raise _refuse(ReadOperation.GET, ReadFailure.TOO_LARGE) from None
        chunks.append(chunk)
    return b"".join(chunks)


class LicensedObjectReader:
    """Exact reads and one conditional report write, against one licensed bucket.

    The client and the bucket are injected. This class discovers neither, so it
    cannot be pointed at a bucket by an environment variable, a profile or a
    module-level default -- and it constructs no SDK client of its own.

    Counters are attributes rather than a return value because they must survive a
    refusal: a run that failed halfway still has to be able to report what it did.
    """

    __slots__ = ("_bucket", "_client", "get_object_count", "head_object_count", "put_object_count")

    def __init__(self, *, client: AssessmentS3Client, licensed_bucket: str) -> None:
        """Bind an injected client to one licensed bucket.

        Raises:
            LicensedReadError: ``BIND: INVALID_CONFIGURATION`` for a bucket value or
                a client this reader cannot use. **The refusal never echoes the
                value** -- a bucket name is a private identifier, so it may not
                appear in an error any more than in a log.
        """
        if type(licensed_bucket) is not str or not 3 <= len(licensed_bucket) <= 63:
            raise _refuse(ReadOperation.BIND, ReadFailure.INVALID_CONFIGURATION) from None
        for method in ("get_object", "put_object", "head_object"):
            if not callable(getattr(client, method, None)):
                raise _refuse(ReadOperation.BIND, ReadFailure.INVALID_CONFIGURATION) from None
        self._client = client
        self._bucket = licensed_bucket
        self.get_object_count = 0
        self.put_object_count = 0
        self.head_object_count = 0

    def read_locator_by_name(self, *, logical_key: str, max_bytes: int) -> bytes:
        """The bytes of **the one object addressed by name**, bounded while reading.

        The locator is the single asymmetry this architecture rests on: its content
        address cannot be known before it is read, because knowing it would require
        the bytes. So it is retrieved by a key derived from the execution identity
        alone, and its integrity is established **afterwards** by its closed schema
        validation and its size ceiling -- never by a digest it could not have
        supplied.

        **This is not a general by-name read, and it structurally cannot become one.**
        The key must lie under the locator prefix; every other object in this
        architecture is reachable only through :meth:`read_exact`, which demands an
        expected digest and byte count. Without that restriction this method would be
        the arbitrary-read capability the whole design removes.

        Raises:
            LicensedReadError: ``GET: INVALID_KEY`` for a key outside the locator
                prefix or an unusable ceiling; ``GET: TOO_LARGE`` above it; and the
                closed backend categories for anything the store refused.
        """
        if type(logical_key) is not str or not logical_key.startswith(LOCATOR_KEY_PREFIX):
            raise _refuse(ReadOperation.GET, ReadFailure.INVALID_KEY) from None
        if type(max_bytes) is not int or not 0 < max_bytes <= MAX_READ_BYTES:
            raise _refuse(ReadOperation.GET, ReadFailure.INVALID_KEY) from None
        segments = logical_key[len(f"{_LICENSED_PREFIX}/") :].split("/")
        if any(not segment for segment in segments):
            raise _refuse(ReadOperation.GET, ReadFailure.INVALID_KEY) from None

        self.get_object_count += 1
        try:
            response = self._client.get_object(Bucket=self._bucket, Key="/".join(segments))
        except Exception as exception:
            raise _classified(exception, ReadOperation.GET) from None
        return _bounded_body(response, ceiling=max_bytes)

    def __repr__(self) -> str:
        """Counts only. **Never the bucket, the client or a key.**"""
        return (
            f"LicensedObjectReader(get={self.get_object_count}, "
            f"put={self.put_object_count}, head={self.head_object_count})"
        )

    def read_exact(self, reference: ExactObjectReference) -> bytes:
        """The verified bytes of one referenced object.

        The byte count and the digest are checked **before this returns**, so a
        caller that parses the result is parsing material whose identity was proven
        rather than assumed. The digest is recomputed locally rather than read from
        the backend's own checksum header: a backend that returned the wrong object
        would return its checksum with it.

        Raises:
            LicensedReadError: ``GET: INVALID_KEY`` for an unusable reference;
                ``GET: TOO_LARGE`` above the ceiling; ``GET: INTEGRITY_MISMATCH`` if
                the byte count or the digest is not the one the reference expects;
                and the closed backend categories for anything the store refused.
                **No refusal names the key, the bucket or the backend's message.**
        """
        if type(reference) is not ExactObjectReference:
            raise _refuse(ReadOperation.GET, ReadFailure.INVALID_KEY) from None
        if reference.expected_bytes > MAX_READ_BYTES:
            # Refused before the request, not after the bytes arrive.
            raise _refuse(ReadOperation.GET, ReadFailure.TOO_LARGE) from None
        location = physical_key(reference.object_key())

        self.get_object_count += 1
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=location)
        except Exception as exception:
            raise _classified(exception, ReadOperation.GET) from None

        payload = _bounded_body(response, ceiling=min(MAX_READ_BYTES, reference.expected_bytes))
        if len(payload) != reference.expected_bytes:
            raise _refuse(ReadOperation.GET, ReadFailure.INTEGRITY_MISMATCH) from None
        if sha256_hex(payload) != reference.expected_sha256:
            raise _refuse(ReadOperation.GET, ReadFailure.INTEGRITY_MISMATCH) from None
        return payload

    def publish_report(self, *, key: ObjectKey, payload: bytes) -> bool:
        """Publish one private report conditionally. ``True`` if this call wrote it.

        One conditional ``PutObject``, and **no retry**: unlike a locator, a failed
        report costs only a re-run of an assessment that makes zero provider
        requests, so the cheap remedy is a new assessment identity rather than a
        repeat. An occupied name is resolved from metadata exactly once, which is
        the ``412`` path the append-only writer already establishes.

        Raises:
            LicensedReadError: ``PUT`` or ``HEAD`` with a closed category;
                ``HEAD: COLLISION`` if the name holds different content.
        """
        if type(key) is not ObjectKey or type(payload) is not bytes:
            raise _refuse(ReadOperation.PUT, ReadFailure.INVALID_CONFIGURATION) from None
        if sha256_hex(payload) != key.content_sha256:
            raise _refuse(ReadOperation.PUT, ReadFailure.INTEGRITY_MISMATCH) from None
        location = physical_key(key)

        self.put_object_count += 1
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=location,
                Body=payload,
                ContentLength=len(payload),
                ContentType=CONTENT_TYPE,
                ChecksumAlgorithm=CHECKSUM_ALGORITHM,
                ChecksumSHA256=checksum_of(key.content_sha256),
                ServerSideEncryption=SERVER_SIDE_ENCRYPTION,
                IfNoneMatch="*",
            )
        except Exception as exception:
            refusal = _classified(exception, ReadOperation.PUT)
            if refusal.failure is not ReadFailure.PRECONDITION_FAILED:
                raise refusal from None
            return self._resolve_report_name(key=key, location=location, byte_count=len(payload))
        return True

    def _resolve_report_name(self, *, key: ObjectKey, location: str, byte_count: int) -> bool:
        """Decide what an occupied report name means, from metadata alone.

        **Reached only after a ``412``.** Identical content is an ordinary
        idempotent re-publication and answers ``False``; different content is a
        collision; content that cannot be proven either way is a refusal, because
        the one answer never available here is a guess.
        """
        self.head_object_count += 1
        try:
            response = self._client.head_object(
                Bucket=self._bucket, Key=location, ChecksumMode="ENABLED"
            )
        except Exception as exception:
            raise _classified(exception, ReadOperation.HEAD) from None

        if not callable(getattr(response, "get", None)):
            raise _refuse(ReadOperation.HEAD, ReadFailure.INVALID_RESPONSE) from None
        checksum_type = response.get("ChecksumType")
        encoded = response.get("ChecksumSHA256")
        length = response.get("ContentLength")
        if checksum_type != "FULL_OBJECT" or type(encoded) is not str:
            # A composite checksum is a digest of part digests rather than of the
            # object, and an absent type is simply unproven. Both fail closed.
            raise _refuse(ReadOperation.HEAD, ReadFailure.INVALID_RESPONSE) from None
        if type(length) is not int or length < 0:
            raise _refuse(ReadOperation.HEAD, ReadFailure.INVALID_RESPONSE) from None
        if encoded == checksum_of(key.content_sha256) and length == byte_count:
            return False
        raise _refuse(ReadOperation.HEAD, ReadFailure.COLLISION) from None


__all__ = [
    "LOCATOR_KEY_PREFIX",
    "MAX_READ_BYTES",
    "AssessmentS3Client",
    "ExactObjectReference",
    "LicensedObjectReader",
    "LicensedReadError",
    "ReadFailure",
    "ReadOperation",
]
