"""The disjoint production Bronze key builders (ADR-0037, amending ADR-0036).

ADR-0037 traced the merged key layouts and found that ADR-0036's original
production prefixes overlapped the general Bronze bridge's, so a production grant
would have reached qualification objects. **Production Bronze objects therefore
live under namespaces no earlier package writes**, and the builders here are the
only spelling of them:

```text
payloads   licensed/bronze/sharadar/<dataset>/production/objects/sha256/<digest>
records    licensed/bronze/sharadar/<dataset>/production/acquisitions/<digest>/<run-id>.<NN>.json
locator    licensed/bronze/sharadar/_indexes/<run-id>.json
claims     licensed/bronze/_production_claims/<digest>/<run-id>.<NN>.json
```

**The record and claim names bind the request ordinal ``<NN>``** as well as the
digest and the run identity. Two requests of one run may legitimately return
byte-identical payloads -- a header-only final page, an unchanged cross-section --
and the payload namespace is content-addressed on purpose (ADR-0035 §3.1: identical
bytes are an idempotent no-op on the payload). Without the ordinal, the second
request's claim and record would land on the first request's names and either
collide or, worse, be mistaken for it: distinct request provenance would collapse
into one object. With it, every request has its own claim and its own record
whatever its bytes, and a reused run identity meets an occupied claim name on its
very first write.

**The general Bronze bridge and the qualification builders are unchanged.**
``publication.bronze_payload_key``, ``bronze_acquisition_key`` and
``acquisition_claim_key`` keep their layouts; ``qualification_payload_key`` keeps
its own; none of them can spell a production key, and none of these can spell
theirs -- a test builds all of them on the same synthetic inputs and proves the
four namespaces pairwise disjoint.

The record key's inner shape -- ``<payload-digest>/<run-id>.<NN>.json`` -- is the
general Bronze record shape carried under the ``production/`` segment, which is
the one ADR-0037 leaves as ``<...>``, with the ordinal appended for the reason
above; the locator's prefix-allowlist clause binds the ``<run-id>`` and the ``<NN>``
of every record key to the locator's own run identity and the entry's own ordinal.
"""

from __future__ import annotations

import re
from typing import Final

from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.contracts.vocabulary import DataClassification
from kalpamani.data.ingest.publication import BRONZE_NAMESPACE
from kalpamani.data.ingest.sharadar.datasets import PROVIDER, SharadarDataset
from kalpamani.data.objectstore import ObjectKey

#: The path segment that makes a production namespace disjoint from the general
#: bridge's, and the two reserved namespaces production alone occupies.
PRODUCTION_SEGMENT: Final = "production"
PRODUCTION_CLAIM_NAMESPACE: Final = "_production_claims"
INDEX_NAMESPACE: Final = "_indexes"

#: Fixed sub-segments, spelled as the general bridge spells them.
OBJECTS_SEGMENT: Final = "objects"
DIGEST_SEGMENT: Final = "sha256"
ACQUISITIONS_SEGMENT: Final = "acquisitions"
_JSON_SUFFIX: Final = ".json"

#: A production run identity: the general bridge's identifier grammar.
RUN_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: A SHA-256 digest, lowercase hex.
_DIGEST: Final = re.compile(r"^[0-9a-f]{64}$")

#: Request ordinals are zero-padded to two digits: the per-run ceiling is 96, so
#: ``00``--``95`` covers every slice and lexical order equals numeric order.
ORDINAL_WIDTH: Final = 2
MAX_ORDINAL: Final = 99

#: The datasets a production key may name: the provider's closed vocabulary.
PRODUCTION_DATASETS: Final[frozenset[str]] = frozenset(member.value for member in SharadarDataset)


class ProductionKeyError(ValueError):
    """A production key could not be built. **Carries no value.**

    The path grammar's own refusal quotes the offending component; this one names
    nothing, so a run identity, a dataset or a digest cannot reach a log through it.
    """

    __slots__ = ()

    def __init__(self) -> None:
        """Carry the fixed sentence."""
        super().__init__("a production key could not be built from these components")


def _dataset(dataset: object) -> str:
    if type(dataset) is not str or dataset not in PRODUCTION_DATASETS:
        raise ProductionKeyError() from None
    return dataset


def _run_id(run_id: object) -> str:
    if type(run_id) is not str or not RUN_ID_RE.match(run_id):
        raise ProductionKeyError() from None
    return run_id


def _digest(digest: object) -> str:
    if type(digest) is not str or not _DIGEST.match(digest):
        raise ProductionKeyError() from None
    return digest


def request_ordinal_segment(ordinal: object) -> str:
    """The zero-padded ordinal segment. ``bool`` is refused with everything else."""
    if type(ordinal) is not int or not 0 <= ordinal <= MAX_ORDINAL:
        raise ProductionKeyError() from None
    return f"{ordinal:0{ORDINAL_WIDTH}d}"


def _key(segments: tuple[str, ...], content_sha256: str) -> ObjectKey:
    try:
        return ObjectKey(
            classification=DataClassification.LICENSED,
            segments=segments,
            content_sha256=content_sha256,
        )
    except Exception:
        raise ProductionKeyError() from None


def production_payload_key(*, dataset: str, payload: bytes) -> ObjectKey:
    """The content-addressed production payload key. Always LICENSED.

    Raises:
        ProductionKeyError: for a dataset outside the vocabulary or a payload that
            is not exact ``bytes``.
    """
    if type(payload) is not bytes:
        raise ProductionKeyError() from None
    digest = sha256_hex(payload)
    return production_payload_key_for_digest(dataset=dataset, content_sha256=digest)


def production_payload_key_for_digest(*, dataset: str, content_sha256: str) -> ObjectKey:
    """The production payload key a recorded digest names. **No bytes are needed.**

    The locator validator rebuilds every payload key through this function and
    compares the result exactly to the key the locator recorded, so a locator
    cannot name a payload outside the production namespace whatever string it
    carries.
    """
    return _key(
        (
            BRONZE_NAMESPACE,
            PROVIDER,
            _dataset(dataset),
            PRODUCTION_SEGMENT,
            OBJECTS_SEGMENT,
            DIGEST_SEGMENT,
            _digest(content_sha256),
        ),
        content_sha256,
    )


def production_acquisition_key(
    *, dataset: str, payload_digest: str, run_id: str, ordinal: int, record: bytes
) -> ObjectKey:
    """The production acquisition-record key, named by ``(digest, run id, ordinal)``."""
    if type(record) is not bytes:
        raise ProductionKeyError() from None
    return production_acquisition_key_for_digest(
        dataset=dataset,
        payload_digest=payload_digest,
        run_id=run_id,
        ordinal=ordinal,
        content_sha256=sha256_hex(record),
    )


def production_acquisition_key_for_digest(
    *, dataset: str, payload_digest: str, run_id: str, ordinal: int, content_sha256: str
) -> ObjectKey:
    """The production record key a recorded digest names. **No bytes are needed.**"""
    return _key(
        (
            BRONZE_NAMESPACE,
            PROVIDER,
            _dataset(dataset),
            PRODUCTION_SEGMENT,
            ACQUISITIONS_SEGMENT,
            _digest(payload_digest),
            f"{_run_id(run_id)}.{request_ordinal_segment(ordinal)}{_JSON_SUFFIX}",
        ),
        _digest(content_sha256),
    )


def production_claim_key(
    *, payload_digest: str, run_id: str, ordinal: int, claim: bytes
) -> ObjectKey:
    """The production acquisition-identity claim key, under ``_production_claims``.

    Global across datasets exactly as the general claim is global across providers:
    the claim binds ``(digest, run id, ordinal)`` and nothing about where the
    payload lives.
    """
    if type(claim) is not bytes:
        raise ProductionKeyError() from None
    return _key(
        (
            BRONZE_NAMESPACE,
            PRODUCTION_CLAIM_NAMESPACE,
            _digest(payload_digest),
            f"{_run_id(run_id)}.{request_ordinal_segment(ordinal)}{_JSON_SUFFIX}",
        ),
        sha256_hex(claim),
    )


def run_locator_key_segments(run_id: str) -> tuple[str, ...]:
    """The run locator's segments: ``bronze/sharadar/_indexes/<run-id>.json``.

    Derived from the run identity alone -- **no listing is involved** -- which is
    the one asymmetry the exact-read discipline rests on (ADR-0036 §2.4).
    """
    return (BRONZE_NAMESPACE, PROVIDER, INDEX_NAMESPACE, f"{_run_id(run_id)}{_JSON_SUFFIX}")


def run_locator_logical_key(run_id: str) -> str:
    """The locator's logical key, ``licensed/bronze/sharadar/_indexes/<run-id>.json``."""
    return "/".join((DataClassification.LICENSED.value.lower(), *run_locator_key_segments(run_id)))


def run_locator_key(*, run_id: str, payload: bytes) -> ObjectKey:
    """The LICENSED key one run locator payload is published under."""
    if type(payload) is not bytes:
        raise ProductionKeyError() from None
    return _key(run_locator_key_segments(run_id), sha256_hex(payload))


__all__ = [
    "ACQUISITIONS_SEGMENT",
    "DIGEST_SEGMENT",
    "INDEX_NAMESPACE",
    "MAX_ORDINAL",
    "OBJECTS_SEGMENT",
    "ORDINAL_WIDTH",
    "PRODUCTION_CLAIM_NAMESPACE",
    "PRODUCTION_DATASETS",
    "PRODUCTION_SEGMENT",
    "RUN_ID_RE",
    "ProductionKeyError",
    "production_acquisition_key",
    "production_acquisition_key_for_digest",
    "production_claim_key",
    "production_payload_key",
    "production_payload_key_for_digest",
    "request_ordinal_segment",
    "run_locator_key",
    "run_locator_key_segments",
    "run_locator_logical_key",
]
