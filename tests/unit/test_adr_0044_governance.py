"""ADR-0044 governance: a proposed resolution of the delivery contracts and the packaging.

These checks hold the document to its own claims -- proposed and not in force, the trust chain
without a self-referential digest, one selected design per open question, the amendments it
names, the gates -- and hold the offline contracts to the shape the document describes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from kalpamani.data.production.sharadar import compiled, inputs, receipts, release
from kalpamani.data.production.sharadar.metadata import CompiledTask
from kalpamani.data.production.sharadar.outcomes import PlacementIncident
from kalpamani.data.production.sharadar.vocabulary import (
    RELEASE_CONTRACT_ID,
    ProductionActor,
    constants_for,
)

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0044-production-delivery-contracts-and-packaging.md"
README: Final = PROJECT_ROOT / "README.md"
CLAUDE: Final = PROJECT_ROOT / "CLAUDE.md"
PRODUCTION: Final = PROJECT_ROOT / "src" / "kalpamani" / "data" / "production" / "sharadar"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""
ADR_FLAT: Final = " ".join(ADR_TEXT.split())
ADR_PLAIN: Final = ADR_FLAT.replace("**", "").replace("`", "")

HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")
REAL_ARN: Final = re.compile(r"\barn:aws\b")
PROPOSED: Final = "PROPOSED " + chr(0x2014) + " NOT IN FORCE"
SECTION: Final = chr(0xA7)


def test_the_adr_exists_and_is_the_only_0044() -> None:
    assert ADR.is_file()
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0044-*.md"))] == [ADR.name]


def test_the_adr_carries_a_conditional_acceptance_status_and_the_gates() -> None:
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert f"the resolution of ADR-0043 {SECTION}3 and {SECTION}4" in ADR_PLAIN
    assert "Nothing was run to produce this decision" in ADR_FLAT
    assert "## 8. Effectiveness and execution gates" in ADR_TEXT
    assert (
        "acceptance authorizes no image build or publication, no Terraform plan or apply, "
        "no launch, no run" in ADR_PLAIN
    )
    assert "No image is built or published by this repository" in ADR_PLAIN


def test_the_adr_states_the_circularity_and_the_trust_chain() -> None:
    assert "An image cannot contain its own content digest" in ADR_PLAIN
    assert "A placeholder would have satisfied the shape and verified nothing" in ADR_PLAIN
    assert "never in the image" in ADR_PLAIN and "attested by the launch tool" in ADR_PLAIN
    assert "kalpamani-placement-release/v2" in ADR_TEXT and "v1 is retired" in ADR_PLAIN
    assert "IMAGE_MISMATCH" in ADR_TEXT and "CONFIGURATION_MISMATCH" in ADR_TEXT
    assert "kalpamani-compiled-configuration/v1" in ADR_TEXT
    assert "never an ARN" in ADR_PLAIN and "no account id in the image" in ADR_PLAIN
    assert "Amendments to accepted text, stated" in ADR_PLAIN


def test_the_adr_selects_one_design_per_question() -> None:
    assert "Selected: acquisition input contract v2" in ADR_PLAIN
    assert "kalpamani-production-acquisition-input/v2" in ADR_TEXT
    assert "No fourth parameter, no IAM change, no new operation" in ADR_PLAIN
    assert "never an empty registry" in ADR_PLAIN
    assert "conditional run reservation (ADR-0038) is unchanged" in ADR_PLAIN
    assert "Retired:" in ADR_PLAIN and "spent_source.py" in ADR_TEXT
    assert "kalpamani-task-receipt/v1" in ADR_TEXT and "binding_digest" in ADR_TEXT
    assert "no identifier" in ADR_PLAIN
    assert "never become measured zeros" in ADR_PLAIN
    assert "logs:GetLogEvents" in ADR_TEXT and "deferred" in ADR_PLAIN
    assert "Collection (proposed, not implemented)" in ADR_PLAIN


def test_the_adr_states_the_source_identity_and_the_total_parsing_corrections() -> None:
    # Finding 1: the context comes from the exact tree; five records must agree.
    assert "The source identity covers what enters the build" in ADR_PLAIN
    assert "scripts/production_build_context.py" in ADR_TEXT and "git archive" in ADR_TEXT
    assert "separately declared, digest-bound input" in ADR_PLAIN
    assert "refused rather than relabelled" in ADR_PLAIN
    assert "CONFIGURATION_DIGEST" in ADR_TEXT and "KALPAMANI_COMMIT" in ADR_TEXT
    assert "The repository root is not a build context" in ADR_PLAIN
    # Finding 2: total, closed parsing on both boundaries.
    assert "Parsing is total" in ADR_PLAIN and "Its parsing is total and closed" in ADR_PLAIN
    assert "DUPLICATE_KEY" in ADR_TEXT and "ENCODING_INVALID" in ADR_TEXT
    assert "no raw TypeError, ValueError or Unicode error" in ADR_PLAIN
    # Finding 3: every outcome ends in the line; an invalid invocation names no actor.
    assert "Every outcome ends in the line, the early refusals included" in ADR_PLAIN
    assert "null exactly for REFUSED_ENTRY" in ADR_PLAIN
    assert "invents no actor" in ADR_PLAIN


def test_the_implementation_matches_the_document() -> None:
    assert RELEASE_CONTRACT_ID == "kalpamani-placement-release/v2"
    assert release.RELEASE_SCHEMA_VERSION == 2
    assert {"image_digest", "configuration_digest"} <= release.release_fields(
        ProductionActor.ACQUISITION
    )
    assert release.ReleaseDefect.IMAGE_MISMATCH in release.MISMATCH_DEFECTS
    assert release.ReleaseDefect.CONFIGURATION_MISMATCH in release.MISMATCH_DEFECTS
    assert {"code_commit", "configuration_digest"} <= set(CompiledTask.__dataclass_fields__)
    assert not {"revision", "image_digest"} & set(CompiledTask.__dataclass_fields__)
    assert PlacementIncident.IMAGE_MISMATCH and PlacementIncident.IMAGE_UNRESOLVED
    assert constants_for(ProductionActor.ACQUISITION).input_contract_id.endswith("/v2")
    assert inputs.ACQUISITION_INPUT_SCHEMA_VERSION == 2 and inputs.MAX_SPENT_IDENTITIES == 128
    assert compiled.COMPILED_CONFIGURATION_CONTRACT_ID == "kalpamani-compiled-configuration/v1"
    assert compiled.COMPILED_CONFIGURATION_PATH == "/etc/kalpamani/compiled-configuration.json"
    assert receipts.RECEIPT_CONTRACT_ID == "kalpamani-task-receipt/v1"
    assert receipts.RECEIPT_LINE_PREFIX == "receipt: "
    assert not (PRODUCTION / "spent_source.py").exists()
    assert (PROJECT_ROOT / "docker" / "production" / "Dockerfile").is_file()
    assert (PROJECT_ROOT / "scripts" / "production_compiled_configuration.py").is_file()
    assert (PROJECT_ROOT / "scripts" / "production_build_context.py").is_file()
    assert receipts.ReceiptDefect.DUPLICATE_KEY and receipts.ReceiptDefect.ENCODING_INVALID
    assert compiled.CompiledConfigurationDefect.DUPLICATE_KEY
    assert (PROJECT_ROOT / "docs" / "operations" / "production-image-build.md").is_file()


def test_the_adr_carries_no_private_value() -> None:
    assert HEX_64.search(ADR_TEXT) is None
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    assert REAL_ARN.search(ADR_TEXT) is None


@pytest.mark.parametrize("path", [README, CLAUDE])
def test_status_documents_record_the_adr_as_proposed(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert re.search("ADR-0044[^\\n]{0,200}" + re.escape(PROPOSED), text) is not None
    assert "ADR-0044 (delivery contracts and packaging):       " + PROPOSED in text
    assert (
        "ADR-0044 delivery contracts + packaging (code):   "
        "OFFLINE / SYNTHETIC-ONLY / NO IMAGE / NEVER RUN" in text
    )
    assert "production image:                                  NONE" in text
