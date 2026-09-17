"""ADR-0052 says what the cell catalogue and the runner do, and they say the same.

The dedicated R-2 corroboration cell, the hook's single attachment point, the verdict's moved
dependency, the rebinding refusal, the amendment sections of ADR-0045 and ADR-0046, and the
owner-inputs row.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import production_verification_cells as runner

from kalpamani.data.production.sharadar import verification_cells as vc
from kalpamani.data.production.sharadar.entry import TaskEntry
from kalpamani.data.production.sharadar.vocabulary import ProductionActor

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = REPO_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0052-dedicated-r2-corroboration-cell.md"
ADR_TEXT: Final = ADR.read_text(encoding="utf-8")
ADR_PLAIN: Final = " ".join(ADR_TEXT.split()).replace("**", "").replace("`", "")
ADR_0045: Final = (
    DECISIONS / "ADR-0045-verification-entries-observation-build-and-launch-tool.md"
).read_text(encoding="utf-8")
ADR_0046: Final = (
    DECISIONS / "ADR-0046-verification-tooling-materializer-r3-tool-and-cell-runner.md"
).read_text(encoding="utf-8")
OWNER_INPUTS: Final = (REPO_ROOT / "docs" / "operations" / "production-owner-inputs.md").read_text(
    encoding="utf-8"
)
PROPOSED: Final = (
    "PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is"
)
TWELVE_DIGITS: Final = re.compile(r"\b[0-9]{12}\b")
CELL: Final = "R2-BLD-CORROBORATION"


def test_the_adr_exists_is_proposed_and_authorizes_nothing() -> None:
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0052-*.md"))] == [ADR.name]
    assert PROPOSED in ADR_TEXT
    assert "Acceptance authorizes no execution" in ADR_PLAIN
    for phrase in (
        "no launch, no path, no analysis, no receipt collection, no reservation, no D-16",
        "no rerun of any PASSED cell",
        "Mocked results are not AWS verification",
        "PASSED here is the launch's own success and nothing more",
        "A launched binding is never rebound",
    ):
        assert phrase in ADR_PLAIN, phrase
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    for private in ("arn:aws", "eni-0", "nip-0", "nia-0", "y91xlz15"):
        assert private not in ADR_TEXT, private


def test_the_catalogue_carries_the_cell_exactly_as_the_adr_states() -> None:
    cell = vc.CELL_BY_ID[CELL]
    assert cell.cell_ref == "R-2" and cell.kind is vc.CellKind.RUNTIME_LAUNCH
    assert cell.actor is ProductionActor.BUILD and cell.entry is TaskEntry.BUILD_VERIFY
    assert cell.depends_on == ("R3", "R1-BLD-BOOTSTRAP")
    assert cell.release_mode is None or cell.release_mode.value == "NORMAL"
    assert "ADR-0052" in cell.title
    assert vc.CELL_BY_ID["R2-BLD-ISOLATION"].depends_on == (CELL,)
    ids = [c.cell_id for c in vc.REQUIRED_CELLS]
    assert ids.index("R1-BLD-BOOTSTRAP") < ids.index(CELL) < ids.index("R2-BLD-ISOLATION")
    # The R-1 bootstrap cells and the negatives are untouched by the addition.
    assert vc.CELL_BY_ID["R1-BLD-BOOTSTRAP"].depends_on == ("R3",)
    for negative in ("R1-BLD-NO-RELEASE", "R1-BLD-RELEASE-MISMATCH"):
        assert vc.CELL_BY_ID[negative].depends_on == ("R1-BLD-BOOTSTRAP",)
    for text in (CELL, "R2-BLD-ISOLATION", "R1-BLD-BOOTSTRAP", "refused_cell_state"):
        assert text in ADR_TEXT, text


def test_the_runner_hands_the_hook_to_this_cell_alone_and_never_rebinds() -> None:
    assert runner.HOOK_CELL_ID == CELL

    def hook(_held: object) -> None:  # pragma: no cover - never invoked here
        raise AssertionError("not called")

    for cell in vc.REQUIRED_CELLS:
        expected = hook if cell.cell_id == CELL else None
        assert runner.while_running_for(cell, hook) is expected, cell.cell_id
    assert "a ledger row" in (runner._identity_launched.__doc__ or "")
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "never a licence to rebind" in source
    assert "_identity_launched(store, bound.identity)" in source
    assert 'raise CellsRefusalError("refused_cell_state", EXIT_REFUSED_CELL_STATE)' in source


def test_the_amended_documents_name_the_cell_and_the_amendment() -> None:
    assert "## 13. Amendment (2026-09-17)" in ADR_0045 and "ADR-0052" in ADR_0045
    assert CELL in ADR_0045.split("## 13. Amendment")[1]
    assert "## 7. Amendment (2026-09-17)" in ADR_0046 and "ADR-0052" in ADR_0046
    assert CELL in ADR_0046 and "never rebound" in ADR_0046
    assert CELL in OWNER_INPUTS and "ADR-0052" in OWNER_INPUTS
    assert "owner-attested" in OWNER_INPUTS
