"""Phase 3 documentation-consistency audit.

Phase 3 is a **plan**, not an implementation. There is no ingestion code, no database and no
data, so nothing here can be checked against runtime behaviour. What *can* be checked
deterministically is whether the plan agrees with itself: whether a quality check names an enum
value the schema actually defines, whether a derived artifact is required to carry a field the
contract says it must not have, whether a temporal class is declared without the anchor it
needs, and whether any document still refers to a field name a later revision retired.

Those are exactly the defects the review rounds kept finding by hand. This script finds them by
running.

It reads `docs/phase3/` and `docs/decisions/ADR-0005-*.md`. It touches no runtime code, opens no
network connection, and asserts nothing about data. Exit code 0 means the documents are
mutually consistent on the properties below; non-zero lists what disagrees.

Run:  .venv/Scripts/python.exe scripts/phase3_docs_audit.py
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE3 = REPO_ROOT / "docs" / "phase3"
ADR = REPO_ROOT / "docs" / "decisions" / "ADR-0005-point-in-time-data-architecture.md"

CONTRACT = PHASE3 / "pit-data-contract.md"
SCHEMA = PHASE3 / "conceptual-schema.md"
QUALITY = PHASE3 / "data-quality-plan.md"
MANIFEST = PHASE3 / "reproducibility-and-provenance.md"

#: Documents the audit reads. The source register is excluded: it is generated evidence about
#: vendors, not part of the internal contract, and it legitimately quotes vendor wording.
AUDITED = (CONTRACT, SCHEMA, QUALITY, MANIFEST, PHASE3 / "implementation-plan.md", ADR)

# --------------------------------------------------------------------------------------
# The properties being audited. Each is a fact the documents must agree on.
# --------------------------------------------------------------------------------------

#: Closed vocabularies. Every value a check references must appear in the schema.
INFORMATION_ORIGINS = frozenset(
    {"AUTHORITATIVE_PUBLIC", "PROVIDER_DERIVED", "SYSTEM_OBSERVED", "DERIVED_ARTIFACT"}
)
SOURCE_ORIGINS = INFORMATION_ORIGINS - {"DERIVED_ARTIFACT"}
TEMPORAL_CLASSES = frozenset({"RETROSPECTIVE", "ANNOUNCED_FORWARD", "SAMPLED_STATE"})
OUTPUT_VALIDITIES = frozenset({"SESSION_SCOPED", "INTERVAL", "PERIOD_END", "EVENT_REFERENCED"})
PROFILES = frozenset({"PUBLIC_PIT", "PROVIDER_REALISTIC_PIT", "FORWARD_SYSTEM"})
REVISION_VIEWS = frozenset({"AS_KNOWN_AT_AS_OF", "ORIGINAL_FILING_ONLY", "LATEST_RESTATED"})
GAP_POLICIES = frozenset({"NONE", "EXCLUDE", "BOUND", "DOWNGRADE"})

#: The anchor each temporal class requires, per the atomic-fact rule.
CLASS_ANCHOR = {
    "RETROSPECTIVE": "observation_time",
    "ANNOUNCED_FORWARD": "announcement_time",
    "SAMPLED_STATE": "sample_time",
}

#: The validity field each output_validity requires.
VALIDITY_FIELD = {
    "SESSION_SCOPED": "effective_session",
    "INTERVAL": "valid_time_start",
    "PERIOD_END": "period_end",
    "EVENT_REFERENCED": "observation_reference",
}

#: Exact fields may only be written by exact derivations, and bounds only by bound derivations.
EXACT_DERIVATIONS = {
    "public_available_time": frozenset({"AUTHORITATIVE_TIMESTAMP", "VENDOR_TZ_TIMESTAMP"}),
    "provider_available_time": frozenset({"VENDOR_STAMPED", "FILE_DROP"}),
}
BOUND_DERIVATIONS = {
    "public_available_upper_bound": frozenset(
        {"DATE_PLUS_LAG", "SESSION_CLOSE_PLUS_LAG", "FIRST_SEEN_UPPER_BOUND"}
    ),
    "provider_available_upper_bound": frozenset({"FIRST_SEEN_UPPER_BOUND", "DELIVERY_WINDOW"}),
}

#: Fields that belong to the source envelope and must never be demanded of a derived artifact.
SOURCE_ONLY_FIELDS = (
    "public_available_time",
    "public_available_upper_bound",
    "provider_available_time",
    "provider_available_upper_bound",
    "system_first_seen_time",
)

#: Names retired by a later revision, with the replacement. A hit outside an explicit
#: "retired"/"never"/"revision N" note is a document that did not get the memo.
RETIRED_NAMES = {
    "source_available_time": "public/provider/system_first_seen (revision 2)",
    "availability_derivation": "public_time_derivation / public_bound_derivation (revision 5)",
    "provider_availability_derivation": (
        "provider_time_derivation / provider_bound_derivation (revision 5)"
    ),
    "information_set_profile": "requested_profile / resolved_profile (revision 5)",
    "DECLARE": "EXCLUDE / BOUND / DOWNGRADE (revision 3)",
}

#: A retired name is allowed where its retirement is explained. Prose wraps, so the marker is
#: often on a neighbouring line rather than the one carrying the name -- hence the window.
RETIREMENT_MARKERS = (
    "retired",
    "withdraw",
    "never declare",
    "never the ambiguous",
    "no longer exists",
    "no longer carries",
    "revision 1",
    "revision 2",
    "revision 3",
    "revision 4",
    "revision 5",
    "first draft",
    "requesting",
    "superseded",
)

#: How many lines either side of a hit are searched for a retirement marker.
MARKER_WINDOW = 2


@dataclass
class Findings:
    """Accumulates audit failures, grouped by the check that produced them."""

    failures: list[str] = field(default_factory=list)
    checks_run: int = 0

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks_run += 1
        if ok:
            print(f"  OK  : {name}")
        else:
            print(f"  FAIL: {name}{(' -- ' + detail) if detail else ''}")
            self.failures.append(name)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def code_tokens(text: str) -> set[str]:
    """Every backtick-quoted token in a document."""
    return set(re.findall(r"`([A-Za-z_][A-Za-z0-9_.]*)`", text))


def entity_headings(schema: str) -> list[tuple[str, str]]:
    """Return (entity_name, heading_line) for each schema entity."""
    out: list[tuple[str, str]] = []
    for line in schema.splitlines():
        m = re.match(r"^## \d+[a-e]?\. `([a-z_]+)`(.*)$", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def entity_body(schema: str, entity: str) -> str:
    """The markdown between an entity heading and the next ## heading."""
    pattern = re.compile(
        r"^## \d+[a-e]?\. `" + re.escape(entity) + r"`.*?$(.*?)(?=^## )", re.M | re.S
    )
    m = pattern.search(schema)
    return m.group(1) if m else ""


def lines_with(text: str, needle: str) -> Iterable[tuple[int, str]]:
    for i, line in enumerate(text.splitlines(), 1):
        if needle in line:
            yield i, line


def main() -> int:
    print("KalpaMani Phase 3 documentation-consistency audit")
    print("Planning documents only. No runtime behaviour is exercised.\n")

    missing = [p for p in AUDITED if not p.exists()]
    if missing:
        for p in missing:
            print(f"  FAIL: missing document {p.relative_to(REPO_ROOT)}")
        return 1

    contract, schema, quality, manifest = (
        read(CONTRACT),
        read(SCHEMA),
        read(QUALITY),
        read(MANIFEST),
    )
    everything = {p: read(p) for p in AUDITED}
    f = Findings()

    # ---------------------------------------------------------------- 1. vocabularies
    print("[1/6] Closed vocabularies are defined where they are used")
    schema_tokens = code_tokens(schema)
    for name, vocab in (
        ("information_origin", INFORMATION_ORIGINS),
        ("temporal_fact_class", TEMPORAL_CLASSES),
        ("output_validity", OUTPUT_VALIDITIES),
        ("information_set_profile", PROFILES),
        ("revision_view", REVISION_VIEWS),
    ):
        undefined = sorted(v for v in vocab if v not in schema_tokens)
        f.check(f"schema defines every {name} value", not undefined, ", ".join(undefined))

    quality_tokens = code_tokens(quality)
    referenced = quality_tokens & (
        INFORMATION_ORIGINS | TEMPORAL_CLASSES | OUTPUT_VALIDITIES | PROFILES | GAP_POLICIES
    )
    unknown = sorted(referenced - schema_tokens - GAP_POLICIES)
    f.check(
        "every enum value a quality check names exists in the schema",
        not unknown,
        ", ".join(unknown),
    )

    # ---------------------------------------------------------------- 2. envelopes
    print("\n[2/6] Source and derived envelopes stay disjoint")
    derived_entities = [
        name for name, head in entity_headings(schema) if "DERIVED_ARTIFACT" in head
    ]
    f.check(
        "at least one derived entity is declared",
        bool(derived_entities),
        "none found",
    )
    leaks: list[str] = []
    for entity in derived_entities:
        body = entity_body(schema, entity)
        for fld in SOURCE_ONLY_FIELDS:
            # A derived entity may *mention* a source field to forbid it; a table row that
            # defines it as a column is the defect.
            if any(True for _ in lines_with(body, f"| `{fld}`")):
                leaks.append(f"{entity}.{fld}")
    f.check(
        "no derived entity defines a source-envelope field",
        not leaks,
        ", ".join(sorted(set(leaks))),
    )

    both = [
        name
        for name, head in entity_headings(schema)
        if "DERIVED_ARTIFACT" in head and any(c in head for c in TEMPORAL_CLASSES)
    ]
    f.check(
        "no derived entity declares a source temporal class",
        not both,
        ", ".join(both),
    )

    # ---------------------------------------------------------------- 3. anchors
    print("\n[3/6] Every declared temporal semantics has its required anchor")
    anchorless: list[str] = []
    for entity, head in entity_headings(schema):
        body = entity_body(schema, entity)
        for cls, anchor in CLASS_ANCHOR.items():
            if cls in head and anchor not in body and "per row" not in head:
                anchorless.append(f"{entity} declares {cls} without {anchor}")
        for validity, fld in VALIDITY_FIELD.items():
            if validity in head and fld not in body:
                anchorless.append(f"{entity} declares {validity} without {fld}")
    f.check(
        "declared class or validity always has its anchor field",
        not anchorless,
        "; ".join(anchorless),
    )

    # ---------------------------------------------------------------- 4. exact vs bound
    print("\n[4/6] Exact and bound derivations name the correct fields")
    crossed: list[str] = []
    for exact_field, exact_vocab in EXACT_DERIVATIONS.items():
        bound_field = exact_field.replace("_time", "_upper_bound")
        bound_vocab = BOUND_DERIVATIONS[bound_field]
        overlap = exact_vocab & bound_vocab
        if overlap:
            crossed.append(f"{exact_field}/{bound_field} share {sorted(overlap)}")
    f.check("exact and bound vocabularies do not overlap", not crossed, "; ".join(crossed))

    ladder = contract[contract.find("### 5.1") : contract.find("### 5.3")]
    lag_in_exact = [
        line
        for _, line in lines_with(ladder, "public_available_time")
        if "DATE_PLUS_LAG" in line or "SESSION_CLOSE_PLUS_LAG" in line
    ]
    f.check(
        "no lag derivation writes an exact public field in the ladder",
        not lag_in_exact,
        f"{len(lag_in_exact)} line(s)",
    )

    for fld, vocab in list(EXACT_DERIVATIONS.items()) + list(BOUND_DERIVATIONS.items()):
        absent = sorted(v for v in vocab if v not in schema_tokens)
        f.check(f"schema defines every derivation for {fld}", not absent, ", ".join(absent))

    # ---------------------------------------------------------------- 5. retired names
    print("\n[5/6] No document refers to a retired field name")
    for old, replacement in RETIRED_NAMES.items():
        offenders: list[str] = []
        for path, text in everything.items():
            doc_lines = text.splitlines()
            for lineno, _ in lines_with(text, old):
                lo = max(0, lineno - 1 - MARKER_WINDOW)
                hi = min(len(doc_lines), lineno + MARKER_WINDOW)
                window = " ".join(doc_lines[lo:hi]).lower()
                if any(marker in window for marker in RETIREMENT_MARKERS):
                    continue
                offenders.append(f"{path.name}:{lineno}")
        f.check(
            f"'{old}' appears only where its retirement is explained  (-> {replacement})",
            not offenders,
            ", ".join(offenders[:6]),
        )

    # ---------------------------------------------------------------- 6. manifest
    print("\n[6/6] Manifest rules match the current field names")
    required_manifest_keys = (
        "requested_profile",
        "resolved_profile",
        "global_profile_resolution",
        "dataset_provider_gap_resolutions",
        "resolution_policy_version",
        "artifact_first_built_time",
        "derivation_spec_version",
    )
    absent_keys = [k for k in required_manifest_keys if k not in manifest]
    f.check(
        "manifest records every field the contract requires",
        not absent_keys,
        ", ".join(absent_keys),
    )

    m = re.search(r"manifest_version:\s*(\d+)", manifest)
    f.check("manifest declares a version", m is not None, "no manifest_version found")
    if m and int(m.group(1)) < 3:
        f.check("manifest_version reflects the current schema", False, m.group(0))
    elif m:
        f.check("manifest_version reflects the current schema", True)

    f.check(
        "ADR-0005 is still Proposed",
        "**Status:** **Proposed**" in everything[ADR],
        "status changed",
    )

    # ---------------------------------------------------------------- verdict
    print(f"\n{f.checks_run} checks run.")
    if f.failures:
        print(f"AUDIT FAILED -- {len(f.failures)} inconsistency(ies):")
        for name in f.failures:
            print(f"  - {name}")
        return 1
    print("AUDIT PASSED. The Phase-3 planning documents are mutually consistent.")
    print("This says nothing about the data, because there is no data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
