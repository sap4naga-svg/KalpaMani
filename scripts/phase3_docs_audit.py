"""Phase 3 documentation-consistency audit.

Phase 3 is a **plan**, not an implementation. There is no ingestion code, no database and no
data, so nothing here can be checked against runtime behaviour. What *can* be checked
deterministically is whether the plan agrees with itself: whether a quality check names an enum
value the schema actually defines, whether a derived artifact is required to carry a field the
contract says it must not have, whether a temporal class is declared without the anchor it
needs, and whether any document still refers to a field name a later revision retired.

Those are exactly the defects the review rounds kept finding by hand. This script finds them by
running.

It reads `docs/phase3/` (including the G1/G3 provider decision packet and its clarification
draft), the point-in-time, blueprint-adoption and cloud-data-plane ADRs, `docs/architecture/`,
the vendor cloud-deletion runbook, `CLAUDE.md` and `README.md`. It touches no runtime code,
opens no network connection, and asserts nothing about data. Exit code 0 means the documents are
consistent on the named properties below; non-zero lists what disagrees. It is a guard over
those properties, not a proof that the design is correct.

**One section reads configuration rather than prose.** ADR-0007 makes claims about a private AWS
research data plane -- no versioning, no Object Lock, no replication, no inbound rule, no IAM
user -- and those claims are only worth anything if the committed Terraform actually says so.
Prose and configuration drift apart silently, and the drift is invisible precisely because
nobody re-reads the `.tf` files when editing an ADR. Section 13 therefore parses
`infra/aws/research-data-plane/*.tf` as text and asserts on what it contains, so a "helpful"
durability improvement that would defeat a vendor deletion obligation fails the audit instead of
merging quietly. It also scans that directory for account ids, access keys and email addresses,
because the same directory is where such a value is most likely to arrive by accident.

That section checks what the configuration *declares*. It does not run Terraform, reach AWS, or
establish that applying it would produce a working or correct system. **No AWS resource exists.**

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
DECISIONS = REPO_ROOT / "docs" / "decisions"
ARCHITECTURE = REPO_ROOT / "docs" / "architecture"
ADR = DECISIONS / "ADR-0005-point-in-time-data-architecture.md"

#: Blueprint V3.0 became repository authority on 2026-08-27 (ADR-0006). The blueprint PDFs are
#: binary and never edited, so the audit checks the text that governs them: the adopting ADR,
#: the adoption record carrying the Document Control override, and the two status documents.
ADR_V3 = DECISIONS / "ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md"
BLUEPRINT_V3 = ARCHITECTURE / "KalpaMani_Blueprint_V3_0.pdf"
BLUEPRINT_V21 = ARCHITECTURE / "KalpaMani_Blueprint_V2_1.pdf"
ADOPTION = ARCHITECTURE / "BLUEPRINT_V3_ADOPTION.md"

#: The G1/G3 decision packet and the licensing-clarification draft. Both are evidence documents
#: that recommend a decision without taking one, and both sit next to a live purchase question.
#: The audit guards the two properties that make them safe to hold in a public repository: they
#: never report a gate as closed, and they never read as authorization to buy or to contact a
#: vendor. The draft additionally has to keep saying it was not sent.
PACKET = PHASE3 / "provider-licensing-decision-packet.md"
CLARIFICATION = PHASE3 / "provider-licensing-clarification-draft.md"

#: Every decision gate that must still read as open. V3 adoption resolved none of them and
#: added two. A gate is "silently resolved" if a document calls it closed/resolved/satisfied.
OPEN_GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
GATE_RESOLVED_WORDS = ("closed", "resolved", "satisfied", "passed", "complete")

#: A resolution word only counts as a claim if it is not negated. "no G1-G7 resolved" and
#: "none are closed by V3 adoption" assert the opposite of what the bare word suggests.
GATE_NEGATION = re.compile(r"\b(?:no|not|never|none|nor|un|neither|without)\b[^.]{0,40}$")

#: Wording that would wrongly present V3 as still proposed or non-authoritative. It is legitimate
#: only next to a marker showing the sentence is historical or describes the superseded PDF page.
V3_STALE_STATUS = (
    "v3.0 remains proposed",
    "v3 remains proposed",
    "v3.0 is not repository authority",
    "v3 is not repository authority",
    "adr-0006 does not exist",
)
#: The commit PR #8 was branched from. Merging the adoption PR necessarily advances main, so
#: this SHA is the *adoption base*, never the permanent or current post-adoption main.
ADOPTION_BASE_MAIN = "7e76cce22b98e78071076d04f43a29dc60b0d38c"
BASE_MAIN_QUALIFIER = "adoption base main"

V3_HISTORICAL_MARKERS = (
    "superseded",
    "as printed",
    "historical",
    "before adoption",
    "pre-adoption",
    "at drafting",
    "drafted",
)

#: The cloud-first research data plane (ADR-0007). Two properties have to hold, and they pull in
#: opposite directions: the documents must describe AWS as the *intended* platform without ever
#: reading as though anything exists, and the committed Terraform must *enforce* the deletion-first
#: posture rather than merely describe it. Prose can drift from configuration silently, so the
#: checks below read the `.tf` files as text and assert on what they actually say.
ADR_CLOUD = DECISIONS / "ADR-0007-cloud-first-research-data-plane.md"
DELETION_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "vendor-data-cloud-deletion.md"
INFRA = REPO_ROOT / "infra" / "aws" / "research-data-plane"

#: Every file the scaffold is expected to contain. A missing one is a silent gap in the design.
INFRA_FILES = (
    "README.md",
    "versions.tf",
    "providers.tf",
    "variables.tf",
    "main.tf",
    "outputs.tf",
    "storage.tf",
    "iam.tf",
    "network.tf",
    "ecr.tf",
    "ecs.tf",
    "logging.tf",
    "terraform.tfvars.example",
)

#: Terraform constructs that must never appear. Each one either creates a copy a vendor deletion
#: obligation would have to reach, opens an inbound path, or mints a long-lived human credential.
FORBIDDEN_TERRAFORM = {
    "object_lock": "Object Lock makes deletion impossible until expiry, including for the root",
    "aws_s3_bucket_replication_configuration": "replication creates a copy elsewhere",
    "aws_nat_gateway": "an always-on NAT Gateway contradicts the near-zero-idle-cost objective",
    "aws_lb": "no load balancer: nothing accepts inbound connections",
    "aws_iam_user": "no IAM user: roles issue short-lived credentials instead",
    "aws_iam_access_key": "no long-lived access key may be created by Terraform",
    "aws_vpc_security_group_ingress_rule": "the task security group admits nothing",
    "aws_ecs_service": "compute is ephemeral; a service is an always-on workload",
    "GLACIER": "an archival transition makes provable deletion slow and expensive",
    'sse_algorithm = "aws:kms"': "not wrong, but a KMS key is a governed change, not a default",
    # S3 Bucket Keys reduce KMS API calls, so they apply to SSE-KMS only. Setting one
    # alongside AES256 declares an optimization for a service the bucket never calls:
    # harmless at runtime, and a false statement about how the data is encrypted.
    "bucket_key_enabled": "Bucket Keys are an SSE-KMS feature; under SSE-S3 they mean nothing",
}

#: Secret-shaped material that must never be committed under infra/. The account-id pattern is the
#: one most likely to arrive by accident, pasted from a console URL or an ARN.
SECRET_PATTERNS = {
    "AWS access key id": re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA)[A-Z0-9]{16}\b"),
    "12-digit AWS account id": re.compile(r"(?<![\d.])\d{12}(?![\d.])"),
    "email address": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "secret access key assignment": re.compile(r"(?i)secret_access_key\s*=\s*\"[^\"]"),
    "session token assignment": re.compile(r"(?i)session_token\s*=\s*\"[^\"]"),
}

#: Wording that would present the cloud plane as built rather than described. Legitimate only next
#: to a negation -- ADR-0007 itself says the laptop is *not* the authoritative store, and a naive
#: substring scan would trip on exactly the sentence that establishes the property.
PROVISIONED_CLAIMS = (
    "aws resources have been created",
    "aws resources were created",
    "resources have been provisioned",
    "the aws account was created",
    "an aws account exists",
    "terraform has been applied",
    "we applied the terraform",
)

#: Wording that would restore the laptop to authority over Phase-3 production data.
LAPTOP_AUTHORITY_CLAIMS = (
    "laptop is the authoritative",
    "laptop remains the authoritative",
    "local disk is the authoritative",
    "workstation is the authoritative",
    "authoritative long-term licensed-data store",
    "authoritative research store on the laptop",
)

#: A negation anywhere on the line makes a claim above the opposite of a claim.
CLAIM_NEGATION = re.compile(
    r"\b(?:not|never|no|nor|none|neither|rather than|instead of|no longer|without)\b"
)

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
    "no longer exist",
    "no longer carries",
    "replaced",
    "the scalar",
    "withdrawn",
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
    print("[1/13] Closed vocabularies are defined where they are used")
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
    print("\n[2/13] Source and derived envelopes stay disjoint")
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
    print("\n[3/13] Every declared temporal semantics has its required anchor")
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
    print("\n[4/13] Exact and bound derivations name the correct fields")
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

    # ---------------------------------------------------------------- 4a. stale rules
    print("\n[5/13] Normative rules use the current resolved model")

    scalar_offenders: list[str] = []
    for path, text in everything.items():
        doc_lines = text.splitlines()
        for lineno, line in lines_with(text, "profile_resolution"):
            if "global_profile_resolution" in line:
                continue
            lo = max(0, lineno - 1 - MARKER_WINDOW)
            hi = min(len(doc_lines), lineno + MARKER_WINDOW)
            window = " ".join(doc_lines[lo:hi]).lower()
            if any(m in window for m in RETIREMENT_MARKERS):
                continue
            scalar_offenders.append(f"{path.name}:{lineno}")
    f.check(
        "no normative text keeps the scalar profile_resolution fields",
        not scalar_offenders,
        ", ".join(scalar_offenders[:6]),
    )

    failclosed = contract[contract.find("## 10. Fail-closed") : contract.find("## 11.")]
    f.check(
        "contract fail-closed rules use the resolved times",
        "resolved_provider_time" in failclosed and "resolved_public_time" in failclosed,
        "resolved_* absent from section 10",
    )
    f.check(
        "contract fail-closed rules allow a legitimate max() equality",
        "not** refused" in failclosed or "is **not** refused" in failclosed,
        "no carve-out for the equality case",
    )
    f.check(
        "contract fail-closed rules make gap policy per dataset",
        "per dataset" in failclosed,
        "section 10 still reads as run-scoped",
    )

    for label, text in (("contract", contract), ("ADR-0005", everything[ADR])):
        block = text[text.find("source_anchor(record)") :][:700]
        f.check(
            f"{label} source_anchor uses the resolved profile",
            "RESOLVED profile" in block or "resolved profile" in block,
            "still names the requested profile",
        )

    # ---------------------------------------------------------------- 4b. entity shapes
    print("\n[6/13] Entities keep source and derived rows apart")

    mixed: list[str] = []
    for entity, head in entity_headings(schema):
        body = entity_body(schema, entity)
        head_is_source = any(o in head for o in SOURCE_ORIGINS) or "origin per row" in head
        if head_is_source and "DERIVED_ARTIFACT" in body and "not a source fact" not in body:
            # A source entity may reference the derived model in prose; a mapping table row
            # assigning DERIVED_ARTIFACT as a row origin is the defect.
            for _, line in lines_with(body, "DERIVED_ARTIFACT"):
                if line.strip().startswith("|") and "`information_origin`" not in line:
                    mixed.append(f"{entity}: {line.strip()[:60]}")
                    break
    f.check("no source entity maps a row to DERIVED_ARTIFACT", not mixed, "; ".join(mixed))

    adj = entity_body(schema, "adjusted_bar_artifact")
    required_derived = (
        "information_origin",
        "output_validity",
        "valid_time_start",
        "valid_time_end",
        "lineage",
        "artifact_first_built_time",
        "derivation_spec_version",
        "artifact_content_hash",
    )
    absent = [fld for fld in required_derived if f"`{fld}`" not in adj]
    f.check(
        "adjusted_bar_artifact carries a complete derived envelope",
        not absent,
        ", ".join(absent),
    )
    dupes = [n for n in ("built_at", "content_hash") if f"| `{n}` |" in adj]
    f.check(
        "adjusted_bar_artifact has one normative name per field",
        not dupes,
        f"duplicate name(s): {', '.join(dupes)}",
    )

    m_schema = re.search(r"## 7a\. `adjusted_bar_artifact` — `([A-Z_]+)`", schema)
    m_manifest = re.search(
        r"entity: adjusted_bar_artifact\s*\n\s*output_validity: ([A-Z_]+)", manifest
    )
    f.check(
        "adjusted artifact output_validity agrees between schema and manifest",
        bool(m_schema and m_manifest and m_schema.group(1) == m_manifest.group(1)),
        f"schema={m_schema.group(1) if m_schema else '?'} "
        f"manifest={m_manifest.group(1) if m_manifest else '?'}",
    )

    unusable: list[str] = []
    for entity, head in entity_headings(schema):
        body = entity_body(schema, entity)
        if "ANNOUNCED_FORWARD" not in head and "ANNOUNCED_FORWARD" not in body:
            continue
        if "`announcement_time` | instant |" in body:
            continue  # non-nullable exact anchor
        if "`announcement_time` | instant? |" in body:
            has_bound = "announcement_time_upper_bound" in body
            # markdown emphasis means the phrase may read "**required** for"
            has_required = "required" in body and " for `" in body
            if not (has_bound or has_required):
                unusable.append(entity)
    f.check(
        "every announced-forward anchor is usable, not merely nullable",
        not unusable,
        ", ".join(unusable),
    )

    # ---------------------------------------------------------------- 4d. resolved semantics
    print("\n[7/13] Unusability is decided by resolved values, not by a derivation")

    rule6 = ""
    for _, line in lines_with(contract, "resolved_public_time` is null"):
        rule6 = line
        break
    f.check(
        "contract fail-closed keys unusability on resolved_public_time",
        bool(rule6),
        "section 10 still blocks on public_time_derivation = UNKNOWN",
    )
    f.check(
        "contract states UNKNOWN alone is not disqualifying",
        "alone is not this rule" in contract or "not by itself disqualifying" in contract,
        "no carve-out for UNKNOWN plus an approved bound",
    )
    f.check(
        "schema envelope rule keys on resolved_public_time",
        "resolved_public_time` is null may never participate" in schema,
        "schema still blocks on the derivation",
    )
    f.check(
        "quality 3.5 keys on the resolved value",
        "`rpub IS NULL`" in quality,
        "structural check still names public_time_derivation = UNKNOWN",
    )
    f.check(
        "ADR states UNKNOWN with an approved bound resolves",
        "does not disqualify a row that has an approved bound" in everything[ADR],
        "ADR still treats UNKNOWN as automatically unusable",
    )

    for label, text in (("contract", contract), ("ADR-0005", everything[ADR])):
        f.check(
            f"{label} defines a resolved announced-forward fact anchor",
            "announced_forward_fact_anchor" in text,
            "fact-time anchor absent",
        )
    f.check(
        "quality class checks read the resolved fact anchors",
        all(
            n in quality
            for n in (
                "retrospective_fact_anchor",
                "announced_forward_fact_anchor",
                "sampled_state_fact_anchor",
            )
        ),
        "4.1.5-4.1.7 still read raw fields",
    )
    f.check(
        "an unapproved fact-anchor bound is BLOCKING",
        "Unapproved fact-anchor bound" in quality,
        "no check for an unapproved announcement bound",
    )
    f.check(
        "domain anchor aliases are declared in a table",
        "Domain aliases are declared, not implied" in contract,
        "aliases only implied by prose",
    )

    # ---------------------------------------------------------------- 4c. manifest shape
    print("\n[8/13] Manifest records per-axis timing and coverage evidence")
    per_axis = (
        "public_exact_rows",
        "public_bounded_rows",
        "provider_exact_rows",
        "provider_bounded_rows",
    )
    absent_axis = [k for k in per_axis if k not in manifest]
    f.check(
        "manifest counts exact and bounded rows per timing axis",
        not absent_axis,
        ", ".join(absent_axis),
    )
    coverage_fields = (
        "coverage_scope",
        "min_coverage_fraction",
        "minimum_observed_partition_coverage",
        "total_partitions",
        "failing_partitions",
        "min_rows",
        "observed_rows",
    )
    absent_cov = [k for k in coverage_fields if k not in manifest]
    f.check(
        "manifest records required-input coverage evidence",
        not absent_cov,
        ", ".join(absent_cov),
    )
    runid_block = manifest[manifest.find("`run_id` is **derived") :][:2400]
    runid_inputs = ("artifact_id", "artifact_content_hash", "derivation_spec_version", "lineage")
    absent_runid = [k for k in runid_inputs if k not in runid_block]
    f.check(
        "run_id derivation names the derived-artifact inputs",
        not absent_runid,
        ", ".join(absent_runid),
    )
    f.check(
        "run_id includes artifact_first_built_time under FORWARD_SYSTEM",
        "artifact_first_built_time" in runid_block and "FORWARD_SYSTEM" in runid_block,
        "first-built history absent from run_id inputs",
    )

    # coverage evidence must be partition-minimum based, and the example must actually pass
    f.check(
        "coverage evidence uses the partition minimum",
        "minimum_observed_partition_coverage" in manifest and "total_partitions" in manifest,
        "still evidenced by an aggregate fraction",
    )
    failing = re.findall(r"failing_partitions:\s*(\d[\d_]*)", manifest)
    nonzero = [v for v in failing if int(v.replace("_", "")) != 0]
    f.check(
        "the example manifest is genuinely a passing one",
        not nonzero,
        f"failing_partitions {', '.join(nonzero)} in an emitted manifest",
    )
    f.check(
        "WHOLE_DOMAIN records a row-count contract",
        "min_rows" in manifest and "observed_rows" in manifest,
        "WHOLE_DOMAIN still evidenced by a fraction",
    )
    f.check(
        "a PER_* input with a failing partition refuses",
        "failing_partitions > 0" in manifest or "failing_partitions > 0" in quality,
        "no refusal condition for a failing partition",
    )
    f.check(
        "WHOLE_DOMAIN below min_rows refuses",
        "observed_rows < min_rows" in manifest or "observed_rows < min_rows" in quality,
        "no refusal condition for a short whole-domain input",
    )

    # price_bar identity and the adjusted-artifact hash name
    bar = entity_body(schema, "price_bar")
    f.check(
        "price_bar keys on a bar endpoint so minute bars cannot collide",
        "`bar_end_time` | instant, **PK part**" in bar,
        "bar_end_time is not part of row identity",
    )
    f.check(
        "price_bar keeps session_date as a calendar join key, not a key part",
        "`session_date` | date |" in bar and "never derived by truncating" in bar,
        "session_date still keyed or derived by truncation",
    )
    f.check(
        "price_bar declares a canonical-versus-source decision",
        "canonical curated Gold record" in bar,
        "multi-provider collision behaviour undefined",
    )
    adj_body = entity_body(schema, "adjusted_bar_artifact")
    f.check(
        "adjusted artifact prose and checks name artifact_content_hash",
        "artifact_content_hash" in adj_body
        and "adjusted_bar_artifact.artifact_content_hash" in quality,
        "old content_hash name survives for the derived artifact",
    )

    # ADR must distinguish the two blocking domains
    f.check(
        "ADR distinguishes unavailable analyst history from unqualified borrow",
        "Not yet QUALIFIED" in everything[ADR]
        and "No credible individual-cost source identified" in everything[ADR],
        "context still implies both are unavailable at individual cost",
    )

    # ---------------------------------------------------------------- 4e. merge closeout
    print("\n[9/13] Resolved-timing wording, closure rules and current status")

    f.check(
        "contract origin table names resolved timing axes",
        "`resolved_public_time` | `resolved_provider_time`" in contract
        or "resolved timing axes, not exact fields" in contract,
        "origin table still requires the exact field",
    )
    f.check(
        "schema origin table names resolved timing axes",
        "resolved public | resolved provider" in schema or "name the *resolved* axes" in schema,
        "schema origin table still requires the exact field",
    )
    unusable_everywhere = [
        f"{p.name}:{n}"
        for p, t in everything.items()
        for n, line in lines_with(t, "unusable everywhere")
        if "only when" not in line and "only if" not in line
    ]
    f.check(
        "no normative text says an unestablished exact time is unusable everywhere",
        not unusable_everywhere,
        ", ".join(unusable_everywhere),
    )
    f.check(
        "backfill admits an approved public bound",
        "approved `public_available_upper_bound`" in contract
        and "not restricted to exactly-timed records" in contract,
        "PUBLIC_PIT backfill still limited to exact timing rules",
    )
    bound_claims = [
        f"{p.name}:{n}"
        for p, t in everything.items()
        for n, line in lines_with(t, "BOUND sets")
        if "upper_bound" not in line and "upper bound" not in line
    ]
    f.check(
        "BOUND is always described as setting an upper bound",
        not bound_claims,
        ", ".join(bound_claims),
    )

    adr_revs = [
        int(m) for m in re.findall(r"^\| (?:\*\*)?([0-9]+)(?:\*\*)? \| ", everything[ADR], re.M)
    ]
    f.check(
        "ADR revision history is numerically ordered",
        adr_revs == sorted(adr_revs) and len(set(adr_revs)) == len(adr_revs),
        f"order: {adr_revs}",
    )

    f.check(
        "manifest states the evidence closure rule",
        "What the evidence must close over" in manifest,
        "no closure rule for direct versus lineage-reached datasets",
    )
    example = manifest[manifest.find("manifest_version:") : manifest.find("### 2a.")]
    resolution_map = re.findall(r"- dataset: ([a-z_]+)", example)
    required_domains = re.findall(r"- domain: ([a-z_]+)", example)
    derived_entities = re.findall(r"entity: ([a-z_]+)", example)
    # Every direct source input must appear in the resolution map, unless it is a derived
    # artifact (pinned by lineage) or a domain the run declared unavailable.
    unavailable = re.search(r"^  unavailable:.*?$(.*?)(?=^  [a-z_]+:)", example, re.S | re.M)
    declared_absent = (
        set(re.findall(r"- domain: ([a-z_]+)", unavailable.group(1))) if unavailable else set()
    )
    unclosed = [
        d
        for d in required_domains
        if d not in resolution_map and d not in derived_entities and d not in declared_absent
    ]
    f.check(
        "example closes over its direct source inputs",
        not unclosed,
        f"absent from the resolution map: {', '.join(unclosed)}",
    )
    f.check(
        "example lists universe_membership as a derived artifact",
        "entity: universe_membership" in example,
        "a DERIVED_ARTIFACT input is missing from derived_artifacts",
    )
    f.check(
        "zero exclusions do not create an exclusion claim",
        not ("ORIGIN_INELIGIBLE_ROWS_EXCLUDED" in example and "origin_exclusions: []" in example),
        "exclusion token emitted against an empty exclusion list",
    )
    f.check(
        "manifest requires positive evidence for every limitation token",
        "Every limitation token needs positive evidence" in manifest,
        "no evidence requirement for tokens",
    )

    for name, path in (
        ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
        ("README.md", REPO_ROOT / "README.md"),
    ):
        text = read(path)
        ok = (
            "PHASE 3 PLANNING" in text.upper()
            and "ACCEPTED" in text.upper()
            and "NOT AUTHORIZED" in text.upper()
        )
        f.check(f"{name} says planning accepted, implementation unauthorized", ok, "status wording")

    # ---------------------------------------------------------------- 5. retired names
    print("\n[10/13] No document refers to a retired field name")
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
    print("\nManifest field-name conformance")
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
    if m and int(m.group(1)) < 5:
        f.check("manifest_version reflects the current schema", False, m.group(0))
    elif m:
        f.check("manifest_version reflects the current schema", True)

    # ---------------------------------------------------------------- 7. blueprint authority
    print("\n[11/13] Blueprint V3.0 adoption is recorded consistently")

    f.check(
        "Blueprint V3.0 exists at the authoritative path",
        BLUEPRINT_V3.is_file(),
        f"missing: {BLUEPRINT_V3}",
    )
    f.check(
        "Blueprint V2.1 is preserved, not deleted",
        BLUEPRINT_V21.is_file(),
        f"missing: {BLUEPRINT_V21}",
    )
    f.check("ADR-0006 exists", ADR_V3.is_file(), f"missing: {ADR_V3}")
    f.check("the adoption record exists", ADOPTION.is_file(), f"missing: {ADOPTION}")

    if ADR_V3.is_file() and ADOPTION.is_file():
        adr6 = read(ADR_V3)
        adoption = read(ADOPTION)
        claude_md = read(REPO_ROOT / "CLAUDE.md")
        readme = read(REPO_ROOT / "README.md")

        f.check(
            "ADR-0006 is Accepted",
            "**Status:** **Accepted**" in adr6,
            "ADR-0006 does not declare Accepted status",
        )

        # The authority order must name V3.0 first, and must not still name V2.1 first.
        authority = re.search(r"^1\. \*\*Blueprint ([^*]+)\*\*", claude_md, re.M)
        f.check(
            "CLAUDE.md names Blueprint V3.0 first in the authority order",
            authority is not None and authority.group(1).strip() == "V3.0",
            f"authority slot 1 is {authority.group(1).strip() if authority else 'absent'}",
        )
        f.check(
            "CLAUDE.md records that V2.1 is preserved as historical evidence",
            "historical architecture evidence and is not deleted" in claude_md,
            "no V2.1 preservation note",
        )
        f.check(
            "README names Blueprint V3.0 as the current authority",
            "Blueprint V3.0 \u2192 approved ADRs" in readme,
            "README authority order still names V2.1",
        )

        # Adoption must not be presented as a phase milestone.
        f.check(
            "no document presents V3 adoption as Phase 3 completion",
            all(
                "PHASE 3 OVERALL" not in t.upper() or "NOT COMPLETE" in t.upper()
                for t in (claude_md, readme)
            )
            and "Phase 3 overall NOT COMPLETE" in readme,
            "a status document stopped saying Phase 3 is incomplete",
        )
        f.check(
            "the adoption record states adoption grants no implementation authority",
            "grants **no** implementation" in adoption or "no** implementation" in adoption,
            "adoption record does not disclaim implementation authority",
        )
        for name, t in (("CLAUDE.md", claude_md), ("README.md", readme)):
            f.check(
                f"{name} still withholds authority for later phases",
                "NOT AUTHORIZED" in t.upper(),
                "authorization wording disappeared",
            )

        # ADR-0005 must not have been swept along by adopting V3.
        f.check(
            "ADR-0005 is still Proposed after V3 adoption",
            "**Status:** **Proposed**" in everything[ADR],
            "ADR-0005 status changed",
        )

        # No gate may be silently marked resolved.
        gate_offenders: list[str] = []
        gate_scanned = [ADR_V3, ADOPTION, REPO_ROOT / "CLAUDE.md", REPO_ROOT / "README.md"]
        gate_scanned += [p for p in (ADR_CLOUD, DELETION_RUNBOOK) if p.is_file()]
        for path in gate_scanned:
            body = read(path)
            for lineno, line in enumerate(body.splitlines(), 1):
                low = line.lower()
                if "open" in low:
                    continue
                for gate in OPEN_GATES:
                    if not re.search(rf"\b{gate.lower()}\b", low):
                        continue
                    for word in GATE_RESOLVED_WORDS:
                        at = low.find(word)
                        if at < 0 or GATE_NEGATION.search(low[:at]):
                            continue
                        gate_offenders.append(f"{path.name}:{lineno} ({gate}: {word})")
                        break
        f.check(
            "no open gate G1-G7 is marked resolved",
            not gate_offenders,
            ", ".join(gate_offenders[:6]),
        )
        for gate in OPEN_GATES:
            f.check(
                f"{gate} is recorded OPEN",
                re.search(rf"\*\*{gate}\*\*|{gate}\b", adr6) is not None,
                f"{gate} is not mentioned in ADR-0006",
            )
        f.check(
            "ADR-0006 states all seven gates are open",
            "G1\u2013G7 are all OPEN" in adr6 or "G1-G7 are all OPEN" in adr6,
            "no explicit all-gates-open statement",
        )

        # Stale proposal wording may survive only where it is explicitly labelled historical.
        stale: list[str] = []
        for path in (ADR_V3, ADOPTION, REPO_ROOT / "CLAUDE.md", REPO_ROOT / "README.md"):
            doc_lines = read(path).splitlines()
            for lineno, line in enumerate(doc_lines, 1):
                if not any(s in line.lower() for s in V3_STALE_STATUS):
                    continue
                lo = max(0, lineno - 1 - MARKER_WINDOW)
                hi = min(len(doc_lines), lineno + MARKER_WINDOW)
                window = " ".join(doc_lines[lo:hi]).lower()
                if not any(m in window for m in V3_HISTORICAL_MARKERS):
                    stale.append(f"{path.name}:{lineno}")
        f.check(
            "no document says V3 is still proposed outside labelled historical context",
            not stale,
            ", ".join(stale[:6]),
        )

        # The adoption base SHA is repository state, not a permanent architecture input.
        unqualified: list[str] = []
        for path in (ADR_V3, ADOPTION):
            for lineno, line in enumerate(read(path).splitlines(), 1):
                if ADOPTION_BASE_MAIN in line and BASE_MAIN_QUALIFIER not in line.lower():
                    unqualified.append(f"{path.name}:{lineno}")
        f.check(
            "the adoption base SHA is never called the current/permanent main",
            not unqualified,
            ", ".join(unqualified[:6]),
        )
        for name, doc in (("ADR-0006", adr6), ("the adoption record", adoption)):
            f.check(
                f"{name} names the merge of PR #8 as the effective adoption event",
                "merge of PR #8" in doc,
                "no effective-adoption-event statement",
            )

        # Live trading must not have been loosened by a documentation change.
        f.check(
            "live trading is still recorded hard-disabled",
            "HARD-DISABLED" in claude_md.upper() and "HARD-DISABLED" in readme.upper(),
            "hard-disabled wording missing",
        )

    # ------------------------------------------------- 8. provider decision packet
    print("\n[12/13] The provider decision packet decides nothing and closes no gate")

    f.check(
        "the G1/G3 decision packet exists",
        PACKET.is_file(),
        f"missing: {PACKET}",
    )
    f.check(
        "the licensing-clarification draft exists",
        CLARIFICATION.is_file(),
        f"missing: {CLARIFICATION}",
    )

    if PACKET.is_file() and CLARIFICATION.is_file():
        packet = read(PACKET)
        draft = read(CLARIFICATION)

        # The packet recommends; it does not decide. Every gate must still read OPEN in it.
        for gate in OPEN_GATES:
            f.check(
                f"the packet records {gate} OPEN",
                re.search(
                    rf"\*\*{gate}\*\*[^|\n]*\|\s*\*\*OPEN|{gate}\b[^.\n]{{0,40}}\bOPEN\b", packet
                )
                is not None,
                f"{gate} is not recorded OPEN in the packet",
            )
        f.check(
            "the packet states G1 and G3 are not closed",
            "G1 remains OPEN" in packet and "G3 remains OPEN" in packet,
            "the packet does not disclaim closing G1/G3",
        )
        f.check(
            "the packet leaves ADR-0005 proposed",
            "ADR-0005 remains PROPOSED" in packet,
            "the packet does not record ADR-0005 as still Proposed",
        )
        f.check(
            "the packet records that nothing was purchased or credentialed",
            "Nothing has been purchased, trialled or credentialed" in packet,
            "no purchase/credential disclaimer",
        )
        f.check(
            "the packet records that no vendor data was retrieved",
            "No vendor data has been retrieved" in packet,
            "no vendor-data disclaimer",
        )
        f.check(
            "the packet keeps live trading hard-disabled",
            "HARD-DISABLED" in packet.upper(),
            "live-trading wording missing from the packet",
        )
        f.check(
            "the packet's recommendation is one of the four defined categories",
            any(
                cat in packet
                for cat in (
                    "READY TO REQUEST PURCHASE/TRIAL AUTHORIZATION",
                    "NEED WRITTEN LICENSING CLARIFICATION FIRST",
                    "QUALIFY A DIFFERENT PROVIDER FIRST",
                    "MORE PUBLIC RESEARCH REQUIRED",
                )
            ),
            "no A/B/C/D recommendation category found",
        )

        # The draft is a draft. It must keep saying so, in its status and in its own body.
        f.check(
            "the clarification draft is marked not sent",
            "NOT SENT" in draft.upper(),
            "the draft does not declare itself unsent",
        )
        f.check(
            "the clarification draft records that no provider was contacted",
            "NO PROVIDER HAS BEEN CONTACTED" in draft.upper(),
            "the draft does not disclaim provider contact",
        )
        f.check(
            "the clarification draft withholds authority to send itself",
            "does not authorize sending it" in draft,
            "the draft does not disclaim authorization to send",
        )

        # Neither document may read as authorization. This is the property that matters most.
        for name, doc in (("the packet", packet), ("the clarification draft", draft)):
            f.check(
                f"{name} withholds authorization",
                "NOT AUTHORIZED" in doc.upper() or "not authorize" in doc,
                "authorization disclaimer missing",
            )

    # ------------------------------------------- 9. cloud-first research data plane
    print("\n[13/13] The cloud data plane is described, not built -- and the Terraform enforces it")

    f.check("ADR-0007 exists", ADR_CLOUD.is_file(), f"missing: {ADR_CLOUD}")
    f.check(
        "the vendor cloud-deletion runbook exists",
        DELETION_RUNBOOK.is_file(),
        f"missing: {DELETION_RUNBOOK}",
    )
    f.check("the Terraform scaffold directory exists", INFRA.is_dir(), f"missing: {INFRA}")

    if ADR_CLOUD.is_file() and DELETION_RUNBOOK.is_file() and INFRA.is_dir():
        adr7 = read(ADR_CLOUD)
        runbook = read(DELETION_RUNBOOK)
        claude_md = read(REPO_ROOT / "CLAUDE.md")
        readme = read(REPO_ROOT / "README.md")
        infra_readme = read(INFRA / "README.md") if (INFRA / "README.md").is_file() else ""

        # -- the ADR decides a platform and nothing else --------------------------
        f.check(
            "ADR-0007 is accepted on merge rather than silently already in force",
            "Accepted — effective on the merge" in adr7,
            "ADR-0007 does not state its effective condition",
        )
        f.check(
            "ADR-0007 states that no AWS resource exists",
            "No AWS resource exists" in adr7,
            "ADR-0007 does not disclaim existing resources",
        )
        for name, doc in (
            ("ADR-0007", adr7),
            ("the deletion runbook", runbook),
            ("the infra README", infra_readme),
        ):
            f.check(
                f"{name} withholds authorization",
                "NOT AUTHORIZED" in doc.upper() or "not authorize" in doc,
                "authorization disclaimer missing",
            )
        f.check(
            "ADR-0007 keeps every gate open",
            "Gates G1\u2013G7 are all OPEN" in adr7 or "G1-G7 are all OPEN" in adr7,
            "no explicit all-gates-open statement in ADR-0007",
        )
        f.check(
            "ADR-0007 leaves ADR-0005 proposed",
            "remains PROPOSED" in adr7,
            "ADR-0007 does not record ADR-0005 as still Proposed",
        )
        f.check(
            "ADR-0007 selects no provider",
            "does not select Sharadar" in adr7 or "and does not select Sharadar" in adr7,
            "ADR-0007 does not disclaim provider selection",
        )
        f.check(
            "ADR-0007 keeps live trading hard-disabled",
            "HARD-DISABLED" in adr7.upper(),
            "live-trading wording missing from ADR-0007",
        )
        f.check(
            "the deletion runbook declares itself unexecuted",
            "NOT EXECUTED" in runbook.upper(),
            "the runbook does not declare itself unexecuted",
        )

        # -- nothing may read as though the cloud plane is built ------------------
        cloud_docs = {
            "ADR-0007": adr7,
            "runbook": runbook,
            "infra/README.md": infra_readme,
            "CLAUDE.md": claude_md,
            "README.md": readme,
            "implementation-plan.md": everything[PHASE3 / "implementation-plan.md"],
        }
        built: list[str] = []
        for name, doc in cloud_docs.items():
            for lineno, line in enumerate(doc.splitlines(), 1):
                low = line.lower()
                for claim in PROVISIONED_CLAIMS:
                    if claim in low and not CLAIM_NEGATION.search(low):
                        built.append(f"{name}:{lineno}")
                        break
        f.check(
            "no document claims AWS resources exist or that Terraform was applied",
            not built,
            ", ".join(built[:6]),
        )

        # `terraform apply` is the most consequential phrase in this change: it is the one that
        # spends money and creates resources. Any document that raises it must also refuse it.
        #
        # Deliberately a DOCUMENT-level property, not a line-level one. An earlier version
        # required the refusal on the same line and failed against five perfectly correct
        # sentences whose refusal was simply the previous line -- "it does not: ... authorize
        # `terraform apply`". A guard that a correctly-written document cannot satisfy trains
        # people to weaken the guard. Whitespace is flattened so a refusal split across a line
        # break still counts.
        unrefused_apply: list[str] = []
        refusal = re.compile(
            r"(?i)(?:not\s+authoriz|does\s+not\s+authoriz|never\s+been\s+applied"
            r"|requires\s+(?:its\s+own|explicit)|separate\w*[^.]{0,40}authoriz)"
        )
        for name, doc in cloud_docs.items():
            if "terraform apply" not in doc.lower():
                continue
            if not refusal.search(re.sub(r"\s+", " ", doc)):
                unrefused_apply.append(name)
        f.check(
            "every document mentioning terraform apply also refuses it",
            not unrefused_apply,
            ", ".join(unrefused_apply),
        )

        laptop: list[str] = []
        for name, doc in cloud_docs.items():
            for lineno, line in enumerate(doc.splitlines(), 1):
                low = line.lower()
                for claim in LAPTOP_AUTHORITY_CLAIMS:
                    if claim in low and not CLAIM_NEGATION.search(low):
                        laptop.append(f"{name}:{lineno}")
                        break
        f.check(
            "no document calls the laptop the authoritative Phase-3 production data store",
            not laptop,
            ", ".join(laptop[:6]),
        )

        for name, doc in (("CLAUDE.md", claude_md), ("README.md", readme)):
            f.check(
                f"{name} records the AWS account as not created",
                re.search(r"AWS account.*NOT CREATED", doc) is not None,
                "no not-created statement for the AWS account",
            )

        # -- the Terraform enforces the posture, rather than the prose describing it --
        missing_infra = [n for n in INFRA_FILES if not (INFRA / n).is_file()]
        f.check(
            "the Terraform scaffold has every expected file",
            not missing_infra,
            ", ".join(missing_infra),
        )

        tf_files = sorted(INFRA.glob("*.tf"))
        tf_text = "\n".join(read(p) for p in tf_files)
        all_infra = sorted(p for p in INFRA.iterdir() if p.is_file())
        all_infra_text = "\n".join(read(p) for p in all_infra)

        # A forbidden construct is allowed to be *named* in a comment explaining why it is absent.
        # Only a real HCL usage counts, so comment lines are stripped before the scan.
        hcl_only = "\n".join(
            line for line in tf_text.splitlines() if not line.lstrip().startswith("#")
        )
        for token, why in FORBIDDEN_TERRAFORM.items():
            f.check(
                f"Terraform declares no {token}",
                token.lower() not in hcl_only.lower(),
                why,
            )

        f.check(
            "the licensed bucket has versioning disabled",
            re.search(
                r'aws_s3_bucket_versioning"\s+"licensed".*?status\s*=\s*"Disabled"',
                tf_text,
                re.S,
            )
            is not None,
            "licensed-bucket versioning is not explicitly Disabled",
        )
        for flag in (
            "block_public_acls",
            "block_public_policy",
            "ignore_public_acls",
            "restrict_public_buckets",
        ):
            f.check(
                f"both buckets set {flag} = true",
                len(re.findall(rf"{flag}\s*=\s*true", tf_text)) == 2,
                f"expected 2 occurrences, found {len(re.findall(rf'{flag}s*=s*true', tf_text))}",
            )
        f.check(
            "both buckets deny non-TLS requests",
            len(re.findall(r'variable\s*=\s*"aws:SecureTransport"', tf_text)) == 2,
            "a bucket is missing its TLS-only policy",
        )
        f.check(
            "both buckets enforce bucket-owner ownership, disabling ACLs",
            len(re.findall(r'object_ownership\s*=\s*"BucketOwnerEnforced"', tf_text)) == 2,
            "a bucket still permits ACLs",
        )
        f.check(
            "both buckets encrypt at rest",
            len(re.findall(r"apply_server_side_encryption_by_default", tf_text)) == 2,
            "a bucket has no default encryption",
        )
        f.check(
            "the task security group declares no ingress block",
            re.search(r"resource\s+\"aws_security_group\".*?\n\s*ingress\s*\{", tf_text, re.S)
            is None,
            "an inbound rule appeared; ADR-0007 §6 depends on there being none",
        )
        f.check(
            "the licensed bucket aborts incomplete multipart uploads",
            "abort_incomplete_multipart_upload" in tf_text,
            "incomplete-upload parts would survive a list-and-delete deletion",
        )
        f.check(
            "the container registry uses immutable tags",
            'image_tag_mutability = "IMMUTABLE"' in tf_text,
            "a mutable tag breaks the link between an image and the results it produced",
        )
        f.check(
            "the container registry scans images on push",
            re.search(r"scan_on_push\s*=\s*true", tf_text) is not None,
            "image scanning is off",
        )
        f.check(
            "no IAM policy grants a wildcard action",
            re.search(r'actions\s*=\s*\[\s*"\*"', tf_text) is None and '"*:*"' not in tf_text,
            "a wildcard action appeared in an IAM policy",
        )
        # -- wrong-account protection must fail closed ----------------------------
        #
        # This is the check with the most history behind it. The variable originally
        # defaulted to `[]`, which the AWS provider reads as "no restriction" -- so the
        # guard against building KalpaMani in the wrong AWS account was present in the
        # file and inactive in practice. That is the same shape of defect ADR-0003
        # records for broker-side order controls: a safety claim resting on something
        # that is off unless someone remembers to switch it on.
        #
        # Both halves matter. Without the no-default rule, omission silently disables
        # the check; without the digit rule, a placeholder copied out of the `.example`
        # would be accepted and would match no account.
        account_var = re.search(
            r'variable\s+"allowed_account_ids"\s*\{(.*?)\n\}', read(INFRA / "variables.tf"), re.S
        )
        account_body = account_var.group(1) if account_var else ""
        f.check(
            "allowed_account_ids has no default, so omitting it fails closed",
            bool(account_body) and not re.search(r"^\s*default\s*=", account_body, re.M),
            "a default makes wrong-account protection optional",
        )
        f.check(
            "allowed_account_ids rejects an empty list",
            "length(var.allowed_account_ids) >= 1" in account_body,
            "an empty list would disable the provider's account check",
        )
        f.check(
            "allowed_account_ids requires exactly 12 decimal digits per entry",
            r"^[0-9]{12}$" in account_body,
            "a placeholder or malformed id would silently disable the check",
        )
        f.check(
            "the example tfvars placeholder cannot pass account-id validation",
            not re.search(
                r"^\s*allowed_account_ids\s*=\s*\[\s*\"[0-9]{12}\"",
                read(INFRA / "terraform.tfvars.example"),
                re.M,
            ),
            "the example carries something shaped like a real account id",
        )

        f.check(
            "log retention is bounded",
            "retention_in_days" in tf_text and "retention_in_days = 0" not in tf_text,
            "unbounded log retention makes any redaction failure permanent",
        )
        f.check(
            "no secret value is declared in Terraform",
            re.search(r'resource\s+"aws_secretsmanager_secret_version"', tf_text) is None,
            "a secret value would be written to state in plaintext",
        )

        # -- nothing identity-bearing was committed under infra/ ------------------
        for label, pattern in SECRET_PATTERNS.items():
            hits: list[str] = []
            for path in all_infra:
                for lineno, line in enumerate(read(path).splitlines(), 1):
                    if pattern.search(line):
                        hits.append(f"{path.name}:{lineno}")
            f.check(f"no {label} is committed under infra/", not hits, ", ".join(hits[:6]))

        # Only files, and only committable ones. `.terraform/` is a directory that
        # `terraform init` legitimately creates locally and `.gitignore` excludes; an
        # earlier version of this check tested for its ABSENCE ON DISK and therefore
        # started failing the moment anyone actually ran init. Presence on disk was
        # never the property worth guarding -- what must be true is that nothing of
        # this kind can be committed, which the ignore rules below establish.
        stray = sorted(
            p.name
            for p in INFRA.iterdir()
            if p.is_file()
            and (
                p.name.endswith((".tfstate", ".tfplan"))
                or (p.name.endswith(".tfvars") and p.name != "terraform.tfvars.example")
            )
        )
        f.check(
            "no Terraform state, plan or real tfvars file sits in the scaffold",
            not stray,
            ", ".join(stray),
        )
        f.check(
            "the example tfvars carries placeholders rather than values",
            "REPLACE-ME" in all_infra_text,
            "terraform.tfvars.example has no placeholder marker",
        )

        # -- the dependency lock file is committed; state and caches are not -------
        #
        # `.terraform.lock.hcl` is repository metadata, not state: it records which
        # provider build was actually selected and the checksums of its packages, so a
        # later `init` resolves to the same provider instead of whatever is newest that
        # day. Committing it is what makes a supply-chain substitution show up as a
        # diff. It is the one Terraform-generated file that must be tracked, which is
        # exactly why it is easy to sweep into a blanket ignore rule by accident.
        lock = INFRA / ".terraform.lock.hcl"
        gitignore = read(REPO_ROOT / ".gitignore")
        ignore_rules = {
            line.strip() for line in gitignore.splitlines() if not line.strip().startswith("#")
        }

        f.check(
            "the provider dependency lock file is committed",
            lock.is_file(),
            "run `terraform init -backend=false` to generate .terraform.lock.hcl",
        )
        f.check(
            ".gitignore does not exclude the dependency lock file",
            not any("terraform.lock.hcl" in rule for rule in ignore_rules),
            "an ignore rule would keep the lock file out of version control",
        )
        for rule in ("**/.terraform/", "*.tfstate", "*.tfvars", "*.tfplan"):
            f.check(
                f".gitignore still excludes {rule}",
                rule in ignore_rules,
                f"{rule} is no longer ignored",
            )
        f.check(
            ".gitignore keeps the example tfvars committable",
            "!*.tfvars.example" in ignore_rules,
            "the placeholder tfvars would be ignored along with real ones",
        )

        if lock.is_file():
            lock_text = read(lock)
            declared = re.findall(r'^provider\s+"([^"]+)"', lock_text, re.M)
            f.check(
                "the lock file declares only the expected AWS provider",
                declared == ["registry.terraform.io/hashicorp/aws"],
                f"declares {declared}",
            )
            m = re.search(r'version\s*=\s*"(\d+)\.', lock_text)
            f.check(
                "the locked AWS provider is the major this root targets",
                m is not None and m.group(1) == "6",
                f"locked major is {m.group(1) if m else 'absent'}",
            )
            f.check(
                "the lock file carries package checksums",
                "hashes = [" in lock_text and lock_text.count("zh:") >= 5,
                "no checksum block; a lock file without hashes pins nothing",
            )

    # ---------------------------------------------------------------- verdict
    print(f"\n{f.checks_run} checks run.")
    if f.failures:
        print(f"AUDIT FAILED -- {len(f.failures)} inconsistency(ies):")
        for name in f.failures:
            print(f"  - {name}")
        return 1
    print("AUDIT PASSED. All audited consistency properties passed.")
    print("This is a guard over the named properties above, not a proof of the design,")
    print("and it says nothing about the data, because there is no data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
