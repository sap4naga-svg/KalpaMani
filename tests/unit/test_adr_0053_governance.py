"""ADR-0053: accepted on the merge of PR #129, the owner's decision verbatim, nothing qualified.

The dated amendments of ADR-0009, ADR-0041, ADR-0042, ADR-0035, ADR-0040 and ADR-0043, the
owner-input rows, the readiness section, the register rows and the audit's proposed-ADR guard.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import phase3_docs_audit as audit
import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = REPO_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0053-pagination-v2-single-data-page-and-completion-probe.md"
ADR_TEXT: Final = ADR.read_text(encoding="utf-8")
PROPOSED: Final = (
    "PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is"
)
TWELVE_DIGITS: Final = re.compile(r"\b[0-9]{12}\b")
MERGE_COMMIT: Final = "3e8c9cb5c13141c0353d4bb62c3e65c498badf1b"
APPROVED_HEAD: Final = "cef2db911e346630e3d04306c292ffaa389c7429"
OWNER_DECISION: Final = (
    "I accept the R1 + R2 pagination-correction route: governed single-data-page acquisition with "
    "a completion probe, explicit refusal of multi-page data, raised bounded payload/parser "
    "ceilings, full O-5 recompilation, and whole-run replacement of acquisition run 1. Existing "
    "run 1 remains historical evidence; run 2 and S10c remain on hold."
)
AMENDED: Final = {
    "ADR-0009-sharadar-provider-realistic-implementation.md": "## 10. Amendment (2026-09-18)",
    "ADR-0041-production-provider-request-form.md": "## 7. Amendment (2026-09-18)",
    "ADR-0042-build-side-pagination-admission.md": "## 6. Amendment (2026-09-18)",
    "ADR-0035-initial-breakout-long-research-dataset-ingestion-design.md": (
        "## 9. Amendment (2026-09-18)"
    ),
    "ADR-0040-research-build-output-objects-and-manifest.md": "## 5. Amendment (2026-09-18)",
    "ADR-0043-production-task-entrypoint-composition.md": "## 7. Amendment (2026-09-18)",
}


def _plain(text: str) -> str:
    joined = " ".join(line.removeprefix("> ") for line in text.splitlines())
    return " ".join(joined.split()).replace("**", "").replace("`", "")


ADR_PLAIN: Final = _plain(ADR_TEXT)


def test_the_adr_exists_is_proposed_and_authorizes_nothing() -> None:
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0053-*.md"))] == [ADR.name]
    assert PROPOSED in ADR_TEXT  # the historical clause stays
    assert "ACCEPTED / IN FORCE as governance and contract only" in ADR_PLAIN
    assert "ADR-0053 is therefore ACCEPTED / IN FORCE exactly as the clause above" in ADR_PLAIN
    assert MERGE_COMMIT in ADR_TEXT and APPROVED_HEAD in ADR_TEXT
    assert "Acceptance changed nothing that runs and qualified nothing" in ADR_PLAIN
    assert "Acceptance authorizes nothing that runs" in ADR_PLAIN
    for phrase in (
        "no provider qualification request, no implementation, no image build",
        "Nothing was run to produce this decision",
        "none is qualified by this ADR",
        "The next owner decision after this merge is the bounded provider-qualification",
    ):
        assert phrase in ADR_PLAIN, phrase
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    for private in ("arn:aws", "eni-0", "y91xlz15", "licensed/bronze/sharadar/tickers/production"):
        assert private not in ADR_TEXT, private


def test_the_owner_decision_is_recorded_verbatim_with_its_limits() -> None:
    assert OWNER_DECISION in ADR_PLAIN
    for limit in (
        "does not waive completeness, determinism, schema, licensing or evidence requirements",
        "does not declare run 1 buildable",
        "preserves the superseded run-2 specification and its unconsumed identity",
        "keeps runs 2" + chr(0x2013) + "19 and S10c blocked",
    ):
        assert limit in ADR_PLAIN, limit


def test_the_thirteen_point_contract_is_stated() -> None:
    for clause in (
        "Multi-page data is prohibited",
        "exactly one governed data request at limit L",
        "exactly one completion probe at offset L",
        "fewer than, or exactly, L rows",
        "must parse successfully and contain zero data rows",
        "does not publish a COMPLETE locator",
        "retained and hashed",
        "contributes no rows",
        "Schema equality is required",
        "governed primary-key and uniqueness rules",
        "never silently removed",
        "followed by an empty completion probe may be admitted as complete",
        "data-bearing completion probe is refused as truncated",
        "multiple data-bearing pages for one group or window is refused under v2",
        "Limit and payload qualification gate",
        "It is not claimed that limit=100000 is supported",
        "visibly insufficient",
        "no replacement (64 MiB or any other value) is invented or finalized here",
        "offset pagination does not return as the fallback",
        "2,147",
    ):
        assert clause in ADR_PLAIN, clause


def test_the_consequences_and_the_corrected_deployment_impact_are_stated() -> None:
    for phrase in (
        "run 1 is replaced as a whole",
        "Stocks are not copied into, or patched onto, the old run",
        "approximately 94 requests",
        "1 + 3 " + chr(0xD7) + " 94 + 1 = 284",
        "remains superseded and preserved",
        "That claim is withdrawn",
        "binds the release commit, the exact tree and the generated timestamp",
        "Generate four new release-bound configuration digests",
        "Rederive the precise Terraform add / change / destroy count from the declaration",
        "It is not stated here that R-3 or the permission-probe evidence remains current",
        "G1, G4, G5, PEAD, short-side and M0 readiness are unchanged",
    ):
        assert phrase in ADR_PLAIN, phrase


def test_every_amended_adr_carries_a_dated_section_naming_adr_0053() -> None:
    for name, heading in AMENDED.items():
        text = (DECISIONS / name).read_text(encoding="utf-8")
        assert heading in text, name
        tail = text.split(heading, 1)[1]
        plain = _plain(tail)
        assert "ADR-0053" in tail and "SUPERSEDED under ADR-0053" in plain, name
        assert "Superseded rule" in plain, name
        assert "Nothing in this amendment is implemented, qualified or deployed" in plain, name
        assert "Since accepted: ADR-0053 is ACCEPTED / IN FORCE on the merge of PR #129" in plain
        # The historical text above is untouched: the heading appears once, at the end.
        assert text.count(heading) == 1 and text.rstrip().endswith(tail.rstrip()), name


def test_the_registers_the_owner_inputs_and_the_readiness_record_are_synchronized() -> None:
    owner_inputs = (REPO_ROOT / "docs" / "operations" / "production-owner-inputs.md").read_text(
        encoding="utf-8"
    )
    assert OWNER_DECISION in _plain(owner_inputs)
    assert "| D-18 |" in owner_inputs and "| D-19 |" in owner_inputs
    readiness = (REPO_ROOT / "docs" / "operations" / "production-readiness.md").read_text(
        encoding="utf-8"
    )
    assert "## 17. The pagination-v2 governance cycle (2026-09-18)" in readiness
    assert "not buildable" in readiness and "899f2e11" in readiness
    checklist = (REPO_ROOT / "docs" / "operations" / "production-owner-checklist.md").read_text(
        encoding="utf-8"
    )
    assert "| 4.6 |" in checklist and "ADR-0053" in checklist
    assert "ADR-0053" not in audit.PROPOSED_ADR_STATUS
    assert dict(audit.MERGED_ADR_STATUS)["ADR-0053"] == "PR #129 merged"
    documents = {
        name: (REPO_ROOT / name).read_text(encoding="utf-8") for name in ("CLAUDE.md", "README.md")
    }
    assert audit._proposed_adr_row_defects(documents) == []
    for name, text in documents.items():
        rows = [line for line in text.splitlines() if "[ADR-0053](docs/decisions/" in line]
        assert len(rows) == 1, name
        assert "ACCEPTED / IN FORCE" in rows[0] and "PR #129 merged" in rows[0], name
        assert MERGE_COMMIT in rows[0] and APPROVED_HEAD in rows[0], name
        assert "not buildable" in rows[0] and "nothing is qualified" in rows[0], name
        assert "ADR-0053 pagination v2 (governance):" in text, name
        assert (
            "D-19 attempt 1 PROVIDER_REFUSED" in text
            and "D-21 third qualification PENDING" in text
            and "D-20 round 2 DUPLICATE_PRIMARY_KEY" in text
        ), name
        assert "runtime pagination-v2 implementation ABSENT" in text, name


def test_the_audit_guard_refuses_a_proposed_row_that_claims_a_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The guard is exercised over a proposed entry even now that the registry is empty.
    monkeypatch.setattr(audit, "PROPOSED_ADR_STATUS", ("ADR-0053",))
    bad = {
        "CLAUDE.md": (
            "| **[ADR-0053](docs/decisions/x.md) — t** | **ACCEPTED / IN FORCE** — PR #999 merged |"
        ),
        "README.md": "",
    }
    defects = audit._proposed_adr_row_defects(bad)
    assert any("claims an in-force merge" in d for d in defects)
    assert any("has 0 register rows" in d for d in defects)


DECISION_2: Final = (
    "I accept amending ADR-0053 so that a successfully parsed data response containing fewer "
    "than the governed limit L is complete-shaped without a completion probe."
)


def test_section_11_records_the_second_decision_the_first_attempt_and_the_stocks_predicate() -> (
    None
):
    assert "## 11. Amendment (2026-09-18)" in ADR_TEXT
    section = _plain(ADR_TEXT.split("## 11. Amendment (2026-09-18)", 1)[1])
    assert DECISION_2 in section
    for phrase in (
        "PROVIDER_REFUSED stands, unchanged",
        "did not qualify L = 100000",
        "did not measure peak RSS",
        "a second qualification is required",
        "the actions groups remain unqualified",
        "complete-shaped without a completion probe",
        "exactly one completion probe at offset L",
        "more than L rows is malformed",
        "Multiple data-bearing pages remain prohibited",
        "offset-based assembly remains prohibited",
        "Every tickers request carries an accepted explicit table predicate",
        "permaticker remains the identity within each table-specific logical group",
        "never silently combined",
        'exactly { "stocks" }',
        "Decision rule 1 applies: exactly one table",
        "PSR-SHD-134",
        "owner-input D-20",
    ):
        assert phrase in section, phrase
    # every amended decision carries the dated section-11 note, appended after its earlier notes
    for name in AMENDED:
        text = (DECISIONS / name).read_text(encoding="utf-8")
        assert text.count("Amended 2026-09-18 by ADR-0053 §11") == 1, name
    register = (REPO_ROOT / "docs" / "phase3" / "provider-source-register.md").read_text(
        encoding="utf-8"
    )
    assert "| `PSR-SHD-134` |" in register and "https://sharadar.com/docs/tickers" in register
    owner_inputs = (REPO_ROOT / "docs" / "operations" / "production-owner-inputs.md").read_text(
        encoding="utf-8"
    )
    assert "| D-20 |" in owner_inputs and "PROVIDER_REFUSED" in owner_inputs
    assert "attempt 1 (02:32Z)" in owner_inputs and "NOT qualified" in owner_inputs
    readiness = (REPO_ROOT / "docs" / "operations" / "production-readiness.md").read_text(
        encoding="utf-8"
    )
    assert "### 17.1 The first D-19 attempt and the ADR-0053" in readiness
