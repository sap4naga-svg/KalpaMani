"""The provider-neutral research object store.

[ADR-0007](../../../docs/decisions/ADR-0007-cloud-first-research-data-plane.md)
made a private AWS account the intended authoritative location for licensed
research data, and anticipated an interface between the code that *produces* an
object and the code that *puts it somewhere*. This is that interface, at the
smallest size that is production-worthy rather than a sketch.

**What a producer is not allowed to know.** A bucket name, an AWS account, an
ARN, a Terraform output, a profile name, an SDK type. All of them are deployment
facts, and a provider adapter that knew any of them could not be tested without
one -- which is how a "unit test" ends up needing credentials. A producer names a
*logical object*; a deployment binds that name to a location.

**What identity means here, stated precisely.** A logical key is::

    <classification>/<segment>/<segment>/.../<segment>

and an :class:`ObjectKey` is that name **together with** the SHA-256 the named
object must hold. The store therefore provides *immutable logical names with a
content-integrity binding*: a name refers to at most one payload for the life of
the store, and every operation checks that the payload under the name is the one
the key claims.

That is deliberately **not** the same as saying every path is content-addressed.
Only namespaces that put a digest *in the path* are content-addressed, and in
this system exactly one does -- the Bronze payload namespace built by
:mod:`kalpamani.data.ingest.publication`. An acquisition record lives at a path
named by ``(digest, run id)`` rather than by its own digest, so its identity is a
name plus an integrity binding. Claiming otherwise would suggest the store
computes locations from content, which it does not, and would make a reader
expect a re-published variant to land somewhere new instead of being refused.

**A name is taken by the first payload that claims it, and only by that payload.**
:meth:`~ResearchObjectStore.exists` answers about the *whole* key, so it is
``False`` when the name is occupied by different content -- and
:meth:`~ResearchObjectStore.put_if_absent` still refuses that write. The pairing
looks odd for a moment and is the honest one: the object you asked about is not
there, and the name is not free either. A forged key naming another object's path
therefore cannot read that object's bytes.

The classification prefix is not decoration. ADR-0007 keeps licensed vendor data
in a deletion-first store that carries no versioning, no Object Lock, no
replication and no backup, so that a termination arriving without notice can be
honoured inside 30 days. Control-plane material lives elsewhere precisely because
it must *survive* that deletion. An object whose classification were merely an
attribute could be moved between the two by an ordinary-looking edit; an object
whose classification is part of its key cannot move without becoming a different
object.

**LICENSED is structural, not a default argument.** :meth:`ObjectKey.licensed`
takes no classification parameter, so provider-derived material cannot be routed
anywhere else by omission, by a wrong keyword or by a copied line.
:meth:`ObjectKey.control` exists, and it demands a written attestation saying why
the object cannot reconstruct a vendor row. That attestation is refused when
empty, so "it is control-plane because I said so" is not expressible. The rule it
encodes is ADR-0007's classification question -- *can vendor rows be recovered
from this artifact?* -- under which **uncertain resolves to LICENSED**.

**Puts are append-only and idempotent.** :meth:`ResearchObjectStore.put_if_absent`
writes only when nothing is stored under the key. Re-putting identical bytes
reports ``stored=False`` and changes nothing; putting *different* bytes under an
existing key is refused rather than resolved, because an object store that
silently replaces evidence is not evidence.

**Nothing here opens a socket, reads a file or names a cloud.** The only
implementation in this module is :class:`InMemoryResearchObjectStore`, which is
for tests and local development. **The real S3 writer is a separate, later,
separately authorized slice** -- it is the piece that needs a credential, a bucket
and an SDK, and none of those is authorized here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.contracts.errors import (
    ObjectAlreadyExistsError,
    ObjectClassificationError,
    ObjectContentMismatchError,
)
from kalpamani.data.contracts.paths import safe_component
from kalpamani.data.contracts.vocabulary import DataClassification, closed_member

#: A content address is exactly 64 lowercase hex characters. Checked rather than
#: assumed: a key carrying a truncated or upper-cased digest would still be a
#: usable path component, and two spellings of one digest are two identities.
_CONTENT_ADDRESS: Final = re.compile(r"^[0-9a-f]{64}$")

#: Longest logical key this contract will mint. Not a security boundary -- a
#: legibility one, and a guard against a key no object store will accept.
MAX_LOGICAL_KEY_LENGTH: Final = 900


@dataclass(frozen=True, slots=True, kw_only=True)
class ObjectKey:
    """The logical name of one immutable object, and its content address.

    ``segments`` are the path below the classification prefix. Every one of them
    passes :func:`~kalpamani.data.contracts.paths.safe_component`, so a provider
    name, a dataset name or a run identifier arriving from outside the system
    cannot choose where we write.

    Prefer :meth:`licensed` and :meth:`control` over constructing this directly:
    they are the two spellings that make the classification decision visible at
    the call site.
    """

    classification: DataClassification
    segments: tuple[str, ...]
    content_sha256: str
    control_attestation: str = ""

    def __post_init__(self) -> None:
        # Normalised, not merely annotated. These are StrEnums, so a bare
        # "LICENSED" compares equal to the member everywhere except where
        # something reads `.value` -- which is exactly where the logical key is
        # built. An untyped classification would look correct to every test in
        # the system and then raise AttributeError while naming the object.
        classification = closed_member(DataClassification, self.classification)
        if classification is None:
            raise ObjectClassificationError(
                "classification must name a member of DataClassification "
                f"({[member.value for member in DataClassification]}). An unrecognised "
                "value cannot be resolved to a store, and guessing one would put an "
                "object somewhere nobody chose."
            )
        object.__setattr__(self, "classification", classification)
        if not self.segments:
            raise ObjectClassificationError(
                "An object key needs at least one segment; a bare classification prefix "
                "names a whole store rather than an object in it."
            )
        for segment in self.segments:
            safe_component(segment, kind="object key segment")
        if not _CONTENT_ADDRESS.match(self.content_sha256):
            raise ObjectContentMismatchError(
                f"content_sha256={self.content_sha256!r} is not 64 lowercase hex characters. "
                "A content address that two spellings can share is not an address."
            )
        if self.classification is DataClassification.CONTROL:
            if not self.control_attestation.strip():
                raise ObjectClassificationError(
                    "A CONTROL object requires a written attestation that vendor rows cannot "
                    "be reconstructed from it (ADR-0007). Uncertain resolves to LICENSED, so "
                    "an unattested object is licensed by construction rather than by choice."
                )
        elif self.control_attestation:
            raise ObjectClassificationError(
                "A LICENSED object carries no control attestation. An attestation on the "
                "licensed side records a decision nobody made, and would read as evidence "
                "that the object had been cleared."
            )
        if len(self.logical_key) > MAX_LOGICAL_KEY_LENGTH:
            raise ObjectClassificationError(
                f"logical key is {len(self.logical_key)} characters, over the "
                f"{MAX_LOGICAL_KEY_LENGTH} limit."
            )

    @property
    def logical_key(self) -> str:
        """The deployment-independent name of this object. No bucket, no host."""
        return "/".join((self.classification.value.lower(), *self.segments))

    @classmethod
    def licensed(cls, *segments: str, payload: bytes) -> ObjectKey:
        """Name a LICENSED object. **There is no parameter that changes that.**

        Provider-derived material, and anything that could reconstruct it, takes
        this route. The absence of a classification argument is the point:
        licensed is what you get by writing the ordinary thing.
        """
        return cls(
            classification=DataClassification.LICENSED,
            segments=tuple(segments),
            content_sha256=sha256_hex(payload),
        )

    @classmethod
    def control(cls, *segments: str, payload: bytes, attestation: str) -> ObjectKey:
        """Name a CONTROL object, on a written attestation that is refused when empty.

        Raises:
            ObjectClassificationError: if ``attestation`` is blank. The control
                store survives a vendor deletion, so putting a reconstructable
                artifact there would defeat the obligation ADR-0007 and
                CLAUDE.md §4.23 exist to keep provable.
        """
        return cls(
            classification=DataClassification.CONTROL,
            segments=tuple(segments),
            content_sha256=sha256_hex(payload),
            control_attestation=attestation,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PutOutcome:
    """What one :meth:`ResearchObjectStore.put_if_absent` actually did.

    ``stored`` is ``False`` when identical bytes were already present. That is an
    ordinary idempotent re-publication, not a repair and not an error -- and
    reporting it distinctly is what lets a caller tell "we wrote it" from "it was
    already there" without reading the store back.
    """

    key: ObjectKey
    stored: bool
    byte_count: int


class ResearchObjectStore(Protocol):
    """The whole contract a Bronze publisher needs, and nothing more.

    Two methods, deliberately. Listing, deleting, copying, versioning and metadata
    retrieval are all absent: deletion is a separately-roled operation under
    ADR-0007, versioning is forbidden on the licensed store, and a producer that
    could list the store could enumerate what a vendor sent.

    **Both methods are about the whole key**, name and content address together.
    An implementation that keyed on the logical name alone would let a key with a
    different ``content_sha256`` report ``exists`` and read back somebody else's
    bytes, which is the identity the type exists to prevent.
    """

    def put_if_absent(self, *, key: ObjectKey, payload: bytes) -> PutOutcome:
        """Store ``payload`` under ``key`` unless the name is already occupied.

        Raises:
            ObjectContentMismatchError: if ``payload`` does not hash to the
                content address ``key`` claims.
            ObjectAlreadyExistsError: if different content is already stored under
                this logical name. Append-only: an object store that replaces
                evidence is not evidence.
        """
        ...

    def exists(self, *, key: ObjectKey) -> bool:
        """Whether **this exact object** -- name and content address -- is stored.

        ``False`` when the name is occupied by different content. That is not the
        same as the name being free, and :meth:`put_if_absent` will still refuse
        such a write.
        """
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class _StoredObject:
    """One stored payload and the digest it was admitted under.

    The digest is stored rather than recomputed on every read. Recomputation
    would make an integrity check a function of the *current* bytes checking
    themselves -- true by construction, and therefore worth nothing.
    """

    payload: bytes
    content_sha256: str


class InMemoryResearchObjectStore:
    """A deterministic, process-local :class:`ResearchObjectStore`.

    **Not a cloud writer and not a durable store.** It exists so the publication
    mechanics can be proven end to end with no credential, no bucket, no SDK and
    no network -- which is the only honest way to test them before a provider is
    selected and ingestion is authorized.
    """

    def __init__(self) -> None:
        """Bind an empty store. Nothing outside this process is touched."""
        self._objects: dict[str, _StoredObject] = {}

    def put_if_absent(self, *, key: ObjectKey, payload: bytes) -> PutOutcome:
        """Store ``payload`` under ``key`` unless the name is already occupied."""
        digest = sha256_hex(payload)
        if digest != key.content_sha256:
            raise ObjectContentMismatchError(
                f"payload hashes to {digest}, but {key.logical_key} claims "
                f"{key.content_sha256}. A content address the content does not satisfy would "
                "make every identity in this store a coincidence."
            )
        stored = self._objects.get(key.logical_key)
        if stored is not None:
            if stored.content_sha256 == digest and stored.payload == payload:
                return PutOutcome(key=key, stored=False, byte_count=len(payload))
            raise ObjectAlreadyExistsError(
                f"{key.logical_key} already holds different content. This store is "
                "append-only: a second payload under one name is either a collision or a "
                "corruption, and neither is resolved by overwriting."
            )
        self._objects[key.logical_key] = _StoredObject(payload=payload, content_sha256=digest)
        return PutOutcome(key=key, stored=True, byte_count=len(payload))

    def exists(self, *, key: ObjectKey) -> bool:
        """Whether this exact object -- name **and** content address -- is stored."""
        stored = self._objects.get(key.logical_key)
        return stored is not None and stored.content_sha256 == key.content_sha256

    def read(self, key: ObjectKey) -> bytes:
        """The exact bytes stored under ``key``.

        **Not part of :class:`ResearchObjectStore`.** A producer has no reason to
        read the store back; this exists so tests can prove that what went in is
        what came out.

        Raises:
            ObjectContentMismatchError: if nothing is stored under the name, or
                the stored digest is not the one ``key`` claims. Returning the
                bytes anyway would let a forged key -- right path, wrong digest --
                read another object's content, which is the whole reason the
                content address is part of the key.
        """
        stored = self._objects.get(key.logical_key)
        if stored is None:
            raise ObjectContentMismatchError(f"nothing is stored at {key.logical_key}.")
        if stored.content_sha256 != key.content_sha256:
            raise ObjectContentMismatchError(
                f"{key.logical_key} holds {stored.content_sha256}, but the key claims "
                f"{key.content_sha256}. A key names a name and a content address together; "
                "serving the stored bytes for a mismatched address would make the address "
                "decorative."
            )
        return stored.payload

    def snapshot(self) -> Mapping[str, bytes]:
        """Every stored object by logical key. For assertions, not for producers."""
        return {name: stored.payload for name, stored in self._objects.items()}

    def stored_digest(self, logical_key: str) -> str | None:
        """The digest stored under a bare logical name, if any. For assertions only."""
        stored = self._objects.get(logical_key)
        return stored.content_sha256 if stored is not None else None


__all__ = [
    "MAX_LOGICAL_KEY_LENGTH",
    "InMemoryResearchObjectStore",
    "ObjectKey",
    "PutOutcome",
    "ResearchObjectStore",
]
