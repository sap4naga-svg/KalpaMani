"""ADR-0045 governance: the proposed verification path, held to its own claims and to the code.

The document is PROPOSED and says so; it names the four entries, the exit code, the probe's
constants and vocabularies, the one admitted corroboration and its permission delta, the receipt
version, the ledger records, the reserved identity prefix, the two Terraform digest keys and the
gates -- and every one of those is read back from the offline code rather than restated.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from kalpamani.data.production.sharadar import (
    compiled,
    entry,
    launch_records,
    probe,
    receipts,
    schema_observation,
    verification_entry,
)
from kalpamani.data.production.sharadar.inputs import LEDGER_OUTCOME_VERIFIED, LEDGER_OUTCOMES
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0045-verification-entries-observation-build-and-launch-tool.md"
PRODUCTION: Final = PROJECT_ROOT / "src" / "kalpamani" / "data" / "production" / "sharadar"
INFRA: Final = PROJECT_ROOT / "infra" / "aws" / "research-data-plane"
LAUNCH_SCRIPT: Final = PROJECT_ROOT / "scripts" / "production_launch.py"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""
ADR_FLAT: Final = " ".join(ADR_TEXT.split())
ADR_PLAIN: Final = ADR_FLAT.replace("**", "").replace("`", "")

HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")
REAL_ARN: Final = re.compile(r"\barn:aws\b")
PROPOSED: Final = "PROPOSED " + chr(0x2014) + " NOT IN FORCE"
SECTION: Final = chr(0xA7)


def test_the_adr_exists_and_is_the_only_0045() -> None:
    assert ADR.is_file()
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0045-*.md"))] == [ADR.name]


def test_the_adr_is_proposed_and_names_its_gates() -> None:
    # The conditional status line is kept as the record of the days before the merge; the
    # post-merge note beside it records that the condition has been satisfied.
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "The condition above has since been satisfied" in ADR_PLAIN
    assert "PR #104 merged" in ADR_PLAIN and "af20f36acbe8a3006830762fbad5cb01d1e9b38b" in ADR_TEXT
    assert "2966ed2f24f7841eea264657f75e9c081e35922a" in ADR_TEXT
    assert "ACCEPTED / IN FORCE" in ADR_PLAIN
    assert "Acceptance authorized no image build" in ADR_PLAIN
    assert "Acceptance authorizes no execution" in ADR_PLAIN
    assert "## 9. Effectiveness and execution gates" in ADR_TEXT
    assert "Nothing was run to produce this decision" in ADR_FLAT
    assert "Mocked results are not AWS verification" in ADR_PLAIN
    assert "does not decide G-14" in ADR_PLAIN and "stays deferred" in ADR_PLAIN
    assert "G2 stays OPEN, CONTROL stays DEFERRED, Phase 3 stays NOT COMPLETE" in ADR_PLAIN
    assert "live trading stays HARD-DISABLED" in ADR_PLAIN


def test_the_adr_names_no_real_value() -> None:
    assert not HEX_64.search(ADR_TEXT)
    assert not TWELVE_DIGITS.search(ADR_TEXT)
    assert not REAL_ARN.search(ADR_TEXT)


def test_the_four_entries_and_the_exit_code_match_the_document() -> None:
    # ADR-0045's four entries; the two probe entries beside them are proposed ADR-0048's.
    assert {e.value for e in entry.TaskEntry if e not in entry.PROBE_ENTRIES} == {
        "kalpamani-production-acquire",
        "kalpamani-research-build",
        "kalpamani-production-acquire-verify",
        "kalpamani-research-build-verify",
    }
    for member in entry.TaskEntry:
        if member not in entry.PROBE_ENTRIES:
            assert member.value in ADR_TEXT
    assert entry.VERIFICATION_ENTRIES == frozenset(
        {entry.TaskEntry.ACQUISITION_VERIFY, entry.TaskEntry.BUILD_VERIFY}
    )
    assert entry.EXIT_STATUS[entry.TaskOutcome.VERIFIED_BOOTSTRAP] == 18
    assert entry.EXIT_STATUS[entry.TaskOutcome.COMPLETED] == 0
    assert "VERIFIED_BOOTSTRAP" in ADR_TEXT and "exit code **18**" in ADR_TEXT
    for actor in ProductionActor:
        constants = constants_for(actor)
        assert constants.verification_task_family in ADR_TEXT
        assert constants.verification_task_family.endswith("-verify")


def test_the_verification_factories_have_no_data_plane_field() -> None:
    fields = set(verification_entry.VerificationFactories.__dataclass_fields__)
    for forbidden in ("secrets", "transport", "s3", "store", "get", "put", "registry"):
        assert not any(forbidden in name for name in fields), fields
    assert "probe" in fields and "ssm" in fields and "sts" in fields
    source = (PRODUCTION / "verification_entry.py").read_text(encoding="utf-8")
    for name in ("secretsmanager", "get_secret_value", "put_object", "get_object", "reserve_run"):
        assert name not in source


def test_the_probe_constants_and_vocabularies_match_the_document() -> None:
    assert probe.PROBE_PORT == 443 and "Port **443**" in ADR_TEXT
    assert probe.PROBE_TIMEOUT_SECONDS == 5.0 and "timeout **5 s**" in ADR_TEXT
    assert probe.PROBE_MAX_ATTEMPTS == 1 and "at most one attempt" in ADR_PLAIN
    assert {m.value for m in probe.ProbeResolution} == {
        "RESOLVED_IN_SET",
        "RESOLVED_OUTSIDE_SET",
        "UNRESOLVED",
    }
    assert {m.value for m in probe.ProbeResult} == {
        "CONNECTED",
        "CONNECTION_REFUSED",
        "TIMED_OUT",
        "CONNECTION_ERROR",
        "NOT_ATTEMPTED",
    }
    assert {m.value for m in probe.IsolationVerdict} == {"FAILED", "INCONCLUSIVE", "VERIFIED"}
    for vocabulary in (probe.ProbeResolution, probe.ProbeResult, probe.IsolationVerdict):
        for member in vocabulary:
            assert member.value in ADR_TEXT
    assert "isolation_verdict=NOT_DECIDED_BY_THE_TASK" in ADR_TEXT
    assert "NOT_DECIDED_BY_THE_TASK" in (PRODUCTION / "entry.py").read_text(encoding="utf-8")


def test_the_one_admitted_corroboration_and_its_limits_are_stated() -> None:
    assert [m.value for m in probe.CorroborationKind] == ["REACHABILITY_ANALYSIS"]
    assert "REACHABILITY_ANALYSIS" in ADR_TEXT
    assert {m.value for m in probe.BlockingComponent} == {
        "ROUTE_TABLE",
        "SECURITY_GROUP",
        "NETWORK_ACL",
        "SUBNET",
    }
    for member in probe.BlockingComponent:
        assert member.value in ADR_TEXT
    # The corroboration is a closed transcription of one analysis, bound by derivation: the
    # document names no supplied match, and the verdict's reasons are the document's.
    assert not hasattr(probe, "IsolationCorroboration")
    for field in (
        "analysis_id",
        "path_id",
        "status",
        "network_path_found",
        "start_date",
        "source_interface_id",
        "destination_ip",
        "destination_port",
        "protocol",
        "explanations",
    ):
        assert field in probe.ReachabilityEvidence.__dataclass_fields__ and field in ADR_TEXT
    assert probe.REACHABILITY_EVIDENCE_CONTRACT_ID in ADR_TEXT
    for reason in probe.VerdictReason:
        assert reason.value in ADR_TEXT, reason
    for code in probe.ADMITTED_EXPLANATIONS:
        assert code in ADR_TEXT, code
    assert "destination_binding_digest" in ADR_TEXT and "probe_destination" in ADR_TEXT
    assert "never infers the task's DNS result" in ADR_PLAIN
    assert "--isolation-verdict" in ADR_TEXT and "VERIFIED is unreachable without one" in ADR_PLAIN
    assert "sends **no packets**" in ADR_TEXT and "charged per analysis" in ADR_PLAIN
    for permission in (
        "ec2:CreateNetworkInsightsPath",
        "ec2:StartNetworkInsightsAnalysis",
        "ec2:DescribeNetworkInsights*",
        "ec2:DeleteNetworkInsights*",
    ):
        assert permission in ADR_TEXT
    assert "That IAM delta is not granted by this ADR" in ADR_PLAIN
    assert "VPC Flow Logs are not admitted as corroboration" in ADR_PLAIN
    assert "never turns INCONCLUSIVE into VERIFIED" in ADR_PLAIN
    # The permission delta is a recorded owner input, not a declaration: no policy names it.
    for path in INFRA.glob("*.tf"):
        assert "NetworkInsights" not in path.read_text(encoding="utf-8"), path.name


def test_the_receipt_version_and_the_observation_block_match_the_document() -> None:
    # ADR-0045 moved the receipt to v2; proposed ADR-0048 moves it to v3 by adding the
    # permission block, and ADR-0045's own text still names the version it introduced.
    assert receipts.RECEIPT_CONTRACT_ID == "kalpamani-task-receipt/v3"
    assert "kalpamani-task-receipt/v2" in ADR_TEXT
    assert receipts.RECEIPT_SCHEMA_VERSION == 3
    assert receipts.LEDGER_OUTCOME_OF[entry.TaskOutcome.VERIFIED_BOOTSTRAP] == "VERIFIED"
    assert LEDGER_OUTCOME_VERIFIED in LEDGER_OUTCOMES
    assert schema_observation.MAX_DIGESTS_PER_DATASET == 8
    assert set(schema_observation.OBSERVED_DATASETS) == {"actions", "stocks", "tickers"}
    assert "schema_observation" in ADR_TEXT and "REFUSED_NORMALIZATION" in ADR_TEXT
    assert "evidence for owner review, never an accepted set" in ADR_PLAIN
    assert "explicitly empty" in ADR_PLAIN


def test_the_compiled_configuration_field_sets_match_the_document() -> None:
    for verify in entry.VERIFICATION_ENTRIES:
        assert compiled.ENTRY_FIELDS[verify] == compiled._VERIFICATION_FIELDS
        assert "secret_name" not in compiled.ENTRY_FIELDS[verify]
        assert "build_configuration" not in compiled.ENTRY_FIELDS[verify]
        assert "origin_addresses" in compiled.ENTRY_FIELDS[verify]
    assert "_VERIFICATION_FIELDS" in ADR_TEXT and "is_known_family" in ADR_TEXT


def test_the_launch_records_and_identity_rule_match_the_document() -> None:
    for contract in (
        launch_records.LEDGER_CONTRACT_ID,
        launch_records.LAUNCH_INPUTS_CONTRACT_ID,
        launch_records.AUTHORIZATION_CONTRACT_ID,
        launch_records.LAUNCH_RECORD_CONTRACT_ID,
        launch_records.EVIDENCE_CONTRACT_ID,
    ):
        assert contract in ADR_TEXT
    assert launch_records.VERIFICATION_IDENTITY_PREFIX == "verify-" and "`verify-`" in ADR_TEXT
    # The correction cycle's contracts (ADR s.10): the specification, the reservation, the
    # task-definition evidence and the bound equivalence.
    from kalpamani.data.production.sharadar import launch_store

    assert launch_records.SPECIFICATION_CONTRACT_ID in ADR_TEXT
    assert launch_store.RESERVATION_CONTRACT_ID in ADR_TEXT
    assert "kalpamani-isolation-verdict/v1" in ADR_TEXT
    assert "specification_digest" in launch_records._AUTHORIZATION_FIELDS
    assert "O_CREAT | O_EXCL" in ADR_TEXT and "os.replace" in ADR_TEXT
    assert "never deleted and never expires" in ADR_PLAIN
    assert "--recover" in ADR_TEXT and "refused_recovery_pending" in ADR_TEXT
    assert "ecs:DescribeTaskDefinition" in ADR_TEXT and "not added" in ADR_PLAIN
    for name in launch_records.TASK_DEFINITION_SHARED_FIELDS:
        assert name in launch_records.TaskDefinitionEvidence.__dataclass_fields__
    assert "differ by design" in ADR_PLAIN and "never runtime proof" in ADR_PLAIN
    assert "## 10. Corrections after the independent review of PR #104" in ADR_TEXT
    # The second cycle: reservations anchored to the ledger, the verdict bound to the recorded
    # placement, the trust boundary stated as the owner's private root.
    assert (
        launch_store.RESERVATIONS_SUFFIX == ".reservations" and launch_store.LOCK_SUFFIX == ".lock"
    )
    assert "`<ledger>.reservations/<identity>.json`" in ADR_TEXT and "`<ledger>.lock`" in ADR_TEXT
    assert "Path.resolve" in ADR_TEXT and "evidence destination" in ADR_PLAIN
    assert launch_store.LEGACY_RESERVATIONS_DIRECTORY == "reservations"
    assert "refused_legacy_reservations" in ADR_TEXT
    assert "reads, moves, migrates and deletes none of them" in ADR_PLAIN
    assert (
        launch_store.StoreDefect.LEGACY_RESERVATIONS_PRESENT.value == "LEGACY_RESERVATIONS_PRESENT"
    )
    assert "specification" in launch_store._RESERVATION_FIELDS
    assert {"security_group_ids", "specification_digest"} <= launch_records._LAUNCH_RECORD_FIELDS
    assert "The verdict's security\ngroups are the record's" in ADR_TEXT
    assert "never a freshly\nsupplied launch-inputs file's" in ADR_TEXT
    assert "The trust boundary is the\nowner's private root" in ADR_TEXT
    assert "does not claim that a stored digest protects against its own author" in ADR_PLAIN
    assert callable(launch_records.parse_specification)
    assert launch_records.MAX_AUTHORIZATION_VALIDITY.total_seconds() == 24 * 3600
    assert "at most 24 hours" in ADR_PLAIN
    assert {m.value for m in launch_records.LedgerEvidence} == {
        "EXIT_CODE_ONLY",
        "RECEIPT_VERIFIED",
    }
    assert {m.value for m in launch_records.EquivalenceVerdict} == {
        "EQUIVALENT",
        "UNREADABLE",
        "TARGET_MISMATCH",
        "ENTRY_MISMATCH",
        "CODE_DIFFERS",
        "ORIGIN_DIFFERS",
        "TASK_DEFINITION_DIFFERS",
        "EVIDENCE_MISSING",
    }
    for verdict in launch_records.EquivalenceVerdict:
        if verdict is not launch_records.EquivalenceVerdict.EQUIVALENT:
            assert verdict.value in ADR_TEXT
    for actor in ProductionActor:
        assert constants_for(actor).launcher_profile.endswith("-launcher")
    assert "launcher_profile" in ADR_TEXT
    assert "an identity in the ledger is consumed for both kinds" in ADR_PLAIN
    assert "No RunTask is ever retried" in ADR_PLAIN
    assert "is recorded as G-4, unchanged" in ADR_PLAIN


def test_the_launch_script_refuses_by_default_and_names_its_flag() -> None:
    source = LAUNCH_SCRIPT.read_text(encoding="utf-8")
    assert "--i-am-the-owner-authorizing-one-launch" in source
    assert "scripts/production_launch.py" in ADR_TEXT
    # The SDK is imported exactly once, inside the real client factory, and every session
    # is pinned to a profile; the constructor itself is named only by the guards that
    # forbid it elsewhere (the docs audit and the binding-preflight test).
    assert source.count("import boto3") == 1 and "profile_name=profile" in source
    assert "_Boto3Clients" in source
    for refused in ("--run", "--live", "--execute", "--force", "--retry", "--aws-profile"):
        assert f'"{refused}"' in source


def test_the_terraform_digest_keys_and_the_run_task_shape_match_the_document() -> None:
    variables = (INFRA / "production_variables.tf").read_text(encoding="utf-8")
    for key in ("acquisition_verify", "build_verify"):
        assert key in variables and key in ADR_TEXT
    policies = (INFRA / "production_policies.tf").read_text(encoding="utf-8")
    for actor_td in ("production_acquire", "production_build"):
        assert f"aws_ecs_task_definition.{actor_td}_verify[*].arn" in policies
    assert "concat" in ADR_PLAIN and "never a wildcard" in ADR_PLAIN
    assert "touches no assignment" in ADR_PLAIN


def test_the_amendments_table_names_every_amended_text() -> None:
    assert "## 8. Amendments stated" in ADR_TEXT
    for reference in (
        f"ADR-0043 {SECTION}2",
        f"ADR-0036 {SECTION}2.9",
        f"ADR-0036 {SECTION}3",
        f"ADR-0036 {SECTION}2.6",
        f"ADR-0036 {SECTION}2.12",
        f"ADR-0044 {SECTION}2",
        f"ADR-0044 {SECTION}4",
    ):
        assert reference in ADR_TEXT, reference
    assert "No accepted document is edited" in ADR_PLAIN
    assert "## 7. Decision" in ADR_TEXT and "re-verification" in ADR_PLAIN
    assert "A stage-b digest rotation therefore requires no re-verification" in ADR_PLAIN
