"""Proposed ADR-0048 says what the code does, and the code says the same.

The two mechanisms it delivers (the permission-probe entry, the held ExecuteCommand check), the
contracts and vocabularies it adds, the layers the catalogue now carries, the deletion path it
designs and does not open, the declarations it amends, and the status register.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from kalpamani.data.production.sharadar import entry
from kalpamani.data.production.sharadar import permission_cells as pc
from kalpamani.data.production.sharadar import permission_probe as pp
from kalpamani.data.production.sharadar import receipts as pr
from kalpamani.data.production.sharadar.compiled import ENTRY_FIELDS
from kalpamani.data.production.sharadar.inputs import LEDGER_OUTCOME_PROBED, LEDGER_OUTCOMES
from kalpamani.data.production.sharadar.launch_records import LaunchKind, identity_kind
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = REPO_ROOT / "docs" / "decisions"
ADR: Final = (
    DECISIONS
    / "ADR-0048-permission-probe-tasks-held-execute-command-and-the-deletion-rehearsal-path.md"
)
ADR_TEXT: Final = ADR.read_text(encoding="utf-8")
ADR_PLAIN: Final = " ".join(ADR_TEXT.split()).replace("**", "").replace("`", "")
INFRA: Final = REPO_ROOT / "infra" / "aws" / "research-data-plane"
PROPOSED: Final = (
    "PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is"
)
HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
TWELVE_DIGITS: Final = re.compile(r"\b[0-9]{12}\b")


def test_the_adr_exists_is_proposed_and_names_its_gates() -> None:
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0048-*.md"))] == [ADR.name]
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "Acceptance authorizes no execution" in ADR_PLAIN
    assert "acceptance grants no permission" in ADR_PLAIN
    assert "## 7. Effectiveness and execution gates" in ADR_TEXT
    assert "Nothing was run to produce this decision" in ADR_PLAIN
    assert "Mocked results are not AWS verification" in ADR_PLAIN
    assert "G2 stays OPEN, CONTROL stays DEFERRED, Phase 3 stays NOT COMPLETE" in ADR_PLAIN
    assert "not to be rewritten as though this decision had authority" in ADR_PLAIN
    assert "The deletion rehearsal path stays a separate decision" in ADR_PLAIN


def test_the_entries_families_and_contracts_match_the_document() -> None:
    assert entry.PROBE_ENTRIES == {entry.TaskEntry.ACQUISITION_PROBE, entry.TaskEntry.BUILD_PROBE}
    for member in entry.PROBE_ENTRIES:
        assert member.value in ADR_TEXT
        assert (
            entry.entry_family(member) == constants_for(entry.ENTRY_ACTOR[member]).probe_task_family
        )
        assert entry.entry_family(member) == member.value
        assert ENTRY_FIELDS[member] == ENTRY_FIELDS[entry.TaskEntry.ACQUISITION] - {
            "secret_name",
            "origin_addresses",
        }
    for actor in ProductionActor:
        assert constants_for(actor).probe_task_family in ADR_TEXT
    assert {entry.EXIT_STATUS[o] for o in entry.PROBE_OUTCOMES} == {41, 42, 43, 44}
    for code in ("41", "42", "43", "44"):
        assert code in ADR_TEXT
    assert pp.PROBE_INPUT_CONTRACT_ID in ADR_TEXT and pr.RECEIPT_CONTRACT_ID in ADR_TEXT
    assert pr.RECEIPT_CONTRACT_ID == "kalpamani-task-receipt/v3" and pr.RECEIPT_SCHEMA_VERSION == 3
    assert pp.PROBE_HOLD_CEILING_SECONDS == 600 and "600 s" in ADR_PLAIN
    assert "hold_seconds = 180" in ADR_PLAIN
    assert (
        LaunchKind.PERMISSION_PROBE.value == "permission-probe" and "permission-probe" in ADR_TEXT
    )
    assert identity_kind("probe-20260915T000000Z-abcd") is LaunchKind.PERMISSION_PROBE
    assert LEDGER_OUTCOME_PROBED in LEDGER_OUTCOMES and "PROBED" in ADR_TEXT
    assert pr.LEDGER_OUTCOME_OF[entry.TaskOutcome.PROBE_HELD] == "PROBED"
    for token in (
        "interactive: true",
        "startedBy",
        "AccessDeniedException",
        "UnauthorizedOperation",
    ):
        assert token in ADR_TEXT, token
    assert "permission_probe" in ADR_TEXT and "while_running" in ADR_TEXT
    assert "--complete-subcell" in ADR_TEXT and "AWAITING_RECEIPT" in ADR_TEXT
    assert "fake HTTP 200 had accepted" in ADR_PLAIN


def test_the_corrections_are_stated_and_the_code_carries_them() -> None:
    """Correction 1: the reservation before RunTask, recovery, the complete evidence
    binding, the held-task precondition -- each named in the ADR and present in the code."""
    from kalpamani.data.production.sharadar.launch_records import (
        PROBE_STARTED_BY_PREFIX,
        probe_specification,
    )
    from kalpamani.data.production.sharadar.launcher import (
        HELD_READY_CEILING_SECONDS,
        HELD_READY_POLL_INTERVAL_SECONDS,
        HeldTask,
    )
    from kalpamani.data.production.sharadar.outcomes import HeldCheckOutcome

    assert "## 8. Corrections after review" in ADR_TEXT
    for token in (
        "--recover-probe-launch",
        "kalpamani-launch-reservation/v1",
        "kalpamani-probe-receipt-evidence/v1",
        "kalpamani-held-task-evidence/v1",
        "held-task precondition",
        "re-verified on every read",
        "No post-launch record is needed",
        "Completion is repeatable",
        "evaluation-order limitation",
    ):
        assert token in ADR_PLAIN, token
    assert pc.PROBE_RECEIPT_CONTRACT_ID == "kalpamani-probe-receipt-evidence/v1"
    assert pc.HELD_TASK_CONTRACT_ID == "kalpamani-held-task-evidence/v1"
    assert callable(probe_specification) and PROBE_STARTED_BY_PREFIX == "kalpamani-permission-"
    assert HELD_READY_POLL_INTERVAL_SECONDS == 5.0 and HELD_READY_CEILING_SECONDS == 120.0
    assert "at 5 s intervals for at most 120 s" in ADR_PLAIN
    assert HELD_READY_CEILING_SECONDS < pp.PROBE_HOLD_CEILING_SECONDS
    for member in HeldCheckOutcome:
        if member is not HeldCheckOutcome.NOT_APPLICABLE and member is not HeldCheckOutcome.INVOKED:
            assert member.value in ADR_TEXT, member
    assert HeldTask.__slots__  # the fresh description is a closed value
    for defect in (
        pc.ChainDefect.LAUNCH_MISSING,
        pc.ChainDefect.LAUNCH_DUPLICATE,
        pc.ChainDefect.LAUNCH_UNBOUND,
        pc.ChainDefect.LEDGER_MISMATCH,
        pc.ChainDefect.RECEIPT_INVALID,
        pc.ChainDefect.HELD_TASK_NOT_RUNNING,
    ):
        assert defect.value in pc.ChainDefect.__members__
    assert "'--recover-probe-launch'" in (
        REPO_ROOT / "scripts" / "production_permission_cells.py"
    ).read_text(encoding="utf-8").replace('"', "'")


def test_the_layers_and_counts_are_the_catalogue_s() -> None:
    by_layer = {layer: sum(1 for s in pc.SUBCELLS if s.layer is layer) for layer in pc.Layer}
    assert len(pc.SUBCELLS) == 98
    assert by_layer == {
        pc.Layer.L3_RUNTIME: 56,
        pc.Layer.L3_BY_R1: 6,
        pc.Layer.L3_TASK: 32,
        pc.Layer.L3_HELD_TASK: 2,
        pc.Layer.BLOCKED: 2,
    }
    assert "56 / 6 / 32 / 2 / 2" in ADR_PLAIN
    for layer, count in by_layer.items():
        assert f"| `{layer.value}` | {count} |" in ADR_TEXT, layer
    held = [s for s in pc.SUBCELLS if s.layer is pc.Layer.L3_HELD_TASK]
    assert all(s.operation is pc.Operation.ECS_EXECUTE_COMMAND for s in held)
    blocked = [s for s in pc.SUBCELLS if s.layer is pc.Layer.BLOCKED]
    assert all(s.principal is pc.Principal.DELETION_ROLE for s in blocked)
    assert all(s.blocked_on == pc.DELETION_DEPENDENCY for s in blocked)
    assert (
        "governance decision" in pc.DELETION_DEPENDENCY and "ADR-0048 s.4" in pc.DELETION_DEPENDENCY
    )
    assert pc.SubcellStatus.AWAITING_RECEIPT.value in ADR_TEXT


def test_the_deletion_path_is_designed_and_not_opened() -> None:
    assert "## 4. Proposed and not opened" in ADR_TEXT
    for token in (
        "kalpamani-deletion-rehearsal",
        "KalpaManiDeletionRehearse",
        "no human assumes the deletion role",
        "Not implemented here",
        "ADR-0007",
    ):
        assert token in ADR_PLAIN, token
    # Nothing of it exists in code or declarations.
    assert not hasattr(ProductionActor, "DELETION")
    for path in INFRA.glob("*.tf"):
        text = path.read_text(encoding="utf-8")
        assert "deletion-rehearsal" not in text and "DeletionRehearse" not in text, path.name


def test_the_declarations_carry_the_probe_families_and_nothing_wider() -> None:
    compute = (INFRA / "production_compute.tf").read_text(encoding="utf-8")
    policies = (INFRA / "production_policies.tf").read_text(encoding="utf-8")
    variables = (INFRA / "production_variables.tf").read_text(encoding="utf-8")
    for actor in ProductionActor:
        family = constants_for(actor).probe_task_family
        assert f'command   = ["{family}"]' in compute
    assert (
        "production_acquire_probe_container" in compute
        and "production_build_probe_container" in compute
    )
    assert "aws_ecs_task_definition.production_acquire_probe[*].arn" in policies
    assert "aws_ecs_task_definition.production_build_probe[*].arn" in policies
    assert '"acquisition_probe", "build_probe"' in variables
    assert (
        "production_acquire_probe_count" in variables
        and "production_build_probe_count" in variables
    )
    # The launcher keeps its explicit ExecuteCommand deny; no permission set is added.
    assert policies.count('"ecs:ExecuteCommand",') >= 2
    assert "KalpaManiDeletionRehearse" not in policies


def test_the_status_register_carries_the_proposal() -> None:
    for name in ("CLAUDE.md", "README.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert ADR.name in text
        assert "ADR-0048 permission-probe tasks + held ExecuteCommand (code):" in text
        assert "ADR-0048 PROPOSED, NOT IN FORCE" in text
        assert "the deletion rehearsal path designed and NOT opened" in text
    readiness = (REPO_ROOT / "docs" / "operations" / "production-readiness.md").read_text(
        encoding="utf-8"
    )
    assert "## 12. The mechanisms cycle" in readiness
    dispositions = (
        REPO_ROOT / "docs" / "operations" / "production-readiness-dispositions.md"
    ).read_text(encoding="utf-8")
    assert "## F-12 — the permission-probe tasks and the held ExecuteCommand check" in dispositions


def test_the_adr_names_no_real_value() -> None:
    assert not HEX_64.search(ADR_TEXT)
    assert not TWELVE_DIGITS.search(ADR_TEXT)
    assert "arn:aws:" not in ADR_TEXT
