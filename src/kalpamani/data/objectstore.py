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

**This slice publishes LICENSED objects only, and there is no constructor for
anything else.** :meth:`ObjectKey.licensed` takes no classification parameter, so
provider-derived material cannot be routed elsewhere by omission, by a wrong
keyword or by a copied line -- and ``CONTROL`` is refused outright at
construction.

An earlier revision offered ``ObjectKey.control`` gated on a free-text
attestation, accepted whenever it was merely non-blank and never durably bound to
the object it cleared. That is not auditable clearance: ``"x"`` would have passed,
nothing recorded *which* decision cleared the object, and the artifact would then
have survived a vendor deletion on the strength of a string nobody could check.
Withdrawing the constructor is the honest fix for this slice, because there is no
permitted-output artifact to publish yet and therefore nothing the surface is
needed for. :class:`~kalpamani.data.contracts.vocabulary.DataClassification`
keeps ``CONTROL`` as architecture; adding a *structured* attestation -- a closed
reason code, a governing decision reference, a version, a deterministic identity,
and durable binding to the object -- is a later, separately reviewed decision.

The rule this encodes is ADR-0007's classification question -- *can vendor rows be
recovered from this artifact?* -- under which **uncertain resolves to LICENSED**.
With no CONTROL constructor, uncertain is the only answer expressible.

**Nothing a caller still owns survives construction.** ``segments`` is copied into
a fresh plain :class:`tuple` of exact plain :class:`str`, and every payload must
be exact plain :class:`bytes`. A frozen dataclass holding a caller's ``list``
would let ``segments[1] = "elsewhere"`` change ``logical_key`` after the fact, and
a ``bytearray`` would let the bytes change after they were hashed. Subclassing is
refused, so ``logical_key`` cannot be overridden either.

**Puts are append-only and idempotent.** :meth:`ResearchObjectStore.put_if_absent`
writes only when nothing is stored under the key. Re-putting identical bytes
reports ``stored=False`` and changes nothing; putting *different* bytes under an
existing key is refused rather than resolved, because an object store that
silently replaces evidence is not evidence.

**Nothing here opens a socket, reads a file or names a cloud.** The only
implementation in this module is :class:`InMemoryResearchObjectStore`, which is
for tests and local development. The licensed cloud backend lives behind the same
protocol in :mod:`kalpamani.data.storage.s3` (ADR-0011), and this module does not
import it: the seam only means something if the contract stays ignorant of the
backends.

**Admission is decided here, once, for every backend.** :func:`require_exact_key`,
:func:`require_publishable` and :func:`physical_key` are shared rather than
reimplemented per store. Two implementations of *what may be published* would
eventually disagree, and the disagreement would surface as a divergence between
what a test proved and what a bucket holds.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.contracts.errors import (
    ObjectAlreadyExistsError,
    ObjectClassificationError,
    ObjectContentMismatchError,
    ObjectPayloadTypeError,
)
from kalpamani.data.contracts.paths import path_segment
from kalpamani.data.contracts.vocabulary import DataClassification, closed_member

#: A content address is exactly 64 lowercase hex characters. Checked rather than
#: assumed: a key carrying a truncated or upper-cased digest would still be a
#: usable path component, and two spellings of one digest are two identities.
_CONTENT_ADDRESS: Final = re.compile(r"^[0-9a-f]{64}$")

#: Longest logical key this contract will mint. Not a security boundary -- a
#: legibility one, and a guard against a key no object store will accept.
MAX_LOGICAL_KEY_LENGTH: Final = 900


def exact_str(value: object) -> str | None:
    """``value`` as a plain :class:`str` holding its real character data, or ``None``.

    A ``str`` subclass is rebuilt from the data it actually holds, obtained with
    ``str.__str__`` so an overridden ``__str__`` cannot substitute something else.
    The result is a genuine ``str``, so nothing the caller wrote -- an overridden
    ``__eq__``, ``__hash__`` or ``__str__`` -- travels into the key. Anything that
    is not a string yields ``None``, and so does anything that merely claims to be
    one: ``isinstance`` can be satisfied by a spoofed ``__class__``, and the
    descriptor then raises rather than returning.
    """
    if type(value) is str:
        return value
    if not isinstance(value, str):
        return None
    try:
        return str(str.__str__(value))
    except Exception:
        return None


def immutable_payload(payload: object) -> bytes:
    """``payload`` if it is exact plain :class:`bytes`, else a refusal.

    **Fail closed rather than normalise.** A ``bytearray`` or a ``memoryview``
    could be mutated by whoever still holds it after this store hashed it and
    filed it under that hash -- so the object's content address would stop
    describing its content, silently, at a time of the caller's choosing. Copying
    would fix the storage but hide the caller's mistake; refusing surfaces it.
    A ``bytes`` subclass is refused for the same reason a ``str`` subclass is:
    its behaviour is not this module's.

    Raises:
        ObjectPayloadTypeError: for anything that is not exactly ``bytes``.
    """
    if type(payload) is not bytes:
        raise ObjectPayloadTypeError(
            f"payload must be exact bytes, not {type(payload).__name__}. A mutable buffer can "
            "be changed after it has been hashed and filed under that hash, which would leave "
            "an object whose content address no longer describes its content."
        )
    return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class ObjectKey:
    """The logical name of one immutable object, and its content address.

    ``segments`` are the path below the classification prefix. Every one of them
    passes :func:`~kalpamani.data.contracts.paths.path_segment`, so a provider
    name, a dataset name or a run identifier arriving from outside the system
    cannot choose where we write.

    **Deeply frozen.** ``segments`` is copied into a fresh plain ``tuple`` of
    exact plain ``str``, so mutating whatever the caller passed -- a list, a
    tuple subclass, a string subclass -- changes nothing here afterwards.
    Subclassing is refused, so ``logical_key`` cannot be overridden.

    Use :meth:`licensed`. It is the only constructor, and the only classification
    this slice publishes.
    """

    classification: DataClassification
    segments: tuple[str, ...]
    content_sha256: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing.

        A subclass could override ``logical_key`` or ``content_sha256`` and hand
        the store a key whose identity is not the one it validated. The store also
        requires an exact ``ObjectKey``; this is the half that makes the subclass
        impossible to write in the first place.
        """
        raise TypeError(
            "ObjectKey may not be subclassed. A subclass could override logical_key or "
            "content_sha256 and present the store with an identity other than the one that "
            "was checked."
        )

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
        if classification is not DataClassification.LICENSED:
            raise ObjectClassificationError(
                f"{classification.value} objects are not publishable in this slice. There is no "
                "permitted-output artifact to publish yet, and clearing one to a store that "
                "survives a vendor deletion needs a structured, durably-bound attestation "
                "rather than a string. That is a later, separately reviewed decision."
            )
        object.__setattr__(self, "classification", classification)

        # Read through `object` deliberately: the annotation says tuple[str, ...],
        # and the whole point of this block is the caller who ignored it.
        supplied: object = self.segments
        if isinstance(supplied, str | bytes) or not isinstance(supplied, Iterable):
            raise ObjectClassificationError(
                "segments must be an iterable of path components, not a single value."
            )
        segments: list[str] = []
        for segment in supplied:
            exact = exact_str(segment)
            if exact is None:
                raise ObjectClassificationError(
                    f"an object key segment must be a string, not {type(segment).__name__}."
                )
            segments.append(path_segment(exact, kind="object key segment"))
        if not segments:
            raise ObjectClassificationError(
                "An object key needs at least one segment; a bare classification prefix "
                "names a whole store rather than an object in it."
            )
        # A fresh plain tuple of plain strings. Whatever the caller still holds is
        # now unrelated to this key.
        object.__setattr__(self, "segments", tuple(segments))

        digest = exact_str(self.content_sha256)
        if digest is None or not _CONTENT_ADDRESS.match(digest):
            raise ObjectContentMismatchError(
                f"content_sha256={self.content_sha256!r} is not 64 lowercase hex characters. "
                "A content address that two spellings can share is not an address."
            )
        object.__setattr__(self, "content_sha256", digest)

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
        """Name a LICENSED object. **The only constructor, and the only classification.**

        Provider-derived material, and anything that could reconstruct it, takes
        this route. The absence of a classification argument is the point:
        licensed is what you get by writing the ordinary thing, and in this slice
        it is the only thing you can write.
        """
        return cls(
            classification=DataClassification.LICENSED,
            segments=tuple(segments),
            content_sha256=sha256_hex(immutable_payload(payload)),
        )


def require_exact_key(key: ObjectKey) -> ObjectKey:
    """``key`` if it is an exact, publishable :class:`ObjectKey`, else a refusal.

    **The admission rule every backend applies, in one place.** Extracted so the
    in-memory store and the S3 store cannot drift apart on what they accept --
    two stores disagreeing about which keys are valid is a difference that only
    shows up in production.

    Raises:
        ObjectClassificationError: if ``key`` is not an exact ``ObjectKey``, or
            names a classification this slice cannot publish. Subclassing is
            refused at class creation; this is the boundary half of the same
            rule, so a duck-typed stand-in cannot present an identity that was
            never validated.
    """
    if type(key) is not ObjectKey:
        raise ObjectClassificationError(
            f"key must be an exact ObjectKey, not {type(key).__name__}. Subclassing is "
            "refused at class creation; this is the boundary half of the same rule, so a "
            "duck-typed stand-in cannot present an identity that was never validated."
        )
    if key.classification is not DataClassification.LICENSED:
        raise ObjectClassificationError(
            f"{key.classification.value} objects are not publishable in this slice."
        )
    return key


def require_publishable(key: ObjectKey, payload: bytes) -> bytes:
    """The exact bytes ``key`` names, or a refusal. Applied by every backend.

    Raises:
        ObjectClassificationError: if ``key`` is not an exact, publishable key.
        ObjectPayloadTypeError: if ``payload`` is not exact, immutable ``bytes``.
        ObjectContentMismatchError: if ``payload`` does not hash to the content
            address ``key`` claims.
    """
    require_exact_key(key)
    exact = immutable_payload(payload)
    digest = sha256_hex(exact)
    if digest != key.content_sha256:
        raise ObjectContentMismatchError(
            f"payload hashes to {digest}, but {key.logical_key} claims "
            f"{key.content_sha256}. A content address the content does not satisfy would "
            "make every identity in this store a coincidence."
        )
    return exact


def physical_key(key: ObjectKey) -> str:
    """The location a backend stores ``key`` at, below its classification's store.

    **Identity and location are different things, and this is the seam.**
    :attr:`ObjectKey.logical_key` is the deployment-independent identity and
    keeps its ``licensed/`` prefix; the classification *selects the store*, so
    repeating it inside that store would name the object
    ``<licensed-bucket>/licensed/...`` -- the classification stated twice, once
    as a routing decision and once as a directory.

    So a logical ``licensed/bronze/<provider>/<dataset>/...`` is stored at
    ``bronze/<provider>/<dataset>/...`` inside the licensed store. Every segment
    has already passed :func:`~kalpamani.data.contracts.paths.path_segment`, so
    the join introduces nothing a caller chose.
    """
    require_exact_key(key)
    return "/".join(key.segments)


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
            ObjectPayloadTypeError: if ``payload`` is not exact, immutable
                ``bytes``.
            ObjectClassificationError: if ``key`` is not an exact
                :class:`ObjectKey`.
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
        payload = require_publishable(key, payload)
        digest = key.content_sha256
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
        require_exact_key(key)
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
    "exact_str",
    "immutable_payload",
    "physical_key",
    "require_exact_key",
    "require_publishable",
]
