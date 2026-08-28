"""The research object-store contract: identity, append-only, classification.

Three properties carry the weight, and each has a way of failing quietly:

**Identity is the content.** Same bytes, same address; one byte different, a
different address. A store whose identity drifted from its content would make
every "reproduces bit-identically" claim downstream a coincidence.

**Writes are append-only and idempotent.** Re-publishing the same bytes must be a
no-op that says so; publishing *different* bytes under an occupied key must be a
refusal, not a replacement.

**LICENSED is the only thing this slice can publish.** ADR-0007 classifies by one
question -- can vendor rows be recovered from this artifact? -- under which
uncertain resolves to LICENSED. ``ObjectKey.control`` was withdrawn: a free-text
attestation accepted whenever it was merely non-blank is not auditable clearance,
and there is no permitted-output artifact to publish yet.

**Nothing the caller still owns survives construction.** A frozen dataclass
holding a caller's list would let ``segments[1] = "elsewhere"`` change
``logical_key`` afterwards, and a ``bytearray`` would let the bytes change after
they were hashed and filed under that hash.

No filesystem, no network, no cloud. The store under test is in memory.
"""

from __future__ import annotations

import pytest

from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.contracts.errors import (
    ObjectAlreadyExistsError,
    ObjectClassificationError,
    ObjectContentMismatchError,
    ObjectPayloadTypeError,
    UnsafePathComponentError,
)
from kalpamani.data.contracts.vocabulary import DataClassification
from kalpamani.data.objectstore import (
    MAX_LOGICAL_KEY_LENGTH,
    InMemoryResearchObjectStore,
    ObjectKey,
    ResearchObjectStore,
)

pytestmark = pytest.mark.unit

PAYLOAD = b"synthetic-opaque-payload-alpha"
OTHER_PAYLOAD = b"synthetic-opaque-payload-alphb"  # one byte different, deliberately


def store() -> ResearchObjectStore:
    """A fresh store, typed as the Protocol so conformance is checked by mypy."""
    return InMemoryResearchObjectStore()


# ---------------------------------------------------------------------------
# Content-addressed identity
# ---------------------------------------------------------------------------


def test_the_same_bytes_always_produce_the_same_content_address() -> None:
    first = ObjectKey.licensed("bronze", "provider", "dataset", payload=PAYLOAD)
    second = ObjectKey.licensed("bronze", "provider", "dataset", payload=bytes(PAYLOAD))
    assert first.content_sha256 == second.content_sha256 == sha256_hex(PAYLOAD)
    assert first.logical_key == second.logical_key


def test_one_byte_of_difference_produces_a_different_content_address() -> None:
    """The negative control for the test above, and the more important half."""
    assert len(PAYLOAD) == len(OTHER_PAYLOAD)
    assert PAYLOAD != OTHER_PAYLOAD
    first = ObjectKey.licensed("bronze", "provider", "dataset", payload=PAYLOAD)
    second = ObjectKey.licensed("bronze", "provider", "dataset", payload=OTHER_PAYLOAD)
    assert first.content_sha256 != second.content_sha256


def test_a_logical_key_names_no_bucket_host_or_cloud_account() -> None:
    """A producer names a logical object; a deployment binds it to a location."""
    key = ObjectKey.licensed("bronze", "provider", "dataset", "objects", payload=PAYLOAD)
    assert key.logical_key == "licensed/bronze/provider/dataset/objects"
    for marker in ("://", "s3", "arn:", "amazonaws", "kalpamani-", ".com"):
        assert marker not in key.logical_key


def test_a_key_segment_arriving_from_outside_cannot_navigate() -> None:
    """A provider name is data from outside the system, not a directory choice."""
    with pytest.raises(UnsafePathComponentError):
        ObjectKey.licensed("bronze", "..", "dataset", payload=PAYLOAD)


def test_a_key_needs_at_least_one_segment() -> None:
    with pytest.raises(ObjectClassificationError, match="at least one segment"):
        ObjectKey(
            classification=DataClassification.LICENSED,
            segments=(),
            content_sha256=sha256_hex(PAYLOAD),
        )


@pytest.mark.parametrize(
    "digest",
    ["", "abc", sha256_hex(PAYLOAD).upper(), sha256_hex(PAYLOAD)[:-1], sha256_hex(PAYLOAD) + "a"],
)
def test_a_content_address_must_be_exactly_64_lowercase_hex_characters(digest: str) -> None:
    """Two spellings of one digest would be two identities for one object."""
    with pytest.raises(ObjectContentMismatchError):
        ObjectKey(
            classification=DataClassification.LICENSED,
            segments=("bronze",),
            content_sha256=digest,
        )


def test_an_over_long_logical_key_is_refused() -> None:
    segments = tuple("s" * 100 for _ in range(20))
    with pytest.raises(ObjectClassificationError, match="over the"):
        ObjectKey.licensed(*segments, payload=PAYLOAD)
    assert len("/".join(("licensed", *segments))) > MAX_LOGICAL_KEY_LENGTH


# ---------------------------------------------------------------------------
# Classification -- LICENSED by construction, CONTROL only on an attestation
# ---------------------------------------------------------------------------


def test_the_licensed_constructor_has_no_parameter_that_changes_the_classification() -> None:
    """The structural half of the guarantee: there is nothing to get wrong."""
    key = ObjectKey.licensed("bronze", "provider", payload=PAYLOAD)
    assert key.classification is DataClassification.LICENSED
    assert key.logical_key.startswith("licensed/")


def test_licensed_is_the_only_public_constructor() -> None:
    """``ObjectKey.control`` was withdrawn for this slice, and its absence is the fix."""
    assert not hasattr(ObjectKey, "control")
    constructors = {
        name
        for name, member in vars(ObjectKey).items()
        if isinstance(member, classmethod) and not name.startswith("_")
    }
    assert constructors == {"licensed"}


def test_a_control_object_cannot_be_constructed_at_all() -> None:
    """A free-text attestation was never auditable clearance.

    ``"x"`` would have passed it, nothing recorded *which* decision cleared the
    object, and the artifact would then have survived a vendor deletion on the
    strength of a string nobody could check. With no constructor, the unsafe
    surface is not merely guarded -- it does not exist.
    """
    with pytest.raises(ObjectClassificationError, match="not publishable in this slice"):
        ObjectKey(
            classification=DataClassification.CONTROL,
            segments=("control", "manifest"),
            content_sha256=sha256_hex(PAYLOAD),
        )


def test_no_attestation_string_can_clear_an_object_to_control() -> None:
    """Including the one-character string the old rule would have accepted."""
    for attestation in ("x", "cleared", "not reconstructable", ""):
        with pytest.raises(TypeError):
            ObjectKey(  # type: ignore[call-arg]
                classification=DataClassification.CONTROL,
                segments=("control",),
                content_sha256=sha256_hex(PAYLOAD),
                control_attestation=attestation,
            )


def test_control_remains_in_the_architecture_vocabulary() -> None:
    """Withdrawing the constructor is not withdrawing the concept."""
    assert DataClassification.CONTROL.value == "CONTROL"
    assert set(DataClassification) == {DataClassification.LICENSED, DataClassification.CONTROL}


def test_the_classification_is_part_of_the_identity_not_an_attribute() -> None:
    """The prefix comes from the classification, so it cannot be edited away."""
    key = ObjectKey.licensed("bronze", "x", payload=PAYLOAD)
    assert key.logical_key.split("/")[0] == DataClassification.LICENSED.value.lower()


# ---------------------------------------------------------------------------
# put_if_absent -- append-only and idempotent
# ---------------------------------------------------------------------------


def test_a_first_put_stores_the_exact_bytes() -> None:
    backing = InMemoryResearchObjectStore()
    key = ObjectKey.licensed("bronze", "provider", "dataset", payload=PAYLOAD)
    outcome = backing.put_if_absent(key=key, payload=PAYLOAD)
    assert outcome.stored is True
    assert outcome.byte_count == len(PAYLOAD)
    assert backing.read(key) == PAYLOAD
    assert backing.exists(key=key) is True


def test_re_putting_identical_bytes_is_idempotent_and_says_so() -> None:
    backing = InMemoryResearchObjectStore()
    key = ObjectKey.licensed("bronze", "provider", "dataset", payload=PAYLOAD)
    backing.put_if_absent(key=key, payload=PAYLOAD)
    second = backing.put_if_absent(key=key, payload=PAYLOAD)
    assert second.stored is False
    assert backing.read(key) == PAYLOAD
    assert len(backing.snapshot()) == 1


def test_different_bytes_under_one_key_are_refused_rather_than_replacing() -> None:
    """An object store that silently replaces evidence is not evidence."""
    backing = InMemoryResearchObjectStore()
    key = ObjectKey.licensed("bronze", "provider", "dataset", payload=PAYLOAD)
    backing.put_if_absent(key=key, payload=PAYLOAD)
    with pytest.raises(ObjectAlreadyExistsError, match="append-only"):
        backing.put_if_absent(key=forged_key(key, OTHER_PAYLOAD), payload=OTHER_PAYLOAD)
    assert backing.read(key) == PAYLOAD


# ---------------------------------------------------------------------------
# Deep immutability -- nothing the caller still owns survives construction
# ---------------------------------------------------------------------------


def test_mutating_the_source_segment_list_changes_nothing() -> None:
    """The defect this closes: a frozen dataclass holding a caller's list.

    ``ObjectKey`` was frozen, but its leaves were not. A caller could hand in a
    list, keep the reference, and change ``logical_key`` after the key had been
    validated and used.
    """
    segments = ["bronze", "provider", "dataset"]
    key = ObjectKey(
        classification=DataClassification.LICENSED,
        segments=segments,  # type: ignore[arg-type]
        content_sha256=sha256_hex(PAYLOAD),
    )
    before = key.logical_key
    segments[1] = "elsewhere"
    segments.append("appended")
    assert key.logical_key == before == "licensed/bronze/provider/dataset"


def test_the_retained_segments_are_an_exact_tuple_of_exact_strings() -> None:
    class SneakyTuple(tuple):  # type: ignore[type-arg]
        pass

    class SneakySegment(str):
        def __str__(self) -> str:
            return "elsewhere"

    key = ObjectKey(
        classification=DataClassification.LICENSED,
        segments=SneakyTuple(("bronze", SneakySegment("provider"))),
        content_sha256=sha256_hex(PAYLOAD),
    )
    assert type(key.segments) is tuple
    assert all(type(segment) is str for segment in key.segments)
    # Rebuilt from the data the subclass actually holds, not from what it claims.
    assert key.logical_key == "licensed/bronze/provider"


def test_the_retained_content_address_is_an_exact_string() -> None:
    class SneakyDigest(str):
        def __str__(self) -> str:
            return "0" * 64

    key = ObjectKey(
        classification=DataClassification.LICENSED,
        segments=("bronze",),
        content_sha256=SneakyDigest(sha256_hex(PAYLOAD)),
    )
    assert type(key.content_sha256) is str
    assert key.content_sha256 == sha256_hex(PAYLOAD)


@pytest.mark.parametrize("segment", [None, 7, b"bytes", ["nested"], object()])
def test_a_non_string_segment_is_refused(segment: object) -> None:
    with pytest.raises(ObjectClassificationError, match="must be a string"):
        ObjectKey(
            classification=DataClassification.LICENSED,
            segments=("bronze", segment),  # type: ignore[arg-type]
            content_sha256=sha256_hex(PAYLOAD),
        )


@pytest.mark.parametrize("segments", ["bronze", b"bronze", 7, None])
def test_a_single_value_is_not_a_segment_collection(segments: object) -> None:
    """A bare string is iterable, and iterating it would make one segment per letter."""
    with pytest.raises(ObjectClassificationError, match="iterable of path components"):
        ObjectKey(
            classification=DataClassification.LICENSED,
            segments=segments,  # type: ignore[arg-type]
            content_sha256=sha256_hex(PAYLOAD),
        )


def test_object_key_cannot_be_subclassed() -> None:
    """A subclass could override ``logical_key`` and present an unvalidated identity."""
    with pytest.raises(TypeError, match="may not be subclassed"):

        class Forged(ObjectKey):
            @property
            def logical_key(self) -> str:
                return "licensed/somewhere/else"


def test_the_store_requires_an_exact_object_key() -> None:
    """The boundary half of the same rule: a duck-typed stand-in is refused too."""

    class NotAnObjectKey:
        classification = DataClassification.LICENSED
        segments = ("bronze",)
        content_sha256 = sha256_hex(PAYLOAD)
        logical_key = "licensed/bronze"

    backing = InMemoryResearchObjectStore()
    with pytest.raises(ObjectClassificationError, match="exact ObjectKey"):
        backing.put_if_absent(key=NotAnObjectKey(), payload=PAYLOAD)  # type: ignore[arg-type]


def test_a_put_outcome_key_stays_stable_after_the_source_is_mutated() -> None:
    segments = ["bronze", "provider"]
    key = ObjectKey(
        classification=DataClassification.LICENSED,
        segments=segments,  # type: ignore[arg-type]
        content_sha256=sha256_hex(PAYLOAD),
    )
    backing = InMemoryResearchObjectStore()
    outcome = backing.put_if_absent(key=key, payload=PAYLOAD)
    segments[0] = "elsewhere"
    assert outcome.key.logical_key == "licensed/bronze/provider"
    assert backing.read(outcome.key) == PAYLOAD


# ---------------------------------------------------------------------------
# Payload bytes are exact and immutable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        bytearray(b"synthetic-mutable"),
        memoryview(b"synthetic-view"),
        "synthetic-str",
        None,
        7,
    ],
)
def test_only_exact_bytes_may_be_hashed_into_a_key(payload: object) -> None:
    with pytest.raises(ObjectPayloadTypeError, match="exact bytes"):
        ObjectKey.licensed("bronze", payload=payload)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "payload", [bytearray(b"synthetic-mutable"), memoryview(b"synthetic-view"), "str", None]
)
def test_only_exact_bytes_may_be_stored(payload: object) -> None:
    backing = InMemoryResearchObjectStore()
    key = ObjectKey.licensed("bronze", payload=PAYLOAD)
    with pytest.raises(ObjectPayloadTypeError, match="exact bytes"):
        backing.put_if_absent(key=key, payload=payload)  # type: ignore[arg-type]
    assert backing.snapshot() == {}


def test_a_bytes_subclass_is_refused_rather_than_retained() -> None:
    """Its behaviour is not this module's, and neither is its lifetime."""

    class SneakyBytes(bytes):
        pass

    with pytest.raises(ObjectPayloadTypeError):
        ObjectKey.licensed("bronze", payload=SneakyBytes(PAYLOAD))


def test_a_mutable_buffer_cannot_be_edited_into_stored_content() -> None:
    """The scenario the refusal exists for, run end to end.

    Hash, file under the hash, then mutate what the caller still holds -- and the
    object's content address would have stopped describing its content, silently.
    """
    buffer = bytearray(PAYLOAD)
    backing = InMemoryResearchObjectStore()
    with pytest.raises(ObjectPayloadTypeError):
        ObjectKey.licensed("bronze", payload=buffer)  # type: ignore[arg-type]

    # The supported route: an exact copy the caller no longer shares.
    key = ObjectKey.licensed("bronze", payload=bytes(buffer))
    backing.put_if_absent(key=key, payload=bytes(buffer))
    buffer[0] = 0
    assert backing.read(key) == PAYLOAD
    assert sha256_hex(backing.read(key)) == key.content_sha256


def test_everything_the_store_exposes_is_immutable_bytes() -> None:
    backing = InMemoryResearchObjectStore()
    key = ObjectKey.licensed("bronze", payload=PAYLOAD)
    backing.put_if_absent(key=key, payload=PAYLOAD)
    assert type(backing.read(key)) is bytes
    assert all(type(value) is bytes for value in backing.snapshot().values())


# ---------------------------------------------------------------------------
# The whole key is the identity -- name AND content address
# ---------------------------------------------------------------------------


def forged_key(key: ObjectKey, other: bytes) -> ObjectKey:
    """``key``'s exact path, carrying a different payload's content address."""
    return ObjectKey(
        classification=key.classification,
        segments=key.segments,
        content_sha256=sha256_hex(other),
    )


def test_exists_is_true_only_for_the_digest_the_key_names() -> None:
    """A store keyed on the logical name alone would report ``True`` here."""
    backing = InMemoryResearchObjectStore()
    key = ObjectKey.licensed("bronze", "provider", "dataset", payload=PAYLOAD)
    backing.put_if_absent(key=key, payload=PAYLOAD)
    assert backing.exists(key=key) is True
    assert backing.exists(key=forged_key(key, OTHER_PAYLOAD)) is False


def test_a_forged_key_cannot_read_another_objects_bytes() -> None:
    """Right path, wrong digest. Serving the bytes would make the address decorative."""
    backing = InMemoryResearchObjectStore()
    key = ObjectKey.licensed("bronze", "provider", "dataset", payload=PAYLOAD)
    backing.put_if_absent(key=key, payload=PAYLOAD)
    with pytest.raises(ObjectContentMismatchError, match="but the key claims"):
        backing.read(forged_key(key, OTHER_PAYLOAD))


def test_reading_an_absent_name_refuses_rather_than_raising_a_key_error() -> None:
    backing = InMemoryResearchObjectStore()
    key = ObjectKey.licensed("bronze", "provider", "dataset", payload=PAYLOAD)
    with pytest.raises(ObjectContentMismatchError, match="nothing is stored"):
        backing.read(key)


def test_a_name_reported_absent_is_still_not_free() -> None:
    """The pairing that looks odd and is the honest one.

    ``exists`` answers about the object you named; ``put_if_absent`` answers about
    the name. When a name is occupied by different content, the first is ``False``
    and the second still refuses -- and reporting anything else would either hide
    the occupant or invite an overwrite.
    """
    backing = InMemoryResearchObjectStore()
    key = ObjectKey.licensed("bronze", "provider", "dataset", payload=PAYLOAD)
    backing.put_if_absent(key=key, payload=PAYLOAD)
    forged = forged_key(key, OTHER_PAYLOAD)
    assert backing.exists(key=forged) is False
    with pytest.raises(ObjectAlreadyExistsError):
        backing.put_if_absent(key=forged, payload=OTHER_PAYLOAD)


def test_the_stored_digest_is_recorded_rather_than_recomputed_on_read() -> None:
    """An integrity check that rehashes the current bytes checks them against
    themselves, which is true by construction and therefore worth nothing."""
    backing = InMemoryResearchObjectStore()
    key = ObjectKey.licensed("bronze", "provider", "dataset", payload=PAYLOAD)
    backing.put_if_absent(key=key, payload=PAYLOAD)
    assert backing.stored_digest(key.logical_key) == sha256_hex(PAYLOAD)
    assert backing.stored_digest("licensed/nothing/here") is None


def test_a_payload_that_does_not_hash_to_its_key_is_refused() -> None:
    backing = InMemoryResearchObjectStore()
    key = ObjectKey.licensed("bronze", "provider", "dataset", payload=PAYLOAD)
    with pytest.raises(ObjectContentMismatchError, match="hashes to"):
        backing.put_if_absent(key=key, payload=OTHER_PAYLOAD)
    assert backing.exists(key=key) is False


def test_exists_is_false_before_a_put_and_true_after() -> None:
    backing = InMemoryResearchObjectStore()
    key = ObjectKey.licensed("bronze", "provider", "dataset", payload=PAYLOAD)
    assert backing.exists(key=key) is False
    backing.put_if_absent(key=key, payload=PAYLOAD)
    assert backing.exists(key=key) is True


def test_the_contract_exposes_only_put_if_absent_and_exists() -> None:
    """No listing, no deletion, no versioning. A producer that could list the store
    could enumerate what a vendor sent, and deletion is a separately-roled operation."""
    surface = {name for name in vars(ResearchObjectStore) if not name.startswith("_")}
    assert surface == {"put_if_absent", "exists"}


@pytest.mark.parametrize(
    "value",
    [
        "LICENSED",
        DataClassification.LICENSED,
    ],
)
def test_a_valid_classification_spelling_is_normalised_to_the_exact_member(
    value: object,
) -> None:
    """A bare string compares equal to the member everywhere except at ``.value``,
    which is precisely where the logical key is built."""
    key = ObjectKey(
        classification=value,  # type: ignore[arg-type]
        segments=("bronze",),
        content_sha256=sha256_hex(PAYLOAD),
    )
    assert type(key.classification) is DataClassification
    assert key.logical_key.startswith("licensed/")


class _HostileEquality:
    """Claims to be anything it is compared against, and is not a string."""

    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return hash("LICENSED")

    def __str__(self) -> str:
        return "LICENSED"


class _SneakyClassification(str):
    """A ``str`` subclass whose ``__str__`` lies about the data it holds."""

    def __str__(self) -> str:
        return "LICENSED"


@pytest.mark.parametrize(
    "value",
    [
        "licensed",
        "PUBLIC_PIT",
        "",
        None,
        7,
        _HostileEquality(),
        _SneakyClassification("NOT_A_CLASSIFICATION"),
    ],
)
def test_an_unrecognised_classification_is_refused_rather_than_guessed(value: object) -> None:
    """Including a sibling vocabulary, a hostile equality object and a lying subclass."""
    with pytest.raises(ObjectClassificationError, match="DataClassification"):
        ObjectKey(
            classification=value,  # type: ignore[arg-type]
            segments=("bronze",),
            content_sha256=sha256_hex(PAYLOAD),
        )


def test_a_str_subclass_is_resolved_by_the_data_it_actually_holds() -> None:
    """Not by what ``__str__`` claims -- otherwise a lie would pick the member."""
    key = ObjectKey(
        classification=_SneakyClassification("LICENSED"),  # type: ignore[arg-type]
        segments=("bronze",),
        content_sha256=sha256_hex(PAYLOAD),
    )
    assert type(key.classification) is DataClassification
    assert key.classification is DataClassification.LICENSED


def test_the_in_memory_store_satisfies_the_protocol_at_runtime() -> None:
    """mypy checks the static half; this checks the methods actually exist."""
    backing: ResearchObjectStore = store()
    key = ObjectKey.licensed("bronze", "provider", payload=PAYLOAD)
    assert backing.put_if_absent(key=key, payload=PAYLOAD).stored is True
    assert backing.exists(key=key) is True
