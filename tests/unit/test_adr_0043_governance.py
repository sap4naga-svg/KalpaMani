"""ADR-0043 governance: the accepted narrow completion fixing the task entrypoint composition.

These checks hold the document to its own claims -- the preserved conditional status and the
merge that satisfied it, the closed entries, the refusal order, what was proposed rather than
decided, the gates -- and hold the offline entrypoints to the shape the document describes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from kalpamani.data.production.sharadar import entry, task_clients, task_metadata

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0043-production-task-entrypoint-composition.md"
README: Final = PROJECT_ROOT / "README.md"
CLAUDE: Final = PROJECT_ROOT / "CLAUDE.md"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""
ADR_FLAT: Final = " ".join(ADR_TEXT.split())
ADR_PLAIN: Final = ADR_FLAT.replace("**", "").replace("`", "")

HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")
REAL_ARN: Final = re.compile(r"\barn:aws\b")
PROPOSED: Final = "PROPOSED " + chr(0x2014) + " NOT IN FORCE"
SECTION: Final = chr(0xA7)


def test_the_adr_exists_and_is_the_only_0043() -> None:
    assert ADR.is_file()
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0043-*.md"))] == [ADR.name]


def test_the_adr_keeps_its_conditional_status_and_records_the_merge() -> None:
    """The pre-merge condition is preserved as written; the note beside it records the event."""
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "The condition above has since been satisfied." in ADR_FLAT
    assert "PR #100 merged" in ADR_FLAT and "2026-09-12T19:55:44Z" in ADR_FLAT
    assert "2b956c05d1aa171b571f6739d3d5756a00479847" in ADR_TEXT
    assert "9d2bacc0095ad540bfc5b0bc351f51bfb09582dc" in ADR_TEXT
    assert "59f814ede3410a12eb84c7e02871886ec6116d17" in ADR_TEXT
    assert "entrypoint-composition decision is therefore ACCEPTED / IN FORCE" in ADR_PLAIN
    assert f"Its {SECTION}3 and {SECTION}4 were not decided by that merge" in ADR_PLAIN
    assert "resolved" in ADR_PLAIN and "ADR-0044" in ADR_TEXT
    assert "Acceptance authorizes no execution." in ADR_PLAIN
    assert f"a narrow completion of ADR-0036 {SECTION}2.9 and {SECTION}2.12" in ADR_FLAT
    assert "Nothing was run to produce this decision" in ADR_FLAT
    assert "## 6. Effectiveness and execution gates" in ADR_TEXT
    assert (
        "acceptance authorizes no image build, no image publication, no task launch, no run"
        in ADR_FLAT
    )
    assert "The entrypoint has never been run" in ADR_FLAT


def test_the_adr_distinguishes_decided_from_proposed() -> None:
    assert (
        f"Its {SECTION}3 and {SECTION}4 record proposals the owner has not decided; "
        "acceptance of this ADR decides neither" in ADR_PLAIN
    )
    assert "## 3. Proposed, undecided" in ADR_TEXT and "## 4. Proposed, undecided" in ADR_TEXT
    assert "Nothing here is accepted by accepting this ADR" in ADR_PLAIN
    assert "every defect is UNAVAILABLE, never UNSPENT" in ADR_PLAIN
    assert "widens the task bootstrap policy" in ADR_PLAIN and "is not done here" in ADR_PLAIN
    assert "Neither is chosen here" in ADR_PLAIN
    assert "wired to nothing" in ADR_PLAIN


def test_the_implementation_matches_the_document() -> None:
    # ADR-0043 decided the two production entries. The two verification entries beside
    # them are ADR-0045's and the two probe entries ADR-0048's, not this
    # document's, and each is held by its own test.
    production_entries = {
        e
        for e in entry.TaskEntry
        if e not in entry.VERIFICATION_ENTRIES and e not in entry.PROBE_ENTRIES
    }
    assert {e.value for e in production_entries} == {
        "kalpamani-production-acquire",
        "kalpamani-research-build",
    }
    for name in production_entries:
        assert name.value in ADR_TEXT
    for token in (
        "REFUSED_CONFIGURATION",
        "REFUSED_CREDENTIAL_ENVIRONMENT",
        "REFUSED_ORIGIN",
        "REFUSED_DEPENDENCY",
        "UNCLASSIFIED",
    ):
        assert token in ADR_TEXT and entry.TaskOutcome(token)
    assert entry.EXIT_STATUS[entry.TaskOutcome.REFUSED_ENTRY] == 2
    assert entry.EXIT_STATUS[entry.TaskOutcome.UNCLASSIFIED] == 40
    assert (
        task_metadata.METADATA_HOST == "169.254.170.2" and task_metadata.METADATA_HOST in ADR_TEXT
    )
    assert "2 s; 64 KiB" in ADR_TEXT
    assert task_metadata.METADATA_TIMEOUT_SECONDS == 2.0
    assert task_metadata.MAX_METADATA_BYTES == 64 * 1024
    assert "total_max_attempts 1" in ADR_TEXT
    assert task_clients.client_config_kwargs(task_clients.TaskService.STS)["retries"] == {
        "total_max_attempts": 1,
        "mode": "standard",
    }
    assert "kalpamani_production_compiled" in ADR_TEXT
    assert "kalpamani-spent-identities/v1" in ADR_TEXT


def test_the_adr_carries_no_private_value() -> None:
    assert HEX_64.search(ADR_TEXT) is None
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    assert REAL_ARN.search(ADR_TEXT) is None


@pytest.mark.parametrize("path", [README, CLAUDE])
def test_status_documents_record_the_adr_as_accepted_on_the_merge(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    rows = [
        line
        for line in text.splitlines()
        if line.startswith("| ")
        and "ADR-0043](" in line
        and "production task entrypoint composition" in line.split("|")[1]
    ]
    assert len(rows) == 1
    flat = " ".join(rows[0].replace("**", "").replace("`", "").split())
    assert "ACCEPTED / IN FORCE" in flat and "PR #100 merged 2026-09-12T19:55:44Z" in flat
    assert "2b956c05d1aa171b571f6739d3d5756a00479847" in flat
    assert "while PR #100 was open it was proposed and carried no authority" in flat
    assert (
        "the merge did not decide" in flat
        and "resolved, as a proposal of its own, by ADR-0044" in flat
    )
    assert "acceptance authorized no image, launch or run" in flat
    assert "ADR-0043 (production task entrypoint composition): ACCEPTED / IN FORCE" in text
    assert (
        "ADR-0043 task entrypoints (code):                 "
        "OFFLINE / SYNTHETIC-ONLY / NO IMAGE / NEVER RUN" in text
    )
    assert "production image:                                  NONE" in text
    assert re.search("ADR-0043[^\\n]{0,200}" + re.escape(PROPOSED), text) is None
