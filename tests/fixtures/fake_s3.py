"""A synthetic, thread-safe S3 client. **Opens no socket and knows no AWS.**

It implements exactly the two operations
:class:`~kalpamani.data.storage.s3.S3Client` declares, with the semantics the
adapter depends on:

* ``PutObject`` with ``IfNoneMatch="*"`` is **atomic** -- the occupancy check and
  the store happen under one lock, so two concurrent writers cannot both win.
  A fake that checked and then stored would hide exactly the race the adapter's
  conditional write exists to close, and the concurrency tests would pass against
  a broken implementation.
* ``HeadObject`` returns the stored full-object SHA-256 and length, and nothing
  else the adapter is allowed to read.

Every recorded call is kept so a test can assert on what was *sent* -- the
conditional header, the checksum, the encryption -- rather than only on what came
back.

The bucket names, keys and payloads here are invented. No real bucket name, no
credential and no vendor row appears anywhere in this file.
"""

from __future__ import annotations

import base64
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

#: An invented bucket name with a valid S3 shape. **Not a real bucket**, and
#: deliberately says so in the value itself.
SYNTHETIC_BUCKET = "synthetic-fake-not-a-real-bucket"


class SyntheticClientError(Exception):
    """An exception shaped like ``botocore.exceptions.ClientError``.

    The adapter classifies structurally rather than by type, so this stands in
    for the real thing without importing an SDK. Its ``message`` deliberately
    carries bucket-, key-, URL-, request-id- and credential-shaped text, so a
    test can prove none of it escapes the adapter's translated refusal.
    """

    def __init__(self, code: str, *, operation: str = "PutObject") -> None:
        self.response: dict[str, Any] = {
            "Error": {
                "Code": code,
                "Message": (
                    "synthetic-fake-not-a-real-bucket/bronze/leak.bin failed at "
                    "https://synthetic-fake-not-a-real-bucket.s3.eu-west-1.amazonaws.com "
                    "with aws_access_key_id=AKIAsyntheticFAKEKEY0001 "
                    "session_token=synthetic-fake-session-token"
                ),
                "BucketName": SYNTHETIC_BUCKET,
                "Key": "bronze/leak.bin",
            },
            "ResponseMetadata": {
                "RequestId": "SYNTHETICFAKEREQ0001",
                "HostId": "synthetic-fake-host-id",
                "HTTPHeaders": {"x-amz-id-2": "synthetic-fake-host-id"},
            },
        }
        self.operation_name = operation
        super().__init__(
            f"An error occurred ({code}) when calling the {operation} operation: "
            f"{self.response['Error']['Message']}"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredObject:
    """What the fake keeps per key. Bytes plus the checksum it was admitted under."""

    body: bytes
    checksum_sha256: str


@dataclass
class FakeS3Client:
    """A conditional-write S3 client held entirely in memory.

    ``fail_put`` / ``fail_head`` queue exceptions to raise instead of serving a
    request, so backend-failure paths can be exercised without a network.
    ``head_override`` replaces the next ``HeadObject`` response, so malformed and
    contradictory responses can be tested.
    """

    bucket: str = SYNTHETIC_BUCKET
    objects: dict[str, StoredObject] = field(default_factory=dict)
    put_calls: list[dict[str, Any]] = field(default_factory=list)
    head_calls: list[dict[str, Any]] = field(default_factory=list)
    fail_put: list[BaseException] = field(default_factory=list)
    fail_head: list[BaseException] = field(default_factory=list)
    head_override: list[Any] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # -- the two operations the adapter may call ---------------------------

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]:
        """Store an object, honouring ``IfNoneMatch="*"`` **atomically**."""
        with self._lock:
            self.put_calls.append(dict(kwargs))
            if self.fail_put:
                raise self.fail_put.pop(0)
            if kwargs.get("Bucket") != self.bucket:
                raise SyntheticClientError("NoSuchBucket")
            key = kwargs["Key"]
            conditional = kwargs.get("IfNoneMatch") == "*"
            if conditional and key in self.objects:
                raise SyntheticClientError("PreconditionFailed")
            body = kwargs["Body"]
            self.objects[key] = StoredObject(
                body=body,
                checksum_sha256=base64.b64encode(sha256(body).digest()).decode("ascii"),
            )
            return {"ETag": '"synthetic-fake-etag"'}

    def head_object(self, **kwargs: Any) -> Mapping[str, Any]:
        """Return one object's checksum and length. **Never its body.**"""
        with self._lock:
            self.head_calls.append(dict(kwargs))
            if self.fail_head:
                raise self.fail_head.pop(0)
            if self.head_override:
                return self.head_override.pop(0)  # type: ignore[no-any-return]
            stored = self.objects.get(kwargs["Key"])
            if stored is None:
                raise SyntheticClientError("404", operation="HeadObject")
            return {
                "ChecksumSHA256": stored.checksum_sha256,
                "ContentLength": len(stored.body),
                "ETag": '"synthetic-fake-etag"',
            }

    # -- assertions helpers, not part of the client surface ----------------

    @property
    def stored_keys(self) -> list[str]:
        """Every physical key currently held, sorted."""
        return sorted(self.objects)

    def body_of(self, key: str) -> bytes:
        """The exact bytes stored at a physical key. For assertions only."""
        return self.objects[key].body


#: Text a translated refusal must never contain. Every value appears somewhere in
#: :class:`SyntheticClientError`, so a test that finds none of them has proven the
#: adapter's sanitisation rather than merely asserted it.
LEAK_CANARIES = (
    SYNTHETIC_BUCKET,
    "bronze/leak.bin",
    "https://",
    "amazonaws.com",
    "AKIAsyntheticFAKEKEY0001",
    "synthetic-fake-session-token",
    "SYNTHETICFAKEREQ0001",
    "synthetic-fake-host-id",
    "aws_access_key_id",
)


__all__ = [
    "LEAK_CANARIES",
    "SYNTHETIC_BUCKET",
    "FakeS3Client",
    "StoredObject",
    "SyntheticClientError",
]
