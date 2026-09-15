"""ADR-0050 says what the code and the declaration do, and they say the same.

Decision D-1 made concrete and not taken; the rehearsal task, launcher, completion and the tool's
modes it integrates offline; the inert declaration; the owner checklist; the status register.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import production_deletion_rehearsal_tool as rehearsal_tool
from test_production_permission_cells import tool as cells

from kalpamani.data.production.sharadar import deletion_rehearsal as dr
from kalpamani.data.production.sharadar import deletion_rehearsal_launch as dl
from kalpamani.data.production.sharadar import deletion_rehearsal_task as dt
from kalpamani.data.production.sharadar import permission_cells as pc
from kalpamani.data.production.sharadar.permission_cells import SUBCELL_BY_ID, Layer

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = REPO_ROOT / "docs" / "decisions"
ADR: Final = (
    DECISIONS / "ADR-0050-deletion-rehearsal-decision-made-concrete-and-offline-integration.md"
)
ADR_TEXT: Final = ADR.read_text(encoding="utf-8")
ADR_PLAIN: Final = " ".join(ADR_TEXT.split()).replace("**", "").replace("`", "")
INFRA: Final = REPO_ROOT / "infra" / "aws" / "research-data-plane"
CHECKLIST: Final = REPO_ROOT / "docs" / "operations" / "production-owner-checklist.md"
PROPOSED: Final = (
    "PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is"
)
TWELVE_DIGITS: Final = re.compile(r"\b[0-9]{12}\b")


def test_the_adr_exists_is_proposed_and_takes_no_decision() -> None:
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0050-*.md"))] == [ADR.name]
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "Acceptance decides D-1 in neither direction" in ADR_PLAIN
    assert "This ADR's acceptance does not take D-1" in ADR_PLAIN
    assert "Nothing was run to produce this decision" in ADR_PLAIN
    assert "## 7. Effectiveness and execution gates" in ADR_TEXT
    assert "G2 stays OPEN, CONTROL stays DEFERRED, Phase 3 stays NOT COMPLETE" in ADR_PLAIN
    assert "not to be rewritten as though this decision had authority" in ADR_PLAIN
    # The decision is presented verbatim, for a signature outside the repository.
    assert "### 2.11 The decision presented" in ADR_TEXT
    assert "Accepted / Declined" in ADR_TEXT and "outside this repository" in ADR_PLAIN
    for heading in (
        "### 2.2 Resources and permissions introduced",
        "### 2.3 Who launches, and which role deletes",
        "### 2.4 How the target is restricted to the one synthetic object",
        "### 2.5 How production and unrelated resources are excluded",
        "### 2.6 Operation limits",
        "### 2.7 Interruption handling",
        "### 2.8 Cleanup",
        "### 2.9 Residual risk the owner accepts by taking D-1",
        "### 2.10 What acceptance enables, and what still needs its own authorization",
    ):
        assert heading in ADR_TEXT, heading
    assert TWELVE_DIGITS.search(ADR_TEXT) is None


def test_the_path_stays_closed_and_the_declaration_inert() -> None:
    assert dr.REHEARSAL_PATH_OPEN is False and dr.rehearsal_blocked()
    for subcell_id in dr.REHEARSAL_SEQUENCE:
        assert SUBCELL_BY_ID[subcell_id].layer is Layer.BLOCKED
    assert "REHEARSAL_PATH_OPEN is False" in ADR_PLAIN
    assert "deletion_rehearsal_open is false" in ADR_PLAIN
    variables = (INFRA / "production_variables.tf").read_text(encoding="utf-8")
    block = variables.split('variable "deletion_rehearsal_open"')[1]
    assert "default     = false" in block
    declaration = (INFRA / "production_deletion_rehearsal.tf").read_text(encoding="utf-8")
    assert "production_deletion_rehearsal.tf" in ADR_TEXT
    for token in (
        dr.REHEARSAL_FAMILY,
        dr.REHEARSAL_ENTRY,
        dr.REHEARSAL_CONTAINER,
        dr.REHEARSAL_STREAM_PREFIX,
        dr.REHEARSAL_LAUNCHER_PERMISSION_SET,
        dr.REHEARSAL_BINDING_PARAMETER,
        dr.REHEARSAL_BINDING_CONTRACT_ID,
        dt.REHEARSAL_BINDING_KIND,
    ):
        assert token in declaration and token in ADR_TEXT, token
    assert "aws_iam_role.licensed_data_deletion" in declaration
    assert "actual deletion role" in ADR_PLAIN
    assert "not by IAM" in ADR_PLAIN or "not IAM" in ADR_PLAIN


def test_the_contracts_and_bounds_match_the_text() -> None:
    for token in (
        dt.REHEARSAL_INPUT_CONTRACT_ID,
        dt.REHEARSAL_RELEASE_CONTRACT_ID,
        dt.REHEARSAL_RECEIPT_CONTRACT_ID,
        dl.REHEARSAL_LAUNCH_INPUTS_CONTRACT_ID,
        dl.REHEARSAL_RESERVATION_CONTRACT_ID,
        dl.REHEARSAL_LAUNCH_RECORD_CONTRACT_ID,
        dl.REHEARSAL_RESOLUTION_CONTRACT_ID,
        dl.REHEARSAL_RECEIPT_EVIDENCE_CONTRACT_ID,
        dl.REHEARSAL_RESERVATIONS_ANCHOR,
        dl.REHEARSAL_RESOLUTIONS_ANCHOR,
        dl.RECOVERED_INTERRUPTED,
        dr.REHEARSAL_STATEMENT_CONTRACT_ID,
        dr.REHEARSAL_LAUNCHER_PROFILE,
        dr.REHEARSAL_CONSUMPTION_KIND,
    ):
        assert token in ADR_TEXT, token
    assert dt.REHEARSAL_EXIT_STATUS[dt.RehearsalTaskOutcome.REHEARSED] == 50
    assert (
        "50 REHEARSED, 51" in ADR_PLAIN and "58 the refusals in order, 59 unclassified" in ADR_PLAIN
    )
    assert dt.MAX_RELEASE_READS == 60 and dt.RELEASE_CEILING_SECONDS == 300.0
    assert "60 release reads within 300 s at 5 s polls" in ADR_PLAIN
    assert dl.MAX_OBSERVATION_READS == 120 and dl.OBSERVATION_CEILING_SECONDS == 600.0
    assert "120 DescribeTasks reads within 600 s at 5 s polls" in ADR_PLAIN
    assert "one RunTask, never retried" in ADR_PLAIN
    for outcome in dl.RehearsalLaunchOutcome:
        assert outcome.value in ADR_TEXT, outcome
    for defect in dl.RehearsalCompletionDefect:
        assert defect.value in ADR_TEXT, defect
    # Correction 1: the anchored states, the binding defects and the accepted cleanup rule.
    for state in dl.RehearsalTaskState:
        assert state.value in ADR_TEXT, state
    for binding_defect in dl.RehearsalBindingDefect:
        assert binding_defect.value in ADR_TEXT, binding_defect
    assert "## 8. Corrections after review (correction 1; the ADR stays PROPOSED)" in ADR_TEXT
    assert "A listing that finds nothing settles nothing" in ADR_PLAIN
    assert "CLEANUP_STARTED_BY_PREFIXES" in ADR_TEXT and pc.CLEANUP_STARTED_BY_PREFIXES == (
        "kalpamani-permission-",
        dl.REHEARSAL_STARTED_BY_PREFIX,
    )
    assert dt.RehearsalTaskOutcome.REFUSED_TARGET.value in ADR_TEXT
    assert "kalpamani-rehearsal-<stamp>" in ADR_TEXT and dl.REHEARSAL_STARTED_BY_PREFIX == (
        "kalpamani-rehearsal-"
    )


def test_the_tool_modes_and_exits_match_the_text() -> None:
    for mode in (
        "--prepare-rehearsal",
        "--rehearse-deletion",
        "--collect-rehearsal-receipt",
        "--complete-rehearsal",
        "--rehearsal-inputs",
        "--recover-rehearsal-launch",
        "--acknowledge-collection-contradiction",
    ):
        assert mode in ADR_TEXT, mode
    for exit_code, sentence in (
        (cells.EXIT_REFUSED_RECOVERY_PENDING, "recovery pending 21"),
        (cells.EXIT_REFUSED_RESERVATION, "reserved 22"),
        (cells.EXIT_REFUSED_RECOVERY, "nothing to recover 23"),
        (cells.EXIT_COMPLETION_RECORDED, "rehearsal_completion_recorded, 24"),
    ):
        assert str(exit_code) in sentence and sentence in ADR_PLAIN, sentence
    assert rehearsal_tool.EXIT_REHEARSAL_NOT_LAUNCHED == 31 and "exits 31" in ADR_PLAIN
    assert rehearsal_tool.EXIT_REFUSED_REHEARSAL_RECORDS == 32 and "(32)" in ADR_PLAIN
    assert "exits 27" in ADR_PLAIN or "exit 27" in ADR_PLAIN
    for key in ("rehearsal_not_launched", "refused_rehearsal_records"):
        assert key in rehearsal_tool.SENTENCES


def test_the_checklist_exists_marks_every_value_missing_and_takes_no_decision() -> None:
    text = CHECKLIST.read_text(encoding="utf-8")
    for heading in (
        "## 1. Before local image preparation",
        "## 2. Before publication or infrastructure change",
        "## 3. Before verification launches and collection",
        "## 4. Before the first production acquisition and build",
    ):
        assert heading in text, heading
    assert "Every private value is MISSING" in text
    assert "D-1 not taken" in text or "D-1 **not taken**" in text
    assert TWELVE_DIGITS.search(text) is None
    assert "production-owner-checklist.md" in ADR_TEXT
    assert "MISSING" in text and "after S" in text


def test_the_status_register_carries_the_proposal() -> None:
    for name in ("CLAUDE.md", "README.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert ADR.name in text
        assert "ADR-0050 deletion rehearsal readiness (code + declaration):" in text
        assert "ADR-0050 PROPOSED, NOT IN FORCE" in text
        assert "ADR-0049 ACCEPTED / IN FORCE" in text
        assert "NOT TAKEN" in text
    readiness = (REPO_ROOT / "docs" / "operations" / "production-readiness.md").read_text(
        encoding="utf-8"
    )
    assert "## 14. The deletion-rehearsal readiness cycle" in readiness
    dispositions = (
        REPO_ROOT / "docs" / "operations" / "production-readiness-dispositions.md"
    ).read_text(encoding="utf-8")
    assert "## F-14 — the deletion rehearsal made concrete" in dispositions
    assert "Correction 1 (PR #109 review; ADR-0050 §8)" in dispositions
    assert "### 14.2 Implemented offline (never run)" in readiness
    assert "--recover-rehearsal-launch" in readiness
    inputs = (REPO_ROOT / "docs" / "operations" / "production-owner-inputs.md").read_text(
        encoding="utf-8"
    )
    assert "production-owner-checklist.md" in inputs and "proposed ADR-0050" in inputs
