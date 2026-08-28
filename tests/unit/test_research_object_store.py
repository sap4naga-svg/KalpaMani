"""The research object-store contract: identity, append-only, classification.

Three properties carry the weight, and each has a way of failing quietly:

**Identity is the content.** Same bytes, same address; one byte different, a
different address. A store whose identity drifted from its content would make
every "reproduces bit-identically" claim downstream a coincidence.

**Writes are append-only and idempotent.** Re-publishing the same bytes must be a
no-op that says so; publishing *different* bytes under an occupied key must be a
refusal, not a replacement.

**LICENSED is what you get by writing the ordinary thing.** ADR-0007 classifies by
one question -- can vendor rows be recovered from this artifact? -- under which
uncertain resolves to LICENSED. The tests below establish that the CONTROL side
cannot be reached by omission, a wrong keyword or a blank string.

No filesystem, no network, no cloud. The store under test is in memory.
"""

from __future__ import annotations

import pytest

from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.contracts.errors import (
    ObjectAlreadyExistsError,
    ObjectClassificationError,
    ObjectContentMismatchError,
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
    assert key.control_attestation == ""


@pytest.mark.parametrize("attestation", ["", "   ", "\t\n"])
def test_control_is_refused_without_a_written_attestation(attestation: str) -> None:
    """Uncertain resolves to LICENSED, so an unattested object cannot be CONTROL."""
    with pytest.raises(ObjectClassificationError, match="written attestation"):
        ObjectKey.control("control", "manifest", payload=PAYLOAD, attestation=attestation)


def test_control_is_reachable_only_by_stating_why() -> None:
    key = ObjectKey.control(
        "control",
        "manifest",
        payload=PAYLOAD,
        attestation="a manifest of hashes; no vendor row can be reconstructed from it",
    )
    assert key.classification is DataClassification.CONTROL
    assert key.logical_key.startswith("control/")


def test_a_licensed_object_may_not_carry_a_control_attestation() -> None:
    """An attestation on the licensed side would read as evidence of a clearance."""
    with pytest.raises(ObjectClassificationError, match="carries no control attestation"):
        ObjectKey(
            classification=DataClassification.LICENSED,
            segments=("bronze",),
            content_sha256=sha256_hex(PAYLOAD),
            control_attestation="cleared",
        )


def test_the_classification_is_part_of_the_identity_not_an_attribute() -> None:
    """An object cannot move between the two stores without becoming a different one."""
    licensed = ObjectKey.licensed("bronze", "x", payload=PAYLOAD)
    controlled = ObjectKey.control(
        "bronze", "x", payload=PAYLOAD, attestation="hashes only, not reconstructable"
    )
    assert licensed.content_sha256 == controlled.content_sha256
    assert licensed.logical_key != controlled.logical_key


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
        classification=_SneakyClassification("CONTROL"),  # type: ignore[arg-type]
        segments=("control",),
        content_sha256=sha256_hex(PAYLOAD),
        control_attestation="hashes only",
    )
    assert key.classification is DataClassification.CONTROL


def test_the_in_memory_store_satisfies_the_protocol_at_runtime() -> None:
    """mypy checks the static half; this checks the methods actually exist."""
    backing: ResearchObjectStore = store()
    key = ObjectKey.licensed("bronze", "provider", payload=PAYLOAD)
    assert backing.put_if_absent(key=key, payload=PAYLOAD).stored is True
    assert backing.exists(key=key) is True
