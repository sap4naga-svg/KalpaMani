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


def test_the_adr_keeps_its_conditional_status_and_records_the_merge() -> None:
    """The pre-merge condition is preserved as written; the note beside it records the event."""
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "Nothing was run to produce this decision" in ADR_FLAT
    assert "The condition above has since been satisfied." in ADR_FLAT
    assert "PR #97 merged" in ADR_FLAT and "2026-09-12T16:56:34Z" in ADR_FLAT
    assert "2be8d2ee7946de457e8071160f89836746713168" in ADR_TEXT
    assert "6ddfa3601a8b14d4e0768ddd823f2c5a34927bdd" in ADR_TEXT
    assert "310df423f2a2b26109e23bb5a4b1be8edc787f65" in ADR_TEXT
    assert "ADR-0040 is therefore ACCEPTED / IN FORCE" in ADR_FLAT.replace("**", "")
    assert "Acceptance authorizes no build and no run" in ADR_FLAT
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
def test_status_documents_record_the_adr_as_accepted_on_the_merge(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    rows = [
        line
        for line in text.splitlines()
        if line.startswith("| ")
        and "ADR-0040](" in line
        and "research-build output objects and manifest" in line.split("|")[1]
    ]
    assert len(rows) == 1
    flat = " ".join(rows[0].replace("**", "").split())
    assert "ACCEPTED / IN FORCE" in flat and "PR #97 merged 2026-09-12T16:56:34Z" in flat
    assert "2be8d2ee7946de457e8071160f89836746713168" in flat
    assert "while PR #97 was open it was proposed and carried no authority" in flat
    assert "ADR-0040 (build output objects and manifest):     ACCEPTED / IN FORCE" in text
    assert re.search(r"ADR-0040[^\n]{0,200}" + re.escape(PROPOSED), text) is None
