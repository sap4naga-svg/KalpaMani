"""Correction 1 of the exploratory boundaries (PR #111 review): each regression reproduced on the
submitted head 56556d9e before its correction, beside a valid control that must keep passing.

The defects: a raw exception could escape ``admit`` (a consumer whose ``data`` attribute raises)
and the constructors / parsers (a non-string identifier or digest, an unhashable limitation item,
a lone-surrogate string); ``schema_version`` accepted ``true`` and ``1.0`` for ``1``; a consumer
carrying a production profile *by name* was refused under the wrong code; a research
specification could be constructed without acknowledging the mandatory limitations and could
therefore never admit anything while looking valid. Every refusal code stays closed; the
exact-type opt-in and the production isolation are unchanged.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

import pytest

from kalpamani.data.contracts.vocabulary import InformationSetProfile
from kalpamani.data.exploratory.admission import (
    AdmissionOutcome,
    ResearchSpecification,
    admit,
    parse_research_specification,
)
from kalpamani.data.exploratory.contracts import (
    ExploratoryContractError,
    ExploratoryDefect,
    ExploratoryInputSet,
    ExploratoryProvenance,
    ExploratoryPublication,
    decode_document,
    parse_input_set,
    parse_provenance,
    parse_publication,
)
from kalpamani.data.exploratory.vocabulary import (
    MANDATORY_LIMITATIONS,
    ExploratoryDerivation,
    ExploratoryLimitation,
    ExploratoryProfile,
)

DIGEST: Final = hashlib.sha256(b"synthetic").hexdigest()
ALL: Final = frozenset(ExploratoryLimitation)


def provenance(**overrides: Any) -> ExploratoryProvenance:
    fields: dict[str, Any] = {
        "profile": ExploratoryProfile.EXPLORATORY_HINDSIGHT,
        "derivation": ExploratoryDerivation.AS_DATED,
        "limitations": ALL,
        "source_manifest_digest": DIGEST,
    }
    fields.update(overrides)
    return ExploratoryProvenance(**fields)


def publication(**overrides: Any) -> ExploratoryPublication:
    fields: dict[str, Any] = {
        "publication_id": "synthetic-pub-01",
        "content_digest": DIGEST,
        "provenance": provenance(),
    }
    fields.update(overrides)
    return ExploratoryPublication(**fields)


def specification(**overrides: Any) -> ResearchSpecification:
    fields: dict[str, Any] = {
        "name": "breakout-long-m0-exploratory",
        "version": "breakout-long-m0-exploratory-v1",
        "admits_profile": ExploratoryProfile.EXPLORATORY_HINDSIGHT,
        "admits_derivation": ExploratoryDerivation.AS_DATED,
        "declared_limitations": ALL,
        "base_strategy_version": "breakout-long/r1-research",
        "differences": ("D1 profile",),
        "trial": 1,
    }
    fields.update(overrides)
    return ResearchSpecification(**fields)


def inputs() -> ExploratoryInputSet:
    return ExploratoryInputSet(publications=(publication(),))


def refused(call: Any, defect: ExploratoryDefect) -> None:
    with pytest.raises(ExploratoryContractError) as caught:
        call()
    assert caught.value.defect is defect


# --- admit() never raises -----------------------------------------------------------------


def test_a_consumer_whose_data_attribute_raises_is_refused_not_propagated() -> None:
    """On 56556d9e the ``data`` lookup sat outside the guard and a RuntimeError escaped."""

    class RaisingData:
        @property
        def data(self) -> object:
            raise RuntimeError("inspection must not escape the rule")

    assert admit(RaisingData(), inputs()) is AdmissionOutcome.REFUSED_NOT_A_RESEARCH_SPECIFICATION
    # Control: the accepted-shaped consumer is still named as a production consumer.

    class Accepted:
        class data:  # noqa: N801 -- the accepted spec's attribute name
            required_profile = InformationSetProfile.PROVIDER_REALISTIC_PIT

    assert admit(Accepted(), inputs()) is AdmissionOutcome.REFUSED_PRODUCTION_CONSUMER


@pytest.mark.parametrize("name", [m.value for m in InformationSetProfile])
def test_a_production_profile_carried_by_name_is_a_production_consumer(name: str) -> None:
    """On 56556d9e only the enum member was recognised; the same name as a string was refused
    under the generic code, which under-reports what was attempted."""

    class ByName:
        required_profile = name

    assert admit(ByName(), inputs()) is AdmissionOutcome.REFUSED_PRODUCTION_CONSUMER
    # Control: an unrelated string is not a production consumer.

    class Other:
        required_profile = "EXPLORATORY_HINDSIGHT"

    assert admit(Other(), inputs()) is AdmissionOutcome.REFUSED_NOT_A_RESEARCH_SPECIFICATION


# --- constructors refuse with closed codes, never raw exceptions ------------------------------


@pytest.mark.parametrize("bad", [None, 5, b"x" * 64, ["a"]])
def test_a_non_string_digest_or_identity_refuses_at_construction(bad: object) -> None:
    """On 56556d9e a non-string reached ``re.fullmatch`` and raised TypeError."""
    refused(lambda: provenance(source_manifest_digest=bad), ExploratoryDefect.FIELD_MALFORMED)
    refused(lambda: publication(content_digest=bad), ExploratoryDefect.FIELD_MALFORMED)
    refused(lambda: publication(publication_id=bad), ExploratoryDefect.FIELD_MALFORMED)
    # Control: the well-formed values construct.
    assert publication().content_digest == DIGEST


def test_a_wrong_typed_provenance_on_a_publication_is_malformed_not_missing() -> None:
    refused(lambda: publication(provenance={"profile": "x"}), ExploratoryDefect.FIELD_MALFORMED)
    refused(lambda: publication(provenance=None), ExploratoryDefect.PROFILE_MISSING)


# --- parsers refuse with closed codes, never raw exceptions -----------------------------------


def test_an_unhashable_limitation_item_refuses_instead_of_raising() -> None:
    """On 56556d9e the duplicate check built a set before the items were typed: TypeError."""
    document = provenance().document()
    document["limitations"] = [["REVISION_LOOKAHEAD"]]
    refused(lambda: parse_provenance(document), ExploratoryDefect.FIELD_MALFORMED)
    spec_document = specification().document()
    spec_document["declared_limitations"] = [{"a": 1}]
    refused(lambda: parse_research_specification(spec_document), ExploratoryDefect.FIELD_MALFORMED)
    # Control: a real duplicate is still FIELD_MALFORMED, an unknown name LIMITATION_UNKNOWN.
    document = provenance().document()
    document["limitations"] = [*document["limitations"], document["limitations"][0]]
    refused(lambda: parse_provenance(document), ExploratoryDefect.FIELD_MALFORMED)
    document = provenance().document()
    document["limitations"] = [*document["limitations"], "NO_SUCH_LIMITATION"]
    refused(lambda: parse_provenance(document), ExploratoryDefect.LIMITATION_UNKNOWN)


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_schema_version_is_the_exact_integer_one(version: object) -> None:
    """On 56556d9e ``True == 1`` and ``1.0 == 1`` passed the contract check."""
    for build, parse in (
        (provenance, parse_provenance),
        (publication, parse_publication),
        (specification, parse_research_specification),
        (inputs, parse_input_set),
    ):
        document = build().document()
        document["schema_version"] = version
        refused(lambda p=parse, d=document: p(d), ExploratoryDefect.CONTRACT_MISMATCH)
    # Control: the integer round-trips.
    assert parse_provenance(provenance().document()) == provenance()


def test_a_lone_surrogate_string_is_a_malformed_document_not_an_encoding_error() -> None:
    """On 56556d9e ``str.encode`` raised UnicodeEncodeError before any refusal."""
    refused(lambda: decode_document('{"a": "\ud800"}'), ExploratoryDefect.DOCUMENT_MALFORMED)
    refused(lambda: decode_document(b'{"a": "\xff"}'), ExploratoryDefect.DOCUMENT_MALFORMED)
    # Control: ordinary text decodes.
    assert decode_document(json.dumps(provenance().document()))["profile"] == (
        "EXPLORATORY_HINDSIGHT"
    )


def test_a_non_string_contract_id_or_missing_nested_provenance_type_refuses() -> None:
    document = publication().document()
    document["contract_id"] = ["kalpamani-exploratory-publication/v1"]
    refused(lambda: parse_publication(document), ExploratoryDefect.CONTRACT_MISMATCH)
    document = publication().document()
    document["provenance"] = "EXPLORATORY_HINDSIGHT"
    refused(lambda: parse_publication(document), ExploratoryDefect.DOCUMENT_MALFORMED)


# --- a research specification must acknowledge the mandatory limitations ----------------------


def test_a_specification_that_ignores_a_mandatory_limitation_is_refused_at_construction() -> None:
    """On 56556d9e such a specification constructed and parsed, and could never admit anything."""
    for missing in MANDATORY_LIMITATIONS:
        refused(
            lambda m=missing: specification(declared_limitations=ALL - {m}),
            ExploratoryDefect.LIMITATION_MISSING,
        )
    document = specification().document()
    document["declared_limitations"] = ["EVENT_BLIND"]
    refused(lambda: parse_research_specification(document), ExploratoryDefect.LIMITATION_MISSING)
    # Controls: the mandatory four alone are a valid acknowledgment, and the full set admits.
    narrow = specification(declared_limitations=MANDATORY_LIMITATIONS)
    narrow_inputs = ExploratoryInputSet(
        publications=(publication(provenance=provenance(limitations=MANDATORY_LIMITATIONS)),)
    )
    assert admit(narrow, narrow_inputs) is AdmissionOutcome.ADMITTED
    assert admit(narrow, inputs()) is AdmissionOutcome.REFUSED_LIMITATIONS_UNDECLARED
    assert admit(specification(), inputs()) is AdmissionOutcome.ADMITTED
