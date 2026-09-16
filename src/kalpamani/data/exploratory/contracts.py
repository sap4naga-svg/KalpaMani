"""Closed, versioned contracts identifying exploratory inputs and their provenance (ADR-0051 §3).

Three documents, each with a fixed ``contract_id`` and a closed field set:

* :class:`ExploratoryProvenance` -- *why* a publication's availability is what it is: the
  research-only profile and derivation, the assumed basis, the declared limitations, the
  production publication it was derived from (by digest), and the one thing it may claim
  about production qualification -- ``NONE``.
* :class:`ExploratoryPublication` -- one derived publication: its identity, content digest,
  classification and provenance.
* :class:`ExploratoryInputSet` -- the publications one research run consumes together, which
  must share one provenance profile, derivation and limitation set.

Parsing is total and closed: an unknown key, a missing key, a duplicate key at any depth, a
wrong type, an unknown value, a production value where a research-only one belongs (a
*substitution*), or a contradiction between fields is a closed :class:`ExploratoryDefect`,
never a raw exception and never a default. ``document()`` and ``parse_*`` round-trip exactly.

This is a labelling and admission contract, not a cryptographic one: an owner who rewrites
every private document consistently can make an exploratory publication say what they like.
What the contract guarantees is that nothing *accidental* -- a wrapper, a bridge, a parser
default -- can relabel exploratory evidence as production-qualified.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.exploratory.vocabulary import (
    MANDATORY_LIMITATIONS,
    PRODUCTION_DERIVATION_NAMES,
    PRODUCTION_PROFILE_NAMES,
    AvailabilityBasis,
    ExploratoryDerivation,
    ExploratoryLimitation,
    ExploratoryProfile,
    QualificationClaim,
)

PROVENANCE_CONTRACT_ID: Final = "kalpamani-exploratory-provenance/v1"
PUBLICATION_CONTRACT_ID: Final = "kalpamani-exploratory-publication/v1"
INPUT_SET_CONTRACT_ID: Final = "kalpamani-exploratory-input-set/v1"
SCHEMA_VERSION: Final = 1

#: Every exploratory artefact is derived from licensed rows and stays inside the private
#: boundary. The one classification an exploratory publication may carry.
CLASSIFICATION: Final = "LICENSED_DERIVED"

#: A production build manifest digest, a content digest: 64 lowercase hex.
DIGEST_RE: Final = re.compile(r"[0-9a-f]{64}")
#: A publication identity: the run-identity grammar the production key builders use.
IDENTITY_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
#: The largest document parsed. Provenance documents are small; a large one is not one.
MAX_DOCUMENT_BYTES: Final = 65_536
#: At most this many publications in one input set.
MAX_PUBLICATIONS: Final = 64


class ExploratoryDefect(StrEnum):
    """Why a document or object was refused. Closed."""

    DOCUMENT_MALFORMED = "DOCUMENT_MALFORMED"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    FIELD_SET_MISMATCH = "FIELD_SET_MISMATCH"
    FIELD_MALFORMED = "FIELD_MALFORMED"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    PROFILE_MISSING = "PROFILE_MISSING"
    PROFILE_UNKNOWN = "PROFILE_UNKNOWN"
    PRODUCTION_PROFILE_SUBSTITUTED = "PRODUCTION_PROFILE_SUBSTITUTED"
    DERIVATION_UNKNOWN = "DERIVATION_UNKNOWN"
    PRODUCTION_DERIVATION_SUBSTITUTED = "PRODUCTION_DERIVATION_SUBSTITUTED"
    EVIDENCED_BASIS_CLAIMED = "EVIDENCED_BASIS_CLAIMED"
    QUALIFICATION_CLAIMED = "QUALIFICATION_CLAIMED"
    LIMITATION_MISSING = "LIMITATION_MISSING"
    LIMITATION_UNKNOWN = "LIMITATION_UNKNOWN"
    CLASSIFICATION_MISMATCH = "CLASSIFICATION_MISMATCH"
    PROVENANCE_MIXED = "PROVENANCE_MIXED"
    INPUT_SET_EMPTY = "INPUT_SET_EMPTY"
    INPUT_SET_TOO_LARGE = "INPUT_SET_TOO_LARGE"
    IDENTITY_DUPLICATED = "IDENTITY_DUPLICATED"


class ExploratoryContractError(Exception):
    """One closed defect. Carries no document content."""

    def __init__(self, defect: ExploratoryDefect) -> None:
        if type(defect) is not ExploratoryDefect:
            raise TypeError("defect must be an exact ExploratoryDefect")
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: ExploratoryDefect) -> ExploratoryContractError:
    return ExploratoryContractError(defect)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise _refuse(ExploratoryDefect.DUPLICATE_KEY)
        document[key] = value
    return document


def _exact_str(value: object) -> str:
    if type(value) is not str:
        raise _refuse(ExploratoryDefect.FIELD_MALFORMED)
    return value


def _closed_fields(document: object, fields: frozenset[str]) -> dict[str, Any]:
    if type(document) is not dict:
        raise _refuse(ExploratoryDefect.DOCUMENT_MALFORMED)
    if set(document) != fields:
        raise _refuse(ExploratoryDefect.FIELD_SET_MISMATCH)
    return document


def _contract(document: dict[str, Any], contract_id: str) -> None:
    version = document.get("schema_version")
    if (
        document.get("contract_id") != contract_id
        or type(version) is not int  # bool and float compare equal to 1; neither is a version
        or version != SCHEMA_VERSION
    ):
        raise _refuse(ExploratoryDefect.CONTRACT_MISMATCH)


def _digest(value: object) -> str:
    text = _exact_str(value)
    if DIGEST_RE.fullmatch(text) is None:
        raise _refuse(ExploratoryDefect.FIELD_MALFORMED)
    return text


def _identity(value: object) -> str:
    text = _exact_str(value)
    if IDENTITY_RE.fullmatch(text) is None:
        raise _refuse(ExploratoryDefect.FIELD_MALFORMED)
    return text


def _canonical(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def decode_document(text: str | bytes) -> dict[str, Any]:
    """One JSON object from text, refusing duplicates at any depth and oversize input."""
    try:
        raw = text.encode("utf-8") if isinstance(text, str) else text
    except UnicodeEncodeError:
        # A lone surrogate has no byte form at all; it is not a document.
        raise _refuse(ExploratoryDefect.DOCUMENT_MALFORMED) from None
    if type(raw) is not bytes or len(raw) > MAX_DOCUMENT_BYTES:
        raise _refuse(ExploratoryDefect.DOCUMENT_MALFORMED)
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except ExploratoryContractError:
        raise
    except (ValueError, RecursionError):
        raise _refuse(ExploratoryDefect.DOCUMENT_MALFORMED) from None
    if type(document) is not dict:
        raise _refuse(ExploratoryDefect.DOCUMENT_MALFORMED)
    return document


def parse_limitations(raw: object) -> frozenset[ExploratoryLimitation]:
    """A list of distinct limitation names, every item typed before any set is built."""
    if type(raw) is not list:
        raise _refuse(ExploratoryDefect.FIELD_MALFORMED)
    names = [_exact_str(item) for item in raw]
    if len(set(names)) != len(names):
        raise _refuse(ExploratoryDefect.FIELD_MALFORMED)
    limitations: set[ExploratoryLimitation] = set()
    for name in names:
        try:
            limitations.add(ExploratoryLimitation(name))
        except ValueError:
            raise _refuse(ExploratoryDefect.LIMITATION_UNKNOWN) from None
    return frozenset(limitations)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

_PROVENANCE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "contract_id",
        "schema_version",
        "profile",
        "derivation",
        "availability_basis",
        "production_qualification",
        "limitations",
        "source_manifest_digest",
        "source_manifest_contract",
    }
)

#: The production build manifest an exploratory publication may be derived from.
SOURCE_MANIFEST_CONTRACT: Final = "kalpamani-production-build-manifest/v1"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExploratoryProvenance:
    """Why a publication's availability is what it is. Research-only by construction."""

    profile: ExploratoryProfile
    derivation: ExploratoryDerivation
    limitations: frozenset[ExploratoryLimitation]
    source_manifest_digest: str
    availability_basis: AvailabilityBasis = AvailabilityBasis.ASSUMED_HISTORICAL
    production_qualification: QualificationClaim = QualificationClaim.NONE

    def __post_init__(self) -> None:
        if type(self.profile) is not ExploratoryProfile:
            raise _refuse(ExploratoryDefect.PROFILE_UNKNOWN)
        if type(self.derivation) is not ExploratoryDerivation:
            raise _refuse(ExploratoryDefect.DERIVATION_UNKNOWN)
        if self.availability_basis is not AvailabilityBasis.ASSUMED_HISTORICAL:
            raise _refuse(ExploratoryDefect.EVIDENCED_BASIS_CLAIMED)
        if self.production_qualification is not QualificationClaim.NONE:
            raise _refuse(ExploratoryDefect.QUALIFICATION_CLAIMED)
        if type(self.limitations) is not frozenset or any(
            type(item) is not ExploratoryLimitation for item in self.limitations
        ):
            raise _refuse(ExploratoryDefect.LIMITATION_UNKNOWN)
        if not MANDATORY_LIMITATIONS <= self.limitations:
            raise _refuse(ExploratoryDefect.LIMITATION_MISSING)
        _digest(self.source_manifest_digest)

    def document(self) -> dict[str, Any]:
        """The closed document. Round-trips through :func:`parse_provenance`."""
        return {
            "contract_id": PROVENANCE_CONTRACT_ID,
            "schema_version": SCHEMA_VERSION,
            "profile": self.profile.value,
            "derivation": self.derivation.value,
            "availability_basis": self.availability_basis.value,
            "production_qualification": self.production_qualification.value,
            "limitations": sorted(item.value for item in self.limitations),
            "source_manifest_digest": self.source_manifest_digest,
            "source_manifest_contract": SOURCE_MANIFEST_CONTRACT,
        }

    @property
    def digest(self) -> str:
        """SHA-256 over the canonical document."""
        return hashlib.sha256(_canonical(self.document())).hexdigest()


def _profile(value: object) -> ExploratoryProfile:
    if value is None:
        raise _refuse(ExploratoryDefect.PROFILE_MISSING)
    text = _exact_str(value)
    if text in PRODUCTION_PROFILE_NAMES:
        raise _refuse(ExploratoryDefect.PRODUCTION_PROFILE_SUBSTITUTED)
    try:
        return ExploratoryProfile(text)
    except ValueError:
        raise _refuse(ExploratoryDefect.PROFILE_UNKNOWN) from None


def _derivation(value: object) -> ExploratoryDerivation:
    text = _exact_str(value)
    if text in PRODUCTION_DERIVATION_NAMES:
        raise _refuse(ExploratoryDefect.PRODUCTION_DERIVATION_SUBSTITUTED)
    try:
        return ExploratoryDerivation(text)
    except ValueError:
        raise _refuse(ExploratoryDefect.DERIVATION_UNKNOWN) from None


def parse_provenance(document: object) -> ExploratoryProvenance:
    """The provenance a document describes, or one closed refusal."""
    fields = _closed_fields(document, _PROVENANCE_FIELDS)
    _contract(fields, PROVENANCE_CONTRACT_ID)
    profile = _profile(fields["profile"])
    derivation = _derivation(fields["derivation"])
    basis_text = _exact_str(fields["availability_basis"])
    if basis_text == AvailabilityBasis.EVIDENCED.value:
        raise _refuse(ExploratoryDefect.EVIDENCED_BASIS_CLAIMED)
    if basis_text != AvailabilityBasis.ASSUMED_HISTORICAL.value:
        raise _refuse(ExploratoryDefect.FIELD_MALFORMED)
    if _exact_str(fields["production_qualification"]) != QualificationClaim.NONE.value:
        raise _refuse(ExploratoryDefect.QUALIFICATION_CLAIMED)
    limitations = parse_limitations(fields["limitations"])
    if _exact_str(fields["source_manifest_contract"]) != SOURCE_MANIFEST_CONTRACT:
        raise _refuse(ExploratoryDefect.CONTRACT_MISMATCH)
    return ExploratoryProvenance(
        profile=profile,
        derivation=derivation,
        limitations=limitations,
        source_manifest_digest=_digest(fields["source_manifest_digest"]),
    )


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------

_PUBLICATION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "contract_id",
        "schema_version",
        "publication_id",
        "content_digest",
        "classification",
        "provenance",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExploratoryPublication:
    """One exploratory publication: identity, content, classification, provenance."""

    publication_id: str
    content_digest: str
    provenance: ExploratoryProvenance

    def __post_init__(self) -> None:
        _identity(self.publication_id)
        _digest(self.content_digest)
        if self.provenance is None:
            raise _refuse(ExploratoryDefect.PROFILE_MISSING)
        if type(self.provenance) is not ExploratoryProvenance:
            raise _refuse(ExploratoryDefect.FIELD_MALFORMED)

    @property
    def classification(self) -> str:
        """Always ``LICENSED_DERIVED``: derived from licensed rows, inside the boundary."""
        return CLASSIFICATION

    def document(self) -> dict[str, Any]:
        """The closed document. Round-trips through :func:`parse_publication`."""
        return {
            "contract_id": PUBLICATION_CONTRACT_ID,
            "schema_version": SCHEMA_VERSION,
            "publication_id": self.publication_id,
            "content_digest": self.content_digest,
            "classification": CLASSIFICATION,
            "provenance": self.provenance.document(),
        }

    @property
    def digest(self) -> str:
        """SHA-256 over the canonical document."""
        return hashlib.sha256(_canonical(self.document())).hexdigest()


def parse_publication(document: object) -> ExploratoryPublication:
    """The publication a document describes, or one closed refusal."""
    fields = _closed_fields(document, _PUBLICATION_FIELDS)
    _contract(fields, PUBLICATION_CONTRACT_ID)
    if _exact_str(fields["classification"]) != CLASSIFICATION:
        raise _refuse(ExploratoryDefect.CLASSIFICATION_MISMATCH)
    if fields["provenance"] is None:
        raise _refuse(ExploratoryDefect.PROFILE_MISSING)
    return ExploratoryPublication(
        publication_id=_identity(fields["publication_id"]),
        content_digest=_digest(fields["content_digest"]),
        provenance=parse_provenance(fields["provenance"]),
    )


# ---------------------------------------------------------------------------
# Input set
# ---------------------------------------------------------------------------

_INPUT_SET_FIELDS: Final[frozenset[str]] = frozenset(
    {"contract_id", "schema_version", "publications"}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExploratoryInputSet:
    """The publications one research run consumes together: one provenance, not a mixture."""

    publications: tuple[ExploratoryPublication, ...]

    def __post_init__(self) -> None:
        if type(self.publications) is not tuple or any(
            type(item) is not ExploratoryPublication for item in self.publications
        ):
            raise _refuse(ExploratoryDefect.FIELD_MALFORMED)
        if not self.publications:
            raise _refuse(ExploratoryDefect.INPUT_SET_EMPTY)
        if len(self.publications) > MAX_PUBLICATIONS:
            raise _refuse(ExploratoryDefect.INPUT_SET_TOO_LARGE)
        identities = [item.publication_id for item in self.publications]
        if len(set(identities)) != len(identities):
            raise _refuse(ExploratoryDefect.IDENTITY_DUPLICATED)
        first = self.publications[0].provenance
        for item in self.publications[1:]:
            other = item.provenance
            if (
                other.profile is not first.profile
                or other.derivation is not first.derivation
                or other.limitations != first.limitations
            ):
                raise _refuse(ExploratoryDefect.PROVENANCE_MIXED)

    @property
    def profile(self) -> ExploratoryProfile:
        """The one profile every publication in the set carries."""
        return self.publications[0].provenance.profile

    @property
    def derivation(self) -> ExploratoryDerivation:
        """The one derivation every publication in the set carries."""
        return self.publications[0].provenance.derivation

    @property
    def limitations(self) -> frozenset[ExploratoryLimitation]:
        """The one limitation set every publication in the set carries."""
        return self.publications[0].provenance.limitations

    def document(self) -> dict[str, Any]:
        """The closed document. Round-trips through :func:`parse_input_set`."""
        return {
            "contract_id": INPUT_SET_CONTRACT_ID,
            "schema_version": SCHEMA_VERSION,
            "publications": [item.document() for item in self.publications],
        }

    @property
    def digest(self) -> str:
        """SHA-256 over the canonical document."""
        return hashlib.sha256(_canonical(self.document())).hexdigest()


def parse_input_set(document: object) -> ExploratoryInputSet:
    """The input set a document describes, or one closed refusal."""
    fields = _closed_fields(document, _INPUT_SET_FIELDS)
    _contract(fields, INPUT_SET_CONTRACT_ID)
    raw = fields["publications"]
    if type(raw) is not list:
        raise _refuse(ExploratoryDefect.FIELD_MALFORMED)
    return ExploratoryInputSet(publications=tuple(parse_publication(item) for item in raw))


__all__ = [
    "CLASSIFICATION",
    "INPUT_SET_CONTRACT_ID",
    "MAX_DOCUMENT_BYTES",
    "MAX_PUBLICATIONS",
    "PROVENANCE_CONTRACT_ID",
    "PUBLICATION_CONTRACT_ID",
    "SCHEMA_VERSION",
    "SOURCE_MANIFEST_CONTRACT",
    "ExploratoryContractError",
    "ExploratoryDefect",
    "ExploratoryInputSet",
    "ExploratoryProvenance",
    "ExploratoryPublication",
    "decode_document",
    "parse_input_set",
    "parse_limitations",
    "parse_provenance",
    "parse_publication",
]
