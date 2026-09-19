"""ADR-0055: the decision verbatim, the registers, the amendments; the tooling says the same.

The compact build input v2, the historical disposition of v1, the two refusal-boundary
corrections, the ADR-0036 and ADR-0045 amendment sections, the register rows and the
audit registry -- every row written for the post-merge state, so no activation
synchronization is owed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import phase3_docs_audit as audit
import production_launch as launch

from kalpamani.data.production.sharadar import build_inputs as bi
from kalpamani.data.production.sharadar import inputs as pin
from kalpamani.data.production.sharadar import launch_records as lr
from kalpamani.data.production.sharadar import locator as loc
from kalpamani.data.production.sharadar.vocabulary import (
    MAX_ADVANCED_PARAMETER_BYTES,
    ProductionActor,
    constants_for,
)

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = REPO_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0055-compact-build-input-v2.md"
ADR_TEXT: Final = ADR.read_text(encoding="utf-8")
PR: Final = "PR #138"
PROPOSED: Final = (
    "PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is"
)
TWELVE_DIGITS: Final = re.compile(r"\b[0-9]{12}\b")
DECISION: Final = (
    "I select Option A for S10c: replace the redundant build-input row representation with a "
    "compact, lossless and strictly validated contract that makes the accepted 32-run ceiling "
    "genuinely reachable within the unchanged 8 KiB advanced-parameter limit. The compact form may "
    "remove only values that are deterministically derived from the run identity, locator key or "
    "validated locator content; it must preserve cryptographic binding, fail closed on every "
    "mismatch, retain v1 as historical evidence only, and weaken no acquisition, build, "
    "point-in-time, schema, completion, write-order or audit requirement. I also authorize fixing "
    "the raw-ValueError refusal boundary and enforcing the byte ceiling during materialization. "
    "This authorizes repository governance/tooling/runtime changes and an exact-head merge, but no "
    "image build, registry publication, Terraform, registration change, AWS task, S3 operation, "
    "production build, backtest or trade."
)
PROPOSED_SECTION: Final = (
    "PROPOSED — NOT IN FORCE while the pull request carrying this section is open"
)
AMENDED: Final = {
    "ADR-0036-production-data-plane-principals-and-trust-model.md": (
        "## 7. Amendment (2026-09-19) — the build input's compact, digest-bound form (ADR-0055)"
    ),
    "ADR-0045-verification-entries-observation-build-and-launch-tool.md": (
        "## 16. Amendment (2026-09-19) — the build launch binds the preserved locators; "
        "a sized, closed refusal (ADR-0055)"
    ),
}


def _plain(text: str) -> str:
    # Blockquote markers are layout, not text: the owner's decision is quoted verbatim.
    lines = (line[2:] if line.startswith("> ") else line for line in text.splitlines())
    return " ".join(" ".join(lines).split()).replace("**", "").replace("`", "")


ADR_PLAIN: Final = _plain(ADR_TEXT)


def test_the_adr_exists_states_its_status_and_authorizes_nothing_that_runs() -> None:
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0055-*.md"))] == [ADR.name]
    assert PROPOSED in ADR_TEXT  # the historical clause stays
    assert "On the exact-head merge of that pull request this ADR becomes ACCEPTED / IN FORCE" in (
        ADR_PLAIN
    )
    assert f"ACCEPTED / IN FORCE — {PR} merged" in ADR_PLAIN
    assert "no later activation synchronization is owed" in ADR_PLAIN
    assert "Acceptance authorizes no deployment and no execution" in ADR_PLAIN
    assert "Acceptance authorizes nothing that runs" in ADR_PLAIN
    assert "None of the above is authorized by acceptance" in ADR_PLAIN
    assert "Mocked results are not AWS verification" in ADR_PLAIN
    assert "Nothing was run against AWS to produce this decision" in ADR_PLAIN
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    for private in ("arn:aws", "eni-0", "nip-0", "nia-0", "C:\\Users", "sap4n", "<home>"):
        assert private not in ADR_TEXT, private


def test_the_owners_decision_is_recorded_verbatim() -> None:
    assert DECISION in ADR_PLAIN
    assert "owner-input D-23" in ADR_PLAIN


def test_the_decision_states_the_contract_the_mapping_and_the_proof() -> None:
    for phrase in (
        "8,266 bytes",
        "8,192 bytes",
        "Seventeen rows fit (7,784 bytes)",
        "build-input-build-20260918T234038Z-6421d019.json",
        "never written, never consumed and is not reused",
        "kalpamani-research-build-input/v2",
        '{"run_identity": <run-id>, "locator_sha256": <64 lowercase hex>}',
        "MAX_BUILD_RUNS is not reduced; the 8 KiB ceiling is not raised; "
        "no partial or two-part build",
        "Field-by-field mapping, version 1 → version 2",
        "removed — derived",
        "removed — fixed",
        "bind_run_locators",
        "before any decode",
        "compared in constant time",
        "MAX_BUILD_INPUT_DOCUMENT_BYTES = MAX_ADVANCED_PARAMETER_BYTES = 8,192",
        "before returning them",
        "5,717 bytes",
        "margin of 2,475 bytes",
        "WORST_CASE_32_RUN_BYTES",
        "historical evidence, never execution",
        "parse_historical_build_input_v1",
        "HistoricalBuildInputV1",
        "The raw ValueError no longer escapes",
        "refused_input_size, exit code 20",
        "The ceiling is enforced during materialization",
        "weakens no acquisition, build, point-in-time, schema, completion, write-order or audit "
        "requirement",
        "images to rebuild",
        "build and build-verification images only",
        "left to the runner to derive, never hand-marked",
        "equivalent mutant",
    ):
        assert phrase in ADR_PLAIN, phrase
    assert "kalpamani-research-build-input/v1" in ADR_TEXT
    for row in ("`slice`", "`plan_digest`", "`outcome`", "`launched_at`", "`completed_at`"):
        assert f"| {row} | **removed**" in ADR_TEXT, row
    assert "| `run_identity` | **kept**" in ADR_TEXT
    assert "| — | **added: `locator_sha256`**" in ADR_TEXT


def test_the_tooling_carries_what_the_decision_states() -> None:
    assert constants_for(ProductionActor.BUILD).input_contract_id == (
        "kalpamani-research-build-input/v2"
    )
    assert pin.BUILD_INPUT_SCHEMA_VERSION == 2
    assert pin.HISTORICAL_BUILD_INPUT_SCHEMA_VERSION == 1
    assert pin.HISTORICAL_BUILD_INPUT_CONTRACT_ID == "kalpamani-research-build-input/v1"
    assert pin.MAX_BUILD_INPUT_DOCUMENT_BYTES == MAX_ADVANCED_PARAMETER_BYTES == 8 * 1024
    assert pin.MAX_BUILD_RUNS == 32
    assert pin.InputDefect.LOCATOR_DIGEST_DUPLICATED.value == "LOCATOR_DIGEST_DUPLICATED"
    for name in (
        "BUILD_INPUT_SCHEMA_VERSION",
        "BuildInputRow",
        "HistoricalBuildInputV1",
        "MAX_BUILD_INPUT_DOCUMENT_BYTES",
        "check_input_size",
        "compact_row_document",
        "parse_historical_build_input_v1",
    ):
        assert name in pin.__all__, name
    assert loc.RunLocatorDefect.LOCATOR_DIGEST_MISMATCH.value == "LOCATOR_DIGEST_MISMATCH"
    for name in ("validate_bound_run_locator", "ledger_row_of_locator"):
        assert name in loc.__all__, name
    assert callable(loc.ProductionLocatorReader.read_bound_run_locator)
    assert bi.BuildInputDefect.LOCATOR_DIGEST_MISMATCH.value == "LOCATOR_DIGEST_MISMATCH"
    for defect in (
        "LOCATOR_MISSING",
        "LOCATOR_REFUSED",
        "LOCATOR_DIGEST_DUPLICATE",
        "INPUT_TOO_LARGE",
    ):
        assert lr.LaunchRecordDefect[defect].value == defect
    assert "bind_run_locators" in lr.__all__
    assert launch.EXIT_REFUSED_INPUT_SIZE == 20
    assert "refused_input_size" in launch.SENTENCES
    assert launch.LOCATORS_DIRECTORY == "locators"
    assert launch.LOCATOR_FILE_TEMPLATE == "run-locator-{identity}.json"
    # The historical reader is named by no execution path.
    launch_source = (REPO_ROOT / "scripts" / "production_launch.py").read_text(encoding="utf-8")
    assert "parse_historical_build_input_v1" not in launch_source
    assert "HistoricalBuildInputV1" not in launch_source


def test_every_amended_adr_carries_a_dated_section_naming_adr_0055() -> None:
    for name, heading in AMENDED.items():
        text = (DECISIONS / name).read_text(encoding="utf-8")
        assert heading in text, name
        tail = text.split(heading, 1)[1]
        plain = _plain(tail)
        assert "ADR-0055" in tail, name
        assert PROPOSED_SECTION in plain, name
        assert "in force on the exact-head merge of that pull request" in plain, name
        assert "The accepted text above is not rewritten" in plain, name
        # The historical text above is untouched: the heading appears once, at the end.
        assert text.count(heading) == 1 and text.rstrip().endswith(tail.rstrip()), name
    adr_0036 = _plain((DECISIONS / next(iter(AMENDED))).read_text(encoding="utf-8"))
    assert "for each, the owner's slice-ledger row" in adr_0036  # the accepted clause stays
    assert "kalpamani-research-build-input/v1" in adr_0036
    adr_0045 = _plain((DECISIONS / list(AMENDED)[1]).read_text(encoding="utf-8"))
    assert "a commit change requires both families rebuilt" in adr_0045  # §7 stays as written
    assert "refused_input_size" in adr_0045 and "exit code 20" in adr_0045


def test_the_registers_and_the_audit_registry_are_synchronized() -> None:
    assert "ADR-0055" not in audit.PROPOSED_ADR_STATUS
    assert dict(audit.MERGED_ADR_STATUS)["ADR-0055"] == f"{PR} merged"
    owner_inputs = (REPO_ROOT / "docs" / "operations" / "production-owner-inputs.md").read_text(
        encoding="utf-8"
    )
    assert "| D-23 |" in owner_inputs and DECISION in _plain(owner_inputs)
    assert "build input v2" in owner_inputs and "ADR-0055" in owner_inputs
    readiness = (REPO_ROOT / "docs" / "operations" / "production-readiness.md").read_text(
        encoding="utf-8"
    )
    assert "## 19. The S10c build-input cycle (2026-09-19)" in readiness
    assert "8,266 bytes" in readiness and "5,717 bytes" in readiness
    documents = {
        name: (REPO_ROOT / name).read_text(encoding="utf-8") for name in ("CLAUDE.md", "README.md")
    }
    assert audit._proposed_adr_row_defects(documents) == []
    for name, text in documents.items():
        rows = [line for line in text.splitlines() if "[ADR-0055](docs/decisions/" in line]
        assert len(rows) == 1, name
        assert audit.PROPOSED_ROW_MARK not in rows[0], name
        assert "ACCEPTED / IN FORCE" in rows[0] and f"{PR} merged" in rows[0], name
        for wording in audit.PRE_MERGE_STATUS_WORDING:
            assert wording.upper() not in rows[0].upper(), (name, wording)
        assert "Deployment consequences stated, not performed" in rows[0], name
        assert "5,717 bytes" in rows[0] and "historical evidence only" in rows[0], name
        assert "Acceptance authorizes no image build" in rows[0], name
        assert "ADR-0055 compact build input v2:" in text, name
        assert "NOT AUTHORIZED BY ACCEPTANCE" in text, name
    examples = REPO_ROOT / "docs" / "operations" / "examples" / "production"
    assert (examples / "build-input.v2.synthetic.json").exists()
    assert (examples / "build-input.v1.synthetic.json").exists()  # historical, retained
