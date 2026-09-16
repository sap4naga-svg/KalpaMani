"""ADR-0051 (accepted on the merge of PR #111): the exploratory research isolation foundation, on
synthetic documents only.

What these tests establish is contract behaviour on synthetic inputs: an explicitly exploratory
research specification admits a compatible exploratory input set; the accepted Breakout Long
specification and every other consumer refuse it; a missing, unknown, substituted, mixed or
contradictory profile or provenance refuses at parsing; serialization preserves the
classification; and the accepted vocabularies, gate and production resolution are unchanged.
None of it is empirical: no row, no run, no result.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Final

import pytest

from kalpamani.data.contracts.vocabulary import InformationSetProfile, ProviderBoundDerivation
from kalpamani.data.exploratory import admission, contracts, vocabulary
from kalpamani.data.exploratory.admission import (
    AdmissionOutcome,
    ResearchSpecification,
    admit,
    parse_research_specification,
)
from kalpamani.data.exploratory.contracts import (
    CLASSIFICATION,
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
    AvailabilityBasis,
    ExploratoryDerivation,
    ExploratoryLimitation,
    ExploratoryProfile,
    QualificationClaim,
)
from kalpamani.data.production.sharadar import availability
from kalpamani.strategies.brain import gate
from kalpamani.strategies.breakout import long as breakout_long

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
SRC: Final = REPO_ROOT / "src" / "kalpamani"

DIGEST_A: Final = hashlib.sha256(b"synthetic manifest a").hexdigest()
DIGEST_B: Final = hashlib.sha256(b"synthetic content b").hexdigest()
ALL_LIMITATIONS: Final = frozenset(ExploratoryLimitation)


def provenance(**overrides: Any) -> ExploratoryProvenance:
    fields: dict[str, Any] = {
        "profile": ExploratoryProfile.EXPLORATORY_HINDSIGHT,
        "derivation": ExploratoryDerivation.AS_DATED,
        "limitations": ALL_LIMITATIONS,
        "source_manifest_digest": DIGEST_A,
    }
    fields.update(overrides)
    return ExploratoryProvenance(**fields)


def publication(identity: str = "synthetic-pub-01", **overrides: Any) -> ExploratoryPublication:
    return ExploratoryPublication(
        publication_id=identity, content_digest=DIGEST_B, provenance=provenance(**overrides)
    )


def input_set(*publications: ExploratoryPublication) -> ExploratoryInputSet:
    return ExploratoryInputSet(publications=publications or (publication(),))


def research_specification(**overrides: Any) -> ResearchSpecification:
    fields: dict[str, Any] = {
        "name": "breakout-long-m0-exploratory",
        "version": "breakout-long-m0-exploratory-v1",
        "admits_profile": ExploratoryProfile.EXPLORATORY_HINDSIGHT,
        "admits_derivation": ExploratoryDerivation.AS_DATED,
        "declared_limitations": ALL_LIMITATIONS,
        "base_strategy_version": breakout_long.build_spec().version,
        "differences": ("D1 profile", "D2 event-blind", "D3 constant permission"),
        "trial": 1,
    }
    fields.update(overrides)
    return ResearchSpecification(**fields)


def refused(call: Any, defect: ExploratoryDefect) -> None:
    with pytest.raises(ExploratoryContractError) as caught:
        call()
    assert caught.value.defect is defect


# ---------------------------------------------------------------------------
# Admission: an explicit research specification admits; everything else refuses
# ---------------------------------------------------------------------------


def test_an_explicitly_exploratory_specification_admits_a_compatible_input_set() -> None:
    assert admit(research_specification(), input_set()) is AdmissionOutcome.ADMITTED


def test_the_accepted_breakout_long_specification_refuses_the_same_input_set() -> None:
    spec = breakout_long.build_spec()
    assert spec.data.required_profile is InformationSetProfile.PROVIDER_REALISTIC_PIT
    assert admit(spec, input_set()) is AdmissionOutcome.REFUSED_PRODUCTION_CONSUMER


@pytest.mark.parametrize("profile", list(InformationSetProfile))
def test_any_consumer_declaring_an_accepted_profile_is_a_production_consumer(
    profile: InformationSetProfile,
) -> None:
    class Consumer:
        required_profile = profile

    class Nested:
        data = Consumer()

    assert admit(Consumer(), input_set()) is AdmissionOutcome.REFUSED_PRODUCTION_CONSUMER
    assert admit(Nested(), input_set()) is AdmissionOutcome.REFUSED_PRODUCTION_CONSUMER


def test_a_consumer_that_is_not_a_research_specification_is_refused() -> None:
    class Raising:
        @property
        def required_profile(self) -> object:
            raise RuntimeError("inspection must not escape")

    for consumer in (None, "breakout-long-m0-exploratory-v1", object(), Raising(), {}):
        assert admit(consumer, input_set()) is AdmissionOutcome.REFUSED_NOT_A_RESEARCH_SPECIFICATION


def test_a_research_specification_cannot_be_forged_by_a_lookalike() -> None:
    class Lookalike:
        admits_profile = ExploratoryProfile.EXPLORATORY_HINDSIGHT
        admits_derivation = ExploratoryDerivation.AS_DATED
        declared_limitations = ALL_LIMITATIONS

    assert admit(Lookalike(), input_set()) is AdmissionOutcome.REFUSED_NOT_A_RESEARCH_SPECIFICATION


def test_inputs_that_are_not_an_input_set_are_refused_before_the_consumer_is_read() -> None:
    for inputs in (None, publication(), publication().document(), [publication()]):
        assert admit(research_specification(), inputs) is AdmissionOutcome.REFUSED_NOT_AN_INPUT_SET


def test_a_specification_must_acknowledge_every_limitation_the_inputs_declare() -> None:
    narrower = research_specification(declared_limitations=MANDATORY_LIMITATIONS)
    assert admit(narrower, input_set()) is AdmissionOutcome.REFUSED_LIMITATIONS_UNDECLARED
    # The inputs declaring only the mandatory four are admitted by the narrower specification.
    narrower_inputs = input_set(publication(limitations=MANDATORY_LIMITATIONS))
    assert admit(narrower, narrower_inputs) is AdmissionOutcome.ADMITTED


def test_a_research_specification_names_at_least_one_difference_and_a_trial() -> None:
    refused(lambda: research_specification(differences=()), ExploratoryDefect.FIELD_MALFORMED)
    refused(
        lambda: research_specification(differences=("", "x")), ExploratoryDefect.FIELD_MALFORMED
    )
    refused(lambda: research_specification(trial=0), ExploratoryDefect.FIELD_MALFORMED)
    refused(lambda: research_specification(trial=True), ExploratoryDefect.FIELD_MALFORMED)


# ---------------------------------------------------------------------------
# Parsing: missing, unknown, substituted, mixed and contradictory provenance refuse
# ---------------------------------------------------------------------------


def test_a_missing_profile_refuses_as_missing_not_as_a_default() -> None:
    document = provenance().document()
    document["profile"] = None
    refused(lambda: parse_provenance(document), ExploratoryDefect.PROFILE_MISSING)
    del document["profile"]
    refused(lambda: parse_provenance(document), ExploratoryDefect.FIELD_SET_MISMATCH)
    pub = publication().document()
    pub["provenance"] = None
    refused(lambda: parse_publication(pub), ExploratoryDefect.PROFILE_MISSING)


def test_an_unknown_profile_or_derivation_refuses() -> None:
    document = provenance().document()
    document["profile"] = "HINDSIGHT"
    refused(lambda: parse_provenance(document), ExploratoryDefect.PROFILE_UNKNOWN)
    document = provenance().document()
    document["derivation"] = "AS_DELIVERED"
    refused(lambda: parse_provenance(document), ExploratoryDefect.DERIVATION_UNKNOWN)


@pytest.mark.parametrize("production_profile", [m.value for m in InformationSetProfile])
def test_a_production_profile_in_an_exploratory_document_is_a_substitution(
    production_profile: str,
) -> None:
    document = provenance().document()
    document["profile"] = production_profile
    refused(lambda: parse_provenance(document), ExploratoryDefect.PRODUCTION_PROFILE_SUBSTITUTED)


@pytest.mark.parametrize("production_derivation", [m.value for m in ProviderBoundDerivation])
def test_a_production_derivation_in_an_exploratory_document_is_a_substitution(
    production_derivation: str,
) -> None:
    document = provenance().document()
    document["derivation"] = production_derivation
    refused(lambda: parse_provenance(document), ExploratoryDefect.PRODUCTION_DERIVATION_SUBSTITUTED)


def test_an_evidenced_basis_or_a_qualification_claim_refuses() -> None:
    document = provenance().document()
    document["availability_basis"] = AvailabilityBasis.EVIDENCED.value
    refused(lambda: parse_provenance(document), ExploratoryDefect.EVIDENCED_BASIS_CLAIMED)
    document = provenance().document()
    document["production_qualification"] = "PROVIDER_REALISTIC_PIT"
    refused(lambda: parse_provenance(document), ExploratoryDefect.QUALIFICATION_CLAIMED)
    # The same two refusals hold at construction, not only at parsing.
    refused(
        lambda: provenance(availability_basis=AvailabilityBasis.EVIDENCED),
        ExploratoryDefect.EVIDENCED_BASIS_CLAIMED,
    )
    refused(
        lambda: provenance(production_qualification="QUALIFIED"),
        ExploratoryDefect.QUALIFICATION_CLAIMED,
    )
    assert QualificationClaim.NONE.value == "NONE" and len(QualificationClaim) == 1


def test_the_mandatory_limitations_must_be_declared() -> None:
    for missing in MANDATORY_LIMITATIONS:
        refused(
            lambda m=missing: provenance(limitations=ALL_LIMITATIONS - {m}),
            ExploratoryDefect.LIMITATION_MISSING,
        )
    document = provenance().document()
    document["limitations"] = [*sorted(document["limitations"]), "NO_SURVIVORSHIP_BIAS"]
    refused(lambda: parse_provenance(document), ExploratoryDefect.LIMITATION_UNKNOWN)
    document = provenance().document()
    document["limitations"] = [*document["limitations"], document["limitations"][0]]
    refused(lambda: parse_provenance(document), ExploratoryDefect.FIELD_MALFORMED)


def test_the_field_set_and_contract_are_closed() -> None:
    document = provenance().document()
    document["evidenced"] = True
    refused(lambda: parse_provenance(document), ExploratoryDefect.FIELD_SET_MISMATCH)
    document = provenance().document()
    document["contract_id"] = "kalpamani-production-build-manifest/v1"
    refused(lambda: parse_provenance(document), ExploratoryDefect.CONTRACT_MISMATCH)
    document = provenance().document()
    document["source_manifest_contract"] = "kalpamani-exploratory-publication/v1"
    refused(lambda: parse_provenance(document), ExploratoryDefect.CONTRACT_MISMATCH)
    document = provenance().document()
    document["source_manifest_digest"] = DIGEST_A.upper()
    refused(lambda: parse_provenance(document), ExploratoryDefect.FIELD_MALFORMED)
    refused(lambda: parse_provenance([]), ExploratoryDefect.DOCUMENT_MALFORMED)


def test_a_duplicate_key_at_any_depth_and_an_oversize_document_refuse() -> None:
    text = json.dumps(publication().document())
    duplicated = text.replace(
        '"classification"', '"classification": "PUBLIC_SAFE", "classification"', 1
    )
    refused(lambda: decode_document(duplicated), ExploratoryDefect.DUPLICATE_KEY)
    nested = text.replace('"profile"', '"profile": "PUBLIC_PIT", "profile"', 1)
    refused(lambda: decode_document(nested), ExploratoryDefect.DUPLICATE_KEY)
    refused(lambda: decode_document("[]"), ExploratoryDefect.DOCUMENT_MALFORMED)
    refused(lambda: decode_document("{" * 10), ExploratoryDefect.DOCUMENT_MALFORMED)
    refused(
        lambda: decode_document("{" + " " * contracts.MAX_DOCUMENT_BYTES + "}"),
        ExploratoryDefect.DOCUMENT_MALFORMED,
    )


def test_a_publication_carries_only_the_licensed_derived_classification() -> None:
    document = publication().document()
    document["classification"] = "PUBLIC_SAFE"
    refused(lambda: parse_publication(document), ExploratoryDefect.CLASSIFICATION_MISMATCH)
    assert publication().classification == CLASSIFICATION == "LICENSED_DERIVED"


def test_a_mixed_input_set_refuses() -> None:
    narrower = publication("synthetic-pub-02", limitations=MANDATORY_LIMITATIONS)
    refused(lambda: input_set(publication(), narrower), ExploratoryDefect.PROVENANCE_MIXED)
    refused(lambda: ExploratoryInputSet(publications=()), ExploratoryDefect.INPUT_SET_EMPTY)
    refused(lambda: input_set(publication(), publication()), ExploratoryDefect.IDENTITY_DUPLICATED)
    too_many = tuple(
        publication(f"synthetic-pub-{i:03d}") for i in range(contracts.MAX_PUBLICATIONS + 1)
    )
    refused(
        lambda: ExploratoryInputSet(publications=too_many), ExploratoryDefect.INPUT_SET_TOO_LARGE
    )
    # A mixture assembled through the document, not only through the constructor.
    document = input_set(publication(), publication("synthetic-pub-02")).document()
    document["publications"][1]["provenance"]["derivation"] = "FIRST_SEEN_UPPER_BOUND"
    refused(lambda: parse_input_set(document), ExploratoryDefect.PRODUCTION_DERIVATION_SUBSTITUTED)


# ---------------------------------------------------------------------------
# Serialization preserves the classification
# ---------------------------------------------------------------------------


def test_every_document_round_trips_exactly_and_keeps_its_profile() -> None:
    prov = provenance()
    assert parse_provenance(prov.document()) == prov
    assert parse_provenance(decode_document(json.dumps(prov.document()))).digest == prov.digest
    pub = publication()
    assert parse_publication(pub.document()) == pub
    assert (
        parse_publication(pub.document()).provenance.profile
        is ExploratoryProfile.EXPLORATORY_HINDSIGHT
    )
    inputs = input_set(publication(), publication("synthetic-pub-02"))
    assert parse_input_set(inputs.document()) == inputs
    assert parse_input_set(inputs.document()).profile is ExploratoryProfile.EXPLORATORY_HINDSIGHT
    spec = research_specification()
    assert parse_research_specification(spec.document()) == spec
    assert parse_research_specification(spec.document()).digest == spec.digest
    # The profile and basis appear verbatim in the serialized form, never implied.
    text = json.dumps(pub.document())
    assert '"profile": "EXPLORATORY_HINDSIGHT"' in text
    assert '"availability_basis": "ASSUMED_HISTORICAL"' in text
    assert '"production_qualification": "NONE"' in text
    assert "PROVIDER_REALISTIC_PIT" not in text and "PUBLIC_PIT" not in text


def test_the_digest_is_over_the_canonical_document() -> None:
    prov = provenance()
    canonical = json.dumps(
        prov.document(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    assert prov.digest == hashlib.sha256(canonical).hexdigest()
    assert provenance(limitations=MANDATORY_LIMITATIONS).digest != prov.digest


# ---------------------------------------------------------------------------
# The accepted vocabularies, gate and production resolution are unchanged
# ---------------------------------------------------------------------------


def test_the_exploratory_vocabulary_shares_no_value_with_the_accepted_one() -> None:
    assert {m.value for m in InformationSetProfile} == {
        "PUBLIC_PIT",
        "PROVIDER_REALISTIC_PIT",
        "FORWARD_SYSTEM",
    }
    assert {m.value for m in ProviderBoundDerivation} == {
        "FIRST_SEEN_UPPER_BOUND",
        "DELIVERY_WINDOW",
        "NONE",
    }
    with pytest.raises(ValueError):
        InformationSetProfile("EXPLORATORY_HINDSIGHT")
    with pytest.raises(ValueError):
        ProviderBoundDerivation("AS_DATED")
    assert vocabulary.PRODUCTION_PROFILE_NAMES == {m.value for m in InformationSetProfile}
    assert [m.value for m in ExploratoryProfile] == ["EXPLORATORY_HINDSIGHT"]
    assert [m.value for m in ExploratoryDerivation] == ["AS_DATED"]


def test_the_accepted_gate_admits_only_the_two_point_in_time_profiles() -> None:
    assert gate._POINT_IN_TIME_PROFILES == frozenset(
        {InformationSetProfile.PUBLIC_PIT, InformationSetProfile.PROVIDER_REALISTIC_PIT}
    )
    # An exploratory profile is not an InformationSetProfile at all, so it can never be a
    # member of that set, whatever a later vocabulary adds.
    assert "EXPLORATORY_HINDSIGHT" not in {m.value for m in gate._POINT_IN_TIME_PROFILES}


def test_the_production_availability_resolution_is_unchanged() -> None:
    assert availability.RESOLVED_PROFILE is InformationSetProfile.PROVIDER_REALISTIC_PIT
    assert availability.EXPRESSIBLE_DERIVATIONS == frozenset(
        {ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND, ProviderBoundDerivation.DELIVERY_WINDOW}
    )
    assert availability.RESOLUTION_POLICY_VERSION == "sharadar-availability-v2"


def test_the_accepted_breakout_long_specification_is_unchanged() -> None:
    params = breakout_long.BreakoutLongParameters()
    assert (params.trend_sessions, params.base_sessions, params.relative_strength_sessions) == (
        50,
        20,
        60,
    )
    assert (params.volume_baseline_sessions, params.liquidity_sessions) == (20, 20)
    assert params.high_proximity_sessions == 252 and params.required_history_sessions == 252
    assert str(params.max_base_compactness) == "0.15"
    assert str(params.min_relative_volume) == "1.5"
    assert str(params.min_relative_strength) == "0.0"
    assert str(params.max_entry_gap) == "0.10"
    assert str(params.min_average_dollar_volume) == "1000000"
    spec = breakout_long.build_spec()
    assert spec.data.required_profile is InformationSetProfile.PROVIDER_REALISTIC_PIT
    assert spec.version == "breakout-long/r1-research"


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_no_accepted_module_imports_the_exploratory_package() -> None:
    """Research may read accepted contracts; nothing accepted reads research."""
    accepted = [
        SRC / "data" / "contracts",
        SRC / "data" / "curate",
        SRC / "data" / "pit",
        SRC / "data" / "production",
        SRC / "data" / "qualify",
        SRC / "data" / "quality",
        SRC / "data" / "ingest",
        SRC / "data" / "storage",
        SRC / "strategies",
        SRC / "execution",
        SRC / "portfolio",
        SRC / "risk",
        SRC / "broker",
        SRC / "common",
        REPO_ROOT / "scripts",
    ]
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for root in accepted
        for path in root.rglob("*.py")
        if any(name.startswith("kalpamani.data.exploratory") for name in _imports_of(path))
    ]
    assert offenders == []


def test_the_exploratory_package_imports_no_production_runtime_and_no_network() -> None:
    forbidden = ("boto3", "botocore", "socket", "urllib", "http", "kalpamani.data.production")
    for module in (vocabulary, contracts, admission):
        names = _imports_of(Path(str(module.__file__)))
        assert not any(
            name == bad or name.startswith(bad + ".") for name in names for bad in forbidden
        ), module.__name__


# The accepted production *contract* modules the research path may read: pure data shapes and
# deterministic clauses, none of which constructs a client, reads a binding or reaches a store.
_ACCEPTED_CONTRACT_MODULES = frozenset(
    {
        "kalpamani.data.production.sharadar.availability",
        "kalpamani.data.production.sharadar.sessions",
        "kalpamani.data.production.sharadar.silver",
        "kalpamani.data.production.sharadar.universe",
    }
)


def test_every_exploratory_module_reads_only_accepted_contracts_and_no_runtime() -> None:
    """The later modules may read accepted contract shapes; none may reach a task runtime, a
    binding, a store, a launcher, a network or the AWS SDK."""
    forbidden_exact = (
        "boto3",
        "botocore",
        "socket",
        "urllib",
        "http",
        "subprocess",
        "kalpamani.data.storage",
        "kalpamani.broker",
        "kalpamani.execution",
    )
    package = SRC / "data" / "exploratory"
    modules = sorted(package.glob("*.py"))
    assert len(modules) >= 8, [m.name for m in modules]
    for path in modules:
        names = _imports_of(path)
        for name in names:
            assert not any(name == bad or name.startswith(bad + ".") for bad in forbidden_exact), (
                path.name,
                name,
            )
            if name.startswith("kalpamani.data.production"):
                assert name in _ACCEPTED_CONTRACT_MODULES, (path.name, name)
            if name.startswith("kalpamani.data.ingest"):
                # The dataset vocabulary only: never the client, transport, secrets,
                # composition or any other module of the provider package.
                assert name == "kalpamani.data.ingest.sharadar.datasets", (path.name, name)
