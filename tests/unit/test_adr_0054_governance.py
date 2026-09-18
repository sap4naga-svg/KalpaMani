"""ADR-0054: proposed, the owner's two decisions verbatim, and the tooling says the same.

The evidence-only v1 reservation read, the registration-historical rebinding rule, the
amendment sections of ADR-0052, ADR-0045 and ADR-0046, the register rows and the audit registry.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import phase3_docs_audit as audit
import production_verification_cells as runner

from kalpamani.data.production.sharadar import launch_records as lr
from kalpamani.data.production.sharadar import launch_store as ls
from kalpamani.data.production.sharadar import verification_cells as vc

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = REPO_ROOT / "docs" / "decisions"
ADR: Final = (
    DECISIONS / "ADR-0054-historical-v1-reservations-and-registration-historical-rebinding.md"
)
ADR_TEXT: Final = ADR.read_text(encoding="utf-8")
PROPOSED: Final = (
    "PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is"
)
MERGE_COMMIT: Final = "8be462b953c33a6953429ee9edc321f843ab6ae1"
ACCEPTED_CLAUSE: Final = (
    "ADR-0054 is therefore ACCEPTED / IN FORCE exactly as the clause above states"
)
SINCE_ACCEPTED: Final = "Since accepted: ADR-0054 is ACCEPTED / IN FORCE on the merge of PR #135"
APPROVED_HEAD: Final = "bbaa419dea40f53040f2d228d25fc1eb631b713c"
TWELVE_DIGITS: Final = re.compile(r"\b[0-9]{12}\b")
DECISION_ONE: Final = (
    "A supported, integrity-valid v1 reservation may be read by pagination-v2 workstation tooling "
    "solely to preserve and classify historical evidence. It must never become current launch "
    "authority or bypass the v2 parser."
)
DECISION_TWO: Final = (
    "A verification cell whose prior bound launch is runner-derived HISTORICAL solely because it "
    "belongs to a different registration may receive a fresh identity and specification. The prior "
    "binding, launch, reservation, ledger row and receipt must remain preserved and auditable. A "
    "current, prepared, unlaunched, malformed or otherwise non-historical binding may not be "
    "replaced."
)
PROPOSED_SECTION: Final = (
    "PROPOSED — NOT IN FORCE while the pull request carrying this section is open"
)
AMENDED: Final = {
    "ADR-0052-dedicated-r2-corroboration-cell.md": (
        "## 6. Amendment (2026-09-18) — registration-historical rebinding (ADR-0054)"
    ),
    "ADR-0045-verification-entries-observation-build-and-launch-tool.md": (
        "## 14. Amendment (2026-09-18) — the store reads supported v1 reservations as evidence"
    ),
    "ADR-0046-verification-tooling-materializer-r3-tool-and-cell-runner.md": (
        "## 8. Amendment (2026-09-18) — `HISTORICAL` from a historical reservation's chain"
    ),
}


def _plain(text: str) -> str:
    # Blockquote markers are layout, not text: the owner's decisions are quoted verbatim.
    lines = (line[2:] if line.startswith("> ") else line for line in text.splitlines())
    return " ".join(" ".join(lines).split()).replace("**", "").replace("`", "")


ADR_PLAIN: Final = _plain(ADR_TEXT)


def test_the_adr_exists_is_proposed_and_authorizes_nothing() -> None:
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0054-*.md"))] == [ADR.name]
    assert PROPOSED in ADR_TEXT  # the historical clause stays
    assert ACCEPTED_CLAUSE in ADR_PLAIN
    assert MERGE_COMMIT in ADR_TEXT and APPROVED_HEAD in ADR_TEXT
    assert "acceptance authorizes only the supported-v1 historical read" in ADR_PLAIN
    assert "Acceptance authorizes no execution" in ADR_PLAIN
    assert "Acceptance authorizes nothing that runs" in ADR_PLAIN
    assert "Mocked results are not AWS verification" in ADR_PLAIN
    assert "Nothing was run against AWS to produce this decision" in ADR_PLAIN
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    for private in ("arn:aws", "eni-0", "nip-0", "nia-0", "C:\\Users", "sap4n"):
        assert private not in ADR_TEXT, private


def test_the_owners_two_decisions_are_recorded_verbatim() -> None:
    assert DECISION_ONE in ADR_PLAIN
    assert DECISION_TWO in ADR_PLAIN


def test_the_decision_names_the_rules_the_tooling_implements() -> None:
    for phrase in (
        "The strict v2 grammar is unchanged",
        "never recompiled",
        "refused WORKLOAD_CURRENT",
        "RESERVATION_ORPHANED",
        "There is no identity or filename special-casing",
        "Original bytes are never rewritten, moved or upgraded",
        "never PASSED",
        "exactly one exception",
        "A PREPARED (unlaunched) binding is not replaceable",
        "Preservation is part of the write, not a courtesy",
        "Write ordering is recoverable",
        "The rule is generic",
        "No task entry imports the changed modules",
        "no rebuild, republication, plan, apply or re-registration follows from it",
    ):
        assert phrase in ADR_PLAIN, phrase
    assert "kalpamani-production-acquisition-plan/v1" in ADR_TEXT
    assert "refused_rebinding" in ADR_TEXT and "exit 15" in ADR_TEXT
    assert ".cells.superseded-" in ADR_TEXT


def test_the_tooling_carries_what_the_decision_states() -> None:
    assert lr.SUPERSEDED_WORKLOAD_CONTRACT_ID == "kalpamani-production-acquisition-plan/v1"
    assert lr.LaunchRecordDefect.WORKLOAD_CURRENT.value == "WORKLOAD_CURRENT"
    assert ls.StoreDefect.RESERVATION_ORPHANED.value == "RESERVATION_ORPHANED"
    assert callable(lr.parse_historical_specification)
    assert callable(ls.parse_reservation_for_evidence)
    for name in ("HistoricalSpecification", "parse_historical_specification"):
        assert name in lr.__all__
    for name in ("HistoricalReservation", "parse_reservation_for_evidence"):
        assert name in ls.__all__
    assert "SupersededBinding" in vc.__all__
    assert vc.SupersededBinding.__dataclass_fields__.keys() >= {
        "identity",
        "specification_digest",
        "reservation_sha256",
        "cells_document_sha256",
        "registration_sha256",
        "superseded_at",
    }
    assert runner.EXIT_REFUSED_REBINDING == 15
    assert "refused_rebinding" in runner.SENTENCES
    assert runner.CELLS_SUPERSEDED_INFIX == ".cells.superseded-"
    # The launch tool's execution surface still reads reservations strictly, and only strictly.
    launch_source = (REPO_ROOT / "scripts" / "production_launch.py").read_text(encoding="utf-8")
    assert "evidence_reservation" not in launch_source
    assert "parse_reservation_for_evidence" not in launch_source
    assert "HistoricalReservation" not in launch_source


def test_every_amended_adr_carries_a_dated_section_naming_adr_0054() -> None:
    for name, heading in AMENDED.items():
        text = (DECISIONS / name).read_text(encoding="utf-8")
        assert heading in text, name
        tail = text.split(heading, 1)[1]
        plain = _plain(tail)
        assert "ADR-0054" in tail, name
        assert PROPOSED_SECTION in plain, name
        assert "preserved as accepted and is not rewritten" in plain, name
        assert SINCE_ACCEPTED in plain, name
        # The historical text above is untouched: the heading appears once, at the end.
        assert text.count(heading) == 1 and text.rstrip().endswith(tail.rstrip()), name
    adr_0052 = _plain((DECISIONS / next(iter(AMENDED))).read_text(encoding="utf-8"))
    assert "A launched binding is never rebound" in adr_0052  # the accepted clause stays
    assert "never a current PASSED" in adr_0052


def test_the_registers_and_the_audit_registry_are_synchronized() -> None:
    assert "ADR-0054" not in audit.PROPOSED_ADR_STATUS
    assert dict(audit.MERGED_ADR_STATUS)["ADR-0054"] == "PR #135 merged"
    owner_inputs = (REPO_ROOT / "docs" / "operations" / "production-owner-inputs.md").read_text(
        encoding="utf-8"
    )
    assert "| D-22 |" in owner_inputs and DECISION_ONE in _plain(owner_inputs)
    readiness = (REPO_ROOT / "docs" / "operations" / "production-readiness.md").read_text(
        encoding="utf-8"
    )
    assert "## 18. The historical-rebinding cycle (2026-09-18)" in readiness
    documents = {
        name: (REPO_ROOT / name).read_text(encoding="utf-8") for name in ("CLAUDE.md", "README.md")
    }
    assert audit._proposed_adr_row_defects(documents) == []
    for name, text in documents.items():
        rows = [line for line in text.splitlines() if "[ADR-0054](docs/decisions/" in line]
        assert len(rows) == 1, name
        assert audit.PROPOSED_ROW_MARK not in rows[0], name
        assert "ACCEPTED / IN FORCE" in rows[0] and "PR #135 merged" in rows[0], name
        assert MERGE_COMMIT in rows[0] and APPROVED_HEAD in rows[0], name
        assert "Deployment impact: none" in rows[0], name
        assert "never becomes a current `PASSED`" in rows[0], name
        assert "ADR-0054 historical v1 reservations + registration-historical rebinding:" in text
        assert "nothing PASSED under the new registration" in text, name
