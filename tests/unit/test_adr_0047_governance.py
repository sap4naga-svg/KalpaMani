"""Proposed ADR-0047 says what the code does, and the code says the same.

The document is PROPOSED and says so; it names the release modes, the negative-evidence
and permission contracts, the tool, the subcell counts, the two mechanisms it leaves
required and unimplemented; every "must succeed" and "must be refused" clause of
ADR-0036 s.3's R-4 .. R-9 rows is held to at least one subcell; the status register
carries the proposal; and nothing in the decision is a real value.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from kalpamani.data.production.sharadar import permission_cells as pc
from kalpamani.data.production.sharadar import verification_cells as vc
from kalpamani.data.production.sharadar.launch_records import ReleaseMode

pytestmark = pytest.mark.unit

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = REPO_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0047-negative-verification-launches-and-permission-subcells.md"
ADR_0036: Final = DECISIONS / "ADR-0036-production-data-plane-principals-and-trust-model.md"
ADR_TEXT: Final = ADR.read_text(encoding="utf-8")
ADR_PLAIN: Final = " ".join(ADR_TEXT.split()).replace("**", "").replace("`", "")
PROPOSED: Final = "PROPOSED " + chr(0x2014) + " NOT IN FORCE"
HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")

R7_PREFIXES: Final = (
    "any production prefix (`bronze/sharadar/*` outside `qualification/`, `_indexes/`, "
    "`silver/`, `gold/`, `manifests/`)"
)

#: ADR-0036 s.3, R-4 .. R-9: (cell, a fragment of the row's own text, the expectation, a
#: fragment every satisfying subcell's trace carries). The row fragment is asserted in
#: ADR-0036 so the mapping cannot drift from the accepted text it traces.
CLAUSES: Final[tuple[tuple[str, str, pc.Expectation, str], ...]] = (
    (
        "R-4",
        "`GetSecretValue` on the one secret",
        pc.Expectation.ALLOWED,
        "GetSecretValue on the one secret",
    ),
    (
        "R-4",
        "conditional `PutObject` to each production Bronze prefix",
        pc.Expectation.ALLOWED,
        "each production Bronze prefix",
    ),
    ("R-4", "and to `_indexes/`", pc.Expectation.ALLOWED, "PutObject to _indexes/"),
    ("R-4", "`GetObject` on its own write", pc.Expectation.DENIED, "GetObject on its own write"),
    ("R-4", "`ListBucket`; `DeleteObject`", pc.Expectation.DENIED, "ListBucket"),
    ("R-4", "`ListBucket`; `DeleteObject`", pc.Expectation.DENIED, "DeleteObject"),
    (
        "R-4",
        "`PutObject` to `silver/`, `gold/`, `manifests/`",
        pc.Expectation.DENIED,
        "PutObject to silver/",
    ),
    (
        "R-4",
        "`PutObject` to `silver/`, `gold/`, `manifests/`",
        pc.Expectation.DENIED,
        "PutObject to gold/",
    ),
    (
        "R-4",
        "`PutObject` to `silver/`, `gold/`, `manifests/`",
        pc.Expectation.DENIED,
        "PutObject to manifests/",
    ),
    (
        "R-4",
        "any qualification prefix, the CONTROL bucket",
        pc.Expectation.DENIED,
        "any qualification prefix",
    ),
    (
        "R-4",
        "any qualification prefix, the CONTROL bucket",
        pc.Expectation.DENIED,
        "the CONTROL bucket",
    ),
    (
        "R-4",
        "`GetSecretValue` on the qualification secret",
        pc.Expectation.DENIED,
        "GetSecretValue on the qualification secret",
    ),
    ("R-4", "`DescribeSecret`", pc.Expectation.DENIED, "DescribeSecret"),
    (
        "R-4",
        "`ssm:GetParameter` on the other actor's parameters",
        pc.Expectation.DENIED,
        "ssm:GetParameter on the other actor's parameters",
    ),
    (
        "R-4",
        "`ssm:PutParameter` on any binding parameter",
        pc.Expectation.DENIED,
        "ssm:PutParameter on any binding parameter",
    ),
    (
        "R-5",
        "exact `GetObject` on a Bronze payload, record and locator",
        pc.Expectation.ALLOWED,
        "GetObject on a Bronze payload",
    ),
    (
        "R-5",
        "exact `GetObject` on a Bronze payload, record and locator",
        pc.Expectation.ALLOWED,
        "GetObject on a Bronze record",
    ),
    (
        "R-5",
        "exact `GetObject` on a Bronze payload, record and locator",
        pc.Expectation.ALLOWED,
        "GetObject on a locator",
    ),
    (
        "R-5",
        "conditional `PutObject` to `silver/`, `gold/`, `manifests/`",
        pc.Expectation.ALLOWED,
        "PutObject to silver/",
    ),
    (
        "R-5",
        "conditional `PutObject` to `silver/`, `gold/`, `manifests/`",
        pc.Expectation.ALLOWED,
        "PutObject to gold/",
    ),
    (
        "R-5",
        "conditional `PutObject` to `silver/`, `gold/`, `manifests/`",
        pc.Expectation.ALLOWED,
        "PutObject to manifests/",
    ),
    ("R-5", "`GetObject` on its own output", pc.Expectation.ALLOWED, "GetObject on its own output"),
    (
        "R-5",
        "`GetSecretValue` on any secret",
        pc.Expectation.DENIED,
        "GetSecretValue on any secret",
    ),
    ("R-5", "`ListBucket`; `GetObject` on a claim", pc.Expectation.DENIED, "ListBucket"),
    ("R-5", "`ListBucket`; `GetObject` on a claim", pc.Expectation.DENIED, "GetObject on a claim"),
    ("R-5", "`PutObject` to `bronze/*`", pc.Expectation.DENIED, "PutObject to bronze/*"),
    (
        "R-5",
        "`DeleteObject`; any qualification prefix; the CONTROL bucket",
        pc.Expectation.DENIED,
        "DeleteObject",
    ),
    (
        "R-5",
        "`DeleteObject`; any qualification prefix; the CONTROL bucket",
        pc.Expectation.DENIED,
        "any qualification prefix",
    ),
    (
        "R-5",
        "`DeleteObject`; any qualification prefix; the CONTROL bucket",
        pc.Expectation.DENIED,
        "the CONTROL bucket",
    ),
    (
        "R-5",
        "`ssm:GetParameter` on the acquisition parameters",
        pc.Expectation.DENIED,
        "ssm:GetParameter on the acquisition parameters",
    ),
    (
        "R-6",
        "`RunTask` of its own actor's exact revision on the one cluster with `count = 1`",
        pc.Expectation.ALLOWED,
        "RunTask of its own actor's exact revision",
    ),
    (
        "R-6",
        "`DescribeTasks`; `DescribeNetworkInterfaces` on the task's interface",
        pc.Expectation.ALLOWED,
        "DescribeTasks",
    ),
    (
        "R-6",
        "`DescribeTasks`; `DescribeNetworkInterfaces` on the task's interface",
        pc.Expectation.ALLOWED,
        "DescribeNetworkInterfaces on the task's interface",
    ),
    (
        "R-6",
        "`RunTask` of the **other actor's** definition",
        pc.Expectation.DENIED,
        "RunTask of the other actor's definition",
    ),
    ("R-6", "of another revision or family", pc.Expectation.DENIED, "RunTask of another revision"),
    ("R-6", "of another revision or family", pc.Expectation.DENIED, "RunTask of another family"),
    ("R-6", "on another cluster", pc.Expectation.DENIED, "RunTask on another cluster"),
    (
        "R-6",
        "with a `taskRoleArn` override naming the other actor's task role",
        pc.Expectation.DENIED,
        "taskRoleArn override naming the other actor's task role",
    ),
    ("R-6", "`ExecuteCommand`", pc.Expectation.DENIED, "ExecuteCommand"),
    (
        "R-7",
        R7_PREFIXES,
        pc.Expectation.DENIED,
        "any production prefix (bronze/sharadar/* outside qualification/)",
    ),
    (
        "R-7",
        R7_PREFIXES,
        pc.Expectation.DENIED,
        "any production prefix (_indexes/)",
    ),
    (
        "R-7",
        R7_PREFIXES,
        pc.Expectation.DENIED,
        "any production prefix (silver/)",
    ),
    (
        "R-7",
        R7_PREFIXES,
        pc.Expectation.DENIED,
        "any production prefix (gold/)",
    ),
    (
        "R-7",
        R7_PREFIXES,
        pc.Expectation.DENIED,
        "any production prefix (manifests/)",
    ),
    ("R-7", "any production parameter", pc.Expectation.DENIED, "any production parameter"),
    (
        "R-8",
        "list and delete under the widened prefixes (rehearsal against synthetic objects only)",
        pc.Expectation.ALLOWED,
        "list and delete under the widened prefixes",
    ),
    ("R-8", "`GetObject` anywhere", pc.Expectation.DENIED, "GetObject anywhere"),
    (
        "R-9",
        "not passable by either launcher (`iam:PassRole` refused by `NotResource`)",
        pc.Expectation.DENIED,
        "not passable by either launcher",
    ),
)


def _adr_0036_row(ref: str) -> str:
    text = ADR_0036.read_text(encoding="utf-8")
    match = re.search(rf"^\| {re.escape(ref)} \|[^\n]*$", text, re.M)
    assert match is not None, ref
    return match.group(0)


def test_the_adr_exists_is_proposed_and_names_its_gates() -> None:
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0047-*.md"))] == [ADR.name]
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "Acceptance authorizes no execution" in ADR_PLAIN
    assert "acceptance grants no permission" in ADR_PLAIN
    assert "## 7. Effectiveness and execution gates" in ADR_TEXT
    assert "Nothing was run to produce this decision" in ADR_PLAIN
    assert "Mocked results are not AWS verification" in ADR_PLAIN
    assert "G2 stays OPEN, CONTROL stays DEFERRED, Phase 3 stays NOT COMPLETE" in ADR_PLAIN
    assert "not to be rewritten as though this decision had authority" in ADR_PLAIN


def test_the_adr_names_the_release_modes_the_contracts_and_the_tool() -> None:
    for mode in ReleaseMode:
        assert mode.value in ADR_TEXT, mode
    for contract in (
        vc.NEGATIVE_EVIDENCE_CONTRACT_ID,
        pc.PERMISSION_TARGETS_CONTRACT_ID,
        pc.PERMISSION_ATTEMPT_CONTRACT_ID,
        pc.PERMISSION_RECORD_CONTRACT_ID,
        pc.PERMISSION_CLEANUP_CONTRACT_ID,
    ):
        assert contract in ADR_TEXT, contract
    for name in ("scripts/production_permission_cells.py", "scripts/production_launch.py"):
        assert name in ADR_TEXT and (REPO_ROOT / name).is_file(), name
    assert "permission_cells.SUBCELLS" in ADR_TEXT
    assert "--release-mode withheld|mismatched" in ADR_TEXT
    assert "MODE_MISMATCH" in ADR_TEXT
    for status in pc.SubcellStatus:
        assert status.value in ADR_TEXT, status
    for cell in vc.REQUIRED_CELLS:
        if cell.kind in {vc.CellKind.NEGATIVE_LAUNCH, vc.CellKind.PERMISSION_MATRIX}:
            assert cell.cell_id in ADR_TEXT, cell.cell_id


def test_the_subcell_counts_in_the_adr_are_the_catalogue_s() -> None:
    by_layer = {layer: sum(1 for s in pc.SUBCELLS if s.layer is layer) for layer in pc.Layer}
    assert len(pc.SUBCELLS) == 98 and "98 in" in ADR_PLAIN
    assert by_layer[pc.Layer.L3_RUNTIME] == 58
    assert by_layer[pc.Layer.L3_BY_R1] == 6
    assert by_layer[pc.Layer.BLOCKED] == 34
    per_cell = {
        "R4-ACQUISITION": (34, 17, 0, 17),
        "R5-BUILD": (30, 15, 0, 15),
        "R6-LAUNCHERS": (18, 12, 6, 0),
        "R7-QUALIFICATION": (12, 12, 0, 0),
        "R8-DELETION": (2, 0, 0, 2),
        "R9-FOUNDATION-TASK": (2, 2, 0, 0),
    }
    for cell_id, (total, runtime, by_r1, blocked) in per_cell.items():
        cells = pc.subcells_of(cell_id)
        assert len(cells) == total, cell_id
        assert sum(1 for s in cells if s.layer is pc.Layer.L3_RUNTIME) == runtime, cell_id
        assert sum(1 for s in cells if s.layer is pc.Layer.L3_BY_R1) == by_r1, cell_id
        assert sum(1 for s in cells if s.layer is pc.Layer.BLOCKED) == blocked, cell_id
    # The table row of s.3.1 carries the same figures.
    assert (
        "| R-4 acquisition (`R4-ACQUISITION`) | 34 | 17" in ADR_TEXT
        and "| 17 (the acquisition task role) |" in ADR_TEXT
    )
    assert "| R-5 build (`R5-BUILD`) | 30 | 15" in ADR_TEXT
    assert (
        "| R-6 launchers (`R6-LAUNCHERS`) | 18 | 12" in ADR_TEXT and "| 6 (own revision" in ADR_TEXT
    )
    assert "| R-7 qualification (`R7-QUALIFICATION`) | 12 | 12" in ADR_TEXT
    assert "| R-8 deletion (`R8-DELETION`) | 2 | — | — | 2 (no execution path) |" in ADR_TEXT
    assert "| R-9 foundation task role (`R9-FOUNDATION-TASK`) | 2 | 2" in ADR_TEXT
    assert "the 32 task-role subcells of R-4 and R-5" in ADR_PLAIN
    assert sum(1 for s in pc.SUBCELLS if s.blocked_on == pc.TASK_PROBE_DEPENDENCY) == 32
    assert sum(1 for s in pc.SUBCELLS if s.blocked_on == pc.DELETION_DEPENDENCY) == 2


def test_every_adr_0036_clause_of_r4_to_r9_is_held_by_a_subcell() -> None:
    rows = {ref: _adr_0036_row(ref) for ref in ("R-4", "R-5", "R-6", "R-7", "R-8", "R-9")}
    for ref, fragment, expectation, trace in CLAUSES:
        assert fragment in rows[ref], (ref, fragment)
        holders = [
            s
            for s in pc.SUBCELLS
            if s.cell_id.startswith(f"R{ref[2]}-")
            and s.expectation is expectation
            and trace in s.trace
        ]
        assert holders, (ref, trace)
    # And every subcell's trace is one of the clauses above: nothing in the catalogue is traced
    # to a phrase the accepted row does not carry.
    traced = {(ref, exp, trace) for ref, _, exp, trace in CLAUSES}
    for s in pc.SUBCELLS:
        ref = f"R-{s.cell_id[1]}"
        assert any(r == ref and e is s.expectation and t in s.trace for r, e, t in traced), (
            s.subcell_id
        )


def test_the_two_required_mechanisms_are_named_and_not_implemented() -> None:
    assert "## 5. Required and not implemented" in ADR_TEXT
    assert "task-side permission probe entry" in ADR_PLAIN
    assert "execution path for the deletion role" in ADR_PLAIN
    assert "not implemented; not authorized by this ADR" in ADR_PLAIN
    assert "A human role never stands in for a task role" in ADR_PLAIN
    assert "human role is never a substitute for a task role" in pc.TASK_PROBE_DEPENDENCY
    assert "no deletion task definition exists" in pc.DELETION_DEPENDENCY
    assert (
        "D-14 (analyzer), V-16" in ADR_PLAIN and "G-14 stay recorded and not granted" in ADR_PLAIN
    )
    # The amendments are stated, and the one wording of ADR-0036 s.3 is read, not rewritten.
    assert "### 6.1 ADR-0045's contracts, narrowly" in ADR_TEXT
    assert "### 6.3 ADR-0036 §3, one wording" in ADR_TEXT
    assert "ADR-0036's text is not rewritten" in ADR_PLAIN


def test_the_status_register_carries_the_proposal() -> None:
    for name in ("CLAUDE.md", "README.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert ADR.name in text
        assert "ADR-0047 negative launches + permission subcells (code):" in text
        assert "ADR-0047 PROPOSED, NOT IN FORCE" in text
        # The accepted-state synchronization of ADR-0046 travels in the same change.
        assert "PR #105 merged 2026-09-14T20:37:38Z" in text
        assert "ADR-0046 ACCEPTED / IN FORCE" in text


def test_the_adr_names_no_real_value() -> None:
    assert not HEX_64.search(ADR_TEXT)
    assert not TWELVE_DIGITS.search(ADR_TEXT)
    assert "arn:aws" not in ADR_TEXT
