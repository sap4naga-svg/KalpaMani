"""The R-2 isolation verdict (proposed ADR-0045 §3): derived from evidence, never supplied.

The observation binds the destination the task actually selected under a keyed digest;
the corroboration is a closed transcription of one Reachability Analyzer analysis; every
comparison -- source interface, destination, port, protocol, status, time window, the
blocking explanation and its placement -- is derived here from the two records and the
launch binding. ``CONNECTED`` always fails; everything not bound stays ``INCONCLUSIVE``;
configuration-model evidence is never read as a packet observation.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

import pytest

from fixtures.production_entry import ORIGIN_ADDRESSES
from fixtures.production_runtime import (
    CANARIES,
    INTERFACE_ID,
    NOW,
    OTHER_SECURITY_GROUP,
    OTHER_SUBNET_ID,
    SECURITY_GROUPS,
    SUBNET_ID,
    encode,
)
from kalpamani.data.production.sharadar import probe as pp

pytestmark = pytest.mark.unit

KEY: Final = "ab" * 32
SELECTED: Final = min(ORIGIN_ADDRESSES)


def _observation(
    result: pp.ProbeResult = pp.ProbeResult.TIMED_OUT, *, address: str = SELECTED
) -> pp.ProbeObservation:
    if result is pp.ProbeResult.NOT_ATTEMPTED:
        return pp.ProbeObservation(
            resolution=pp.ProbeResolution.UNRESOLVED, result=result, attempts=0
        )
    return pp.ProbeObservation(
        resolution=pp.ProbeResolution.RESOLVED_IN_SET,
        result=result,
        attempts=1,
        destination_digest=pp.destination_binding_digest(KEY, address, pp.PROBE_PORT),
    )


def _binding(**overrides: Any) -> pp.VerdictBinding:
    fields_: dict[str, Any] = {
        "network_interface_id": INTERFACE_ID,
        "subnet_id": SUBNET_ID,
        "security_group_ids": frozenset(SECURITY_GROUPS),
        "launched_at": NOW,
        "recorded_at": NOW + timedelta(minutes=10),
        "binding_key": KEY,
        "origin_addresses": frozenset(ORIGIN_ADDRESSES),
    }
    fields_.update(overrides)
    return pp.VerdictBinding(**fields_)


def _evidence_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": 1,
        "contract_id": pp.REACHABILITY_EVIDENCE_CONTRACT_ID,
        "analysis_id": "nia-0123456789abcdef0",
        "path_id": "nip-0123456789abcdef0",
        "status": "succeeded",
        "network_path_found": False,
        "start_date": (NOW + timedelta(minutes=2)).isoformat(),
        "source_interface_id": INTERFACE_ID,
        "destination_ip": SELECTED,
        "destination_port": 443,
        "protocol": "tcp",
        "explanations": [
            {
                "explanation_code": "NO_ROUTE_TO_DESTINATION",
                "component_kind": "ROUTE_TABLE",
                "component_id": "rtb-0123456789abcdef0",
                "subnet_id": SUBNET_ID,
            }
        ],
    }
    document.update(overrides)
    return document


def _evidence(**overrides: Any) -> pp.ReachabilityEvidence:
    return pp.parse_reachability_evidence(encode(_evidence_document(**overrides)))


class TestDestinationBinding:
    def test_the_digest_is_keyed_and_recovers_only_the_selected_address(self) -> None:
        observation = _observation()
        assert pp.bound_destination(_binding(), observation) == SELECTED
        # A different key -- another launch's input -- recovers nothing.
        assert pp.bound_destination(_binding(binding_key="cd" * 32), observation) is None
        # A compiled set that does not contain the selected address recovers nothing:
        # the task's DNS result is read from its own record, never assumed from the set.
        assert (
            pp.bound_destination(
                _binding(origin_addresses=frozenset({"198.51.100.1"})), observation
            )
            is None
        )
        assert pp.bound_destination(_binding(), _observation(pp.ProbeResult.NOT_ATTEMPTED)) is None

    def test_the_digest_names_no_address(self) -> None:
        digest = pp.destination_binding_digest(KEY, SELECTED, pp.PROBE_PORT)
        assert len(digest) == 64 and SELECTED not in digest
        assert digest != pp.destination_binding_digest(KEY, SELECTED, 8443)
        with pytest.raises(ValueError):
            pp.destination_binding_digest("not-a-digest", SELECTED, pp.PROBE_PORT)


class TestEvidenceParsing:
    def test_a_well_formed_transcription_parses_closed(self) -> None:
        evidence = _evidence()
        assert evidence.kind is pp.CorroborationKind.REACHABILITY_ANALYSIS
        assert evidence.status == pp.ANALYSIS_SUCCEEDED and not evidence.network_path_found
        assert evidence.explanations[0].component_kind is pp.BlockingComponent.ROUTE_TABLE
        for canary in CANARIES:
            assert canary not in repr(evidence) and canary not in repr(evidence.explanations[0])
        assert INTERFACE_ID not in repr(evidence) and SELECTED not in repr(evidence)

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d.__setitem__("status", "done"),
            lambda d: d.__setitem__("analysis_id", "analysis-1"),
            lambda d: d.__setitem__("path_id", "nia-0123456789abcdef0"),
            lambda d: d.__setitem__("source_interface_id", "i-0123456789abcdef0"),
            lambda d: d.__setitem__("destination_ip", "example.invalid"),
            lambda d: d.__setitem__("destination_port", "443"),
            lambda d: d.__setitem__("protocol", "icmp"),
            lambda d: d.__setitem__("network_path_found", "false"),
            lambda d: d.__setitem__("start_date", "yesterday"),
            lambda d: d.__setitem__("explanations", "NO_ROUTE_TO_DESTINATION"),
            lambda d: d["explanations"][0].__setitem__("component_kind", "VPC"),
            lambda d: d["explanations"][0].__setitem__("component_id", None),  # kind without id
            lambda d: d["explanations"][0].__setitem__("explanation_code", "no route"),
            lambda d: d["explanations"][0].__setitem__("extra", 1),
            lambda d: d.__setitem__("contract_id", "kalpamani-reachability-evidence/v2"),
            lambda d: d.pop("path_id"),
            lambda d: d.__setitem__("explanations", [_evidence_document()["explanations"][0]] * 33),
        ],
    )
    def test_every_departure_from_the_documented_shape_is_refused(self, mutate: Any) -> None:
        document = _evidence_document()
        mutate(document)
        with pytest.raises(ValueError):
            pp.parse_reachability_evidence(encode(document))

    def test_the_admitted_explanations_are_the_documented_vpc_control_codes(self) -> None:
        assert pp.ADMITTED_EXPLANATIONS == {
            "ENI_SG_RULES_MISMATCH": pp.BlockingComponent.SECURITY_GROUP,
            "SG_HAS_NO_RULES": pp.BlockingComponent.SECURITY_GROUP,
            "SUBNET_ACL_RESTRICTION": pp.BlockingComponent.NETWORK_ACL,
            "NO_ROUTE_TO_DESTINATION": pp.BlockingComponent.ROUTE_TABLE,
        }
        assert pp.ANALYSIS_STATUSES == {"running", "succeeded", "failed"}
        assert pp.PROBE_PROTOCOL == "tcp"


class TestVerdict:
    def test_the_verdict_takes_no_supplied_match_booleans(self) -> None:
        """PR #104 review finding 4: the earlier shape accepted caller-supplied matches."""
        assert not hasattr(pp, "IsolationCorroboration")
        fields = set(pp.ReachabilityEvidence.__dataclass_fields__)
        assert not {"source_interface_matches", "destination_matches"} & fields
        assert {"analysis_id", "status", "start_date", "source_interface_id"} <= fields

    def test_bound_evidence_verifies_with_its_reason_and_components(self) -> None:
        record = pp.isolation_verdict(_observation(), _evidence(), binding=_binding())
        assert record.verdict is pp.IsolationVerdict.VERIFIED
        assert record.reason is pp.VerdictReason.CORROBORATED
        assert record.blocking_components == frozenset({pp.BlockingComponent.ROUTE_TABLE})
        assert record.analysis_bound
        assert record.document() == {
            "verdict": "VERIFIED",
            "reason": "CORROBORATED",
            "blocking_components": ["ROUTE_TABLE"],
            "analysis_bound": True,
        }

    def test_connected_fails_whatever_the_model_says(self) -> None:
        for evidence in (None, _evidence(), _evidence(network_path_found=True)):
            record = pp.isolation_verdict(
                _observation(pp.ProbeResult.CONNECTED), evidence, binding=_binding()
            )
            assert record.verdict is pp.IsolationVerdict.FAILED
            assert record.reason is pp.VerdictReason.OBSERVED_CONNECTION

    @pytest.mark.parametrize(
        "result",
        [
            pp.ProbeResult.TIMED_OUT,
            pp.ProbeResult.CONNECTION_REFUSED,
            pp.ProbeResult.CONNECTION_ERROR,
        ],
    )
    def test_a_non_connection_without_evidence_is_inconclusive(
        self, result: pp.ProbeResult
    ) -> None:
        record = pp.isolation_verdict(_observation(result), None, binding=_binding())
        assert record.verdict is pp.IsolationVerdict.INCONCLUSIVE
        assert record.reason is pp.VerdictReason.NO_CORROBORATION and not record.analysis_bound

    def test_an_unattempted_or_unbound_probe_is_inconclusive_even_with_evidence(self) -> None:
        record = pp.isolation_verdict(
            _observation(pp.ProbeResult.NOT_ATTEMPTED), _evidence(), binding=_binding()
        )
        assert record.reason is pp.VerdictReason.NO_ATTEMPT
        record = pp.isolation_verdict(
            _observation(), _evidence(), binding=_binding(binding_key="cd" * 32)
        )
        assert record.reason is pp.VerdictReason.DESTINATION_UNBOUND
        assert record.verdict is pp.IsolationVerdict.INCONCLUSIVE

    @pytest.mark.parametrize(
        ("reason", "overrides"),
        [
            (pp.VerdictReason.ANALYSIS_NOT_SUCCEEDED, {"status": "failed"}),
            (pp.VerdictReason.ANALYSIS_NOT_SUCCEEDED, {"status": "running"}),
            (pp.VerdictReason.SOURCE_MISMATCH, {"source_interface_id": "eni-0fedcba9876543210"}),
            (pp.VerdictReason.DESTINATION_MISMATCH, {"destination_ip": max(ORIGIN_ADDRESSES)}),
            (pp.VerdictReason.DESTINATION_MISMATCH, {"destination_port": 80}),
            (pp.VerdictReason.DESTINATION_MISMATCH, {"protocol": "udp"}),
            (
                pp.VerdictReason.ANALYSIS_OUTSIDE_TASK_WINDOW,
                {"start_date": (NOW - timedelta(seconds=1)).isoformat()},
            ),
            (
                pp.VerdictReason.ANALYSIS_OUTSIDE_TASK_WINDOW,
                {"start_date": (NOW + timedelta(minutes=11)).isoformat()},
            ),
            (pp.VerdictReason.PATH_FOUND_CONTRADICTS_OBSERVATION, {"network_path_found": True}),
            (pp.VerdictReason.UNSUPPORTED_EXPLANATION, {"explanations": []}),
            (
                pp.VerdictReason.UNSUPPORTED_EXPLANATION,
                {
                    "explanations": [
                        {
                            "explanation_code": "VPC_BLOCK_PUBLIC_ACCESS_ENABLED",
                            "component_kind": None,
                            "component_id": None,
                            "subnet_id": None,
                        }
                    ]
                },
            ),
            (
                pp.VerdictReason.UNSUPPORTED_EXPLANATION,
                {
                    # A documented code attributed to the wrong component kind corroborates
                    # nothing: the code and the component must agree.
                    "explanations": [
                        {
                            "explanation_code": "NO_ROUTE_TO_DESTINATION",
                            "component_kind": "SECURITY_GROUP",
                            "component_id": SECURITY_GROUPS[0],
                            "subnet_id": None,
                        }
                    ]
                },
            ),
            (
                pp.VerdictReason.COMPONENT_OUTSIDE_PLACEMENT,
                {
                    "explanations": [
                        {
                            "explanation_code": "NO_ROUTE_TO_DESTINATION",
                            "component_kind": "ROUTE_TABLE",
                            "component_id": "rtb-0123456789abcdef0",
                            "subnet_id": OTHER_SUBNET_ID,
                        }
                    ]
                },
            ),
            (
                pp.VerdictReason.COMPONENT_OUTSIDE_PLACEMENT,
                {
                    "explanations": [
                        {
                            "explanation_code": "ENI_SG_RULES_MISMATCH",
                            "component_kind": "SECURITY_GROUP",
                            "component_id": OTHER_SECURITY_GROUP,
                            "subnet_id": None,
                        }
                    ]
                },
            ),
        ],
    )
    def test_missing_stale_unsupported_contradictory_or_unbound_corroboration_is_inconclusive(
        self, reason: pp.VerdictReason, overrides: dict[str, Any]
    ) -> None:
        record = pp.isolation_verdict(_observation(), _evidence(**overrides), binding=_binding())
        assert record.verdict is pp.IsolationVerdict.INCONCLUSIVE and record.reason is reason
        assert record.blocking_components == frozenset()

    def test_a_changed_placement_unbinds_a_previously_bound_analysis(self) -> None:
        """The same analysis under a different launch record corroborates nothing."""
        evidence = _evidence()
        assert (
            pp.isolation_verdict(_observation(), evidence, binding=_binding()).verdict
            is pp.IsolationVerdict.VERIFIED
        )
        for overrides in (
            {"network_interface_id": "eni-0fedcba9876543210"},
            {"subnet_id": OTHER_SUBNET_ID},
            {"launched_at": NOW + timedelta(minutes=5), "recorded_at": NOW + timedelta(minutes=6)},
        ):
            record = pp.isolation_verdict(_observation(), evidence, binding=_binding(**overrides))
            assert record.verdict is pp.IsolationVerdict.INCONCLUSIVE, overrides

    def test_one_admitted_component_inside_the_placement_is_enough_and_others_are_noted(
        self,
    ) -> None:
        evidence = _evidence(
            explanations=[
                {
                    "explanation_code": "SUBNET_ACL_RESTRICTION",
                    "component_kind": "NETWORK_ACL",
                    "component_id": "acl-0123456789abcdef0",
                    "subnet_id": SUBNET_ID,
                },
                {
                    "explanation_code": "ENI_SG_RULES_MISMATCH",
                    "component_kind": "SECURITY_GROUP",
                    "component_id": OTHER_SECURITY_GROUP,
                    "subnet_id": None,
                },
                {
                    "explanation_code": "NO_PATH",
                    "component_kind": None,
                    "component_id": None,
                    "subnet_id": None,
                },
            ]
        )
        record = pp.isolation_verdict(_observation(), evidence, binding=_binding())
        assert record.verdict is pp.IsolationVerdict.VERIFIED
        assert record.blocking_components == frozenset({pp.BlockingComponent.NETWORK_ACL})
