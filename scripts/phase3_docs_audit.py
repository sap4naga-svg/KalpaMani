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

import ast
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class GitUnavailableError(RuntimeError):
    """git could not enumerate tracked files, so no committed-file claim can be made."""


def tracked_files(directory: Path) -> list[Path]:
    """Files under `directory` that git ACTUALLY TRACKS.

    The identifier and stray-file scans below must test what is *committed*, not what
    happens to sit on disk. Once the foundation was provisioned, operating it requires a
    real, git-ignored `terraform.tfvars` in the scaffold -- carrying, by design, the
    account id whose commitment those scans exist to prevent.

    Scanning the working tree would therefore fail on precisely the file whose
    git-ignored status is the control working correctly. That is the same mistake an
    earlier revision made with `.terraform/`, and the fix is the same: ask git.
    """
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(REPO_ROOT), "ls-files", "--", str(directory)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # NO WORKING-TREE FALLBACK. Walking the directory is exactly what this function
        # exists to avoid: `infra/` holds a real, git-ignored `terraform.tfvars` carrying
        # the account id, so a fallback would scan the file the ignore rule protects and
        # report the control working as a failure. If git cannot answer, the audit fails.
        raise GitUnavailableError("git ls-files could not enumerate tracked files")
    return sorted((REPO_ROOT / line).resolve() for line in result.stdout.split() if line)


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

#: Every decision gate. Seven of them; **exactly one is closed.**
ALL_GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")

#: The gates that must still read as open. A gate is "silently resolved" if a document calls it
#: closed/resolved/satisfied. **G3 is deliberately absent**: ADR-0008 closed it for Sharadar
#: personal use on 2026-08-27, so scanning for a resolution word next to G3 would now report the
#: recorded decision as a defect.
OPEN_GATES = ("G1", "G2", "G4", "G5", "G6", "G7")

#: Gates that are closed, and by which decision. A blanket "G1-G7 are all OPEN" statement in a
#: CURRENT-status document is now a factual error, and section 14 refuses one.
CLOSED_GATES = {"G3": "ADR-0008"}

#: Negation appearing anywhere earlier in the line. Deliberately looser than
#: ``GATE_NEGATION``: a prohibition on a phrase reads naturally as "no ... <phrase> ...",
#: with the negation far to the left of the quoted claim.
GATE_NEGATION_INLINE = re.compile(
    r"\b(?:no|not|never|none|neither|nor|rather than|instead of|no longer|superseded)\b"
)

#: Statements that were true when written and are now historical. They are legitimate **only**
#: inside an accepted ADR, which the repository never rewrites -- the same rule that keeps a
#: Blueprint PDF unedited. In a current-status document they are simply wrong.
BLANKET_ALL_OPEN = (
    "g1\u2013g7 are all open",
    "g1-g7 are all open",
    "g1\u2013g7 remain open",
    "g1-g7 remain open",
    "g1\u2013g7 are open",
    "g1-g7 are open",
    "g1\u2013g7 decision gates | **open**",
)
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

#: The Sharadar personal-use licensing decision, and the harness it authorizes. The ADR
#: closes exactly one gate; the harness is code and methodology only, never a result.
ADR_LICENCE = DECISIONS / ("ADR-0008-sharadar-personal-use-license-and-private-qualification.md")
QUALIFICATION_HARNESS = REPO_ROOT / "scripts" / "sharadar_private_qualification.py"

#: The provider-realistic implementation authorization (ADR-0009), and the package it authorized.
#: Section 15 exists because this decision **narrowed** a rule rather than removing one: provider
#: code is now allowed, and every clause that keeps it code-only has to survive the next edit.
ADR_IMPLEMENTATION = DECISIONS / "ADR-0009-sharadar-provider-realistic-implementation.md"

#: The bounded-semantics decision and the qualification subscription it authorized (ADR-0010).
#: Section 16 exists because this ADR is the one a later session is most likely to misread: a
#: subscription is now active, and nothing in this repository may yet use it.
ADR_QUALIFICATION = DECISIONS / (
    "ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md"
)
#: The licensed S3 object-store implementation (ADR-0011). Section 17 exists because this ADR
#: is the easiest of all of them to misread as access: a cloud backend now exists in the source
#: tree, and it has no credential, no bucket, no client and no caller.
ADR_OBJECT_STORE = DECISIONS / "ADR-0011-implement-the-licensed-s3-research-object-store.md"
S3_STORE = REPO_ROOT / "src" / "kalpamani" / "data" / "storage" / "s3.py"
PROVIDER_PACKAGE = REPO_ROOT / "src" / "kalpamani" / "data" / "ingest" / "sharadar"
OBJECT_STORE = REPO_ROOT / "src" / "kalpamani" / "data" / "objectstore.py"
PUBLICATION = REPO_ROOT / "src" / "kalpamani" / "data" / "ingest" / "publication.py"
TRANSPORT_TEST = REPO_ROOT / "tests" / "unit" / "test_sharadar_transport.py"
SOURCE_REGISTER = PHASE3 / "provider-source-register.md"

#: Wording that would read as authorization the owner did not give. Checked against the two
#: CURRENT-status documents, where a reader looks first and where an over-claim does real damage.
#:
#: The pairing matters: each phrase is only a defect when it appears **without** a negation to its
#: left, because the same words are exactly how a document correctly states the prohibition.
#:
#: **This list stays global, and three phrases were added on 2026-08-28.**
#:
#: A draft of that day's change removed *"subscription is authorized"* and *"purchase is
#: authorized"* on the grounds that ADR-0010 had made them true. That was the wrong shape of fix.
#: ADR-0010 authorizes **one scoped qualification subscription**, not subscriptions and purchases in
#: general -- and a repository-wide guard must not be weakened to accommodate a scoped decision,
#: because the next provider, the next purchase and the next renewal would inherit the hole. Both
#: phrases are restored, and neither appears in any document: the status tables state the specific
#: authorization instead of the general one, which is what they should have said anyway. Section 16
#: checks ADR-0010's exact authorization matrix, so the narrow permission is enforced by naming it
#: rather than by relaxing this list.
OVERCLAIM_PHRASES = (
    "production ingestion is authorized",
    "subscription is authorized",
    "purchase is authorized",
    "credential setup is authorized",
    "api access is authorized",
    "services data ingestion is authorized",
    "provider selection is closed",
    "g1 is closed",
    "g1 closed",
    "sharadar is the selected production provider",
    "sharadar is selected",
)

#: A document claiming that **this work** created the AWS account. The account pre-dated
#: the work and was configured for the foundation on 2026-08-27, so "CREATED" invents a
#: history -- and "NOT CREATED" is equally wrong, because account existence and foundation
#: provisioning are different facts that must not be collapsed.
#:
#: **Written with explicit word boundaries, and that is the point.** Three earlier copies of
#: this pattern carried literal ASCII backspace bytes (0x08) where `\b` was intended -- which
#: is exactly what `\b` means inside a NON-raw Python string. The compiled pattern then
#: required a control character no document contains, so every guard built on it passed
#: unconditionally, and passed invisibly: the defect renders as ordinary text in a terminal,
#: a diff and a review. One definition now, exercised by a behavioural regression test, with
#: a byte scan refusing 0x08 from returning.
ACCOUNT_CREATED_CLAIM = re.compile(r"AWS account.*\bCREATED\b")


def claims_account_created(text: str) -> bool:
    """True if ``text`` states that an AWS account was created by this work."""
    return ACCOUNT_CREATED_CLAIM.search(text) is not None


#: The provision record. It is the one document that describes real, deployed infrastructure,
#: which makes it the likeliest place for an account id, bucket name or ARN to arrive.
FOUNDATION_STATUS = REPO_ROOT / "docs" / "operations" / "aws-foundation-status.md"
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
#: Wording that was true before 2026-08-27 and is FALSE now. The foundation is provisioned, so a
#: document still saying nothing exists is not cautious -- it is wrong, and wrong in the direction
#: that hides real infrastructure and real (if currently zero) spend from whoever reads it next.
STALE_UNBUILT_CLAIMS = (
    "aws account not created",
    "no aws account has been created",
    "aws resources created    none",
    "no aws resource has been created",
    "never been applied",
    "description only",
)

#: The claims that must NEVER appear, before or after provisioning. Provisioning a platform
#: resolved no gate, selected no provider and retrieved no data; a document drifting into any of
#: these would report authority that was never granted.
USE_CLAIMS = (
    "provider has been selected",
    "sharadar has been selected",
    "provider credential has been issued",
    "vendor data has been retrieved",
    "vendor data has been ingested",
    "ingestion has run",
    "a research image has been pushed",
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


#: Ways a document could assert the very thing corrected on 2026-08-28: that a
#: conflict answer establishes occupancy. A targeted denylist of the defect,
#: matching this file's existing idiom, rather than a heuristic sentence scan --
#: a scan that had to be tuned until the prose passed would be measuring the
#: prose, not the claim.
CONFLICT_AS_OCCUPANCY = (
    "409 means occupied",
    "409 means the name is occupied",
    "409 preconditionfailed",
    "conditionalrequestconflict means occupied",
    "conditionalrequestconflict is an occupied",
    "a 409 is an occupied name",
    "409 or 412",
    "412 or 409",
    "preconditionfailed or conditionalrequestconflict",
    "conditionalrequestconflict, both",
)


def _asserts_conflict_is_occupancy(text: str) -> list[str]:
    """Every defective phrasing a document contains, or an empty list."""
    flat = " ".join(" ".join(line.lstrip("> ") for line in text.splitlines()).split()).lower()
    return [phrase for phrase in CONFLICT_AS_OCCUPANCY if phrase in flat]


def _has_a_loop(path: Path) -> bool:
    """Whether a module contains any loop statement at all.

    Comprehensions are not loops for this purpose: they cannot retry a request,
    which is the thing being ruled out.
    """
    tree = ast.parse(read(path), filename=str(path))
    return any(isinstance(node, ast.While | ast.For | ast.AsyncFor) for node in ast.walk(tree))


def _executable_python(path: Path) -> str:
    """A Python module's code with every docstring removed.

    A guard that scanned raw source would fire on the prose explaining what a
    module refuses to do -- which would either weaken the guard or forbid saying
    why it exists. Unparsing a docstring-stripped tree keeps string literals and
    attribute access, and drops only the narration.
    """
    tree = ast.parse(read(path), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


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


def strip_hcl_comments(text: str) -> str:
    """Drop whole-line `#` comments from Terraform source.

    Necessary rather than fastidious. These files explain at length **why** a
    permission or setting is absent, and to do that they name the exact action or
    argument they do not grant -- ``# NO s3:DeleteObject``, ``# no iam:PassRole``.
    A scan over raw text therefore reports every deliberate, well-documented
    omission as a violation, which would train the next person to delete the
    explanation rather than fix the config.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


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
    print("[1/17] Closed vocabularies are defined where they are used")
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
    print("\n[2/17] Source and derived envelopes stay disjoint")
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
    print("\n[3/17] Every declared temporal semantics has its required anchor")
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
    print("\n[4/17] Exact and bound derivations name the correct fields")
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
    print("\n[5/17] Normative rules use the current resolved model")

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
    print("\n[6/17] Entities keep source and derived rows apart")

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
    print("\n[7/17] Unusability is decided by resolved values, not by a derivation")

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
    print("\n[8/17] Manifest records per-axis timing and coverage evidence")
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
    print("\n[9/17] Resolved-timing wording, closure rules and current status")

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
    print("\n[10/17] No document refers to a retired field name")
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
    print("\n[11/17] Blueprint V3.0 adoption is recorded consistently")

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
        for gate in ALL_GATES:
            f.check(
                f"{gate} is recorded in ADR-0006",
                re.search(rf"\*\*{gate}\*\*|{gate}\b", adr6) is not None,
                f"{gate} is not mentioned in ADR-0006",
            )
        # ADR-0006's all-gates-open statement is HISTORICAL and must survive verbatim.
        # Editing an accepted ADR to agree with a later one would destroy the record of what
        # was decided when; ADR-0008 records the supersession instead (section 14).
        f.check(
            "ADR-0006 preserves its historical all-gates-open statement",
            "G1\u2013G7 are all OPEN" in adr6 or "G1-G7 are all OPEN" in adr6,
            "the as-at-adoption gate statement was rewritten rather than superseded",
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
    print("\n[12/17] The provider decision packet decides nothing and closes no gate")

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
            "the packet states G1 is not closed",
            "G1 remains OPEN" in packet,
            "the packet does not disclaim closing G1",
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
    print("\n[13/17] The cloud data plane is described, not built -- and the Terraform enforces it")

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
        status_doc = read(FOUNDATION_STATUS) if FOUNDATION_STATUS.is_file() else ""

        # -- the ADR decides a platform and nothing else --------------------------
        f.check(
            "ADR-0007 is accepted on merge rather than silently already in force",
            "Accepted — effective on the merge" in adr7,
            "ADR-0007 does not state its effective condition",
        )
        f.check(
            "ADR-0007 carries an implementation-status section rather than a rewritten decision",
            "## Implementation status" in adr7,
            "ADR-0007 has no implementation-status section",
        )
        f.check(
            "ADR-0007 still frames its own text as of its decision date",
            "At the time of this decision, no AWS resource exists" in adr7,
            "the as-of-decision framing was lost",
        )
        f.check(
            "ADR-0007 records that provisioning granted no further authority",
            "Provisioning a platform is not permission to use it" in adr7
            or "authorized nothing" in adr7
            or "still stands and is still refused" in adr7,
            "ADR-0007 does not bound what provisioning authorized",
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
        # Historical, exactly as in ADR-0006 above: true when accepted, superseded for G3 by
        # ADR-0008, and never rewritten.
        f.check(
            "ADR-0007 preserves its historical all-gates-open statement",
            "Gates G1\u2013G7 are all OPEN" in adr7 or "G1-G7 are all OPEN" in adr7,
            "the as-at-decision gate statement was rewritten rather than superseded",
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
            "aws-foundation-status.md": status_doc,
        }
        # A stale claim is legitimate only where the sentence marks itself historical --
        # ADR-0007 deliberately preserves its own as-of-decision wording.
        stale: list[str] = []
        for name, doc in cloud_docs.items():
            for lineno, line in enumerate(doc.splitlines(), 1):
                low = line.lower()
                historical = any(mark in low for mark in V3_HISTORICAL_MARKERS) or (
                    "at the time of this decision" in low or "pre-apply" in low
                )
                for claim in STALE_UNBUILT_CLAIMS:
                    if claim in low and not historical:
                        stale.append(f"{name}:{lineno}")
                        break
        f.check(
            "no document still claims the AWS foundation does not exist",
            not stale,
            ", ".join(stale[:6]),
        )

        overclaim: list[str] = []
        for name, doc in cloud_docs.items():
            for lineno, line in enumerate(doc.splitlines(), 1):
                low = line.lower()
                for claim in USE_CLAIMS:
                    if claim in low and not CLAIM_NEGATION.search(low):
                        overclaim.append(f"{name}:{lineno}")
                        break
        f.check(
            "no document claims a provider, credential, ingestion or image exists",
            not overclaim,
            ", ".join(overclaim[:6]),
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
            # `never been applied` was removed as an accepted refusal: the foundation HAS
            # been applied, so a document satisfying this guard with that phrase would be
            # passing the audit by making a false statement.
            r"(?i)(?:not\s+authoriz|does\s+not\s+authoriz"
            r"|requires\s+(?:its\s+own|their\s+own|explicit)|separate\w*[^.]{0,40}authoriz)"
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
                f"{name} does not claim an AWS account was created",
                not claims_account_created(doc)
                and re.search(r"AWS account.*EXISTING", doc) is not None,
                "account existence and foundation provisioning must not be collapsed",
            )
            f.check(
                f"{name} records the foundation as provisioned",
                "PROVISIONED" in doc,
                "no provisioned statement for the AWS foundation",
            )
            f.check(
                f"{name} still bounds further cloud spend",
                re.search(r"(?i)spend.{0,60}NOT AUTHORIZED", doc) is not None,
                "no statement bounding cloud spend beyond the idle foundation",
            )

        # -- the provision record ------------------------------------------------
        f.check(
            "the AWS foundation status document exists",
            FOUNDATION_STATUS.is_file(),
            f"missing: {FOUNDATION_STATUS}",
        )
        if status_doc:
            for label, needle in (
                ("records the provision date", "2026-08-27"),
                ("records the region", "us-east-1"),
                ("records the Terraform version", "v1.16.0"),
                ("records the AWS provider version", "v6.62.0"),
                ("records remote state as active", "ACTIVE"),
                ("records a configured budget", "budget"),
                ("records a cost anomaly alert", "anomaly"),
                ("records the verification result", "66"),
                ("records that no vendor data exists", "vendor data"),
                ("records that no provider credential exists", "provider credential"),
                ("keeps live trading hard-disabled", "HARD-DISABLED"),
            ):
                f.check(
                    f"the status document {label}", needle in status_doc, f"missing: {needle!r}"
                )

            f.check(
                "the status document records the account as pre-existing",
                "EXISTING" in status_doc and not claims_account_created(status_doc),
                "account existence and foundation provisioning must not be collapsed",
            )
            f.check(
                "the status document records the Terraform state backend verification",
                "State bucket" in status_doc or "state bucket" in status_doc,
                "the state bucket is part of the foundation and must be verified",
            )
            f.check(
                "the status document records fail-closed verification semantics",
                "fails closed" in status_doc.lower(),
                "a verifier whose failure mode is a green tick proves nothing",
            )
            f.check(
                "the status document does not claim resources are free",
                "free at rest" not in status_doc.lower()
                and "not literally guaranteed zero" in status_doc,
                "S3 state storage and lock requests bill; idle cost is near zero, not zero",
            )
            f.check(
                "the empty-bucket claim is scoped to the research-data buckets",
                "research-data" in status_doc.lower(),
                "the Terraform state bucket is not empty and must not be",
            )
            f.check(
                "the status document states the precise deletion-role property",
                all(
                    phrase in status_doc
                    for phrase in (
                        "no human can directly assume it",
                        "no deletion task definition exists",
                        "iam:PassRole",
                    )
                ),
                'the role trusts ecs-tasks.amazonaws.com, so "unassumable" would overstate it',
            )
            f.check(
                "the status document keeps the gates open",
                "OPEN" in status_doc and "PROPOSED" in status_doc,
                "gate or ADR-0005 status missing",
            )
            f.check(
                "the status document separates the smoke test from the deletion rehearsal",
                "not the 15-step" in status_doc.replace("*", "").lower(),
                "the smoke test could be misread as the vendor-termination rehearsal",
            )

            # The scan that matters most: this document describes real infrastructure.
            for label, pattern in SECRET_PATTERNS.items():
                hits = [
                    f"line {n}"
                    for n, line in enumerate(status_doc.splitlines(), 1)
                    if pattern.search(line)
                ]
                f.check(
                    f"the status document contains no {label}",
                    not hits,
                    ", ".join(hits[:6]),
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
        # TRACKED files only -- see `tracked_files`. The git-ignored `terraform.tfvars`
        # holds a real account id by design; finding it here would report the ignore
        # rule working as a failure.
        try:
            all_infra = [p for p in tracked_files(INFRA) if p.is_file()]
            git_ok = True
        except GitUnavailableError:
            all_infra, git_ok = [], False
        f.check(
            "git can enumerate the tracked files under infra/",
            git_ok,
            "without git the committed-file scans below cannot be evaluated",
        )
        all_infra_text = "\n".join(read(p) for p in all_infra)

        # A forbidden construct is allowed to be *named* in a comment explaining why it is absent.
        # Only a real HCL usage counts, so comment lines are stripped before the scan.
        hcl_only = strip_hcl_comments(tf_text)
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

        # -- destructive authority is separated from routine research -------------
        #
        # The licensed bucket has no versioning, no replication and no backup, so a
        # delete cannot be undone and a re-fetch is not a restore. An earlier revision
        # gave `s3:DeleteObject` to the role that also runs routine ingestion, arguing
        # that deletion is a licensing requirement. It is -- but the obligation binds
        # KalpaMani AS A SYSTEM, not every compute role continuously, and conflating
        # the two is how standing destructive authority gets justified. The effect was
        # that a bug in ordinary research code could destroy unrecoverable history.
        #
        # These checks parse each policy document separately, because "does the file
        # mention DeleteObject" cannot distinguish the routine role from the dedicated
        # deletion role -- and the whole point is which role holds it.
        # Comments are stripped first. These files explain at length WHY a permission is
        # absent, naming the very action they do not grant -- so a scan over raw text
        # reports every deliberate omission as a violation. Only real HCL counts.
        iam_text = strip_hcl_comments(read(INFRA / "iam.tf"))

        def policy_body(name: str) -> str:
            """The body of one `data "aws_iam_policy_document" "<name>"` block."""
            match = re.search(
                r'data\s+"aws_iam_policy_document"\s+"' + re.escape(name) + r'"\s*\{(.*?)\n\}',
                iam_text,
                re.S,
            )
            return match.group(1) if match else ""

        routine = policy_body("task")
        deletion = policy_body("licensed_data_deletion")

        f.check(
            "the routine research role exists as a policy document",
            bool(routine),
            'data "aws_iam_policy_document" "task" not found',
        )
        for action in ("s3:DeleteObject", "s3:DeleteObjectVersion"):
            f.check(
                f"the routine research role does not grant {action}",
                f'"{action}"' not in routine,
                "an irreversible delete on the licensed bucket must not be routine authority",
            )
        f.check(
            "the routine research role still cannot delete control-bucket objects",
            '"s3:DeleteObject"' not in routine,
            "manifests, lineage and receipts are governance evidence",
        )
        f.check(
            "the routine research role writes no CloudWatch Logs directly",
            "logs:PutLogEvents" not in routine and "logs:CreateLogStream" not in routine,
            "the awslogs driver uses the execution role; direct log writes bypass redaction",
        )

        f.check(
            "a dedicated licensed-data deletion role exists",
            bool(deletion)
            and re.search(r'resource\s+"aws_iam_role"\s+"licensed_data_deletion"', iam_text)
            is not None,
            "no dedicated deletion identity; deletion would fall back to a broader role",
        )
        if deletion:
            for action in ("s3:DeleteObject", "s3:DeleteObjectVersion", "s3:AbortMultipartUpload"):
                f.check(
                    f"the deletion role grants {action}",
                    f'"{action}"' in deletion,
                    "the deletion procedure could not complete",
                )
            f.check(
                "the deletion role can prove the bucket's versioning and replication state",
                '"s3:GetBucketVersioning"' in deletion
                and '"s3:GetReplicationConfiguration"' in deletion,
                "runbook steps 8-9 would be asserted rather than evidenced",
            )
            f.check(
                "the deletion role cannot write objects",
                '"s3:PutObject"' not in deletion,
                "a role that destroys must not also be able to write",
            )
            f.check(
                "the deletion role cannot read licensed object contents",
                '"s3:GetObject"' not in deletion,
                "deletion does not require reading the data it destroys",
            )
            f.check(
                "the deletion role cannot reach the control bucket",
                "aws_s3_bucket.control" not in deletion,
                "the evidence a deletion happened must be outside the reach of the deleter",
            )
            f.check(
                "the deletion role has no provider-secret access",
                "secretsmanager" not in deletion and "ssm:" not in deletion,
                "the credential is revoked before deletion begins; this role never needs it",
            )
            f.check(
                "the deletion role is scoped to the licensed bucket only",
                "aws_s3_bucket.licensed" in deletion,
                "the deletion role names no licensed-bucket resource",
            )
        f.check(
            "nothing is granted iam:PassRole for the deletion role",
            "iam:PassRole" not in iam_text,
            "a PassRole grant makes the deletion role assumable; that is a separate authorization",
        )

        # The runbook must not over-claim what the deletion role does. A role scoped
        # tightly enough to be safe is necessarily too narrow to run the whole
        # procedure: it cannot stop a schedule, revoke a credential, delete a container
        # image, touch a log group, clear a laptop, or write the receipt to the control
        # bucket. An earlier revision said "every deletion step runs as the dedicated
        # deletion role", which contradicted the role's own policy in the same PR.
        f.check(
            "the runbook does not claim the deletion role performs every step",
            not re.search(r"(?i)every (?:deletion )?step (?:below )?runs as", runbook),
            "the deletion role cannot perform the non-S3 steps; saying so contradicts iam.tf",
        )
        f.check(
            "the runbook assigns the licensed-S3 steps to the deletion role explicitly",
            "steps 3\u20139" in runbook or "steps 3-9" in runbook,
            "no explicit step range is assigned to the dedicated deletion role",
        )
        f.check(
            "the runbook names a separate operator path for the surrounding steps",
            "operator path" in runbook,
            "no operator/orchestration path is named for the non-S3 steps",
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
            if not git_ok:
                # An empty file list would make every scan below pass vacuously.
                f.check(f"no {label} is committed under infra/", False, "git could not enumerate")
                continue
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
        # COMMITTED, not present-on-disk. A real `terraform.tfvars` must exist locally to
        # operate the provisioned foundation; what must never be true is that git tracks it.
        stray = sorted(
            p.name
            for p in all_infra
            if p.name.endswith((".tfstate", ".tfplan"))
            or (p.name.endswith(".tfvars") and p.name != "terraform.tfvars.example")
        )
        f.check(
            "no Terraform state, plan or real tfvars file is COMMITTED in the scaffold",
            git_ok and not stray,
            ", ".join(stray) if stray else "git could not enumerate tracked files",
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

    # ----------------------------------------------- 14. ADR-0008 and the exact gate map
    print("\n[14/17] The Sharadar licence decision closes G3, and nothing else")
    f.check("ADR-0008 exists", ADR_LICENCE.is_file(), f"missing: {ADR_LICENCE}")
    if ADR_LICENCE.is_file():
        adr8 = read(ADR_LICENCE)

        f.check(
            "ADR-0008 is accepted on merge and not before",
            "Accepted \u2014 effective on the merge" in adr8 and "carries no authority" in adr8,
            "the ADR must carry no authority until its pull request merges",
        )
        f.check(
            "ADR-0008 records the owner's acceptance of the published licence",
            "accepts the Sharadar Personal Use License as currently published" in adr8,
            "the decision itself is not stated",
        )
        f.check(
            "ADR-0008 records the clarification message as cancelled and unsent",
            "CANCELLED" in adr8 and "NOT SENT" in adr8,
            "the Q1-Q8 draft status is not recorded",
        )
        f.check(
            "ADR-0008 retains rather than deletes the cancelled draft",
            "not deleted" in adr8 and CLARIFICATION.is_file(),
            "historical evidence must be preserved, not removed",
        )
        f.check(
            "ADR-0008 closes G3",
            re.search(r"\*\*G3\*\*[^|\n]*\|[^|\n]*\|\s*\*\*CLOSED", adr8) is not None,
            "G3 is not recorded CLOSED",
        )
        for gate in OPEN_GATES:
            f.check(
                f"ADR-0008 leaves {gate} open",
                re.search(rf"\*\*{gate}\*\*[^|\n]*\|[^|\n]*\|\s*\*\*OPEN", adr8) is not None,
                f"{gate} is not recorded OPEN in ADR-0008",
            )
        f.check(
            "ADR-0008 reopens G3 if the provider changes",
            "G3 reopens for the replacement provider" in adr8,
            "a licence decision is provider-specific and must say so",
        )
        f.check(
            "ADR-0008 selects no provider",
            "Sharadar selected as the production provider     NO" in adr8,
            "closing a licensing gate must not read as selecting a provider",
        )
        f.check(
            "ADR-0008 supersedes the historical all-gates-open statements explicitly",
            "Supersession of the historical all-gates-open statements" in adr8
            and "neither ADR is edited" in adr8,
            "the contradiction with ADR-0006/0007 must be named, not left implicit",
        )
        f.check(
            "ADR-0008 leaves ADR-0005 proposed",
            "ADR-0005 remains PROPOSED" in adr8,
            "ADR-0005 status changed",
        )
        f.check(
            "ADR-0008 keeps live trading hard-disabled",
            "HARD-DISABLED" in adr8.upper(),
            "live-trading wording missing from ADR-0008",
        )
        f.check(
            "ADR-0008 withholds every other authorization",
            "Explicit non-authorizations" in adr8,
            "no non-authorization block",
        )
        for label, needle in (
            ("personal use only", "Personal use only"),
            ("Services Data privacy", "Services Data stays private"),
            ("private empirical evaluation", "Empirical provider evaluation is private"),
            ("the 30-day deletion obligation", "vendor-data-cloud-deletion.md"),
            ("the third-party AI boundary", "Third-party AI"),
        ):
            f.check(
                f"ADR-0008 retains the {label} constraint",
                needle in adr8,
                f"missing {needle!r}",
            )
        f.check(
            "ADR-0008 publishes no empirical provider result",
            not re.search(
                r"\bP[1-9]\b\s*[:=]\s*(TESTED|PARTIALLY_TESTED|INCONCLUSIVE|DEFERRED)", adr8
            ),
            "Terms s.8 keeps empirical conclusions out of a public repository",
        )

    # -- the cancelled draft says so, prominently --------------------------------
    if CLARIFICATION.is_file():
        draft = read(CLARIFICATION)
        f.check(
            "the clarification draft is marked cancelled and unsent",
            "CANCELLED" in draft and "NOT SENT" in draft and "HISTORICAL" in draft.upper(),
            "the retired draft must say plainly that it was never sent",
        )
        f.check(
            "the cancelled draft still carries the two questions a purchase needs",
            "Q7" in draft and "Q8" in draft and "before any purchase" in draft,
            "Q7 and Q8 are not licensing questions and are still unanswered",
        )

    # -- no current-status document may still claim all seven gates are open -----
    current_status_docs = {
        "CLAUDE.md": REPO_ROOT / "CLAUDE.md",
        "README.md": REPO_ROOT / "README.md",
        "aws-foundation-status.md": FOUNDATION_STATUS,
        "vendor-data-cloud-deletion.md": DELETION_RUNBOOK,
        "infra README": INFRA / "README.md",
        "decision packet": PACKET,
        "clarification draft": CLARIFICATION,
    }
    blanket: list[str] = []
    for name, path in current_status_docs.items():
        if not path.is_file():
            continue
        for lineno, line in enumerate(read(path).lower().splitlines(), 1):
            for phrase in BLANKET_ALL_OPEN:
                at = line.find(phrase)
                if at < 0:
                    continue
                # A sentence that FORBIDS the blanket claim contains it. "No blanket
                # 'G1-G7 are all OPEN' statement is correct any more" asserts the opposite
                # of what a bare substring match reads, and banning it would push the
                # document toward saying less rather than more.
                if GATE_NEGATION_INLINE.search(line[:at]):
                    continue
                blanket.append(f"{name}:{lineno} ({phrase})")
                break
    f.check(
        "no current-status document still claims all seven gates are open",
        not blanket,
        ", ".join(blanket[:6]),
    )

    # -- and each one carries the closed gate, so the map is stated rather than implied
    for name, path in current_status_docs.items():
        if not path.is_file():
            continue
        body = read(path)
        f.check(
            f"{name} records G3 as closed",
            re.search(r"G3[^.\n]{0,80}CLOSED", body) is not None,
            "the gate map must be stated where the old blanket claim used to be",
        )

    # -- the harness exists, is not production code, and is not run by automation
    f.check(
        "the private qualification harness exists",
        QUALIFICATION_HARNESS.is_file(),
        f"missing: {QUALIFICATION_HARNESS}",
    )
    if QUALIFICATION_HARNESS.is_file():
        harness = read(QUALIFICATION_HARNESS)
        for label, needle in (
            ("requires an explicit live-run flag", "--private-live-run"),
            ("pins the foundation AWS profile", 'EXPECTED_PROFILE = "kalpamani-foundation"'),
            ("reuses the fail-closed AWS identity gate", "aws_identity_gate"),
            ("refuses automated contexts", "running_under_automation"),
            ("stores evidence under the licensed prefix", "assert_licensed_destination"),
            ("writes its report under .runtime", '".runtime" / "phase3" / "sharadar"'),
            ("redacts URLs and query strings", "def redact("),
            ("keeps the verdict out of the exit code", "def operational_exit_code("),
            # Live-run correctness. Each of these was a way the run could have meant
            # something other than what the methodology said it meant.
            ("sends an explicit five-year window", "def five_year_window("),
            ("takes the ratio base from the action date", "def action_date_base("),
            ("refuses an unusable actions table", "ACTIONS_NOT_USABLE"),
            ("counts only splits that adjust a compared row", "splits_exercised"),
            ("treats a split-like unmodelled action as confounding", "stock_dividend_literals"),
            ("makes the caller state retrieval completeness", "retrieval_complete: bool"),
            (
                "validates that responses are usable, not merely returned",
                "def validate_retrieved_inventory(",
            ),
            ("confounds on any unmodelled action literal", "def unmodelled_action_literals("),
            (
                "refuses to file a documented-method contradiction as a pass",
                "DOCUMENTATION_DATA_CONTRADICTION",
            ),
            (
                "refuses agreement by absence of a discriminating row",
                "CONVENTION_NOT_DISCRIMINATED",
            ),
        ):
            f.check(f"the harness {label}", needle in harness, f"missing: {needle!r}")

        f.check(
            "the harness cannot convict the provider from this free probe",
            "return REJECT" not in harness,
            "the split comparison rests on an undocumented reading of actions.value",
        )
        f.check(
            "the harness requires both runnable P5 limbs before proceeding",
            'for limb in ("split_limb", "dividend_limb"):' in harness,
            "a trivially-agreeing limb must not reach PROCEED",
        )
        f.check(
            "the harness describes the probe as single-name",
            "single-name, five-year" in harness and "30-name" not in harness,
            "the 30-name sample subscription is a different surface",
        )
        f.check(
            "the harness never requests a table-wide bulk download",
            '("years"' not in harness and '"years":' not in harness,
            "`years=` fetches every security, not the authorized single-ticker probe",
        )
        f.check(
            "the harness windows every temporal table and no snapshot",
            "WINDOWED_TABLES: tuple[str, ...] = tuple(t for t, windowed in REQUEST_INVENTORY"
            in harness
            and '("tickers", False)' in harness,
            "tickers is a snapshot and must not carry a date range; the rest must",
        )
        f.check(
            "the harness declares the test key as a vendor-published public token",
            "PUBLIC TEST TOKEN" in harness,
            "a committed key literal must be labelled as the vendor's published test token",
        )
        f.check(
            "the harness imports no cloud or vendor SDK",
            not re.search(r"^\s*import\s+(boto3|botocore|requests|httpx)\b", harness, re.M),
            "AWS access goes through the CLI so no SDK becomes a project dependency",
        )

    # -- research-bucket emptiness must no longer read as a standing invariant ---
    if FOUNDATION_STATUS.is_file():
        status_body = read(FOUNDATION_STATUS)
        f.check(
            "bucket emptiness is recorded as a closeout observation, not an invariant",
            "not a continuing invariant" in status_body,
            "qualification may legitimately place private material in the licensed bucket",
        )

    # -------------------------- 15. ADR-0009 authorizes code, and only code
    print("\n[15/17] The Sharadar implementation authorization is code-only, and G1 stays open")
    f.check(
        "ADR-0009 exists",
        ADR_IMPLEMENTATION.is_file(),
        f"missing: {ADR_IMPLEMENTATION}",
    )
    if ADR_IMPLEMENTATION.is_file():
        adr9 = read(ADR_IMPLEMENTATION)

        f.check(
            "ADR-0009 is accepted on merge and not before",
            "Accepted — effective on the merge" in adr9 and "carries no authority" in adr9,
            "the ADR must carry no authority until its pull request merges",
        )
        f.check(
            "ADR-0009 records the owner's instruction as the governance input",
            "Authorize the next Sharadar implementation phase" in adr9,
            "the decision this ADR records is not stated",
        )
        f.check(
            "ADR-0009 separates the implementation target from the production provider",
            "Sharadar is not the selected production provider" in adr9,
            "naming an implementation target must not read as closing G1",
        )
        # Each of these is a distinct thing a reader could wrongly infer from
        # "the next Sharadar implementation phase is authorized".
        for label, needle in (
            ("G1 closure", "**Not** final **G1** closure"),
            ("subscription authorization", "**Not** subscription authorization (**A3**)"),
            ("purchase authorization", "**Not** purchase authorization"),
            ("production ingestion", "**Not** production ingestion authorization"),
            ("a qualification finding", "**Not** a finding about the private qualification"),
        ):
            f.check(
                f"ADR-0009 disclaims {label}",
                needle in adr9,
                f"missing: {needle!r}",
            )
        f.check(
            "ADR-0009 states that no request has been sent",
            "No request has been sent to the vendor by this work" in adr9,
            "a code-only slice must say plainly that the code has never run",
        )
        f.check(
            "ADR-0009 carries an explicit non-authorization block",
            "Explicit non-authorizations" in adr9,
            "no non-authorization block",
        )
        f.check(
            "ADR-0009 keeps G1 open",
            re.search(r"\*\*G1\*\*[^|\n]*\|[^|\n]*\|\s*\*\*OPEN", adr9) is not None,
            "G1 is not recorded OPEN in ADR-0009",
        )
        f.check(
            "ADR-0009 keeps G3 closed",
            re.search(r"\*\*G3\*\*[^|\n]*\|[^|\n]*\|\s*\*\*CLOSED", adr9) is not None,
            "G3 is not recorded CLOSED in ADR-0009",
        )
        for gate in OPEN_GATES:
            f.check(
                f"ADR-0009 leaves {gate} open",
                re.search(rf"\*\*{gate}\*\*[^|\n]*\|[^|\n]*\|\s*\*\*OPEN", adr9) is not None,
                f"{gate} is not recorded OPEN in ADR-0009",
            )
        f.check(
            "ADR-0009 leaves ADR-0005 proposed",
            "remains **PROPOSED**" in adr9,
            "ADR-0005 status changed",
        )
        f.check(
            "ADR-0009 keeps live trading hard-disabled",
            "HARD-DISABLED" in adr9.upper(),
            "live-trading wording missing from ADR-0009",
        )
        f.check(
            "ADR-0009 records Q7 and Q8 as still unresolved",
            "Q7" in adr9 and "Q8" in adr9 and "STILL UNRESOLVED" in adr9,
            "the two pre-purchase questions must be reported, not quietly dropped",
        )
        f.check(
            "ADR-0009 keeps Q7 and Q8 as pre-purchase blockers",
            "pre-purchase blockers" in adr9,
            "an unanswered pre-purchase question must still block the purchase",
        )
        f.check(
            "ADR-0009 records that the vendor was not contacted for the refresh",
            "The vendor was not contacted" in adr9,
            "a public-source refresh must say what it did not do",
        )
        # Terms s.8 keeps empirical conclusions out of a public repository, and an
        # authorization to build is not a licence to publish what motivated it.
        f.check(
            "ADR-0009 publishes no empirical provider result",
            not re.search(
                r"\bP[1-9]\b\s*[:=]\s*(TESTED|PARTIALLY_TESTED|INCONCLUSIVE|DEFERRED)", adr9
            )
            and "PROCEED_TO_PROVIDER_REALISTIC_IMPLEMENTATION" not in adr9
            and "HOLD_FOR_ADDITIONAL_PRIVATE_SAMPLE" not in adr9
            and "REJECT_FOR_PHASE3A" not in adr9,
            "the private qualification result must not be disclosed or implied",
        )

    # -- the authorized package exists, and every clause that keeps it inert holds ----
    f.check(
        "the authorized provider package exists",
        PROVIDER_PACKAGE.is_dir(),
        f"missing: {PROVIDER_PACKAGE}",
    )
    if PROVIDER_PACKAGE.is_dir():
        modules = sorted(p for p in PROVIDER_PACKAGE.glob("*.py"))
        package = "\n".join(read(p) for p in modules)
        f.check(
            "the provider package carries no API key literal",
            "test-api-key" not in package,
            "not even the vendor's published test token belongs in production code",
        )
        f.check(
            "the provider package has no executable entry point",
            "__main__" not in package,
            "no runner is authorized in this slice",
        )
        f.check(
            "the provider package declares no new dependency",
            not re.search(r"^\s*import\s+(boto3|botocore|requests|httpx|urllib3)\b", package, re.M),
            "the project still declares no runtime dependency",
        )
        f.check(
            "request construction refuses a table-wide bulk download",
            '"years"' in package and "FORBIDDEN_QUERY_PARAMETERS" in package,
            "`years=` fetches every security and must not be constructible",
        )
        f.check(
            "request construction requires an explicit window on a windowed table",
            "WINDOWED_DATASETS" in package,
            "the vendor defaults an omitted window to one year (PSR-SHD-121)",
        )
        f.check(
            "the credential is injected and renders as a placeholder",
            "CREDENTIAL_PLACEHOLDER" in package and "def reveal(" in package,
            "a credential must have exactly one named route out and no other rendering",
        )
        f.check(
            "errors are assembled from a closed vocabulary",
            "class SharadarErrorCode" in package and "def redact(" in package,
            "a response body must have no parameter to reach an error through",
        )
        f.check(
            "pacing and bounded retries exist and are deterministic",
            "class Pacer" in package and "class RetryPolicy" in package,
            "no documented rate limit is not an absent rate limit",
        )
        # -- the transport boundary corrections, each a way a credential could travel
        f.check(
            "the transport pins an exact origin by parsing, not by string prefix",
            "def origin_refusal(" in package
            and "urlsplit" in package
            and "parts.hostname" in package
            and "parts.username" in package
            and "parts.fragment" in package,
            "a lookalike host and a userinfo prefix both satisfy startswith('https://')",
        )
        f.check(
            "the transport refuses redirects rather than following them",
            "class RefuseRedirects" in package
            and "HTTP_REDIRECT_REFUSED" in package
            and "def redirect_request(" in package,
            "a 3xx would hand the query string, and the key, to the Location host",
        )
        f.check(
            "the transport suppresses ambient proxy discovery",
            "ProxyHandler({})" in package,
            "HTTPS_PROXY must not route a credential-bearing request",
        )
        f.check(
            "the transport installs no global opener",
            "install_opener" not in package,
            "a globally installed opener would change unrelated code in the process",
        )
        f.check(
            "a successful response body is bounded by a finite, capped ceiling",
            "DEFAULT_MAX_RESPONSE_BYTES" in package
            and "MAX_RESPONSE_BYTES_CEILING" in package
            and "RESPONSE_TOO_LARGE" in package,
            "an unbounded read lets the other end decide this process's memory",
        )
        f.check(
            "closed vocabularies are normalised at construction, not merely annotated",
            "closed_member" in package and "UNCLASSIFIED" in package,
            "a bare string differs from the member only where .value is read",
        )

    # -- the transport is exercised, so 'dormant' does not mean 'unchecked' -----
    f.check(
        "the concrete transport has a dedicated synthetic test",
        TRANSPORT_TEST.is_file(),
        f"missing: {TRANSPORT_TEST}",
    )
    if TRANSPORT_TEST.is_file():
        transport_test = read(TRANSPORT_TEST)
        f.check(
            "the transport test injects a fake opener and opens no socket",
            "opener=" in transport_test and "urlopen" not in transport_test,
            "the one module allowed to build a transport must not reach a network",
        )

    # -- durable metadata has no free-text field at all -------------------------
    f.check(
        "the durable acquisition record carries no free-form notes field",
        PUBLICATION.is_file()
        and '"notes"' not in read(PUBLICATION)
        and "_FIELD_GRAMMAR" in read(PUBLICATION),
        "a substring blocklist cannot prove an arbitrary credential is absent from free text",
    )
    f.check(
        "acquisition identity is claimed in a global, provider-independent namespace",
        PUBLICATION.is_file()
        and "CLAIM_NAMESPACE" in read(PUBLICATION)
        and "_acquisition_claims" in read(PUBLICATION),
        "(digest, run id) names one retrieval globally, not one per provider partition",
    )
    f.check(
        "the claim namespace sits inside bronze/, which the deletion runbook already deletes",
        PUBLICATION.is_file() and "BRONZE_NAMESPACE, CLAIM_NAMESPACE" in read(PUBLICATION),
        "a new top-level prefix would be an unexpected-prefix finding in the deletion runbook",
    )
    f.check(
        "the reserved claim segment cannot collide with a provider name",
        "_acquisition_claims" in read(REPO_ROOT / "src/kalpamani/data/contracts/paths.py")
        and "RESERVED_SEGMENTS" in read(REPO_ROOT / "src/kalpamani/data/contracts/paths.py"),
        "safe_component refuses a leading underscore, so the reservation holds by grammar",
    )
    f.check(
        "durable ranges and instants are parsed, not pattern-matched",
        PUBLICATION.is_file()
        and "_requested_range_defect" in read(PUBLICATION)
        and "_retrieved_at_defect" in read(PUBLICATION),
        "a pattern that counts digits admits an impossible date and an inverted range",
    )
    f.check(
        "the client fixes its User-Agent rather than accepting one",
        "user_agent" not in read(PROVIDER_PACKAGE / "client.py")
        or "DEFAULT_USER_AGENT" in read(PROVIDER_PACKAGE / "client.py"),
        "a caller-supplied header value is a request-splitting and disclosure channel",
    )
    f.check(
        "the transport validates headers itself rather than trusting urllib",
        "def headers_are_safe(" in read(PROVIDER_PACKAGE / "transport.py"),
        "Request stores a header unvalidated; CR/LF is only rejected at send time",
    )
    f.check(
        "the credential is deeply frozen and cannot be subclassed",
        "__init_subclass__" in read(PROVIDER_PACKAGE / "credentials.py")
        and "MAX_CREDENTIAL_LENGTH" in read(PROVIDER_PACKAGE / "credentials.py"),
        "a subclass could override every rendering method and reveal() at once",
    )
    f.check(
        "the credential module imports no os module",
        not any(
            line.strip() in ("import os", "import os.path") or line.strip().startswith("from os ")
            for line in read(PROVIDER_PACKAGE / "credentials.py").splitlines()
        ),
        "credential_from_env takes an explicit mapping; this slice reads no real secret",
    )
    f.check(
        "the transport response contract is enforced rather than annotated",
        "MIN_HTTP_STATUS" in read(PROVIDER_PACKAGE / "transport.py")
        and "may not be subclassed" in read(PROVIDER_PACKAGE / "transport.py"),
        "a bytearray body would otherwise leave fetch() as a payload",
    )
    f.check(
        "the client validates what an injected transport returns",
        "type(response) is not TransportResponse" in read(PROVIDER_PACKAGE / "client.py")
        and "type(request) is not SharadarRequest" in read(PROVIDER_PACKAGE / "client.py"),
        "a Protocol annotation is a static claim, not a runtime one",
    )
    f.check(
        "the client requires an exact credential",
        "type(credential) is not SharadarCredential" in read(PROVIDER_PACKAGE / "client.py"),
        "a credential-shaped stand-in could override reveal() or a rendering method",
    )
    f.check(
        "direct transport arguments are type-checked before anything can raise",
        "def usable_timeout(" in read(PROVIDER_PACKAGE / "transport.py")
        and "def exact_text(" in read(PROVIDER_PACKAGE / "transport.py"),
        "math.isfinite on an arbitrary object raises out of a sanitizing boundary",
    )
    f.check(
        "the failing-response path never reads, and its close is guarded",
        "_http_error_response" in read(PROVIDER_PACKAGE / "transport.py")
        and "_close_quietly" in read(PROVIDER_PACKAGE / "transport.py"),
        "a close() failure names the host and must not become the outcome",
    )
    f.check(
        "error construction accepts an arbitrary object without raising",
        "def safe_dataset_label(label: object)" in read(PROVIDER_PACKAGE / "redaction.py"),
        "an exception that fails while being built discards the failure it reported",
    )
    f.check(
        "the classification error documents the withdrawn CONTROL surface",
        "withdrawn" in read(REPO_ROOT / "src" / "kalpamani" / "data" / "contracts" / "errors.py"),
        "an attestation would not currently make CONTROL valid, and the docs must say so",
    )
    f.check(
        "the object store binds the content address to the logical name",
        OBJECT_STORE.is_file()
        and "stored.content_sha256 == key.content_sha256" in read(OBJECT_STORE),
        "a store keyed on the name alone would let a forged key read another object",
    )

    f.check(
        "the object-store contract publishes LICENSED objects only in this slice",
        OBJECT_STORE.is_file()
        and "def licensed(" in read(OBJECT_STORE)
        and "def control(" not in read(OBJECT_STORE)
        and "not publishable in this slice" in read(OBJECT_STORE),
        "a free-text attestation is not auditable clearance; the constructor is withdrawn",
    )
    f.check(
        "the object key is deeply frozen and cannot be subclassed",
        OBJECT_STORE.is_file()
        and "__init_subclass__" in read(OBJECT_STORE)
        and "def exact_str(" in read(OBJECT_STORE)
        and "def immutable_payload(" in read(OBJECT_STORE),
        "a caller-owned list or buffer surviving construction can change a key after it is used",
    )
    f.check(
        "no cloud writer was built in this slice",
        OBJECT_STORE.is_file()
        and not re.search(r"^\s*import\s+(boto3|botocore)\b", read(OBJECT_STORE), re.M),
        "the real S3 writer is a following reviewed slice",
    )

    # -- the two Q-questions are recorded as answered by nobody -----------------
    if SOURCE_REGISTER.is_file():
        register = read(SOURCE_REGISTER)
        for claim in ("PSR-SHD-122", "PSR-SHD-123"):
            f.check(
                f"the source register carries {claim}",
                claim in register,
                "the Q7/Q8 public-source refresh must be traceable to a row",
            )
        f.check(
            "the Q7/Q8 refresh is recorded as unresolved rather than as progress",
            "Neither question was answered. Neither was invented an answer." in register,
            "an unanswered question recorded as answered is the defect this guards",
        )

    # -- neither current-status document may over-claim the authorization -------
    overclaims: list[str] = []
    for name, path in (
        ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
        ("README.md", REPO_ROOT / "README.md"),
    ):
        if not path.is_file():
            continue
        for lineno, line in enumerate(read(path).lower().splitlines(), 1):
            for phrase in OVERCLAIM_PHRASES:
                at = line.find(phrase)
                # A negation to the left is the document stating the PROHIBITION, which is
                # exactly what it should say. Banning the phrase outright would push both
                # documents toward saying less rather than more.
                if at >= 0 and not GATE_NEGATION_INLINE.search(line[:at]):
                    overclaims.append(f"{name}:{lineno} ({phrase})")
                    break
    f.check(
        "no current-status document claims a purchase or ingestion authorization",
        not overclaims,
        ", ".join(overclaims[:6]),
    )

    # -- and both must state the distinction the slice rests on -----------------
    for name, path in (
        ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
        ("README.md", REPO_ROOT / "README.md"),
    ):
        if not path.is_file():
            continue
        body = read(path)
        f.check(
            f"{name} records the provider-integration slice as code-only",
            "ADR-0009" in body and re.search(r"CODE ONLY|code only", body) is not None,
            "the authorized slice and the unauthorized ingestion must be distinguishable",
        )
        f.check(
            f"{name} still records real-data ingestion as unauthorized",
            re.search(r"real-data ingestion\**\s*\|\s*\**NOT AUTHORIZED", body) is not None,
            "full Stage 3A ingestion is not authorized by ADR-0009",
        )

    # ------------------- 16. ADR-0010 buys access to evaluate, and nothing more
    print("\n[16/17] The qualification subscription is purchased, and still authorizes no access")
    f.check(
        "ADR-0010 exists",
        ADR_QUALIFICATION.is_file(),
        f"missing: {ADR_QUALIFICATION}",
    )
    if ADR_QUALIFICATION.is_file():
        adr10 = read(ADR_QUALIFICATION)
        # Prose wraps. Several claims below span a line break, so they are matched against
        # a flattened, emphasis-stripped copy rather than the raw text -- otherwise the guard
        # would be checking the line width rather than the claim.
        flat10 = " ".join(adr10.replace("**", "").split())

        f.check(
            "ADR-0010 is accepted on merge and not before",
            "Accepted \u2014 effective on the merge" in adr10 and "carries no authority" in adr10,
            "the ADR must carry no authority until its pull request merges",
        )
        f.check(
            "ADR-0010 records Q7 as publicly unresolved and owner-accepted",
            "PUBLICLY_UNRESOLVED" in adr10 and "OWNER-ACCEPTED FOR QUALIFICATION" in adr10,
            "a decision is not a discovery, and the document must not blur the two",
        )
        f.check(
            "ADR-0010 binds Sharadar price data to PROVIDER_DERIVED",
            "PROVIDER_DERIVED" in adr10 and "PROVIDER_REALISTIC_PIT" in adr10,
            "an unresolved origin has exactly one safe classification",
        )
        f.check(
            "ADR-0010 forbids representing Sharadar price data as PUBLIC_PIT",
            "must never be represented as `PUBLIC_PIT`" in adr10,
            "the whole consequence of an unresolved Q7 is this prohibition",
        )
        f.check(
            "ADR-0010 scopes the derived-artifact rule to Sharadar data alone",
            "No artifact may be classified `PUBLIC_PIT` solely on the basis of Sharadar price data"
            in flat10
            and "is not established by this ADR" in flat10,
            "the direct data is never PUBLIC_PIT, but a future artifact standing on an "
            "independent public source is a question this ADR did not examine and must not "
            "pre-emptively refuse",
        )
        f.check(
            "ADR-0010 distinguishes Q7's evidence state from Q8's",
            "Q7 remained publicly unresolved" in flat10
            and "Q8 was publicly bounded but not empirically verified" in flat10
            and "The owner accepted both dispositions for qualification" in flat10,
            "the two did not reach the same evidence state, and collapsing them into 'neither was "
            "answered' overstates what is unknown about Q8 and understates it about Q7",
        )
        f.check(
            "ADR-0010 records Q8 as publicly bounded, not resolved",
            "PUBLICLY_BOUNDED" in adr10
            and "not certified earliest actual records" in adr10
            and "must be measured from the subscribed data" in flat10,
            "documented depth is not measured depth, and the difference is the qualification",
        )
        f.check(
            "ADR-0010 keeps the security-master metadata boundary explicit",
            "latest primary listing venue" in flat10
            and "must never be silently treated as historically known" in flat10,
            "a current value read as a historical one is look-ahead that raises no error",
        )
        # -- permaticker: the vendor's own pages disagree, and the record says so --
        #
        # This block replaced a check that asserted security-level semantics as
        # settled. It was not: /docs/tickers says "issuer" in its query-parameter
        # description and /docs/faqs says "security" in its ticker-change answer,
        # both current and both first-party. The earlier check would have locked
        # a wrong reading into the audit, which is the worst place to put one --
        # a guard that enforces a mistake makes the mistake harder to find.
        f.check(
            "ADR-0010 records the permaticker granularity as publicly unresolved",
            "PUBLICLY_UNRESOLVED` — CONFLICTING FIRST-PARTY DOCUMENTATION" in adr10,
            "two current first-party pages disagree; neither overrides the other",
        )
        f.check(
            "ADR-0010 records both conflicting first-party statements",
            "identifier for an **issuer**" in adr10
            and "identifier for a **security**" in adr10
            and "https://sharadar.com/docs/tickers" in adr10
            and "https://sharadar.com/docs/faqs" in adr10,
            "recording the contradiction requires carrying both statements, not one",
        )
        f.check(
            "ADR-0010 classifies permaticker as neither issuer-level nor security-level",
            "does not classify `permaticker` as either an issuer-level or a security-level "
            "identifier" in flat10,
            "the public record supports neither classification, so the ADR must assert neither",
        )
        f.check(
            "ADR-0010 makes no definitive security-level claim",
            "security-level anchor" not in flat10
            and "stable per security" not in flat10
            and "settles the level" not in flat10,
            "a definitive claim here would restate the error this correction removes",
        )
        f.check(
            "ADR-0010 states the conservative no-inference rule in full",
            all(
                phrase in flat10
                for phrase in (
                    "opaque, vendor-stable identifier",
                    "do not infer issuer identity",
                    "do not infer security or share-class granularity",
                    "do not collapse share classes or securities",
                    "do not infer issuer-level concentration or exposure groupings",
                    "do not use it alone to establish cross-table entity identity",
                )
            ),
            "an unresolved granularity is safe only while nothing infers one from it",
        )
        f.check(
            "ADR-0010 requires independent evidence or a governed mapping, not yet authorized",
            "independent evidence, an explicit governed mapping, or later empirical qualification"
            in flat10
            and "the subscription does not authorize that qualification" in flat10,
            "an issuer or security relationship is a mapping, not an inference from an opaque key",
        )
        # -- the two identity-failure directions, assigned to the right direction --
        #
        # An earlier revision put "split one exposure into several" on the
        # issuer-key-read-as-security-key direction. That is backwards, and
        # backwards in the direction that reads plausibly: a shared issuer key
        # used as security identity COLLAPSES securities, it does not split them.
        # Splitting is what happens the other way round, and it is why that
        # direction understates issuer concentration.
        f.check(
            "ADR-0010 assigns the security-key-as-issuer-key failure correctly",
            "carry **different** identifiers" in adr10
            and "fragments that issuer's exposure across several" in flat10
            and "understate issuer-level concentration" in flat10,
            "distinct per-security keys grouped as issuers fragment one issuer across groups, "
            "which understates issuer concentration",
        )
        f.check(
            "ADR-0010 assigns the issuer-key-as-security-key failure correctly",
            "**share** one identifier" in adr10
            and "collapses or conflates distinct securities" in flat10
            and "corrupting security-level histories" in flat10,
            "one shared issuer key used as security identity collapses securities; it does not "
            "split an exposure",
        )
        f.check(
            "ADR-0010 no longer reverses the two identity-failure directions",
            "split** one exposure" not in adr10 and "split one exposure into several" not in flat10,
            "the reversed consequence must not return; it reads plausibly and is wrong",
        )

        # -- the PIT consequence is scoped to Sharadar data alone -----------------
        f.check(
            "ADR-0010 states no permanent ceiling on everything built with Sharadar data",
            "permanent ceiling for everything built on" not in flat10
            and "permanent ceiling on everything built" not in flat10,
            "that wording would refuse in advance an artifact resting on evidence this ADR never "
            "examined, and contradicts the narrower rule in §3",
        )
        f.check(
            "ADR-0010 keeps the consequences section scoped to Sharadar data alone",
            "an artifact whose classification rests solely on that price data cannot be "
            "`PUBLIC_PIT`"
            in flat10
            and "this ADR neither establishes nor prohibits" in flat10,
            "the ceiling applies to the data itself and to artifacts resting solely on it",
        )
        f.check(
            "ADR-0010 keeps Q7 and Q8 distinct in its consequences",
            "Q7 is publicly unresolved" in flat10
            and "Q8 is publicly bounded but not empirically verified" in flat10
            and "ceased to be pre-purchase blockers for **different reasons**" in adr10,
            "the consequences section must not re-flatten two different evidence states",
        )

        f.check(
            "ADR-0010 keeps the mutable-metadata rule intact",
            "must never\nbe silently treated as historically known" in adr10
            or "must never be silently treated as historically known" in flat10,
            "the permaticker correction must not weaken the separate, valid metadata rule",
        )
        f.check(
            "ADR-0010 keeps derived price fields distinguishable from provider bytes",
            "formula-versioned" in flat10
            and "must never be labelled a raw exchange observation" in adr10,
            "an imputed column presented as a provider field is a mislabelled observation",
        )
        f.check(
            "ADR-0010 records the subscription as purchased and active",
            "PURCHASED / ACTIVE FOR QUALIFICATION" in adr10,
            "the commercial state is a governance fact and belongs in the record",
        )
        # The matrix is the load-bearing part: four YES rows, and everything that
        # would touch the vendor's systems still NO.
        for label, needle in (
            ("subscription authorization", "| subscription authorization | **YES** |"),
            ("purchase authorization", "| purchase authorization | **YES** |"),
            ("subscription purchased", "| qualification subscription purchased | **YES** |"),
            ("subscription active", "| qualification subscription active | **YES** |"),
            ("provider not selected", "| production provider selected | **NO** |"),
            ("G1 not closed", "| G1 closed | **NO** |"),
            ("G2 not closed", "| G2 closed | **NO** |"),
            (
                "no credential setup",
                "| private credential retrieval / setup authorized | **NO** |",
            ),
            (
                "no Secrets Manager setup",
                "| Secrets Manager credential setup authorized | **NO** |",
            ),
            ("no API call", "| provider API call authorized | **NO** |"),
            ("no test-token probing", "| public test-token probing authorized | **NO** |"),
            ("no Services Data access", "| Services Data access authorized | **NO** |"),
            ("no Services Data ingestion", "| Services Data ingestion authorized | **NO** |"),
            ("no bulk download", "| bulk download authorized | **NO** |"),
            ("no production backfill", "| production backfill authorized | **NO** |"),
            ("no S3 writer", "| real S3 writer implemented | **NO** |"),
            ("no production ingestion", "| production ingestion implemented | **NO** |"),
            ("no broker or LEAN", "| broker or LEAN activity authorized | **NO** |"),
            ("no live trading", "| live trading authorized | **NO** |"),
        ):
            f.check(
                f"ADR-0010 authorization matrix records {label}",
                needle in adr10,
                f"missing matrix row: {needle}",
            )
        f.check(
            "ADR-0010 defers every qualification measurement",
            "These are recorded, not performed." in adr10,
            "recording an obligation is not discharging it",
        )
        f.check(
            "ADR-0010 scopes its privacy claim to this repository",
            "No purchase screenshot, account identifier, account email, billing information, "
            "receipt, payment information, credential, API key, or private licensing evidence is "
            "stored or committed in this repository." in flat10,
            "purchase confirmation is a governance fact; the receipt is not",
        )
        f.check(
            "ADR-0010 claims only what this repository can vouch for",
            "displayed" not in flat10,
            "the assistant cannot speak for what the owner saw on their own screen; the honest "
            "claim is about what is stored and committed here",
        )
        f.check(
            "ADR-0010 records that no private page was opened and no credential inspected",
            "No private account page or API-key page was opened" in flat10
            and "no credential was retrieved or inspected" in flat10,
            "what the assistant did and did not open is a checkable fact and belongs in the record",
        )
        f.check(
            "ADR-0010 closes no gate",
            re.search(r"\*\*G1\*\*[^|\n]*\|[^|\n]*\|\s*\*\*OPEN", adr10) is not None
            and re.search(r"\*\*G2\*\*[^|\n]*\|[^|\n]*\|\s*\*\*OPEN", adr10) is not None
            and re.search(r"\*\*G3\*\*[^|\n]*\|[^|\n]*\|\s*\*\*CLOSED", adr10) is not None,
            "buying access to evaluate a provider is not choosing one",
        )
        f.check(
            "ADR-0010 leaves ADR-0005 proposed and live trading disabled",
            "ADR-0005 remains PROPOSED" in adr10 and "HARD-DISABLED" in adr10,
            "no other governance state moves with this decision",
        )
        f.check(
            "ADR-0010 publishes no empirical provider result",
            not re.search(
                r"\bP[1-9]\b\s*[:=]\s*(TESTED|PARTIALLY_TESTED|INCONCLUSIVE|DEFERRED)", adr10
            ),
            "Terms s.8 keeps empirical conclusions out of a public repository",
        )

    # -- the source register carries the rows ADR-0010's claims rest on ---------
    if SOURCE_REGISTER.is_file():
        register = read(SOURCE_REGISTER)
        for claim, url in (
            ("PSR-SHD-124", "https://sharadar.com/docs/faqs"),
            ("PSR-SHD-125", "https://sharadar.com/docs/tickers"),
            ("PSR-SHD-126", "https://sharadar.com/docs/actions"),
            ("PSR-SHD-127", "https://sharadar.com/docs/fundamentals"),
            ("PSR-SHD-128", "https://sharadar.com/docs/daily"),
        ):
            # The row must exist AND cite the page that actually states its claim.
            # A combined row citing one URL for four tables is not traceability: a
            # reviewer opening the link would find one claim in four.
            row = next(
                (line for line in register.splitlines() if line.startswith(f"| `{claim}`")),
                "",
            )
            f.check(
                f"the source register carries {claim}, cited to its own page",
                bool(row) and url in row,
                f"{claim} must resolve to a row whose source is {url}",
            )
        f.check(
            "PSR-SHD-113 retains the /docs/tickers issuer claim",
            any(
                line.startswith("| `PSR-SHD-113`")
                and "identifier for an issuer" in line
                and "https://sharadar.com/docs/tickers" in line
                for line in register.splitlines()
            ),
            "that page still says issuer today, so the row is current evidence rather than a "
            "stale paraphrase, and must not be rewritten or invalidated",
        )
        f.check(
            "PSR-SHD-124 retains the /docs/faqs security claim and marks the conflict",
            any(
                line.startswith("| `PSR-SHD-124`")
                and "identifier for a **security**" in line
                and "https://sharadar.com/docs/faqs" in line
                and "directly conflicts with `PSR-SHD-113`" in line
                for line in register.splitlines()
            ),
            "both first-party statements must be carried, cross-referenced as a conflict",
        )
        f.check(
            "no register row claims the permaticker conflict was resolved",
            "supersedes the identifier wording in `PSR-SHD-113`" not in register
            and "settles the level `permaticker` identifies" not in register,
            "neither current first-party page overrides the other",
        )
        f.check(
            "the R5 pass records that no account page or API was touched",
            "No account page, subscribe-flow page, API-key page, receipt or" in register
            and "No purchase screenshot, account identifier, account email" in register,
            "a live subscription raises the stakes on what a research pass may open",
        )

    # -- the status documents separate having access from being allowed to use it
    for name, path in (
        ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
        ("README.md", REPO_ROOT / "README.md"),
    ):
        if not path.is_file():
            continue
        body = read(path)
        f.check(
            f"{name} records the qualification subscription as purchased",
            "ADR-0010" in body and "PURCHASED / ACTIVE" in body,
            "the commercial state must be discoverable where a reader looks first",
        )
        f.check(
            f"{name} keeps credentialing, API access and Services Data unauthorized",
            re.search(
                r"credential(ing|s)?[^|\n]*(API|Services Data)[^|\n]*\|\s*\*\*NOT AUTHORIZED",
                body,
                re.I,
            )
            is not None,
            "a subscription existing is not permission to use it",
        )
        f.check(
            f"{name} no longer calls Q7 and Q8 open pre-purchase blockers",
            "remain pre-purchase blockers" not in body,
            "ADR-0010 decided both; leaving the old wording would contradict the record",
        )

    # ------------------- 17. The S3 store is written, and has never reached AWS
    print("\n[17/17] The licensed S3 object store is implemented, and has touched nothing")
    f.check(
        "ADR-0011 exists",
        ADR_OBJECT_STORE.is_file(),
        f"missing: {ADR_OBJECT_STORE}",
    )
    if ADR_OBJECT_STORE.is_file():
        adr11 = read(ADR_OBJECT_STORE)
        # Prose wraps, and the exhaustive non-authorization list is a blockquote, so the
        # leading "> " has to come off before flattening -- otherwise a claim that spans a
        # line break reads as "... configuring a > credential", and the guard would be
        # checking the line width rather than the claim.
        unquoted = [line.lstrip("> ") for line in adr11.replace("**", "").splitlines()]
        flat11 = " ".join(" ".join(unquoted).split())

        f.check(
            "ADR-0011 is accepted on merge and not before",
            "Accepted \u2014 effective on the merge" in adr11 and "carries no authority" in adr11,
            "the ADR must carry no authority until its pull request merges",
        )
        f.check(
            "ADR-0011 records that the store has never run against AWS",
            "never been run against AWS" in flat11,
            "the whole point of the slice is that it is code, reviewed before access exists",
        )
        f.check(
            "ADR-0011 states the append-only mechanism as a single conditional write",
            "IfNoneMatch" in adr11 and "no preflight `HEAD`" in flat11,
            "a check-then-write would be a race the deletion-first bucket cannot absorb",
        )
        f.check(
            "ADR-0011 ties conditional publication to the absence of versioning",
            "conditional publication in software is the immutability" in flat11,
            "no versioning means software is the only immutability boundary there is",
        )
        f.check(
            "ADR-0011 distinguishes a 412 from a 409",
            "Only a `412` means occupied" in flat11
            and "409 ConditionalRequestConflict" in adr11
            and "the condition was never resolved" in flat11.lower(),
            "a conflict is retryable and proves nothing; occupancy is a 412 and only a 412",
        )
        f.check(
            "ADR-0011 records that a 409 sends no HeadObject and yields no verdict",
            "sends no `HeadObject`" in flat11
            and "no idempotency or collision determination" in flat11,
            "a HeadObject issued on a non-answer would invent a collision or a contradiction",
        )
        f.check(
            "ADR-0011 adds no retry loop and says why a caller's retry is safe",
            "no retry loop" in flat11 and "every attempt stays conditional" in flat11,
            "retry policy is the caller's; safety comes from the write staying conditional",
        )
        f.check(
            "no document asserts that a conflict answer establishes occupancy",
            not any(
                _asserts_conflict_is_occupancy(text)
                for text in (adr11, read(REPO_ROOT / "CLAUDE.md"), read(REPO_ROOT / "README.md"))
            ),
            "the whole correction is that a 409 is not occupancy; pairing the two codes as "
            "one meaning is how the defect was written in the first place",
        )
        f.check(
            "ADR-0011 refuses the ETag as an identity",
            "never an ETag" in flat11 and "multipart-dependent opaque token" in flat11,
            "an ETag is not a content hash, and treating it as one voids every identity claim",
        )
        f.check(
            "ADR-0011 requires a proven FULL_OBJECT checksum type",
            "FULL_OBJECT" in adr11 and "COMPOSITE" in adr11,
            "the algorithm being SHA-256 is not enough; the type has to be proven",
        )
        f.check(
            "ADR-0011 explains why a composite checksum is not a content address",
            "digest of part digests" in flat11 or "digest of a multipart upload" in flat11,
            "a composite value varies with the part size, so it does not name the bytes",
        )
        f.check(
            "ADR-0011 refuses an unstated checksum type as well as a composite one",
            "an allowlist of one, matched exactly" in flat11,
            "a denylist would admit every checksum type AWS has not invented yet",
        )
        f.check(
            "ADR-0011 substantiates the declared SDK floor rather than asserting it",
            "boto3==1.36.0" in adr11
            and "botocore==1.36.0" in adr11
            and "the lowest `botocore` that release permits" in flat11,
            "a version floor nobody checked is a guess wearing a bound",
        )
        f.check(
            "ADR-0011 names the model members the floor was checked for",
            all(
                member in adr11
                for member in ("IfNoneMatch", "ChecksumMode", "ChecksumType", "ChecksumSHA256")
            ),
            "the claim has to say what was verified, or it cannot be re-checked",
        )
        f.check(
            "ADR-0011 resolves a collision by metadata rather than by download",
            "never by downloading" in flat11 and "bytes are never retrieved" in flat11,
            "downloading a vendor payload to compare it would spread licensed rows",
        )
        f.check(
            "ADR-0011 fails closed on an unverifiable response",
            "INVALID_RESPONSE" in adr11 and "never a guess in either direction" in flat11,
            "an ambiguous answer is a refusal, not a decision",
        )
        f.check(
            "ADR-0011 requires backend errors to be sanitized into a closed vocabulary",
            "from None" in adr11
            and "no bucket, key, endpoint, request id, host id or credential-shaped text" in flat11,
            "a raw ClientError string is exactly what CLAUDE.md s.3 forbids committing",
        )
        f.check(
            "ADR-0011 keeps deletion out of the routine research writer",
            "Deletion belongs to the separately roled path under ADR-0007" in flat11,
            "ADR-0007 separated deletion authority; a writer must not quietly reunite it",
        )
        f.check(
            "ADR-0011 keeps CONTROL publication deferred",
            "CONTROL publication remains deferred" in flat11,
            "CONTROL was not authorized for this slice",
        )
        f.check(
            "ADR-0011 records the dependency posture it gave up, and its bound",
            "boto3>=1.36.0,<2.0" in adr11 and "first and only" in flat11,
            "a dependency change is a governed decision, not an incidental one",
        )
        f.check(
            "ADR-0011 states that no module imports the SDK",
            "No module under `src/` imports it" in flat11,
            "injection is what keeps import network-silent and credential-free",
        )
        f.check(
            "ADR-0011 rejects the service emulators explicitly",
            "moto" in adr11 and "LocalStack" in adr11 and "Rejected" in adr11,
            "an emulator is a second implementation of S3 semantics to be wrong about",
        )
        f.check(
            "ADR-0011 rejects bucket versioning on the deletion-first grounds",
            "versioning leaves copies behind" in flat11,
            "s.4.23 forbids it; a durability argument must not be allowed to reopen it",
        )
        f.check(
            "ADR-0011 closes no gate",
            "G1 OPEN" in adr11
            and "G2 OPEN" in adr11
            and "G4 OPEN" in adr11
            and "G5 OPEN" in adr11
            and "G6 OPEN" in adr11
            and "G7 OPEN" in adr11,
            "implementing a backend resolves no decision gate",
        )
        f.check(
            "ADR-0011 leaves ADR-0005 proposed and live trading disabled",
            "ADR-0005 remains **PROPOSED**" in adr11
            and "LIVE_TRADING_HARD_DISABLED` remains **True**" in adr11,
            "neither is touched by a storage backend",
        )
        f.check(
            "ADR-0011 states its non-authorizations exhaustively",
            all(
                phrase in flat11
                for phrase in (
                    "any AWS mutation or read",
                    "Terraform plan, apply or destroy",
                    "retrieving, disclosing or binding a bucket name",
                    "creating, retrieving or configuring a credential",
                    "constructing a client",
                    "an ingestion runner",
                    "CONTROL publication",
                )
            ),
            "a reader must not have to infer what merging this does not enable",
        )
        f.check(
            "ADR-0011 uses merge-stable status wording",
            "ACCEPTED EFFECTIVE ON MERGE OF PR #16" in adr11
            and "PENDING MERGE ACCEPTANCE" not in adr11,
            "a status that has to be edited on merge is a status that will be wrong",
        )
        f.check(
            "ADR-0011 scopes its absence claims to this slice",
            "retrieved, inspected, created, configured and bound no credential" in flat11
            and "binds no bucket identifier" in flat11,
            "what this slice did is checkable; what exists elsewhere is not its claim",
        )
        f.check(
            "ADR-0011 acknowledges what already exists outside this slice",
            "provisioned in August 2026 and exist now" in flat11
            and "its clock is running" in flat11,
            "the foundation and the subscription are real; the ADR must not imply otherwise",
        )
        f.check(
            "ADR-0011 makes no claim that no bill is running",
            "before a bill is running" not in adr11 and "no bill is running" not in adr11,
            "cost is not something this slice established",
        )
        f.check(
            "ADR-0011 infers nothing about owner account activity",
            "vendor account page" not in adr11 and "did not examine and must not" in flat11,
            "assistant activity is not evidence about what the owner did",
        )
        f.check(
            "ADR-0011 rests its safety on absence rather than on care",
            "not that the code is careful" in flat11,
            '"the code is careful" is not a control; having no credential and no caller is',
        )

    # -- the code matches what the ADR says about it ---------------------------
    if S3_STORE.is_file():
        s3_source = read(S3_STORE)
        f.check(
            "the S3 store imports no AWS SDK",
            not re.search(r"^\s*(import|from)\s+(boto3|botocore)\b", s3_source, re.M),
            "the client is injected; an import here would undo the whole posture",
        )
        f.check(
            "the S3 store writes conditionally",
            'IfNoneMatch="*"' in s3_source,
            "the append-only guarantee is this one argument",
        )
        f.check(
            "the S3 store requests SSE-S3 explicitly",
            'SERVER_SIDE_ENCRYPTION: Final = "AES256"' in s3_source,
            "an object must be encrypted because this code asked, not because a setting survived",
        )
        f.check(
            "the S3 store sends and verifies a full-object SHA-256",
            "ChecksumSHA256" in s3_source and "ChecksumAlgorithm" in s3_source,
            "identity is the digest the ObjectKey is named by",
        )
        f.check(
            "the S3 store requires a proven FULL_OBJECT checksum type",
            'FULL_OBJECT_CHECKSUM: Final = "FULL_OBJECT"' in s3_source
            and "checksum_type != FULL_OBJECT_CHECKSUM" in s3_source,
            "a COMPOSITE SHA-256 depends on the upload, not only on the bytes",
        )
        f.check(
            "the S3 store treats only a 412 as occupancy",
            '_OCCUPIED_CODES: Final[frozenset[str]] = frozenset({"PreconditionFailed", "412"})'
            in s3_source,
            "409 is a retryable conflict, and reading it as occupancy would be a fail-open",
        )
        f.check(
            "the S3 store classifies a conflict as transient",
            "_CONFLICT_CODES: Final[frozenset[str]] = frozenset("
            '{"ConditionalRequestConflict", "409"})'
            in s3_source
            and "_TRANSIENT_CODES" in s3_source,
            "the condition was never resolved, so nothing was learned about the name",
        )
        f.check(
            "the S3 store adds no retry loop in this slice",
            not _has_a_loop(S3_STORE),
            "retry policy belongs to an authorized caller, not to the store. Checked as an "
            "absence of loop *nodes*, because a substring probe for `while True` would miss "
            "every other spelling of a retry",
        )
        f.check(
            "the S3 store exposes no read, list, delete or copy operation",
            not any(
                name in _executable_python(S3_STORE)
                for name in ("get_object", "delete_object", "list_objects", "copy_object")
            ),
            "a routine research writer must not be able to reach any of them",
        )
        f.check(
            "the S3 store hard-codes no bucket, ARN, account or endpoint",
            not re.search(
                r"(arn:aws|s3://|amazonaws\.com|\b\d{12}\b)",
                _executable_python(S3_STORE),
            ),
            "a bucket name is operational configuration and never belongs in Git",
        )
        f.check(
            "the S3 store has no runner and no entry point",
            '__name__ == "__main__"' not in s3_source and "argparse" not in s3_source,
            "no execution path is authorized for this slice",
        )

    if OBJECT_STORE.is_file():
        neutral = read(OBJECT_STORE)
        f.check(
            "the neutral contract names no cloud provider",
            not re.search(
                r"\b(boto3|botocore|s3|aws|bucket)\b",
                _executable_python(OBJECT_STORE),
                re.I,
            ),
            "the protocol is the seam; a backend leaking into it would remove the seam",
        )
        f.check(
            "the shared admission rules live in the neutral contract",
            all(
                f"def {helper}(" in neutral
                for helper in ("require_exact_key", "require_publishable", "physical_key")
            ),
            "two implementations of what may be published would eventually disagree",
        )

    # -- the status documents record a store that exists and has never been used
    for name, path in (
        ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
        ("README.md", REPO_ROOT / "README.md"),
    ):
        if not path.is_file():
            continue
        body = read(path)
        flat = " ".join(body.replace("**", "").split())
        f.check(
            f"{name} records the S3 store as code that has never run against AWS",
            "ADR-0011" in body and "NEVER RUN AGAINST AWS" in body,
            "a reader must not mistake a written backend for a used one",
        )
        f.check(
            f"{name} uses merge-stable status wording for this slice",
            "ACCEPTED EFFECTIVE ON MERGE OF PR #16" in body,
            "the same sentence must stay true on both sides of the merge",
        )
        f.check(
            f"{name} does not describe the slice as pending merge acceptance",
            "PENDING MERGE ACCEPTANCE" not in body,
            "a pending status is stale the moment it stops being pending -- the PR #13 defect",
        )
        f.check(
            f"{name} scopes its absence claims to this slice and this repository",
            "adapter bucket binding: NONE" in body and "adapter credential binding: NONE" in body,
            "an unscoped 'bucket NONE' claims something this slice cannot establish",
        )
        f.check(
            f"{name} makes no claim that nothing is billable",
            "before a bill is running" not in body and "no bill is running" not in body,
            "the AWS foundation exists and a vendor subscription clock is running",
        )
        f.check(
            f"{name} claims zero requests for the adapter, not for the account",
            "AWS requests sent by the adapter: ZERO" in body and "adapter-attributable" in body,
            "what is checkable here is the adapter's behaviour, not the account's",
        )
        f.check(
            f"{name} states no unscoped 'bucket NONE' or 'credential NONE'",
            "bucket NONE   " not in body and "credential NONE   " not in body,
            "the corrected wording names what is bound to the adapter",
        )
        f.check(
            f"{name} narrows the SDK-boundary claim to application modules under src/",
            "only application module under" in body or "only module under" in body,
            "tests and this documentation name the SDK; the enforced boundary is src/",
        )
        f.check(
            f"{name} records the single runtime dependency and that nothing imports it",
            "boto3" in body and "imports it" in flat,
            "the dependency posture changed; the status documents must say how far",
        )
        f.check(
            f"{name} keeps every AWS action unauthorized",
            re.search(r"AWS[^|\n]*\|\s*\*\*NOT AUTHORIZED", body) is not None,
            "provisioning a platform was never permission to use it, and neither is this",
        )
        f.check(
            f"{name} states that the control is absence rather than care, and scopes it",
            "retrieved, inspected, created, configured and" in flat
            and "no bucket identifier is bound to the adapter" in flat
            and "no module constructs a client or calls the store" in flat,
            "the store is safe because nothing binds it to AWS -- said as a claim about this "
            "slice, not as a claim about the owner's account",
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
