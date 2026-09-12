"""ADR-0040 governance: a proposed, narrow amendment fixing the research-build output shapes.

These checks hold the document to its own claims -- proposed and not in force, the inner
shapes under the accepted namespaces, the manifest contract, the deadline, the gates -- and
hold the offline implementation to the shapes the document describes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from kalpamani.data.production.sharadar import build_manifest, build_processing
from kalpamani.data.production.sharadar.gold import GoldArtifact

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0040-research-build-output-objects-and-manifest.md"
README: Final = PROJECT_ROOT / "README.md"
CLAUDE: Final = PROJECT_ROOT / "CLAUDE.md"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""
ADR_FLAT: Final = " ".join(ADR_TEXT.split())

HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")
REAL_ARN: Final = re.compile(r"\barn:aws\b")
PROPOSED: Final = "PROPOSED " + chr(0x2014) + " NOT IN FORCE"


def test_the_adr_exists_and_is_the_only_0040() -> None:
    assert ADR.is_file()
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0040-*.md"))] == [ADR.name]


def test_the_adr_carries_a_conditional_acceptance_status_and_the_gates() -> None:
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "Nothing was run to produce this decision" in ADR_FLAT
    assert "## 3. Effectiveness and execution gates" in ADR_TEXT
    assert "acceptance authorizes no build and no run" in ADR_FLAT
    assert "synthetic in this repository" in ADR_FLAT
    assert "Terraform declaration or deployed resource changes" in ADR_FLAT


def test_the_adr_states_the_shapes_the_implementation_writes() -> None:
    assert "licensed/silver/sharadar/<dataset>/objects/sha256/<digest>" in ADR_TEXT
    assert "licensed/gold/sharadar/<artifact>/objects/sha256/<digest>" in ADR_TEXT
    assert "licensed/manifests/sharadar/builds/<build-id>.json" in ADR_TEXT
    assert build_manifest.MANIFEST_SCHEMA_VERSION in ADR_TEXT
    assert "3,600 seconds" in ADR_TEXT and build_processing.BUILD_DEADLINE_SECONDS == 3600.0
    for token in ("ALREADY_PRESENT", "MANIFEST_NAME_OCCUPIED", "MANIFEST_STATE_UNKNOWN"):
        assert token in ADR_TEXT, token
    assert "then the manifest LAST" in ADR_FLAT


def test_the_key_builders_match_the_document() -> None:
    silver = GoldArtifact(name="silver-stocks", content=b"{}", sha256="ab" * 32, row_count=0)
    gold = GoldArtifact(name="gold-adjusted-bars", content=b"{}", sha256="cd" * 32, row_count=0)
    assert build_manifest.artifact_key(silver).segments == (
        "silver",
        "sharadar",
        "stocks",
        "objects",
        "sha256",
        "ab" * 32,
    )
    assert build_manifest.artifact_key(gold).segments == (
        "gold",
        "sharadar",
        "adjusted-bars",
        "objects",
        "sha256",
        "cd" * 32,
    )
    manifest = build_manifest.manifest_key(build_id="synthetic-build-0001", payload=b"{}")
    assert manifest.segments == ("manifests", "sharadar", "builds", "synthetic-build-0001.json")
    assert manifest.logical_key.startswith("licensed/manifests/")
    assert {m.value for m in build_manifest.ManifestDisposition} == {
        "PUBLISHED",
        "NOT_ATTEMPTED",
        "NAME_OCCUPIED",
        "REFUSED",
        "STATE_UNKNOWN",
    }


def test_the_adr_carries_no_private_value() -> None:
    assert HEX_64.search(ADR_TEXT) is None
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    assert REAL_ARN.search(ADR_TEXT) is None


@pytest.mark.parametrize("path", [README, CLAUDE])
def test_status_documents_record_the_adr_as_proposed(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert re.search(r"ADR-0040[^\n]{0,200}" + re.escape(PROPOSED), text) is not None
    assert "ADR-0040 (build output objects and manifest):     " + PROPOSED in text
