"""ADR-0049 says what the code does, and the code says the same.

The bounded receipt collector it delivers (its derived destination, its bounds, its one-attempt
client, its evidence contract), the deletion rehearsal path it implements offline and keeps
closed, the decision it presents and does not take, the permission it records and does not grant,
and the status register.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from kalpamani.data.production.sharadar import deletion_rehearsal as dr
from kalpamani.data.production.sharadar import receipt_collector as rc
from kalpamani.data.production.sharadar.permission_cells import SUBCELL_BY_ID, Layer

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = REPO_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0049-receipt-collection-and-the-deletion-rehearsal-decision.md"
ADR_TEXT: Final = ADR.read_text(encoding="utf-8")
ADR_PLAIN: Final = " ".join(ADR_TEXT.split()).replace("**", "").replace("`", "")
INFRA: Final = REPO_ROOT / "infra" / "aws" / "research-data-plane"
PROPOSED: Final = (
    "PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is"
)
HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
MERGE_COMMIT: Final = "82cae1ebfcc99dbbc53f67e534e4d78ffb914d4a"
APPROVED_HEAD: Final = "9625e241db01b2996fbf9f63814ba3a916a3def7"
TWELVE_DIGITS: Final = re.compile(r"\b[0-9]{12}\b")


def test_the_adr_exists_is_proposed_and_names_its_gates() -> None:
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0049-*.md"))] == [ADR.name]
    # The status line it was authored with is preserved as history; the post-merge note
    # beside it records the acceptance with PR #108's merge evidence.
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "The condition above has since been satisfied" in ADR_PLAIN
    assert "PR #108 merged" in ADR_PLAIN and MERGE_COMMIT in ADR_TEXT and APPROVED_HEAD in ADR_TEXT
    assert "ADR-0049 is therefore ACCEPTED / IN FORCE" in ADR_PLAIN
    assert "Acceptance decided Decision D-1 in neither direction" in ADR_PLAIN
    assert "Acceptance decides §3.8's Decision D-1 in neither direction" in ADR_PLAIN
    assert "Nothing was run to produce this decision" in ADR_PLAIN
    assert "## 5. Effectiveness and execution gates" in ADR_TEXT
    assert "G2 stays OPEN, CONTROL stays DEFERRED, Phase 3 stays NOT COMPLETE" in ADR_PLAIN
    assert "not to be rewritten as though this decision had authority" in ADR_PLAIN


def test_the_collector_bounds_and_contract_match_the_text() -> None:
    assert rc.COLLECT_MAX_PAGES == 16 and "at most 16 pages" in ADR_PLAIN
    assert rc.COLLECT_MAX_REQUESTS == 40 and "40 requests per collection" in ADR_PLAIN
    assert rc.COLLECT_MAX_EVENTS == 20_000 and "20,000 events scanned" in ADR_PLAIN
    assert rc.COLLECT_POLL_SECONDS == 15.0 and "15 s" in ADR_PLAIN
    assert rc.COLLECT_CEILING_SECONDS == 300.0 and "300 s elapsed" in ADR_PLAIN
    # Correction 1: a complete scan, verification before persistence, one admission rule.
    assert "A complete scan, and only a complete scan, establishes one line" in ADR_PLAIN
    assert "verified before anything of it is kept" in ADR_PLAIN
    assert "nothing is chosen by filename order" in ADR_PLAIN
    assert "## 6. Corrections after review" in ADR_TEXT
    for member in rc.CollectionOutcome:
        assert member.value in ADR_TEXT, member
    for defect in rc.CollectionRecordDefect:
        assert defect.value in ADR_TEXT, defect
    assert rc.admit_collection_records.__name__ in ADR_TEXT
    assert rc.parse_collection_record.__name__ in ADR_TEXT
    # Correction 2: a recorded contradiction is never superseded; the disposition is explicit.
    assert rc.DISPOSITION_CONTRACT_ID in ADR_TEXT
    assert "is never superseded" in ADR_PLAIN
    assert "--acknowledge-collection-contradiction" in ADR_TEXT
    for disposition in rc.ContradictionDisposition:
        assert disposition.value in ADR_TEXT, disposition
    # Correction 3: the disposition's receipt binding constrains recovery.
    assert "constrains recovery" in ADR_PLAIN and "refused_receipt_binding" in ADR_TEXT
    assert rc.contradiction_status.__name__ in ADR_TEXT
    assert rc.LOGS_TOTAL_MAX_ATTEMPTS == 1 and "total_max_attempts = 1" in ADR_PLAIN
    assert rc.COLLECTION_CONTRACT_ID == "kalpamani-receipt-collection/v1"
    assert rc.COLLECTION_CONTRACT_ID in ADR_TEXT
    # A caller never names the stream: the destination is derived from the registered block.
    assert "never supplied" in ADR_PLAIN
    assert "the budget was exhausted before a line was obtained" in ADR_PLAIN
    assert "A successful log read is not a successful verification" in ADR_PLAIN


def test_the_permission_is_recorded_and_not_granted() -> None:
    assert "logs:GetLogEvents" in ADR_TEXT
    assert "This ADR grants nothing" in ADR_PLAIN
    policies = (INFRA / "production_policies.tf").read_text(encoding="utf-8")
    assert "logs:GetLogEvents" not in policies
    assert "KalpaManiDeletionRehearse" not in policies
    compute = (INFRA / "production_compute.tf").read_text(encoding="utf-8")
    assert dr.REHEARSAL_FAMILY not in compute
    # Proposed ADR-0050 declares them in their own file, inert behind a variable that is
    # false by default; the actor launchers' logs delta stays undeclared.
    rehearsal = (INFRA / "production_deletion_rehearsal.tf").read_text(encoding="utf-8")
    assert "KalpaManiDeletionRehearse" in rehearsal and "logs:GetLogEvents" in rehearsal
    variables = (INFRA / "production_variables.tf").read_text(encoding="utf-8")
    assert "default     = false" in variables.split('variable "deletion_rehearsal_open"')[1]


def test_the_rehearsal_path_is_closed_and_the_decision_is_presented() -> None:
    assert dr.REHEARSAL_PATH_OPEN is False
    assert dr.REHEARSAL_DECISION == "ADR-0049 D-1"
    assert dr.rehearsal_blocked()
    for subcell_id in dr.REHEARSAL_SEQUENCE:
        cell = SUBCELL_BY_ID[subcell_id]
        assert cell.layer is Layer.BLOCKED
        assert cell.blocked_on is not None and "D-1" in cell.blocked_on
    assert "REHEARSAL_PATH_OPEN = False" in ADR_PLAIN
    assert "### 3.8 Decision D-1" in ADR_TEXT
    assert "This ADR's acceptance does not take D-1" in ADR_PLAIN
    for token in (
        dr.REHEARSAL_FAMILY,
        dr.REHEARSAL_CONTAINER,
        dr.REHEARSAL_STREAM_PREFIX,
        dr.REHEARSAL_LAUNCHER_PERMISSION_SET,
        dr.REHEARSAL_STATEMENT_CONTRACT_ID,
        dr.REHEARSAL_RECORD_CONTRACT_ID,
        dr.REHEARSAL_BINDING_CONTRACT_ID,
    ):
        assert token in ADR_TEXT


def test_the_status_register_carries_the_acceptance() -> None:
    for name in ("CLAUDE.md", "README.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert ADR.name in text
        assert "ADR-0049 receipt collection + deletion rehearsal (code):" in text
        assert "ADR-0049 ACCEPTED / IN FORCE" in text
        assert "ADR-0049 PROPOSED, NOT IN FORCE" not in text
        assert "ADR-0048 ACCEPTED / IN FORCE" in text
        assert "PR #108 merged" in text and MERGE_COMMIT in text
    readiness = (REPO_ROOT / "docs" / "operations" / "production-readiness.md").read_text(
        encoding="utf-8"
    )
    assert "## 13. The collection-and-rehearsal cycle" in readiness
    dispositions = (
        REPO_ROOT / "docs" / "operations" / "production-readiness-dispositions.md"
    ).read_text(encoding="utf-8")
    assert "## F-13 — the receipt collector and the deletion rehearsal" in dispositions
    inputs = (REPO_ROOT / "docs" / "operations" / "production-owner-inputs.md").read_text(
        encoding="utf-8"
    )
    assert "Decision D-1" in inputs and "log_destination" in inputs


def test_the_adr_names_no_real_value() -> None:
    assert not HEX_64.search(ADR_TEXT)
    assert not TWELVE_DIGITS.search(ADR_TEXT)
    # The one ARN shape is the permission's placeholder resource, with no account in it.
    for match in re.finditer(r"arn:aws:[^\s`]*", ADR_TEXT):
        assert "<account>" in match.group(0)
