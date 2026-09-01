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
import io
import re
import subprocess
import sys
import tokenize
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, NamedTuple

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
#: The dormant qualification runtime core (ADR-0012). Section 19 exists because
#: this ADR narrowed a claim rather than adding one: something in this repository
#: now calls the object store, and the checkable control moved from "nothing calls
#: it" to "nothing can build a real one to call".
#: The acquisition-mode contract correction (ADR-0013). Section 20 exists because
#: this ADR *removed* a field rather than adding one, and the guard that matters
#: most is an absence: no alias, no converter, no default, no dual-write.
ADR_ACQUISITION_MODE = DECISIONS / "ADR-0013-introduce-acquisition-mode-and-retire-is-backfill.md"
VOCABULARY = REPO_ROOT / "src" / "kalpamani" / "data" / "contracts" / "vocabulary.py"
#: the *filesystem* Bronze writer -- the store the first revision of ADR-0013 left behind.
LOCAL_BRONZE = REPO_ROOT / "src" / "kalpamani" / "data" / "ingest" / "bronze.py"
#: the behavioural suite for the mode contract, including the completeness
#: verifier the second revision left fail-open.
ACQUISITION_MODE_TESTS = REPO_ROOT / "tests" / "unit" / "test_acquisition_mode_contract.py"

#: ADR-0014: the one module authorized to construct the client, the licensed store
#: and the qualification runtime, and the suite that proves it inert.
ADR_COMPOSITION = (
    DECISIONS / "ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md"
)
COMPOSITION_ROOT = PROVIDER_PACKAGE / "composition.py"
PROVIDER_CLIENT = PROVIDER_PACKAGE / "client.py"

#: Claims about the composition that are stronger than the code supports.
#:
#: Each was written in an earlier revision and each is false. A caller's
#: arguments do not stop existing when a function returns -- the caller still owns
#: them. A returned result is not "the only reachable object" in a running
#: program. And offline preflight *validates*, which is work, so "no way to run
#: anything" is wrong; the true, narrower claim is that there is no
#: qualification-run execution surface.
COMPOSITION_OVERCLAIMS: Final[tuple[str, ...]] = (
    "all unreachable: nothing holds them",
    "the only reachable object",
    "no way to run anything",
    "and is unreachable when that call returns",
    "and is unreachable after it",
)

#: The unscoped execution-surface claim, matched after normalisation.
#:
#: An earlier revision checked one exact literal, ``"execution surface     NONE"``,
#: with the spacing a fenced status block happened to use. That missed the two
#: places the claim actually did the damage -- the Markdown status rows, which
#: write it as ``**execution surface NONE**``. A guard that only recognises the
#: form it was written against is a guard for that form, not for the claim.
#:
#: Matched against text with emphasis and backticks removed and whitespace
#: collapsed, so ``**execution surface NONE**``, `` `execution surface: NONE` ``
#: and the multi-space fenced form are all one pattern. The optional colon is
#: part of it.
#:
#: The *scoped* form is the correct claim and is permitted, which is why this is
#: a search with a preceding-context test rather than a plain substring check:
#: "qualification-run execution surface NONE" contains the wrong phrase inside
#: the right one.
UNSCOPED_EXECUTION_SURFACE: Final = re.compile(r"execution\s+surface\s*:?\s*NONE", re.IGNORECASE)

#: What must precede the phrase for it to be the scoped, correct claim.
EXECUTION_SURFACE_SCOPE: Final = "qualification-run "

#: Markdown emphasis and code fencing. Removed before the scan, because a status
#: row's asterisks are formatting and a guard that reads them as content is
#: defeated by bolding the sentence.
MARKDOWN_EMPHASIS: Final = re.compile(r"[*`]+")

#: The object-lifetime claim, in whatever order it is written.
#:
#: "a local is unreachable when the call returns" is a garbage-collection claim
#: dressed as a safety property. The enforced property is that nothing durable
#: retains the object; whether it still exists is a different question, and one
#: that is false-by-construction on an exception path where a traceback holds the
#: frame. Matched semantically -- ``unreachable`` near a returning call -- rather
#: than as the one sentence that happened to be written today.
LIFETIME_CLAIM: Final = re.compile(
    r"unreachable[^.]{0,90}?\b(?:when|after|once)\b[^.]{0,50}?\breturns?\b"
    r"|\breturns?\b[^.]{0,60}?\bunreachable\b",
    re.IGNORECASE,
)

#: Wording that marks a quoted phrase as something being *refuted* rather than
#: asserted. Deliberately not a general "anything in quotes is exempt" rule: a
#: current status row could otherwise bypass the guard by adding quotation marks.
REFUTATION_MARKERS: Final = (
    "would be false",
    "was false",
    "is false",
    "were false",
    "no longer true",
    "an earlier revision",
    "earlier revision of this adr",
    "retired",
    "unqualified",
    "overclaim",
    "corrected",
)
COMPOSITION_TESTS = REPO_ROOT / "tests" / "unit" / "test_sharadar_composition_preflight.py"

#: ADR-0015: the one operator entry point authorized to construct an SDK client
#: and to call the composition, and the boundary module it reads a secret through.
ADR_BINDING = DECISIONS / "ADR-0015-implement-the-dormant-sharadar-private-binding-preflight.md"
BINDING_PREFLIGHT = REPO_ROOT / "scripts" / "sharadar_binding_preflight.py"
SECRETS_BOUNDARY = PROVIDER_PACKAGE / "secrets.py"
BINDING_TESTS = REPO_ROOT / "tests" / "unit" / "test_sharadar_binding_preflight.py"

#: The ADR-0017 implementation slice: one operator entry point and its two
#: dedicated synthetic suites. Named as exact paths so a rename has to pass
#: review rather than merely land in the right folder.
ADR_0017_ENTRY_POINT = REPO_ROOT / "scripts" / "sharadar_authenticated_qualification.py"
ADR_0017_ENTRY_TESTS = REPO_ROOT / "tests" / "unit" / "test_sharadar_authenticated_qualification.py"
ADR_0017_COMPOSITION_TESTS = (
    REPO_ROOT / "tests" / "unit" / "test_sharadar_acquisition_composition.py"
)
#: ADR-0016: the correction that split one credential refusal into three.
ADR_BOUNDARIES = DECISIONS / ("ADR-0016-correct-private-binding-preflight-failure-boundaries.md")
ADR_RUNTIME = DECISIONS / "ADR-0012-implement-the-dormant-sharadar-qualification-runtime-core.md"
QUALIFICATION_PLAN = PROVIDER_PACKAGE / "qualification.py"
QUALIFICATION_RUNTIME = PROVIDER_PACKAGE / "runtime.py"
PLAN_CHECK = REPO_ROOT / "scripts" / "sharadar_plan_check.py"
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


#: Dash spellings folded together before matching, so a guard cannot be evaded by
#: retyping one character. The middle dot is here because the negative control
#: proved a legacy block separated by it slipped past a guard written with
#: hyphens. Written as escapes: a literal dash in source is itself ambiguous,
#: which is the problem being solved.
EM_DASH = "\u2014"
EN_DASH = "\u2013"
MIDDLE_DOT = "\u00b7"

#: Formulations that were true once and are false now. Each names a specific
#: superseded claim rather than a topic, because a topic-shaped guard would
#: also forbid the *historical* framing these documents are required to keep.
#:
#: The distinction this section enforces: a document may say "ADR-0009 did not
#: authorize a purchase, as written on 2026-08-27". It may not say a purchase
#: is unauthorized, because on 2026-08-28 the owner authorized one and it
#: completed.
#: Verbatim fragments of ADR-0009's obsolete matrix, and the conclusions drawn
#: from reproducing it. A current-status document must not carry any of them.
#:
#: The two prohibition forms at the end are separate from the block itself: a
#: document could drop the copy and still assert, in prose, that a vendor account
#: or billing is forbidden. Neither was ever this repository's to forbid.
REPRODUCED_LEGACY_MATRIX: list[tuple[str, str]] = [
    (
        "NOT AUTHORIZED subscription",
        "the obsolete matrix, reproduced; a labelled copy is still a second matrix",
    ),
    (
        "trial - vendor account - billing",
        "the obsolete matrix's prohibition line, which described a slice, not the owner",
    ),
    (
        "ADR-0009, as written on 2026-08-27 -- HISTORICAL",
        "the reproduced block's own header",
    ),
    (
        "Two lines of it were superseded, and only two",
        "a conclusion that only holds if the obsolete list is read as current",
    ),
    (
        "Two lines of that historical boundary were superseded, and only two",
        "same conclusion, README phrasing",
    ),
    (
        "Everything else on that line is still forbidden",
        "false: the line also named a vendor account and billing, which are not forbidden here",
    ),
    (
        "Everything else on that list is still forbidden",
        "same, README phrasing",
    ),
    (
        "a vendor account is not authorized",
        "the owner's account is not this repository's to authorize or forbid",
    ),
    (
        "vendor account is forbidden",
        "the owner's account is not this repository's to authorize or forbid",
    ),
    (
        "billing is not authorized",
        "an authorized purchase necessarily involved billing; forbidding it in the abstract "
        "contradicts a completed, authorized action",
    ),
    (
        "billing is forbidden",
        "same",
    ),
    (
        "ACCEPTED ON MERGE OF PR #13",
        "PR #13 merged; an event-conditional status is no longer a status",
    ),
]


SUPERSEDED_CLAIMS: list[tuple[str, str]] = [
    (
        "must still be answered before any purchase",
        "ADR-0010 decided Q7 and Q8, and the purchase completed",
    ),
    ("nothing has been purchased", "the qualification subscription is purchased and active"),
    (
        "no vendor account exists",
        "what exists in a vendor account is outside what this repository establishes",
    ),
    (
        "no private credential exists",
        "the checkable claim is that none is stored, configured or bound HERE",
    ),
    (
        "no provider credential exists",
        "the checkable claim is about this repository, not the owner's accounts",
    ),
    ("provider credentials NONE", "an unscoped absence claim about the owner's accounts"),
    (
        "No provider has been purchased, trialled or credentialed",
        "a bounded qualification subscription was purchased under ADR-0010",
    ),
    ("subscription NONE", "a qualification subscription is active"),
    (
        "awaiting acceptance",
        "PR #13 merged; Slice 1 is accepted",
    ),
    (
        "nothing below is in force until that merge",
        "PR #13 merged, so what follows IS in force",
    ),
    (
        "ACCEPTED on merge of PR #13 - carries no authority before it",
        "PR #13 merged, so ADR-0009 is in force",
    ),
    (
        "ACCEPTED on merge of the PR introducing it - carries no authority before it",
        "ADR-0010's PR merged; ADR-0011's row must name PR #16 explicitly",
    ),
]


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


def _legacy_identifier_sites() -> list[str]:
    """Every executable use of the retired ``is_backfill`` name under ``src/``.

    Docstrings are stripped, so the three places that *explain* the retirement do
    not weaken the guard -- and a negative assertion cannot be mistaken for a
    live use.
    """
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        code = _executable_python(path)
        for name in ("is_backfill", "QUALIFICATION_IS_BACKFILL"):
            if name in code:
                offenders.append(f"{path.relative_to(REPO_ROOT)} names {name}")
    return offenders


def _conditional_mode_sites() -> list[str]:
    """Every place an acquisition mode is assigned from a conditional expression.

    Structural rather than textual: "derive it from the data" is written as an
    ``if`` expression, and a word search would have to guess at every phrasing of
    a range check, a count comparison or a coverage lookup.
    """
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(read(path), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "acquisition_mode":
                if isinstance(node.value, ast.IfExp):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.value.lineno}")
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.IfExp):
                for target in node.targets:
                    named = isinstance(target, ast.Name) and target.id == "acquisition_mode"
                    attributed = (
                        isinstance(target, ast.Attribute) and target.attr == "acquisition_mode"
                    )
                    if named or attributed:
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return offenders


#: What a merged ADR's current-status row must say, by ADR number.
#:
#: An ADR whose status line reads "accepted, effective on the merge of the pull
#: request that introduces this" is stating a *condition*. Once that pull request
#: merges, the condition is satisfied and the current-status tables have to say
#: so -- otherwise a session reads a merged decision as one carrying no
#: authority, which is exactly backwards.
#:
#: Merged main carried both failure modes at once: README.md had **two** ADR-0013
#: rows, the correct one and a stale duplicate still claiming the pre-merge
#: status, and CLAUDE.md had only the stale one. Neither was caught, because
#: nothing checked the rows.
MERGED_ADR_STATUS: Final[tuple[tuple[str, str], ...]] = (
    ("ADR-0009", "PR #13 merged"),
    ("ADR-0010", "PR #15 merged"),
    ("ADR-0011", "PR #16 merged"),
    ("ADR-0012", "PR #17 merged"),
    ("ADR-0013", "PR #18 merged"),
    ("ADR-0014", "PR #19 merged"),
    ("ADR-0015", "PR #22 merged"),
    ("ADR-0016", "PR #24 merged"),
    ("ADR-0017", "PR #33 merged"),
    ("ADR-0018", "PR #39 merged"),
    ("ADR-0019", "PR #46 merged"),
    ("ADR-0020", "PR #49 merged"),
)

#: How a current-status row states that its ADR is in force and names the pull
#: request that made it so.
#:
#: Used by the coverage check to *find* rows of this class, never to decide
#: whether one is true: the row is what claims the ADR merged, and
#: :data:`MERGED_ADR_STATUS` is what governs the claim. The number is captured so
#: a mismatch is a mismatch and not merely "both mention some PR".
IN_FORCE_ROW: Final = re.compile(
    r"ACCEPTED\s*/\s*IN\s+FORCE.*?\bPR\s*#(?P<pr>\d+)\s+merged", re.IGNORECASE | re.DOTALL
)

#: The first cell of a current-status row whose subject is an ADR.
ADR_ROW_SUBJECT: Final = re.compile(r"\[(?P<adr>ADR-\d{4})\]\(docs/decisions/")

#: What a merged *phase* row must say, keyed by the subject text of its first
#: table cell.
#:
#: The merged-ADR guard covers rows whose subject is an ADR link. It does not
#: cover *phase* rows, and merged main carried two that had gone stale the same
#: way: the Sharadar qualification runtime core still read "ACCEPTED EFFECTIVE ON
#: MERGE OF PR #17" in both status documents, months after PR #17 merged.
#:
#: Explicit, like ``MERGED_ADR_STATUS`` and for the same reason: merge
#: effectiveness is a fact about a pull request, and inferring it from a
#: filename, an ADR number, Git history or prose would be guessing at the one
#: thing this guard exists to pin down.
#:
#: Each entry is (subject fragment, required phrases). The subject fragment is
#: matched in the row's **first cell**, so a feature row that merely cites the
#: same pull request elsewhere is not swept in.
MERGED_PHASE_STATUS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "SHARADAR QUALIFICATION RUNTIME CORE",
        (
            "IMPLEMENTED / ACCEPTED",
            "PR #17 MERGED",
            "CODE ONLY",
            "NEVER RUN AGAINST SHARADAR OR AWS",
        ),
    ),
)

#: What the ADR-0015 current-status row must carry beyond being in force.
#:
#: The registry pins *that* the decision merged. This pins what merging it did
#: **not** do -- because a row reading only "ACCEPTED / IN FORCE -- PR #22
#: merged" would be true and still misread: the slice implemented the path that
#: will one day supply private bindings, and a reader who took that as the
#: binding having happened would have it exactly backwards.
ADR_0015_ROW_BOUNDARY: Final[tuple[str, ...]] = (
    "refused by default",
    "binding preflight only",
    "separately gated",
    "NOT AUTHORIZED",
)

#: Wording in the ADR-0015 row that would claim something already happened.
#:
#: Not a general prohibition on the words -- the row has to *name* what stays
#: absent, so "real bucket binding NONE" is required while "bucket bound" is
#: refused. Every entry is therefore the **affirmative** form.
#:
#: A first draft listed the bare "QUALIFICATION RUN" and failed the very row it
#: was written for, which says an authenticated qualification run *stays
#: separately gated*. A guard that a correct row cannot pass would be answered
#: by weakening the row, which is the opposite of the point.
ADR_0015_ROW_OVERCLAIMS: Final[tuple[str, ...]] = (
    "CREDENTIAL RETRIEVED",
    "CREDENTIAL CONFIGURED",
    "BUCKET BOUND",
    "BINDING PERFORMED",
    "BINDING AUTHORIZED",
    "QUALIFICATION AUTHORIZED",
    "QUALIFICATION RUN AUTHORIZED",
    "QUALIFICATION RUN PERFORMED",
    "PROVIDER ACCESS AUTHORIZED",
    "INGESTED",
)

#: The ADR-0015 status *sentence* in the two status documents.
#:
#: A sibling of the table row, and stale in the same way for the same reason:
#: merged main said "accepted effective on the merge of the pull request
#: introducing ADR-0015, and carrying no authority before it", after PR #22 had
#: merged. It is prose, so no table-row guard reaches it -- which is exactly why
#: it needs one of its own.
ADR_0015_STATUS_SENTENCE: Final = "**Status: ACCEPTED / IN FORCE — PR #22 merged.**"

#: The superseded sentence, refused outright.
ADR_0015_STALE_SENTENCE: Final = (
    "accepted effective on the merge of the pull request introducing ADR-0015"
)

#: The line in the CLAUDE.md IN FORCE matrix that records ADR-0015.
#:
#: A third surface, and the one most easily left behind: a merged decision
#: missing from the in-force list reads as a decision that did not merge.
ADR_0015_MATRIX_LINE: Final = "ADR-0015 dormant private-binding preflight -- ACCEPTED / IN FORCE --"

#: The first-cell subject of the binding status row in both status documents.
#:
#: Matched with :func:`_phase_status_rows`, which is a first-cell matcher that
#: skips ADR-link rows -- exactly the scoping this row needs. The ADR-0015 row
#: also says "real bucket binding NONE", and matching it here would hold two
#: rows to one contract.
BINDING_STATUS_ROW_SUBJECT: Final = "Licensed bucket"

#: What the binding status row must state, now that ADR-0015 has merged and run.
#:
#: The row said "NOT AUTHORIZED -- none exists, and a static test keeps it that
#: way". A credential-source boundary does exist, the operator entry point is the
#: one place permitted to construct an SDK client, and it has been invoked four times.
#: The row has to separate **architectural existence** from **operational
#: execution**, because the old wording denied both at once.
#: What a status document must say about the licensed bucket, now that the fifth
#: attempt resolved it and built a real S3 client against it.
#:
#: "real bucket binding performed: NONE" was the shape this guard required, and it
#: stopped being answerable. The repository never fixed the threshold that phrase
#: names: the composition root reports ``real bucket binding: NONE`` while
#: constructing a store from a caller-supplied bucket string, and the ADR-0011
#: section lists *a constructed SDK client* and *a bound bucket* as two separate
#: absent items without naming the act that produces the second. Claiming a real
#: binding and claiming its absence are therefore both unsupported, so the guard
#: requires the three counts a reader can check and the statement that the term
#: itself is undefined here.
BUCKET_FACTS_NOT_A_VERDICT: Final[tuple[str, ...]] = (
    "licensed-bucket resolutions on the fifth attempt: ONE",
    "fifth attempt S3 client constructions: ONE",
    "fifth attempt S3 client constructions: ONE   ·   S3 object operations: ZERO",
    '"real bucket binding": UNDEFINED IN THIS REPOSITORY -- STATED AS BUCKET RESOLUTION ONE,',
    "S3 CLIENT CONSTRUCTION ONE, S3 OBJECT OPERATIONS ZERO",
    "claims **neither a real binding nor its absence**",
)


BINDING_ROW_FACTS: Final[tuple[str, ...]] = (
    # The row's subject changed with the fifth attempt. "Real bucket binding" was
    # a verdict this repository never defined: the composition root reports it
    # NONE while constructing a store from a caller-supplied bucket string, and
    # the ADR-0011 section lists a constructed SDK client and a bound bucket as
    # two separate absent items without naming the act that produces the second.
    # The row states the three facts a reader can check instead.
    "LICENSED-BUCKET RESOLUTIONS ONE",
    "S3 CLIENT CONSTRUCTIONS ONE",
    "S3 OBJECT OPERATIONS ZERO",
    "IS UNDEFINED IN THIS REPOSITORY",
    "NEITHER A CLAIMED BINDING NOR A CLAIMED ABSENCE",
    "OPERATIONAL SECRET-IDENTIFIER CONFIGURATION OWNER-CONFIGURED, AND RESOLVED ONCE "
    "BY THE ENTRY POINT",
    "SECRETS MANAGER CLIENT CONSTRUCTIONS ONE",
    "ADR-0015 OPERATOR ENTRY POINT IS THE SOLE PERMITTED CONSTRUCTION BOUNDARY",
    "INVOKED FIVE TIMES UNDER SEPARATE AUTHORIZATION",
    "THE FIRST FOUR REFUSING WITHOUT CONSTRUCTING A CLIENT AND THE FIFTH COMPLETING",
    "ONE ADMITTED `GET_SECRET_VALUE`",
    "ONE RETRIEVED AND STRUCTURALLY ACCEPTED CREDENTIAL",
    "ONE OFFLINE COMPOSITION PREFLIGHT RETURNING `VALIDATED_OFFLINE`",
    # The corrected SSO refresh and the one identity confirmation belong in this
    # row for the same reason the attempt counts do: the row is read alone, and
    # a boundary described only by what it has refused reads as one nothing has
    # succeeded against. Both clauses say what the events did *not* move.
    "A CORRECTED AWS SSO LOGIN COMPLETED SUCCESSFULLY",
    "ONE SANITIZED IDENTITY CONFIRMATION RETURNED `IDENTITY_CONFIRMED`",
    "WHICH BOUND NOTHING AND VERIFIED NO SECRET, CREDENTIAL, BUCKET OR PROVIDER ACCESS",
    "A SIXTH BINDING-PREFLIGHT ATTEMPT NOT AUTHORIZED",
    "FURTHER AWS AUTHENTICATION DIAGNOSIS NOT AUTHORIZED",
    "ANOTHER AWS SSO-LOGIN/REFRESH ATTEMPT SEPARATELY GATED / NOT AUTHORIZED",
    "ADDITIONAL CREDENTIAL OR SECRETS MANAGER ACCESS NOT AUTHORIZED",
    "OUTSIDE THAT BOUNDARY NOT AUTHORIZED",
)

#: Claims that no credential source, bucket resolution or construction path exists.
#:
#: Scoped to the binding row and the entry point's own documentation, never to a
#: whole document: ADR-0011's and ADR-0012's sections say comparable things about
#: *their* modules and are still accurate, and `docs/decisions/` is immutable.
STALE_BINDING_ABSENCE_CLAIMS: Final[tuple[str, ...]] = (
    "NONE EXISTS, AND A STATIC TEST KEEPS IT THAT WAY",
    "NO CREDENTIAL SOURCE, NO BUCKET RESOLUTION, NO CONSTRUCTED AWS CLIENT",
    "NO CREDENTIAL SOURCE EXISTS",
    "NO BUCKET RESOLUTION EXISTS",
    "NO CONSTRUCTED AWS CLIENT",
    "NO SDK CLIENT CONSTRUCTION PATH EXISTS",
    "HAS EVER HAD A WAY TO OBTAIN ONE",
    "WILL EVENTUALLY SUPPLY THEM",
)

#: What the entry point's opening docstring must distinguish.
#:
#: Two different facts: the downstream components cannot discover a binding, and
#: this file is the one boundary that may resolve one. Collapsing them into "none
#: of it exists" is what made the old wording false once this file had run.
BINDING_SOURCE_SCOPE: Final[tuple[str, ...]] = (
    "by injection and cannot discover an ambient one",
    "This file is the sole boundary that can",
    "not a claim that none of it exists",
    "invoked five times under separate authorization",
    "reached bucket resolution",
    "reached the fixed secret-identifier source",
    "the fourth refused at the AWS identity gate",
    "None of those four reached Secrets Manager client construction",
)


#: The two status-document sections whose operational claims this round corrected.
#:
#: Scoped deliberately. The stale-phrase guards below must not sweep other
#: slices' accurate, differently-scoped statements -- ADR-0011's "AWS requests
#: sent by the adapter: ZERO" is about an adapter and is still true -- and they
#: must never reach `docs/decisions/`, where an accepted ADR's text is immutable
#: and legitimately records what was true when it was written.
ADR_0015_SECTION_HEADING: Final = (
    "### The Sharadar private-binding preflight — refused by default, four times refused, "
    "then completed"
)
ADR_0016_SECTION_HEADING: Final = (
    "### The private-binding failure boundaries — corrected, and the environment that is not"
)

#: Operational claims that two authorized preflight attempts made false.
#:
#: Every entry is a form that asserts *no AWS activity at all* or *never run*.
#: Bare "never run" is deliberately absent: the section still says authenticated
#: qualification "has never run", which is true, and a guard that could not tell
#: the two apart would be answered by deleting a correct sentence.
STALE_PREFLIGHT_CLAIMS: Final[tuple[str, ...]] = (
    "NEVER BEEN RUN AGAINST AWS",
    "NEVER RUN AGAINST AWS",
    "NEVER BEEN EXECUTED AGAINST AWS",
    "NEVER EXECUTED AGAINST AWS",
    "NONE HAS BEEN RUN",
    "AWS REQUESTS: ZERO",
    "AWS REQUESTS ZERO",
    "AWS NETWORK REQUESTS: ZERO",
    "AWS NETWORK REQUESTS ZERO",
    "CREDENTIAL SOURCE CONFIGURED: NONE",
    "CREDENTIAL SOURCE CONFIGURED NONE",
    "NO CLIENT HAS EVER BEEN CONSTRUCTED",
    "PREFLIGHT ONLY, NEVER RUN",
    "DORMANT, REFUSED BY DEFAULT, NEVER RUN",
)

#: What the ADR-0015 current-status row must now state.
#:
#: The registry pins that ADR-0015 merged. This pins the operational history the
#: merge did not create and four later attempts did.
ADR_0015_ROW_HISTORY: Final[tuple[str, ...]] = (
    "FOUR SEPARATELY AUTHORIZED ATTEMPTS OCCURRED AND ALL FOUR REFUSED, AND A FIFTH "
    "SEPARATELY AUTHORIZED ATTEMPT THEN COMPLETED",
    "REFUSED_SECRET_IDENTIFIER",
    "REFUSED_IDENTITY",
    "AWS IDENTITY-GATE ACTIVITY OCCURRED",
    "AWS NETWORK REQUESTS ON THE FOURTH ATTEMPT ARE UNKNOWN",
    "POST-FOURTH STANDALONE AWS IDENTITY DIAGNOSIS HAS SINCE COMPLETED",
    "NO STANDALONE DIAGNOSIS WAS PERFORMED AS PART OF THE ATTEMPT",
    "STS COMMAND INVOCATION IS UNKNOWN",
    "REAL PRE-STS REFUSAL PATHS",
    "REFUSED_SSO_SESSION_MISSING_OR_EXPIRED",
    "REACHED NEITHER LICENSED-BUCKET RESOLUTION NOR THE SECRET-IDENTIFIER SOURCE",
    "DID NOT READ `KALPAMANI_SHARADAR_SECRET_ID`",
    "OWNER-CONFIGURED, AND RESOLVED ONCE BY THE ENTRY POINT",
    "OWNER SETUP HAVING OCCURRED AFTER THE THIRD ATTEMPT",
    "AND BEFORE THE FOURTH",
)

#: The scoped counts the ADR-0015 section's fenced block must carry.
#: The fifth attempt's counts, in the fenced current-status block of both
#: status documents.
#:
#: Separate from :data:`ADR_0015_SECTION_COUNTS` on purpose. That tuple carries
#: the standing counts a reader checks; this one carries the run that moved
#: them, and each entry fails on its own. A count stated only in narrative prose
#: cannot answer either -- both are matched against the fenced block.
FIFTH_ATTEMPT_FACTS: Final[tuple[str, ...]] = (
    "fifth binding-preflight attempt: COMPLETED -- run later, under its own authorization",
    "fifth attempt process invocations: ONE   ·   exit code: 0",
    "fifth attempt public output: binding preflight completed / offline validation completed",
    "fifth attempt closed outcome: COMPLETED + VALIDATION_COMPLETED",
    "fifth attempt last stage definitively reached: STAGE 10 -- offline composition preflight",
    "fifth attempt composition status: VALIDATED_OFFLINE",
    "fifth attempt identity-gate invocations: ONE -- PASSED",
    "fifth attempt licensed-bucket resolutions: ONE",
    "fifth attempt secret-identifier resolutions: ONE",
    "fifth attempt Secrets Manager client constructions: ONE",
    "fifth attempt get_secret_value invocations: ONE -- ADMITTED",
    "fifth attempt S3 client constructions: ONE   ·   S3 object operations: ZERO",
    "fifth attempt provider transport constructions: ONE   ·   Sharadar/provider requests: ZERO",
    "fifth attempt offline composition-preflight invocations: ONE",
    "fifth attempt qualification executions: ZERO",
    "fifth attempt underlying AWS network requests: UNKNOWN",
    "fifth attempt credential: RETRIEVED -- ONE SecretString, STRUCTURALLY ACCEPTED",
    "credential display, log, persistence, hash, fingerprint or measurement: NONE",
    '"usable" means: STRUCTURALLY ACCEPTABLE TO THE EXISTING CREDENTIAL CONTRACT',
    "Sharadar authentication by that credential: UNKNOWN -- NO PROVIDER REQUEST WAS MADE",
)

#: The nine chronology steps, required **in order**.
#:
#: Order is the claim. The same nine facts printed in a different sequence read
#: as a different history -- an identity confirmation before the refresh that
#: caused it, or a completed attempt before the refusals it followed -- so the
#: guard checks the indices are sorted, not merely that each phrase is present.
#: The list numbers are part of each anchor: they are what makes "step 4" a
#: position rather than a sentence that could be moved.
FIFTH_ATTEMPT_CHRONOLOGY: Final[tuple[str, ...]] = (
    "1. Four separately authorized binding-preflight attempts occurred and all four refused.",
    "2. Attempt 4 refused at the AWS identity gate with `REFUSED_IDENTITY`.",
    "3. The later standalone diagnosis classified the SSO session "
    "`REFUSED_SSO_SESSION_MISSING_OR_EXPIRED`, without distinguishing missing from expired.",
    "4. A later corrected SSO refresh completed successfully.",
    "5. A sanitized identity-confirmation command returned `IDENTITY_CONFIRMED`, without "
    "guaranteeing future session validity.",
    "6. The fifth separately authorized binding-preflight attempt then ran exactly once.",
    "7. It exited `0` and emitted exactly `binding preflight completed` and "
    "`offline validation completed`.",
    "8. Its closed outcome was `COMPLETED + VALIDATION_COMPLETED`.",
    "9. Its last definitively reached stage was stage 10: one "
    "`preflight_qualification_composition` invocation that returned `VALIDATED_OFFLINE`.",
)

#: What the fifth attempt establishes about the credential, and what it does not.
#:
#: The two halves are one guard because separating them is how the dangerous
#: sentence gets written: "a credential was retrieved" is true, and reads as
#: provider access unless the same passage says the acceptance was structural
#: and Sharadar authentication is unknown.
FIFTH_ATTEMPT_CREDENTIAL_SCOPE: Final[tuple[str, ...]] = (
    "A credential was retrieved, and that is not provider authentication.",
    "One admitted `get_secret_value` returned a `SecretString`",
    "the existing credential contract accepted it structurally",
    "it was passed into the offline composition",
    "No credential or fragment was displayed, logged, persisted, hashed, fingerprinted, "
    "measured or summarized.",
    "structurally acceptable to the existing contract",
    "whether it authenticates successfully against Sharadar remains UNKNOWN",
    "because no Sharadar or provider request occurred",
    "Owner attestation and successful repository retrieval are not the same as provider "
    "authentication.",
)

#: The fifth attempt in the ADR-0015 current-status row, which is read alone.
#:
#: A row guard, not a document guard: the same facts appear in the section, and
#: a narrative duplicate must not answer for a missing row clause. That is the
#: failure the entry-scoped guards elsewhere in this file were written against.
FIFTH_ATTEMPT_ROW_FACTS: Final[tuple[str, ...]] = (
    "THE FIFTH SEPARATELY AUTHORIZED ATTEMPT THEN RAN EXACTLY ONCE AND COMPLETED",
    "EXIT CODE `0`",
    "PUBLIC OUTPUT EXACTLY `BINDING PREFLIGHT COMPLETED` AND `OFFLINE VALIDATION COMPLETED`",
    "CLOSED OUTCOME `COMPLETED + VALIDATION_COMPLETED`",
    "LAST DEFINITIVELY REACHED STAGE OF STAGE 10",
    "RETURNING `VALIDATED_OFFLINE`",
    "IDENTITY-GATE INVOCATIONS ONE, PASSED",
    "LICENSED-BUCKET RESOLUTIONS ONE",
    "SECRET-IDENTIFIER RESOLUTIONS ONE",
    "SECRETS MANAGER CLIENT CONSTRUCTIONS ONE",
    "`GET_SECRET_VALUE` INVOCATIONS ONE, ADMITTED",
    "S3 CLIENT CONSTRUCTIONS ONE",
    "S3 OBJECT OPERATIONS ZERO",
    "PROVIDER TRANSPORT CONSTRUCTIONS ONE",
    "SHARADAR/PROVIDER REQUESTS ZERO",
    "OFFLINE COMPOSITION-PREFLIGHT INVOCATIONS ONE",
    "QUALIFICATION EXECUTIONS ZERO",
    "UNDERLYING AWS NETWORK REQUESTS UNKNOWN",
    "A CREDENTIAL WAS DEFINITIVELY RETRIEVED",
    "THE EXISTING CREDENTIAL CONTRACT ACCEPTED STRUCTURALLY",
    "NEVER DISPLAYED, LOGGED, PERSISTED, HASHED, FINGERPRINTED, MEASURED OR SUMMARIZED",
    "SHARADAR AUTHENTICATION UNKNOWN",
    "NO PROVIDER REQUEST OCCURRED",
)

#: Current claims the fifth attempt made false, and overclaims it does not support.
#:
#: Both directions in one denylist because both are the same defect: a status
#: line that does not match what happened. The stale half is a document that
#: never got the memo; the overstated half is one that read a completed offline
#: preflight as provider access, an authorization, or a proven request count.
#:
#: 37 stale-or-overstated fifth-attempt claims are listed here, and a self-guard
#: below derives that number from the tuple rather than trusting this sentence.
#: Without it, a denylist can be weakened by deleting an entry -- there is no
#: document-side symptom, because a denylist that checks nothing passes.
STALE_FIFTH_ATTEMPT_CLAIMS: Final[tuple[str, ...]] = (
    "ONLY FOUR ATTEMPTS OCCURRED",
    "FOUR AUTHORIZED ATTEMPTS TO DATE, ALL REFUSED",
    "AUTHORIZED BINDING-PREFLIGHT ATTEMPTS TO DATE: FOUR",
    "ALL FIVE REFUSED",
    "ALL FIVE ATTEMPTS REFUSED",
    "FIFTH BINDING-PREFLIGHT ATTEMPTS: ZERO",
    "FIFTH BINDING-PREFLIGHT ATTEMPTS REMAIN ZERO",
    "A FIFTH BINDING-PREFLIGHT ATTEMPT: NOT AUTHORIZED",
    "A FIFTH BINDING-PREFLIGHT ATTEMPT NOT AUTHORIZED",
    "A FIFTH ATTEMPT NOT AUTHORIZED",
    "NO SUCCESSFUL BINDING PREFLIGHT",
    "NO BINDING PREFLIGHT HAS COMPLETED",
    "THE BINDING PREFLIGHT HAS NEVER COMPLETED",
    "SECRETS MANAGER CLIENT CONSTRUCTIONS: ZERO",
    "GET_SECRET_VALUE INVOCATIONS: ZERO",
    "CREDENTIAL RETRIEVAL: NONE",
    "REAL CREDENTIAL RETRIEVAL: NONE",
    "CREDENTIAL RETRIEVED: NONE",
    "S3 CLIENT CONSTRUCTIONS: ZERO",
    "PROVIDER TRANSPORT CONSTRUCTIONS: ZERO",
    "OFFLINE COMPOSITION-PREFLIGHT INVOCATIONS: ZERO",
    "COMPOSITION PREFLIGHT RUN: NEVER",
    "NOT YET VERIFIED BY THE ENTRY POINT",
    # The other direction.
    "SHARADAR AUTHENTICATION: CONFIRMED",
    "THE CREDENTIAL IS VALID FOR SHARADAR",
    "SHARADAR AUTHENTICATION CONFIRMED",
    "A SHARADAR REQUEST OCCURRED",
    "A PROVIDER REQUEST OCCURRED",
    "AN S3 OBJECT OPERATION OCCURRED",
    "QUALIFICATION EXECUTIONS: ONE",
    "A QUALIFICATION RUN OCCURRED",
    "UNDERLYING AWS NETWORK REQUESTS: ZERO",
    "UNDERLYING AWS NETWORK REQUESTS: ONE",
    "A SIXTH BINDING-PREFLIGHT ATTEMPT IS AUTHORIZED",
    "A SIXTH ATTEMPT IS AUTHORIZED",
    "ADDITIONAL CREDENTIAL ACCESS IS AUTHORIZED",
    "CURRENT SESSION VALIDITY IS GUARANTEED",
)

#: The fifth attempt in the entry point's own source documentation.
BINDING_SOURCE_FIFTH: Final[tuple[str, ...]] = (
    "invoked five times under separate authorization",
    "The fifth completed: it resolved the identifier once, built one Secrets Manager client",
    "retrieved one credential the existing contract accepted structurally",
    "made one offline ``preflight_qualification_composition`` invocation that returned "
    "``VALIDATED_OFFLINE``",
    "No provider request, no S3 object operation and no qualification execution occurred",
    "whether that credential authenticates against Sharadar is UNKNOWN",
    "fifth attempt COMPLETED + VALIDATION_COMPLETED -- exit code 0,",
    "the fifth authorized attempt",
    "what the fifth did not establish",
    "sixth attempt NOT AUTHORIZED",
)


ADR_0015_SECTION_COUNTS: Final[tuple[str, ...]] = (
    "authorized attempts   FIVE",
    "first four attempts   REFUSED",
    "fifth attempt         COMPLETED + VALIDATION_COMPLETED -- exit code 0",
    "third attempt         REFUSED_SECRET_IDENTIFIER",
    "AWS identity-gate activity: OCCURRED",
    "operational secret-identifier configuration: OWNER-CONFIGURED, AND RESOLVED ONCE "
    "BY THE ENTRY POINT",
    "owner credential setup occurred AFTER the third attempt",
    "identifier-source resolutions on the third attempt: ONE",
    "identifier-source resolutions on the fifth attempt: ONE",
    "Secrets Manager client constructions: ONE",
    "get_secret_value invocations: ONE",
    "Secrets Manager underlying network requests: UNKNOWN",
    "S3 client constructions: ONE",
    "S3 object operations: ZERO",
    "provider transport constructions: ONE",
    "Sharadar/provider requests: ZERO",
    "offline composition-preflight invocations: ONE",
    "credential retrieval: ONE",
    "qualification runs: ZERO",
)

#: The history the ADR-0015 section's prose must state, not merely tabulate.
ADR_0015_SECTION_HISTORY: Final[tuple[str, ...]] = (
    "Four later, separately authorized operator attempts",
    "reached the AWS identity gate and refused there",
    "sts:GetCallerIdentity",
    "refused before constructing a Secrets Manager client",
    "reached the fixed secret-identifier source exactly once",
    "refused there with `REFUSED_SECRET_IDENTIFIER`",
    "AWS identity-gate activity occurred, so total AWS activity was not zero",
    "UNKNOWN at the time of the second attempt",
    "still UNKNOWN at the time of the third attempt",
    "the owner attests that",
    "The fifth separately authorized attempt then completed",
    "The first four refusals remain refusals",
    "A credential was retrieved, and that is not provider authentication",
    "What entry-point resolution did and did not establish",
    "A real binding preflight is no longer a future event at all",
    "Two authenticated qualification attempts have since occurred, each separately authorized.",
)

#: What the corrected ADR-0015 IN FORCE matrix entry must state.
ADR_0015_MATRIX_CLAUSES: Final[tuple[str, ...]] = (
    "PR #22 MERGED, CODE ONLY, REFUSED BY DEFAULT, BINDING PREFLIGHT ONLY",
    "FIVE SEPARATELY AUTHORIZED ATTEMPTS, THE FIRST FOUR REFUSED",
    "THE THIRD WITH REFUSED_SECRET_IDENTIFIER AT THE SECRET-IDENTIFIER SOURCE",
    "AND THE FOURTH WITH REFUSED_IDENTITY AT THE AWS IDENTITY GATE",
    "SET UP AFTER THE THIRD ATTEMPT, NOT READ BY THE FOURTH",
    "AND RESOLVED ONCE BY THE ENTRY POINT ON THE FIFTH",
    "FOURTH-ATTEMPT AWS NETWORK REQUESTS UNKNOWN",
    "POST-FOURTH AWS IDENTITY DIAGNOSIS COMPLETED -- REFUSED_SSO_SESSION_MISSING_OR_EXPIRED",
    "ONE COMMAND, EXIT CODE 255, MISSING AND EXPIRED NOT DISTINGUISHED",
    "A SIXTH ATTEMPT, FURTHER AWS AUTHENTICATION DIAGNOSIS, ANOTHER "
    "SSO-LOGIN/REFRESH ATTEMPT AND ADDITIONAL CREDENTIAL OR SECRETS MANAGER "
    "ACCESS SEPARATELY GATED AND NOT AUTHORIZED",
    "POST-DIAGNOSIS AWS SSO-LOGIN ATTEMPT COMPLETED -- REFUSED_SSO_LOGIN",
    "ONE COMMAND, TIMED OUT AFTER 420 SECONDS, NO EXIT STATUS RETURNED",
    "ZERO BROWSER AUTHORIZATIONS, ZERO DEVICE AUTHORIZATIONS, ZERO SUCCESSFUL "
    "REFRESHES, ZERO IDENTITY CONFIRMATIONS",
    "SSO SESSION STILL UNREFRESHED AFTER IT, EARLIER DIAGNOSIS UNREVISED",
    "LIKELY CAUSE INTERACTIVE-SURFACE SUPPRESSION -- LIKELY, NOT PROVEN",
    "SECRET IDENTIFIER OWNER-CONFIGURED",
    "SET UP AFTER THE THIRD ATTEMPT",
    "AWS IDENTITY-GATE ACTIVITY OCCURRED",
    "ACROSS THE FIRST FOUR ATTEMPTS NO SECRETS MANAGER CLIENT, CREDENTIAL, S3 "
    "OBJECT OPERATION, SHARADAR REQUEST OR QUALIFICATION RUN",
    # The fifth attempt, in the compact entry a reader consults on its own.
    "FIFTH BINDING-PREFLIGHT ATTEMPTS ZERO AT THAT POINT",
    "THE FIFTH SEPARATELY AUTHORIZED ATTEMPT THEN RAN EXACTLY ONCE AND COMPLETED -- EXIT CODE 0",
    "CLOSED OUTCOME COMPLETED + VALIDATION_COMPLETED",
    "LAST STAGE DEFINITIVELY REACHED STAGE 10 WITH ONE "
    "preflight_qualification_composition INVOCATION RETURNING VALIDATED_OFFLINE",
    "IDENTITY-GATE INVOCATIONS ONE AND PASSED, LICENSED-BUCKET RESOLUTIONS ONE, "
    "SECRET-IDENTIFIER RESOLUTIONS ONE, SECRETS MANAGER CLIENT CONSTRUCTIONS ONE, "
    "GET_SECRET_VALUE INVOCATIONS ONE AND ADMITTED, S3 CLIENT CONSTRUCTIONS ONE, "
    "S3 OBJECT OPERATIONS ZERO, PROVIDER TRANSPORT CONSTRUCTIONS ONE, "
    "SHARADAR/PROVIDER REQUESTS ZERO, OFFLINE COMPOSITION-PREFLIGHT INVOCATIONS ONE, "
    "QUALIFICATION EXECUTIONS ZERO, UNDERLYING AWS NETWORK REQUESTS UNKNOWN",
    "ONE CREDENTIAL RETRIEVED AND STRUCTURALLY ACCEPTED, PASSED INTO THE OFFLINE "
    "COMPOSITION AND NEVER DISPLAYED, LOGGED, PERSISTED, HASHED, FINGERPRINTED, "
    "MEASURED OR SUMMARIZED, WITH SHARADAR AUTHENTICATION UNKNOWN AND NO PROVIDER "
    "REQUEST MADE",
)

#: What the entry point's own documentation must state about what has happened.
BINDING_SOURCE_HISTORY: Final[tuple[str, ...]] = (
    "authorized attempts FIVE",
    "third attempt REFUSED_SECRET_IDENTIFIER at the identifier source",
    "fourth attempt REFUSED_IDENTITY at the AWS identity gate",
    "AWS activity NOT ZERO",
    "Five later, separately authorized operator attempts did execute it",
    "before constructing a Secrets Manager client",
    "reached the fixed secret-identifier source exactly once",
    "total AWS activity was not zero",
    "OWNER-CONFIGURED, AND RESOLVED ONCE BY THIS ENTRY POINT",
    "The fifth resolved it exactly once",
    "each requires separate written authorization",
)


#: The ADR-0016 status *sentence* in the two status documents.
#:
#: The sibling of its table row, and stale in the same way for the same reason:
#: ADR-0015's section sentence still read "accepted effective on the merge" long
#: after PR #22 landed, because prose is not a table row and no row guard reaches
#: it. This one is pinned before it can drift.
ADR_0016_STATUS_SENTENCE: Final = "**Status: ACCEPTED / IN FORCE — PR #24 merged.**"

#: The superseded pre-merge sentence, refused in a current-status document.
#:
#: ADR-0016's *own* immutable status line legitimately still carries the
#: accepted-on-merge condition -- that is the decision record, and the merge has
#: satisfied it. A current-status document may not.
ADR_0016_STALE_SENTENCE: Final = "accepted on the merge of the pull request that introduces it"

#: ADR-0016's own immutable status line, which a status sync must leave alone.
#:
#: Checked as *present* rather than absent: the sync changes what the status
#: documents say, and an ADR whose accepted-on-merge condition had been edited
#: away would no longer record the condition the merge satisfied.
ADR_0016_IMMUTABLE_STATUS: Final = (
    "**Status:** **Accepted — effective on the merge of the pull request that "
    "introduces this ADR.**"
)

#: What the ADR-0016 current-status row must carry beyond being in force.
#:
#: Same design as :data:`ADR_0015_ROW_BOUNDARY`: the registry pins *that* the
#: decision merged, and this pins what merging it did **not** do. A row reading
#: only "ACCEPTED / IN FORCE -- PR #24 merged" would be true and still misread --
#: this decision corrected what a refusal *says*, and a reader who took that for
#: permission to produce another refusal would have it backwards.
ADR_0016_ROW_BOUNDARY: Final[tuple[str, ...]] = (
    "SEPARATES SECRET-IDENTIFIER, LOCAL DEPENDENCY, UNCLASSIFIED AND CREDENTIAL REFUSALS",
    # Scoped to Secrets Manager, and moved off zero by the fifth attempt: the
    # corrected boundaries were exercised for the first time by a run that
    # passed the identifier stage instead of refusing at it.
    "SECRETS MANAGER CLIENT CONSTRUCTIONS ONE",
    "INVOCATIONS ONE, ADMITTED",
    "SECRETS MANAGER UNDERLYING NETWORK REQUESTS UNKNOWN",
    "REAL CREDENTIAL RETRIEVAL ONE, STRUCTURALLY ACCEPTED",
    # The environment clause used to read "SYNCHRONIZATION NOT AUTHORIZED",
    # which two separately authorized events made false. What replaces it says
    # what happened *and* what is still gated.
    "OPERATIONAL ENVIRONMENT SYNCHRONIZED AND VERIFIED",
    "PYTHON DEPENDENCY LOCK ABSENT",
    "RANGE-CONFORMANT NOT LOCK-CONFORMANT",
    "FURTHER ENVIRONMENT RESYNCHRONIZATION SEPARATELY GATED",
    "A SIXTH BINDING-PREFLIGHT ATTEMPT NOT AUTHORIZED",
    "ADDITIONAL CREDENTIAL OR SECRETS MANAGER ACCESS NOT AUTHORIZED",
    "A THIRD AUTHENTICATED QUALIFICATION ATTEMPT NOT AUTHORIZED",
)

#: The first-cell subject of the corrected provider-credential-state row.
PROVIDER_CREDENTIAL_ROW_SUBJECT: Final = "Provider credential state"

#: What that row must state, independently.
#:
#: The old row put credential *existence*, repository *consumption* and provider
#: *access* under one verdict. They are three subjects with three different
#: answers now: the owner holds a key, this repository has never consumed it, and
#: access is still unauthorized. A single NOT AUTHORIZED over all three denied the
#: first while reporting the third.
#:
#: Existence is owner-attested and stays that way in the wording: nothing here has
#: seen the key, and a row that dropped the qualifier would be claiming a
#: verification no run performed.
PROVIDER_CREDENTIAL_ROW_FACTS: Final[tuple[str, ...]] = (
    "OWNER API KEY EXISTS / OWNER-ATTESTED / RETRIEVED ONCE BY THE ENTRY POINT AND "
    "STRUCTURALLY ACCEPTED / NOT VERIFIED AGAINST SHARADAR",
    "REPOSITORY/APPLICATION CREDENTIAL RETRIEVAL ONE, ON THE FIFTH AUTHORIZED "
    "BINDING-PREFLIGHT ATTEMPT",
    "ANY ADDITIONAL RETRIEVAL NOT AUTHORIZED",
    "PROVIDER API ACCESS NOT AUTHORIZED",
    "SERVICES DATA ACCESS AND INGESTION NOT AUTHORIZED",
    "A THIRD AUTHENTICATED QUALIFICATION ATTEMPT NOT AUTHORIZED",
)

#: The superseded unscoped first cell, refused as a row subject.
#:
#: Matched as the row's own subject rather than as free text, so the narrative may
#: still quote what the row used to say when explaining why it changed.
STALE_PROVIDER_CREDENTIAL_ROW_SUBJECT: Final = "Provider credentialing / API access / Services Data"

#: The three future actions the ADR-0015 fenced blocks ran together.
#:
#: "another attempt · environment synchronization · authenticated qualification"
#: was one verdict over three, and one of the three has since happened: an
#: environment synchronization was separately authorized and performed. Only a
#: *further* one is gated, and the word carries the whole difference.
FUTURE_ACTION_BOUNDARIES: Final[tuple[str, ...]] = (
    "sixth binding-preflight attempt: NOT AUTHORIZED",
    "further AWS authentication diagnosis: NOT AUTHORIZED",
    "another AWS SSO-login/refresh attempt: SEPARATELY GATED / NOT AUTHORIZED",
    "further environment resynchronization: SEPARATELY GATED / NOT AUTHORIZED",
    "additional credential or Secrets Manager access: NOT AUTHORIZED",
    "a third authenticated qualification attempt: NOT AUTHORIZED",
    "Sharadar/provider access: NOT AUTHORIZED",
    "S3 object operations or publication: NOT AUTHORIZED",
    "ingestion, backfill and update: NOT AUTHORIZED",
    "CONTROL publication: DEFERRED / NOT AUTHORIZED",
    "broker, LEAN, Paper and live trading: NOT AUTHORIZED -- live trading HARD-DISABLED",
)

#: The superseded combined future-action line, refused in the ADR-0015 section.
STALE_FUTURE_ACTION_LINE: Final = (
    "another attempt · environment synchronization · authenticated qualification: NOT AUTHORIZED"
)

#: Wording that would deny the environment synchronization that did happen.
#:
#: Distinct from :data:`STALE_ENVIRONMENT_CLAIMS`, which covers the SDK's absence.
#: These are about the *event*: it occurred, under its own authorization, and the
#: chronology in the environment section is the record of it.
DENIED_SYNCHRONIZATION_CLAIMS: Final[tuple[str, ...]] = (
    "ENVIRONMENT SYNCHRONIZATION: NOT AUTHORIZED",
    "ENVIRONMENT SYNCHRONIZATION NEVER OCCURRED",
    "NO ENVIRONMENT SYNCHRONIZATION HAS OCCURRED",
    "ENVIRONMENT SYNCHRONIZATION HAS NOT OCCURRED",
)


#: The two facts the old combined creation/read line ran together.
#:
#: "Secrets Manager secret created or read: NONE" was one sentence about two
#: different subjects. Owner-side creation is now attested and happened outside
#: this repository; reads *by* this repository remain zero. One line could report
#: the second correctly only by denying the first.
SECRET_CREATION_AND_READ_FACTS: Final[tuple[str, ...]] = (
    "owner-side Secrets Manager secret creation: ATTESTED, AND READ ONCE BY THE ENTRY POINT",
    "Secrets Manager secret reads by this repository: ONE",
)

#: The superseded combined line, refused wherever it reappears.
#:
#: The name trips ruff's hardcoded-password heuristic. It is a superseded
#: status sentence from a status document, suppressed per line rather than by
#: renaming it to something less accurate about what it matches.
STALE_SECRET_CREATED_OR_READ: Final = "Secrets Manager secret created or read: NONE"  # noqa: S105

#: The first-cell subject of the corrected top-level authorization row.
CREDENTIAL_SETUP_ROW_SUBJECT: Final = "Owner-side credential setup"

#: What that row must state, once owner-side setup is a fact and access is not.
#:
#: Five separate statuses, because the old row had one: it labelled setup, provider
#: access and ingestion "NOT AUTHORIZED" together, and owner-side setup has since
#: happened. A single verdict over three subjects goes stale the moment any one of
#: them moves.
CREDENTIAL_SETUP_ROW_FACTS: Final[tuple[str, ...]] = (
    "OWNER-SIDE SHARADAR SECRET CREATION AND IDENTIFIER CONFIGURATION",
    "OWNER-CONFIGURED, AND RESOLVED ONCE BY THE ENTRY POINT",
    "ADDITIONAL APPLICATION CREDENTIAL RETRIEVAL NOT AUTHORIZED",
    "PROVIDER API ACCESS NOT AUTHORIZED",
    "SERVICES DATA ACCESS AND INGESTION NOT AUTHORIZED",
    "A THIRD AUTHENTICATED QUALIFICATION ATTEMPT NOT AUTHORIZED",
)

#: The superseded collective row, refused by its exact first cell.
#:
#: Matched as the row's own subject rather than as free text, so the narrative may
#: still quote what the row used to say when explaining why it changed.
STALE_CREDENTIAL_SETUP_ROW_SUBJECT: Final = (
    "Credential setup · provider API access · Services Data ingestion"
)

#: The first line of the CLAUDE.md NOT AUTHORIZED stanza, and its indent.
#:
#: A top-level stanza, so its continuations sit at fifteen -- the same shape the
#: ENVIRONMENT guard needed, and the same reason the default of twenty-four would
#: silently reduce the stanza to its header line.
NOT_AUTHORIZED_STANZA_LINE: Final = "NOT AUTHORIZED additional application credential retrieval"
NOT_AUTHORIZED_STANZA_INDENT: Final = 15

#: What the stanza must forbid, now that owner-side setup has happened.
#:
#: The stanza forbade "credential retrieval, setup, configuration or binding" and
#: "a CONFIGURED credential source". Both were accurate while no secret existed.
#: Each now denies something the same matrix's ENVIRONMENT stanza reports as done,
#: and a matrix that contradicts itself teaches a reader to trust neither half. The
#: replacements move the boundary from *setup* to *use*, which is where it actually
#: sits: the application may not retrieve the credential, and only a separately
#: authorized attempt may construct a client.
NOT_AUTHORIZED_STANZA_CLAUSES: Final[tuple[str, ...]] = (
    "additional application credential retrieval",
    "additional Secrets Manager client construction or use, except during a separately "
    "authorized ADR-0015 binding-preflight attempt",
    "licensed-bucket resolutions ONE",
    "S3 object operations ZERO",
    "undefined in this repository",
    "SDK/client construction outside the ADR-0015 operator boundary",
    "a sixth binding-preflight attempt",
    "further AWS authentication diagnosis -- one completed after the fourth",
    "another AWS SSO refresh or login -- separately gated",
    "ANY provider API call",
    "ANY S3 object operation or publication",
    "a THIRD authenticated qualification attempt",
    "further AWS identity diagnosis of that refusal",
)

#: Stanza wording that forbids owner-side setup that has since happened.
STALE_NOT_AUTHORIZED_CLAUSES: Final[tuple[str, ...]] = (
    "credential retrieval, setup, configuration or binding",
    "a CONFIGURED credential source",
)


#: Claims the owner's post-attempt credential setup does not support.
#:
#: The owner created a Secrets Manager secret and configured the identifier
#: **after** the third attempt had already refused. That is an attestation about
#: the owner's AWS account; it is not an observation this repository made. Nothing
#: here resolved the identifier, constructed a client, called the backend or held a
#: credential, so every affirmative below would be a claim no run can support.
#:
#: Each is the *affirmative* form. The status documents state the same list as
#: noun phrases -- "construction of a Secrets Manager client" rather than "a
#: Secrets Manager client was constructed" -- so the sentence that denies these
#: cannot itself trip the guard. A denylist answered by deleting the denial would
#: be worse than none.
OWNER_SETUP_FORBIDDEN_CLAIMS: Final[tuple[str, ...]] = (
    "THE IDENTIFIER WAS VERIFIED",
    "THE IDENTIFIER IS VERIFIED",
    "THE SECRET WAS VERIFIED",
    "THE SECRET IS VERIFIED",
    "THE SECRET WAS READ",
    "THE SECRET HAS BEEN READ",
    "VERIFIED BY AWS",
    "AWS-VERIFIED",
    "REPOSITORY-VERIFIED",
    "SUCCESSFULLY CONSUMED",
    "THE ENTRY POINT RESOLVED THE IDENTIFIER",
    "THE PROCESS INHERITED THE VARIABLE",
    "A SECRETS MANAGER CLIENT WAS CONSTRUCTED",
    "GET_SECRET_VALUE WAS INVOKED",
    "THE CREDENTIAL WAS RETRIEVED",
    "CREDENTIAL RETRIEVAL SUCCEEDED",
    "THE CREDENTIAL WORKS WITH SHARADAR",
    "THE BINDING IS VERIFIED",
)

#: Current-status wording that still calls the identifier configuration unknown.
#:
#: Scoped to current-status rows, matrix entries and the section's fenced count
#: block -- never to prose. The narrative must still be able to say it *was*
#: unknown at the second and third attempts, because it was, and an owner setting
#: a secret up afterwards does not reach back and change what those runs saw.
STALE_IDENTIFIER_UNKNOWN_CLAIMS: Final[tuple[str, ...]] = (
    "OPERATIONAL SECRET-IDENTIFIER CONFIGURATION: UNKNOWN",
    "OPERATIONAL SECRET-IDENTIFIER CONFIGURATION UNKNOWN",
    "SECRET-IDENTIFIER CONFIGURATION REMAINS UNKNOWN",
    "IS OPERATIONALLY CONFIGURED REMAINS UNKNOWN",
    "IS OPERATIONALLY CONFIGURED IS UNKNOWN",
    "CONFIGURATION UNKNOWN;",
)

#: The exact fenced-block form, refused inside the ADR-0015 section.
STALE_SECTION_IDENTIFIER_LINE: Final = "operational secret-identifier configuration: UNKNOWN"

#: What the ADR-0015 row must still hold open after four refusals.
#:
#: A configured secret is the thing a reader is most likely to mistake for
#: permission. It is not: the fifth attempt, AWS authentication diagnosis, the
#: application's access to the credential and an authenticated run are four
#: separate decisions and none has been taken.
ADR_0015_STILL_GATED: Final[tuple[str, ...]] = (
    "A SIXTH ATTEMPT",
    "FURTHER AWS AUTHENTICATION DIAGNOSIS",
    "ANOTHER AWS SSO REFRESH OR LOGIN",
    "ADDITIONAL CREDENTIAL OR SECRETS MANAGER ACCESS",
    "SHARADAR/PROVIDER ACCESS",
    "ANY S3 OBJECT OPERATION OR PUBLICATION",
    "INGESTION, BACKFILL AND UPDATE",
    "AUTHENTICATED QUALIFICATION ATTEMPT STAY SEPARATELY GATED AND NOT AUTHORIZED",
)

#: The two chronology anchors whose order carries the meaning.
#:
#: Owner setup happened **after** the third attempt refused, which is why no
#: attempt could have seen the identifier. A document that prints them the other
#: way round says the third attempt refused with a configured secret available --
#: a different and much worse finding, and a false one.
THIRD_ATTEMPT_ANCHOR: Final = "still UNKNOWN at the time of the third attempt"
OWNER_SETUP_ANCHOR: Final = "The owner created the secret and configured the variable only after"

#: The fourth attempt's anchor, which must follow the owner's setup.
#:
#: The third sits before the setup and the fourth after it, and the order is the
#: whole finding: attempts one to three ran before the secret existed, and the
#: fourth ran after it and still never reached the identifier. A document that
#: printed the fourth before the setup would be describing a run that refused
#: with no secret configured -- which is the third attempt, not this one.
FOURTH_ATTEMPT_ANCHOR: Final = (
    "fourth attempt refused at the AWS identity gate, two stages before the identifier source"
)

#: The fourth attempt's scoped counts, in the ADR-0015 fenced block.
#:
#: Raw rather than flattened, like :data:`ADR_0015_SECTION_COUNTS`: the block is
#: column-aligned and the alignment is what makes it readable beside the third
#: attempt's row.
#:
#: The two ``ZERO`` resolutions and the ``NO`` read are the point. An outcome
#: word alone would let a reader assume the run got as far as the third did.
FOURTH_ATTEMPT_COUNTS: Final[tuple[str, ...]] = (
    "fourth attempt        REFUSED_IDENTITY at the AWS identity gate",
    "identity-gate invocations on the fourth attempt: ONE -- it did not pass",
    "STS command invocations on the fourth attempt: UNKNOWN -- real pre-STS refusal paths exist",
    "standalone diagnostic commands during the fourth attempt: ZERO",
    "AWS network requests on the fourth attempt: UNKNOWN -- no numeric count is established",
    "owner credential setup occurred AFTER the third attempt and BEFORE the fourth",
    "identifier-source resolutions on the fourth attempt: ZERO",
    "licensed-bucket resolutions on the fourth attempt: ZERO",
    "KALPAMANI_SHARADAR_SECRET_ID read by the fourth attempt: NO",
    "offline composition-preflight invocations: ONE",
    "sixth binding-preflight attempt: NOT AUTHORIZED",
    "further AWS authentication diagnosis: NOT AUTHORIZED",
    "another AWS SSO-login/refresh attempt: SEPARATELY GATED / NOT AUTHORIZED",
)

#: What the fourth attempt's chronology entry must state, not merely tabulate.
FOURTH_ATTEMPT_HISTORY: Final[tuple[str, ...]] = (
    "fourth authorized attempt, after that setup",
    "invoked the application AWS identity gate once",
    "refused there with `REFUSED_IDENTITY`",
    "binding preflight refused: the AWS identity gate did not pass",
    "exit code 1",
    "never reached licensed-bucket resolution and never reached the secret-identifier source",
    "did not read `KALPAMANI_SHARADAR_SECRET_ID`",
    "No retry and no standalone authentication diagnosis followed",
)

#: The four attempts and the owner's setup, in the order they happened.
#:
#: Checked as increasing indices rather than mere presence. A chronology holding
#: every event in the wrong order is worse than one missing an event: it reads as
#: a sequence somebody verified.
CHRONOLOGY_ORDER: Final[tuple[str, ...]] = (
    "first authorized attempt",
    "second authorized attempt",
    "third authorized attempt",
    "owner credential setup, after the third attempt",
    "fourth authorized attempt, after that setup",
)

#: What must stay UNKNOWN about the fourth attempt.
#:
#: The identity gate was invoked once and did not pass, and a gate can fail
#: before anything leaves the machine -- so the network-request count is
#: genuinely unknown, not zero and not one.
#:
#: The unknown does **not** rest on nothing having been diagnosed. A later
#: separately authorized standalone diagnosis did run, and it fixes no count
#: either: it returned one closed word about a session, not a tally of
#: requests. An earlier revision of this comment made the uncertainty depend on
#: no diagnosis ever occurring, which stopped being true.
FOURTH_ATTEMPT_NETWORK_UNKNOWN: Final[tuple[str, ...]] = (
    "Whether the fourth attempt sent an AWS network request is UNKNOWN",
    "neither zero nor one network request may be claimed",
    "No standalone diagnosis was performed as part of attempt 4",
    "A gate invocation is therefore not proof of an STS command invocation",
)

#: Definite network-request counts the fourth attempt does not support.
#:
#: Every entry is the **affirmative** form, on the rule the other refusal lists
#: here follow: the documents must be able to say the count is UNKNOWN, which is
#: a claim about not knowing, while being unable to state a number.
FOURTH_ATTEMPT_NETWORK_CLAIMS: Final[tuple[str, ...]] = (
    "AWS NETWORK REQUESTS ON THE FOURTH ATTEMPT: ZERO",
    "AWS NETWORK REQUESTS ON THE FOURTH ATTEMPT ZERO",
    "AWS NETWORK REQUESTS ON THE FOURTH ATTEMPT: ONE",
    "AWS NETWORK REQUESTS ON THE FOURTH ATTEMPT ONE",
    # Not the bare "THE FOURTH ATTEMPT SENT AN AWS NETWORK REQUEST". The
    # required UNKNOWN sentence contains that span verbatim -- "Whether the
    # fourth attempt sent an AWS network request is UNKNOWN" -- so the guard
    # was answered by deleting the one sentence it exists to protect. The
    # affirmative forms below cannot occur inside it.
    "THE FOURTH ATTEMPT SENT ONE AWS NETWORK REQUEST",
    "THE FOURTH ATTEMPT SENT EXACTLY ONE AWS NETWORK REQUEST",
    "THE FOURTH ATTEMPT DID SEND AN AWS NETWORK REQUEST",
    "THE FOURTH ATTEMPT SENT NO AWS NETWORK REQUEST",
    "THE FOURTH ATTEMPT REACHED AWS",
    "THE FOURTH ATTEMPT DID NOT REACH AWS",
    "EXACTLY ONE AWS NETWORK REQUEST ON THE FOURTH",
)

#: This audit's own prose that a completed diagnosis made false.
#:
#: The comments, check names and failure details in this file are a status
#: surface like any document it guards, and they went stale in the same way: they
#: asserted that nothing had diagnosed the fourth refusal, long after a
#: separately authorized standalone diagnosis had.
#:
#: Every entry is written in the **case the prose uses**, never the upper case
#: the denylists use. That is the whole mechanism separating an assertion from a
#: fixture: ``STALE_NO_DIAGNOSIS_CLAIMS`` and :data:`STALE_GATE_PROBE_CLAIMS`
#: deliberately quote forbidden phrases as test data, and a quoted phrase is not
#: a claim. Only an audit-owned sentence stating one as current truth is the
#: defect, and only those can match here.
STALE_AUDIT_DIAGNOSTICS: Final[tuple[str, ...]] = (
    "Nothing diagnosed the fourth",
    "infers no SSO defect from the fourth refusal",
    "no diagnosis was performed, so nothing may say why",
    "and none was diagnosed",
    # Normalised: the scanned surface goes through `_comment_prose`, which strips
    # comment markers and emphasis so a claim wrapped across two lines is still
    # one phrase. The bold markers this sentence originally carried are gone by
    # the time it is searched.
    "no diagnosis was performed, so the",
    "nothing here may say why its gate refused",
    # Added with the corrected refresh. This file's own labels said the session
    # was still unrefreshed and that no login had ever succeeded; both were true
    # of the timed-out attempt and false the moment the second one returned.
    "and no SSO login has succeeded",
    "the governed session is still unrefreshed",
    # Added with correction round 1. This file asserted a cause the evidence
    # does not carry: it required the documents to name one attempt's output
    # handling as its mistake, and its own commentary called that the finding.
    "which is the one thing the first attempt got wrong",
    "That single difference is the whole operational finding",
)

#: Exact-state, contemporaneous and causal overclaims about the fourth refusal.
#:
#: **Not** a prohibition on the diagnosis. A separately authorized standalone
#: diagnosis did run after attempt 4 and classified the governed SSO session or
#: cached token as **missing or expired** -- the first direct diagnostic evidence
#: explaining that attempt's identity refusal -- and the documents must be able
#: to say so. The name says which of the two jobs this list does, because the
#: previous name (``SSO_INFERENCE_CLAIMS``) read as though any inference were
#: forbidden.
#:
#: What the evidence does not establish is *which* of the two states applied,
#: that the state held **at the moment** the gate refused, or that it is the
#: proven cause of that refusal. The diagnosis ran afterwards and returned one
#: closed word covering two states.
#:
#: Scoped to the fourth attempt deliberately. The *first* attempt was followed by
#: a separately authorized ``sts:GetCallerIdentity`` diagnosis that did classify
#: its session, and that sentence is accurate history which these must not reach.
SSO_EXACT_STATE_OVERCLAIMS: Final[tuple[str, ...]] = (
    # Causal. The diagnosis is evidence, not proof of why the gate refused.
    "THE FOURTH ATTEMPT REFUSED BECAUSE THE SESSION",
    "THE FOURTH ATTEMPT REFUSED BECAUSE THE SSO",
    "THE IDENTITY GATE REFUSED BECAUSE THE SESSION",
    "THE IDENTITY GATE REFUSED BECAUSE THE SSO",
    "A MISSING OR EXPIRED SESSION CAUSED THE FOURTH",
    # Contemporaneous. The diagnosis ran later, not during the attempt.
    "THE SESSION WAS MISSING OR EXPIRED AT THE FOURTH",
    "THE FOURTH ATTEMPT PROVED THE SESSION",
    "PROVED CONTEMPORANEOUSLY",
    # Exact state. One closed word covering two states is neither of them.
    #
    # Gone from this list: the bare "THE FOURTH ATTEMPT'S SSO SESSION", which
    # refused an accurate combined sentence for naming its subject. A guard
    # that blocks a true statement is answered by writing a vaguer one.
    "THE FOURTH ATTEMPT'S SESSION WAS MISSING",
    "THE FOURTH ATTEMPT'S SESSION WAS EXPIRED",
    "THE SESSION WAS DEFINITELY MISSING",
    "THE SESSION WAS DEFINITELY EXPIRED",
    "DEFINITELY MISSING",
    "DEFINITELY EXPIRED",
    "PROVEN TO BE MISSING",
    "PROVEN TO BE EXPIRED",
)

#: Current-status wording a fourth attempt made false.
#:
#: Scoped to the two status documents and the entry point, never to
#: ``docs/decisions/``, where an accepted ADR legitimately records what was true
#: when it was written. The documents still state history in attempt-specific
#: wording -- "at the time of the third attempt" -- which none of these reaches.
STALE_ATTEMPT_COUNT_CLAIMS: Final[tuple[str, ...]] = (
    "ALL THREE REFUSED",
    "THREE SEPARATELY AUTHORIZED ATTEMPTS",
    "INVOKED THREE TIMES UNDER SEPARATE AUTHORIZATION",
    "AUTHORIZED BINDING-PREFLIGHT ATTEMPTS TO DATE: THREE",
    "THREE AUTHORIZED ATTEMPTS TO DATE",
    "THREE LATER, SEPARATELY AUTHORIZED OPERATOR ATTEMPTS",
    "THREE OCCURRED.",
    "FOURTH BINDING-PREFLIGHT ATTEMPT: NOT AUTHORIZED",
    "ANOTHER BINDING-PREFLIGHT ATTEMPT: NOT AUTHORIZED",
    "ANOTHER BINDING-PREFLIGHT ATTEMPT NOT AUTHORIZED",
    "A FOURTH ATTEMPT, CREDENTIAL ACCESS BY THE APPLICATION",
)

#: The banner dividing the entry point's prose from its real-factory section.
#:
#: The event table and the factory commentary are two surfaces that must each
#: name the variable, and a guard over the whole file cannot tell which one it
#: found. Splitting on the banner scopes each requirement to its own region, so
#: dropping the name from one of them is caught by that region's guard.
FACTORY_SECTION_MARKER: Final = (
    "# The real factories. Referenced by `main`, never called by a test."
)

#: What the module docstring's event table must say about the fourth attempt.
#:
#: The variable is named, rather than described. "The environment variable" was
#: the original wording and it was wrong in a way only naming can fix -- see
#: :data:`STALE_ENVIRONMENT_READ_CLAIMS`.
#:
#: Named for the *identifier* rather than the secret. Spelling it
#: ``..._SECRET_SCOPE`` tripped ruff's hardcoded-password heuristic, and the
#: honest fix was the accurate name: this constant is about the identifier the
#: fourth attempt never resolved, not about a secret value, which appears
#: nowhere in this repository.
EVENT_TABLE_IDENTIFIER_SCOPE: Final = (
    "nor the secret-identifier source, so it did not read ``KALPAMANI_SHARADAR_SECRET_ID``"
)

#: The same requirement, scoped to the real-factory commentary.
FACTORY_IDENTIFIER_SCOPE: Final[tuple[str, ...]] = (
    "The fourth never reached it and therefore did not read",
    "`KALPAMANI_SHARADAR_SECRET_ID`. The scope is deliberate:",
    "`_ambient_profile`\n# reads `AWS_PROFILE` from the process environment",
    "is the one variable the fourth may be said to have left unread",
)

#: Unqualified claims that the fourth attempt read nothing from the environment.
#:
#: It read ``AWS_PROFILE``. ``_ambient_profile`` does that on every attempt, and
#: the fourth passed the governed profile contract -- so it demonstrably ran.
#: What the fourth attempt did not read is ``KALPAMANI_SHARADAR_SECRET_ID``,
#: because it refused two stages earlier, and that narrow claim is the only one
#: the run supports.
#:
#: The first revision of this slice wrote both blanket forms. They read as a
#: stronger absence than any run established, and an operator who believed them
#: would think the profile stage had been skipped.
STALE_ENVIRONMENT_READ_CLAIMS: Final[tuple[str, ...]] = (
    "did not read the environment variable",
    "read no environment variable",
    "read no environment variables",
    "read nothing from the environment",
    "performed no environment lookup on the fourth",
)

#: Denials that ``AWS_PROFILE`` was read, which would be the opposite error.
#:
#: Correcting an overbroad absence must not manufacture a new one. Nothing here
#: establishes that the profile variable was missing, unread or invalid -- the
#: fourth attempt passed the profile contract, so it was read and it was the
#: governed one. These are the affirmative denials, refused for the same reason
#: the blanket claims above are.
PROFILE_READ_DENIALS: Final[tuple[str, ...]] = (
    "did not read `AWS_PROFILE`",
    "did not read AWS_PROFILE",
    "never read `AWS_PROFILE`",
    "never read AWS_PROFILE",
    "AWS_PROFILE was not read",
    "AWS_PROFILE was unread",
    "AWS_PROFILE was absent",
    "AWS_PROFILE was invalid",
    "no AWS_PROFILE was read",
)

#: Affirmative claims that put the owner's setup after the fourth attempt.
#:
#: The index comparison beside :data:`FOURTH_ATTEMPT_ANCHOR` catches a chronology
#: whose *entries* move. It does not catch a sentence that leaves both anchors
#: where they are and reverses the claim between them -- "configured the variable
#: only after the fourth attempt" reads in document order and is false. A
#: negative control found exactly that gap, so the ordering guard is paired with
#: this one rather than trusted alone.
#:
#: Affirmative forms only, like every other refusal list here: the documents must
#: keep saying the setup happened after the *third* attempt and before the fourth.
REVERSED_CHRONOLOGY_CLAIMS: Final[tuple[str, ...]] = (
    "CONFIGURED THE VARIABLE ONLY AFTER THE FOURTH",
    "OWNER SETUP HAVING OCCURRED AFTER THE FOURTH",
    "SET UP AFTER THE FOURTH ATTEMPT",
    "OWNER SETUP OCCURRED AFTER THE FOURTH ATTEMPT",
    "THE FOURTH ATTEMPT RAN BEFORE THE OWNER",
    "THE FOURTH ATTEMPT PRECEDED THE OWNER",
    "BEFORE THAT SETUP",
)

#: The post-fourth AWS identity diagnosis, as the fenced block must record it.
#:
#: Raw, like the other count tuples: the block is column-aligned and read beside
#: the attempt rows above it.
#:
#: Two counts are deliberately different things. ``STS command invocations: ONE``
#: is what a caller can witness; ``diagnosis underlying AWS network requests:
#: UNKNOWN`` is what the command's own behaviour does not reveal, because a CLI
#: call resolves credentials locally and can fail before anything leaves the
#: machine. Collapsing them would be the same mistake ADR-0016 corrected.
POST_FOURTH_DIAGNOSIS_COUNTS: Final[tuple[str, ...]] = (
    "post-fourth AWS identity diagnosis: COMPLETED -- REFUSED_SSO_SESSION_MISSING_OR_EXPIRED",
    "diagnosis process invocations: ONE   ·   STS command invocations: ONE   ·   exit code: 255",
    "diagnosis underlying AWS network requests: UNKNOWN",
    "missing vs expired: NOT DISTINGUISHED by the diagnosis",
    "governed profile: PINNED IN THE CHILD ENVIRONMENT, NEVER DISCLOSED",
    "SSO-login invocations during the diagnosis: ZERO   ·   repair actions during it: ZERO",
    "fifth binding-preflight attempts at that point: ZERO",
)

#: What the diagnosis narrative must state, not merely tabulate.
POST_FOURTH_DIAGNOSIS_HISTORY: Final[tuple[str, ...]] = (
    "A separately authorized diagnosis has since answered that. It is an additional standalone",
    "neither the gate's own internal path above, nor the diagnosis that followed the first",
    "one process and one `aws sts get-caller-identity` command, which exited 255",
    "classified as `REFUSED_SSO_SESSION_MISSING_OR_EXPIRED`",
    "the governed SSO session or cached token was unavailable or expired",
    "It does not distinguish missing from expired",
    "first direct diagnostic evidence explaining the fourth attempt's identity refusal",
    "the attempt's own network-request total stays UNKNOWN",
    "At that point SSO-login invocations were ZERO",
    "authentication-repair actions were ZERO",
    "fifth binding-preflight attempts were ZERO",
)

#: How the diagnosis pinned the governed profile, and why that was correct.
#:
#: A shell-level pin does not survive separate tool invocations, so an unpinned
#: call would have fallen back to an unrelated default profile -- the wrong-account
#: hazard section 4.24 exists to prevent. Recording the *mechanism* matters: the
#: value came from a static parse of the repository's own constant, and the module
#: was never imported or executed.
PROFILE_PIN_FACTS: Final[tuple[str, ...]] = (
    "shell-level `AWS_PROFILE` pin does not persist across separate tool invocations",
    "an unpinned CLI call would have fallen back to an unrelated default profile",
    "statically parsing the repository-owned `EXPECTED_PROFILE` constant",
    "the entry-point module was neither imported nor executed",
    "That constant already existed in tracked executable source",
    "not print, log, disclose or newly write it",
    "added it to no document, comment, output or new file",
    "This is the governed profile, not an alternate one",
)

#: The two standalone diagnoses, which are different events.
#:
#: One followed the *first* attempt and preceded an SSO login; one followed the
#: *fourth* and was followed by nothing. A document that merges them would report
#: a single diagnosis whose session was then refreshed, which is false of the
#: second and would imply attempt 5 was reachable.
DISTINCT_DIAGNOSES: Final[tuple[str, ...]] = (
    "| separately authorized diagnosis | one `sts:GetCallerIdentity` request, which classified "
    "the session as missing or expired |",
    "| a second, separately authorized diagnosis, after the fourth attempt and after PR #28 "
    "merged |",
)

#: The chronology anchor for the post-fourth diagnosis, which must come last.
POST_FOURTH_DIAGNOSIS_ANCHOR: Final = (
    "a second, separately authorized diagnosis, after the fourth attempt and after PR #28 merged"
)

#: Current-status wording the completed diagnosis made false.
#:
#: Every entry is a *full* superseded form rather than a prefix of the corrected
#: one. "No diagnosis was performed" alone would match the accurate sentence that
#: replaced it -- "No diagnosis was performed during the attempt itself" -- and a
#: guard answered by deleting the true statement is worse than no guard.
STALE_NO_DIAGNOSIS_CLAIMS: Final[tuple[str, ...]] = (
    "UNKNOWN -- NO DIAGNOSIS WAS PERFORMED",
    "AND NO DIAGNOSIS WAS PERFORMED.",
    "NOTHING HERE ESTABLISHES THAT THE AWS SSO SESSION WAS MISSING, EXPIRED OR OTHERWISE DEFECTIVE",
    "AWS AUTHENTICATION DIAGNOSIS OR SSO REFRESH: SEPARATELY GATED",
    "AWS AUTHENTICATION DIAGNOSIS OR AN SSO REFRESH",
    "AWS AUTHENTICATION DIAGNOSIS AND AN SSO REFRESH ARE",
    "NO POST-FOURTH DIAGNOSIS",
    "AWS AUTHENTICATION DIAGNOSIS IS ENTIRELY FUTURE",
    "NO DIAGNOSIS HAS OCCURRED",
    "NO DIAGNOSIS OF THE FOURTH",
)

#: Claims the diagnosis does not support, each in the affirmative form.
#:
#: It returned one closed word. It did not say *which* of missing or expired, it
#: did not pass, nothing was logged in or repaired afterwards, no fifth attempt
#: ran, and the underlying network count stays unknown in both directions.
DIAGNOSIS_OVERCLAIMS: Final[tuple[str, ...]] = (
    "IDENTITY_PASSED",
    "THE SSO SESSION WAS SPECIFICALLY MISSING",
    "THE SSO SESSION WAS SPECIFICALLY EXPIRED",
    "THE SESSION WAS MISSING, NOT EXPIRED",
    "THE SESSION WAS EXPIRED, NOT MISSING",
    "MISSING RATHER THAN EXPIRED",
    "EXPIRED RATHER THAN MISSING",
    # Subject-scoped, and that is a correction rather than a relaxation. The
    # six entries that stood here were bare -- "a successful AWS SSO login
    # occurred", "the session was refreshed" -- and a corrected second login
    # has since made every one of them a true statement about a *different*
    # event. A document-wide ban on a true sentence is answered by writing a
    # vaguer one, so each now names the diagnosis it is about.
    "THE DIAGNOSIS PERFORMED AN SSO LOGIN",
    "AN SSO LOGIN WAS PERFORMED DURING THE DIAGNOSIS",
    "A SUCCESSFUL AWS SSO LOGIN OCCURRED DURING THE DIAGNOSIS",
    "THE DIAGNOSIS REPAIRED AUTHENTICATION",
    "AUTHENTICATION WAS REPAIRED BY THE DIAGNOSIS",
    "THE DIAGNOSIS REFRESHED THE SESSION",
    "THE SESSION WAS REFRESHED BY THE DIAGNOSIS",
    "THE FIFTH ATTEMPT OCCURRED",
    "THE FIFTH ATTEMPT RAN",
    "A FIFTH BINDING-PREFLIGHT ATTEMPT OCCURRED",
    "DIAGNOSIS AWS NETWORK REQUESTS: ZERO",
    "DIAGNOSIS AWS NETWORK REQUESTS: ONE",
    "THE DIAGNOSIS SENT ONE AWS NETWORK REQUEST",
    "THE DIAGNOSIS SENT NO AWS NETWORK REQUEST",
)

#: The fenced-block record of the timed-out post-diagnosis SSO-login attempt.
#:
#: One authorized ``aws sso login`` invocation ran after PR #29 merged, and it
#: did not succeed. The *shape* of that failure is the point: the process was
#: terminated on a 420-second timeout, so it returned **no status at all**.
#: Writing a numeric exit code would invent one, which is the class of error
#: ADR-0016 corrected -- a report naming a boundary the run never reached.
SSO_LOGIN_ATTEMPT_COUNTS: Final[tuple[str, ...]] = (
    "post-diagnosis AWS SSO-login attempt: COMPLETED -- REFUSED_SSO_LOGIN",
    "SSO-login command invocations: ONE   ·   command: aws sso login --no-cli-pager",
    "SSO-login exit code: NOT AVAILABLE / PROCESS TERMINATED ON TIMEOUT",
    "SSO-login timeout: 420 SECONDS   ·   lingering AWS CLI process: NONE",
    "browser authorization interactions: ZERO   ·   device authorizations completed: ZERO",
    "SSO refreshes achieved by the first attempt: ZERO   ·   "
    "SSO session after it: STILL UNREFRESHED",
    "SSO-login underlying AWS network requests: UNKNOWN",
    "identity-confirmation command invocations after the first attempt: ZERO",
    "likely cause: INTERACTIVE BROWSER/DEVICE-CODE SURFACE SUPPRESSED -- LIKELY, NOT PROVEN",
    "device URL or code in the first attempt's undisplayed buffer: UNKNOWN -- NOT INSPECTED",
)

#: What the attempt's narrative must state, not merely tabulate.
#:
#: The counts say what happened; these say what it means and what it left alone.
#: An attempt recorded only as a row of zeros reads as an event with no bearing
#: on anything, and this one has a specific bearing: it revised no earlier
#: finding, verified no identifier, and retrieved nothing.
SSO_LOGIN_ATTEMPT_HISTORY: Final[tuple[str, ...]] = (
    "A separately authorized AWS SSO-login attempt has since been made, and it did not succeed.",
    "it invoked one process and one `aws sso login --no-cli-pager` command",
    "resolved by statically parsing the tracked `EXPECTED_PROFILE` constant",
    "the entry-point module was neither imported nor executed",
    "pinned in the child process only, never disclosed",
    "It timed out after 420 seconds, was terminated, and left no lingering AWS CLI process.",
    "A terminated process returns no status",
    "exit code: NOT AVAILABLE / PROCESS TERMINATED ON TIMEOUT",
    "never as a numeric exit code",
    "the closed public outcome is `REFUSED_SSO_LOGIN`",
    "Browser authorization interactions ZERO",
    "device authorizations completed ZERO",
    "successful SSO refreshes ZERO",
    "identity-confirmation command invocations ZERO",
    "Its underlying AWS network-request count is UNKNOWN",
    "The SSO session remained unrefreshed",
    "the earlier diagnosis stands unrevised at `REFUSED_SSO_SESSION_MISSING_OR_EXPIRED`",
    "no evidence distinguishing missing from expired",
    "did not verify or contradict the owner-configured secret identifier",
    "retrieved no credential",
)

#: The likely-versus-proven scoping of why the interaction failed.
#:
#: Everything here is evidence about the **operator's handling**: output was
#: captured rather than streamed, nothing reached the owner, and the process
#: waited its whole timeout. That supports *likely*, and nothing supports
#: *proven*: the buffer was never inspected and cannot be inspected now, so
#: whether the CLI even emitted a device URL or code is unknown in both
#: directions. A procedural explanation promoted to a proven AWS-configuration
#: defect would send the next session to repair something nobody has shown to
#: be broken.
SSO_LOGIN_CAUSE_SCOPE: Final[tuple[str, ...]] = (
    "The likely cause is procedural, and it is recorded as likely rather than proven.",
    "stdout and stderr were captured rather than streamed",
    "no browser appeared, no device URL or code was displayed to the owner",
    "the process waited the full 420 seconds",
    "likely caused by suppressing the interactive browser/device-code surface",
    "an operational-handling explanation, not proof of an AWS configuration defect",
    "was not inspected and remains UNKNOWN",
    "no raw output may be inspected now to resolve that uncertainty",
    "Nothing here establishes a defective AWS SSO configuration",
    "an incorrect governed profile",
    "a wrong SSO start URL",
    "the presence or absence of a generated device code",
)

#: What stays unauthorized now that one SSO-login attempt has failed.
#:
#: Stated as an explicit sentence rather than left to inference. A failed
#: operation reads as an invitation to repeat it, and the whole point of the
#: gate is that it is not one.
SSO_LOGIN_FORWARD_BOUNDARIES: Final[tuple[str, ...]] = (
    "A failed login attempt is not permission to retry.",
    "Another AWS SSO-login/refresh attempt NOT AUTHORIZED",
    "further AWS authentication diagnosis NOT AUTHORIZED",
    "a sixth binding-preflight attempt NOT AUTHORIZED",
    "additional credential or Secrets Manager access NOT AUTHORIZED",
    "a third authenticated qualification attempt NOT AUTHORIZED",
)

#: Current-status wording the SSO-login attempt made false.
#:
#: Every entry is a **full** superseded form, never a prefix of the corrected
#: one -- the discipline :data:`STALE_NO_DIAGNOSIS_CLAIMS` documents. The
#: corrected text says "SSO-login invocations during the diagnosis: ZERO" and
#: "At that point SSO-login invocations were ZERO", and neither contains the
#: bare forms below, so a document can be accurate about the diagnosis's own
#: zeros without tripping a guard about the current total.
STALE_SSO_LOGIN_CLAIMS: Final[tuple[str, ...]] = (
    "SSO-LOGIN INVOCATIONS: ZERO",
    "SSO-LOGIN INVOCATIONS ZERO",
    "SSO-LOGIN COMMAND INVOCATIONS: ZERO",
    "AUTHORIZED AWS SSO-LOGIN ATTEMPTS TO DATE: ZERO",
    "ZERO SSO LOGINS, ZERO REPAIR ACTIONS",
    "AWS SSO REFRESH/LOGIN: SEPARATELY GATED",
    "AWS SSO REFRESH/LOGIN SEPARATELY GATED",
    "NO SSO LOGIN OCCURRED",
    "NO SSO-LOGIN INVOCATION FOLLOWED",
    "NO SSO-LOGIN INVOCATION HAS OCCURRED",
    "NO AWS SSO LOGIN HAS BEEN ATTEMPTED",
    "NO SSO LOGIN HAS BEEN ATTEMPTED",
    "AN AWS SSO REFRESH OR LOGIN IS ENTIRELY FUTURE",
    "ALL SSO-LOGIN ACTIVITY IS FUTURE",
    "SSO-LOGIN ACTIVITY IS ENTIRELY FUTURE",
    "AN SSO LOGIN REMAINS ENTIRELY FUTURE",
)

#: Claims the timed-out attempt does not support, each in the affirmative form.
#:
#: Affirmative deliberately, and the documents state the same subjects as noun
#: phrases -- "a defective AWS SSO configuration", "an incorrect governed
#: profile" -- so the sentence *denying* each cannot trip the guard denying it.
#: An earlier draft wrote the denial as "nothing establishes that the governed
#: profile is incorrect", which contains this list's own entry: the guard would
#: have been answered by deleting the true disclaimer.
#:
#: The numeric exit codes are listed individually. A timeout returns no status,
#: so any number here is invented, and 255 in particular is the *diagnosis*
#: command's code -- the nearest wrong answer to hand.
#: The eighteen bare success forms that stood here are gone, and the reason is
#: the same one :data:`DIAGNOSIS_OVERCLAIMS` records: a corrected second login
#: succeeded, refreshed the session and was followed by one identity
#: confirmation, so "the SSO login succeeded", "successful SSO refreshes: ONE"
#: and ``IDENTITY_CONFIRMED`` are now facts this repository must be able to
#: state. Each is replaced by a form naming the *first* attempt, which is the
#: one this list was ever about. What a successful refresh does **not** license
#: is in :data:`CORRECTED_SSO_OVERCLAIMS`, and what it makes stale is in
#: :data:`STALE_CORRECTED_SSO_CLAIMS`.
SSO_LOGIN_OVERCLAIMS: Final[tuple[str, ...]] = (
    "THE FIRST SSO LOGIN SUCCEEDED",
    "THE FIRST SSO-LOGIN ATTEMPT SUCCEEDED",
    "THE FIRST ATTEMPT SUCCEEDED",
    "THE TIMED-OUT SSO LOGIN SUCCEEDED",
    "THE TIMED-OUT ATTEMPT SUCCEEDED",
    "THE FIRST ATTEMPT REFRESHED THE SSO SESSION",
    "THE FIRST ATTEMPT REFRESHED THE SESSION",
    "THE FIRST ATTEMPT COMPLETED A BROWSER AUTHORIZATION",
    "THE FIRST ATTEMPT COMPLETED A DEVICE AUTHORIZATION",
    "THE FIRST ATTEMPT CONFIRMED AN IDENTITY",
    "AN IDENTITY CONFIRMATION FOLLOWED THE FIRST ATTEMPT",
    "THE FIRST ATTEMPT GENERATED A DEVICE CODE",
    "THE FIRST ATTEMPT GENERATED NO DEVICE CODE",
    "FIRST SSO-LOGIN EXIT CODE: 0",
    "A RETRY IS AUTHORIZED",
    "A RETRY IS NOW AUTHORIZED",
    "ANOTHER SSO LOGIN IS AUTHORIZED",
    "A FIFTH BINDING-PREFLIGHT ATTEMPT IS AUTHORIZED",
    "SSO-LOGIN UNDERLYING AWS NETWORK REQUESTS: ZERO",
    "SSO-LOGIN UNDERLYING AWS NETWORK REQUESTS: ONE",
    "THE SSO-LOGIN ATTEMPT SENT ONE AWS NETWORK REQUEST",
    "THE SSO-LOGIN ATTEMPT SENT NO AWS NETWORK REQUEST",
    "SSO-LOGIN EXIT CODE: 1",
    "SSO-LOGIN EXIT CODE: 255",
    "SSO-LOGIN EXIT CODE 255",
    "TIMED OUT WITH EXIT CODE",
    "EXIT CODE: TIMEOUT",
    "THE AWS SSO CONFIGURATION IS DEFECTIVE",
    "THE SSO CONFIGURATION IS DEFECTIVE",
    "SSO CONFIGURATION IS DEFINITELY DEFECTIVE",
    "THE GOVERNED PROFILE IS INCORRECT",
    "THE GOVERNED PROFILE WAS INCORRECT",
    "THE GOVERNED PROFILE WAS WRONG",
    "THE SSO START URL IS WRONG",
    "THE BROWSER FAILED TO LAUNCH BECAUSE",
    "THE PROVEN CAUSE",
    "PROVEN TO BE CAUSED BY",
    "DEFINITELY CAUSED BY",
    "THE CREDENTIAL WAS RETRIEVED",
    "THE SECRET IDENTIFIER WAS READ",
)

#: The bounds of the SSO-login narrative inside the ADR-0015 section.
#:
#: The environment guards below are scoped to this span and not to the section,
#: because the section also carries accurate component-scoped statements about
#: what *earlier* attempts read -- the fourth never reaching
#: ``KALPAMANI_SHARADAR_SECRET_ID``, the environment verification reading no
#: profile or SSO cache. A guard about *this runner's* environment copy has no
#: business reaching those, and a document-wide version would eventually be
#: answered by weakening a true sentence somewhere else.
SSO_LOGIN_NARRATIVE_BOUNDS: Final[tuple[str, str]] = (
    "A separately authorized AWS SSO-login attempt has since been made",
    "qualification attempt NOT AUTHORIZED.",
)

#: How the child environment was built, and what that does and does not mean.
#:
#: The first revision of this slice wrote "No credential value was read or
#: displayed", and the reported mechanism does not support it: the runner built
#: the child environment with ``dict(os.environ)``, and copying a process
#: environment **transiently materializes every value in it**, credential-bearing
#: ones included. That is not inspection -- the named static AWS credential
#: variables were dropped **by name**, never examined -- but "not read" and "not
#: inspected" are different claims, and only the second is true.
#:
#: So the facts required here are the mechanical ones plus the four that are the
#: actual boundary: not individually inspected, not passed to the child, not
#: printed or persisted, and the parent environment left alone. An absence stated
#: more strongly than the mechanism supports is the same defect ADR-0016
#: corrected, one layer up.
SSO_LOGIN_ENVIRONMENT_FACTS: Final[tuple[str, ...]] = (
    "The child environment was built by copying the parent process environment",
    "that copy transiently materialized the parent environment's values in the runner process",
    "the credential-bearing ones included",
    "a mechanical consequence of copying a process environment",
    "an earlier revision of this section asserted a stronger absence than the mechanism supports",
    "Copying is not inspection, use, disclosure or persistence",
    "removed from the child environment before the AWS CLI process was started",
    "not individually inspected, tested, enumerated or classified",
    "not passed to, and not used by, the AWS CLI child",
    "No credential value was printed, logged, disclosed or persisted",
    "the parent environment itself was not modified",
    "not deliberately inspected and not used as the profile selection",
)

#: Absences the environment copy cannot support, and uses it did not make.
#:
#: The first four are stronger than the mechanism: values *were* materialized by
#: the copy, and the parent environment *was* copied. The next two are claims
#: about the parent environment's contents that nothing observed -- dropping a
#: key by name establishes neither its absence nor an empty value. The last two
#: are the opposite error: the removed variables never reached the child, so the
#: CLI neither received nor used them.
#:
#: Scoped to :data:`SSO_LOGIN_NARRATIVE_BOUNDS` only.
SSO_LOGIN_ENVIRONMENT_OVERCLAIMS: Final[tuple[str, ...]] = (
    "NO CREDENTIAL VALUE WAS READ",
    "NO ENVIRONMENT-VARIABLE VALUE WAS READ",
    "CREDENTIAL VALUES WERE NEVER MATERIALIZED",
    "THE PARENT ENVIRONMENT WAS NOT COPIED",
    "CREDENTIAL VARIABLES WERE ABSENT",
    "CREDENTIAL VALUES WERE EMPTY",
    "THE AWS CLI RECEIVED THE AMBIENT STATIC CREDENTIALS",
    "THE AWS CLI USED UNRELATED CREDENTIALS",
)

#: The chronology anchor for the SSO-login attempt, which must come last.
SSO_LOGIN_ATTEMPT_ANCHOR: Final = (
    "a separately authorized AWS SSO-login attempt, after that diagnosis and after PR #29 merged"
)

#: The fenced-block record of the corrected AWS SSO-login attempt and the one
#: identity confirmation that followed it.
#:
#: A second login was separately authorized after PR #30 merged, and it
#: succeeded. Its counts are named apart from the first attempt's -- "first"
#: against "corrected" -- because an unqualified "SSO-login exit code" line
#: sitting beside two attempts is a line a reader has to guess at, and guessing
#: is exactly what the earlier undistinguished blocks forced.
CORRECTED_SSO_REFRESH_COUNTS: Final[tuple[str, ...]] = (
    "authorized AWS SSO-login attempts to date: TWO -- the first refused, the second succeeded",
    "corrected AWS SSO-login attempt: COMPLETED -- SUCCESSFUL",
    "corrected SSO-login command invocations: ONE   ·   command: aws sso login --no-cli-pager",
    "corrected SSO-login session: A NEW CLAUDE SESSION",
    "corrected SSO-login output handling: LIVE CONSOLE -- INHERITED STDIN, STDOUT AND STDERR",
    "corrected SSO-login capture, pipe, redirect, buffer or file: NONE",
    "corrected SSO-login interactive browser/device flow: COMPLETED",
    "corrected SSO-login exit code: 0   ·   lingering AWS CLI process: NONE",
    "successful governed SSO refreshes: ONE",
    "corrected SSO-login underlying AWS network requests: UNKNOWN",
    "corrected child environment: MINIMAL AND ALLOWLISTED, BUILT KEY-BY-KEY",
    "whole-environment copy during the corrected attempt: NONE",
    "credential-bearing ambient variables copied or inspected during it: NONE",
    "governed profile source: STATIC AST PARSE OF EXPECTED_PROFILE, NEVER DISCLOSED",
    "entry-point module imported or executed by either SSO operation: NEITHER",
    "verification URL and one-time device code: TRANSIENT IN THE LIVE CONSOLE ONLY",
    "sanitized identity confirmations after the corrected refresh: ONE -- SUCCESSFUL",
    "identity-confirmation command: aws sts get-caller-identity --no-cli-pager --output json",
    "identity-confirmation exit code: 0   ·   classification: IDENTITY_CONFIRMED",
    "identity-confirmation response: UserId, Account AND Arn STRUCTURALLY PRESENT AND NON-EMPTY",
    "raw identity response and private identity values: NOT DISPLAYED, NOT PERSISTED",
    "captured identity buffers: CLEARED AFTER CLASSIFICATION",
    "identity-confirmation underlying AWS network requests: UNKNOWN",
    "identity status: CONFIRMED AT THE TIME OF THAT COMMAND",
    "current or future session validity: NOT GUARANTEED BY THAT HISTORICAL CONFIRMATION",
    "KALPAMANI_SHARADAR_SECRET_ID reads by the corrected SSO session: ZERO",
    "fifth binding-preflight attempts immediately after the corrected refresh: ZERO",
)

#: What the corrected attempt's narrative must state, not merely tabulate.
CORRECTED_SSO_REFRESH_HISTORY: Final[tuple[str, ...]] = (
    "A corrected, separately authorized SSO login has since completed, and the governed "
    "session was refreshed.",
    "Run in a new Claude session after PR #30 merged",
    "it invoked one process and one `aws sso login --no-cli-pager` command",
    "on a live console with inherited stdin, stdout and stderr",
    "Nothing was captured, piped, redirected, buffered or written to a file",
    "The interactive browser/device flow completed",
    "the command exited `0`",
    "no lingering AWS CLI process remained",
    "successful governed SSO refreshes became ONE",
)

#: The live-console versus captured-output distinction, stated as observation.
#:
#: The first attempt's stdout and stderr were captured, the corrected one's were
#: inherited, and the corrected attempt worked. Those are observations, and the
#: entry that stood beside them was a conclusion: it required the documents to
#: say the earlier attempt's output handling was the one thing it got wrong.
#: Nothing in this repository supports that. The two runs differed in more than
#: output handling -- different sessions, a whole-environment copy against a
#: minimal allowlisted one, and whatever point-in-time SSO state each met -- and
#: the earlier buffer was never inspected, so capture is neither established as
#: the cause nor ruled out as a contributor.
#:
#: The contrast is required, because a document recording two attempts without
#: it records two coincidences. The cause is not required, because it is not
#: known: see :data:`SSO_CAUSE_EVIDENCE_SCOPE` for what must be said instead and
#: :data:`SSO_CAUSE_OVERCLAIMS` for what may not.
SSO_OUTPUT_HANDLING_CONTRAST: Final[tuple[str, ...]] = (
    "stdout and stderr were captured rather than streamed",
    "on a live console with inherited stdin, stdout and stderr",
    "Nothing was captured, piped, redirected, buffered or written to a file",
    "The first attempt captured stdout and stderr",
    "Output handling was one deliberate correction",
)

#: Observation held apart from inference, in the corrected-refresh prose.
#:
#: Ten facts are established: the first attempt captured its streams, no
#: interactive surface reached the owner, it timed out at 420 seconds, its
#: buffer was never inspected, the corrected attempt inherited a live console,
#: its browser/device flow completed, it exited zero, one identity confirmation
#: followed and succeeded, and streaming the interactive surface was a
#: deliberate corrective measure. The tenth is what the other nine do **not**
#: add up to: they are consistent with capture contributing to the earlier
#: timeout, and they do not establish it as necessary, sufficient or sole.
#:
#: Required inside the bounded corrected-refresh prose rather than the section,
#: for the reason :data:`CORRECTED_SSO_NARRATIVE_BOUNDS` records: the event row
#: restates the handling facts, and a row must not answer for the prose.
SSO_CAUSE_EVIDENCE_SCOPE: Final[tuple[str, ...]] = (
    "Output handling was one deliberate correction, and the evidence stops short of a cause.",
    "The first attempt captured stdout and stderr",
    "the corrected attempt used a live console with inherited stdin, stdout and stderr",
    "and it completed successfully",
    "Streaming the interactive surface was a deliberate corrective measure",
    "consistent with the interactive surface contributing to the earlier timeout",
    "the earlier buffer was never inspected",
    "capture is not established as the sole, necessary, sufficient or definitive cause",
    "likely, not proven",
    "The two attempts differed in more than output handling",
    "They ran in different Claude sessions",
    "the first copied the whole parent process environment",
    "the corrected one built a minimal allowlisted child environment key-by-key",
    "the point-in-time SSO state may itself have differed",
    "Nothing here claims the two runs were otherwise identical",
    "the second attempt's success does not establish why the first failed",
)

#: Causal conclusions the two attempts do not support, each affirmative.
#:
#: Scoped to the two status documents. The ADR-0015 operator entry point still
#: carries the superseded sentence in its own docstring; correcting that file is
#: a separate, separately authorized edit, and this round was scoped to leave it
#: byte-identical. Widening this list to that file would fail the audit for a
#: defect nobody was authorized to fix here, which is worse than recording it.
#:
#: Every entry is written so the *true* disclaimer beside it cannot match. The
#: documents say "capture is not established as the sole, necessary, sufficient
#: or definitive cause" and "Nothing here claims the two runs were otherwise
#: identical"; an entry that were a substring of either would be answered by
#: deleting the sentence it exists to protect.
SSO_CAUSE_OVERCLAIMS: Final[tuple[str, ...]] = (
    "THE ONE THING THE FIRST ATTEMPT GOT WRONG",
    "THE SINGLE DIFFERENCE",
    "THE WHOLE OPERATIONAL FINDING",
    "OUTPUT HANDLING WAS THE ONLY DIFFERENCE",
    "THE ONLY DIFFERENCE BETWEEN THE TWO ATTEMPTS",
    "OUTPUT CAPTURE WAS THE SOLE CAUSE",
    "CAPTURE WAS THE SOLE CAUSE",
    "THE SOLE CAUSE OF THE TIMEOUT",
    "OUTPUT CAPTURE DEFINITIVELY CAUSED",
    "DEFINITIVELY CAUSED THE TIMEOUT",
    "CAPTURING OUTPUT CAUSED THE TIMEOUT",
    "THE TIMEOUT WAS CAUSED BY CAPTURING",
    "CAPTURE IS ESTABLISHED AS THE SOLE",
    "CAPTURE WAS NECESSARY AND SUFFICIENT",
    "CAPTURE WAS SUFFICIENT TO CAUSE",
    "LIVE STREAMING DEFINITIVELY FIXED",
    "STREAMING DEFINITIVELY FIXED THE CAUSE",
    "STREAMING FIXED THE CAUSE",
    "ALL OTHER EXECUTION CONDITIONS WERE IDENTICAL",
    "EVERY OTHER EXECUTION CONDITION WAS IDENTICAL",
    "OTHERWISE IDENTICAL CONDITIONS",
    "THE TWO RUNS WERE IDENTICAL APART FROM",
    "SUCCESS ESTABLISHES WHY THE FIRST FAILED",
    "THE SECOND ATTEMPT PROVES WHY THE FIRST FAILED",
    "PROVES WHY THE FIRST FAILED",
    "THE CAUSE IS ESTABLISHED",
    "THE CAUSE IS PROVEN",
    "PROVEN CAUSE OF THE TIMEOUT",
)

#: How the corrected attempt's child environment was built.
#:
#: The first attempt copied the parent process environment wholesale, which
#: transiently materialized every value in it. This one did not, and the claim
#: is scoped to *this* run rather than backdated onto the earlier one -- the
#: same discipline :data:`SSO_LOGIN_ENVIRONMENT_FACTS` records for the run that
#: did copy.
CORRECTED_CHILD_ENVIRONMENT_FACTS: Final[tuple[str, ...]] = (
    "The child environment was built the narrow way this time.",
    "static AST parse of the tracked `EXPECTED_PROFILE` constant",
    "the entry-point module was neither imported nor executed",
    "the value was not disclosed",
    "A minimal, allowlisted child environment was built key-by-key",
    "there was no whole-environment copy",
    "no credential-bearing ambient variable was copied or inspected",
    "That closes the transient materialization the first attempt's whole-environment copy produced",
    "stated as a property of this run rather than backdated onto the earlier one",
    "The verification URL and the one-time device code appeared only transiently in the "
    "live AWS console",
    "not repeated and not persisted",
)

#: The one sanitized identity confirmation, and the four things it is not.
#:
#: It ran because the corrected login exited zero, it returned zero, and its
#: response was read **structurally**. What it establishes is a session fact at
#: one instant; what it does not establish is anything about the secret, the
#: credential, the bucket, the provider, or any later session.
IDENTITY_CONFIRMATION_FACTS: Final[tuple[str, ...]] = (
    "Because that login exited `0`, exactly one identity confirmation ran.",
    "One `aws sts get-caller-identity --no-cli-pager --output json` command, which exited `0`.",
    "The response structurally contained non-empty `UserId`, `Account` and `Arn` fields",
    "that structural check is the whole of what was read from it",
    "The raw response and the private identity values were neither displayed nor persisted",
    "the outcome was classified `IDENTITY_CONFIRMED`",
    "the captured buffers were cleared after classification",
    "A successful identity confirmation is a historical session fact and nothing more.",
    "Identity was confirmed at the time of that command",
    "no current or future session validity is guaranteed",
    "verified no secret identifier, no secret, no API key, no bucket and no provider access",
    "It is not a fifth binding-preflight attempt",
    "the fifth attempt came later, under its own separate authorization, and is recorded below",
)

#: What stays gated now that one SSO login has succeeded.
#:
#: A completed authorization reads as a standing one unless it is refused in
#: words. That is the same reason :data:`SSO_LOGIN_FORWARD_BOUNDARIES` exists
#: for the attempt that failed: success and failure both invite a repeat.
CORRECTED_SSO_FORWARD_BOUNDARIES: Final[tuple[str, ...]] = (
    "A completed authorization is not a standing one.",
    "Two SSO-login attempts have now been separately authorized",
    "the first refused, the second succeeded",
    "each was authorized for itself, not for the next one",
    "The same holds for the five binding-preflight attempts, the fifth and successful "
    "one included.",
    "Another AWS SSO refresh or login is SEPARATELY GATED and NOT AUTHORIZED",
    "a sixth binding-preflight attempt NOT AUTHORIZED",
    "additional credential or Secrets Manager access NOT AUTHORIZED",
    "an authenticated qualification run NOT AUTHORIZED",
)

#: Current-status wording the corrected refresh and the confirmation made false.
#:
#: Full superseded forms, never a prefix of the corrected one -- the discipline
#: :data:`STALE_NO_DIAGNOSIS_CLAIMS` documents. The documents still say
#: "SSO refreshes achieved by the first attempt: ZERO" and "successful SSO
#: refreshes zero" inside the first attempt's own narrative, and neither
#: contains a colon form below.
STALE_CORRECTED_SSO_CLAIMS: Final[tuple[str, ...]] = (
    "SUCCESSFUL SSO REFRESHES: ZERO",
    "SUCCESSFUL GOVERNED SSO REFRESHES: ZERO",
    "SUCCESSFUL SSO REFRESHES REMAIN ZERO",
    "NO SUCCESSFUL SSO REFRESH HAS OCCURRED",
    "NO SSO REFRESH HAS OCCURRED",
    "NO AWS SSO REFRESH OR LOGIN HAS OCCURRED",
    "AN AWS SSO REFRESH OR LOGIN HAS NEVER OCCURRED",
    "ANOTHER AWS SSO REFRESH OR LOGIN IS ENTIRELY FUTURE",
    "AUTHORIZED AWS SSO-LOGIN ATTEMPTS TO DATE: ONE",
    "SSO-LOGIN ATTEMPTS REMAIN ONE",
    "THE SSO SESSION REMAINS UNREFRESHED",
    "SSO SESSION: STILL UNREFRESHED",
    "IDENTITY CONFIRMATIONS: ZERO",
    "IDENTITY CONFIRMATIONS AFTER IT: ZERO",
    "IDENTITY-CONFIRMATION COMMAND INVOCATIONS: ZERO",
    "SANITIZED IDENTITY CONFIRMATIONS: ZERO",
    "IDENTITY CONFIRMATION HAS NEVER RUN",
    "NO IDENTITY CONFIRMATION HAS RUN",
    "NO IDENTITY CONFIRMATION HAS OCCURRED",
    "THE GOVERNED IDENTITY REMAINS REFUSED",
    "THE GOVERNED IDENTITY GATE REMAINS REFUSED",
    "AWS AUTHENTICATION REMAINS UNREPAIRED",
    "AWS AUTHENTICATION REMAINS UNCONFIRMED",
    "THE CORRECTED SSO LOGIN TIMED OUT",
    "THE CORRECTED SSO LOGIN REFUSED",
    "THE CORRECTED ATTEMPT TIMED OUT",
    "THE CORRECTED ATTEMPT REFUSED",
    "THE CORRECTED LOGIN DID NOT SUCCEED",
    "THE SECOND SSO-LOGIN ATTEMPT TIMED OUT",
)

#: Claims the corrected refresh and the confirmation do not support.
#:
#: Affirmative forms, and deliberately not prefixes of the true denials the
#: documents carry: "no current or future session validity is guaranteed"
#: contains the words a careless entry here would refuse, and a guard answered
#: by deleting the disclaimer is worse than no guard.
CORRECTED_SSO_OVERCLAIMS: Final[tuple[str, ...]] = (
    "THE SESSION WILL REMAIN VALID",
    "THE SESSION IS GUARANTEED TO REMAIN VALID",
    "FUTURE SESSIONS ARE GUARANTEED VALID",
    "GUARANTEES CURRENT AND FUTURE SESSION VALIDITY",
    "CURRENT AND FUTURE SESSION VALIDITY ARE ESTABLISHED",
    "THE IDENTITY REMAINS CONFIRMED",
    "IDENTITY IS CURRENTLY CONFIRMED",
    "THE SESSION IS STILL AUTHENTICATED",
    "THE IDENTITY CONFIRMATION VERIFIED THE SECRET",
    "THE IDENTITY CONFIRMATION VERIFIED THE CREDENTIAL",
    "THE IDENTITY CONFIRMATION VERIFIED THE API KEY",
    "THE IDENTITY CONFIRMATION VERIFIED THE BUCKET",
    "THE IDENTITY CONFIRMATION VERIFIED PROVIDER ACCESS",
    "THE SECRET IDENTIFIER IS VERIFIED",
    "THE SECRET IDENTIFIER HAS BEEN VERIFIED",
    "THE SECRET IDENTIFIER WAS VERIFIED BY",
    "THE CREDENTIAL IS VERIFIED",
    "THE CREDENTIAL HAS BEEN VERIFIED",
    "THE IDENTITY CONFIRMATION WAS THE FIFTH ATTEMPT",
    "THE FIFTH ATTEMPT WAS THE IDENTITY CONFIRMATION",
    "IDENTITY CONFIRMATIONS: TWO",
    "SUCCESSFUL GOVERNED SSO REFRESHES: TWO",
    "CORRECTED SSO-LOGIN UNDERLYING AWS NETWORK REQUESTS: ZERO",
    "CORRECTED SSO-LOGIN UNDERLYING AWS NETWORK REQUESTS: ONE",
    "IDENTITY-CONFIRMATION UNDERLYING AWS NETWORK REQUESTS: ZERO",
    "IDENTITY-CONFIRMATION UNDERLYING AWS NETWORK REQUESTS: ONE",
    "THE CORRECTED ATTEMPT SENT ONE AWS NETWORK REQUEST",
    "THE CORRECTED ATTEMPT SENT NO AWS NETWORK REQUEST",
    "THE IDENTITY CONFIRMATION SENT ONE AWS NETWORK REQUEST",
    "THE IDENTITY CONFIRMATION SENT NO AWS NETWORK REQUEST",
    "CORRECTED SSO-LOGIN EXIT CODE: 1",
    "CORRECTED SSO-LOGIN EXIT CODE: 255",
    "IDENTITY-CONFIRMATION EXIT CODE: 1",
    "IDENTITY-CONFIRMATION EXIT CODE: 255",
    "THE RAW IDENTITY RESPONSE WAS DISPLAYED",
    "THE RAW IDENTITY RESPONSE WAS PERSISTED",
    "THE PRIVATE IDENTITY VALUES WERE DISPLAYED",
    "THE ACCOUNT ID WAS DISPLAYED",
    "THE ARN WAS DISPLAYED",
    "THE USER ID WAS DISPLAYED",
    "THE DEVICE CODE WAS PERSISTED",
    "THE VERIFICATION URL WAS PERSISTED",
    "A WHOLE-ENVIRONMENT COPY WAS USED",
    "THE PARENT ENVIRONMENT WAS COPIED WHOLESALE",
    "CREDENTIAL-BEARING AMBIENT VARIABLES WERE COPIED",
    "CREDENTIAL-BEARING AMBIENT VARIABLES WERE INSPECTED",
    "ANOTHER SSO REFRESH IS AUTHORIZED",
    "A SIXTH ATTEMPT IS NOW AUTHORIZED",
    "ADDITIONAL CREDENTIAL ACCESS IS NOW AUTHORIZED",
)

#: The bounds of the corrected-refresh narrative inside the ADR-0015 section.
#:
#: The event table states the same facts in its own row, so a section-wide guard
#: cannot tell the prose from the table -- and a negative control proved it:
#: deleting the live-console sentence from the prose left the guard green on the
#: strength of the row. Both surfaces are required, each in its own scope.
CORRECTED_SSO_NARRATIVE_BOUNDS: Final[tuple[str, str]] = (
    "A corrected, separately authorized SSO login has since completed",
    "an authenticated qualification run NOT AUTHORIZED.",
)

#: What the corrected-refresh prose must state in its own narrative, not only in
#: the event table beside it.
CORRECTED_SSO_NARRATIVE_FACTS: Final[tuple[str, ...]] = (
    "on a live console with inherited stdin, stdout and stderr",
    "Nothing was captured, piped, redirected, buffered or written to a file",
    "The interactive browser/device flow completed",
    "successful governed SSO refreshes became ONE",
    "A minimal, allowlisted child environment was built key-by-key",
    "there was no whole-environment copy",
    "no credential-bearing ambient variable was copied or inspected",
    "the outcome was classified `IDENTITY_CONFIRMED`",
    "no current or future session validity is guaranteed",
)

#: What the entry point's own documentation must say about cause, and not say.
#:
#: Correction round 1 fixed the two status documents and deliberately left this
#: file byte-identical, so the superseded sentence survived here -- wrapped
#: across two lines, which is exactly why nothing noticed. Round 2 removes it
#: and pins the replacement, in the file an operator opens before running the
#: one path permitted to construct an SDK client.
#:
#: The wording is the source's own -- double backticks, ``--`` dashes, no
#: markdown -- rather than the documents', because a fixture copied from another
#: surface is a fixture that will be satisfied by editing the wrong file.
BINDING_SOURCE_CAUSE_SCOPE: Final[tuple[str, ...]] = (
    "Output handling was one deliberate correction, and the evidence stops short of a cause.",
    "The first attempt captured stdout and stderr",
    "the corrected attempt used a live console with inherited stdin, stdout and stderr",
    "and it completed successfully",
    "Streaming the interactive surface was a deliberate corrective measure",
    "consistent with the interactive surface contributing to the earlier timeout",
    "the undisplayed buffer was never inspected",
    "capture is not established as the sole, necessary, sufficient or definitive cause",
    "likely, not proven",
    "The two attempts differed in more than output handling",
    "They ran in different Claude sessions",
    "the first copied the whole parent process environment",
    "the corrected one built a minimal allowlisted child environment key-by-key",
    "the point-in-time SSO state may itself have differed",
    "Nothing here claims the two runs were otherwise identical",
    "the second attempt's success does not establish why the first failed",
)

#: The chronology anchor for the corrected attempt, which follows the failed one.
CORRECTED_SSO_ANCHOR: Final = (
    "a corrected, separately authorized AWS SSO-login attempt, in a new Claude session "
    "after PR #30 merged"
)

#: The chronology anchor for the identity confirmation, which follows both.
IDENTITY_CONFIRMATION_ANCHOR: Final = (
    "one conditional identity confirmation, because that login exited `0`"
)

#: What the ADR-0015 current-status row must carry about the corrected events.
ADR_0015_ROW_CORRECTED: Final[tuple[str, ...]] = (
    "CORRECTED SECOND AWS SSO-LOGIN ATTEMPT HAS SINCE COMPLETED SUCCESSFULLY",
    "LIVE CONSOLE WITH INHERITED STDIN, STDOUT AND STDERR",
    "EXIT CODE `0`",
    "SUCCESSFUL GOVERNED SSO REFRESHES ONE",
    "NO WHOLE-ENVIRONMENT COPY",
    "EXACTLY ONE SANITIZED IDENTITY CONFIRMATION RAN",
    "CLASSIFIED `IDENTITY_CONFIRMED`",
    "NO GUARANTEE OF CURRENT OR FUTURE SESSION VALIDITY",
    "VERIFYING NO SECRET IDENTIFIER, SECRET, CREDENTIAL, BUCKET OR PROVIDER ACCESS",
)

#: What both CLAUDE.md status matrices must carry about the corrected events.
#:
#: One tuple for two stanzas on purpose. They are read alone and each is
#: extracted as its own bounded entry, so a clause deleted from one is caught by
#: that stanza's own guard -- while a second, hand-kept list would be a place for
#: the two to drift apart.
MATRIX_CORRECTED_SSO_CLAUSES: Final[tuple[str, ...]] = (
    "CORRECTED SECOND AWS SSO-LOGIN ATTEMPT COMPLETED SUCCESSFULLY -- ONE COMMAND IN A "
    "NEW CLAUDE SESSION",
    "LIVE CONSOLE WITH INHERITED STDIN, STDOUT AND STDERR",
    "NO CAPTURED, PIPED, REDIRECTED, BUFFERED OR FILE OUTPUT",
    "INTERACTIVE BROWSER/DEVICE FLOW COMPLETED, EXIT CODE 0",
    "SUCCESSFUL GOVERNED SSO REFRESHES ONE",
    "MINIMAL ALLOWLISTED CHILD ENVIRONMENT BUILT KEY-BY-KEY, NO WHOLE-ENVIRONMENT COPY",
    "NO CREDENTIAL-BEARING AMBIENT VARIABLE COPIED OR INSPECTED",
    "ONE SANITIZED IDENTITY CONFIRMATION FOLLOWED IT",
    "CLASSIFIED IDENTITY_CONFIRMED, CAPTURED BUFFERS CLEARED AFTER CLASSIFICATION",
    "IDENTITY CONFIRMED AT THE TIME OF THAT COMMAND WITH NO GUARANTEE OF CURRENT OR "
    "FUTURE SESSION VALIDITY",
)

#: What the entry point's own documentation must say about the corrected events.
#:
#: Its docstring sits beside the one authorized SDK-construction path, so an
#: operator reading the file must not have to open a status document to learn
#: that the session was refreshed, that an identity was confirmed once, and that
#: neither moved a single gate.
BINDING_SOURCE_CORRECTED_SSO: Final[tuple[str, ...]] = (
    "corrected SSO-login attempt: COMPLETED SUCCESSFUL",
    "identity confirmation ONE, SUCCESSFUL",
    "A corrected, separately authorized SSO login has since completed, and the governed "
    "session was refreshed.",
    "Run in a new Claude session after PR #30 merged",
    "on a live console with inherited stdin, stdout and stderr",
    "nothing captured, piped, redirected, buffered or written to a file",
    "The interactive browser/device flow completed",
    "the command exited 0",
    "successful governed SSO refreshes became ONE",
    "static AST parse of the ``EXPECTED_PROFILE`` constant below",
    "A minimal, allowlisted child environment was built key-by-key",
    "there was no whole-environment copy",
    "no credential-bearing ambient variable was copied or inspected",
    "only transiently in the live AWS console",
    "not repeated and not persisted",
    "Because that login exited 0, exactly one identity confirmation ran.",
    "structurally contained non-empty UserId, Account and Arn fields",
    "raw response and the private identity values were neither displayed nor persisted",
    "classified IDENTITY_CONFIRMED",
    "captured buffers were cleared after classification",
    "A successful identity confirmation is a historical session fact and nothing more.",
    "no current or future session validity is guaranteed",
    "verified no secret identifier, no secret, no API key, no bucket and no provider access",
    "not a fifth binding-preflight attempt",
    "A completed authorization is not a standing one.",
)

#: What the entry point's own documentation must state about the attempt.
#:
#: Its docstring is a current-status surface sitting beside the one authorized
#: SDK-construction path, so an operator reading the file must not have to open
#: a status document to learn that a login was tried and failed.
BINDING_SOURCE_SSO_LOGIN: Final[tuple[str, ...]] = (
    "post-diagnosis SSO-login attempt: COMPLETED REFUSED_SSO_LOGIN",
    "timed out after 420 seconds, terminated, no exit status returned",
    "zero browser authorizations, zero device authorizations, zero successful refreshes",
    "A separately authorized AWS SSO-login attempt has since been made, and it did not succeed.",
    "it invoked one process and one ``aws sso login --no-cli-pager`` command",
    "static AST parse of the ``EXPECTED_PROFILE`` constant below",
    "this module was neither imported nor executed",
    "pinned in the child environment only, never disclosed",
    "It timed out after 420 seconds, was terminated and left no lingering AWS CLI process, "
    "so no exit status was returned",
    "exit code NOT AVAILABLE / PROCESS TERMINATED ON TIMEOUT*, never a numeric one",
    "the closed public outcome is REFUSED_SSO_LOGIN",
    "identity-confirmation command invocations zero",
    "The SSO session remained unrefreshed",
    "the earlier REFUSED_SSO_SESSION_MISSING_OR_EXPIRED diagnosis stands unrevised",
    "The likely cause is procedural, and it is recorded as likely rather than proven.",
    "likely caused by suppressing the interactive browser/device-code surface",
    "not proof of an AWS configuration defect",
    "was not inspected and remains UNKNOWN",
    "Nothing establishes a defective SSO configuration",
    "a failed login attempt is not permission to retry",
)

#: What the entry point's own documentation must say about the diagnosis.
BINDING_SOURCE_DIAGNOSIS: Final[tuple[str, ...]] = (
    "post-fourth identity diagnosis: COMPLETED",
    "No standalone diagnosis was performed as part of attempt 4",
    "A separately authorized diagnosis has since answered that. It is an additional",
    "standalone command",
    "one process and one ``aws sts get-caller-identity`` command, which exited 255",
    "REFUSED_SSO_SESSION_MISSING_OR_EXPIRED",
    "It does not distinguish missing from expired",
    "At that point SSO-login invocations were zero, authentication-repair actions "
    "were zero and fifth binding-preflight attempts were zero.",
    "because a shell-level pin does not survive across separate tool invocations",
    "That constant already existed in tracked executable source",
    "did not print, log, disclose or newly write the value",
    "Further AWS authentication diagnosis is not authorized",
)

#: The gate's internal path, kept apart from the standalone diagnosis.
#:
#: ``identity_gate()`` in ``scripts/aws_foundation_verify.py`` does run
#: ``sts get-caller-identity`` -- but only after two checks that can refuse
#: before it: an unpinned ``AWS_PROFILE``, and an ``expected_account()`` that
#: returns ``None`` from a git-ignored ``terraform.tfvars``, which is a plain
#: file read. **A gate invocation is therefore not proof of an STS command
#: invocation.** For attempt 4 the profile condition is mechanically proven and
#: the account-binding condition is not, so the STS invocation is UNKNOWN.
#:
#: Two revisions have now been wrong here in opposite directions: one claimed no
#: STS call at all, the next claimed exactly one. Neither is supported, and the
#: documents must be able to say so without being able to state a number.
GATE_VERSUS_DIAGNOSIS: Final[tuple[str, ...]] = (
    "No standalone diagnosis was performed as part of attempt 4",
    "A gate invocation is therefore not proof of an STS command invocation",
    "`identity_gate()` in `scripts/aws_foundation_verify.py` does run `sts get-caller-identity`",
    "One of the two pre-STS conditions is proven for attempt 4, and the other is not",
    "The profile condition holds mechanically",
    "account-binding condition is unproven",
    "bracketing is not evidence of that file's state at attempt 4 itself",
    "So the fourth attempt's STS command invocation is UNKNOWN",
    "neither that diagnosis nor the later successful refresh is retrospective proof",
    "run an *additional* diagnostic command or any SSO inspection",
    "The gate's internal path is not the later standalone diagnosis",
)

#: Claims that attempt 4 issued no STS identity operation at all.
#:
#: Refused because ZERO is a number, and no tracked evidence establishes one:
#: the gate may well have reached its ``sts get-caller-identity`` call, and
#: nothing records which internal branch refused. An earlier revision refused
#: these on the stronger ground that the gate issues an STS call *by
#: construction*; that reasoning was wrong -- the gate has pre-STS refusal
#: paths -- and only the conclusion survives it.
#:
#: The accurate scoped statements are required by :data:`GATE_VERSUS_DIAGNOSIS`
#: and are deliberately not matched here: "no *standalone* diagnosis" stays
#: sayable, and only the unqualified forms are refused.
STALE_GATE_PROBE_CLAIMS: Final[tuple[str, ...]] = (
    "IT MADE NO `STS:GETCALLERIDENTITY` PROBE",
    "IT MADE NO ``STS:GETCALLERIDENTITY`` PROBE",
    "MADE NO STS:GETCALLERIDENTITY PROBE",
    "NO DIAGNOSIS WAS PERFORMED DURING THE ATTEMPT ITSELF",
    "THE IDENTITY GATE MADE NO STS",
    "THE GATE MADE NO STS IDENTITY CALL",
    "NO STS COMMAND OCCURRED DURING ATTEMPT 4",
    "NO STS IDENTITY OPERATION OCCURRED DURING ATTEMPT 4",
    "ATTEMPT 4 ISSUED NO STS",
    "THE FOURTH ATTEMPT MADE NO STS",
    "STS COMMAND INVOCATIONS ON THE FOURTH ATTEMPT: ZERO",
    "STS COMMAND INVOCATIONS ON THE FOURTH ATTEMPT ZERO",
)

#: Numeric STS claims neither attempt supports.
#:
#: ``identity_gate()`` refuses before its ``sts get-caller-identity`` call on two
#: paths, so a gate invocation fixes no STS count in either direction. ONE and
#: ZERO are both refused, for the two attempts separately: the fourth
#: binding-preflight attempt and the first authenticated one are different events
#: under different authorizations, and neither lends the other a number.
#:
#: 16 numeric STS claims are refused here, and that number is checked against
#: ``len()``.
ATTEMPT_STS_COUNT_CLAIMS: Final[tuple[str, ...]] = (
    # -- attempt 4, the fourth binding preflight
    "INVOKED ITS OWN STS IDENTITY OPERATION ONCE",
    "THE GATE RUNS ITS OWN STS IDENTITY OPERATION",
    "STS COMMAND INVOCATIONS ON THE FOURTH ATTEMPT: ONE",
    "STS COMMAND INVOCATIONS ON THE FOURTH ATTEMPT ONE",
    "THE FOURTH ATTEMPT INVOKED STS ONCE",
    "ATTEMPT 4 MADE ONE STS IDENTITY CALL",
    "ATTEMPT 4 REACHED ITS STS CALL",
    "THE FOURTH ATTEMPT REACHED THE STS CALL",
    # -- the first authenticated qualification attempt
    "STS COMMAND INVOCATIONS BY THE GATE ONE",
    "STS COMMAND INVOCATIONS BY THE GATE: ONE",
    "STS COMMAND INVOCATIONS BY THE GATE ZERO",
    "STS COMMAND INVOCATIONS BY THE GATE: ZERO",
    "THE FIRST AUTHENTICATED ATTEMPT INVOKED STS ONCE",
    "THE FIRST AUTHENTICATED ATTEMPT MADE NO STS CALL",
    "THE AUTHENTICATED ATTEMPT REACHED THE STS CALL",
    "THE AUTHENTICATED ATTEMPT MADE ONE STS IDENTITY CALL",
)

#: SSO conclusions drawn from an identity refusal rather than from a diagnosis.
#:
#: A gate that did not pass says nothing about why. The later standalone
#: diagnosis returned one closed word about a session, and it is a separate event
#: under a separate authorization; reading it backwards into either attempt is
#: the inference this list refuses.
#:
#: 10 inferences are refused here, and that number is checked against ``len()``.
ATTEMPT_SSO_INFERENCES: Final[tuple[str, ...]] = (
    "ATTEMPT 4 PROVES THE SSO SESSION WAS MISSING",
    "ATTEMPT 4 PROVES THE SSO SESSION WAS EXPIRED",
    "THE FOURTH ATTEMPT PROVES A MISSING SSO SESSION",
    "THE FOURTH ATTEMPT PROVES AN EXPIRED SSO SESSION",
    "THE FOURTH ATTEMPT REFUSED BECAUSE THE SSO SESSION WAS MISSING",
    "THE FOURTH ATTEMPT REFUSED BECAUSE THE SSO SESSION WAS EXPIRED",
    "THE FIRST AUTHENTICATED ATTEMPT PROVES THE SSO SESSION WAS MISSING",
    "THE FIRST AUTHENTICATED ATTEMPT PROVES THE SSO SESSION WAS EXPIRED",
    "THE IDENTITY REFUSAL PROVES A MISSING SSO SESSION",
    "THE IDENTITY REFUSAL PROVES AN EXPIRED SSO SESSION",
)

#: Denials of the one invocation that did happen, and the completion that did not.
#:
#: The pair is the point. *The bounded acquisition never completed* is true and
#: *the entry point was never invoked* is false, and a summary that reaches for
#: the first to imply the second is the drift this refuses.
#:
#: 9 denials are refused here, and that number is checked against ``len()``.
ATTEMPT_INVOCATION_DENIALS: Final[tuple[str, ...]] = (
    "THE ENTRY POINT WAS NEVER INVOKED",
    "THE ENTRY POINT HAS NEVER BEEN INVOKED",
    "THE FUNCTION HAS NEVER BEEN RUN",
    "THE FUNCTION WAS NEVER RUN",
    "AUTHENTICATED ATTEMPTS: ZERO",
    "AUTHENTICATED ATTEMPTS ZERO",
    "THE BOUNDED ACQUISITION COMPLETED",
    "THE BOUNDED ACQUISITION HAS COMPLETED",
    "A SECOND AUTHENTICATED ATTEMPT IS AUTHORIZED",
)

#: The first attempt's facts, required in each status document independently.
FIRST_ATTEMPT_REQUIRED_FACTS: Final[tuple[tuple[str, str], ...]] = (
    ("records that exactly one process was invoked", "exactly one entry-point process was invoked"),
    ("records that the attempt refused", "was invoked once and refused"),
    (
        "records that attempt two reached the runtime and made one request",
        "The qualification runtime was reached, and one provider request was made.",
    ),
    (
        "bounds attempt two's PutObject invocations exactly",
        "PutObject invocations EXACTLY THREE",
    ),
    (
        "bounds attempt two's conditional HeadObject invocations",
        "conditional HeadObject invocations ZERO TO THREE",
    ),
    (
        "bounds attempt two's total S3 qualification operations",
        "S3 qualification operations THREE TO SIX",
    ),
    (
        "records that attempt two's publication state is not unknown",
        "publication state unknown NO",
    ),
    (
        "records that a complete retained acquisition record exists",
        "complete acquisition record EXISTS",
    ),
    (
        "keeps the newly-written object count unestablished",
        "newly written objects NOT ESTABLISHED",
    ),
    (
        "keeps the already-present object count unestablished",
        "already-present identical objects NOT ESTABLISHED",
    ),
    (
        "records exact-request authentication as established",
        "exact-request authentication ESTABLISHED",
    ),
    (
        "keeps provider-wide authentication unknown",
        "provider-wide authentication UNKNOWN",
    ),
    (
        "refuses to read a completed command as a verdict",
        "`COMPLETED` is a command status, not a verdict.",
    ),
)

#: The attempt-4 facts the binding preflight's own documentation must carry.
#:
#: Correction round 1 fixed both status documents and then *dropped* this
#: requirement rather than replacing it, because the source file was outside that
#: authorization's scope. Dropping a guard leaves the claim unguarded, so the
#: requirement is restored here against the corrected wording -- and against the
#: file's own documentation surface, not its executable strings.
BINDING_SOURCE_ATTEMPT4_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    (
        "records one identity-gate invocation that did not pass",
        "identity-gate invocations are ONE, which did not pass",
    ),
    ("leaves the STS command invocation unknown", "its STS command invocation is UNKNOWN"),
    (
        "leaves the underlying network interactions unknown",
        "underlying AWS network interactions are UNKNOWN",
    ),
    (
        "keeps the network total unknown in its own sentence",
        "Whether the fourth attempt sent an AWS network request is UNKNOWN",
    ),
    (
        "states that a gate invocation is not proof of an STS call",
        "A gate invocation is therefore not proof of an STS command invocation",
    ),
    (
        "separates the proven pre-STS condition from the unproven one",
        "One of the two pre-STS conditions is proven for attempt 4, and the other is not",
    ),
    ("names the mechanically proven condition", "The profile condition holds mechanically"),
    ("names the unproven condition", "account-binding condition is unproven"),
    ("keeps the outcome unchanged", "Its outcome is unchanged: REFUSED_IDENTITY"),
    (
        "keeps the gate apart from the standalone diagnosis",
        "The gate's internal path is not the later standalone diagnosis",
    ),
    (
        "infers no SSO conclusion from attempt 4",
        "no missing or expired SSO session may be inferred from attempt 4",
    ),
)

#: Attempt-4 conclusions the binding preflight's documentation may not state.
#:
#: Both directions, because both are numbers: the gate refuses before its own
#: ``sts get-caller-identity`` call on two paths, so ONE is unsupported and so is
#: ZERO. The SSO entries refuse reading the later standalone diagnosis backwards
#: into the attempt, and the conflation entries refuse merging the two events.
#:
#: 25 attempt-4 STS and SSO claims are refused here, and the number in that
#: sentence is checked against ``len()`` so an entry cannot leave quietly.
BINDING_SOURCE_ATTEMPT4_FORBIDDEN: Final[tuple[str, ...]] = (
    # -- STS definitely ran
    "IDENTITY GATE INVOKED ITS OWN STS IDENTITY OPERATION ONCE",
    "INVOKED ITS OWN STS IDENTITY OPERATION ONCE",
    "IT IS FALSE TO SAY THE ATTEMPT MADE NO STS IDENTITY CALL",
    "THE GATE RUNS ITS OWN STS IDENTITY OPERATION",
    "RUNS ``STS GET-CALLER-IDENTITY`` ITSELF",
    "THE ATTEMPT DID MAKE AN STS IDENTITY CALL",
    "ATTEMPT 4 MADE ONE STS IDENTITY CALL",
    "THE GATE'S OWN STS OPERATION ABOVE",
    "STS COMMAND INVOCATION IS ONE",
    "STS COMMAND INVOCATIONS ON THE FOURTH ATTEMPT: ONE",
    # -- STS definitely did not run
    "STS COMMAND INVOCATIONS ON THE FOURTH ATTEMPT: ZERO",
    "THE ATTEMPT MADE NO STS IDENTITY CALL",
    "THE GATE MADE NO STS IDENTITY CALL",
    "ATTEMPT 4 ISSUED NO STS",
    "THE FOURTH ATTEMPT MADE NO STS",
    # -- a number for the network total
    "AWS NETWORK REQUESTS ON THE FOURTH ATTEMPT: ZERO",
    "AWS NETWORK REQUESTS ON THE FOURTH ATTEMPT: ONE",
    "THE FOURTH ATTEMPT SENT ONE AWS NETWORK REQUEST",
    "THE FOURTH ATTEMPT SENT NO AWS NETWORK REQUEST",
    # -- an SSO conclusion drawn from the refusal
    "ATTEMPT 4 PROVES THE SSO SESSION WAS MISSING",
    "ATTEMPT 4 PROVES THE SSO SESSION WAS EXPIRED",
    "THE FOURTH ATTEMPT REFUSED BECAUSE THE SSO SESSION WAS MISSING",
    "THE FOURTH ATTEMPT REFUSED BECAUSE THE SSO SESSION WAS EXPIRED",
    # -- the gate merged with the standalone diagnosis
    "THE IDENTITY GATE WAS THE DIAGNOSIS",
    "THE GATE OPERATION IS THE STANDALONE DIAGNOSIS",
)

#: Each refused phrase paired with the denylist that must still contain it.
#:
#: The companion guard used to ask whether these strings occurred *anywhere* in
#: this file. Each occurs twice -- once in the real denylist, once in the check's
#: own literal tuple -- so deleting the enforcing entry left the guard green on
#: the strength of its own copy. Occurrence proved nothing; **membership** does.
#:
#: Pairing the expectation with its intended tuple also catches a subtler edit:
#: moving a phrase into some other denylist while removing it from the one whose
#: guard actually reaches the surface it protects.
#:
#: This does **not** make guard-weakening behaviourally detectable in general.
#: Deleting an expectation *and* its enforcement together still passes, because
#: nothing is left to disagree with; that remains a targeted source assertion's
#: job, and is reported as such rather than dressed up as a behavioural catch.
REQUIRED_FIXTURE_MEMBERSHIP: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("UNKNOWN -- NO DIAGNOSIS WAS PERFORMED", STALE_NO_DIAGNOSIS_CLAIMS),
    ("NO DIAGNOSIS WAS PERFORMED DURING THE ATTEMPT ITSELF", STALE_GATE_PROBE_CLAIMS),
    ("SSO-LOGIN INVOCATIONS ZERO", STALE_SSO_LOGIN_CLAIMS),
    ("THE GOVERNED PROFILE IS INCORRECT", SSO_LOGIN_OVERCLAIMS),
    ("NO CREDENTIAL VALUE WAS READ", SSO_LOGIN_ENVIRONMENT_OVERCLAIMS),
    ("SUCCESSFUL SSO REFRESHES: ZERO", STALE_CORRECTED_SSO_CLAIMS),
    ("THE SESSION WILL REMAIN VALID", CORRECTED_SSO_OVERCLAIMS),
    ("THE FIRST SSO LOGIN SUCCEEDED", SSO_LOGIN_OVERCLAIMS),
    ("THE ONE THING THE FIRST ATTEMPT GOT WRONG", SSO_CAUSE_OVERCLAIMS),
    ("ALL OTHER EXECUTION CONDITIONS WERE IDENTICAL", SSO_CAUSE_OVERCLAIMS),
    ("THE SINGLE DIFFERENCE", SSO_CAUSE_OVERCLAIMS),
    ("THE WHOLE OPERATIONAL FINDING", SSO_CAUSE_OVERCLAIMS),
    ("INVOKED ITS OWN STS IDENTITY OPERATION ONCE", ATTEMPT_STS_COUNT_CLAIMS),
    ("STS COMMAND INVOCATIONS BY THE GATE ONE", ATTEMPT_STS_COUNT_CLAIMS),
    ("STS COMMAND INVOCATIONS BY THE GATE ZERO", ATTEMPT_STS_COUNT_CLAIMS),
    ("ATTEMPT 4 PROVES THE SSO SESSION WAS EXPIRED", ATTEMPT_SSO_INFERENCES),
    ("THE ENTRY POINT WAS NEVER INVOKED", ATTEMPT_INVOCATION_DENIALS),
    ("THE BOUNDED ACQUISITION COMPLETED", ATTEMPT_INVOCATION_DENIALS),
    ("A SECOND AUTHENTICATED ATTEMPT IS AUTHORIZED", ATTEMPT_INVOCATION_DENIALS),
    ("INVOKED ITS OWN STS IDENTITY OPERATION ONCE", BINDING_SOURCE_ATTEMPT4_FORBIDDEN),
    (
        "STS COMMAND INVOCATIONS ON THE FOURTH ATTEMPT: ZERO",
        BINDING_SOURCE_ATTEMPT4_FORBIDDEN,
    ),
    ("ATTEMPT 4 PROVES THE SSO SESSION WAS EXPIRED", BINDING_SOURCE_ATTEMPT4_FORBIDDEN),
)

#: Wording that merges the gate's operation with the standalone diagnosis, or
#: that adds them into a number.
#:
#: They are two operations with two scopes and no shared count. A total would be
#: a numeric claim about AWS traffic that neither event establishes.
GATE_DIAGNOSIS_CONFLATIONS: Final[tuple[str, ...]] = (
    "THE IDENTITY GATE WAS THE DIAGNOSIS",
    "THE GATE'S STS CALL WAS THE DIAGNOSIS",
    "THE GATE OPERATION IS THE STANDALONE DIAGNOSIS",
    "TWO STANDALONE DIAGNOSES OCCURRED AFTER THE FOURTH",
    "TWO STANDALONE POST-FOURTH DIAGNOSES",
    "TOTAL AWS NETWORK REQUESTS: TWO",
    "TOTAL AWS NETWORK REQUESTS: ONE",
    "COMBINED AWS NETWORK REQUESTS",
    "TWO AWS NETWORK REQUESTS IN TOTAL",
    "AWS NETWORK REQUESTS ON THE FOURTH ATTEMPT: ONE",
    "AWS NETWORK REQUESTS ON THE FOURTH ATTEMPT: ZERO",
)

#: The superseded unqualified profile-disclosure sentence.
#:
#: ``EXPECTED_PROFILE`` already existed in tracked executable source before the
#: diagnosis ran, so "never written down" was false about the repository. What the
#: diagnosis did -- and did not -- do is the narrower supportable claim.
STALE_PROFILE_DISCLOSURE_CLAIMS: Final[tuple[str, ...]] = (
    "THE VALUE WAS NEVER PRINTED OR WRITTEN DOWN",
    "THE VALUE WAS NEVER WRITTEN DOWN",
    "THE VALUE HAS NEVER BEEN WRITTEN DOWN",
    "THE PROFILE VALUE APPEARS NOWHERE",
    "THE PROFILE VALUE EXISTS NOWHERE IN TRACKED SOURCE",
    "NOT PRINTED, LOGGED OR WRITTEN INTO ANY DOCUMENT",
    "THE DIAGNOSIS WROTE THE PROFILE VALUE",
    "THE DIAGNOSIS NEWLY WROTE THE VALUE",
)

#: What must stay unauthorized now that a fourth attempt has happened.
SIXTH_ATTEMPT_BOUNDARIES: Final[tuple[str, ...]] = (
    "sixth binding-preflight attempt: NOT AUTHORIZED",
    "further AWS authentication diagnosis: NOT AUTHORIZED",
    "another AWS SSO-login/refresh attempt: SEPARATELY GATED / NOT AUTHORIZED",
    "additional credential or Secrets Manager access: NOT AUTHORIZED",
    "a third authenticated qualification attempt: NOT AUTHORIZED",
)

#: What the entry point's own documentation must state about the fourth attempt.
BINDING_SOURCE_FOURTH: Final[tuple[str, ...]] = (
    "invoked five times under separate authorization",
    "the fourth refused at the AWS identity gate, reaching neither",
    "fourth attempt REFUSED_IDENTITY at the AWS identity gate",
    "fourth-attempt identity-gate invocations: ONE -- the gate runs its own STS",
    "fourth-attempt standalone diagnostic commands: ZERO",
    "fourth-attempt AWS network requests: UNKNOWN -- no numeric count established",
    "the first four refused and the fifth completed",
    "Whether the fourth attempt sent an AWS network request is UNKNOWN.",
    "neither zero nor one may be claimed here",
    "the fourth refused at the identity gate, two stages before the identifier source",
    "a sixth binding preflight",
)

#: What ``main``'s docstring must say about which attempts reached construction.
#:
#: It described **two** attempts long after four had run, and named the wrong
#: reason for the fourth by omission. A docstring beside the one authorized SDK
#: construction is the worst place in the file to carry a stale count.
BINDING_SOURCE_MAIN_HISTORY: Final[tuple[str, ...]] = (
    "Five separately authorized attempts have run this",
    "The first four never reached this construction",
    "the first and the fourth",
    "refused at the AWS identity gate, the second refused on the missing AWS SDK,",
    "and the third refused at the secret-identifier source",
    "The fifth reached all of it",
    "one offline composition preflight that returned ``VALIDATED_OFFLINE`` with exit code ``0``",
    "a sixth attempt is not authorized",
)

#: What the real-factory commentary must say about which factories have run.
#:
#: Per factory, because the answer differs per factory: two ran on every attempt,
#: one ran on two of them, one ran once, and three have never run at all. The
#: superseded comment said "the two separately authorized attempts" and put
#: ``_environment_secret_id`` among the factories that had not run -- which the
#: third attempt had already made false before the fourth was authorized.
BINDING_SOURCE_FACTORY_HISTORY: Final[tuple[str, ...]] = (
    "`_ambient_profile` and `_governed_identity_gate` HAVE run, on all five",
    "`_governed_licensed_bucket` ran on the second, third and fifth attempts,",
    "`_environment_secret_id` ran twice: on the",
    "third attempt, which refused there, and on the fifth, which resolved it and",
    "`_secrets_client`, `_s3_client` and `_transport` were never constructed by",
    "the first four attempts",
    "constructed exactly once by the fifth",
    "No provider request, no S3 object",
    "operation and no qualification execution has occurred",
    "Diagnosis is no longer entirely future:",
    "governed SSO session or cached token as missing or expired, without",
    "other operational event remain separately",
)


#: The heading of the operational-environment section in both status documents.
ENVIRONMENT_SECTION_HEADING: Final = (
    "### The operational environment — synchronized and verified, and not reproducibly locked"
)

#: The environment fingerprint both documents must record.
#:
#: Exact versions, because "the SDK is present" is the claim that went stale in the
#: other direction: a status document that names no version cannot be checked
#: against the machine it describes.
ENVIRONMENT_FINGERPRINT: Final[tuple[str, ...]] = (
    "operational .venv                     EXISTS AND USABLE",
    "interpreter                           Python 3.11.9",
    "boto3                                 1.43.83",
    "botocore                              1.43.83",
    "pip check                             no broken requirements",
    "boto3.client                          EXISTS AND CALLABLE -- not invoked during verification",
    "Python dependency lock                ABSENT",
    "conformance                           RANGE-CONFORMANT, NOT LOCK-CONFORMANT",
    # The bounded attempt this fingerprint was validated for has been run.
    # "TECHNICALLY READY FOR SEPARATE AUTHORIZATION" described a machine waiting
    # for a decision that has since been taken and consumed.
    "one future bounded attempt            AUTHORIZED, RUN AND COMPLETED -- the fifth attempt",
)

#: The four events the chronology must keep distinct.
#:
#: Collapsing them is how a status document starts asserting that a review
#: performed an installation it deliberately did not perform, or that no
#: installation ever happened.
ENVIRONMENT_CHRONOLOGY: Final[tuple[str, ...]] = (
    "the second authorized binding-preflight attempt refused because this environment lacked "
    "the AWS SDK",
    "an earlier, separately authorized environment action",
    "installed the AWS SDK using the range already declared",
    "the latest environment-synchronization review",
    "installed nothing.",
    "no Python dependency lock, so that path was not executable",
    "made no change",
)

#: The dependency-lock limitation, which recording does not resolve.
ENVIRONMENT_LOCK_LIMITATION: Final[tuple[str, ...]] = (
    "No Python dependency lock currently exists.",
    "range-conformant, not lock-conformant",
    "could resolve different, still-compatible package versions",
    "DEFERRED to a separately reviewed dependency-governance slice",
    # The provisional acceptance was granted for one bounded diagnostic. That one
    # ran, so the required wording is that it is spent rather than available.
    "the provisional acceptance is spent",
    "not approval for production qualification, ingestion, CONTROL publication or live operation",
    "it is not approval for a sixth attempt",
)

#: The boundaries the environment section must restate rather than relax.
ENVIRONMENT_BOUNDARIES: Final[tuple[str, ...]] = (
    "binding-preflight entry point         SOLE PERMITTED SDK/CLIENT-CONSTRUCTION BOUNDARY",
    "licensed-bucket resolutions: ONE",
    "S3 client constructions: ONE",
    "S3 object operations: ZERO",
    '"real bucket binding": UNDEFINED IN THIS REPOSITORY -- STATED AS THE THREE FACTS ABOVE',
    "operational secret-identifier configuration: OWNER-CONFIGURED, AND RESOLVED ONCE "
    "BY THE ENTRY POINT",
    "authorized binding-preflight attempts to date: FIVE -- the first four refused, "
    "the fifth completed",
    "fifth attempt: COMPLETED + VALIDATION_COMPLETED -- exit code 0, stage 10, VALIDATED_OFFLINE",
    "authorized AWS SSO-login attempts to date: TWO -- the first refused, the second succeeded",
    "first AWS SSO-login attempt: REFUSED_SSO_LOGIN, timed out at 420s",
    "corrected AWS SSO-login attempt: SUCCESSFUL -- live console, exit code 0",
    "successful governed SSO refreshes: ONE",
    "sanitized identity confirmations after it: ONE, SUCCESSFUL",
    "identity status: CONFIRMED AT THE TIME OF THAT COMMAND -- "
    "future session validity NOT GUARANTEED",
    "identity-confirmation underlying AWS network requests: UNKNOWN",
    "Secrets Manager client constructions: ONE",
    "get_secret_value invocations: ONE",
    "Secrets Manager underlying network requests: UNKNOWN",
    "Sharadar/provider requests: ZERO",
    "credential retrieved: ONE",
    "credential status: STRUCTURALLY ACCEPTED",
    "Sharadar authentication: UNKNOWN",
    "qualification runs: ZERO",
    "AWS credential-provider chain invoked during environment verification: NONE",
    "AWS requests during environment verification: ZERO",
    "binding preflight or composition preflight run during environment verification: NEITHER",
    "composition preflight run: ONCE -- by the fifth binding-preflight attempt, offline",
    "a sixth binding-preflight attempt: NOT AUTHORIZED",
    "further AWS authentication diagnosis: NOT AUTHORIZED",
    "another AWS SSO-login/refresh attempt: SEPARATELY GATED / NOT AUTHORIZED",
    "additional credential or Secrets Manager access: NOT AUTHORIZED",
    "a third authenticated qualification attempt: NOT AUTHORIZED",
    "Sharadar/provider access: NOT AUTHORIZED",
    "S3 object operations or publication: NOT AUTHORIZED",
    "ingestion, backfill and update: NOT AUTHORIZED",
    "CONTROL publication: DEFERRED / NOT AUTHORIZED",
    "broker, LEAN, Paper and live trading: NOT AUTHORIZED -- live trading HARD-DISABLED",
    "further dependency installation or environment resynchronization: SEPARATELY GATED",
)

#: The environment-history prohibitions ADR-0016's forbidden-claims list gave up.
#:
#: Listed rather than counted in prose, so the number in that list's comment is
#: derived from something checkable. The comment previously said "five" and
#: enumerated six.
#: Prohibitions the fifth binding-preflight attempt made true, and which are
#: therefore retired rather than kept.
#:
#: The same rule the environment-repair entries were retired under: a guard that
#: forbids a true statement is answered by writing a vaguer one, which is worse
#: than the guard is good. Each of these named something that had not happened
#: and now has -- once, offline, under a separate authorization. What replaces
#: them in `SURVIVING_PROHIBITIONS` is the set of claims the fifth attempt still
#: does not support: a provider request, an S3 object operation, a credential
#: proven against Sharadar, and a sixth attempt.
RETIRED_PREFLIGHT_PROHIBITIONS: Final[tuple[str, ...]] = (
    "THE BINDING PREFLIGHT COMPLETED",
    "THE BINDING PREFLIGHT SUCCEEDED",
    "A CREDENTIAL WAS RETRIEVED",
    "THE CREDENTIAL WAS RETRIEVED",
    "GETSECRETVALUE WAS ISSUED",
    "GETSECRETVALUE SUCCEEDED",
    "A SECRET WAS READ",
)

RETIRED_ENVIRONMENT_PROHIBITIONS: Final[tuple[str, ...]] = (
    "THE ENVIRONMENT WAS REPAIRED",
    "THE ENVIRONMENT HAS BEEN REPAIRED",
    "BOTO3 WAS INSTALLED",
    "BOTO3 HAS BEEN INSTALLED",
    "THE SDK WAS INSTALLED",
    "THE DEPENDENCY WAS INSTALLED",
)

#: Number words this audit may write about itself. Small on purpose: the point is
#: to derive the word from a length, not to build a spelling library.
COUNT_WORDS: Final[dict[int, str]] = {4: "Four", 5: "Five", 6: "Six", 7: "Seven"}

#: The prohibitions that survived, and must keep surviving.
#: 6 prohibitions survive here, and the self-guard below derives that number
#: from this tuple. Retiring an entry from `ADR_0016_FORBIDDEN_CLAIMS` *and*
#: from this list would otherwise leave no symptom at all.
SURVIVING_PROHIBITIONS: Final[tuple[str, ...]] = (
    "AUTHENTICATED QUALIFICATION IS AUTHORIZED",
    "AUTHENTICATED QUALIFICATION IS NOW AUTHORIZED",
    "A SHARADAR REQUEST WAS MADE",
    "AN S3 OBJECT OPERATION WAS PERFORMED",
    "SHARADAR AUTHENTICATION CONFIRMED",
    "A SIXTH BINDING-PREFLIGHT ATTEMPT IS AUTHORIZED",
)


#: What a usable environment must never be read as granting.
#:
#: "Technically ready" is a fact about a machine. Every entry here is a fact
#: about a decision, and none of those decisions has been taken.
ENVIRONMENT_FORBIDDEN_CLAIMS: Final[tuple[str, ...]] = (
    "BINDING PREFLIGHT AUTHORIZED",
    "BINDING PREFLIGHT IS AUTHORIZED",
    "CREDENTIAL ACCESS AUTHORIZED",
    "CREDENTIAL ACCESS IS AUTHORIZED",
    "QUALIFICATION IS AUTHORIZED",
    "ENVIRONMENT REPRODUCIBLY LOCKED",
    "REPRODUCIBLY LOCKED ENVIRONMENT",
    "LOCK-CONFORMANT ENVIRONMENT",
    "A PYTHON DEPENDENCY LOCK EXISTS",
    "DEPENDENCY LOCK INTRODUCED",
    "OPERATIONAL SECRET IDENTIFIER CONFIGURED",
    "SECRET-IDENTIFIER CONFIGURATION: CONFIGURED",
    "PRODUCTION READY",
    "PHASE 3 COMPLETE",
)

#: Environment claims two separately authorized events made false.
#:
#: Each was accurate before the SDK was installed. None is now, and each is the
#: affirmative absence form -- a document must still be able to say the *lock* is
#: absent, which is a different absence and remains true.
STALE_ENVIRONMENT_CLAIMS: Final[tuple[str, ...]] = (
    "OPERATIONAL ENVIRONMENT SYNCHRONIZED: NOT DONE",
    "OPERATIONAL ENVIRONMENT SYNCHRONIZATION NOT AUTHORIZED",
    "THE ABSENT SDK STAYS ABSENT",
    "BOTO3 REMAINS ABSENT",
    "THE AWS SDK IS ABSENT",
    "THE AWS SDK REMAINS ABSENT",
    "NO DEPENDENCY WAS EVER INSTALLED",
    "ENVIRONMENT SYNCHRONIZATION HAS NEVER OCCURRED",
    "THE OPERATIONAL ENVIRONMENT DOES NOT EXIST",
    "BLOCKED BY LOCAL SDK ABSENCE",
    "SDK CONSTRUCTION IS IMPOSSIBLE",
)

#: The CLAUDE.md matrix stanza recording the environment.
ENVIRONMENT_MATRIX_LINE: Final = "ENVIRONMENT    operational .venv and AWS SDK PRESENT / VERIFIED"

#: The continuation indent of that stanza.
#:
#: A top-level stanza header sits at column zero and its continuations at
#: fifteen, where an ADR entry *inside* a stanza sits at fifteen and continues at
#: twenty-four. Passing the wrong one silently truncates the stanza to its header
#: line, which is exactly how the first revision of the guard below came to
#: search the whole document instead.
ENVIRONMENT_MATRIX_INDENT: Final = 15

#: What that stanza must state.
ENVIRONMENT_MATRIX_CLAUSES: Final[tuple[str, ...]] = (
    "Python 3.11.9",
    "boto3 1.43.83, botocore 1.43.83, pip check clean",
    "PYTHON DEPENDENCY LOCK ABSENT",
    "RANGE-CONFORMANT, NOT REPRODUCIBLY LOCKED",
    "the one future bounded attempt AUTHORIZED, RUN AND COMPLETED -- THE FIFTH",
    "FIVE AUTHORIZED ATTEMPTS TO DATE -- THE FIRST FOUR REFUSED, THE FIFTH COMPLETED",
    "FOURTH ATTEMPT REFUSED_IDENTITY AT THE AWS IDENTITY GATE",
    "FOURTH-ATTEMPT IDENTITY-GATE INVOCATIONS ONE -- IT DID NOT PASS; ITS OWN STS "
    "COMMAND INVOCATION UNKNOWN, BECAUSE REAL PRE-STS REFUSAL PATHS EXIST; STANDALONE "
    "DIAGNOSTIC COMMANDS ZERO; AWS NETWORK REQUESTS UNKNOWN",
    # Three clauses rather than one long one: the stanza is joined before it is
    # searched, so each is independently required and each fails on its own.
    "POST-FOURTH AWS IDENTITY DIAGNOSIS COMPLETED -- REFUSED_SSO_SESSION_MISSING_OR_EXPIRED",
    "ONE COMMAND, EXIT CODE 255",
    "ITS OWN NETWORK COUNT UNKNOWN, ZERO SSO LOGINS DURING IT, ZERO REPAIR ACTIONS DURING IT",
    "POST-DIAGNOSIS AWS SSO-LOGIN ATTEMPT COMPLETED -- REFUSED_SSO_LOGIN",
    "ONE COMMAND, TIMED OUT AFTER 420 SECONDS, NO EXIT STATUS RETURNED",
    "ZERO BROWSER AUTHORIZATIONS, ZERO DEVICE AUTHORIZATIONS, ZERO SUCCESSFUL "
    "REFRESHES, ZERO IDENTITY CONFIRMATIONS",
    "SSO SESSION STILL UNREFRESHED AFTER IT, EARLIER DIAGNOSIS UNREVISED",
    # The fifth attempt, stated in the stanza a reader consults on its own.
    "FIFTH BINDING-PREFLIGHT ATTEMPT COMPLETED -- ONE PROCESS INVOCATION, EXIT CODE 0, "
    "CLOSED OUTCOME COMPLETED + VALIDATION_COMPLETED, LAST STAGE DEFINITIVELY REACHED "
    "STAGE 10, COMPOSITION STATUS VALIDATED_OFFLINE",
    "FIFTH-ATTEMPT COUNTS -- IDENTITY-GATE INVOCATIONS ONE AND PASSED, LICENSED-BUCKET "
    "RESOLUTIONS ONE, SECRET-IDENTIFIER RESOLUTIONS ONE, SECRETS MANAGER CLIENT "
    "CONSTRUCTIONS ONE, GET_SECRET_VALUE INVOCATIONS ONE AND ADMITTED, S3 CLIENT "
    "CONSTRUCTIONS ONE, S3 OBJECT OPERATIONS ZERO, PROVIDER TRANSPORT CONSTRUCTIONS ONE, "
    "SHARADAR/PROVIDER REQUESTS ZERO, OFFLINE COMPOSITION-PREFLIGHT INVOCATIONS ONE, "
    "QUALIFICATION EXECUTIONS ZERO, UNDERLYING AWS NETWORK REQUESTS UNKNOWN",
    "ONE CREDENTIAL RETRIEVED AND STRUCTURALLY ACCEPTED -- NEVER DISPLAYED, LOGGED, "
    "PERSISTED, HASHED, FINGERPRINTED, MEASURED OR SUMMARIZED; SHARADAR AUTHENTICATION "
    "UNKNOWN, NO PROVIDER REQUEST MADE",
    "SECRET IDENTIFIER OWNER-CONFIGURED, NOT READ BY THE FOURTH ATTEMPT, AND RESOLVED "
    "ONCE BY THE ENTRY POINT ON THE FIFTH",
    "a sixth attempt NOT AUTHORIZED",
    "further AWS authentication diagnosis NOT AUTHORIZED",
    "ANOTHER AWS SSO-LOGIN/REFRESH ATTEMPT SEPARATELY GATED AND NOT AUTHORIZED",
    "additional credential or Secrets Manager access NOT AUTHORIZED",
    "a third authenticated qualification attempt NOT AUTHORIZED",
    "Sharadar/provider access NOT AUTHORIZED",
    "S3 object operations or publication NOT AUTHORIZED",
    "ingestion, backfill and update NOT AUTHORIZED",
    "CONTROL publication DEFERRED / NOT AUTHORIZED",
    "broker, LEAN, Paper and live trading NOT AUTHORIZED -- live trading HARD-DISABLED",
    "SDK/client construction outside the ADR-0015 operator boundary NOT AUTHORIZED",
)


#: The first line of the CLAUDE.md IN FORCE matrix entry recording ADR-0016.
ADR_0016_MATRIX_LINE: Final = "ADR-0016 corrected private-binding failure boundaries -- ACCEPTED /"

#: What that matrix entry must state, once its continuation lines are joined.
ADR_0016_MATRIX_CLAUSES: Final[tuple[str, ...]] = (
    "IN FORCE -- PR #24 MERGED",
    "CODE AND FAILURE-BOUNDARY CORRECTION ONLY",
    "SECRET-IDENTIFIER / LOCAL-DEPENDENCY / CREDENTIAL REFUSALS SEPARATED",
    "FURTHER ENVIRONMENT RESYNCHRONIZATION SEPARATELY GATED",
    "A SIXTH BINDING-PREFLIGHT ATTEMPT NOT AUTHORIZED",
    "FIRST EXERCISED PAST THE IDENTIFIER STAGE BY THE FIFTH ATTEMPT",
    "WHICH RETRIEVED ONE STRUCTURALLY ACCEPTED CREDENTIAL AND RAN NO QUALIFICATION",
)


#: Wording that states a status which has not been reached yet.
#:
#: Legitimate in an ADR's own immutable status line and in historical prose --
#: neither of which is a current-status table row -- and never legitimate in one.
PRE_MERGE_STATUS_WORDING: Final[tuple[str, ...]] = (
    "ACCEPTED EFFECTIVE ON MERGE",
    "carries no authority before it",
    "ACCEPTED ON MERGE",
    "EFFECTIVE ON THE MERGE",
)


#: The invocation-count rows a current-status document must carry.
#:
#: ADR-0016's correction *is* these counts. A document that describes the
#: outcomes without them has described several names for one behaviour.
#:
#: The third column counts calls into the injected client's ``get_secret_value``
#: method -- which is what a counter can see. It is deliberately **not** headed
#: "requests": see :data:`ADR_0016_INVOCATION_CONFLATIONS`.
ADR_0016_COUNT_ROWS: Final[tuple[str, ...]] = (
    "authorization / profile / identity / bucket            0        0             0",
    "secrets-boundary import refusal                        0        0             0",
    "REFUSED_SECRET_IDENTIFIER                              1        0             0",
    "REFUSED_DEPENDENCY at client construction              1        1             0",
    "REFUSED_CREDENTIAL                                     1        1             1",
    "REFUSED_DEPENDENCY after the credential                1        1             1",
    "completed synthetic offline preflight                  1        1             1",
)

#: The sentence a current-status document must carry to keep the two claims
#: apart.
#:
#: A ``botocore`` client validates parameters locally and can reject a call after
#: the method is entered and before anything leaves the machine. The synthetic
#: counter therefore establishes an invocation and nothing about the network.
ADR_0016_INVOCATION_SENTENCE: Final = "A method invocation is not a proven AWS network request."

#: The exact ADR sentence that kept the credential default, refused outright.
#:
#: Correction round 1 removed the default; round 2 found the ADR still listing it
#: as *kept*, in the present tense, in the section a reader consults to learn what
#: was decided. A decision document contradicting the code it governs is worse
#: than one that is merely incomplete.
ADR_0016_KEPT_DEFAULT_SENTENCE: Final = (
    "**Make `REFUSED_CREDENTIAL` the default for anything unmapped.** Kept"
)

#: Wording that reads a method counter as proof that AWS was contacted.
#:
#: Every entry is the **affirmative** form, like the other two refusal lists
#: here: a document has to be able to say "AWS network requests from this path:
#: ZERO", which is established by no client ever having existed, while being
#: unable to say the counter proved a request.
ADR_0016_INVOCATION_CONFLATIONS: Final[tuple[str, ...]] = (
    "GETSECRETVALUE REQUESTS ISSUED",
    "WITNESSED AWS REQUEST",
    "WITNESSED AWS NETWORK REQUEST",
    "WITNESSED REQUEST COUNT",
    "REQUEST COUNTS ARE WITNESSED",
    "PROVEN AWS REQUEST",
    "PROVES AN AWS REQUEST",
    "PROVES THAT AWS RECEIVED",
    "THE COUNTER PROVES A REQUEST",
    "COUNTED AWS REQUESTS",
    "EXACTLY ONE AWS REQUEST",
    # Round 2. An operator cannot be told a refusal reveals this: the counter
    # sees a method call, and a client can reject parameters locally after the
    # method is entered.
    "WHETHER AWS WAS ASKED FOR ANYTHING",
    "AN INVOCATION PROVES AWS",
    "INVOCATION PROVES THAT AWS",
)

#: The boundary failure tokens the entry point maps to a credential refusal.
#:
#: Named here so a guard about what the *error constructor* may normalise into can
#: be written against the set that matters, rather than against every member.
CREDENTIAL_MAPPED_FAILURES: Final[tuple[str, ...]] = (
    "BACKEND_REFUSED",
    "RESPONSE_MALFORMED",
    "SECRET_BINARY_REFUSED",
    "SECRET_VALUE_UNUSABLE",
)

#: Blanket claims that one outcome fixes a count it does not fix.
#:
#: ``REFUSED_DEPENDENCY`` occurs both before a client exists (zero invocations)
#: and after a successful retrieval (one). A document that reads it as "nothing
#: was invoked" is wrong half the time, and wrong in the direction that
#: understates activity.
ADR_0016_BLANKET_COUNT_CLAIMS: Final[tuple[str, ...]] = (
    "NO REQUEST WAS SENT BY THIS STAGE",
    "REFUSED_DEPENDENCY MEANS ZERO",
    "REFUSED_DEPENDENCY IMPLIES ZERO",
    "A DEPENDENCY REFUSAL MEANS NOTHING WAS INVOKED",
    "A DEPENDENCY REFUSAL PROVES ZERO",
)

#: Affirmative claims about things that have not happened.
#:
#: Every entry is the **affirmative** form, for the reason the ADR-0015 overclaim
#: list gives: a current-status document has to *name* what stays absent, so
#: "a fifth binding-preflight attempt: NOT AUTHORIZED" is required while "the
#: binding preflight completed" is refused.
ADR_0016_FORBIDDEN_CLAIMS: Final[tuple[str, ...]] = (
    # Six environment-repair entries stood here and are gone -- the six named in
    # `RETIRED_ENVIRONMENT_PROHIBITIONS`. The first revision of this comment said
    # "five" and then listed six, which is why the count is now derived from that
    # tuple rather than written by hand.
    #
    # Seven preflight entries stood here and are gone -- the seven named in
    # `RETIRED_PREFLIGHT_PROHIBITIONS`. Each was refused because it would have
    # been false; the fifth separately authorized binding-preflight attempt made
    # each of them true, once and offline, and a guard that forbids a true
    # statement is answered by writing a vaguer one.
    #
    # What remains is what the fifth attempt still does not support, plus what a
    # *usable* environment must never be read as granting, which
    # `ENVIRONMENT_FORBIDDEN_CLAIMS` adds.
    "AUTHENTICATED QUALIFICATION IS AUTHORIZED",
    "AUTHENTICATED QUALIFICATION IS NOW AUTHORIZED",
    "A SHARADAR REQUEST WAS MADE",
    "AN S3 OBJECT OPERATION WAS PERFORMED",
    "SHARADAR AUTHENTICATION CONFIRMED",
    "A SIXTH BINDING-PREFLIGHT ATTEMPT IS AUTHORIZED",
)


#: One double-quoted span, straight or curly, not crossing a paragraph.
QUOTED_SPAN: Final = re.compile('["“][^"“”]{0,300}?["”]')


def _is_refuted(text: str, start: int, end: int) -> bool:
    """Whether the span at ``[start, end)`` sits inside a quotation explained as false.

    Both halves are required. Quotation alone would be a general bypass -- a
    current status row could keep its claim and add quotation marks -- so the
    surrounding sentence must also say the phrase was wrong.

    Containment, not adjacency. An earlier revision required the quote marks to
    touch the match exactly, which failed on a quotation slightly wider than the
    phrase: quoting *is unreachable when the call returns* encloses one word
    more than the pattern matches. That is a normal way to quote something, and
    a guard that mistook it for an assertion would push a writer toward not
    explaining what they had corrected.
    """
    if not any(span.start() <= start and end <= span.end() for span in QUOTED_SPAN.finditer(text)):
        return False
    window = text[max(0, start - 400) : end + 400].lower()
    return any(marker in window for marker in REFUTATION_MARKERS)


def _current_status_rows(text: str, adr: str) -> list[str]:
    """Every current-status **table row** whose subject is ``adr``.

    Two narrowings, and both matter.

    A **table row**: a line starting with ``|``. An ADR's own status line and any
    explanatory prose are out of scope, which is the whole design -- the
    immutable ADR documents legitimately say "accepted, effective on merge", and
    a guard that could not tell a table row from a decision document would force
    one of them to lie.

    Whose **subject** is the ADR: the link appears in the row's *first cell*. A
    first draft matched any row mentioning the ADR anywhere, which swept in the
    feature tables that cite it inside a description -- rows that are not status
    claims and have no business being held to one.
    """
    rows: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("|"):
            continue
        cells = stripped.split("|")
        if len(cells) > 1 and f"[{adr}](" in cells[1]:
            rows.append(line)
    return rows


def _phase_status_rows(text: str, subject: str) -> list[str]:
    """Every **phase** status row whose first cell names ``subject``.

    The same first-cell scoping the merged-ADR guard uses, for the same reason: a
    row that mentions a phase inside a *description* is not a status claim about
    it, and holding one to a status contract would fail an honest sentence. Case
    is ignored, because these subjects are written in caps in one document and in
    sentence case in the other.

    **A first cell carrying an ADR link is not a phase row.** ADR-0012's row
    describes itself as the "dormant Sharadar qualification runtime core", so a
    bare text match claimed it too -- and it is already governed by
    :data:`MERGED_ADR_STATUS`, which requires different wording. One row answering
    to two registries would make the two contracts fight over it; the split is
    that ADR rows are the ADR guard's and every other row is this one's.
    """
    rows: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("|"):
            continue
        cells = stripped.split("|")
        if len(cells) < 2:
            continue
        first = cells[1]
        if "](docs/decisions/ADR-" in first:
            continue
        if subject.upper() in first.upper():
            rows.append(line)
    return rows


def _stale_phase_status_defects(name: str, text: str) -> list[str]:
    """Every way ``text``'s merged-phase rows misstate a completed merge.

    Reported one defect at a time, because they need different repairs: a
    missing row, a duplicated row, a missing required phrase, and a row still
    carrying a future condition.
    """
    defects: list[str] = []
    for subject, required in MERGED_PHASE_STATUS:
        rows = _phase_status_rows(text, subject)
        if not rows:
            defects.append(f"{name}: no current-status row for {subject}")
            continue
        if len(rows) > 1:
            defects.append(f"{name}: {len(rows)} current-status rows for {subject}, expected 1")
            continue
        flat = " ".join(rows[0].replace("**", "").split()).upper()
        for phrase in required:
            if phrase.upper() not in flat:
                defects.append(f"{name}: the {subject} row does not state {phrase!r}")
        for wording in PRE_MERGE_STATUS_WORDING:
            if wording.upper() in flat:
                defects.append(f"{name}: the {subject} row still says {wording!r}")
                break
    return defects


def _in_force_adr_claims(text: str) -> dict[str, str]:
    """Every ADR that a current-status row claims is in force, and its PR number.

    Read from the **rows**, not from the registry -- that is the point. The
    registry is the governed mapping; this is what the document actually says, and
    comparing the two is how an unregistered row becomes visible instead of
    silently ungoverned.

    Scoped exactly as the other row guards are: the ADR link must be in the row's
    **first cell**, so a feature row citing an ADR in a description is not a
    status claim, and an ADR document's own immutable status line is not a table
    row at all.

    A row is only collected when it states **both** ``ACCEPTED / IN FORCE`` and a
    ``PR #<n> merged`` reference. ADR-0007 and ADR-0008 say ``ACCEPTED on merge
    (2026-08-27)`` -- a dated completed event with no pull-request number -- so
    they are not of this class and are not swept in.
    """
    claims: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("|"):
            continue
        cells = stripped.split("|")
        if len(cells) < 3:
            continue
        subject = ADR_ROW_SUBJECT.search(cells[1])
        if subject is None:
            continue
        status = IN_FORCE_ROW.search("|".join(cells[2:]).replace("**", ""))
        if status is None:
            continue
        claims[subject.group("adr")] = f"PR #{status.group('pr')} merged"
    return claims


def _duplicate_registry_entries(registry: Iterable[tuple[str, str]]) -> list[str]:
    """Every ADR the merged-status registry lists more than once.

    ``dict(MERGED_ADR_STATUS)`` is what every other guard reads, and a mapping
    keeps only the last value for a repeated key -- so a second entry for one
    decision is invisible to them and silently governs. This counts the tuple.
    """
    counts: dict[str, int] = {}
    for adr, _ in registry:
        counts[adr] = counts.get(adr, 0) + 1
    return sorted(adr for adr, count in counts.items() if count > 1)


def _registry_coverage_defects(documents: Mapping[str, str]) -> list[str]:
    """Every in-force ADR claim the explicit registry does not govern, or governs
    differently, or that the two documents disagree about.

    The registry stays the source of truth. This does not add entries, infer a
    merge from a filename or an ADR number, or read Git history -- it refuses to
    let a row of this class exist outside the registry's coverage, which is the
    failure that let ADR-0009 through ADR-0012 sit unguarded while ADR-0013 and
    ADR-0014 were checked.
    """
    registered = dict(MERGED_ADR_STATUS)
    defects: list[str] = []

    for name, text in documents.items():
        for adr, claimed in _in_force_adr_claims(text).items():
            if adr not in registered:
                defects.append(f"{name}: {adr} claims {claimed} but is not in MERGED_ADR_STATUS")
            elif registered[adr].lower() != claimed.lower():
                defects.append(
                    f"{name}: {adr} claims {claimed}, the registry governs {registered[adr]!r}"
                )

    names = sorted(documents)
    if len(names) == 2:
        first, second = (_in_force_adr_claims(documents[n]) for n in names)
        for adr in sorted(set(first) | set(second)):
            if first.get(adr) != second.get(adr):
                defects.append(
                    f"{names[0]} and {names[1]} disagree on {adr}: "
                    f"{first.get(adr)!r} vs {second.get(adr)!r}"
                )
    return defects


def _document_section(text: str, heading: str) -> str:
    """One ``###`` section of a status document, up to the next ``###`` heading.

    Scoping matters more here than anywhere else in this audit: the stale-claim
    guards below refuse wording that other slices use accurately about their own
    surfaces, so they must see one section and not a whole document.
    """
    start = text.find(heading)
    if start == -1:
        return ""
    end = text.find("\n### ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def _matrix_entry(text: str, first_line: str, continuation_indent: int = 24) -> str:
    """One matrix entry or stanza, its continuation lines joined onto it.

    Returns ``""`` when the entry is missing **or** duplicated -- a duplicated
    status line is its own defect, and a guard that silently read the first of
    two would not see it.

    ``continuation_indent`` exists because the matrix holds two shapes, and the
    default is the one this helper was written for:

    * an **ADR entry inside a stanza** begins at fifteen spaces and continues at
      twenty-four -- ADR-0015 and ADR-0016, and the default serves them
      unchanged;
    * a **top-level stanza** begins at column zero and continues at fifteen --
      ``ENVIRONMENT``, whose continuations the twenty-four-space test rejects,
      so the guard for it read only its header line and every clause below was
      invisible to it.

    The parameter is additive and defaulted: both existing callers pass nothing
    and get byte-identical results. Reindenting the stanza instead was not open
    -- ``CLAUDE.md`` is byte-identical across this correction by construction.
    """
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip().startswith(first_line)]
    if len(starts) != 1:
        return ""
    collected = [lines[starts[0]].strip()]
    for line in lines[starts[0] + 1 :]:
        if not line.startswith(" " * continuation_indent) or not line.strip():
            break
        collected.append(line.strip())
    return " ".join(collected)


def _audit_fixture_span(source: str) -> tuple[int, int]:
    """The 1-based inclusive line span of the one ``STALE_AUDIT_DIAGNOSTICS`` assignment.

    Resolved through :mod:`ast`, so the end of the assignment is the parser's
    ``end_lineno`` rather than the next line that happens to look like a tuple
    closing. The first revision of this helper partitioned on a raw ``"\\n)\\n"``
    delimiter, which is not a boundary: a comment on the closing line, or any
    other valid reformatting, made it run on to a *later* tuple and silently hide
    unrelated audit prose from the guard that depends on it.

    Raises:
        ValueError: if the assignment is missing, appears more than once at
            module level, or reports no end line. Fail closed -- an ambiguous
            boundary must break the guard, never quietly widen what it skips.
    """
    spans = [
        (node.lineno, node.end_lineno)
        for node in ast.parse(source).body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "STALE_AUDIT_DIAGNOSTICS"
        and node.end_lineno is not None
    ]
    if len(spans) != 1:
        raise ValueError(
            f"expected exactly one STALE_AUDIT_DIAGNOSTICS assignment, found {len(spans)}"
        )
    return spans[0]


def _audit_prose_excluding_own_fixture(source: str) -> str:
    """This file's text with exactly the stale-diagnostic fixture assignment removed.

    The guard built on :data:`STALE_AUDIT_DIAGNOSTICS` searches for phrases that
    must not be *asserted*, and the tuple listing them necessarily contains every
    one -- so scanning the whole file would always match. That is the same
    self-referential trap this slice has hit repeatedly: a denylist entry that is
    a substring of the thing protecting against it.

    Only the assignment's own lines are dropped. Comments, check names and
    failure details immediately before and after it stay in the scanned surface,
    which is the point: those are exactly where a stale claim would reappear.

    Raises:
        ValueError: propagated from :func:`_audit_fixture_span`.
        SyntaxError: if this file will not parse. Both are fail-closed at the
            call site.
    """
    start, end = _audit_fixture_span(source)
    lines = source.splitlines()
    return "\n".join(lines[: start - 1] + lines[end:])


def _bounded_narrative(section: str, bounds: tuple[str, str]) -> str:
    """One narrative span of ``section``, flattened, or ``""`` if its bounds fail.

    Fail closed. An unresolvable span returns the empty string, which makes the
    required-facts guard fail rather than silently guarding nothing -- the same
    rule :func:`_audit_fixture_span` follows for its own boundary. A boundary
    that is missing, duplicated or inverted is a failure, never a wider span.
    """
    start, end = bounds
    flat = " ".join(section.replace("**", "").split())
    if flat.count(start) != 1 or flat.count(end) != 1:
        return ""
    low = flat.index(start)
    high = flat.index(end, low) + len(end)
    return "" if high <= low else flat[low:high]


def _sso_login_narrative(section: str) -> str:
    """The timed-out SSO-login narrative alone, flattened, or ``""``."""
    return _bounded_narrative(section, SSO_LOGIN_NARRATIVE_BOUNDS)


def _corrected_sso_narrative(section: str) -> str:
    """The corrected-refresh narrative alone, flattened, or ``""``.

    Scoped for the reason :data:`SSO_LOGIN_NARRATIVE_BOUNDS` gives, and for one
    more the negative controls found: the corrected attempt's live-console
    handling is stated twice, in the event table and in the prose, so a
    section-wide guard passed while the prose sentence was deleted. A fact
    asserted in two places needs a guard per place, or it has one guard and one
    unprotected copy.
    """
    return _bounded_narrative(section, CORRECTED_SSO_NARRATIVE_BOUNDS)


def _governed_profile_value(source: str) -> str:
    """The pinned profile name, read from the entry point rather than repeated.

    The guard below needs this string only to prove a status narrative does *not*
    contain it. Writing the value here would put it on one more line for no
    benefit; the entry point already declares it once, and reading it from there
    keeps a single source of truth as well as one fewer copy.

    Returns ``""`` when the constant is absent, which the caller treats as a
    failure rather than as a vacuous pass.
    """
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "EXPECTED_PROFILE"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return ""


def _source_documentation(path: Path) -> str:
    """Every docstring and comment in one module, flattened, or ``""`` on failure.

    :func:`_comment_prose` strips comment markers from *every* line of a file,
    executable lines included, so a required sentence could be satisfied by a
    string literal in the code. This reads the two surfaces that are actually
    documentation -- real docstrings, resolved through :mod:`ast`, and comment
    tokens, resolved through :mod:`tokenize` -- and nothing else. A sentence
    moved out of the docstring and into a variable is therefore *gone* as far as
    this is concerned, which is the property a guard over documentation needs.

    Line wrapping is normalised away before the caller matches anything: the
    phrase this round removes was invisible for two rounds because it was split
    as ``which is the one`` / ``thing the first attempt got wrong``, and a guard
    that cannot see across a wrap is a guard against one particular formatting.

    Fail closed. An unreadable, unparseable or untokenizable file returns the
    empty string, which makes the required-facts guard fail rather than pass on
    an empty surface -- the rule :func:`_audit_fixture_span` follows for its own
    boundary.
    """
    try:
        source = read(path)
        tree = ast.parse(source, filename=str(path))
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (OSError, SyntaxError, UnicodeDecodeError, tokenize.TokenError):
        return ""
    pieces: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            docstring = ast.get_docstring(node, clean=False)
            if docstring:
                pieces.append(docstring)
    pieces.extend(
        re.sub(r"^#:?[ \t]?", "", token.string)
        for token in tokens
        if token.type == tokenize.COMMENT
    )
    return " ".join(" ".join(pieces).replace("**", "").split())


def _comment_prose(text: str) -> str:
    """``text`` with comment markers stripped and line breaks joined out.

    A phrase spanning two comment lines is invisible to a plain flatten: the
    ``#`` opening the continuation lands in the middle of it. The claim
    :data:`STALE_ENVIRONMENT_READ_CLAIMS` refuses did exactly that -- it read
    ``so it read no`` / ``# environment variable`` across a line break -- so the
    marker comes off before the join, the same shape as the blockquote strip
    used for licence prose.

    Both the plain ``#`` and the Sphinx-style ``#:`` marker are removed. A
    negative control found the second: a stale claim wrapped across two ``#:``
    lines survived the guard, because ``lstrip("# ")`` stopped at the colon and
    left it sitting in the middle of the joined phrase. Most commentary in this
    file uses ``#:``, so that gap covered nearly all of it.
    """
    stripped = (
        re.sub(r"^[ \t]*#:?[ \t]?", "", line) for line in text.replace("**", "").splitlines()
    )
    return " ".join(" ".join(stripped).split())


def _documentation_surface(path: Path) -> str:
    """The genuine comments and docstrings of a Python source file, normalized.

    Narrower than :func:`_comment_prose`, which flattens the whole file: this
    takes module, class and function docstrings from the AST and comments from
    the tokenizer, so an **executable string literal is not documentation**
    here. A refusal vocabulary, an allowlisted output sentence or a denylist
    entry living in the source cannot answer a question about what the file
    *says about itself*.

    Emphasis markers come off and whitespace is collapsed before the join, so a
    claim wrapped across two docstring lines -- or two comment lines -- reads
    identically to one written on a single line. Restoring a stale sentence in
    either shape is a negative control, and both must fail.
    """
    source = read(path)
    pieces: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            doc = ast.get_docstring(node)
            if doc:
                pieces.append(doc)
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            pieces.append(re.sub(r"^#:?[ \t]?", "", token.string))
    return " ".join(" ".join(pieces).replace("**", "").split())


def _stale_adr_status_defects(name: str, text: str) -> list[str]:
    """Every way ``text``'s ADR current-status rows misstate a merged decision.

    Four separate failures, reported separately because they need different
    repairs: a missing row, a duplicated row, a row that does not say the
    decision is in force, and a row that names the wrong pull request.
    """
    defects: list[str] = []
    for adr, merged_in in MERGED_ADR_STATUS:
        rows = _current_status_rows(text, adr)
        if not rows:
            defects.append(f"{name}: no current-status row for {adr}")
            continue
        if len(rows) > 1:
            defects.append(f"{name}: {len(rows)} current-status rows for {adr}, expected 1")
            continue
        row = rows[0]
        flat = " ".join(row.replace("**", "").split())
        upper = flat.upper()
        if "ACCEPTED / IN FORCE" not in upper:
            defects.append(f"{name}: the {adr} row does not state ACCEPTED / IN FORCE")
        if merged_in.lower() not in flat.lower():
            defects.append(f"{name}: the {adr} row does not name {merged_in!r}")
        for wording in PRE_MERGE_STATUS_WORDING:
            if wording.upper() in upper:
                defects.append(f"{name}: the {adr} row still says {wording!r}")
                break
    return defects


def _composition_overclaims(text: str) -> list[str]:
    """Every overclaim *asserted* in ``text``.

    Normalised first: Markdown emphasis and backticks are removed and whitespace
    is collapsed, so a claim cannot escape by being bolded, code-fenced or
    line-wrapped. That is the whole reason this exists -- the previous revision
    matched one exact literal and missed the two status rows that wrote the same
    claim in bold.

    A phrase is permitted only where it is quoted **and** the surrounding text
    identifies it as false, so the documents can still explain what was
    corrected without that becoming a way to keep asserting it.
    """
    normalised = re.sub(r"\s+", " ", MARKDOWN_EMPHASIS.sub("", text))
    found: list[str] = []

    for phrase in COMPOSITION_OVERCLAIMS:
        target = re.sub(r"\s+", " ", phrase)
        for match in re.finditer(re.escape(target), normalised):
            if not _is_refuted(normalised, match.start(), match.end()):
                found.append(phrase)
                break

    for match in UNSCOPED_EXECUTION_SURFACE.finditer(normalised):
        if normalised[: match.start()].lower().endswith(EXECUTION_SURFACE_SCOPE):
            continue  # the scoped form is the correct claim
        if _is_refuted(normalised, match.start(), match.end()):
            continue
        found.append(f"unscoped execution-surface claim: {match.group(0)!r}")
        break

    for match in LIFETIME_CLAIM.finditer(normalised):
        if _is_refuted(normalised, match.start(), match.end()):
            continue
        found.append(f"object-lifetime claim: {match.group(0)[:60]!r}")
        break

    return found


def _composition_state_sites() -> list[str]:
    """Every place the composition module stores a constructed component durably.

    **Durable retention is the property, not object lifetime.** A local variable
    is fine: the function neither returns it nor keeps it anywhere a later caller
    can reach. An attribute on ``self``, a class attribute or a module global is
    not -- the first revision of ADR-0014 stored all three on an instance, and
    ``composition._runtime.execute(plan)`` worked.

    Nothing here claims a local stops existing when the call returns. Whether it
    does is a garbage-collection question this audit has no business answering,
    and it is not what makes the composition dormant.
    """
    if not COMPOSITION_ROOT.is_file():
        return []
    built = {"SharadarClient", "S3ResearchObjectStore", "QualificationRuntime"}
    offenders: list[str] = []
    tree = ast.parse(read(COMPOSITION_ROOT), filename=str(COMPOSITION_ROOT))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in built
        ):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                offenders.append(f"line {node.lineno}: {ast.unparse(target)}")
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id != "__all__":
                    offenders.append(f"module-level state: {target.id}")
    return offenders


def _qualification_mode_definitions() -> int:
    """How many modules assign ``QUALIFICATION_ACQUISITION_MODE``. Expected: one.

    Two independent statements of one fact is a dual-write, and the interesting
    case is the one where they disagree.
    """
    count = 0
    for path in _src_python_files():
        for node in ast.walk(ast.parse(read(path), filename=str(path))):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            count += sum(
                1
                for target in targets
                if isinstance(target, ast.Name) and target.id == "QUALIFICATION_ACQUISITION_MODE"
            )
    return count


def _src_python_files() -> list[Path]:
    return [p for p in sorted((REPO_ROOT / "src").rglob("*.py")) if "__pycache__" not in p.parts]


def _qualification_python_files(root: Path) -> list[Path]:
    """Every Python module under ``root``, excluding caches and sorted."""
    if not root.is_dir():
        return []
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


#: What a Sharadar subject may look like on the wire, restated here so the audit can
#: refuse a literal shaped like one without importing the plan model.
_SUBJECT_SHAPED: Final = re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")

#: Uppercase literals that are vocabulary rather than securities. Every one is a
#: closed-vocabulary member or a status token, and none could name a listed security.
_NOT_A_SUBJECT: Final[frozenset[str]] = frozenset(
    {
        "AES256",
        "BIND",
        "BOUNDED",
        "COMPLETE",
        "COMPLETED",
        "CONTROL",
        "COUNT",
        "DATE",
        "DECIMAL",
        "DEFERRED",
        "ENABLED",
        "FLAG",
        "FULL",
        "GET",
        "HEAD",
        "INCONCLUSIVE",
        "INSUFFICIENT",
        "LICENSED",
        "MEASURED",
        "OBSERVED",
        "P1",
        "P2",
        "P3",
        "P4",
        "P5",
        "P6",
        "P7",
        "P8",
        "P9",
        "PARTIAL",
        "PUT",
        "QUALIFICATION",
        "SHA256",
        "SNAPSHOT",
        "TESTED",
        "WRITTEN",
    }
)


def _closed_vocabulary_values(tree: ast.Module) -> set[str]:
    """Every string a ``StrEnum`` in this module assigns to a member.

    Derived rather than hand-listed. A status token is vocabulary, not a security,
    and a list of exemptions would have to grow every time a member was added --
    which is how an exemption list stops being read and starts being appended to.
    """
    values: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(
            (isinstance(base, ast.Name) and base.id == "StrEnum")
            or (isinstance(base, ast.Attribute) and base.attr == "StrEnum")
            for base in node.bases
        ):
            continue
        for statement in node.body:
            if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Constant):
                if type(statement.value.value) is str:
                    values.add(statement.value.value)
    return values


def _subject_shaped_literals(path: Path) -> list[str]:
    """Every string literal in ``path`` shaped like a security symbol.

    Checked against the subject grammar rather than against a list of names nobody
    can enumerate. A closed-vocabulary member defined in the same module is
    vocabulary and not a symbol, and so are the few structural tokens above.
    """
    tree = ast.parse(read(path), filename=str(path))
    permitted = _NOT_A_SUBJECT | _closed_vocabulary_values(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and type(node.value) is str:
            value = node.value
            if _SUBJECT_SHAPED.match(value) and value not in permitted and "_" not in value:
                found.append(value)
    return found


def _qualification_role_declarations() -> list[str]:
    """Every Terraform file declaring one of the two designed qualification roles.

    Expected: none. Designing a role is not creating one, and creating one is a
    separately authorized infrastructure mutation.
    """
    infra = REPO_ROOT / "infra"
    if not infra.is_dir():
        return []
    offenders: list[str] = []
    for path in sorted(infra.rglob("*.tf")):
        text = read(path).lower()
        if "qualification_acquisition" in text or "qualification_assessment" in text:
            offenders.append(path.name)
    return offenders


def _unframed_occurrences(text: str, phrase: str, framing: str) -> int:
    """How many copies of ``phrase`` stand outside its historical ``framing``.

    Pure arithmetic over one flattened reading: every framed copy contains the
    phrase, so subtracting the framed count from the total leaves the copies that
    stand alone. Zero is the only acceptable answer for a superseded status line.

    It is deliberately not a denylist. The phrase is *required* elsewhere and is
    legitimately present, so "is it here" cannot distinguish the preserved record
    from a revert; "is it here unframed" can.
    """
    return text.count(phrase) - text.count(framing)


def _runtime_execute_call_sites() -> list[Path]:
    """Every module under ``src/`` that calls ``.execute(...)`` on something.

    By AST, so a mention in a docstring or a comment is not a call: the composition
    root's own prose quotes ``composition._runtime.execute(plan)`` to explain a
    defect it fixed, and a substring scan would count that as a third caller.

    Expected: exactly the two named in :data:`RUNTIME_EXECUTE_CALLERS`. The
    ADR-0017 composition path is one and the dormant ADR-0018 acquisition path is
    the other, and they are separate on purpose -- the second may not become
    reachable from the first.
    """
    sites: list[Path] = []
    for path in _src_python_files():
        tree = ast.parse(read(path), filename=str(path))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            for node in ast.walk(tree)
        ):
            sites.append(path)
    return sites


def _store_construction_sites() -> list[Path]:
    """Every module under ``src/`` that constructs the licensed object store."""
    sites: list[Path] = []
    for path in _src_python_files():
        tree = ast.parse(read(path), filename=str(path))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "S3ResearchObjectStore"
            for node in ast.walk(tree)
        ):
            sites.append(path)
    return sites


def _entry_point_exports() -> tuple[str, ...]:
    """The entry point's ``__all__``, or every module-level public name.

    The capability, its mint and its minting function must appear in neither.
    """
    if not BINDING_PREFLIGHT.is_file():
        return ()
    tree = ast.parse(read(BINDING_PREFLIGHT), filename=str(BINDING_PREFLIGHT))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            if isinstance(node.value, ast.List):
                return tuple(
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                )
    return ()


def _authorization_handover_sites() -> list[str]:
    """Every function that reads the authorization singleton to pass it on.

    ``_is_authorized`` names it too, to compare against -- that is the check
    rather than a hand-over, so it is excluded. Expected: ``main`` alone.
    """
    if not BINDING_PREFLIGHT.is_file():
        return []
    tree = ast.parse(read(BINDING_PREFLIGHT), filename=str(BINDING_PREFLIGHT))
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name != "_is_authorized"
        and any(
            isinstance(inner, ast.Name) and inner.id == "_BINDING_PREFLIGHT_AUTHORIZATION"
            for inner in ast.walk(node)
        )
    ]


def _argv_secret_identifier_options() -> list[str]:
    """Every ``add_argument`` in the entry point that would put a secret in argv.

    A private identifier on the command line enters shell history and every
    process listing on the machine, whether or not the program prints it -- so
    this is checked at the parser, where the option would be declared, rather
    than by searching prose.
    """
    if not BINDING_PREFLIGHT.is_file():
        return []
    forbidden = ("secret", "credential", "api_key", "apikey", "token", "password")
    offenders: list[str] = []
    tree = ast.parse(read(BINDING_PREFLIGHT), filename=str(BINDING_PREFLIGHT))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument":
            continue
        names = [
            argument.value
            for argument in node.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        ]
        names += [
            keyword.value.value
            for keyword in node.keywords
            if keyword.arg == "dest"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        ]
        offenders += [name for name in names if any(bad in name.lower() for bad in forbidden)]
    return offenders


def _emitted_preflight_sentences(path: Path) -> str:
    """Every string value in the entry point's output vocabulary, joined.

    The *values* are what a caller reads. Member names are not: the refusal
    member is called ``REFUSED_NOT_AUTHORIZED``, and forbidding the word in a
    name would forbid naming a refusal accurately.
    """
    tree = ast.parse(read(path), filename=str(path))
    sentences: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "PreflightOutcome":
            continue
        for statement in node.body:
            if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Constant):
                sentences.append(str(statement.value.value))
    return " ".join(sentences)


def _method_body(path: Path, class_name: str, method: str) -> str:
    """One method's executable body, docstring stripped, unparsed.

    Scoped to its class, because a module can hold several ``__init__`` methods
    and a guard about one of them must not be answered by another.
    """
    tree = ast.parse(read(path), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for statement in node.body:
            if isinstance(statement, ast.FunctionDef) and statement.name == method:
                body = list(statement.body)
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    body = body[1:]
                return ast.unparse(ast.Module(body=body, type_ignores=[]))
    return ""


def _function_body(path: Path, name: str) -> str:
    """One function's executable body, docstring stripped, unparsed.

    Scoped to the function so a guard about what a *classifier* may contain is
    not satisfied or defeated by the module's prose about it. Docstrings are
    dropped for the reason `_executable_python` gives: a module has to be able
    to explain the outcome it refuses to return.
    """
    tree = ast.parse(read(path), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            body = list(node.body)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]
            return ast.unparse(ast.Module(body=body, type_ignores=[]))
    return ""


def _outcome_sentence(path: Path, member: str) -> str:
    """The sentence one ``PreflightOutcome`` member renders as.

    The *value*, not the name: an operator reads the sentence, and ADR-0016 is
    about a sentence that named a boundary the run never reached.
    """
    tree = ast.parse(read(path), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "PreflightOutcome":
            continue
        for statement in node.body:
            if not isinstance(statement, ast.Assign):
                continue
            named = any(
                isinstance(target, ast.Name) and target.id == member for target in statement.targets
            )
            if named and isinstance(statement.value, ast.Constant):
                return str(statement.value.value)
    return ""


#: The three calls whose order is the corrected stage boundary.
BINDING_STAGE_CALLS: Final[tuple[str, ...]] = (
    "secret_id_source",
    "secrets_client_factory",
    "sharadar_credential_from_secret",
)


def _binding_stage_order(source: str) -> list[str]:
    """The three stage calls, in the order the entry point performs them.

    First occurrence in the executable source. Resolve, then construct, then
    ask: the identifier must be refusable before a client exists, and a client
    must exist before anything can be attributed to a request.
    """
    found = [(source.index(call), call) for call in BINDING_STAGE_CALLS if call in source]
    return [call for _, call in sorted(found)]


def _accepted_cli_options(path: Path) -> tuple[tuple[str, ...], ...]:
    """Every option string the entry point's parser accepts, in declaration order.

    Resolved statically. A ``Name`` argument -- the authorization flag is declared
    through its module constant -- is looked up among the module's own top-level
    string assignments, so the guard sees the spelling the parser will register
    rather than the identifier that carries it.

    Fail closed: an ``add_argument`` call whose option string cannot be resolved
    to a literal contributes the sentinel ``("<unresolved>",)``, which no expected
    surface matches. Silently dropping it would let an unreadable declaration
    widen the surface while the guard reported a pass.
    """
    module = ast.parse(read(path))
    constants: dict[str, str] = {}
    for node in module.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target = node.targets[0].id
        if (
            target is not None
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            constants[target] = node.value.value

    surface: list[tuple[str, ...]] = []
    for node in ast.walk(module):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            options: list[str] = []
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    options.append(argument.value)
                elif isinstance(argument, ast.Name) and argument.id in constants:
                    options.append(constants[argument.id])
                else:
                    options.append("<unresolved>")
            surface.append(tuple(options))
    return tuple(surface)


def _module_level_imports(path: Path) -> str:
    """Every import a module performs at import time, unparsed.

    What an ordinary import of the entry point actually pulls in -- which must
    stay empty of the SDK *and* of the data platform, so a refusal on a machine
    with a broken environment is still a refusal rather than a traceback.
    """
    tree = ast.parse(read(path), filename=str(path))
    return ast.unparse(
        ast.Module(
            body=[n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)],
            type_ignores=[],
        )
    )


def _sdk_client_construction_sites() -> list[Path]:
    """Every file that constructs an AWS SDK client or session.

    ADR-0015 authorized exactly one, in ``scripts/``. Text rather than AST,
    because ``boto3.client`` is an attribute call on a module imported inside a
    function body -- which is precisely how the entry point keeps import time
    free of the SDK.
    """
    # This audit and the binding-preflight test both *name* the constructor, in
    # order to forbid it and to assert its absence. A guard that could not tell a
    # prohibition from a construction would forbid writing the prohibition.
    scanning = {
        Path(__file__).resolve(),
        BINDING_TESTS,
        REPO_ROOT / "tests" / "unit" / "test_sharadar_empirical_entry_points.py",
    }
    sites: list[Path] = []
    for root in (REPO_ROOT / "src", REPO_ROOT / "scripts", REPO_ROOT / "tests"):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts or path in scanning:
                continue
            source = read(path)
            if "boto3.client(" in source or "boto3.Session(" in source:
                sites.append(path)
    return sites


def _aws_sdk_import_sites() -> list[str]:
    """Every module under ``src/`` that imports the AWS SDK. Expected: none.

    The SDK is a declared dependency because a *future* authorized runner must
    construct a signed client; the composition root receives one instead, so the
    data platform still imports no AWS code.
    """
    offenders: list[str] = []
    for path in _src_python_files():
        for node in ast.walk(ast.parse(read(path), filename=str(path))):
            names: set[str] = set()
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module}
            if {name.split(".")[0] for name in names} & {"boto3", "botocore"}:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    return offenders


def _composition_construction_sites() -> list[str]:
    """Every place the composition is constructed outside its own test module."""
    offenders: list[str] = []
    roots = (REPO_ROOT / "src", REPO_ROOT / "scripts", REPO_ROOT / "tests")
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts or path == COMPOSITION_TESTS:
                continue
            for node in ast.walk(ast.parse(read(path), filename=str(path))):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "SharadarQualificationComposition"
                ):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return offenders


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


# ---------------------------------------------------------------------------
# ADR-0017 -- an ACCEPTED architecture, and the facts a status document must keep
# ---------------------------------------------------------------------------

#: The ADR this section governs. Merged by PR #33, so it is now governed by
#: :data:`MERGED_ADR_STATUS` like every other in-force ADR -- and the guards below
#: that once required its *absence* from that registry are inverted rather than
#: deleted, because a check removed leaves nothing behind and a check inverted
#: still fails when the fact reverts.
ADR_0017: Final = DECISIONS / (
    "ADR-0017-bounded-authenticated-sharadar-acquisition-qualification.md"
)

#: The pull request that accepted ADR-0017, its merge commit and the approved
#: head that merge carried. Written out so a status document cannot claim the
#: acceptance while naming a different pull request or a different commit.
ADR_0017_PR: Final = "#33"
ADR_0017_MERGE_COMMIT: Final = "4fab37cd9468bc48b62a80e49e5a17a203870926"
ADR_0017_APPROVED_HEAD: Final = "679863fd7f540f47ae4f47aee8d5e363d72caffd"

#: What both status documents must independently say about ADR-0017, in prose.
#:
#: Independently is the point. Merged main has twice carried a fact in one
#: document and a stale contradiction in the other, so each phrase is required in
#: *each* file rather than in their concatenation.
#:
#: Matched against the document with emphasis removed and whitespace collapsed,
#: so a rewrap cannot hide a sentence and a bold marker cannot split one.
ADR_0017_REQUIRED_PROSE: Final[tuple[tuple[str, str], ...]] = (
    (
        "names ADR-0017 and links its decision record",
        "adr-0017](docs/decisions/adr-0017-bounded-authenticated-sharadar-acquisition-qualification",
    ),
    ("records ADR-0017 as accepted and in force", "accepted / in force"),
    ("names the pull request that accepted it", f"pr {ADR_0017_PR} merged"),
    ("names the merge commit", ADR_0017_MERGE_COMMIT),
    ("names the approved ADR head", ADR_0017_APPROVED_HEAD),
    ("keeps the pre-merge period historically accurate", "carried no authority"),
    ("records the entry point as implemented", "is now implemented"),
    (
        "records two attempts, refused then completed",
        "attempted twice \u2014 refused, then completed",
    ),
    ("names the closed outcome of that attempt", "refused_identity"),
    ("names the exit code of that attempt", "exit code `6`"),
    ("keeps the cause of the refusal undiagnosed", "not diagnosed"),
    ("names the implemented entry point", "scripts/sharadar_authenticated_qualification.py"),
    (
        "keeps a third execution separately gated",
        "a third execution of the surface",
    ),
    (
        "refuses a further identity diagnosis and another SSO login",
        "another aws sso refresh or login",
    ),
    ("keeps the three gates distinct", "three distinct gates"),
    ("introduces no parser", "no parser"),
    ("preserves one request = one durable acquisition", "one request = one durable acquisition"),
    ("preserves the opaque-payload boundary", "opaque-payload boundary"),
    ("declares the qualification acquisition mode", "acquisitionmode.qualification"),
    ("introduces no fourth acquisition mode", "no fourth mode"),
    (
        "keeps evidence in the licensed private Bronze data plane",
        "licensed private bronze data plane",
    ),
    (
        "keeps the full empirical qualification separate and unexecuted",
        "empirical qualification remains separate and unexecuted",
    ),
    ("keeps G1 and G2 open in the same breath", "g1 open · g2 open · g3 closed"),
)

#: The same facts as counted lines, matched against the raw document.
#:
#: These live in a fenced block whose alignment is the evidence: a count column
#: that stops lining up is a count somebody edited by hand. Collapsing the
#: whitespace before matching would throw away exactly that signal, so these are
#: checked against the unmodified text.
ADR_0017_REQUIRED_COUNTS: Final[tuple[tuple[str, str], ...]] = (
    (
        "records exactly one implemented authenticated entry point",
        "authenticated entry points implemented      one",
    ),
    (
        "records two authenticated qualification attempts, refused then completed",
        "authenticated qualification attempts        two -- one refused, one completed",
    ),
    (
        "records exactly one entry-point process invocation",
        "entry-point process invocations             one",
    ),
    (
        "names the closed outcome of that attempt",
        "closed outcome                              refused_identity",
    ),
    (
        "records the last stage definitively reached",
        "last stage definitively reached             stage 5 -- the aws identity gate",
    ),
    ("records that stages 1-4 passed", "stages 1-4                                  passed"),
    (
        "records one refused AWS identity-gate invocation",
        "aws identity-gate invocations               one -- refused",
    ),
    (
        "records zero licensed-bucket resolutions",
        "licensed-bucket resolutions                 zero",
    ),
    (
        "records zero Terraform command invocations",
        "terraform command invocations               zero",
    ),
    (
        "records zero secret-identifier resolutions",
        "secret-identifier resolutions               zero",
    ),
    (
        "records zero reads of the secret-identifier variable",
        "kalpamani_sharadar_secret_id reads          zero",
    ),
    (
        "records zero Secrets Manager client constructions",
        "secrets manager client constructions        zero",
    ),
    (
        "records zero get_secret_value invocations",
        "get_secret_value invocations                zero",
    ),
    (
        "records zero credential retrievals by this attempt",
        "credential retrievals by this attempt       zero",
    ),
    ("records zero S3 client constructions", "s3 client constructions                     zero"),
    (
        "records zero provider transport constructions",
        "provider transport constructions            zero",
    ),
    (
        "records zero qualification-runtime executions",
        "qualification-runtime executions            zero",
    ),
    (
        "records zero application-level provider fetches",
        "application-level provider fetches          zero",
    ),
    ("records zero Sharadar/provider requests", "sharadar/provider requests                  zero"),
    (
        "keeps provider-wide authentication UNKNOWN",
        "provider-wide authentication                unknown",
    ),
    ("records zero PutObject operations", "putobject                                   zero"),
    ("records zero S3 object-byte reads", "s3 object-byte reads                        zero"),
    (
        "records zero S3 object operations for qualification",
        "s3 object operations for qualification      zero",
    ),
    ("records zero CONTROL operations", "control operations                          zero"),
    (
        "records zero .runtime/ writes from this attempt",
        ".runtime/ writes from this attempt          zero",
    ),
    ("records zero P1-P9 executions", "p1-p9 executions                            zero"),
    (
        "records zero ingestion and trading operations",
        "ingestion and trading operations            zero",
    ),
    (
        "keeps the underlying AWS/network total UNKNOWN",
        "underlying aws/network interactions         unknown -- no count is established",
    ),
    (
        "keeps the gate's own STS command invocation UNKNOWN",
        "sts command invocations by the gate         unknown -- real pre-sts refusal paths exist",
    ),
    (
        "leaves the cause of the refusal undiagnosed",
        "cause of the identity refusal               undiagnosed -- not inferred, not repaired",
    ),
    (
        "leaves the credential retrievals established by count at one",
        "credential retrievals established by count  one",
    ),
    (
        "leaves the binding-preflight count at five",
        "binding-preflight attempts                  five -- unchanged",
    ),
)
#: The seventeen chronology steps, in the order the governance depends on.
#:
#: Presence is not enough and never was: a document listing acceptance before the
#: merge tells a reader that the ADR carried authority while its pull request was
#: open, which is the one thing this slice must not assert. The audit therefore
#: checks the *positions*, not the sentences.
#:
#: The last four were added when the surface was first executed. Their order is
#: the whole governance claim: the entry point was unexecuted, then one attempt
#: was made, then four stages passed, then the fifth refused. A document that
#: narrates the refusal before the attempt, or the attempt before the merge,
#: tells a reader something nobody authorized.
ADR_0017_CHRONOLOGY: Final[tuple[str, ...]] = (
    "proposed in open pr #33 and carried no authority",
    "pr #33 merged.",
    "the merge activated adr-0017's own acceptance condition",
    "adr-0017 is now accepted and in force",
    "no implementation and no execution followed the merge",
    "the dormant code-only implementation slice",
    "it had never been executed at that point",
    "a separately authorized first execution was then attempted",
    f"stages 1{EN_DASH}4 passed",
    "the existing aws identity gate, was invoked once and refused",
    "no retry, diagnosis, sso login or repair followed that refusal",
    "a separately authorized sso login completed with exit code `0`",
    "a separately authorized identity diagnosis then returned `identity_confirmed`",
    "a separately authorized second execution was then attempted, and it completed",
    "the qualification runtime was reached",
    "attempt two's s3 qualification operations are bounded at three to six",
    "no third attempt, retry, diagnosis, sso login or repair followed",
)

#: Claims that would misdescribe an implemented, twice-attempted surface.
#:
#: Three kinds, and each matters. Some are *stale*: they were required while the
#: entry point did not exist, or while it had not been run, and are false now.
#: Some are *unestablished*: attempt two ran, reached the qualification runtime,
#: made one provider request and returned ``COMPLETED`` -- and ``COMPLETED`` is
#: the command's status, not a verdict, so a document may say the run happened,
#: may state the S3 bounds that token fixes, and may never say it *passed*. The
#: rest are *overreach*: they claim
#: a conclusion no acquisition could establish. Deleting the stale ones without
#: replacing them would leave the reverted claim unguarded, so each is inverted
#: into a rejection instead.
#:
#: What a completed second attempt did not settle, and what these still refuse:
#: provider-wide authentication stays UNKNOWN, how many objects were newly written
#: stays unestablished, no provider is selected, G1 and G2 stay OPEN, and Phase 3
#: stays NOT COMPLETE.
#:
#: 49 claims about an implemented, twice-attempted surface are listed here,
#: and the number in that sentence is checked against ``len()`` so an entry cannot
#: leave quietly.
ADR_0017_FORBIDDEN: Final[tuple[str, ...]] = (
    # -- stale: true before ADR-0017 merged, false now
    "adr-0017 is proposed",
    "adr-0017 remains proposed",
    "adr-0017 is not accepted",
    "adr-0017 is not in force",
    "pr #33 is open",
    "pr #33 remains open",
    "carries no authority whatsoever",
    "adr-0017 is absent from",
    # -- stale: true before the implementation slice, false now
    "no authenticated qualification entry point exists",
    "no tracked authenticated qualification entry point",
    "the entry point has not been implemented",
    "authenticated entry points implemented none",
    "has no production caller",
    # -- stale: true before the dormant ADR-0018 acquisition path merged. The
    # ADR-0017 caller is still exactly one; the repository now has two.
    "exactly one production caller",
    "no authenticated implementation may be built",
    # -- unestablished: more than either run put on the record
    "the authenticated qualification passed",
    "provider authentication confirmed",
    "provider authentication is confirmed",
    "attempt two s3 qualification operations zero",
    "attempt one made a provider request",
    "s3 qualification publication occurred",
    "adr-0017 authorizes execution",
    "adr-0017 permits execution",
    "acceptance authorizes execution",
    "execution of the new surface is authorized",
    # -- overreach: a conclusion no acquisition could establish
    "zero-persistence is the selected design",
    "a fourth acquisition mode",
    "payload parsing is permitted in the acquisition runtime",
    "the acquisition runtime parses",
    "control publication is permitted",
    "a provider is selected",
    "g1 closed",
    "g2 closed",
    # -- stale: true before the first authenticated attempt, false now
    "authenticated qualification attempts zero",
    "the entry point has never been run",
    "code only / never run",
    # -- overstated: more than the one refusal established
    "the authenticated qualification completed",
    "a credential was retrieved during this attempt",
    "the sso session was definitely missing",
    "the sso session was definitely expired",
    "the identity refusal proves a credential defect",
    "the identity refusal proves a provider failure",
    "underlying aws network requests zero",
    "underlying aws network requests one",
    # -- permission the refusal did not create
    "a retry is authorized",
    "a second authenticated attempt is authorized",
    "further aws identity diagnosis is authorized",
    "another sso refresh is authorized",
    "sso repair is authorized",
)

#: The claims that may never leave :data:`ADR_0017_FORBIDDEN`.
#:
#: The size sentence above catches an entry vanishing on its own. It does not
#: catch an entry deleted *together with* the number, which is the shape a
#: weakening actually takes -- one edit removes the guard and a second makes the
#: arithmetic agree again. These are checked by membership, so the denylist may
#: grow and may be reworded, and these particular claims cannot be dropped
#: without failing a check that says so by name.
#:
#: 19 claims are protected by membership here.
ADR_0017_SURVIVING_CLAIMS: Final[tuple[str, ...]] = (
    "adr-0017 remains proposed",
    "pr #33 remains open",
    "the entry point has not been implemented",
    "authenticated entry points implemented none",
    "the authenticated qualification passed",
    "provider authentication is confirmed",
    "attempt one made a provider request",
    "s3 qualification publication occurred",
    "acceptance authorizes execution",
    "a fourth acquisition mode",
    "payload parsing is permitted in the acquisition runtime",
    "a provider is selected",
    "authenticated qualification attempts zero",
    "the entry point has never been run",
    "the sso session was definitely missing",
    "the sso session was definitely expired",
    "underlying aws network requests zero",
    "underlying aws network requests one",
    "a retry is authorized",
)

#: The heading of the ADR-0017 narrative section in both status documents.
ADR_0017_SECTION_HEADING: Final = "### The bounded authenticated acquisition qualification"


def _adr_0017_row(text: str) -> str:
    """The ADR-0017 table row, folded. Empty when the row is absent."""
    for line in text.splitlines():
        if "ADR-0017-bounded-authenticated" in line and line.lstrip().startswith("|"):
            return " ".join(line.replace("**", "").split()).lower()
    return ""


def _adr_0017_section(text: str) -> str:
    """The ADR-0017 narrative section, heading excluded. Empty when absent."""
    start = text.find(ADR_0017_SECTION_HEADING)
    if start < 0:
        return ""
    rest = text[start + len(ADR_0017_SECTION_HEADING) :]
    end = len(rest)
    for marker in ("\n### ", "\n## "):
        found = rest.find(marker)
        if found >= 0:
            end = min(end, found)
    return rest[:end]


#: The fenced governance matrix in CLAUDE.md -- the IN FORCE / NOT AUTHORIZED
#: block, which is neither a table row nor the narrative section.
#:
#: It needs its own extractor because the row guard reads table lines and the
#: section guard reads the narrative heading, and neither can see inside a fenced
#: block. Without this a reviewer deleting the matrix stanza would be told the
#: documents are consistent, on the strength of two other surfaces that still
#: carry the fact.
def _governance_matrix(text: str) -> str:
    """The fenced IN FORCE / NOT AUTHORIZED matrix. Empty when absent."""
    for block in text.split("```"):
        if "\nIN FORCE " in block and "\nNOT AUTHORIZED " in block:
            return block
    return ""


#: What the fenced matrix must carry about ADR-0017, checked inside the matrix.
#:
#: Split deliberately: the first group is what is now IN FORCE, the second is
#: what acceptance did *not* authorize. A matrix that carries one group and not
#: the other reads as either a permission nobody granted or a prohibition that
#: outlived its decision.
ADR_0017_MATRIX_IN_FORCE: Final[tuple[tuple[str, str], ...]] = (
    ("registers ADR-0017 as accepted and in force", "adr-0017 bounded authenticated"),
    ("names the pull request that accepted it", f"pr {ADR_0017_PR} merged"),
    ("names the merge commit", ADR_0017_MERGE_COMMIT),
    ("names the approved ADR head", ADR_0017_APPROVED_HEAD),
    ("records that it is no longer proposed", "no longer\n                        proposed"),
    ("states that implementing is not permission to use", "not permission to"),
    ("keeps execution separately gated", "gated and not authorized"),
    ("records the entry point as implemented", "is now implemented,"),
    (
        "records it as attempted twice, refused then completed",
        "attempted twice -- refused, then completed.",
    ),
    (
        "records two attempts, one refused and one completed",
        "authenticated qualification\n"
        "                        attempts two -- one refused, one completed;",
    ),
    (
        "names the closed outcome",
        "closed outcome\n                        refused_identity;",
    ),
    ("names the exit code", "exit code 6;"),
    (
        "records that stages 1-4 passed",
        "stages 1-4\n                        passed;",
    ),
    (
        "keeps the underlying AWS/network total unknown",
        "underlying aws/network interactions unknown;",
    ),
    (
        "keeps the identity gate own STS command invocation unknown",
        "own sts command invocation unknown, because real",
    ),
    (
        "leaves the cause of the refusal undiagnosed",
        "the cause of the refusal\n                        undiagnosed and not inferred",
    ),
    (
        "records that no retry or repair followed",
        "no retry, diagnosis, sso\n                        login or repair followed",
    ),
    (
        "keeps the binding-preflight count at five",
        "binding-preflight attempts remain five",
    ),
    ("counts one implemented entry point", "implemented one;"),
    ("records the composition root as extended", "extended, not duplicated"),
    ("records exactly one ADR-0017 production caller", "adr-0017 production caller"),
    (
        "records the two production call sites overall",
        "exactly two production call sites overall",
    ),
)

ADR_0017_MATRIX_NOT_AUTHORIZED: Final[tuple[tuple[str, str], ...]] = (
    ("refuses execution of the future surface", "execution of the bounded authenticated"),
    ("keeps the AWS identity gate and Terraform gated", "the aws identity gate, terraform"),
    ("keeps secret retrieval and Secrets Manager gated", "secret retrieval, secrets manager"),
    ("keeps any provider request gated", "any provider request"),
    (
        "keeps S3 qualification publication gated",
        "any s3 qualification\n                        publication",
    ),
    (
        "keeps further authenticated qualification gated",
        "further authenticated qualification",
    ),
    (
        "refuses a third execution rather than a first or a second",
        "a third execution of the bounded authenticated",
    ),
    (
        "refuses a diagnosis, a repair and a retry of the refusal",
        "further aws identity diagnosis of that refusal",
    ),
    ("keeps full empirical qualification a later gate", "full p1-p9 empirical qualification"),
    ("keeps broker, LEAN, Paper and live trading refused", "broker/lean activity"),
)

#: What the ADR-0017 **row** must carry, checked inside the row itself.
#:
#: Scoped rather than document-wide, because a document-wide scan is satisfied by
#: any copy of the phrase. Merged main has already carried a row that had gone
#: stale beside a narrative that had not, and a whole-file check reports that as
#: healthy: the narrative answers for the row. Each fact is required where a
#: reader of the status table would actually look for it.
ADR_0017_ROW_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    ("records ADR-0017 as accepted and in force", "accepted / in force"),
    ("names the pull request that accepted it", f"pr {ADR_0017_PR} merged"),
    ("names the merge commit", ADR_0017_MERGE_COMMIT),
    ("names the approved ADR head", ADR_0017_APPROVED_HEAD),
    ("records that the merge acceptance condition occurred", "acceptance condition has occurred"),
    ("records that ADR-0017 is no longer proposed", "no longer proposed"),
    (
        "keeps the pre-merge period historically accurate",
        "while its pull request was open it was",
    ),
    (
        "records the entry point as implemented, attempted twice, refused then completed",
        "is now implemented, attempted twice \u2014 refused, then completed",
    ),
    (
        "records two attempts, one refused and one completed",
        "authenticated qualification attempts two — one refused, one completed",
    ),
    ("names the closed outcome", "closed outcome `refused_identity`"),
    ("names the exit code", "exit code `6`"),
    (
        "names the last stage definitively reached",
        "last stage definitively reached stage 5 — the aws identity gate",
    ),
    ("records that stages 1-4 passed", f"stages 1{EN_DASH}4 passed"),
    (
        "records one refused identity-gate invocation",
        "aws identity-gate invocations one, refused",
    ),
    ("records zero licensed-bucket resolutions", "licensed-bucket resolutions zero"),
    ("records zero secret-identifier resolutions", "secret-identifier resolutions zero"),
    (
        "records zero credential retrievals by the attempt",
        "credential retrievals by this attempt zero",
    ),
    (
        "records zero application-level provider fetches",
        "application-level provider fetches zero",
    ),
    (
        "keeps the underlying AWS/network total unknown",
        "underlying aws/network interactions unknown",
    ),
    (
        "keeps the identity gate own STS command invocation unknown",
        "sts command invocation is unknown because real pre-sts refusal paths exist",
    ),
    (
        "leaves the cause of the refusal undiagnosed and uninferred",
        "cause of the refusal was not diagnosed and is not inferred",
    ),
    (
        "keeps the binding-preflight count at five",
        "binding-preflight attempts remain five",
    ),
    (
        "refuses a third attempt, a diagnosis and an SSO refresh",
        "a third authenticated attempt, further aws identity diagnosis and another sso "
        "refresh or login are each not authorized",
    ),
    ("names the implemented entry point", "scripts/sharadar_authenticated_qualification.py"),
    ("states the entry point refuses by default", "refuses by default"),
    (
        "counts exactly one implemented entry point",
        "authenticated entry points implemented one",
    ),
    ("records the composition root as extended, not duplicated", "extended, not duplicated"),
    (
        "records exactly one ADR-0017 production caller of execute",
        "exactly one adr-0017 production caller",
    ),
    (
        "records the two production call sites overall",
        "exactly two production call sites overall",
    ),
    (
        "records that the second caller does not reach ADR-0017",
        "does not alter, broaden or become reachable from adr-0017",
    ),
    ("states that implementing is not permission to use", "not permission to use it"),
    (
        "keeps a third execution separately gated and unauthorized",
        "a third execution of the surface remains separately gated and not authorized",
    ),
    (
        "keeps implementation, execution and empirical qualification distinct",
        "three distinct gates",
    ),
    ("preserves one request = one durable acquisition", "one request = one durable acquisition"),
    ("preserves the opaque-payload boundary", "opaque-payload boundary"),
    ("introduces no parser", "no parser introduced"),
    ("declares the qualification acquisition mode", "acquisitionmode.qualification"),
    ("introduces no fourth acquisition mode", "no fourth mode"),
    ("locks one provider request", "one provider request"),
    ("forbids pagination", "no pagination"),
    ("forbids automatic retry", "no automatic retry"),
    ("locks the seven-day trailing window", "seven-day trailing window"),
    (
        "keeps evidence in the licensed private Bronze data plane",
        "licensed private bronze data plane",
    ),
    ("records three durable artifacts", "three durable artifacts"),
    ("records exactly three PutObject operations", "exactly three putobject operations"),
    (
        "records the conditional HeadObject bound",
        "zero-to-three conditional headobject metadata checks only after 412",
    ),
    ("records zero object-byte reads", "zero object-byte reads"),
    ("records zero .runtime/ writes", "zero `.runtime/` writes"),
    ("invents no extra qualification report", "no extra qualification report"),
    ("performs no CONTROL publication", "no control publication"),
    ("keeps provider-wide authentication unknown", "provider-wide authentication unknown"),
    ("records zero qualification S3 operations", "s3 qualification operations zero"),
    ("records zero Terraform command invocations", "terraform command invocations zero"),
    (
        "records zero runtime executions against real services",
        "qualification-runtime executions against real services zero",
    ),
    (
        "leaves the credential retrievals established by count at one",
        "credential retrievals established by count remain one",
    ),
    (
        "keeps the empirical qualification separate",
        "empirical qualification remains separate and unexecuted",
    ),
    ("selects no provider", "no provider is selected"),
    ("keeps G1 and G2 open", "g1 and g2 stay open"),
)

#: What the ADR-0017 **narrative section** must carry, checked inside that section.
#:
#: The other half of the same rule. Two of these name a script beside the label
#: that identifies it, because "public-test-token" appearing somewhere in a long
#: document does not establish that the harness is still described as one -- a
#: negative control proved a document-wide scan passes while the table cell says
#: the harness is the authenticated runner.
ADR_0017_SECTION_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    ("records ADR-0017 as accepted and in force", "accepted / in force"),
    ("names the pull request that accepted it", f"pr {ADR_0017_PR} merged"),
    ("names the merge commit", ADR_0017_MERGE_COMMIT),
    ("names the approved ADR head", ADR_0017_APPROVED_HEAD),
    (
        "records the entry point as implemented, attempted twice, refused then completed",
        "implemented, attempted twice \u2014 refused, then completed",
    ),
    ("names the implemented entry point", "scripts/sharadar_authenticated_qualification.py"),
    ("states the entry point refuses by default", "refuses by default"),
    ("records the composition root as extended, not duplicated", "extended, not duplicated"),
    (
        "records exactly one ADR-0017 production caller of execute",
        "exactly one adr-0017 production caller",
    ),
    (
        "records the two production call sites overall",
        "exactly two production call sites overall",
    ),
    (
        "records that the second caller does not reach ADR-0017",
        "does not alter, broaden or become reachable from adr-0017",
    ),
    (
        "states that implementing a surface was not permission to use it",
        "implementing an operator surface was not permission to use it",
    ),
    (
        "states that one refused attempt is not permission for a second",
        "one refused attempt is not permission to make a second",
    ),
    (
        "keeps a third execution separately gated and unauthorized",
        "a third execution of the surface is separately gated and not authorized",
    ),
    ("names the closed outcome of the one attempt", "refused_identity"),
    ("names its exit code", "exit code `6`"),
    ("names the stage it refused at", "stage 5, the existing aws identity gate"),
    (
        "states what the attempt did not establish",
        "it establishes nothing about the secret identifier",
    ),
    (
        "refuses to infer a cause from the refusal",
        "the cause was not diagnosed, and is not inferred here",
    ),
    (
        "records the identity gate own STS invocation as unknown, with the reason",
        "because a real pre-sts refusal path exists, the sts command invocation for this "
        "attempt is recorded as unknown",
    ),
    (
        "states no STS network-request count",
        "no sts network-request count is stated, and underlying aws network interactions "
        "stay unknown",
    ),
    (
        "keeps both attempts distinct from a binding preflight",
        "neither attempt is a sixth binding-preflight attempt",
    ),
    (
        "refuses a third attempt, a diagnosis and an SSO refresh together",
        "a third authenticated qualification attempt is not authorized · further aws "
        "identity diagnosis is not authorized · another aws sso refresh or login is not "
        "authorized",
    ),
    (
        "states that a refusal is not permission to try again",
        "a refusal is a completed result, not permission to repair and try again",
    ),
    (
        "keeps the implementation and execution gates uncollapsed",
        "never collapsed into one",
    ),
    ("preserves one request = one durable acquisition", "one request = one durable acquisition"),
    ("preserves the opaque-payload boundary", "opaque-payload boundary"),
    ("introduces no parser anywhere in the path", "no parser was introduced"),
    ("declares the qualification acquisition mode", "acquisitionmode.qualification"),
    ("introduces no fourth acquisition mode", "no fourth mode introduced"),
    ("performs no CONTROL publication", "control publication stays zero and forbidden"),
    (
        "preserves the architecture rather than reinterpreting it",
        "preserved by the implementation, not reinterpreted",
    ),
    (
        "names the public-test-token harness beside its script",
        "sharadar_private_qualification.py` | the public-test-token",
    ),
    (
        "names the binding preflight beside its offline termination",
        "sharadar_binding_preflight.py` | the offline binding/composition preflight "
        f"{EM_DASH} terminates at",
    ),
    (
        "keeps the empirical qualification separate",
        "empirical qualification remains separate and unexecuted",
    ),
    ("keeps G1 and G2 open where it resolves nothing", "g1 open · g2 open · g3"),
    ("keeps the remaining gates open", f"g4{EN_DASH}g7 open"),
)

#: What the entry point's own comments and docstrings must carry about the one
#: attempt that has been made.
#:
#: The script is the surface an operator reads before running anything, so a
#: status that is current in two markdown files and stale in the module docstring
#: is the version most likely to mislead the person at the keyboard.
#:
#: Matched against the source with whitespace collapsed and case folded, so a
#: docstring rewrapped across lines -- which is what black or a hand edit does to
#: a long sentence -- cannot slip a claim past the guard.
ADR_0017_ENTRY_POINT_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    (
        "records that it has been attempted twice, refused then completed",
        "it has been attempted exactly twice: the first refused and the second completed",
    ),
    ("names the closed outcome", "refused_identity"),
    ("names the exit code", "the exit code was ``6``"),
    (
        "leaves the cause of the refusal undiagnosed",
        "why the gate refused was not diagnosed and remains unknown",
    ),
    (
        "counts two attempts, one refused with its stage and one completed",
        "authorized attempts two one refused, one completed",
    ),
    (
        "counts one refused identity-gate invocation",
        "aws identity-gate invocations: one, refused",
    ),
    ("counts zero credential retrievals", "credential retrievals: zero"),
    ("keeps provider-wide authentication unknown", "provider-wide authentication: unknown"),
    (
        "keeps the underlying AWS network total unknown",
        "underlying aws network interactions: unknown -- no count is established",
    ),
    (
        "refuses a third attempt, a diagnosis and an SSO refresh",
        "a third attempt · aws identity diagnosis · sso refresh: not authorized",
    ),
    (
        "states what attempt one established of what a completed run would",
        "attempt one established none of that",
    ),
    (
        "records that main has been run exactly twice",
        "this function has been run exactly twice",
    ),
    (
        "bounds attempt two's S3 qualification operations from the closed token",
        "exactly three putobject invocations, zero to three conditional headobject "
        "invocations, and three to six s3 qualification operations in total",
    ),
    (
        "keeps the newly-written object count unestablished",
        "newly written is not established",
    ),
    (
        "separates exact-request from provider-wide authentication",
        "exact-request authentication: established",
    ),
    (
        "refuses to read a completed command as a verdict",
        "``completed`` is a command status, not a verdict",
    ),
)

#: Claims the entry point's own text may no longer make.
#:
#: Each was true and required while the surface was unexecuted. Deleting the
#: requirement without inverting it would leave the reverted claim unguarded.
ADR_0017_ENTRY_POINT_FORBIDDEN: Final[tuple[str, ...]] = (
    "it has never been run.",
    "this function has never been run",
    "the entry point has never been run",
    "authorized attempts zero",
    "authenticated qualification attempts zero",
    "this slice never calls it with real ones",
)

#: What ADR-0017's own text must carry. The status documents summarise it; this
#: is the decision record itself, and a summary that outlives its source is how a
#: governance document starts asserting something nothing decided.
ADR_0017_SELF_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    (
        "ADR-0017 uses the accepted proposed-until-merge convention",
        "accepted — effective on the merge of the pull request that introduces this adr",
    ),
    (
        "ADR-0017 states it carries no authority before that merge",
        "until that merge it is proposed and carries no authority",
    ),
    ("ADR-0017 supersedes nothing", "supersedes: nothing"),
    ("ADR-0017 preserves one request is one acquisition", "one request is one acquisition"),
    ("ADR-0017 preserves byte-for-byte publication", "byte for byte"),
    ("ADR-0017 preserves the opaque-payload boundary", "never parsed"),
    ("ADR-0017 declares the qualification mode", "acquisitionmode.qualification"),
    ("ADR-0017 rejects a fourth acquisition mode", "a fourth acquisition mode for a"),
    ("ADR-0017 rejects a zero-persistence probe", "zero-persistence authenticated probe"),
    (
        "ADR-0017 rejects reusing the public-test-token harness",
        "public-test-token harness as the authenticated runner",
    ),
    ("ADR-0017 rejects reusing the binding preflight", "binding preflight as the runner"),
    (
        "ADR-0017 rejects parsing at the provider boundary",
        "parsing the payload at the provider boundary",
    ),
    ("ADR-0017 rejects a second composition root", "separate composition root for execution"),
    ("ADR-0017 decides the date window", "seven-calendar-day trailing window"),
    ("ADR-0017 states the exact publication write count", "exactly three"),
    ("ADR-0017 surfaces the collision head path rather than rounding it away", "zero to three"),
    ("ADR-0017 refuses control publication", "control bucket operations zero"),
    ("ADR-0017 keeps the authorization sequence intact", "skips no step"),
    ("ADR-0017 authorizes implementation only", "it does not authorize execution"),
    ("ADR-0017 keeps Q7 unresolved", "publicly_unresolved"),
    (
        "ADR-0017 locks exactly three CLI arguments",
        "--i-am-the-operator-authorizing-authenticated-qualification",
    ),
)

#: What the entry point's own status test must assert, and what it may not.
#:
#: The superseded test asserted only that the module docstring contained the
#: substring ``never been run``. That was true and required while the surface was
#: unexecuted, and it kept passing after the surface was invoked -- any sentence
#: carrying those three words satisfied it, including a true one about a
#: different subject. A denylist over the documents cannot catch that, because
#: the weakness was in a test rather than in prose.
ADR_0017_STATUS_TEST_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    (
        "names the corrected status test",
        "def test_the_module_records_one_refused_attempt_and_one_completed_attempt",
    ),
    (
        "asserts two invocations, refused then completed",
        "it has been attempted exactly twice: the first refused and the second completed",
    ),
    ("asserts the stage it refused at", '"refused at stage 5"'),
    ("asserts the closed outcome", "the closed outcome was ``refused_identity``"),
    ("asserts the exit code", "the exit code was ``6``"),
    ("asserts the runtime was reached by attempt two", "the qualification runtime was reached"),
    ("asserts that attempt two completed", '"the second attempt completed"'),
    (
        "asserts a completed command status is not a verdict",
        "``completed`` is a command status, not a verdict",
    ),
    ("asserts one provider request", '"one provider request was made"'),
    ("asserts attempt one published nothing", "s3 qualification operations: zero"),
    (
        "asserts attempt two's exact PutObject count",
        "attempt two -- putobject invocations: exactly three",
    ),
    (
        "asserts attempt two's conditional HeadObject bound",
        "attempt two -- conditional headobject invocations: zero to three",
    ),
    (
        "asserts attempt two's total S3 operation bound",
        "attempt two -- s3 qualification operations: three to six",
    ),
    (
        "asserts the newly-written count stays unestablished",
        "attempt two -- newly written objects: not established",
    ),
    (
        "asserts exact-request authentication is established",
        "exact-request authentication: established",
    ),
    (
        "asserts provider-wide authentication stays unknown",
        "provider-wide authentication: unknown",
    ),
    (
        "asserts a third attempt is unauthorized",
        "a third attempt · aws identity diagnosis · sso refresh: not authorized",
    ),
    ("refuses the never-invoked claim", '"the entry point was never invoked"'),
    ("folds whitespace so a rewrap cannot evade it", "def _folded("),
    ("scopes the function docstring it reads", "def _function_docstring("),
)

#: The superseded assertion, which may not come back.
ADR_0017_STATUS_TEST_FORBIDDEN: Final[tuple[str, ...]] = (
    "def test_the_module_states_that_completion_authorizes_no_second_run",
    "def test_the_module_records_one_refused_attempt_and_no_completed_acquisition",
    'assert "never been run" in doc',
    'assert "never been run" in module_doc',
)

#: The three CLI arguments the future surface may carry, and no others.
#:
#: Written here so a later slice that adds a fourth has to change this tuple in
#: front of a reviewer, rather than only the script nobody re-reads.
ADR_0017_CLI: Final[tuple[str, ...]] = (
    "--i-am-the-operator-authorizing-authenticated-qualification",
    "--subject",
    "--execution-id",
)

#: CLI spellings ADR-0017 forbids the future surface from ever exposing.
#: 16 forbidden CLI spellings are listed here, and that number is checked
#: against ``len()`` for the same reason the claim list is.
ADR_0017_FORBIDDEN_CLI: Final[tuple[str, ...]] = (
    "--run",
    "--live",
    "--force",
    "--secret-id",
    "--api-key",
    "--dataset",
    "--table",
    "--endpoint",
    "--bucket",
    "--full-history",
    "--bulk",
    "--page",
    "--page-size",
    "--limit",
    "--retry",
    "--retries",
)


# ---------------------------------------------------------------------------
# ADR-0018 -- an ACCEPTED architecture, and the facts a status document must keep
# ---------------------------------------------------------------------------

#: The ADR this section governs. **Accepted on the merge of PR #39**, and
#: therefore registered in :data:`MERGED_ADR_STATUS` like every other in-force
#: ADR. The guards below were written while it was proposed and are *inverted*
#: rather than deleted: what they used to require is now false, and deleting
#: them would leave the reverted claim unguarded. What merging did **not** do
#: is the half that still needs guarding -- an ADR that approves an
#: architecture and a status document that reads it as permission to build,
#: mutate infrastructure or run is exactly the drift this audit exists to
#: catch, and it has happened before.
ADR_0018: Final = DECISIONS / ("ADR-0018-bounded-private-empirical-sharadar-qualification.md")

#: The pull request whose merge satisfied ADR-0018's conditional acceptance.
ADR_0018_PR: Final = "#39"

#: The pull request whose merge satisfied the clarification amendment's own
#: conditional effectiveness, its merge commit and the approved clarification
#: head. Pinned the way ADR-0017's acceptance commits are pinned: a merge
#: recorded only as a number is a merge nobody can check against the history
#: that produced it, and the amendment's status line is conditional on exactly
#: this one.
ADR_0018_CLARIFICATION_PR: Final = "#42"
ADR_0018_CLARIFICATION_MERGE_COMMIT: Final = "28239514b9e4e13f55ee98fa50877077e70bd593"
ADR_0018_CLARIFICATION_APPROVED_HEAD: Final = "579259a62ff7561ae2991f3923ea8aa1d0064be8"

#: The pull request that merged the ADR-0018 offline implementation, its merge
#: commit and the approved implementation head. Merging an implementation is
#: crossing the **first** of three gates -- it is not infrastructure deployment
#: and it is not execution -- so the status guards below require the merge and
#: the two uncrossed gates in the same breath.
ADR_0018_IMPL_PR: Final = "#41"
ADR_0018_IMPL_MERGE_COMMIT: Final = "3ddd7d40741bb9a50ae4fc5452324ddbfb5e1ec0"
ADR_0018_IMPL_APPROVED_HEAD: Final = "96daac7963d936f231b37847579c5f28bb313760"

#: The pull request that merged the fixed 48-request assessment-boundary
#: correction, its merge commit and the approved correction head. A **separate**
#: merge event, pinned separately: PR #41 merged before this correction existed,
#: and a document that read one through the other would be claiming the
#: implementation had passed a review that had not happened yet.
ADR_0018_FIX_PR: Final = "#44"
ADR_0018_FIX_MERGE_COMMIT: Final = "c945970613b80bfd4f42acc4f3acb4814895eb42"
ADR_0018_FIX_APPROVED_HEAD: Final = "78b4425077e65eeb12dfd24b35825741370e0e0f"

#: The two entry points ADR-0018 designs, now built as an **offline
#: implementation candidate**. Their presence is what crossing the implementation
#: gate looks like, and it is checked rather than described.
ADR_0018_ACQUIRE_ENTRY: Final = REPO_ROOT / "scripts" / "sharadar_empirical_qualification.py"
ADR_0018_ASSESS_ENTRY: Final = REPO_ROOT / "scripts" / "sharadar_qualification_assessment.py"

#: The parser/evaluator package, deliberately outside ``data/ingest/`` so the
#: acquisition path stays parser-free.
ADR_0018_QUALIFY_PACKAGE: Final = REPO_ROOT / "src" / "kalpamani" / "data" / "qualify"
ADR_0018_QUALIFY_SHARADAR: Final = ADR_0018_QUALIFY_PACKAGE / "sharadar"
ADR_0018_ACQUISITION: Final = ADR_0018_QUALIFY_SHARADAR / "acquisition.py"
ADR_0018_ASSESSMENT: Final = ADR_0018_QUALIFY_SHARADAR / "assessment.py"
ADR_0018_INGEST_PACKAGE: Final = REPO_ROOT / "src" / "kalpamani" / "data" / "ingest"

#: The dedicated offline suites for the implementation candidate. Executable
#: invariants belong in unit tests, and this audit must not stand in for them.
ADR_0018_TEST_SUITES: Final[tuple[Path, ...]] = tuple(
    REPO_ROOT / "tests" / "unit" / name
    for name in (
        "test_sharadar_empirical_inventory.py",
        "test_sharadar_empirical_plan.py",
        "test_sharadar_empirical_locator.py",
        "test_sharadar_empirical_operations.py",
        "test_sharadar_empirical_read.py",
        "test_sharadar_empirical_parser.py",
        "test_sharadar_empirical_evaluator.py",
        "test_sharadar_empirical_report.py",
        "test_sharadar_empirical_pipeline.py",
        "test_sharadar_empirical_entry_points.py",
        "test_sharadar_qualification_package_boundaries.py",
    )
)

#: The modules permitted to construct the shared licensed store. **One** named
#: module, so a **second** still fails: a count could drift, a list cannot.
#:
#: ``acquisition.py`` was the second until ADR-0019 made the empirical acquisition
#: path write-only: the shared store resolves a ``412`` with a ``HeadObject``, which
#: AWS maps onto ``s3:GetObject``, so that path publishes through its own write-only
#: surface now. Narrowing, not relaxing -- a second module here fails again.
STORE_BUILDERS: Final[tuple[str, ...]] = ("composition.py",)

#: The modules permitted to call ``QualificationRuntime.execute`` in production.
#:
#: **Two named modules, so a third fails.** A count could drift; a list cannot.
#:
#: ``composition.py`` is ADR-0017's accepted path and is unchanged. ``acquisition.py``
#: is the dormant ADR-0018 / ADR-0019 / ADR-0020 empirical acquisition path, merged
#: by PR #48. The second is not reachable from the first, and neither reaches the
#: assessment read surface -- both properties are checked rather than described.
#:
#: The standing "exactly ONE production caller" claim was true of the repository
#: until that path merged, and is now scoped to ADR-0017 in both status documents.
RUNTIME_EXECUTE_CALLERS: Final[tuple[str, ...]] = ("acquisition.py", "composition.py")

#: The two operator authorization flags. Different by construction, so neither
#: authorization can be given by pasting the other one.
ACQUIRE_FLAG: Final = "--i-am-the-operator-authorizing-empirical-acquisition"
ASSESS_FLAG: Final = "--i-am-the-operator-authorizing-qualification-assessment"

#: Options the acquisition entry point refuses by name. Each would either widen the
#: retrieval or put private evaluation information into a process listing.
ADR_0018_ACQUIRE_REFUSED: Final[tuple[tuple[str, str], ...]] = (
    ("a subject", "--subject"),
    ("a subject list", "--subjects"),
    ("an inventory path", "--inventory"),
    ("a dataset selector", "--dataset"),
    ("a window", "--window"),
    ("a page count", "--page"),
    ("a retry", "--retry"),
    ("a bulk retrieval", "--bulk"),
    ("a credential", "--api-key"),
    ("a bucket", "--bucket"),
)

#: Options the assessment entry point refuses by name. Each would either search the
#: store or emit a finding, and neither exists anywhere in this architecture.
ADR_0018_ASSESS_REFUSED: Final[tuple[tuple[str, str], ...]] = (
    ("a listing", "--list"),
    ("a prefix scan", "--prefix"),
    ("a report path", "--output"),
    ("a printed report", "--print-report"),
    ("a verdict", "--verdict"),
    ("a provider selection", "--select-provider"),
)


#: Every file permitted to construct an AWS SDK client. All four are operator
#: entry points under ``scripts/`` that refuse by default; no module under
#: ``src/`` appears here, which is what keeps the data platform free of ambient
#: credential discovery.
SDK_CONSTRUCTORS: Final[tuple[str, ...]] = (
    "sharadar_authenticated_qualification.py",
    "sharadar_binding_preflight.py",
    "sharadar_empirical_qualification.py",
    "sharadar_qualification_assessment.py",
)

#: What ADR-0018 must say about itself, matched with emphasis removed and
#: whitespace collapsed so a rewrap cannot hide a sentence.
#:
#: The first three are the whole governance of the slice: a conditional status, a
#: statement that the condition has not been met, and a supersession claim of
#: nothing. The rest pin the numbers, because an arithmetic nobody checks is an
#: arithmetic that drifts on the next edit.
ADR_0018_SELF_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    (
        "carries the exact conditional acceptance status",
        "status: accepted — effective only upon merge of the pull request introducing this adr.",
    ),
    (
        "keeps the pre-merge condition exactly as written",
        "before that merge this adr is proposed and carries no authority.",
    ),
    ("records that the merge condition has since been met", "that merge has since occurred"),
    ("supersedes nothing", "supersedes: nothing."),
    ("approves an architecture and not code", "merging this adr approves an architecture"),
    # The multiplication sign and the dashes below are the document's own
    # characters. A guard spelled with ASCII look-alikes would match nothing,
    # so the ambiguity rule is suppressed per line rather than disabled.
    ("states the request arithmetic", "48 = 8 subjects × 3 datasets × 2 pages"),  # noqa: RUF001
    ("states that provider retries are zero", "`max_attempts = 1` — zero provider retries"),
    ("states the maximum putobject count", "maximum total `putobject` | 147"),
    ("bounds the locator retry at two", "may be retried at most twice"),
    (
        "bounds headobject by the completed requests, not by the writes",
        "head_object_count <= 3 * completed_requests + 1",
    ),
    (
        "states the maximum headobject count",
        "for a complete 48-request run that bound is `head_object_count <= 145`",
    ),
    (
        "states that only one attempt can reach the metadata resolution",
        "at most one locator attempt can ever reach the `412` metadata-resolution path",
    ),
    ("states the maximum per-run s3 total", "maximum total s3 operations | 147 to 292"),
    ("states the maximum two-run s3 total", "294 to 584"),
    (
        "forbids retry after ambiguity",
        "no retry may follow an ambiguous or unclassified result.",
    ),
    ("states the combined assessment read formula", "`e × (2r + 1)` | 194"),  # noqa: RUF001
    (
        "states that claims are not retrieved",
        "acquisition claims are validated structurally from the locator and are not retrieved.",
    ),
    ("requires two separated runs", "two, at least eight calendar days apart"),
    ("uses one locator per execution", "one locator per execution, not per request."),
    (
        "fails closed on a bad locator",
        "a missing, collided, ambiguous or unverified locator fails closed.",
    ),
    # ---------------------------------------------- the clarification amendment
    #
    # Gap A: the accepted text called 1,800 seconds a wall-clock ceiling and
    # derived it from the provider-time component alone, so it never said whether
    # local work, Bronze publication, metadata resolution, locator construction or
    # locator retry fall inside it. A number with no scope is a compile-time
    # assertion, and an implementation candidate reproduced exactly that. Each
    # guard below pins one clause of the scope, the clock, the enforcement points
    # or the refusal, because a deadline stated only in summary is a deadline the
    # next edit can quietly narrow.
    (
        "states that the deadline is actual elapsed time",
        "the 1,800-second ceiling is one actual elapsed-time deadline, and not compile-time "
        "arithmetic.",
    ),
    (
        "measures the deadline on an injected monotonic clock",
        "measured on an injected monotonic clock.",
    ),
    (
        "refuses calendar time for deadline arithmetic",
        "wall-clock calendar time must never be used for deadline arithmetic",
    ),
    (
        "starts the deadline at acquisition stage 11",
        "starts immediately before the first provider request, at acquisition stage 11",
    ),
    (
        "ends the deadline at acquisition stage 13",
        "ends only when acquisition reaches a terminal locator result, at acquisition stage 13",
    ),
    (
        "puts bronze publication inside the deadline",
        "three bronze publications per completed request",
    ),
    ("puts locator work inside the deadline", "locator publication permitted locator retry"),
    (
        "puts the pre-execution gates outside the deadline",
        "gates that happen before acquisition execution begins",
    ),
    (
        "starts no operation on hope",
        "no operation may be started merely in the hope that it completes before it",
    ),
    ("halts rather than overrunning", "the run halts before starting another provider request."),
    ("never shortens pacing to fit", "pacing is never silently shortened."),
    (
        "does not count an unpersisted response",
        "an unpersisted response | is not a completed request.",
    ),
    ("never claims a locator it did not write", "it must not claim a locator exists"),
    (
        "closes and sanitizes deadline exhaustion",
        "deadline exhaustion is a closed, sanitized status",
    ),
    (
        "keeps a timing trace out of public output",
        "no exception text, private identifier, key, subject, digest, vendor row or timing trace",
    ),
    (
        "grants nothing on deadline exhaustion",
        "deadline exhaustion never authorizes a retry, a resume or a new execution identity.",
    ),
    ("disables sdk retries for qualification writes", "disabled for qualification s3 calls."),
    ("forbids an adaptive or hidden retry mode", "adaptive or hidden retry mode | forbidden"),
    ("bounds the connect timeout explicitly", "connect timeout | explicit and bounded"),
    ("bounds the read timeout explicitly", "read timeout | explicit and bounded"),
    ("keeps the application-level locator retry the only one", "is the only locator retry"),
    ("proves the reserved locator-terminal budget", "cover `4 * t_s3 + c`"),
    (
        "refuses configuration that cannot fit",
        "configuration that cannot fit is refused, not clamped.",
    ),
    (
        "admits a request only with its whole downstream budget",
        "remaining >= t_req + 6 * t_s3 + l",
    ),
    (
        "leaves the sub-budget values to the correction review",
        "required implementation constant whose proposed numerical value must be reviewed with "
        "the correction pull request",
    ),
    ("does not raise the ceiling", "raising it is an adr change"),
    (
        "states that the deadline guarantees no completion",
        "the 1,800-second deadline is therefore a safety bound on elapsed time, and not a "
        "guarantee that 48 requests complete.",
    ),
    # Gap B: P1's TESTED ceiling is a cross-run question, and the accepted
    # arithmetic covered one 48-request locator. A single-execution assessor
    # cannot compare two observations, so the guards below pin the combined
    # protocol, its pair preconditions, its arithmetic and its honest ceilings.
    (
        "assesses both runs together",
        "one combined private assessment evaluates run a and run b together",
    ),
    ("requires two distinct execution identities", "two distinct execution identities."),
    (
        "requires the eight-day separation at assessment",
        "at least eight calendar days between the accepted run dates",
    ),
    (
        "validates the pair before reading a payload",
        "before any acquisition record or payload is read.",
    ),
    ("resolves both locators without listing", "both locator keys are resolved without listing"),
    ("reads every acquisition record and payload", "`e × r` | 96"),  # noqa: RUF001
    ("retrieves no acquisition claim", "acquisition-claim `getobject` | `0` | 0"),
    ("bounds a refused pair at two locator reads", "locator `getobject` | 0 to 2"),
    ("reports observed counts, not nominal ones", "never report nominal counts as observed counts"),
    ("states the whole-package envelope", "`485 = 290 + 195` and `780 = 584 + 196`"),
    (
        "binds the report key to three validated segments",
        "three separately validated path segments",
    ),
    ("forbids one execution identity twice", "forbids identical execution identities"),
    (
        "keeps every verdict out of the combined report",
        "no aggregate verdict, no provider-selection value, no readiness value and no operational "
        "recommendation",
    ),
    (
        "caps run a alone at partially tested",
        "run a evidence alone has a p1 ceiling of `partially_tested`",
    ),
    (
        "keeps information time bounded even at tested",
        "the information-time limitation remains explicitly bounded even when p1 reaches `tested`.",
    ),
    ("refuses a weaker pass on thin cross-run evidence", "never becomes a weaker pass."),
    (
        "allows p1 to stay partial after run b",
        "p1 may remain `partially_tested` or insufficient after run b",
    ),
    ("treats tested as a ceiling", "`tested` is a ceiling, not an expected outcome."),
    (
        "keeps p1 out of the gate decisions",
        "no p1 result is an aggregate provider verdict, and no p1 result is a g1 or g2 decision.",
    ),
    # The amendment's own governance. It is conditional in exactly the way the
    # ADR itself was, it names the review outcome that produced it, and it opens
    # no gate -- least of all the one in front of the implementation candidate.
    (
        "carries the conditional amendment status",
        "status of this amendment: proposed — effective only upon merge of the pull request "
        "introducing it.",
    ),
    # The post-merge half, added when PR #42 merged. The conditional status line
    # above is immutable -- it is what the merge satisfied -- so the merge is
    # recorded beside it rather than by rewriting it, exactly as the ADR's own
    # acceptance was recorded beside its conditional line when PR #39 merged.
    (
        "records that the amendment's own merge has since occurred",
        "the clarification's own merge has since occurred",
    ),
    ("names the clarification merge commit", ADR_0018_CLARIFICATION_MERGE_COMMIT),
    ("names the approved clarification head", ADR_0018_CLARIFICATION_APPROVED_HEAD),
    (
        "records that the conditional effectiveness event has occurred",
        "the conditional effectiveness event has occurred",
    ),
    (
        "keeps the pre-merge fact that the amendment carried no authority",
        f"while pr {ADR_0018_CLARIFICATION_PR} was open the clarification was proposed and "
        "carried no authority",
    ),
    (
        "records that the merge approved clarification of architecture only",
        "the merge approved clarification of architecture only",
    ),
    (
        "keeps the candidate blocked against the now-authoritative clarification",
        "the offline implementation candidate must be corrected against the now-authoritative "
        "clarification",
    ),
    ("records the blocking review outcome", "`blocked_adr_clarification_required`"),
    (
        "keeps the implementation candidate blocked",
        "the offline implementation candidate cannot be merged until it is corrected against "
        "this clarification",
    ),
    ("opens none of the later gates", "this clarification authorizes none of the later gates."),
    (
        "sequences one combined assessment after run b",
        "one owner-only combined run a / run b assessment",
    ),
    ("leaves the deletion role alone", "the deletion role is unchanged."),
    # ------------------------------- the adjacent historical implementation note
    #
    # §14.2 records the state this ADR left behind on the day it was accepted, and
    # a decision record is not rewritten when the world moves -- so §14.2 keeps its
    # present tense and the note beside it is what stops that present tense from
    # being read as current. Required rather than optional, because an unlabelled
    # stale §14.2 is exactly the drift the status guards catch one file over.
    (
        "carries the adjacent historical implementation note",
        "this subsection is a historical note added after the decision above",
    ),
    ("names the implementation merge commit", ADR_0018_IMPL_MERGE_COMMIT),
    ("names the approved implementation head", ADR_0018_IMPL_APPROVED_HEAD),
    ("names the correction merge commit", ADR_0018_FIX_MERGE_COMMIT),
    ("names the approved correction head", ADR_0018_FIX_APPROVED_HEAD),
    (
        "keeps the two merge events separate in the note",
        f"pr {ADR_0018_IMPL_PR} is not described as having passed that later review",
    ),
)

#: Claims ADR-0018 must never make. Each is false today, and each is the shape a
#: later edit would take if the slice quietly became an authorization.
#:
#: Every phrase is chosen so it cannot appear inside a *negation* of itself --
#: "authorizes no implementation" does not contain "authorizes implementation" --
#: because a denylist that fires on an honest sentence gets deleted rather than
#: fixed.
ADR_0018_SELF_FORBIDDEN: Final[tuple[str, ...]] = (
    "authorizes implementation",
    "authorizes execution",
    "authorizes a provider request",
    "g1 closed",
    "g2 closed",
    "putobject is always exactly 145",
    # The superseded HeadObject arithmetic. 147 HEADs is a count no run can
    # produce: the extra PutObject invocations a locator retry buys are exactly
    # the ones that send none, so a bound derived from the write count admits
    # operations that cannot happen.
    "zero to 147",
    "147 to 294",
    "294 to 588",
    # The superseded single-execution assessment arithmetic, in the exact
    # canonical shapes the ADR used before the clarification. The historical note
    # still names the old numbers in prose -- deliberately, because explaining
    # what changed needs them -- so each entry below is a *table-row* spelling
    # that only a reverted canonical claim can produce.
    "total `getobject` | `2r + 1` | 97",
    "`2r + 2` to `2r + 3` | 98 to 99",
    "assessment s3 operations, both runs | 196 to 198",
    "for a `complete` locator over",
    # The superseded ceiling row, and the shape a reintroduced hidden retry would
    # take. "disabled" does not contain "enabled", and an honest negation reads
    # "are not enabled", so neither fires on a correct document.
    "wall-clock ceiling | 1,800 seconds",
    "sdk automatic retries enabled",
)

#: Spellings that would mean a concrete subject symbol had been written down.
#:
#: The subject list is evaluation information under the personal-use licence, so
#: it lives in a git-ignored owner-only input and never in a tracked file. A
#: symbol canary cannot be a regex over capital letters -- "ADR", "CSV", "UTC"
#: and "MiB" would all match -- so this guards the *shapes that carry one*
#: instead: a locked-subject constant, a subject command-line option, and a
#: subject tuple literal.
ADR_0018_SUBJECT_CARRIERS: Final[tuple[str, ...]] = (
    "locked_subject",
    "--subject",
    "subjects = (",
    "subjects=(",
)

#: What **both** status documents must independently say about ADR-0018.
#:
#: Independently, and for the reason the ADR-0017 block gives: merged main has
#: twice carried a fact in one document and a stale contradiction in the other,
#: so each phrase is required in *each* file rather than in their concatenation.
ADR_0018_STATUS_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    ("records it as accepted and in force", "adr-0018: accepted / in force"),
    ("records that the merge approved architecture only", "the merge approved architecture only"),
    (
        "records that the merge authorized nothing further",
        "the merge authorized no implementation, no infrastructure mutation and no execution",
    ),
    # The historical half. Acceptance is a fact about now; it does not
    # retroactively give the document authority it did not have while its pull
    # request was open, and a status file that quietly rewrote that would be
    # asserting an authority nobody granted.
    (
        "keeps the pre-merge fact that it carried no authority",
        f"while pr {ADR_0018_PR} was open it was proposed and carried no authority",
    ),
    # The six distinctions an accepted architecture has to keep apart. Approving
    # a design is not permission to write it, to provision for it or to run it,
    # and each of those is separately checkable, so each is separately required.
    # Inverted on the merge of PR #41, not deleted. What this required while the
    # implementation sat on an open pull request is false now, and deleting it
    # would leave the reverted claim unguarded -- the same treatment every ADR-0018
    # acceptance guard in this file was given when PR #39 merged.
    (
        "records the merged, dormant offline implementation",
        "the offline implementation is merged, dormant and never executed",
    ),
    (
        "keeps implementation execution unauthorized",
        "adr-0018 implementation execution: not authorized",
    ),
    ("keeps infrastructure mutation unauthorized", "infrastructure mutation: not authorized"),
    ("keeps run a unauthorized", "run a: not authorized"),
    ("keeps run b unauthorized", "run b: not authorized"),
    ("keeps the assessment run unauthorized", "assessment: not authorized"),
    ("records zero package executions", "empirical-package executions zero"),
    ("records zero provider requests", "provider requests by this package zero"),
    ("records zero s3 operations", "s3 operations by this package zero"),
    ("records zero p-test executions", "p1–p9 executions by this package zero"),  # noqa: RUF001
    ("records zero new roles", "new iam roles zero"),
    # The read surface is no longer absent and no longer sitting on an open pull
    # request, so the single sentence that said so is replaced by the eight claims
    # that are actually true of it. Eight entries rather than one: a single
    # sentence covering all of them is a sentence a later edit can soften in place
    # without any guard noticing, and "a reading implementation exists" is exactly
    # the claim that gets rounded up into "private evidence exists".
    (
        "records that the read implementation exists in committed code",
        "the bounded assessment-only read implementation now exists in committed code",
    ),
    ("records that the read implementation is undeployed", "it is dormant and not deployed"),
    ("records that the read implementation cannot list", "it permits no s3 listing"),
    ("records that it is not a general read surface", "it is not a general read surface"),
    (
        "records that the read implementation has never executed",
        "it has never been executed against licensed objects",
    ),
    (
        "records that no retained evidence has been read",
        "no locator, record, payload or report has been read by the empirical package",
    ),
    ("records that acquisition stays write-only", "the acquisition process remains write-only"),
    (
        "records that ingestion cannot reach the read surface",
        "the ordinary ingestion path remains unable to use the qualification read surface",
    ),
    (
        "refuses to read a read implementation as evidence",
        "a reading implementation existing is not private evidence existing",
    ),
    ("records the per-run request count", "48 requests per run"),
    (
        "records that provider retries are forced to zero",
        "zero provider retries — arithmetically forced",
    ),
    ("records the nominal putobject count", "total `putobject` 145"),
    ("records the real observed bound", "144 ≤ `putobject` ≤ 147"),
    # The en-dashes below are the status documents' own characters. A guard
    # spelled with ASCII look-alikes would match nothing, so the ambiguity rule
    # is suppressed per line rather than disabled.
    ("records the maximum headobject count", "conditional `headobject` 0–145"),  # noqa: RUF001
    ("records the maximum per-run s3 total", "total s3 operations 147–292"),  # noqa: RUF001
    ("records the combined assessment read formula", "`e × (2r + 1)` = 194"),  # noqa: RUF001
    (
        "records that adr-0017's accounting is untouched",
        "adr-0017's exactly-three-`putobject` accounting is untouched",
    ),
    ("keeps the third adr-0017 attempt unauthorized", "a third adr-0017 attempt not authorized"),
    # ------------------------------------------- the clarification amendment
    #
    # Both halves of it, in both documents, for the reason every ADR-0018 status
    # phrase is required of each file rather than of their concatenation: merged
    # main has twice carried a fact in one document and a stale contradiction in
    # the other.
    ("records the elapsed-time deadline", "1,800-second acquisition elapsed-time deadline"),
    ("records the injected monotonic clock", "injected monotonic clock"),
    (
        "records that the deadline is not compile-time arithmetic",
        "and not compile-time arithmetic",
    ),
    (
        "records where the deadline starts",
        "starts immediately before the first provider request, at acquisition stage 11",
    ),
    (
        "records where the deadline ends",
        "ends only when acquisition reaches a terminal locator result, at acquisition stage 13",
    ),
    (
        "records that bronze publication is inside the deadline",
        "three bronze publications per completed request",
    ),
    (
        "records that locator work is inside the deadline",
        "locator publication permitted locator retry",
    ),
    (
        "records that the pre-execution gates are outside it",
        "gates that happen before acquisition execution begins",
    ),
    (
        "records that sdk retries are disabled",
        "sdk automatic retries disabled for qualification s3 calls",
    ),
    ("records that hidden retry modes are forbidden", "adaptive or hidden retry mode forbidden"),
    ("records the locator-reserve obligation", "cover `4 * t_s3 + c`"),
    (
        "records that unfittable configuration is refused",
        "configuration that cannot fit is refused, not clamped",
    ),
    (
        "records that the sub-budget values await the correction review",
        "required implementation constant whose proposed numerical value must be reviewed with "
        "the correction pull request",
    ),
    (
        "records that deadline exhaustion authorizes nothing",
        "deadline exhaustion authorizes nothing",
    ),
    (
        "records the combined assessment",
        "one combined private assessment evaluates run a and run b together",
    ),
    ("records the combined read counts", "96 acquisition records and 96 payloads and zero claims"),
    ("records the combined operation total", "195 to 196"),
    ("records the whole-package envelope", "whole empirical package 485 to 780"),
    ("records the combined report path grammar", "three separately validated path segments"),
    (
        "records that run a alone caps p1",
        "run a evidence alone has a p1 ceiling of `partially_tested`",
    ),
    ("records that tested is a ceiling", "`tested` is a ceiling, not an expected outcome"),
    # The amendment's own conditional effectiveness, now satisfied. This guard
    # required the opposite while PR #42 was open and is *inverted* rather than
    # deleted -- the same treatment the ADR-0018 acceptance guards were given on
    # PR #39, and for the same reason: deleting it would leave the reverted claim
    # unguarded. Its pre-merge spelling moves to the forbidden list below, so a
    # revert is caught rather than merely un-asserted.
    (
        "records that the clarification amendment is effective",
        f"the clarification amendment is effective — pr {ADR_0018_CLARIFICATION_PR} merged",
    ),
    ("names the clarification merge commit", ADR_0018_CLARIFICATION_MERGE_COMMIT),
    ("names the approved clarification head", ADR_0018_CLARIFICATION_APPROVED_HEAD),
    (
        "records that the conditional effectiveness event has occurred",
        "the conditional effectiveness event has occurred",
    ),
    # The two decisions the clarification carries, each named as effective. A
    # document that recorded the event without the decisions would record that
    # something happened and not what now governs.
    (
        "records the effective elapsed acquisition deadline clarification",
        "adr-0018's total elapsed acquisition deadline clarification is now effective",
    ),
    (
        "records the effective combined assessment clarification",
        "adr-0018's combined run a / run b assessment clarification is now effective",
    ),
    # The historical half, for the amendment exactly as for the ADR. A merge is
    # not licence to backdate authority onto the days before it.
    (
        "keeps the pre-merge fact that the clarification carried no authority",
        f"while pr {ADR_0018_CLARIFICATION_PR} was open the clarification was proposed and "
        "carried no authority",
    ),
    # And the scope of it. Making a clarification effective changed what the
    # architecture *means*; a status document that read it as permission to
    # build, provision or run is the drift every ADR-0018 guard here exists to
    # catch, one merge later.
    (
        "records that the clarification merge approved clarification of architecture only",
        "the merge approved clarification of architecture only",
    ),
    (
        "records that the clarification merge authorized nothing further",
        "the clarification merge authorized no implementation, no infrastructure mutation and "
        "no execution",
    ),
    # The candidate has since been corrected under a separate authorization, so
    # these three are inverted rather than deleted -- the same treatment every
    # guard in this file gets when the fact it names changes. What must still be
    # recorded is that the candidate is unmerged, that the correction happened,
    # and that a person has yet to review it.
    (
        "records that the candidate was corrected against the now-authoritative clarification",
        "corrected against the now-authoritative clarification",
    ),
    # Both inverted on the merges, not deleted. The re-review the earlier guard
    # was waiting for has since happened, and what it produced is the correction
    # PR #44 merged -- so the guard now requires the outcome rather than the wait.
    (
        "records that the offline implementation merged",
        f"the adr-0018 offline implementation is merged and dormant — pr {ADR_0018_IMPL_PR} merged",
    ),
    ("names the implementation merge commit", ADR_0018_IMPL_MERGE_COMMIT),
    ("names the approved implementation head", ADR_0018_IMPL_APPROVED_HEAD),
    (
        "records what the implementation merge merged",
        f"pr {ADR_0018_IMPL_PR} merged the adr-0018 offline implementation",
    ),
    ("records that the merged implementation is dormant", "the merged implementation is dormant"),
    (
        "records that the implementation merge deployed nothing",
        "the merge did not deploy infrastructure",
    ),
    (
        "records that the implementation merge ran nothing",
        "did not authorize or execute run a, run b or the combined assessment",
    ),
    ("records that the implementation merge closed no gate", "did not close g1 or g2"),
    ("records that the implementation merge selected no provider", "did not select a provider"),
    (
        "records that the implementation merge authorized no live trading",
        "did not authorize live trading",
    ),
    (
        "records that merging an implementation authorized no execution",
        "merging an implementation authorized no execution, no infrastructure deployment and "
        "no run",
    ),
    (
        "records that the independent re-review has since occurred",
        "the independent re-review has since occurred and produced the fixed-count correction "
        f"merged as pr {ADR_0018_FIX_PR}",
    ),
    # ------------------------------------------ the fixed 48-request correction
    #
    # A second, separate merge. Every phrase here is required of each document for
    # the reason the whole ADR-0018 block is: merged main has twice carried a fact
    # in one status file and a stale contradiction in the other.
    (
        "records that the fixed-count correction merged",
        "the fixed 48-request assessment-boundary correction is merged "
        f"— pr {ADR_0018_FIX_PR} merged",
    ),
    ("names the correction merge commit", ADR_0018_FIX_MERGE_COMMIT),
    ("names the approved correction head", ADR_0018_FIX_APPROVED_HEAD),
    (
        "records what the independent review found",
        f"independent review found that pr {ADR_0018_IMPL_PR}'s initial assessment pair "
        "validation enforced only run-to-run count consistency",
    ),
    (
        "records what the correction compiled",
        f"pr {ADR_0018_FIX_PR} compiled adr-0018's requirement that both runs contain exactly "
        "48 planned and 48 completed requests",
    ),
    (
        "records that accounting cannot scale from a non-48 count",
        f"pr {ADR_0018_FIX_PR} also prevents assessment accounting from scaling from a "
        "locator-supplied non-48 count",
    ),
    (
        "records that an invalid pair refuses before any read",
        "invalid non-48 pairs refuse before record or payload reads",
    ),
    (
        "records that the correction changed nothing else",
        "the correction changed no adr, durable locator schema, infrastructure, provider "
        "behaviour, deadline, p1–p9 ceiling, report format or public "  # noqa: RUF001
        "authorization",
    ),
    # ---------------------------------------------- the four status distinctions
    #
    # Architecture, implementation, deployment and execution are four different
    # states, and this is the row where collapsing any two of them shows up.
    ("records the architecture status", "adr-0018 architecture: accepted / in force"),
    ("records the implementation status", "adr-0018 offline implementation: merged / dormant"),
    ("records the correction status", "fixed 48-request correction: merged"),
    (
        "records that infrastructure was never deployed",
        "infrastructure deployment: not authorized / not performed",
    ),
    ("records zero implementation execution", "implementation execution: not authorized / zero"),
    ("records that run a has not run", "run a: not authorized / not run"),
    ("records that run b has not run", "run b: not authorized / not run"),
    (
        "records that the combined assessment has not run",
        "combined assessment: not authorized / not run",
    ),
    # ------------------------------------------------------- preserved history
    #
    # A merge does not backdate itself, and it does not launder the order the two
    # merges happened in. PR #41 merged with the fixed-count validation missing;
    # saying so is what keeps the record honest.
    (
        "keeps the pre-merge fact that the implementation was a candidate",
        f"while pr {ADR_0018_IMPL_PR} was open it was an unmerged implementation candidate",
    ),
    (
        "keeps the pre-merge absence of the package",
        f"before pr {ADR_0018_IMPL_PR} merged, the offline package and its two dormant entry "
        "points were absent from main",
    ),
    (
        "records that the implementation merged before the correction",
        f"pr {ADR_0018_IMPL_PR} merged before the missing fixed-count validation was corrected",
    ),
    (
        "records why the defect stayed dormant",
        "the defect remained dormant because execution was not authorized",
    ),
    (
        "records that the correction landed on main afterwards",
        f"pr {ADR_0018_FIX_PR} subsequently corrected the implementation on main",
    ),
    (
        "keeps the two merge events separate",
        f"pr {ADR_0018_IMPL_PR} is not described as having passed the later pr "
        f"{ADR_0018_FIX_PR} correction review",
    ),
    (
        "records that no run happened around either merge",
        "no run a, run b or combined assessment occurred before, during or after either merge",
    ),
    (
        "refuses to read the premature merge as evidence",
        "the premature merge is no evidence of execution or of empirical qualification",
    ),
    # The sanitized incident, recorded in the four clauses that make it a record
    # rather than either a confession or an authorization.
    (
        "records the sanitized runtime-area incident",
        "unauthorized directory listing beneath the private runtime area",
    ),
    ("records that no file contents were read", "read no file contents"),
    (
        "records that no tracked contamination was found",
        "no tracked contamination was found by the read-only review",
    ),
    ("records that the filenames stay undisclosed", "filenames are intentionally not disclosed"),
    (
        "records that the incident authorizes no inspection",
        "authorizes neither private-directory inspection nor further diagnosis",
    ),
)

#: Ways a status document could overstate ADR-0018. All false today.
ADR_0018_STATUS_FORBIDDEN: Final[tuple[str, ...]] = (
    "adr-0018 authorizes implementation",
    # Not a bare "read surface exists": the honest current sentence says it exists
    # ONLY as dormant code on an open pull request, and a substring blocklist that
    # fired on the truthful wording would push the next editor to blur it. The
    # required phrase above pins that qualifier; these catch the live claims.
    "read surface is authorized",
    "read surface has executed",
    "read surface is live",
    "read surface is in use",
    "run a completed",
    "run b completed",
    "empirical qualification executed",
    # The superseded HeadObject arithmetic, in both spellings the status
    # documents use -- the en-dashed status row and the ASCII code block.
    "conditional `headobject` 0–147",  # noqa: RUF001
    "total s3 operations 147–294",  # noqa: RUF001
    "conditional headobject 0 to 147",
    "maximum s3 operations 147 to 294",
    # The superseded single-execution assessment arithmetic, in the exact
    # spellings the status documents used. The honest negations were reworded so
    # they do not carry these tokens: a denylist entry a correct document
    # contains is an entry that gets deleted rather than fixed.
    "`2r + 1` = 97",
    "total getobject 2r + 1 = 97",
    "total s3 operations 2r + 2 to 2r + 3 = 98 to 99",
    "conditional `headobject` 0–1, total 98–99",  # noqa: RUF001
    # The superseded ceilings row, before the deadline had a scope.
    "wall clock 1,800 s",
    # The claim the implementation candidate must never carry before it is
    # corrected. Each is a positive assertion, so an honest "cannot be merged
    # until it is corrected" does not contain any of them.
    "implementation candidate is ready to merge",
    "implementation candidate may be merged",
    "pr #41 is ready to merge",
    # The superseded pre-merge spelling of the amendment's status. PR #42 merged,
    # so a status document carrying this sentence is a document that reverted a
    # merged fact rather than one being cautious.
    "a clarification amendment is proposed and is not effective until merged",
    # ------------------------------- the two merges, in both directions of drift
    #
    # PR #41 and PR #44 have both merged. The first group is the superseded
    # pre-merge spelling of each fact, so a revert is caught rather than merely
    # un-asserted; none of them is a substring of the honest sentences the
    # required list above pins.
    "pr #41 is open",
    "pr #44 is open",
    "pr #41 remains unmerged",
    "pr #44 remains unmerged",
    "the offline implementation candidate is unmerged",
    "awaits an independent re-review",
    "implementation candidate, not merged, not accepted, never executed",
    "read surface does not exist",
    "exists only as dormant code on an open pull request",
    "the adr-0018 implementation is absent",
    # The second group is the opposite drift, and the more dangerous one: a
    # merged implementation inflated into a deployed, executed or qualified one.
    # The second and third gates are still uncrossed, and an honest negation
    # ("it is dormant and not deployed") contains none of these.
    "the implementation is deployed",
    "qualification infrastructure is deployed",
    "run a was executed",
    "run b was executed",
    "the combined assessment was executed",
    "the empirical qualification passed",
    "provider selection has occurred",
    "g1 is closed",
    "g2 is closed",
    "a general licensed object read surface exists",
    "licensed objects have been read",
    "the fixed correction authorized execution",
    # The bare implementation gate, in the spelling the status documents used
    # while it was still uncrossed. Implementation was authorized separately and
    # PR #41 merged, so only *execution* is still unauthorized -- and the honest
    # sentence, "adr-0018 implementation execution: not authorized", does not
    # contain either entry below, because the colon falls in a different place.
    "adr-0018 implementation: not authorized",
    "adr-0018 implementation remains not authorized",
)

#: What the deletion runbook must say after the clarification. Naming a prefix
#: must not become permission to depend on the artifact that lives there.
ADR_0018_RUNBOOK_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    ("names the locator prefix", "qualification/sharadar/locators/"),
    ("names the report prefix", "qualification/sharadar/reports/"),
    (
        "states that deletion behaviour is unchanged",
        "deletion behaviour is unchanged by naming them.",
    ),
    (
        "refuses to depend on a locator",
        "a locator may be absent, and this procedure must never depend on one to discover "
        "licensed objects.",
    ),
)

#: What the implementation plan must say once it carries the ceilings.
ADR_0018_PLAN_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    ("links the adr", "adr-0018-bounded-private-empirical-sharadar-qualification.md"),
    (
        "records that the adr is accepted as architecture only",
        "the adr is accepted and approves architecture only",
    ),
    ("records zero p-test executions", "p1–p9 executions by it are zero."),  # noqa: RUF001
    ("produces no aggregate verdict", "no aggregate verdict is produced by any of it."),
    # The clarification's two decisions reach the plan too: the ceiling P1 can
    # reach is now stated with the assessment that reaches it, and the plan must
    # not read an unmerged implementation candidate as a delivered one.
    (
        "records the combined cross-run assessment",
        "one combined assessment of run a and run b together",
    ),
    ("records the elapsed-time deadline", "1,800-second acquisition elapsed-time deadline"),
    # Inverted on PR #41's merge, not deleted. The plan is where the ceilings are
    # read from, so a plan that still called the implementation unmerged would send
    # a reader looking for a pull request that closed.
    (
        "records the merged, dormant offline implementation",
        "the offline implementation is merged and dormant",
    ),
    ("names the implementation merge commit", ADR_0018_IMPL_MERGE_COMMIT),
    ("names the correction merge commit", ADR_0018_FIX_MERGE_COMMIT),
    (
        "records that merging an implementation authorized no execution",
        "merging an implementation authorized no execution, no infrastructure deployment and "
        "no run",
    ),
    # PR #42 merged, so the plan's two clarifications are effective. The plan is
    # where the ceilings are read from, and a plan that still called them
    # proposed would send a reader to the superseded arithmetic.
    (
        "records that the two clarifications are effective",
        f"two clarifications are effective — pr {ADR_0018_CLARIFICATION_PR} merged",
    ),
    ("names the clarification merge commit", ADR_0018_CLARIFICATION_MERGE_COMMIT),
    (
        "records that the clarification merge approved clarification of architecture only",
        "the merge approved clarification of architecture only",
    ),
)


#: The proposed write-only acquisition amendment. **PROPOSED**, and deliberately
#: **not** in :data:`MERGED_ADR_STATUS`: an ADR that has not merged is not in
#: force, and registering it there would make the coverage check assert an
#: authority it does not have. Registration happens on the merge, the way
#: ADR-0017 and ADR-0018 were each registered on theirs.
ADR_0019: Final = DECISIONS / ("ADR-0019-write-only-acquisition-collision-policy.md")

#: The pull request that merged ADR-0019, its merge commit and the approved ADR
#: head. Registered in :data:`MERGED_ADR_STATUS` **on the merge**, and not before
#: -- the same treatment ADR-0017 and ADR-0018 were each given.
ADR_0019_PR: Final = "#46"
ADR_0019_MERGE_COMMIT: Final = "77974f476ead96548beb16543dfd3db8c03232c3"
ADR_0019_APPROVED_HEAD: Final = "bf0414c4a915d85a124ba400284ca1fa671fda27"

#: The pull request that merged the production-code correction ADR-0019 required
#: and ADR-0020 re-scoped, its merge commit and the approved implementation head.
#:
#: One correction, one pull request. It is deliberately **not** registered in
#: :data:`MERGED_ADR_STATUS`: that registry answers *which pull request made an
#: ADR effective*, and PR #48 made none -- PR #46 and PR #49 did. A second row
#: for ADR-0019 or ADR-0020 would be two answers to one question.
ADR_0019_IMPL_PR: Final = "#48"
ADR_0019_IMPL_MERGE_COMMIT: Final = "f0b39fccdfb36ea69d08fb4def3979b87814b9ff"
ADR_0019_IMPL_APPROVED_HEAD: Final = "64dc3388f402ee98cf8940d94b42fa16aa7553e2"

#: Superseded status lines that may appear ONLY inside their historical framing.
#:
#: Both were true, as current status, until PR #48 merged the production-code
#: correction. Both are still required **by name** of CLAUDE.md, README.md and the
#: implementation plan by ``tests/unit/test_adr_0019_governance.py``, so neither can
#: simply be deleted -- and neither may stand as a current claim, because the
#: prerequisite is satisfied and the correction is merged.
#:
#: A denylist cannot express *only inside this framing*: it answers "is the phrase
#: present", and the phrase is legitimately present. :func:`_unframed_occurrences`
#: answers the question that actually matters -- how many copies stand **outside**
#: the sentence that marks them historical -- so reintroducing either as a current
#: status line fails while the preserved record stays.
#:
#: Each framing must contain its phrase verbatim, or the subtraction below is
#: meaningless. A check asserts exactly that rather than trusting the pairing.
HISTORICAL_ONLY_STATUS_LINES: Final[tuple[tuple[str, str], ...]] = (
    (
        "infrastructure design: blocked pending implementation correction",
        f"before pr {ADR_0019_IMPL_PR} merged, infrastructure design: blocked pending "
        "implementation correction",
    ),
    (
        "production implementation correction: not authorized / not implemented",
        f"before pr {ADR_0019_IMPL_PR} merged, production implementation correction: not "
        "authorized / not implemented",
    ),
    (
        "the production implementation does not yet conform to that architecture",
        f"before pr {ADR_0019_IMPL_PR} merged, the production implementation does not yet "
        "conform to that architecture",
    ),
)

#: What ADR-0019 must say about itself.
#:
#: The feasibility gap it records is a permission fact, not a preference: AWS
#: authorizes ``HeadObject`` with ``s3:GetObject`` and publishes no metadata
#: action of its own, so ADR-0018 s10.1's granted collision resolution and its
#: withheld object-byte read are one IAM action apart. Each clause below is a
#: separate entry because a single sentence covering all of them is one a later
#: edit can soften in place.
ADR_0019_SELF_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    # ------------------------------------------------ status, and what it is not
    (
        "records that it is proposed and carries no authority",
        "no authority until the pull request introducing it is independently reviewed and merged",
    ),
    ("authorizes nothing", "this adr authorizes nothing"),
    ("keeps infrastructure blocked", "infrastructure remains blocked"),
    ("keeps adr-0018 in force", "adr-0018 remains accepted / in force"),
    (
        "keeps the merged implementation dormant",
        "the merged adr-0018 offline implementation remains merged / dormant",
    ),
    (
        "records that the merged implementation is not yet deployable",
        "not deployable under the accepted boundary until a later implementation-correction gate "
        "is completed",
    ),
    ("leaves adr-0017 alone", "adr-0017 is not amended and not superseded"),
    # ------------------------------------------------------- the AWS constraint
    ("records the feasibility classification", "stopped_architecture_gap_head_requires_get"),
    ("records that head requires get", "headobject requires the s3:getobject permission"),
    (
        "records that no metadata action exists",
        "aws exposes no independent s3:headobject iam action",
    ),
    ("records that attributes does not help", "getobjectattributes does not solve it"),
    (
        "records the listing limit",
        "absence of s3:listbucket prevents enumeration but not a known-key read",
    ),
    (
        "records that an application shape is not iam authority",
        "does not remove iam authority from a compromised process",
    ),
    (
        "records the kms finding",
        "the current sse-s3 design offers no kms permission that could be withheld",
    ),
    # ------------------------------------------------------------- the decision
    ("withholds the read action", "receives no s3:getobject"),
    ("withholds the version read action", "receives no s3:getobjectversion"),
    ("withholds the attributes action", "receives no s3:getobjectattributes"),
    ("removes acquisition head", "performs no headobject"),
    ("removes acquisition object-byte reads", "performs no object-byte read"),
    ("keeps both layers", "both layers are retained, independently"),
    (
        "refuses to read a 412 as identity",
        "a 412 does not establish that the occupied object is identical",
    ),
    ("names the bronze outcome", "bronze_name_occupied"),
    ("names the locator outcome", "locator_name_occupied"),
    (
        "keeps the locator retry permission unchanged",
        "the bounded locator retry permission of adr-0018",
    ),
    ("records the retry false negative", "that is a false negative in the safe direction"),
    # -------------------------------------------------------- adr-0017 isolation
    (
        "requires an adr-0018-specific write-only surface",
        "adr-0018-specific write-only publication surface",
    ),
    ("keeps the surface away from adr-0017", "cannot be used by adr-0017 accidentally"),
    (
        "records that the surface is not authorized code",
        "not code authorized by this adr's proposal pull request",
    ),
    # ------------------------------------------------------------- the arithmetic
    ("derives the successful-run total", "145 to 147"),
    ("derives the two-run total", "290 to 294"),
    ("derives the package total", "485 to 490"),
    ("keeps the assessment envelope", "195 to 196"),
    ("records zero acquisition head invocations", "head_object_count == 0"),
    ("records zero acquisition object reads", "get_object_count == 0"),
    ("names the superseded acquisition arithmetic", "superseded for the acquisition actor"),
    ("records refused-run accounting", "a refused run did not perform 145 operations"),
    # ---------------------------------------------------------------- the deadline
    ("derives the locator reserve", "l >= 3 * t_s3 + c"),
    ("derives the per-request admission", "remaining >= t_req + 3 * t_s3 + l"),
    ("derives the feasibility inequality", "t_req + p + 3 * t_s3 + l <= d"),
    ("preserves the deadline", "1,800-second total elapsed acquisition deadline"),
    # ------------------------------------------------- the alternative it declines
    ("rejects the weaker alternative", "the application-only alternative is not adopted"),
    (
        "records that the weaker alternative was never authorized",
        "the weaker alternative was never authorized",
    ),
    # ------------------------------------------------------------------- history
    (
        "preserves the chronology",
        "adr-0018 is not rewritten as though the corrected design had always existed",
    ),
    (
        "records that nothing ran before the discovery",
        "no infrastructure was built and no run occurred before the discovery",
    ),
    # ------------------------------------------- the adjacent post-merge note
    #
    # ADDED on the merge, not substituted for the conditional status line above.
    # The ADR keeps the text it was written with -- PROPOSED, no authority until
    # merged -- because that is what it said while its pull request was open, and
    # a decision record is not rewritten when the world moves. The note beside it
    # is what stops that conditional line from being read as current.
    ("records that the condition was satisfied", "the condition above has since been satisfied"),
    ("names the merge commit", ADR_0019_MERGE_COMMIT),
    ("names the approved head", ADR_0019_APPROVED_HEAD),
    (
        "records the conditional acceptance event",
        "adr-0019's conditional acceptance event has occurred",
    ),
    (
        "keeps the proposed period historical",
        f"while pr {ADR_0019_PR} was open adr-0019 was proposed and carried no authority",
    ),
    ("preserves the earlier state", "preserved as history, not rewritten"),
    (
        "records that the merge approved architecture only",
        "the merge approved architecture only, and authorized no production-code correction",
    ),
    ("carries the adjacent historical note", "this section is a historical note added after the"),
    # ------------------------------------------------ the relationship, exactly
    ("records no wholesale supersession", "adr-0019 supersedes no adr wholesale"),
    ("records the narrow amendment", "narrowly amends the enumerated clauses of adr-0018"),
    (
        "keeps adr-0018 in force as amended",
        "adr-0018 remains accepted / in force except as amended by adr-0019",
    ),
    ("leaves adr-0017 alone after the merge", "adr-0017 is not amended or superseded"),
    ("leaves adr-0011 alone after the merge", "adr-0011 is not amended or superseded"),
    ("keeps the shared store unchanged", "the shared s3researchobjectstore remains unchanged"),
    (
        "records the amendment as authoritative",
        "adr-0019's amendment is now authoritative architecture",
    ),
    # ---------------------------------------------------- the implementation gap
    (
        "records that the implementation does not conform",
        "the production implementation does not yet conform to that architecture",
    ),
    ("records the dormant implementation", "adr-0018 offline implementation: merged / dormant"),
    (
        "records the correction status",
        "adr-0019 production-code correction: not authorized / not implemented",
    ),
    (
        "records the pre-amendment collision path",
        "the current dormant acquisition implementation still uses the pre-adr-0019 shared "
        "collision path",
    ),
    (
        "records non-deployability",
        "the current dormant implementation is therefore not deployable under the authoritative "
        "architecture",
    ),
    (
        "refuses a zero-head implementation claim",
        "no claim is made that the current implementation already has zero acquisition head "
        "operations",
    ),
    (
        "refuses a surface-exists claim",
        "no claim is made that the adr-0018-specific write-only publication surface already exists",
    ),
    (
        "records infrastructure blocked pending correction",
        "infrastructure design: blocked pending implementation correction",
    ),
    (
        "records that acceptance is not authorization",
        "acceptance of adr-0019 is not authorization to implement or execute it",
    ),
)

#: Claims ADR-0019 must never make. Two directions of drift: a proposal reading
#: itself as accepted, and a corrected design reading itself as built. Consumed
#: by one aggregate check, so adding an entry adds no audit check of its own.
ADR_0019_SELF_FORBIDDEN: Final[tuple[str, ...]] = (
    "the acquisition role receives s3:getobject",
    "the acquisition role may receive s3:getobject",
    "acquisition may use headobject",
    "headobject has its own iam action",
    "s3:headobject is a valid iam action",
    "application shape alone satisfies the boundary",
    "existing objects may be adopted without inspection",
    "a 412 establishes identical content",
    "infrastructure is ready to deploy",
    "terraform is authorized",
    "run a is authorized",
    "run b is authorized",
    "the combined assessment is authorized",
    "adr-0017's collision behaviour changed",
    "the assessment envelope changed",
    "g1 is closed",
    "g2 is closed",
    # Post-merge drift, in both directions. The first four would revert a merged
    # fact; the last three would read an accepted architecture as a built one.
    "adr-0019 is still proposed",
    "adr-0019 has not merged",
    f"pr {ADR_0019_PR} is open",
    f"pr {ADR_0019_PR} remains unmerged",
    "the write-only publication surface exists",
    "the production implementation conforms",
    "the production-code correction is implemented",
)

#: What both status documents must say about the feasibility gap and ADR-0019.
#:
#: Required of *each* document for the reason the whole ADR-0018 block is:
#: merged main has twice carried a fact in one status file and a stale
#: contradiction in the other.
#: What both status documents must say now that ADR-0019 has merged.
#:
#: Inverted on the merge, not deleted: the proposed-state spellings moved into
#: :data:`ADR_0019_STATUS_FORBIDDEN` below. Required of *each* document,
#: because merged main has twice carried a fact in one status file and a stale
#: contradiction in the other.
ADR_0019_STATUS_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    ("records the feasibility classification", "stopped_architecture_gap_head_requires_get"),
    ("records the accepted status", "adr-0019: accepted / in force"),
    ("records the architecture status", "adr-0019 architecture: accepted / in force"),
    ("names the merge commit", "77974f476ead96548beb16543dfd3db8c03232c3"),
    ("names the approved head", "bf0414c4a915d85a124ba400284ca1fa671fda27"),
    ("records the merge time", "2026-09-01t01:01:22z"),
    (
        "records the conditional acceptance event",
        "adr-0019's conditional acceptance event has occurred",
    ),
    ("records the independent review", "pr #46 was independently reviewed before its merge"),
    (
        "keeps the proposed period historical",
        "while pr #46 was open adr-0019 was proposed and carried no authority",
    ),
    (
        "keeps what governed before the merge",
        "adr-0018's original collision-resolution design and arithmetic governed before the pr "
        "#46 merge",
    ),
    (
        "records that the merge approved architecture only",
        "the merge approved architecture only, and authorized no production-code correction",
    ),
    ("records no wholesale supersession", "adr-0019 supersedes no adr wholesale"),
    ("records the narrow amendment", "narrowly amends the enumerated clauses of adr-0018"),
    (
        "keeps adr-0018 in force as amended",
        "adr-0018 remains accepted / in force except as amended by adr-0019",
    ),
    ("leaves adr-0017 alone", "adr-0017 is not amended or superseded"),
    ("leaves adr-0011 alone", "adr-0011 is not amended or superseded"),
    ("keeps the shared store unchanged", "the shared s3researchobjectstore remains unchanged"),
    (
        "records the amendment as authoritative",
        "adr-0019's amendment is now authoritative architecture",
    ),
    (
        # Inverted on the PR #48 merge, not deleted: the pre-correction spelling
        # moved into :data:`ADR_0019_STATUS_FORBIDDEN`, so a revert fails rather
        # than merely going unchecked. "Offline" is load-bearing -- the code
        # conforms, and nothing is deployed, run or empirically validated.
        "records that the implementation now conforms offline",
        "the production implementation now conforms to that architecture offline",
    ),
    ("records that head requires get", "headobject requires the s3:getobject permission"),
    (
        "records that no metadata action exists",
        "aws exposes no independent s3:headobject iam action",
    ),
    (
        "records that attributes needs read authority",
        "getobjectattributes also requires object-read authority",
    ),
    (
        "records the listing limit",
        "absence of s3:listbucket prevents enumeration but not a known-key read",
    ),
    (
        "records that an application shape is not iam authority",
        "does not remove iam authority from a compromised process",
    ),
    ("withholds the read action", "the acquisition role receives no s3:getobject"),
    ("withholds the version read action", "no s3:getobjectversion"),
    ("withholds the attributes action", "no s3:getobjectattributes"),
    (
        "removes head_object from the surface",
        "the acquisition publication surface has no head_object",
    ),
    ("removes get_object from the surface", "no get_object"),
    ("records zero acquisition head", "acquisition headobject: exactly 0"),
    ("records zero acquisition object reads", "acquisition getobject: exactly 0"),
    (
        "records fail-closed collisions",
        "every acquisition-side conditional putobject collision fails closed",
    ),
    (
        "refuses to read a 412 as identity",
        "a 412 does not establish that the occupied object is identical",
    ),
    (
        "names the authoritative bronze outcome",
        "bronze_name_occupied is the authoritative architectural closed outcome",
    ),
    (
        "names the authoritative locator outcome",
        "locator_name_occupied is the authoritative architectural replacement for the earlier "
        "collision claim",
    ),
    (
        "refuses a verified-collided-object claim",
        "a partial locator cannot claim the collided object was verified or retained",
    ),
    ("keeps the unpublished-locator outcome", "the closed result remains locator_not_published"),
    ("keeps both boundaries", "both the iam boundary and the application boundary are retained"),
    ("rejects the weaker alternative", "the application-only alternative is not adopted"),
    (
        "requires the write-only surface at the later gate",
        "the later implementation correction must introduce an adr-0018-specific write-only "
        "publication surface",
    ),
    ("records the dormant implementation", "adr-0018 offline implementation: merged / dormant"),
    (
        "records the correction status",
        "adr-0019 production-code correction: merged / dormant / offline-conforming",
    ),
    ("names the correction merge commit", ADR_0019_IMPL_MERGE_COMMIT),
    ("names the approved implementation head", ADR_0019_IMPL_APPROVED_HEAD),
    (
        "records that the pre-amendment collision path is gone",
        "the dormant acquisition implementation no longer uses the pre-adr-0019 shared "
        "collision path",
    ),
    (
        "records offline conformance",
        "the current dormant implementation is offline-conforming under the authoritative "
        "architecture",
    ),
    (
        # What the two refusals it replaces could not say. They were honest while
        # nothing had been corrected; a document may now state the property, and
        # a document that states it is held to it by the structural guard.
        "records the zero-read acquisition implementation",
        "the merged dormant acquisition implementation has zero acquisition headobject and zero "
        "acquisition getobject",
    ),
    (
        "records that the write-only surface now exists",
        "the adr-0018-specific write-only publication surface now exists",
    ),
    (
        # The pre-correction period stays a fact about those days, exactly as
        # ADR-0019's own proposed period does.
        "keeps the pre-correction state historical",
        f"before pr {ADR_0019_IMPL_PR} merged the production implementation did not yet conform",
    ),
    (
        "records the satisfied prerequisite",
        "the adr-0019 implementation-correction prerequisite is satisfied",
    ),
    (
        # The transition that matters, and the one a reader could misread: a
        # prerequisite being met is not a permission being granted.
        "records that the prerequisite authorizes nothing",
        "satisfying the implementation prerequisite does not itself authorize or begin "
        "infrastructure work",
    ),
    (
        "records that infrastructure stays unauthorized",
        "infrastructure design and mutation: not authorized / not implemented",
    ),
    ("records the governing put range", "acquisition putobject: 145 to 147"),
    ("records the two-run total", "two successful runs: 290 to 294"),
    ("keeps the assessment envelope", "assessment: unchanged at 195 to 196"),
    ("records the package total", "whole successful package: 485 to 490"),
    ("records the locator reserve", "l >= 3 * t_s3 + c"),
    ("records the admission rule", "remaining >= t_req + 3 * t_s3 + l"),
    ("records the feasibility inequality", "t_req + p + 3 * t_s3 + l <= d"),
    ("records the deadline", "d = 1800 seconds"),
    (
        "records refused-run accounting",
        "partial and refused runs are never reported as having performed 145 operations",
    ),
    (
        "retires the superseded acquisition figures",
        "the superseded acquisition figures are adr-0018's original accepted arithmetic and no "
        "longer govern",
    ),
    # The retirement sentence above is necessary and was not sufficient. Both
    # documents carried it while the detailed ADR-0018 narrative still presented
    # the retired deadline and operation arithmetic as current, three hundred
    # lines from the figures that replaced it -- which is how a reader ends up
    # with two admission rules and two package envelopes and no way to tell which
    # governs. The label and the three pointers below are what make that
    # narrative unreadable as current, and `scan_retired_arithmetic` is what
    # proves no occurrence escaped them.
    (
        "labels the retired arithmetic where it stands",
        "historical \u2014 adr-0018 original arithmetic. superseded by adr-0019; no longer "
        "governing.",
    ),
    (
        "points the historical deadline block at the current rule",
        "the governing deadline arithmetic is adr-0019's",
    ),
    (
        "points the historical count block at the current rule",
        "the governing acquisition arithmetic is adr-0019's",
    ),
    (
        "points the historical envelope block at the current rule",
        "the governing whole-package envelope is adr-0019's",
    ),
    ("records the deployment status", "deployment: not authorized / not performed"),
    (
        "records the terraform and iam status",
        "terraform/iam implementation: not authorized / not implemented",
    ),
    (
        "records the infrastructure mutation status",
        "infrastructure mutation: not authorized / not performed",
    ),
    ("records that run a has not run", "run a: not authorized / not run"),
    ("records that run b has not run", "run b: not authorized / not run"),
    (
        "records that the combined assessment has not run",
        "combined assessment: not authorized / not run",
    ),
    ("records zero new qualification roles", "new qualification iam roles zero -- none exists"),
    (
        "records that acceptance is not authorization",
        "acceptance of adr-0019 is not authorization to implement or execute it",
    ),
    (
        "records that nothing ran before the discovery",
        "no infrastructure was built and no run occurred before the discovery",
    ),
    (
        "records when the conflict was discovered",
        "discovered after adr-0018's dormant implementation had merged",
    ),
    ("keeps g1 open", "g1 open"),
    ("keeps g2 open", "g2 open"),
    ("keeps phase 3 incomplete", "phase 3 not complete"),
    ("keeps control deferred", "control publication deferred"),
    ("keeps live trading disabled", "live trading hard-disabled"),
    (
        "keeps the third adr-0017 attempt unauthorized",
        "a third adr-0017 authenticated attempt not authorized",
    ),
)

#: Claims neither status document may make about the gap or the proposal.
#: One aggregate check per document, so entries here add no audit check.
ADR_0019_STATUS_FORBIDDEN: Final[tuple[str, ...]] = (
    "the acquisition role receives s3:getobject",
    "the acquisition role may receive s3:getobject",
    "acquisition may use headobject",
    "headobject has its own iam action",
    "s3:headobject is a valid iam action",
    "application shape alone satisfies the boundary",
    "existing objects may be adopted without inspection",
    "a 412 establishes identical content",
    "infrastructure is ready to deploy",
    "the feasibility gap is resolved",
    "the architecture gap is closed",
    "adr-0017's collision behaviour changed",
    "the assessment envelope changed",
    # ------------------------------------------- the superseded proposed state
    #
    # Moved here on the merge rather than deleted, so a revert to the pre-merge
    # wording is caught rather than merely un-asserted. None of these is a
    # substring of an honest post-merge sentence: "adr-0019 was proposed" is
    # historical and allowed, "surface already exists" is a refusal, and
    # "does not yet conform" is not "conforms".
    "adr-0019: proposed / not in force",
    "adr-0019 carries no authority until the pull request introducing it is merged",
    "proposed, not in force -- acquisition",
    "adr-0019 is proposed",
    "adr-0019 is still proposed",
    "adr-0019 has not merged",
    "adr-0018 as accepted is what governs",
    "adr-0018's accepted arithmetic remains the in-force arithmetic",
    "the figures adr-0019 derives are proposed rather than current",
    f"pr {ADR_0019_PR} is open",
    f"pr {ADR_0019_PR} remains unmerged",
    # ---------------------------- the superseded pre-correction state
    #
    # Released on the PR #48 merge, and replaced rather than dropped. Three
    # entries left this list because they became TRUE -- "the write-only
    # publication surface exists", "the production implementation conforms" and
    # "the production-code correction is implemented" -- and a denylist that
    # forbids the truth is one that forces a document to lie. What took their
    # place is every spelling of the state the merge ended, so a revert to "not
    # corrected" fails rather than merely going unasserted. None is a substring
    # of an honest post-merge sentence: "before pr #48 merged the production
    # implementation did not yet conform" is history, and is required above.
    "adr-0019 production-code correction: not authorized / not implemented",
    "the current dormant acquisition implementation still uses the pre-adr-0019 shared "
    "collision path",
    "the current dormant implementation is therefore not deployable under the authoritative "
    "architecture",
    "no claim is made that the current implementation already has zero acquisition head operations",
    "no claim is made that the adr-0018-specific write-only publication surface already exists",
    "infrastructure remains blocked until the production correction is separately authorized",
    # ------------------------------------------------- the forward drift
    #
    # A merged offline correction is not a deployment, and the distance between
    # those two is the whole of what this synchronization protects.
    "the write-only publication surface is deployed",
    "the production implementation is deployed",
    "the production-code correction is deployed",
    "terraform/iam implementation: implemented",
    "infrastructure mutation: performed",
    "deployment: performed",
)

#: What the implementation plan must say once the gap is recorded. The plan is
#: where the ceilings are read from, so a plan that still sent a reader to an
#: undeployable design would be sending them to a design nobody can build.
#: What the implementation plan must say now that ADR-0019 has merged. The
#: plan is where the ceilings are read from, so it carries the governing
#: arithmetic and the open implementation gap together.
ADR_0019_PLAN_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    ("records the feasibility classification", "stopped_architecture_gap_head_requires_get"),
    ("records the architecture status", "adr-0019 architecture: accepted / in force"),
    ("names the merge commit", "77974f476ead96548beb16543dfd3db8c03232c3"),
    ("names the approved head", "bf0414c4a915d85a124ba400284ca1fa671fda27"),
    (
        "keeps the proposed period historical",
        "while pr #46 was open adr-0019 was proposed and carried no authority",
    ),
    (
        "keeps what governed before the merge",
        "adr-0018's original collision-resolution design and arithmetic governed before the pr "
        "#46 merge",
    ),
    (
        "records that the merge approved architecture only",
        "the merge approved architecture only, and authorized no production-code correction",
    ),
    ("records no wholesale supersession", "adr-0019 supersedes no adr wholesale"),
    ("records the narrow amendment", "narrowly amends the enumerated clauses of adr-0018"),
    (
        "keeps adr-0018 in force as amended",
        "adr-0018 remains accepted / in force except as amended by adr-0019",
    ),
    ("leaves adr-0017 alone", "adr-0017 is not amended or superseded"),
    ("keeps the shared store unchanged", "the shared s3researchobjectstore remains unchanged"),
    (
        "records that the implementation now conforms offline",
        "the production implementation now conforms to that architecture offline",
    ),
    ("withholds the read action", "the acquisition role receives no s3:getobject"),
    ("records zero acquisition head", "acquisition headobject: exactly 0"),
    ("records zero acquisition object reads", "acquisition getobject: exactly 0"),
    (
        "records fail-closed collisions",
        "every acquisition-side conditional putobject collision fails closed",
    ),
    (
        "requires the write-only surface at the later gate",
        "the later implementation correction must introduce an adr-0018-specific write-only "
        "publication surface",
    ),
    (
        "records the correction status",
        "adr-0019 production-code correction: merged / dormant / offline-conforming",
    ),
    ("names the correction merge commit", ADR_0019_IMPL_MERGE_COMMIT),
    ("names the approved implementation head", ADR_0019_IMPL_APPROVED_HEAD),
    (
        "records that the pre-amendment collision path is gone",
        "the dormant acquisition implementation no longer uses the pre-adr-0019 shared "
        "collision path",
    ),
    (
        "records offline conformance",
        "the current dormant implementation is offline-conforming under the authoritative "
        "architecture",
    ),
    (
        "keeps the pre-correction state historical",
        f"before pr {ADR_0019_IMPL_PR} merged the production implementation did not yet conform",
    ),
    (
        "records the satisfied prerequisite",
        "the adr-0019 implementation-correction prerequisite is satisfied",
    ),
    (
        "records that the prerequisite authorizes nothing",
        "satisfying the implementation prerequisite does not itself authorize or begin "
        "infrastructure work",
    ),
    (
        "records that infrastructure stays unauthorized",
        "infrastructure design and mutation: not authorized / not implemented",
    ),
    ("records the governing put range", "acquisition putobject: 145 to 147"),
    ("records the two-run total", "two successful runs: 290 to 294"),
    ("keeps the assessment envelope", "assessment: unchanged at 195 to 196"),
    ("records the package total", "whole successful package: 485 to 490"),
    ("records the locator reserve", "l >= 3 * t_s3 + c"),
    ("records the admission rule", "remaining >= t_req + 3 * t_s3 + l"),
    (
        "records that acceptance is not authorization",
        "acceptance of adr-0019 is not authorization to implement or execute it",
    ),
    (
        "attributes the clarification merge correctly",
        "the pr #42 clarification merge conferred no implementation authority",
    ),
    (
        "keeps the current truth separate",
        "the offline implementation later merged dormant through pr #41, but its execution and "
        "deployment remain unauthorized",
    ),
)


#: The HTML-comment markers that delimit a block of retired ADR-0018 arithmetic
#: in a current status document.
#:
#: A comment rather than prose because it has to survive rendering: README.md is
#: rendered on GitHub, CLAUDE.md is read raw as instructions, and only a comment
#: is inert in the first while still visible in the second. The human-facing half
#: is the blockquote banner the markers are required to wrap.
RETIRED_ARITHMETIC_BEGIN: Final = "<!-- retired-arithmetic begin"
RETIRED_ARITHMETIC_END: Final = "<!-- retired-arithmetic end"

#: How many delimited historical regions each status document must carry: the
#: deadline sub-budget, the nominal-and-maximum counts, the whole-package envelope,
#: and the supersession paragraph that explains what replaced them. A floor rather
#: than an equality, so merging two adjacent regions stays legal while deleting a
#: label does not.
RETIRED_ARITHMETIC_BLOCKS: Final = 4

#: Same-line retirement markers for retired *arithmetic*, and deliberately only
#: these two.
#:
#: Distinct from :data:`RETIREMENT_MARKERS`, which serves retired field names and
#: is far looser. A bare "superseded" is enough there and is not enough here: the
#: whole-package paragraph happens to contain "the superseded canonical arithmetic
#: is gone", which is about a *different* supersession, and a loose marker would
#: have waved a retired figure through on the strength of an unrelated sentence.
#:
#: A same-line mechanism is needed at all because the ADR-0018 registry row is one
#: table row, and an HTML comment before and after it would break the table.
RETIRED_ARITHMETIC_MARKERS: Final[tuple[str, ...]] = (
    "no longer govern",
    "superseded by adr-0019",
)

#: Acquisition arithmetic ADR-0019 retired, as patterns rather than substrings.
#:
#: Patterns because the same figure is spelled several ways across two documents:
#: ASCII and Unicode multiplication signs, ``to`` and en-dash ranges, ``zero`` and
#: ``0``, and backtick formatting that the scan strips before matching. A bare
#: numeric substring would be worse than useless here -- ``584`` occurs inside
#: commit hashes -- so each entry anchors the whole range or equation.
#:
#: None of these can match the governing ADR-0019 figures: those are ``3 * T_s3``,
#: ``145 to 147``, ``290 to 294``, ``195 to 196``, ``485 to 490`` and an
#: acquisition ``HeadObject`` of exactly 0, and no pattern below matches any of
#: them. In particular "acquisition HeadObject: exactly 0" is not "zero to 145".
RETIRED_ARITHMETIC: Final[tuple[tuple[str, str], ...]] = (
    ("the 4 x T_s3 locator allowance", r"(?<!\d)4\s*[*x\u00d7]\s*t_s3"),
    ("the 6 x T_s3 per-request allowance", r"(?<!\d)6\s*[*x\u00d7]\s*t_s3"),
    ("the zero-to-145 conditional HeadObject range", r"\bzero\s+to\s+145\b"),
    ("the 0-to-145 conditional HeadObject range", r"\b0\s*(?:to|[-\u2013\u2014])\s*145\b"),
    ("the 145-to-290 per-run total", r"\b145\s*(?:to|[-\u2013\u2014])\s*290\b"),
    ("the 147-to-292 per-run total", r"\b147\s*(?:to|[-\u2013\u2014])\s*292\b"),
    ("the 2 x 292 = 584 two-run maximum", r"\b2\s*[*x\u00d7]\s*292\s*=\s*584\b"),
    ("the both-runs 584 maximum", r"\bboth runs\s*(?:=|:)?\s*584\b"),
    ("the 290-to-584 two-run total", r"\b29[04]\s*(?:to|[-\u2013\u2014])\s*584\b"),
    ("the 485-to-780 package envelope", r"\b485\s*(?:to|[-\u2013\u2014])\s*780\b"),
    ("the 780 = 584 + 196 package maximum", r"\b780\s*=\s*584\b"),
)

#: The request-scoped qualification payload identity. **ACCEPTED / IN FORCE** on
#: the merge of PR #49, and registered in :data:`MERGED_ADR_STATUS` on that merge
#: -- the way ADR-0017, ADR-0018 and ADR-0019 were each registered on theirs.
#: While its pull request was open it was **not** registered, because an ADR that
#: has not merged is not in force; the merge is the event that flips it.
ADR_0020: Final = DECISIONS / ("ADR-0020-request-scoped-qualification-payload-identity.md")

#: The pull request whose implementation work exposed the collision. It is **still
#: open and unmerged**, and it now requires a correction against the accepted
#: ADR-0020 design before it may be independently reviewed or merged. Neither the
#: proposal nor its merge touched it.
ADR_0020_BLOCKED_PR: Final = "#48"

#: The pull request that merged ADR-0020, its merge commit and the approved ADR
#: head. Registered in :data:`MERGED_ADR_STATUS` **on the merge**, and not before.
ADR_0020_PR: Final = "#49"
ADR_0020_MERGE_COMMIT: Final = "e4d328af53f2663c570f94e6c090c3296db8cb9d"
ADR_0020_APPROVED_HEAD: Final = "d9bbb17b7f174c34223eb4736d763f115daf229f"

#: The one sentence that keeps the pre-merge period historical rather than
#: current. One constant, used by the ADR, both status documents and the plan --
#: three spellings of one historical fact is how one surface drifts from another.
ADR_0020_HISTORICAL_PROPOSED: Final = (
    f"while pr {ADR_0020_PR} was open, adr-0020 was proposed and carried no authority"
)

#: What ADR-0020 must say about itself.
#:
#: The conflict it answers is an identity fact, not a preference: a complete run
#: is a fixed 48 requests and 144 Bronze writes, the payload object is
#: content-addressed by ``(provider, dataset, digest)``, and ADR-0019 fails a 412
#: closed without looking -- so two legitimate byte-identical observations derive
#: one name and halt a correct run. Each clause below is a separate entry because
#: a single sentence covering all of them is one a later edit can soften in place.
ADR_0020_SELF_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    # ------------------------------------------------ status, and what it is not
    (
        "records that it is proposed and carries no authority",
        "no authority until the pull request introducing it is independently reviewed and merged",
    ),
    ("authorizes nothing", "this adr authorizes nothing"),
    (
        "carries neither implementation nor infrastructure authority",
        "it carries no implementation authority and no infrastructure authority",
    ),
    ("authorizes no deployment", "it authorizes no deployment"),
    (
        "authorizes neither run nor the combined assessment",
        "it authorizes no run a, no run b and no combined assessment",
    ),
    ("keeps infrastructure blocked", "infrastructure remains blocked"),
    # ------------------------------------------------------- what it leaves alone
    (
        "does not make the blocked pull request mergeable",
        f"this adr does not make pr {ADR_0020_BLOCKED_PR} mergeable",
    ),
    (
        "does not rewrite the blocked pull request's status",
        f"it does not retroactively change the status of pr {ADR_0020_BLOCKED_PR}",
    ),
    (
        "supersedes only the payload-key identity rule",
        "it supersedes only the qualification payload-key identity rule",
    ),
    (
        "keeps the write-only collision policy",
        "it does not supersede adr-0019's write-only collision policy",
    ),
    ("leaves adr-0017 alone", "it does not supersede adr-0017"),
    (
        "leaves the shared contracts alone",
        "it does not modify the shared general-purpose bronze or `s3researchobjectstore` contract",
    ),
    # ------------------------------------------------------------- the conflict
    (
        "names the legitimate duplicate-payload collision",
        "the legitimate duplicate-payload collision",
    ),
    ("names the fixed request count", "exactly 48 requests"),
    ("names the fixed bronze write count", "exactly 144 bronze"),
    ("records the header-only completeness probe case", "header-only"),
    ("records the unchanged-snapshot case", "an unchanged snapshot re-observed in run b"),
    (
        "records that the conflict is an identity problem",
        "this is an identity and key-contract problem. it is not a reason to weaken write-only "
        "acquisition.",
    ),
    (
        "records that the conflict predates deployment",
        "the conflict exists before any aws deployment",
    ),
    (
        "records that the blocked pull request obeyed the accepted rule",
        f"pr {ADR_0020_BLOCKED_PR} is not defective for obeying adr-0019",
    ),
    (
        "records that the claim and record keys are already scoped",
        "the claim and the record are already execution-and-request-scoped, and the payload is not",
    ),
    # ------------------------------------------------------------ the three inputs
    ("binds the execution identity", "execution_identity"),
    ("binds the request ordinal", "request_ordinal"),
    ("binds the payload digest", "payload_sha256_digest"),
    ("requires all three bindings", "all three bindings must be preserved"),
    (
        "takes the ordinal from the locked inventory",
        "the deterministic ordinal from the locked 48-request inventory",
    ),
    (
        "keeps the ordinal out of provider control",
        "cannot be supplied freely by the provider",
    ),
    (
        "keeps the digest in durable evidence independently of the key",
        "remains present in durable evidence independently of the key",
    ),
    ("makes the same publication deterministic", "deterministically produce the same key"),
    ("separates executions", "a different execution identity produces a different key"),
    ("separates ordinals", "a different request ordinal produces a different key"),
    (
        "separates payload bytes",
        "different payload bytes produce a different digest and a different key",
    ),
    (
        "removes the legitimate collision",
        "identical bytes from different requests, or from different runs, no longer collide",
    ),
    (
        "keeps a retry deterministic",
        "a retry of the same publication attempt targets the same key",
    ),
    ("forbids a changing suffix", "there is no random suffix"),
    (
        "adds no listing and no existence check",
        "no list operation and no preflight existence check is introduced",
    ),
    # ------------------------------------------------------------------- privacy
    (
        "keeps every private request value out of the key",
        "no provider subject, ticker, date range, api path, credential, bucket, account, owner "
        "name or other private request value",
    ),
    # ----------------------------------------------------------------- integrity
    (
        "requires the recorded key to equal the reconstructed key",
        "the recorded payload key exactly equals the reconstructed key",
    ),
    (
        "requires the digest to be recomputed",
        "sha-256 is recomputed over the retrieved payload bytes",
    ),
    (
        "requires the recomputed digest to match",
        "the recomputed digest exactly equals the durable digest",
    ),
    (
        "fails closed before parsing",
        "any mismatch fails closed before parsing or evaluation",
    ),
    (
        "refuses to treat the name as integrity proof",
        "do not treat the key name alone as integrity proof",
    ),
    (
        "confines the read to the assessment role",
        "read only by the separately authorized assessment role and process",
    ),
    # ------------------------------------------------- write-only, unchanged
    ("keeps acquisition write-only", "acquisition performs conditional `putobject` only"),
    ("keeps headobject at zero", "acquisition performs no `headobject`"),
    ("keeps getobject at zero", "acquisition performs no `getobject`"),
    ("keeps getobjectattributes at zero", "acquisition performs no `getobjectattributes`"),
    ("keeps listing at zero", "acquisition performs no s3 listing"),
    (
        "keeps a 412 uninformative about content",
        "a 412 establishes neither identical nor different content",
    ),
    (
        "introduces no adoption or deduplication",
        "no compare, adopt, resume or deduplicate behaviour exists",
    ),
    ("keeps the bronze outcome", "bronze_name_occupied"),
    ("keeps the locator outcome", "locator_name_occupied"),
    (
        "keeps the safe-direction false negative",
        "an ambiguous write followed by a 412 remains a safe-direction false negative",
    ),
    (
        "counts no occupied object as evidence",
        "no occupied object is counted as retained or verified evidence",
    ),
    (
        "records that collision handling is not relaxed",
        "it does not relax collision handling",
    ),
    # -------------------------------------------------------------- isolation
    (
        "confines the later builder to the qualification package",
        "confined to the adr-0018 / adr-0019 / adr-0020 qualification code",
    ),
    (
        "leaves the shared payload key builder alone",
        "not change the shared general-purpose `bronze_payload_key`",
    ),
    ("leaves the shared store alone", "not change `s3researchobjectstore`"),
    (
        "leaves adr-0017 publication behaviour alone",
        "not change adr-0017 publication behaviour",
    ),
    (
        "keeps the later builder unreachable from adr-0017",
        "structurally unreachable from adr-0017",
    ),
    (
        "stops rather than widening the shared contract",
        "it must stop for a new architecture decision",
    ),
    # --------------------------------------------------------- durable schema
    ("introduces no locator field", "no new locator field is introduced"),
    ("introduces no private subject value", "no private subject value is introduced"),
    ("introduces no additional read", "no additional s3 read is introduced"),
    ("introduces no listing", "no s3 list is introduced"),
    ("introduces no provider request", "no provider request is introduced"),
    (
        "keeps the record carrying the key and digest",
        "continues to carry the exact payload key and digest",
    ),
    (
        "records the changed value pattern",
        "the permitted value pattern of the qualification payload-key field changes",
    ),
    (
        "defers the validator correction to the implementation gate",
        "must later be corrected to reconstruct the qualification-specific key",
    ),
    ("records that no migration is needed", "no migration is authorized or needed"),
    (
        "renames, copies, deletes and reads nothing already published",
        "no already-published private evidence is being renamed, copied, deleted or read",
    ),
    (
        "records that no new durable field is required",
        "the merged durable record already carries enough to reconstruct the new key, so no new "
        "field is required",
    ),
    # ----------------------------------------------------------- arithmetic
    ("keeps the bronze put count", "bronze putobject: exactly 144"),
    ("keeps the acquisition put envelope", "total putobject: 145 to 147"),
    ("keeps acquisition headobject at zero", "headobject: exactly 0"),
    ("keeps acquisition getobject at zero", "getobject: exactly 0"),
    ("keeps the two-run total", "290 to 294"),
    ("keeps the assessment envelope", "195 to 196 total"),
    ("keeps the package envelope", "485 to 490"),
    ("keeps the deadline", "d = 1800 seconds"),
    ("keeps the locator reserve inequality", "l >= 3 * t_s3 + c"),
    ("keeps the per-request obligation", "per-request s3 obligation = 3 * t_s3"),
    ("keeps the admission inequality", "remaining >= t_req + 3 * t_s3 + l"),
    (
        "records that the identity adds no operation",
        "the new key identity introduces no additional operation",
    ),
    # ------------------------------------------------------------- scenarios
    (
        "resolves the same-execution different-bytes case",
        "must not permit two competing payloads for one governed request to be accepted as a "
        "complete observation",
    ),
    (
        "binds the record and locator to one terminal outcome",
        "bind only the single governed terminal outcome",
    ),
    # --------------------------------------------------------- consequences
    (
        "records the loss of global deduplication",
        "qualification payloads are no longer globally deduplicated by payload digest",
    ),
    ("records the duplicate storage cost", "identical bytes may be stored more than once"),
    (
        "records the later correction the blocked pull request needs",
        f"pr {ADR_0020_BLOCKED_PR} requires a later code correction before review or merge",
    ),
    ("bounds the storage cost", "maximum 96 qualification payload objects"),
    (
        "refuses to generalize the choice",
        "do not generalize this choice to ingestion or control storage",
    ),
    # --------------------------------------------------- the blocked pull request
    (
        "records the blocked pull request's state",
        f"pr {ADR_0020_BLOCKED_PR} is open, non-draft, unmerged, blocked on architecture, and "
        "untouched by this proposal",
    ),
    (
        "records that the blocked pull request was not reviewed or merged here",
        f"pr {ADR_0020_BLOCKED_PR} cannot be reviewed or merged until this adr is independently "
        "reviewed, merged and synchronized",
    ),
    ("records that the correction has not begun", "that correction is a separate gate and is"),
    # ----------------------------------------------------------------- gates
    ("leaves g1 open", "g1 open"),
    ("leaves g2 open", "g2 open"),
    ("keeps live trading disabled", "hard-disabled"),
    # ------------------------------------------- the adjacent post-merge note
    #
    # ADDED on the merge, not substituted for the conditional status line above.
    # The ADR keeps the text it was written with -- PROPOSED, no authority until
    # merged -- because that is what it said while its pull request was open, and
    # a decision record is not rewritten when the world moves. The note beside it
    # is what stops that conditional line from being read as current.
    ("records that the condition was satisfied", "the condition above has since been satisfied"),
    ("names the merge commit", ADR_0020_MERGE_COMMIT),
    ("names the approved head", ADR_0020_APPROVED_HEAD),
    (
        "records the conditional effectiveness event",
        "adr-0020's conditional effectiveness event has occurred",
    ),
    ("keeps the proposed period historical", ADR_0020_HISTORICAL_PROPOSED),
    (
        "keeps what governed before the merge",
        "adr-0018 as amended by adr-0019 governed the qualification payload identity before the "
        f"pr {ADR_0020_PR} merge",
    ),
    ("preserves the earlier state", "preserved as history, not rewritten"),
    (
        "records that the merge approved architecture only",
        "the merge approved architecture only, and authorized no implementation, no "
        "infrastructure mutation, no deployment and no execution",
    ),
    ("carries the adjacent historical note", "this section is a historical note added after the"),
    ("records the accepted architecture status", "adr-0020 architecture: accepted / in force"),
    (
        "records the amendment as authoritative",
        "adr-0020's amendment is now authoritative architecture",
    ),
    ("keeps adr-0019 in force after the merge", "adr-0019 remains accepted / in force"),
    (
        "keeps the shared store unchanged after the merge",
        "the shared s3researchobjectstore remains unchanged",
    ),
    # ------------------------------------------- the implementation, merged
    #
    # Inverted on the PR #48 merge, not deleted. Every spelling replaced here
    # moved into :data:`ADR_0020_SELF_FORBIDDEN`, so a revert to "not
    # implemented" fails rather than merely going unchecked -- the treatment
    # ADR-0017's, ADR-0018's and ADR-0019's guards were each given.
    #
    # Sections 1-8 are NOT touched by any of this. They record the amendment as
    # it was proposed and reviewed, PR #48's state on that day included, and a
    # decision record is not rewritten when the world moves. Every clause below
    # belongs to the post-merge section.
    (
        "records that the implementation merged",
        "adr-0020 implementation: merged / dormant / offline-conforming",
    ),
    ("records that a key builder exists", "a qualification payload-key builder exists"),
    (
        "records that the dormant implementation conforms offline",
        "the current dormant implementation is offline-conforming under the authoritative "
        "architecture",
    ),
    (
        "records the satisfied prerequisite",
        "the adr-0020 implementation-correction prerequisite is satisfied",
    ),
    (
        # A prerequisite met is not a permission granted, and this is the one
        # sentence that keeps those apart.
        "records that merging an implementation authorized nothing further",
        "merging an implementation authorizes no infrastructure, no deployment and no run",
    ),
    (
        "refuses to read offline conformance as deployment",
        "offline-conforming is not deployed, not active, not operational, not authorized to run "
        "and not empirically validated",
    ),
    (
        "records that infrastructure stays unauthorized",
        "infrastructure design and mutation: not authorized / not implemented",
    ),
    (
        "records that acceptance is not authorization",
        "acceptance of adr-0020 is not authorization to implement or execute it",
    ),
    # ---------------------------------- the blocked pull request, after the merge
    (
        "records the blocked pull request's merge",
        f"pr {ADR_0020_BLOCKED_PR} is merged, and it was merged under a separate, later "
        "authorization",
    ),
    ("names the correction merge commit", ADR_0019_IMPL_MERGE_COMMIT),
    ("names the approved implementation head", ADR_0019_IMPL_APPROVED_HEAD),
    (
        "records that the correction merged",
        f"pr {ADR_0020_BLOCKED_PR} correction against adr-0020: merged",
    ),
    (
        "records that the separate correction has been made",
        f"the separate correction pr {ADR_0020_BLOCKED_PR} required has since been made, "
        "independently reviewed and merged",
    ),
    (
        # The pre-correction period stays a fact about those days.
        "keeps the pre-correction state historical",
        f"before pr {ADR_0020_BLOCKED_PR} merged no qualification payload-key builder existed",
    ),
    (
        "records that the proposal and its merge left the pull request alone",
        f"pr {ADR_0020_BLOCKED_PR} was untouched by this decision and by its merge",
    ),
    (
        "names the next possible gate",
        "the next possible gate is a separate owner authorization for offline infrastructure, "
        "terraform and iam preparation",
    ),
)

#: Claims ADR-0020 must never make. Every entry is a positive assertion, so an
#: honest negation does not contain one of them.
#:
#: Inverted on the merge, not deleted: the four spellings that refused an
#: acceptance claim while the pull request was open are gone -- the ADR now
#: carries its post-merge note -- and the pre-merge spellings took their place, so
#: a revert to "still proposed" is caught rather than merely un-asserted.
ADR_0020_SELF_FORBIDDEN: Final[tuple[str, ...]] = (
    "adr-0020 is still proposed",
    "adr-0020 has not merged",
    f"pr {ADR_0020_PR} is open",
    f"pr {ADR_0020_PR} remains unmerged",
    "this adr authorizes an implementation",
    "a 412 establishes identical content",
    "the occupied object may be read",
    "acquisition may use headobject",
    "acquisition may resolve a collision",
    "acquisition deduplicates",
    "identical occupied content may be adopted",
    f"pr {ADR_0020_BLOCKED_PR} is ready to merge",
    f"pr {ADR_0020_BLOCKED_PR} may be merged",
    "run a is authorized",
    "run b is authorized",
    "the combined assessment is authorized",
    "infrastructure is authorized",
    "infrastructure is ready to deploy",
    "the shared bronze payload key changes",
    "g1 is closed",
    "g2 is closed",
    # -------------------------- the superseded pre-implementation state
    #
    # Released on the PR #48 merge, and replaced rather than dropped. Six entries
    # left this list because they became TRUE -- "adr-0020 implementation:
    # authorized", "the qualification payload-key builder exists", "the
    # production implementation conforms", "the request-scoped payload identity
    # is implemented", "pr #48 is merged" and "pr #48 has been corrected" -- and
    # a denylist that forbids the truth forces a document to lie. Every spelling
    # of the state that merge ended took their place, so a revert fails rather
    # than merely going unasserted. None is a substring of an honest post-merge
    # sentence: "before pr #48 merged no qualification payload-key builder
    # existed" is history, and is required above.
    "adr-0020 implementation: not authorized / not implemented",
    "no qualification payload-key builder exists",
    "the current dormant implementation is therefore not deployable under the authoritative "
    "architecture",
    "infrastructure design: blocked pending implementation correction",
    f"pr {ADR_0020_BLOCKED_PR} is still open, non-draft, unmerged and untouched",
    f"pr {ADR_0020_BLOCKED_PR} ready for review or merge: no",
    f"pr {ADR_0020_BLOCKED_PR} correction against adr-0020: not begun",
    "requires a separate correction against the accepted adr-0020 design",
    "the next separately authorized implementation gate is correcting pr "
    f"{ADR_0020_BLOCKED_PR} against adr-0020",
    # ------------------------------------------------- the forward drift
    #
    # Merged, dormant and offline-conforming is the whole claim. Deployed, run
    # and validated are three further gates, and none of them has been crossed.
    "the request-scoped payload identity is deployed",
    "the qualification payload-key builder is deployed",
    "the production implementation is deployed",
    "adr-0020 implementation: deployed",
    "the implementation has been empirically validated",
)

#: What **both** status documents must independently say about ADR-0020, **in
#: ADR-0020's own status section**.
#:
#: Independently, and for the reason the ADR-0018 and ADR-0019 blocks give:
#: merged main has twice carried a fact in one status file and a stale
#: contradiction in the other, so each phrase is required in *each* file rather
#: than in their concatenation.
#:
#: Section-scoped, and every entry belongs to that section -- there is no
#: document-global remainder, so the collection is not split. Scanned flat
#: against the whole file, 46 of these 49 phrases were satisfied by a copy
#: standing somewhere else: ADR-0018's and ADR-0019's status blocks spell "run a:
#: not authorized / not run", "infrastructure design and mutation: blocked" and
#: "adr-0020 implementation: not authorized / not implemented" for their own
#: reasons. Deleting one from ADR-0020's section left the neighbour's copy behind
#: and the audit stayed green. Only three phrases -- "adr-0020 architecture:
#: accepted / in force", "pr #49: merged" and "conditional effectiveness event:
#: occurred" -- were unique to the file, which is why deleting the *whole*
#: section was caught while gutting it clause by clause was not.
#:
#: The section is located by :func:`scan_adr_0020_status_sections`, from the
#: heading and never from a phrase in this list: a scope anchored on its own
#: contents would vanish exactly when the content it guards was deleted.
ADR_0020_STATUS_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    # ------------------------------------------ the merge, and what it approved
    #
    # Inverted on the merge, not deleted: the proposed-state spellings moved into
    # :data:`ADR_0020_STATUS_FORBIDDEN` below, so a revert to the pre-merge
    # wording fails rather than merely going unchecked.
    ("records the accepted architecture status", "adr-0020 architecture: accepted / in force"),
    ("records the merge", f"pr {ADR_0020_PR}: merged"),
    ("names the merge commit", ADR_0020_MERGE_COMMIT),
    ("names the approved head", ADR_0020_APPROVED_HEAD),
    ("records the conditional effectiveness event", "conditional effectiveness event: occurred"),
    ("keeps the proposed period historical", ADR_0020_HISTORICAL_PROPOSED),
    ("records that the merge approved architecture only", "the merge approved architecture only"),
    ("records that architecture acceptance is complete", "architecture acceptance: complete"),
    (
        "records that the architecture blocker is resolved",
        "the architecture blocker that prevented adr-0020 from being authoritative is resolved",
    ),
    (
        # Inverted on the PR #48 merge. The architecture blocker was resolved by
        # PR #49 and the implementation blocker by PR #48, and the two are still
        # reported as two, because collapsing them is how an accepted design
        # starts reading as a deployed one.
        "records that the implementation blocker is resolved offline",
        "the implementation blocker is resolved as well, offline",
    ),
    ("names the collision", "the legitimate duplicate-payload collision"),
    (
        "records that the blocked pull request obeyed the accepted rule",
        f"pr {ADR_0020_BLOCKED_PR} is not defective for obeying adr-0019",
    ),
    (
        "records the three key inputs",
        "the qualification payload key binds the execution identity, the request ordinal and the "
        "payload digest",
    ),
    (
        "keeps private subject values out of the key",
        "no provider subject value appears in a qualification payload key",
    ),
    (
        "records that the write-only policy is unchanged",
        "adr-0020 preserves adr-0019's write-only collision policy unchanged",
    ),
    ("keeps acquisition write-only", "acquisition remains conditional `putobject` only"),
    (
        "keeps both occupied-name outcomes",
        "bronze_name_occupied` and `locator_name_occupied` are unchanged",
    ),
    (
        "records the narrow supersession",
        "adr-0020 supersedes only the qualification payload-key identity rule",
    ),
    ("leaves adr-0017 alone", "adr-0020 does not supersede adr-0017"),
    (
        "leaves the shared contracts alone",
        "adr-0020 changes no shared general-purpose bronze or s3researchobjectstore contract",
    ),
    ("introduces no locator field", "adr-0020 introduces no locator field"),
    (
        "introduces no additional operation",
        "adr-0020 introduces no additional s3 operation",
    ),
    ("keeps the package envelope", "adr-0020 preserves the 485 to 490 package envelope"),
    (
        "keeps the deadline arithmetic",
        "adr-0020 preserves the deadline arithmetic l >= 3 * t_s3 + c",
    ),
    (
        "requires the reconstructed key comparison",
        "assessment reconstructs the qualification payload key and compares it exactly",
    ),
    (
        "requires the digest recomputation",
        "assessment recomputes sha-256 over the retrieved payload bytes and refuses on any "
        "mismatch",
    ),
    # -------------------------------------------- the implementation, merged
    #
    # Inverted on the PR #48 merge, not deleted: every spelling replaced here
    # moved into :data:`ADR_0020_STATUS_FORBIDDEN`, so a revert to the
    # pre-correction wording fails rather than merely going unchecked.
    (
        "records that the implementation merged",
        "adr-0020 implementation: merged / dormant / offline-conforming",
    ),
    (
        "records that the production implementation merged",
        "production implementation: merged / dormant / offline-conforming",
    ),
    ("records that a key builder exists", "a qualification payload-key builder exists"),
    (
        "records the dormant offline-conforming implementation",
        "adr-0018 merged implementation: dormant / offline-conforming",
    ),
    (
        "records the satisfied prerequisite",
        "the adr-0020 implementation-correction prerequisite is satisfied",
    ),
    (
        # A prerequisite met is not a permission granted. This sentence is the
        # whole distance between "the code is corrected" and "build the
        # infrastructure", and it is required in both documents for that reason.
        "records that the prerequisite authorizes nothing",
        "satisfying the implementation prerequisite does not itself authorize or begin "
        "infrastructure work",
    ),
    (
        "names the next possible gate",
        "the next possible gate is a separate owner authorization for offline infrastructure, "
        "terraform and iam preparation",
    ),
    (
        "refuses to read offline conformance as deployment",
        "offline-conforming is not deployed, not active, not operational, not authorized to run "
        "and not empirically validated",
    ),
    (
        "records that merging an implementation authorized nothing further",
        "merging an implementation authorizes no infrastructure, no deployment and no run",
    ),
    # ---------------------------------- the blocked pull request, after the merge
    (
        "records the implementation merge",
        f"pr {ADR_0020_BLOCKED_PR}: merged",
    ),
    ("names the correction merge commit", ADR_0019_IMPL_MERGE_COMMIT),
    ("names the approved implementation head", ADR_0019_IMPL_APPROVED_HEAD),
    (
        "records that the correction merged",
        f"pr {ADR_0020_BLOCKED_PR} correction against adr-0020: merged",
    ),
    (
        # Present tense would now be false -- a later, separately authorized
        # correction did touch it. Past tense about the proposal and its merge
        # stays exactly true, and is what is required.
        "records that the proposal and its merge left the pull request alone",
        f"pr {ADR_0020_BLOCKED_PR} was untouched by the adr-0020 proposal and by its merge",
    ),
    (
        "keeps the pre-correction state historical",
        f"while pr {ADR_0020_BLOCKED_PR} was open it was not ready for review or merge and its "
        "correction had not begun",
    ),
    # ------------------------------------------ what the merge did not authorize
    (
        "keeps infrastructure unauthorized",
        "infrastructure design and mutation: not authorized / not implemented",
    ),
    ("keeps terraform and iam unauthorized", "terraform / iam: not authorized / not implemented"),
    ("records that nothing was deployed", "deployment: not performed"),
    ("records that nothing was executed", "execution: zero"),
    ("records that run a has not run", "run a: not authorized / not run"),
    ("records that run b has not run", "run b: not authorized / not run"),
    (
        "records that the assessment has not run",
        "combined assessment: not authorized / not run",
    ),
    # ------------------------------------------------- what is preserved around it
    ("keeps adr-0019 in force", "adr-0019: accepted / in force"),
    ("keeps the third adr-0017 attempt unauthorized", "third adr-0017 attempt: not authorized"),
    ("leaves g1 open", "g1: open"),
    ("leaves g2 open", "g2: open"),
    ("records that no provider is selected", "provider selected: none"),
    ("records that phase 3 is not complete", "phase 3: not complete"),
    ("keeps control deferred", "control: deferred"),
    ("keeps live trading disabled", "live trading: hard-disabled"),
)

#: Claims neither status document may make about ADR-0020. Each is a positive
#: assertion, so the honest negations above do not contain any of them.
ADR_0020_STATUS_FORBIDDEN: Final[tuple[str, ...]] = (
    # ------------------------------------------- the superseded proposed state
    #
    # Moved here on the merge rather than deleted, so a revert to the pre-merge
    # wording is caught rather than merely un-asserted. None of these is a
    # substring of an honest post-merge sentence: "adr-0020 was proposed" is
    # historical and allowed, and "not authorized / not implemented" is not
    # "authorized".
    "adr-0020: proposed / not in force",
    "adr-0020 carries no authority until it is independently reviewed and merged",
    "adr-0020 is still proposed",
    "adr-0020 has not merged",
    "not registered as a merged adr",
    f"pr {ADR_0020_BLOCKED_PR}: open / unmerged / blocked on architecture",
    f"pr {ADR_0020_PR} is open",
    f"pr {ADR_0020_PR} remains unmerged",
    "the conditional effectiveness event has not occurred",
    # -------------------------- the superseded pre-implementation state
    #
    # Released on the PR #48 merge, and replaced rather than dropped. Eight
    # entries left this list because they became TRUE -- "adr-0020
    # implementation: authorized", "the request-scoped payload identity is
    # implemented", "the qualification payload-key builder exists", "the
    # production implementation conforms", "pr #48 has been corrected", "pr #48
    # was corrected", "pr #48 is merged" and "pr #48 was reviewed" -- and a
    # denylist that forbids the truth is one that forces a document to lie.
    # Every spelling of the state that merge ended took their place, so a revert
    # fails rather than merely going unasserted. None is a substring of an
    # honest post-merge sentence: "while pr #48 was open it was not ready for
    # review or merge and its correction had not begun" is history, and is
    # required above.
    "adr-0020 implementation: not authorized / not implemented",
    "production implementation: not authorized / not implemented",
    "no qualification payload-key builder exists",
    "adr-0018 merged implementation: dormant / nonconforming",
    "the implementation blocker remains",
    f"pr {ADR_0020_BLOCKED_PR} state: open / unmerged",
    f"pr {ADR_0020_BLOCKED_PR} ready for review or merge: no",
    f"pr {ADR_0020_BLOCKED_PR} correction against adr-0020: not begun",
    f"pr {ADR_0020_BLOCKED_PR} is untouched by the adr-0020 proposal",
    "requires a separate correction against the accepted adr-0020 design",
    "the next separately authorized implementation gate is correcting pr "
    f"{ADR_0020_BLOCKED_PR} against adr-0020",
    "infrastructure design and mutation: blocked",
    # ------------------------------------------------------ the forward drift
    #
    # Merged, dormant and offline-conforming is the whole claim. Deployed, run
    # and validated are three further gates, and none has been crossed.
    f"pr {ADR_0020_BLOCKED_PR} is ready to merge",
    f"pr {ADR_0020_BLOCKED_PR} is mergeable",
    "the request-scoped payload identity is deployed",
    "the qualification payload-key builder is deployed",
    "the production implementation is deployed",
    "adr-0020 implementation: deployed",
    "adr-0020 implementation: authorized to run",
    "the implementation has been empirically validated",
    "infrastructure is authorized",
    "infrastructure is implemented",
    "infrastructure is deployed",
    "deployment: performed",
    "execution: one",
    "run a is authorized",
    "run b is authorized",
    "the combined assessment is authorized",
    "phase 3 is complete",
    "control publication has occurred",
    "live trading is enabled",
    "acquisition may read an occupied object",
    "an occupied object may be adopted",
    "identical occupied content may be adopted",
    "acquisition deduplicates objects",
    "acquisition may resolve a collision with headobject",
)

#: What the implementation plan must say about ADR-0020. The plan is where the
#: ceilings are read from, so a plan that still sent a reader to an identity that
#: cannot reach a complete run would be sending them to a run nobody can finish.
ADR_0020_PLAN_REQUIRED: Final[tuple[tuple[str, str], ...]] = (
    ("records the accepted architecture status", "adr-0020 architecture: accepted / in force"),
    ("records the merge", f"pr {ADR_0020_PR} merged"),
    ("names the merge commit", ADR_0020_MERGE_COMMIT),
    ("names the approved head", ADR_0020_APPROVED_HEAD),
    ("keeps the proposed period historical", ADR_0020_HISTORICAL_PROPOSED),
    (
        "records that the identity is now authoritative",
        "the request-scoped payload identity is now authoritative architecture",
    ),
    ("names the collision", "the legitimate duplicate-payload collision"),
    (
        "records that the blocked pull request obeyed the accepted rule",
        f"pr {ADR_0020_BLOCKED_PR} is not defective for obeying adr-0019",
    ),
    (
        "records the three key inputs",
        "the qualification payload key binds the execution identity, the request ordinal and the "
        "payload digest",
    ),
    (
        "records that the write-only policy is unchanged",
        "adr-0020 preserves adr-0019's write-only collision policy unchanged",
    ),
    (
        "records that the implementation merged",
        "adr-0020 implementation: merged / dormant / offline-conforming",
    ),
    (
        "records that the implementation was separately authorized",
        "the implementation has since been separately authorized, made, independently reviewed "
        "and merged",
    ),
    ("records that a key builder exists", "a qualification payload-key builder exists"),
    (
        "records the implementation merge",
        f"pr {ADR_0020_BLOCKED_PR}: merged",
    ),
    ("names the correction merge commit", ADR_0019_IMPL_MERGE_COMMIT),
    ("names the approved implementation head", ADR_0019_IMPL_APPROVED_HEAD),
    (
        "records that the correction merged",
        f"pr {ADR_0020_BLOCKED_PR} correction against adr-0020: merged",
    ),
    (
        "keeps the pre-correction state historical",
        f"before pr {ADR_0020_BLOCKED_PR} merged no qualification payload-key builder existed",
    ),
    (
        "records the satisfied prerequisite",
        "the adr-0020 implementation-correction prerequisite is satisfied",
    ),
    (
        "records that the prerequisite authorizes nothing",
        "satisfying the implementation prerequisite does not itself authorize or begin "
        "infrastructure work",
    ),
    (
        "names the next possible gate",
        "the next possible gate is a separate owner authorization for offline infrastructure, "
        "terraform and iam preparation",
    ),
    (
        "records that merging an implementation authorized nothing further",
        "merging an implementation authorizes no infrastructure, no deployment and no run",
    ),
    (
        "refuses to read offline conformance as deployment",
        "offline-conforming is not deployed, not active, not operational, not authorized to run "
        "and not empirically validated",
    ),
    (
        "keeps infrastructure unauthorized",
        "infrastructure design and mutation: not authorized / not implemented",
    ),
    (
        "records that nothing was deployed or executed",
        "no deployment or empirical execution has occurred",
    ),
)

#: The exact level-three heading that opens ADR-0020's current-status section in
#: both status documents.
#:
#: The anchor is the heading, never a phrase being tested: a section located by
#: one of its own required phrases would go missing the moment that phrase was
#: deleted, which is the deletion the guard exists to catch.
#:
#: Heading drift is not silently tolerated. A renamed heading finds no section
#: and fails, so the rename has to be made deliberately here, in a reviewed
#: change, rather than quietly detaching every section-scoped guard below.
ADR_0020_STATUS_HEADING: Final = (
    "The legitimate duplicate-payload collision, and ADR-0020 — ACCEPTED, and the merged "
    "implementation"
)

#: The level-four subsections ADR-0020's status section is allowed to contain.
#:
#: Anything else carrying a heading inside the extracted region means the section
#: swallowed a neighbour -- the boundary drifted, because a terminator was deleted
#: or demoted -- and a section that has drifted is measuring somebody else's text.
ADR_0020_STATUS_SUBSECTIONS: Final[tuple[str, ...]] = (
    "The history, in order",
    "The conflict, stated exactly",
    "The authoritative identity",
    "What ADR-0020 does not change",
    "The implementation gap — closed offline, and stated plainly",
    "Status",
)

#: The level at which the ADR-0020 status heading, and only that heading, may sit.
ADR_0020_STATUS_HEADING_LEVEL: Final = 3

#: A Markdown ATX heading: one to six hashes, whitespace, a title, and an optional
#: run of closing hashes. Setext underlining is not used by either document.
_ATX_HEADING: Final = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<title>.*?)[ \t]*#*[ \t]*$")

#: A fenced code block opener or closer: at least three backticks or tildes.
_CODE_FENCE: Final = re.compile(r"^(?P<fence>`{3,}|~{3,})")


class Adr0020SectionScan(NamedTuple):
    """Every ADR-0020 status section a document carries, and its structure defects.

    ``sections`` is the verbatim text of each match, heading included, so a caller
    can require *exactly one* -- a duplicated, nested or heading-only second copy
    is two answers to one question, and a phrase scan over the flattened document
    cannot tell them apart because a duplicate only ever adds occurrences.

    ``defects`` is reported separately rather than folded into the count, for the
    reason :class:`RetiredArithmeticScan` reports ``balanced`` separately: a
    malformed structure can yield exactly one plausible-looking section, and a
    vacuous pass is what the caller must be able to refuse.
    """

    sections: tuple[str, ...]
    defects: tuple[str, ...]


def scan_adr_0020_status_sections(text: str) -> Adr0020SectionScan:
    """Extract ADR-0020's status section(s) from a document, by heading.

    Pure and deterministic: it takes text, carries no module state between calls,
    opens no file and reaches no service. Two documents scanned in either order
    give the same answer, and one document's scan cannot satisfy the other's.

    A section runs from its level-three heading to the next heading of level three
    or higher, so its own ``####`` subsections stay inside it and the next ``###``
    or ``##`` ends it. Headings inside fenced code blocks are not headings --
    README.md carries a shell comment that begins with ``#`` inside a fence, and a
    scanner that read it as a level-one heading would cut a section short.

    Ambiguous structure is refused rather than resolved: the status title carried
    at any level other than three is a defect, and so is a foreign heading inside
    an extracted section.
    """
    lines = text.splitlines(keepends=True)
    headings: list[tuple[int, int, str]] = []
    defects: list[str] = []
    fence: str | None = None
    for index, raw in enumerate(lines):
        line = raw.rstrip("\n")
        opener = _CODE_FENCE.match(line)
        if opener is not None:
            token = opener.group("fence")
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        heading = _ATX_HEADING.match(line)
        if heading is None:
            continue
        level = len(heading.group("hashes"))
        title = heading.group("title").strip()
        headings.append((index, level, title))
        if title == ADR_0020_STATUS_HEADING and level != ADR_0020_STATUS_HEADING_LEVEL:
            defects.append(f"line {index + 1}: the ADR-0020 status heading sits at level {level}")

    starts = [
        position
        for position, (_, level, title) in enumerate(headings)
        if level == ADR_0020_STATUS_HEADING_LEVEL and title == ADR_0020_STATUS_HEADING
    ]
    sections: list[str] = []
    for position in starts:
        begin = headings[position][0]
        end = len(lines)
        for index, level, _title in headings[position + 1 :]:
            if level <= ADR_0020_STATUS_HEADING_LEVEL:
                end = index
                break
        sections.append("".join(lines[begin:end]))
        for index, _level, title in headings[position + 1 :]:
            if index >= end:
                break
            if title not in ADR_0020_STATUS_SUBSECTIONS:
                defects.append(f"line {index + 1}: foreign heading inside the section: {title}")
    return Adr0020SectionScan(tuple(sections), tuple(defects))


#: Path separators and placeholder brackets a sample key legitimately contains.
#: Everything else in a sample key segment is checked against the subject grammar
#: below, because a worked example is exactly where a real ticker gets typed in.
ADR_0020_KEY_LINE_MARKERS: Final[tuple[str, ...]] = ("sha256/", "licensed/bronze/", "/requests/")


def _sample_key_subject_segments(text: str) -> list[str]:
    """Every subject-shaped path segment in a document's sample keys.

    Expected: none. A sample key is where a real security symbol gets typed in
    while nobody is looking, and a placeholder in angle brackets does not match
    the subject grammar -- the bracket is the first character, and the grammar
    requires a capital letter there.
    """
    found: list[str] = []
    for raw in text.splitlines():
        line = raw.replace("`", "").strip()
        if not any(marker in line for marker in ADR_0020_KEY_LINE_MARKERS):
            continue
        for segment in line.split("/"):
            candidate = segment.strip().strip(".,;:)(")
            if _SUBJECT_SHAPED.match(candidate) and candidate not in _NOT_A_SUBJECT:
                found.append(candidate)
    return found


class RetiredArithmeticScan(NamedTuple):
    """One document's retired-arithmetic surfaces.

    ``findings`` is every retired figure presented as current: ``(line number,
    label)``. ``blocks`` counts the delimited historical regions. ``balanced``
    is false for an unclosed, unopened or nested marker.

    ``balanced`` is separate because an unclosed BEGIN swallows the rest of the
    file and would empty ``findings`` -- a vacuous pass is what the caller must
    be able to refuse, so it is reported rather than folded in.
    """

    findings: tuple[tuple[int, str], ...]
    blocks: int
    balanced: bool


def scan_retired_arithmetic(text: str) -> RetiredArithmeticScan:
    """Find retired ADR-0018 arithmetic that a document presents as current.

    A retired figure may stand only where a reader cannot mistake it: inside a
    delimited historical block, or on a line carrying one of the strict
    :data:`RETIRED_ARITHMETIC_MARKERS`. A retirement sentence elsewhere in the file
    does not count, which is exactly the defect this exists to catch -- ADR-0019
    retired the figures, both status documents said so once, and both still
    carried the old numbers unlabelled in the detailed ADR-0018 narrative.
    """
    findings: list[tuple[int, str]] = []
    depth = 0
    blocks = 0
    balanced = True
    for number, raw in enumerate(text.splitlines(), start=1):
        line = " ".join(raw.replace("`", "").lower().split())
        if RETIRED_ARITHMETIC_BEGIN in line:
            balanced = balanced and depth == 0
            depth += 1
            blocks += 1
            continue
        if RETIRED_ARITHMETIC_END in line:
            balanced = balanced and depth == 1
            depth = max(depth - 1, 0)
            continue
        if depth or any(marker in line for marker in RETIRED_ARITHMETIC_MARKERS):
            continue
        for label, pattern in RETIRED_ARITHMETIC:
            if re.search(pattern, line):
                findings.append((number, label))
                break
    return RetiredArithmeticScan(tuple(findings), blocks, balanced and depth == 0)


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
    print("[1/21] Closed vocabularies are defined where they are used")
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
    print("\n[2/21] Source and derived envelopes stay disjoint")
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
    print("\n[3/21] Every declared temporal semantics has its required anchor")
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
    print("\n[4/21] Exact and bound derivations name the correct fields")
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
    print("\n[5/21] Normative rules use the current resolved model")

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
    print("\n[6/21] Entities keep source and derived rows apart")

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
    print("\n[7/21] Unusability is decided by resolved values, not by a derivation")

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
    print("\n[8/21] Manifest records per-axis timing and coverage evidence")
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
    print("\n[9/21] Resolved-timing wording, closure rules and current status")

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
    print("\n[10/21] No document refers to a retired field name")
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
    print("\n[11/21] Blueprint V3.0 adoption is recorded consistently")

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
    print("\n[12/21] The provider decision packet decides nothing and closes no gate")

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
    print("\n[13/21] The cloud data plane is described, not built -- and the Terraform enforces it")

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
    print("\n[14/21] The Sharadar licence decision closes G3, and nothing else")
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
    print("\n[15/21] The Sharadar implementation authorization is code-only, and G1 stays open")
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
    print("\n[16/21] The qualification subscription is purchased, and still authorizes no access")
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
            f"{name} no longer carries the unscoped provider-credentialing row",
            not [
                row
                for row in body.splitlines()
                if row.lstrip().startswith("|")
                and STALE_PROVIDER_CREDENTIAL_ROW_SUBJECT in row.split("|")[1]
            ],
            "one verdict over key existence, consumption and access goes stale when one moves",
        )
        f.check(
            f"{name} no longer calls Q7 and Q8 open pre-purchase blockers",
            "remain pre-purchase blockers" not in body,
            "ADR-0010 decided both; leaving the old wording would contradict the record",
        )

    # ------------------- 17. The S3 store is written, and has never reached AWS
    print("\n[17/21] The licensed S3 object store is implemented, and has touched nothing")
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
            f"{name} uses merge-stable status wording for the slice under review",
            "ACCEPTED EFFECTIVE ON MERGE OF PR #17" in body,
            "the same sentence must stay true on both sides of the merge",
        )
        f.check(
            f"{name} records PR #16 as merged rather than pending",
            "PR #16 MERGED" in body and "ACCEPTED EFFECTIVE ON MERGE OF PR #16" not in body,
            "a merge-stable status is stable, not permanent: once the merge happens the "
            "condition is satisfied and the document should say so",
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
            "retrieved, inspected, created, configured or bound anywhere under `src/`" in flat
            and "no bucket identifier is recorded here" in flat
            # ADR-0014 narrowed this once; the fifth binding-preflight attempt
            # narrowed it again. A *client* is constructed now -- the Sharadar one
            # from an injected transport, and one real AWS SDK client inside the
            # ADR-0015 operator entry point -- so the true claim is scoped to the
            # platform: no module under `src/` builds one.
            and "no module under `src/` constructs an SDK client" in flat
            and "One boundary outside `src/` has now supplied real values, once." in flat,
            "the store is safe because nothing binds it to AWS -- said as a claim about this "
            "repository, not as a claim about the owner's account",
        )
        f.check(
            f"{name} no longer claims that nothing calls the object store",
            "no module constructs a client or calls the store" not in flat,
            "ADR-0012's runtime calls it, on an injected store, and ADR-0014's composition "
            "root constructs it; the narrower true claim is that nothing binds it to AWS",
        )
        f.check(
            f"{name} names the composition root as the thing that is absent",
            "composition root" in flat.lower(),
            "'nothing calls the store' stopped being the control; 'nothing can build a real "
            "one to call' is",
        )

    # ------------------- 18. No status document carries a superseded current state
    print("\n[18/21] The status documents describe the current governance state, not a past one")

    for name, path in (
        ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
        ("README.md", REPO_ROOT / "README.md"),
    ):
        if not path.is_file():
            continue
        whole = read(path)
        # The WHOLE document, flattened, with every separator folded to one.
        #
        # A guard that inspected only the section it expected the claim in would
        # pass while a stale narrative sat three screens further down -- which is
        # exactly how this defect survived two rounds of review. And a guard that
        # matched one separator character would miss the same sentence typed with
        # another; the negative control found that hole twice here, once for a
        # hyphen against an em dash and once for a middle-dot-separated list.
        flat_whole = " ".join(
            whole.replace("**", "")
            .replace(EM_DASH, "-")
            .replace(EN_DASH, "-")
            .replace(MIDDLE_DOT, "-")
            .split()
        )

        for phrase, why in SUPERSEDED_CLAIMS:
            f.check(
                f"{name} no longer states {phrase!r}",
                phrase not in flat_whole,
                why,
            )

        # -- the obsolete matrix must not be reproduced here at all -----------
        #
        # Round 2 allowed a verbatim copy provided it was labelled historical.
        # That was not enough. A labelled copy is still a second authorization
        # matrix in a current-status document, and its contents were narrower
        # than the label admitted: the old list forbade "vendor account" and
        # "billing", which described what an implementation slice could do and
        # never described the owner's private affairs. An accepted ADR already
        # preserves its own boundary; a status document should link to it.
        for phrase, why in REPRODUCED_LEGACY_MATRIX:
            f.check(
                f"{name} does not reproduce {phrase!r}",
                phrase.lower() not in flat_whole.lower(),
                why,
            )
        f.check(
            f"{name} points at ADR-0009 for the historical boundary instead of copying it",
            "ADR-0009" in whole
            and (
                "holds the historical scope" in flat_whole
                or "original Slice-1 boundary lives in" in flat_whole
            ),
            "the history has to remain findable; it just must not be restated as a matrix",
        )
        f.check(
            f"{name} says the current matrix is the only one governing a session",
            "only one that governs a session now" in flat_whole
            or "the list below is what governs today" in flat_whole.lower(),
            "two matrices in one document is the defect; one of them has to be named as live",
        )
        f.check(
            f"{name} declines to govern owner-side account or billing activity",
            "neither governs nor records" in flat_whole,
            "an authorized purchase involved owner-side activity this repository must not "
            "forbid, infer or deny",
        )

        # -- the positive current state ---------------------------------------
        f.check(
            f"{name} records ADR-0009 and Slice 1 as accepted and in force",
            "ACCEPTED / IN FORCE" in whole and "PR #13 merged" in whole,
            "the merged state must be readable where a session looks first",
        )
        f.check(
            f"{name} states the top-level Slice-1 status as current, not event-conditional",
            "IMPLEMENTED / ACCEPTED - PR #13 MERGED - CODE ONLY" in flat_whole,
            "'accepted on merge' stopped being a status the moment the merge happened",
        )
        f.check(
            f"{name} keeps the published test token unauthorized, and says why that is not odd",
            "the published test token" in flat_whole
            and "not permission to run the harness" in flat_whole,
            "the harness being able to read it is not authorization to run it",
        )
        f.check(
            f"{name} records the qualification subscription as purchased and active",
            "PURCHASED / ACTIVE" in whole and "ADR-0010" in whole,
            "a completed purchase that a document calls unauthorized is a contradiction",
        )
        f.check(
            f"{name} records every merge-conditional ADR against a PR by number",
            "ACCEPTED EFFECTIVE ON MERGE OF PR #" in whole
            and "ACCEPTED on merge of the PR introducing it" not in whole,
            "'the PR introducing it' stops identifying anything once other PRs exist",
        )
        f.check(
            f"{name} keeps the real S3 writer off the currently-unauthorized list",
            "real S3 writer" not in flat_whole
            or "the real S3 writer arrived as its own separately authorized slice" in flat_whole
            or "the real S3 writer became its own slice" in flat_whole
            or "the real S3 writer was authorized as its own slice" in flat_whole,
            "ADR-0011 authorized it; listing it as unauthorized contradicts this very PR",
        )

        # -- what is still forbidden, stated as current ------------------------
        for forbidden in (
            "credential retrieval",
            "Services Data",
            "empirical qualification",
            "production ingestion",
        ):
            f.check(
                f"{name} still forbids {forbidden}",
                forbidden.lower() in flat_whole.lower(),
                "a purchase is not access, and the documents must keep saying so",
            )
        f.check(
            f"{name} keeps production-provider selection unauthorized",
            "production-provider selection" in flat_whole.lower()
            or "production provider is selected" in flat_whole.lower(),
            "buying a qualification subscription selected nothing",
        )
        f.check(
            f"{name} keeps G1 and G2 open after the purchase",
            "G1 OPEN" in whole or "**G1** provider selection" in whole,
            "no gate was resolved by ADR-0010 or by this slice",
        )
        f.check(
            f"{name} keeps ADR-0005 proposed and Phase 3 incomplete",
            "PROPOSED" in whole and "NOT COMPLETE" in whole.upper(),
            "neither is touched by a purchase or a storage backend",
        )

    # -- the Q7/Q8 disposition, as ADR-0010 actually recorded it ---------------
    readme_body = read(REPO_ROOT / "README.md")
    f.check(
        "README records Q7 as publicly unresolved and owner-accepted",
        "PUBLICLY_UNRESOLVED" in readme_body,
        "a decision is not a discovery; the document must not blur the two",
    )
    f.check(
        "README binds Sharadar price data to PROVIDER_DERIVED and PROVIDER_REALISTIC_PIT",
        "PROVIDER_DERIVED" in readme_body and "PROVIDER_REALISTIC_PIT" in readme_body,
        "an unresolved origin has exactly one safe classification",
    )
    f.check(
        "README forbids representing Sharadar price data as PUBLIC_PIT",
        "never represented as `PUBLIC_PIT`" in readme_body,
        "that prohibition is the whole consequence of an unresolved Q7",
    )
    f.check(
        "README records Q8 as publicly bounded, with measurement still required",
        "PUBLICLY_BOUNDED" in readme_body
        and "not certified earliest records" in readme_body.replace("**", ""),
        "documented depths are planning boundaries, not measured coverage",
    )
    f.check(
        "README defers the Q8 measurement to a separate authorization",
        "under a separate authorization" in readme_body.replace("**", ""),
        "measuring the delivered data is provider access, which is not authorized",
    )
    f.check(
        "README states the purchase closed no gate and selected no provider",
        "selected no production provider and closed no" in readme_body.replace("**", ""),
        "a purchase is not a selection",
    )
    f.check(
        "README scopes its credential claim to this repository",
        "no credential is stored, configured or bound by this repository"
        in readme_body.replace("**", ""),
        "whether a key exists in a vendor account is not something this repository knows",
    )

    # ------------------- 19. The qualification runtime exists, and cannot be run
    print("\n[19/21] The Sharadar qualification runtime core is dormant, and says so precisely")
    f.check(
        "ADR-0012 exists",
        ADR_RUNTIME.is_file(),
        f"missing: {ADR_RUNTIME}",
    )
    if ADR_RUNTIME.is_file():
        adr12 = read(ADR_RUNTIME)
        unquoted12 = [line.lstrip("> ") for line in adr12.replace("**", "").splitlines()]
        flat12 = " ".join(" ".join(unquoted12).split())

        f.check(
            "ADR-0012 is accepted on merge and not before",
            "Accepted \u2014 effective on the merge" in adr12 and "carries no authority" in adr12,
            "the ADR must carry no authority until its pull request merges",
        )
        f.check(
            "ADR-0012 records that nothing has been run against Sharadar or AWS",
            "Sharadar requests sent: ZERO" in adr12 and "AWS requests sent: ZERO" in adr12,
            "the whole point of the slice is that it is code, written while nothing can run",
        )
        f.check(
            "ADR-0012 names the composition root as the thing it deliberately omits",
            "composition root: NONE" in adr12
            and "no credential resolver, no client factory and no bucket binding exists" in flat12,
            "a runtime that could build its own client would need a credential",
        )
        f.check(
            "ADR-0012 rejects gating a composition root behind a flag",
            "A flag is a thing that can be set" in flat12
            and "Absence is checkable; a flag is a promise" in flat12,
            "absence is checkable; a flag is a promise",
        )
        f.check(
            "ADR-0012 states every hard ceiling and why each is that number",
            all(
                token in adr12
                for token in ("8", "96", "512 MiB", "32", "lowerable and never raisable")
            ),
            "a number with no stated reason is a number the next session will raise",
        )
        f.check(
            "ADR-0012 records that a limit above its ceiling is refused, not clamped",
            "refused rather than clamped" in flat12,
            "clamping lets a plan claim a budget it does not have",
        )
        f.check(
            "ADR-0012 records that validation is complete and happens first",
            "refused whole" in flat12 and "zero" in flat12.lower(),
            "a partly-wrong plan discovered mid-run leaves immutable objects nobody chose",
        )
        f.check(
            "ADR-0012 states that a failure reports rather than raises, and why",
            "no rollback" in flat12 and "states `partial`" in flat12,
            "an exception would discard the record of which immutable objects exist",
        )
        f.check(
            "ADR-0012 keeps the three-dataset boundary and names what is refused",
            "fundamentals" in adr12 and "refused" in flat12 and "later phase" in flat12,
            "an out-of-phase table would be authority this slice does not have",
        )
        f.check(
            "ADR-0012 binds the permitted point-in-time profile and refuses PUBLIC_PIT",
            "PROVIDER_REALISTIC_PIT" in adr12 and "PUBLIC_PIT" in adr12,
            "an unresolved Q7 has exactly one safe classification",
        )
        f.check(
            "ADR-0012 leaves Q7, Q8 and permaticker unresolved",
            "PUBLICLY_UNRESOLVED" in adr12
            and "PUBLICLY_BOUNDED" in adr12
            and "resolves none of them" in flat12,
            "a runtime core is not evidence about a vendor's data",
        )
        f.check(
            "ADR-0012 derives nothing from permaticker",
            "derives nothing from `permaticker` at all" in flat12,
            "its level is publicly unresolved, so no grouping may rest on it",
        )
        f.check(
            "ADR-0012 records that the CLI has no execution mode, structurally",
            "no execution mode" in flat12 and "structural" in flat12,
            "an absent mode is stronger than a disabled one",
        )
        f.check(
            "ADR-0012 leaves the private harness untouched and unauthorized",
            "untouched, unimported and still unauthorized to execute" in flat12,
            "a production-shaped runtime must not inherit the harness's test token",
        )
        f.check(
            "ADR-0012 adds no dependency",
            "No dependency was added" in flat12,
            "the runtime dependency list is a governed decision, not an incidental one",
        )
        f.check(
            "ADR-0012 closes no gate",
            all(
                token in adr12
                for token in ("G1 OPEN", "G2 OPEN", "G4 OPEN", "G5 OPEN", "G6 OPEN", "G7 OPEN")
            ),
            "writing a runtime core resolves no decision gate",
        )
        f.check(
            "ADR-0012 leaves ADR-0005 proposed, INC-0002 open and live trading disabled",
            "ADR-0005 remains PROPOSED" in flat12
            and "INC-0002 remains OPEN" in flat12
            and "LIVE_TRADING_HARD_DISABLED` remains True" in flat12,
            "none of the three is touched by a runtime core",
        )
        f.check(
            "ADR-0012 states its non-authorizations exhaustively",
            all(
                phrase in flat12
                for phrase in (
                    "binding a private credential",
                    "Secrets Manager",
                    "constructing a real AWS SDK session or client",
                    "resolving or binding a real bucket",
                    "any Sharadar API call",
                    "published-test-token probing",
                    "bulk downloads",
                    "CONTROL publication",
                )
            ),
            "a reader must not have to infer what merging this does not enable",
        )
        f.check(
            "ADR-0012 says what the next slice must bring",
            "supply the real private bindings" in flat12,
            "the boundary is only useful if the next step across it is named",
        )
        f.check(
            "ADR-0012 records the one change it made to an accepted module",
            "max_attempts" in adr12 and "read-only" in flat12,
            "a change to merged code is a decision, and it should be findable",
        )

    # -- the code matches what the ADR says about it --------------------------
    for label, path in (("plan", QUALIFICATION_PLAN), ("runtime", QUALIFICATION_RUNTIME)):
        if not path.is_file():
            f.check(f"the qualification {label} module exists", False, f"missing: {path}")
            continue
        f.check(f"the qualification {label} module exists", True, "")
        code = _executable_python(path)
        f.check(
            f"the qualification {label} module imports no network client or SDK",
            not re.search(
                r"^\s*(import|from)\s+(boto3|botocore|urllib|requests|httpx|socket|ssl|http)\b",
                read(path),
                re.M,
            ),
            "a dormant core that could open a socket is not dormant",
        )
        f.check(
            f"the qualification {label} module reads no environment and no file",
            not any(
                reader in code
                for reader in ("os.environ", "getenv", "open(", "read_text", "read_bytes")
            ),
            "ambient discovery is how a test run ends up holding a credential",
        )
        f.check(
            f"the qualification {label} module names no host, bucket, ARN or account",
            not re.search(r"(https?://|s3://|arn:aws|amazonaws\.com|\b\d{12}\b)", code),
            "operational configuration never belongs in Git",
        )
        f.check(
            f"the qualification {label} module has no entry point",
            '__name__ == "__main__"' not in code and "argparse" not in code,
            "no execution path is authorized for this slice",
        )

    if QUALIFICATION_RUNTIME.is_file():
        runtime_code = _executable_python(QUALIFICATION_RUNTIME)
        f.check(
            "the runtime publishes only through the Bronze bridge",
            "publish_sharadar_payload" in runtime_code
            and not any(
                bypass in runtime_code
                for bypass in ("put_object", "head_object", "ObjectKey.", "put_if_absent(")
            ),
            "a second storage path would own rules the neutral publisher already owns",
        )
        f.check(
            "the runtime constructs no client, session, store or credential",
            not any(
                name in runtime_code
                for name in (
                    "S3ResearchObjectStore(",
                    "UrllibTransport(",
                    "SharadarCredential(",
                    "credential_from_env(",
                    "SharadarClient(",
                )
            ),
            "constructing any of them would be the composition root this slice omits",
        )
        f.check(
            "the runtime never names PUBLIC_PIT",
            "PUBLIC_PIT" not in runtime_code,
            "a profile that cannot be written cannot be written by accident",
        )
        f.check(
            "the runtime never names permaticker",
            "permaticker" not in runtime_code.lower(),
            "payloads are opaque bytes here and are never parsed",
        )
        f.check(
            "the runtime uses no free-text notes field",
            "notes" not in runtime_code,
            "`notes` has no durable destination on this path; using it would invent one",
        )

    if PLAN_CHECK.is_file():
        cli = read(PLAN_CHECK)
        cli_code = _executable_python(PLAN_CHECK)
        f.check(
            "the plan-check command refuses every live or secret option by name",
            all(
                option in cli
                for option in (
                    "--execute",
                    "--live",
                    "--api-key",
                    "--secret",
                    "--bucket",
                    "--aws-profile",
                    "--endpoint",
                )
            ),
            "an unrecognised flag teaches nothing, and someone will try another spelling",
        )
        f.check(
            "the plan-check command imports no client, transport, store or executor",
            not re.search(
                r"^\s*from\s+kalpamani[.\w]*\.(client|transport|runtime|credentials)\b",
                cli,
                re.M,
            )
            and not re.search(
                r"^\s*import\s+(boto3|botocore|urllib|requests)\b",
                cli,
                re.M,
            ),
            "the absence of an execution mode has to be structural, not a policy",
        )
        f.check(
            "the plan-check command does not touch the private harness",
            "private_qualification" not in cli_code,
            "the harness is owner-only and remains unauthorized to execute",
        )

    # -- the status documents record a runtime that exists and cannot be run ---
    for name, path in (
        ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
        ("README.md", REPO_ROOT / "README.md"),
    ):
        if not path.is_file():
            continue
        body = read(path)
        flat = " ".join(body.replace("**", "").split())
        f.check(
            f"{name} records the qualification runtime core and ADR-0012",
            "ADR-0012" in body and "qualification runtime core" in flat.lower(),
            "a session must be able to find what now exists and what still does not",
        )
        f.check(
            f"{name} records that no composition root exists",
            # `and`, not `or`. The negative control found that an `or` here was
            # unfalsifiable: deleting the checkable posture line still left the
            # prose standing, so the guard passed while the fact it checks had
            # been removed.
            "composition root: NONE" in body and "composition root" in flat.lower(),
            "that absence is the control; it must be stated where it is read, and the "
            "posture line is the part a reader can check",
        )
        f.check(
            f"{name} states that the runtime has sent zero provider and zero AWS requests",
            "Sharadar requests sent by these modules themselves: ZERO" in body
            and "AWS requests sent: ZERO" in body,
            "dormancy is a count, not an adjective",
        )
        f.check(
            f"{name} keeps a credential source and client construction unauthorized",
            "credential source" in flat and "client construction" in flat,
            "the next slice must bring them, under its own authorization",
        )

    # -- correction round 1: identity, reporting, resume, admission -----------
    if ADR_RUNTIME.is_file():
        f.check(
            "ADR-0012 records one acquisition identity per request",
            "One request is one acquisition" in adr12
            and "execution id, the provider, the dataset, the subject" in flat12,
            "an execution-level id shared by every request is not a retrieval identity",
        )
        f.check(
            "ADR-0012 names the three defects a shared identity caused",
            "collided on the global acquisition claim" in flat12
            and "collapsed into one acquisition" in flat12,
            "the correction is only checkable if what it corrected is written down",
        )
        f.check(
            "ADR-0012 states that the execution id has no default",
            "The execution id has no default" in flat12,
            "a reusable default made two attempts share evidence",
        )
        f.check(
            "ADR-0012 retracts the resume claim explicitly",
            "There is no resume" in flat12 and "wrongly said there was" in flat12,
            "a false capability quietly dropped is a false capability someone still believes",
        )
        f.check(
            "ADR-0012 says what to do after a halt instead",
            "must use a new explicit execution id" in flat12,
            "removing a capability without naming the supported path leaves a gap",
        )
        f.check(
            "ADR-0012 defers durable resume rather than improvising one",
            "Durable cross-process resume is deferred" in flat12 and "no checkpoint file" in flat12,
            "a checkpoint, a ledger or an attestation would each need their own governance",
        )
        f.check(
            "ADR-0012 distinguishes payload reuse from acquisition reuse",
            "payload reuse is not acquisition reuse" in flat12.lower(),
            "conflating them is what made a repeat look like progress",
        )
        f.check(
            "ADR-0012 records that a failed publication leaves unknown durable state",
            "publication_state_unknown" in adr12
            and "claims to know nothing more" in flat12
            and "may not prove whether any of them committed" in flat12,
            "an append-only publication interrupted mid-way cannot be described exactly",
        )
        f.check(
            "ADR-0012 records the parameter allowlist, not a denylist",
            "allowlist" in flat12.lower() and "api_key" in adr12,
            "a denylist admits every name nobody has heard of yet",
        )
        f.check(
            "ADR-0012 records the backfill flag as a conservative placeholder",
            "conservative placeholder, not a semantic classification" in flat12
            and "authorizes and implements no production backfill" in flat12,
            "a metadata value that does not fit should be reported, not smoothed over",
        )
        f.check(
            "ADR-0012 states the backfill placeholder as a pre-execution blocker",
            "pre-execution blocker" in flat12
            and "may be authorized or executed until the neutral acquisition contract" in flat12,
            "a placeholder with no stated consequence is a placeholder that gets relied on",
        )
        f.check(
            "ADR-0012 denies that the placeholder is evidence of an update",
            "no affirmative evidence that the retrieval is an update" in flat12,
            "False must not be read as a positive claim about the retrieval",
        )
        f.check(
            "ADR-0012 forbids consumers reading the field as evidence",
            "must not interpret this field as evidence" in flat12,
            "a downstream reader treating a placeholder as a finding is the failure mode",
        )
        f.check(
            "ADR-0012 declines to change the neutral vocabulary in this PR",
            "deliberately not introduced here" in flat12
            and "needs its own reviewed decision" in flat12,
            "a three-state vocabulary would change an already-accepted neutral contract",
        )
        f.check(
            "ADR-0012 says exactly what the run-byte ceiling bounds",
            "successful provider payload bytes returned by the injected client" in flat12
            and "before" in flat12,
            "a ceiling that does not say what it counts is a number, not a bound",
        )
        f.check(
            "ADR-0012 denies that the ceiling covers wire traffic",
            "not a bound on HTTP framing" in flat12 and "nobody here can measure" in flat12,
            "claiming to bound what the client does not expose would be a false guarantee",
        )
        f.check(
            "ADR-0012 records the ceiling as headroom checked before each request",
            "headroom, before each request is sent" in flat12
            and "without sending the request" in flat12,
            "a ceiling enforced after the bytes have arrived is not a ceiling",
        )
        f.check(
            "ADR-0012 records the validate-first refusal for an oversized client ceiling",
            "refused during validation" in flat12
            and "before the first provider or store call" in flat12,
            "a run that could never send its first request should not send it",
        )
        f.check(
            "ADR-0012 distinguishes fetched bytes from completed bytes",
            "Two byte totals" in flat12 and "fetched three payloads and completed two" in flat12,
            "one total cannot report a run that fetched more than it completed",
        )
        f.check(
            "ADR-0012 records the result-integrity invariants",
            "must describe" in flat12
            and "one valid execution" in flat12
            and "strictly fewer" in flat12,
            "a halted run that finished its plan is a completed run wearing a failure code",
        )
        f.check(
            "ADR-0012 makes no claim to know which objects exist after a failure",
            "which objects exist" not in flat12 or "no field here claims" in flat12,
            "the honest position is that an interrupted publication is not describable",
        )

    if QUALIFICATION_RUNTIME.is_file() and QUALIFICATION_PLAN.is_file():
        runtime_source = read(QUALIFICATION_RUNTIME)
        plan_source = read(QUALIFICATION_PLAN)
        f.check(
            "the runtime publishes under a per-request acquisition identity",
            "ingestion_run_id=identity" in runtime_source,
            "passing the execution id would restore the defect this round removed",
        )
        f.check(
            "the plan derives an acquisition identity that binds every request component",
            all(
                component in plan_source
                for component in (
                    'f"execution={execution_id}"',
                    'f"dataset={request.dataset.value}"',
                    'f"subject={request.ticker}"',
                    'f"range={request.requested_range}"',
                    'f"limit={request.page.limit}"',
                    'f"skip={request.page.skip}"',
                )
            ),
            "an identity that omits a component cannot separate two requests that differ in it",
        )
        f.check(
            "the plan admits query parameters by allowlist",
            "PLAN_PARAMETER_ALLOWLIST" in plan_source
            and "name not in PLAN_PARAMETER_ALLOWLIST" in plan_source,
            "a denylist admits every name the vendor has not invented yet",
        )
        f.check(
            "the plan carries no caller-controlled acquisition mode",
            # The module *defines* QUALIFICATION_ACQUISITION_MODE, which is the
            # single source; what must not exist is a lowercase field, parameter
            # or keyword a caller could set.
            "acquisition_mode" not in plan_source and "is_backfill" not in plan_source,
            "a plan field would let a caller label evidence as a production backfill",
        )
        f.check(
            "the qualification module owns the single-source acquisition mode",
            "QUALIFICATION_ACQUISITION_MODE: Final = AcquisitionMode.QUALIFICATION" in plan_source
            and '"QUALIFICATION_ACQUISITION_MODE",' in plan_source,
            "one fact stated once, and exported so nothing has to restate it",
        )
        f.check(
            "the runtime records the single-source qualification mode",
            "acquisition_mode=QUALIFICATION_ACQUISITION_MODE" in runtime_source
            # Docstring-stripped: the module *documents* what the constant
            # resolves to, and a raw scan would forbid saying so.
            and "AcquisitionMode.QUALIFICATION" not in _executable_python(QUALIFICATION_RUNTIME),
            "the mode must be fixed here and unreachable from a plan or a caller",
        )
        f.check(
            "the runtime checks byte headroom before sending a request",
            "self._client.max_response_bytes > plan.limits.max_run_bytes" in runtime_source
            and "RUN_BYTE_HEADROOM_EXHAUSTED" in runtime_source,
            "a ceiling enforced after the bytes have arrived is not a ceiling",
        )
        f.check(
            "the runtime refuses a client ceiling larger than the whole run ceiling",
            "RUN_BYTE_CEILING_UNSATISFIABLE" in runtime_source,
            "such a run could never send even its first request within its own ceiling",
        )
        f.check(
            "the runtime reports fetched and published bytes separately",
            "fetched_payload_bytes" in runtime_source
            and "completed_payload_bytes" in runtime_source
            and "total_bytes" not in _executable_python(QUALIFICATION_RUNTIME),
            "one total cannot report a run that fetched more than it published",
        )
        f.check(
            "the runtime derives the client ceiling rather than duplicating it",
            "max_response_bytes" in read(PROVIDER_PACKAGE / "client.py"),
            "two ceilings for one limit are two numbers a later edit can move apart",
        )
        f.check(
            "the result refuses duplicate identities and duplicate coordinates",
            "acquisition_id for outcome in self.outcomes" in runtime_source
            and "outcome.page_limit, outcome.page_skip" in runtime_source,
            "durable evidence that shares an identity or a coordinate cannot exist",
        )
        f.check(
            "a halted result requires strictly fewer completed than planned",
            "self.completed_requests >= self.planned_requests" in runtime_source,
            "otherwise a completed run can wear a failure code",
        )
        f.check(
            "the runtime reports all three publication dispositions",
            all(
                field in runtime_source
                for field in ("claim_written", "payload_written", "acquisition_written")
            ),
            "payload presence alone does not represent acquisition completion",
        )
        f.check(
            "the runtime no longer reports a payload-only stored count",
            "stored_objects" not in _executable_python(QUALIFICATION_RUNTIME)
            and "already_present_objects" not in _executable_python(QUALIFICATION_RUNTIME),
            "the old names described one of three writes and called it the whole publication",
        )
        f.check(
            "the runtime carries an explicit unknown-durable-state field",
            "publication_state_unknown" in runtime_source,
            "an interrupted append-only publication cannot be described exactly",
        )
        f.check(
            "both result structures validate themselves at construction",
            runtime_source.count("def __post_init__") >= 2,
            "an annotation is a static claim and stops nothing at run time",
        )
        f.check(
            "the runtime claims no resume",
            "There is no resume" in runtime_source,
            "the module docstring is where a reader looks first",
        )
        f.check(
            "the runtime adds no checkpoint, ledger or listing",
            not any(
                token in _executable_python(QUALIFICATION_RUNTIME)
                for token in ("checkpoint", "ledger", "list_objects", "attestation")
            ),
            "each would need its own governance, and none is authorized",
        )

    for name, path in (
        ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
        ("README.md", REPO_ROOT / "README.md"),
    ):
        if not path.is_file():
            continue
        body = read(path)
        flat = " ".join(body.replace("**", "").split())
        f.check(
            f"{name} states that one request is one acquisition",
            "One request, one acquisition" in body,
            "the identity model is the correction a later session most needs to see",
        )
        f.check(
            f"{name} records that there is no resume",
            "No resume" in body and "new explicit execution id" in flat,
            "a false capability left in a status document is one someone will rely on",
        )
        f.check(
            f"{name} no longer describes rerunning a plan as a safe resume",
            "Resume is the store's job" not in body
            and "identical bytes republish as an idempotent no-op" not in flat,
            "that sentence was true only of a frozen clock",
        )
        f.check(
            f"{name} records the three-write publication reporting",
            "Three writes, three dispositions" in body,
            "payload presence alone is not acquisition completion",
        )
        f.check(
            f"{name} records that a failed publication leaves unknown durable state",
            "publication_state_unknown" in body and "claims to know nothing more" in flat,
            "the result must not appear to know what an interrupted publication left",
        )
        f.check(
            f"{name} says what the run-byte ceiling actually bounds",
            "successful provider payload bytes handed to the runtime" in flat
            and "not HTTP framing" in flat,
            "a ceiling that does not say what it counts is a number, not a bound",
        )
        f.check(
            f"{name} records the acquisition mode the runtime uses",
            "AcquisitionMode.QUALIFICATION" in body and "declared, never inferred" in flat.lower(),
            "a mode read as a derivation is the failure this guard exists for",
        )
        f.check(
            f"{name} records the result-integrity invariants",
            "Result integrity" in body and "strictly fewer completed than planned" in flat,
            "a result that cannot describe one valid execution is not evidence",
        )

    # -- correction round 3: pre-access ceiling and byte-evidence naming -------
    if ADR_RUNTIME.is_file():
        f.check(
            "ADR-0012 no longer says the run ceiling is enforced as bytes are published",
            "Enforced as bytes are published" not in adr12,
            "the ceiling is budgeted as pre-request headroom, and the old sentence contradicts it",
        )
        f.check(
            "ADR-0012 makes no claim that the run ceiling is enforced through publication",
            "enforced through publication" not in flat12.lower()
            and "enforced at publication" not in flat12.lower(),
            "bytes are counted when they arrive, before anything is published",
        )
        f.check(
            "ADR-0012 records the per-response ceiling as binding before a body is read",
            "binds before a body is read" in flat12
            and "post-access complaint, not a ceiling" in flat12,
            "a ceiling that only complains after the body arrives is not a ceiling",
        )
        f.check(
            "ADR-0012 records that neither ceiling is clamped",
            "Neither value is clamped" in flat12,
            "silently lowering either would make the run behave unlike its plan",
        )
        f.check(
            "ADR-0012 states that the guarantee rests on the transport's declaration",
            "rests on the transport honouring what it declares" in flat12
            and "defence in depth rather than the ceiling itself" in flat12,
            "a guarantee whose dependency is unstated is a guarantee nobody can check",
        )
        f.check(
            "ADR-0012 records that the accepted transport enforces its ceiling before returning",
            "never reaches the client" in flat12,
            "the pre-access property depends on where the read actually stops",
        )
        f.check(
            "ADR-0012 records that the post-fetch check uses the effective ceiling",
            "min(client, plan)" in flat12 and "not the plan's alone" in flat12,
            "the plan's ceiling is insufficient whenever the client is stricter",
        )
        f.check(
            "ADR-0012 names the asymmetric case the plan ceiling alone would miss",
            "declaring 32 and a plan permitting 64" in flat12
            and "would find nothing wrong and publish it" in flat12,
            "a stated counterexample is what makes the rule checkable later",
        )
        f.check(
            "ADR-0012 defines completed payload bytes as acquisition completion",
            "regardless of whether the payload object was newly written, reused, or already"
            in flat12,
            "the number measures completion, not new storage",
        )
        f.check(
            "ADR-0012 forbids describing completed bytes as bytes written or stored",
            "never be described as bytes written, stored, transferred or newly published" in flat12,
            "the old name read as 'bytes this run wrote' and was wrong for two dispositions",
        )

    if QUALIFICATION_RUNTIME.is_file():
        round3_source = read(QUALIFICATION_RUNTIME)
        f.check(
            "the runtime refuses a client response ceiling above the plan's",
            "self._client.max_response_bytes > plan.limits.max_response_bytes" in round3_source
            and "RESPONSE_BYTE_CEILING_UNSATISFIABLE" in round3_source,
            "the ceiling has to bind before the response exists",
        )
        f.check(
            "the runtime keeps the post-fetch length check as defence in depth",
            "len(payload) > effective_response_ceiling" in round3_source
            and "Defence in depth, not the ceiling" in round3_source,
            "an injected transport may break the contract it declares",
        )
        f.check(
            "the post-fetch check uses the effective ceiling, not the plan's alone",
            "effective_response_ceiling = min(" in round3_source
            and "self._client.max_response_bytes, plan.limits.max_response_bytes" in round3_source,
            "a client stricter than its plan is permitted, so comparing against the plan "
            "alone would publish a body that broke the client's own declaration",
        )
        f.check(
            "the runtime no longer compares a returned body against the plan ceiling alone",
            "len(payload) > plan.limits.max_response_bytes" not in round3_source,
            "that comparison misses every violation where the client is the stricter of the two",
        )
        f.check(
            "no source, test or audit still names a published-payload total",
            not any(
                "published_payload" in read(path)
                for path in (
                    QUALIFICATION_RUNTIME,
                    QUALIFICATION_PLAN,
                    ADR_RUNTIME,
                    REPO_ROOT / "CLAUDE.md",
                    REPO_ROOT / "README.md",
                )
            ),
            "the name read as 'bytes this run wrote', which two dispositions contradict",
        )
        f.check(
            "the runtime names the total for completion rather than storage",
            "completed_payload_bytes" in round3_source,
            "it counts acquisitions that completed, including ones that wrote nothing",
        )

    # ------------------- 20. Acquisition mode replaced a boolean, completely
    print("\n[20/21] Acquisition mode is a closed vocabulary, and the boolean is gone")
    f.check(
        "ADR-0013 exists",
        ADR_ACQUISITION_MODE.is_file(),
        f"missing: {ADR_ACQUISITION_MODE}",
    )
    if ADR_ACQUISITION_MODE.is_file():
        adr13 = read(ADR_ACQUISITION_MODE)
        flat13 = " ".join(
            " ".join(line.lstrip("> ") for line in adr13.replace("**", "").splitlines()).split()
        )

        f.check(
            "ADR-0013 is accepted on merge and not before",
            "Accepted \u2014 effective on the merge" in adr13 and "carries no authority" in adr13,
            "the ADR must carry no authority until its pull request merges",
        )
        for member, meaning in (
            ("QUALIFICATION", "bounded provider-validation retrieval"),
            ("BACKFILL", "Historical production loading"),
            ("UPDATE", "Incremental production refresh"),
        ):
            f.check(
                f"ADR-0013 defines {member} exactly",
                member in adr13 and meaning in flat13,
                "a vocabulary whose members are not defined is three spellings of nothing",
            )
        f.check(
            "ADR-0013 gives the production-scoped reason a qualification run is not an UPDATE",
            "not an `UPDATE` because it is not an incremental production refresh" in flat13
            and "does not advance an approved production dataset" in flat13,
            "the distinction is whether an approved production dataset advances",
        )
        f.check(
            "ADR-0013 does not rest that reason on the retrieval extending no prior state",
            "It extends no prior state, so it is not an update" not in flat13,
            "a qualification run may write evidence, and a first UPDATE extends nothing either",
        )
        f.check(
            "ADR-0013 records this as a breaking pre-data correction",
            "breaking pre-data correction" in flat13,
            "the change is total precisely because nothing was ever written under the old schema",
        )
        f.check(
            "ADR-0013 records that no real Services Data exists under the retired schema",
            "No real Services Data has ever been ingested under the retired schema" in flat13,
            "no data means no migration and no compatibility reader",
        )
        f.check(
            "ADR-0013 forbids default, conversion, inference, alias, reader and dual-write",
            "No default, no boolean-to-mode conversion, no inference, no alias, no deprecated"
            in flat13,
            "each would keep the retired representation alive under another name",
        )
        f.check(
            "ADR-0013 records that the mode is declared and never inferred",
            "never inferred" in flat13
            and "not from dates, ranges, record counts" in flat13.lower(),
            "a mode derived from the data is an observation wearing a declaration's name",
        )
        f.check(
            "ADR-0013 records that the mode proves nothing on its own",
            "proves nothing on its own" in flat13
            and "does not grant earlier PIT availability" in flat13,
            "PIT admissibility is decided by the availability envelope, not by a label",
        )
        f.check(
            "ADR-0013 keeps the historical-coverage observation separate",
            "historical-coverage observation stays separate" in flat13,
            "an earlier revision let the coverage rule set the flag, conflating the two",
        )
        f.check(
            "ADR-0013 records that the dormant runtime always uses QUALIFICATION",
            "passes `AcquisitionMode.QUALIFICATION` directly" in adr13,
            "there is one kind of retrieval here, so there is nothing to choose",
        )
        f.check(
            "ADR-0013 authorizes neither production mode",
            "authorizes neither production operation" in flat13,
            "naming BACKFILL and UPDATE is not permission to perform either",
        )
        f.check(
            "ADR-0013 closes the metadata blocker only on merge and on verified removal",
            "closes only when this ADR becomes effective on merge and the complete removal is "
            "verified" in flat13,
            "a blocker that closes on intention rather than on evidence has not closed",
        )
        f.check(
            "ADR-0013 states that closing the blocker authorizes no real run",
            "does not authorize or execute a real qualification run" in flat13
            and "remains NOT" in adr13,
            "removing an obstacle to asking is not being answered",
        )
        f.check(
            "ADR-0013 changes no gate",
            all(
                token in adr13
                for token in ("G1 OPEN", "G2 OPEN", "G4 OPEN", "G5 OPEN", "G6 OPEN", "G7 OPEN")
            )
            and "INC-0002 remains" in adr13
            and "ADR-0005 remains" in adr13,
            "a contract correction resolves no decision gate",
        )
        f.check(
            "ADR-0013 supersedes only the live boolean semantics",
            "live `is_backfill` contract semantics only" in adr13
            and "Accepted ADRs are not rewritten" in flat13,
            "historical ADR text is evidence and is never edited",
        )
        f.check(
            "ADR-0013 claims agreement on the shared acquisition fields, not whole records",
            "agree on the shared acquisition fields" in flat13 and "field for field" not in flat13,
            "the two envelopes differ on purpose, so whole-record equality would be false",
        )
        f.check(
            "ADR-0013 names the envelope difference instead of hiding it",
            "Their envelopes are deliberately not identical" in flat13
            and all(
                token in flat13
                for token in ("`status`, `ingest_date` and `notes`", "carries `classification`")
            ),
            "a difference that is stated can be reviewed; one that is implied cannot",
        )
        f.check(
            "ADR-0013 records that the filesystem record is read back from a real store",
            "not from the builder that wrote it" in flat13,
            "comparing a builder against itself is what missed the omission in the first place",
        )
        f.check(
            "ADR-0013 records the changed-mode refusal as proven on both storage paths",
            "fails closed on both storage paths, proven against each" in flat13,
            "one path holding the property says nothing about the other",
        )
        f.check(
            "ADR-0013 scopes the unreachable-mode claim to the qualification runtime",
            "the qualification runtime's mode is unreachable from `QualificationPlan` and from "
            "the runtime's execute caller" in flat13,
            "a neutral caller must be able to state a mode; only this runtime may not",
        )
        f.check(
            "ADR-0013 records that completeness verification enforces the mode",
            "exactly one active mode field" in flat13
            and "exact built-in `str`" in flat13
            and "exactly one of three tokens" in flat13,
            "writing the mode is not checking it; a bad record must be refusable by reading",
        )
        f.check(
            "ADR-0013 records the closed field allowlist for the filesystem record",
            "a closed field allowlist" in flat13
            and "must equal the durable shape exactly" in flat13,
            "a shape that admits extra or missing fields is a suggestion",
        )
        f.check(
            "ADR-0013 records that verification offers no legacy-reader path",
            "no alias, fallback, conversion, inference, default or dual-read" in flat13
            and "republished, never translated" in flat13,
            "a compatibility reader would manufacture a claim nobody made",
        )
        f.check(
            "ADR-0013 records that no republish is needed to find a bad record",
            "no republish required" in flat13
            and "rather than by attempting to write to it again" in flat13,
            "discovering malformed metadata by writing over it is not verification",
        )
        f.check(
            "ADR-0013 records that the retired key is refused by absence",
            "refused by absence, not by a check that names it" in flat13,
            "the allowlist refuses every undefined field, not one anticipated name",
        )
        f.check(
            "ADR-0013 records that verification echoes no record-controlled text",
            "No record-controlled text reaches a message" in flat13
            and "counted rather than named" in flat13,
            "a malformed value is the text least safe to repeat into a traceback",
        )
        f.check(
            "ADR-0013 discloses the fail-open verification defect too",
            "Writing the mode is not checking it" in flat13
            and "a property enforced on one path and assumed on another" in flat13,
            "the same mistake twice is worth naming as a pattern, not as an incident",
        )
        f.check(
            "ADR-0013 discloses the defect its own first revision contained",
            "recorded no mode at all" in flat13
            and "accepted rather than refused" in flat13
            and "a test's *name* is not evidence of its subject" in flat13,
            "a correction that conceals what it corrected teaches a later reader nothing",
        )
        f.check(
            "ADR-0013 records the durable before and after",
            '"acquisition_mode": "QUALIFICATION"' in adr13 and '"is_backfill": false' in adr13,
            "the shape change is the part a later reader most needs stated",
        )
        f.check(
            "ADR-0013 refuses to repurpose the payload schema version",
            "`source_schema_version` is not one" in adr13,
            "one value answering two unrelated questions is how a schema field goes wrong",
        )

    # -- the vocabulary and the contract, as code ----------------------------
    if VOCABULARY.is_file():
        vocabulary_source = read(VOCABULARY)
        f.check(
            "the vocabulary defines exactly the three members",
            'QUALIFICATION = "QUALIFICATION"' in vocabulary_source
            and 'BACKFILL = "BACKFILL"' in vocabulary_source
            and 'UPDATE = "UPDATE"' in vocabulary_source,
            "three members, and the meanings are recorded beside them",
        )
        f.check(
            "the vocabulary has no escape-hatch member",
            not re.search(
                r"^\s+(UNKNOWN|NONE|OTHER|HISTORICAL|DEFAULT)\s*=",
                vocabulary_source.split("class AcquisitionMode")[1].split("class ")[0]
                if "class AcquisitionMode" in vocabulary_source
                else "",
                re.M,
            ),
            "a member meaning 'we did not say' would be chosen by whatever did not decide",
        )
        f.check(
            "the vocabulary is exported from the neutral surface",
            '"AcquisitionMode",' in vocabulary_source,
            "a contract type nobody can import is a contract nobody can use",
        )

    f.check(
        "no executable module under src/ names the retired identifier",
        not _legacy_identifier_sites(),
        "an alias, a property, a parameter or a serialized field would keep it alive",
    )
    f.check(
        "the durable field allowlist names the mode and refuses the retired key",
        '"acquisition_mode",' in read(PUBLICATION) and '"is_backfill",' not in read(PUBLICATION),
        "the allowlist is what refuses a record carrying the old key, or carrying both",
    )
    f.check(
        "the neutral publisher reads the mode only from the retrieval",
        "str(retrieval.acquisition_mode.value)" in read(PUBLICATION),
        "a second source would be a second place to state one fact",
    )
    f.check(
        "the filesystem acquisition record carries the mode, from the retrieval",
        LOCAL_BRONZE.is_file()
        and '"acquisition_mode": str(retrieval.acquisition_mode.value),' in read(LOCAL_BRONZE),
        "the first revision updated the object-store record and left this store behind",
    )
    if LOCAL_BRONZE.is_file():
        local_bronze = read(LOCAL_BRONZE)
        f.check(
            "the filesystem store declares a closed acquisition-record shape",
            "ACQUISITION_RECORD_FIELDS: Final[frozenset[str]]" in local_bronze
            and "ACQUISITION_MODE_FIELD," in local_bronze,
            "an open shape cannot refuse a field written under a retired schema",
        )
        f.check(
            "the filesystem completeness audit verifies the record shape",
            "_record_shape_problems(record)" in local_bronze
            and "def audit_acquisitions" in local_bronze,
            "a record already on disk was never republished, so nothing else checks it",
        )
        f.check(
            "the filesystem verifier requires an exact str and a permitted token",
            "if type(mode) is not str:" in local_bronze
            and "mode not in _ACQUISITION_MODE_TOKENS" in local_bronze,
            "a str subclass compares equal to its token while being a different type",
        )
        f.check(
            "the filesystem verifier derives its tokens from the vocabulary",
            "str(member.value) for member in AcquisitionMode" in local_bronze,
            "a restated list is a second place for the vocabulary to be wrong",
        )
        f.check(
            "the filesystem verifier echoes no record-controlled text",
            "not repeated here" in local_bronze
            and "undefined = len(keys - ACQUISITION_RECORD_FIELDS)" in local_bronze,
            "a malformed value, and an unrecognised key, are both uncontrolled text",
        )

    if ACQUISITION_MODE_TESTS.is_file():
        mode_tests = read(ACQUISITION_MODE_TESTS)
        for label, needle in (
            ("a missing mode", "test_a_record_with_no_acquisition_mode_is_refused"),
            ("every malformed value", "test_each_invalid_durable_mode_is_refused_on_its_own"),
            ("a str subclass", "test_a_str_subclass_mode_is_refused_where_it_could_arrive"),
            ("a dual-written record", "test_a_valid_mode_beside_the_retired_key_is_refused"),
            ("the retired key alone", "test_the_retired_key_alone_is_refused"),
            ("an undefined field", "test_an_arbitrary_undefined_field_is_refused"),
            (
                "refusal without a republish",
                "test_a_malformed_record_is_refused_without_any_republish_attempt",
            ),
            (
                "the restored record",
                "test_restoring_the_exact_record_makes_verification_pass_again",
            ),
            (
                "a leaked value",
                "test_a_malformed_mode_value_never_reaches_the_audit_or_the_exception",
            ),
            (
                "a leaked field name",
                "test_an_undefined_field_name_is_counted_rather_than_repeated",
            ),
        ):
            f.check(
                f"a filesystem verification test covers {label}",
                needle in mode_tests,
                "the ADR's verification table must name tests that exist",
            )
        f.check(
            "the object-store contradiction test compares a whole-store snapshot",
            "def object_store_snapshot" in mode_tests and "store.stored_digest(name)" in mode_tests,
            "an exception says nothing about what the store did before reaching it",
        )
    f.check(
        "no acquisition mode is assigned conditionally anywhere under src/",
        not _conditional_mode_sites(),
        "deriving the mode from the data is the conflation this correction removed",
    )

    # -- the current documentation --------------------------------------------
    for name, path in (
        ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
        ("README.md", REPO_ROOT / "README.md"),
    ):
        if not path.is_file():
            continue
        body = read(path)
        flat = " ".join(body.replace("**", "").split())
        f.check(
            f"{name} records the three-member vocabulary and ADR-0013",
            "ADR-0013" in body
            and all(token in body for token in ("QUALIFICATION", "BACKFILL", "UPDATE")),
            "the contract a session must not re-derive belongs where a session looks first",
        )
        f.check(
            f"{name} records that the mode is declared and never inferred",
            "Declared, never inferred" in body,
            "counts, ranges and coverage are observations, not declarations",
        )
        f.check(
            f"{name} records that the mode proves nothing on its own",
            "proves nothing on its own" in flat and "grants no earlier PIT availability" in flat,
            "a label that granted PIT availability would be a leak with a governance name",
        )
        f.check(
            f"{name} keeps the historical-coverage check separate from the mode",
            "observes" in flat and "without setting, confirming or contradicting it" in flat,
            "the coverage rule records what arrived; the mode records what was asked for",
        )
        f.check(
            f"{name} closes the metadata blocker only on merge",
            "blocker is CLOSED effective on merge" in flat
            and "only if the complete removal is accepted" in flat,
            "a blocker closed by intention rather than by evidence has not closed",
        )
        f.check(
            f"{name} states beside that closure that a real run is still unauthorized",
            "A real Sharadar qualification run remains NOT AUTHORIZED and has never happened"
            in flat
            and "refused at the AWS identity gate, before any provider contact" in flat,
            "the two statements must be read together or the first misleads",
        )
        f.check(
            f"{name} authorizes neither production mode",
            "neither production operation is authorized" in flat,
            "naming BACKFILL and UPDATE is not permission to perform either",
        )

    plan_path = PHASE3 / "implementation-plan.md"
    if plan_path.is_file():
        plan_body = read(plan_path)
        f.check(
            "the implementation plan describes the ingestion run's declared mode",
            "declared `acquisition_mode`" in plan_body
            and "never inferred from what arrived" in plan_body,
            "the plan is where the durable ingestion_run shape is described",
        )
        f.check(
            "the implementation plan no longer says the run records whether it was a backfill",
            "whether the run was a backfill" not in plan_body,
            "a two-valued description of a three-member field is the retired contract",
        )

    quality_path = PHASE3 / "data-quality-plan.md"
    if quality_path.is_file():
        quality_flat = " ".join(read(quality_path).replace("**", "").split())
        f.check(
            "the data-quality plan does not call an unsatisfied condition a finding",
            "both are findings" not in quality_flat,
            "4.2.4 emits a finding only when its coverage-extension condition holds",
        )
        f.check(
            "the data-quality plan states when 4.2.4 actually emits a finding",
            "emits a finding only when its historical-coverage-extension condition is satisfied"
            in quality_flat
            and "Neither observation rewrites or contradicts the declared acquisition mode"
            in quality_flat,
            "an observation that sits oddly beside the mode does not overrule it",
        )

    for label, path in (
        ("the conceptual schema", PHASE3 / "conceptual-schema.md"),
        ("the data-quality plan", PHASE3 / "data-quality-plan.md"),
    ):
        if not path.is_file():
            continue
        contract = read(path)
        f.check(
            f"{label} names acquisition_mode rather than the retired boolean",
            "acquisition_mode" in contract,
            "a current contract document is where the live field is looked up",
        )
        f.check(
            f"{label} records that counts and coverage do not determine the mode",
            "Neither determines `acquisition_mode`" in contract
            or "does **not** set, confirm or contradict `acquisition_mode`" in contract,
            "record counts and coverage extension are observations",
        )

    status_documents = {
        name: read(path)
        for name, path in (
            ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
            ("README.md", REPO_ROOT / "README.md"),
        )
        if path.is_file()
    }
    if len(status_documents) == 2:
        f.check(
            "the merged-ADR registry covers every in-force ADR row in both documents",
            not _registry_coverage_defects(status_documents),
            "a row of this class outside the registry is a row nothing governs",
        )
        f.check(
            "the two status documents agree on every ADR-to-pull-request mapping",
            all(
                _in_force_adr_claims(status_documents["CLAUDE.md"]).get(adr)
                == _in_force_adr_claims(status_documents["README.md"]).get(adr)
                for adr in set(_in_force_adr_claims(status_documents["CLAUDE.md"]))
                | set(_in_force_adr_claims(status_documents["README.md"]))
            ),
            "two documents naming different pull requests is two answers to one question",
        )
        f.check(
            "the registry is in ascending ADR order",
            [adr for adr, _ in MERGED_ADR_STATUS] == sorted(adr for adr, _ in MERGED_ADR_STATUS),
            "an ordered registry is one a reader can check against the decisions directory",
        )
        f.check(
            "the dated completed-event rows are not treated as PR-numbered claims",
            not {"ADR-0007", "ADR-0008"} & set(_in_force_adr_claims(status_documents["CLAUDE.md"])),
            "ADR-0007 and ADR-0008 record a date, not a pull request, and are not of this class",
        )

    # -- 21. ADR-0014: the dormant composition root and offline preflight ----
    #
    # This section exists because the slice *changed a standing claim*. Every
    # earlier status document said no composition root existed, and that was
    # true. The replacement is narrower and has to be held to: one root, no
    # execution surface, no runner, no bindings, and zero requests.

    f.check(
        "ADR-0014 exists",
        ADR_COMPOSITION.is_file(),
        f"missing: {ADR_COMPOSITION}",
    )
    if ADR_COMPOSITION.is_file():
        adr14 = read(ADR_COMPOSITION)
        flat14 = " ".join(
            " ".join(line.lstrip("> ") for line in adr14.replace("**", "").splitlines()).split()
        )
        f.check(
            "ADR-0014 is accepted on merge and not before",
            "Accepted \u2014 effective on the merge" in adr14 and "carries no authority" in adr14,
            "the ADR must carry no authority until its pull request merges",
        )
        f.check(
            "ADR-0014 keeps its own accepted-on-merge status line",
            "Accepted \u2014 effective on the merge" in adr14,
            "the ADR states the condition that made it effective; only tables state the result",
        )
        f.check(
            "ADR-0014 records the owner's authorization boundary verbatim",
            "Scope is limited to: code; tests; documentation; audits; and synthetic/local"
            in flat14,
            "the boundary a slice was given is the boundary it must be read against",
        )
        f.check(
            "ADR-0014 records that the composition is code-only and dormant",
            "code, tests, documentation, audits and synthetic/local validation only" in flat14,
            "authorizing wiring is not authorizing a run",
        )
        f.check(
            "ADR-0014 records that preflight validates construction and the plan",
            "calls `QualificationRuntime.validate` and nothing else" in flat14,
            "validate is the whole surface; execute is the thing that is absent",
        )
        f.check(
            "ADR-0014 enumerates what preflight does not do",
            all(
                token in flat14
                for token in (
                    "a fetch",
                    "a publication",
                    "a provider call",
                    "an AWS call",
                    "a credential retrieval",
                    "an environment lookup",
                    "a file read",
                )
            ),
            "an absence stated as a list is one a reader can check item by item",
        )
        f.check(
            "ADR-0014 records that there is no public execution method",
            "no qualification-run execution surface" in flat14
            and "no provider-fetch operation" in flat14
            and "no object-publication operation" in flat14
            and "no object to hold a runtime and no attribute to reach one through" in flat14,
            "a private attribute is reachable; only an absent object is not",
        )
        f.check(
            "ADR-0014 records that the first authenticated run stays separately gated",
            "The first authenticated qualification run remains separately gated" in flat14,
            "the gate is the absence of the code, and it must be said beside the wiring",
        )
        f.check(
            "ADR-0014 selects no provider and closes no gate",
            "selects no provider" in flat14
            and all(
                token in adr14
                for token in ("G1 OPEN", "G2 OPEN", "G4 OPEN", "G5 OPEN", "G6 OPEN", "G7 OPEN")
            )
            and "ADR-0005 remains" in adr14
            and "INC-0002 remains" in adr14,
            "joining five slices is not selecting a production provider",
        )
        f.check(
            "ADR-0014 records that QUALIFICATION stays fixed by the runtime",
            "remains fixed by the qualification runtime" in flat14
            and "nothing for a caller to supply or override" in flat14,
            "a mode a caller could choose would be a production operation with a name",
        )
        f.check(
            "ADR-0014 keeps CONTROL publication deferred",
            "CONTROL publication remains DEFERRED and NOT AUTHORIZED" in flat14,
            "the store refuses CONTROL at admission and nothing here changes that",
        )
        f.check(
            "ADR-0014 keeps real bindings and external activity unauthorized",
            "credential retrieval, inspection, creation, setup, storage or real binding" in flat14
            and "bucket discovery or real binding" in flat14
            and "AWS session or client construction" in flat14,
            "wiring that could be given real bindings is not permission to give it any",
        )
        f.check(
            "ADR-0014 supersedes only the live no-composition-root claim",
            'live "no composition root exists" claim only' in adr14
            and "Accepted ADRs are not rewritten" in flat14,
            "historical ADR text is evidence and is never edited",
        )
        f.check(
            "ADR-0014 discloses the escaping-runtime defect its first revision contained",
            "A leading underscore is a naming convention, not an execution barrier" in flat14
            and "composition._runtime.execute(plan)` ran" in flat14,
            "a correction that conceals what it corrected teaches a later reader nothing",
        )
        f.check(
            "ADR-0014 records the composition as a function, not a stateful object",
            "as one function" in flat14 and "no stateful object" in flat14,
            "the non-escape property has to be structural, not a naming convention",
        )
        f.check(
            "ADR-0014 distinguishes local construction from real binding",
            'Precisely what "no construction" does and does not mean here' in flat14
            and "AWS SDK session or S3-client construction" in flat14
            and "real bucket binding" in flat14,
            "a blanket 'client construction: NONE' was false once a client is built",
        )
        f.check(
            "ADR-0014 records that the result cannot describe an impossible run",
            "must describe a plan that could actually have passed" in flat14
            and "same compiled constants" in flat14,
            "zero requests and zero bytes described a validation that never happened",
        )
        f.check(
            "ADR-0014 records the transport contract at its owning boundary",
            "The transport contract is enforced where it is owned" in flat14
            and "A bound is not a bound if the thing it bounds can move it" in flat14,
            "a Protocol annotation is a static claim, and nothing checked it",
        )
        f.check(
            "ADR-0014 records one acquisition-mode constant in one module",
            "One acquisition-mode constant, in the module that owns it" in flat14
            and "defined once" in flat14,
            "two independent statements of one fact is a dual-write",
        )
        f.check(
            "ADR-0014 records that offline validation is itself work",
            "validation is work" in flat14 and "an earlier revision of this ADR did" in flat14,
            "'no way to run anything' was false while preflight validates a plan",
        )
        f.check(
            "ADR-0014 records that the caller keeps ownership of its arguments",
            "caller keeps ownership of everything it passed in" in flat14
            and "neither takes them over nor makes them go away" in flat14,
            "an argument does not stop existing because the callee returned",
        )
        f.check(
            "ADR-0014 scopes the retention claim away from object lifetime",
            "a claim about retention, not about object lifetime" in flat14
            and "makes no garbage-collection claim" in flat14
            and "a traceback may hold a frame" in flat14,
            "a guarantee that is false on an exception path is not a guarantee",
        )
        f.check(
            "ADR-0014 makes no composition overclaim",
            not _composition_overclaims(adr14),
            "each of these was written once and each is stronger than the code supports",
        )
        f.check(
            "ADR-0014 records the status vocabulary as a control",
            "VALIDATED_OFFLINE" in adr14
            and "Preflight is not a verdict" in flat14
            and all(word in adr14 for word in ("READY", "PROCEED", "APPROVED", "QUALIFIED")),
            "a status word a caller could read as permission is a governance defect",
        )

    # -- the module, as code -------------------------------------------------
    f.check(
        "the composition root exists",
        COMPOSITION_ROOT.is_file(),
        f"missing: {COMPOSITION_ROOT}",
    )
    if COMPOSITION_ROOT.is_file():
        composition = _executable_python(COMPOSITION_ROOT)
        f.check(
            "the composition constructs the three accepted components",
            all(
                token in composition
                for token in (
                    "SharadarClient(",
                    "S3ResearchObjectStore(",
                    "QualificationRuntime(",
                )
            ),
            "a composition root that constructs nothing is a name, not a slice",
        )
        f.check(
            "the composition exposes offline preflight and calls only validate",
            "def preflight_qualification_composition(" in composition
            and "runtime.validate(plan)" in composition,
            "validate fetches nothing and stores nothing; that is the whole dormancy claim",
        )
        f.check(
            "the composition exposes exactly one qualification-run execution surface",
            # Inverted by ADR-0017, not deleted. The earlier rule was that no such
            # surface existed, which was correct while offline preflight was the only
            # operation; deleting it would have left a second, unreviewed one
            # unguarded. Exactly one is named, and every other execution verb is
            # still refused -- a private spelling hides a callable from a reviewer,
            # not from a caller.
            composition.count("def execute_qualification_acquisition(") == 1
            and composition.count(".execute(") == 1
            and not any(
                f"def {verb}" in composition
                for verb in ("run", "fetch", "publish", "upload", "main", "ingest")
            ),
            "one authorized execution surface, and no second one under any spelling",
        )
        f.check(
            "the composition is a function, holding no state a caller could reach",
            not _composition_state_sites(),
            "a leading underscore is a naming convention, not an execution barrier",
        )
        f.check(
            "the composition builds its components as locals only",
            all(
                f"    {name} = {name.capitalize() if False else construction}(" in composition
                for name, construction in (
                    ("client", "SharadarClient"),
                    ("store", "S3ResearchObjectStore"),
                    ("runtime", "QualificationRuntime"),
                )
            ),
            "a local is not retained; an attribute on self, a class or a module is",
        )
        f.check(
            "the preflight result is bounded by the compiled constants",
            all(
                constant in composition
                for constant in (
                    "MAX_REQUESTS",
                    "MAX_ATTEMPTS_CEILING",
                    "MAX_RESPONSE_BYTES",
                    "MAX_RUN_BYTES",
                    "MAX_RETRY_BUDGET",
                )
            ),
            "a second set of numbers beside the plan's is a second thing to drift",
        )
        f.check(
            "the preflight result refuses counts no validated plan could produce",
            "if self.max_response_bytes > self.max_run_bytes:" in composition
            and "self.request_count * (self.max_attempts - 1) > self.retry_budget" in composition,
            "zero requests and zero bytes described a run that never happened",
        )
        f.check(
            "the composition module makes no reachability overclaim",
            not _composition_overclaims(read(COMPOSITION_ROOT)),
            "the module's own prose is read as the contract more often than the ADR",
        )
        f.check(
            "the composition states that the caller keeps its arguments",
            "The caller keeps what the caller passed in" in read(COMPOSITION_ROOT)
            and "caller-owned arguments" in read(COMPOSITION_ROOT),
            "an argument does not stop existing because the callee returned",
        )
        f.check(
            "the composition reads the single-source acquisition mode",
            "QUALIFICATION_ACQUISITION_MODE" in composition
            and "AcquisitionMode.QUALIFICATION" not in composition,
            "two independent spellings of one fact is a dual-write",
        )
        f.check(
            "the composition has no runner, entry point or argument parsing",
            'if __name__ == "__main__"' not in composition
            and "argparse" not in composition
            and "sys.argv" not in composition
            and "subprocess" not in composition,
            "an entry point is what turns dormant code into something a scheduler runs",
        )
        f.check(
            "the composition reads no environment, no file and no credential source",
            not any(
                token in composition
                for token in ("os.environ", "getenv", "credential_from_env", "reveal(", "open(")
            ),
            "a credential source is the one binding that would make this live",
        )
        f.check(
            "the composition imports no SDK and no network client",
            not any(
                f"import {module}" in composition
                for module in ("boto3", "botocore", "urllib", "requests", "socket", "os", "sys")
            ),
            "the S3 client is injected here as it is everywhere else",
        )
        f.check(
            "the composition names no host, bucket, endpoint, ARN or account",
            re.search(r"(https?://|s3://|arn:aws|amazonaws\.com|\b\d{12}\b)", composition) is None,
            "a real identifier in a dormant module is a real identifier",
        )
        f.check(
            "the composition admits only the provider-realistic profile",
            "PERMITTED_PROFILE" in composition and "PUBLIC_PIT" not in composition,
            "PUBLIC_PIT is refused by the type and is not named here at all",
        )
        f.check(
            "the composition fixes the acquisition mode and offers no override",
            "QUALIFICATION_ACQUISITION_MODE" in composition
            and "acquisition_mode="
            not in composition.replace("acquisition_mode=QUALIFICATION_ACQUISITION_MODE", ""),
            "one kind of retrieval, so there is nothing to choose",
        )
        f.check(
            "the composition uses no wording implying permission to run",
            not any(
                word in composition
                for word in ("PROCEED", "APPROVED", "QUALIFIED", "AUTHORIZED", "READY")
            ),
            "a caller must not be able to read arithmetic as permission",
        )
        f.check(
            "the composition does not touch the private harness or the test token",
            "sharadar_private_qualification" not in read(COMPOSITION_ROOT)
            and "test-api-key" not in read(COMPOSITION_ROOT),
            "the harness is an owner-run instrument and is not the composition root",
        )

    if PROVIDER_CLIENT.is_file():
        client_source = _executable_python(PROVIDER_CLIENT)
        f.check(
            "the client requires a callable transport get",
            "if not callable(get):" in client_source,
            "a Protocol annotation is a static claim; this is the runtime half",
        )
        f.check(
            "the client resolves the response ceiling once, at construction",
            "self._max_response_bytes = _resolve_response_ceiling(transport)" in client_source
            and "return self._max_response_bytes" in client_source,
            "a bound is not a bound if the thing it bounds can move it",
        )
        f.check(
            "the client retains the validated transport operation and calls that one",
            "_transport_get" in client_source
            and "self._transport_get = get" in client_source
            and "self._transport_get(" in client_source
            and "self._transport." not in client_source,
            "checking one object and invoking another is not validation",
        )
        f.check(
            "the client sanitizes a raising transport declaration",
            "def _resolve_response_ceiling" in client_source and "from None" in client_source,
            "a dependency's own exception text must not become the refusal",
        )

    f.check(
        "exactly one assignment defines the qualification acquisition mode",
        _qualification_mode_definitions() == 1,
        "one fact, one statement; two copies cannot be reconciled after the fact",
    )
    f.check(
        "only the one authorized module under src/ constructs the licensed store",
        sorted(path.name for path in _store_construction_sites()) == list(STORE_BUILDERS),
        "the permission is one named module, not a count that could drift",
    )
    f.check(
        # The caller-count correction, structurally. ADR-0017's caller is still
        # exactly one; the repository now has two, because the dormant ADR-0018
        # acquisition path merged. A third would be a path nobody reviewed.
        "exactly the two authorized modules under src/ call the qualification runtime",
        sorted(path.name for path in _runtime_execute_call_sites())
        == list(RUNTIME_EXECUTE_CALLERS),
        "two named modules, not a count that could drift",
    )
    f.check(
        "ADR-0017's composition still carries exactly one execute call",
        _executable_python(COMPOSITION_ROOT).count(".execute(") == 1,
        "the accepted path was extended once and has not grown a second call",
    )
    f.check(
        # Separation, not merely count. The acquisition path may not reach the
        # assessment read surface, and a shared import would be the route.
        "the acquisition caller cannot reach the assessment read surface",
        "assessment" not in _executable_python(ADR_0018_ACQUISITION),
        "a write-only acquisition path that can import the reader is not write-only",
    )
    f.check(
        "no module under src/ imports the AWS SDK",
        not _aws_sdk_import_sites(),
        "the SDK is declared so a future runner can construct a signed client",
    )
    f.check(
        "nothing outside its own tests constructs the composition",
        not _composition_construction_sites(),
        "the wiring exists and nobody uses it -- the whole slice in one property",
    )

    # -- the behavioural suite ------------------------------------------------
    if COMPOSITION_TESTS.is_file():
        composition_tests = read(COMPOSITION_TESTS)
        for label, needle in (
            ("required inputs", "test_every_composition_input_is_required_and_keyword_only"),
            ("the constructed components", "test_the_three_accepted_components_are_constructed"),
            ("validate rather than execute", "test_preflight_calls_validate_and_never_execute"),
            ("the offline status", "test_a_bounded_plan_validates_offline"),
            (
                "derived ceilings",
                "test_the_reported_numbers_are_derived_from_the_plan_and_the_client",
            ),
            ("the fixed mode", "test_no_caller_can_supply_or_override_the_acquisition_mode"),
            ("the profile", "test_the_profile_is_exactly_provider_realistic_pit"),
            ("zero provider and S3 calls", "test_a_successful_preflight_touches_no_transport"),
            ("no publication", "test_no_object_store_publication_occurs"),
            ("no credential reveal", "test_the_credential_is_never_revealed"),
            (
                "exactly one execution-like callable",
                "test_the_module_has_exactly_one_execution_like_callable",
            ),
            ("no escaping component", "test_no_executable_component_escapes_the_preflight"),
            ("no retained state", "test_the_module_holds_no_stateful_composition_object"),
            (
                "no durable component assignment",
                "test_no_assignment_stores_a_constructed_component_anywhere_durable",
            ),
            ("no returned component or closure", "test_the_module_returns_no_component_closure"),
            (
                "every adversarial result value",
                "test_the_result_refuses_a_value_no_validated_plan_could_produce",
            ),
            ("every legitimate boundary", "test_the_result_accepts_every_legitimate_boundary"),
            ("a transport without get", "test_a_transport_without_get_is_refused"),
            ("a frozen response ceiling", "test_the_transport_ceiling_is_read_exactly_once"),
            (
                "a mutating transport",
                "test_changing_the_transport_after_construction_cannot_move_the_ceiling",
            ),
            ("no caller anywhere", "test_nothing_calls_the_composition_outside_this_file"),
            ("the leak canaries", "test_no_canary_reaches_the_result_its_repr_or_captured_output"),
        ):
            f.check(
                f"a composition test covers {label}",
                needle in composition_tests,
                "the ADR's verification table must name tests that exist",
            )

    # -- the current documentation --------------------------------------------
    for name, path in (
        ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
        ("README.md", REPO_ROOT / "README.md"),
    ):
        if not path.is_file():
            continue
        body = read(path)
        flat = " ".join(body.replace("**", "").split())
        f.check(
            f"{name} records that one dormant composition root exists",
            "ADR-0014" in flat
            and "composition           ONE function, and no stateful object" in body,
            "the standing 'composition root: NONE' claim is no longer true",
        )
        f.check(
            f"{name} records that it constructs from injected values",
            "It constructs from injected values only" in flat,
            "constructing from injections is what keeps a constructed component inert",
        )
        f.check(
            f"{name} records that it exposes validation only",
            "exposed operation     offline preflight -- plan validation, and only that" in body
            and "qualification-run execution surface: NONE" in body,
            "validation is work, so the absence has to be scoped to a qualification run",
        )
        f.check(
            f"{name} records the four absences that keep it dormant",
            all(
                token in body
                for token in (
                    "components            LOCALS, built inside one call, not returned",
                    "provider-fetch operation: NONE",
                    "object-publication operation: NONE",
                    "runner                NONE",
                    "retained state        NONE",
                    "credential retrieval  NONE",
                    "real credential binding: NONE",
                    "real bucket binding: NONE",
                    "AWS SDK session / S3-client construction: NONE",
                )
            ),
            "each is separately checkable, so each is separately stated",
        )
        f.check(
            f"{name} records zero provider and AWS requests beside the composition",
            "Sharadar requests: ZERO   \u00b7   AWS requests: ZERO   \u00b7   Services Data: NONE"
            in body,
            "a composition that had sent one request would be a different slice",
        )
        f.check(
            f"{name} keeps the first authenticated run separately gated",
            "A further authenticated qualification run remains separately gated" in flat,
            "the wiring must never read as an approach to running",
        )
        f.check(
            f"{name} states each merged ADR as in force, once, naming its pull request",
            not _stale_adr_status_defects(name, body),
            "a merged decision shown as pre-merge reads as carrying no authority",
        )
        for adr, merged_in in MERGED_ADR_STATUS:
            f.check(
                f"{name} has exactly one current-status row for {adr}",
                len(_current_status_rows(body, adr)) == 1,
                "two rows for one decision is two answers to one question",
            )
            f.check(
                f"{name} records {adr} as ACCEPTED / IN FORCE, {merged_in}",
                any(
                    "ACCEPTED / IN FORCE" in row.replace("**", "").upper()
                    and merged_in.lower() in row.lower()
                    for row in _current_status_rows(body, adr)
                ),
                "the merge condition is satisfied, so the table must say so",
            )
        f.check(
            f"{name} states each merged phase as accepted, once, naming its pull request",
            not _stale_phase_status_defects(name, body),
            "a merged phase shown as conditional reads as work that has not landed",
        )
        for subject, required in MERGED_PHASE_STATUS:
            f.check(
                f"{name} has exactly one current-status row for {subject}",
                len(_phase_status_rows(body, subject)) == 1,
                "two rows for one phase is two answers to one question",
            )
            for phrase in required:
                f.check(
                    f"{name} records {subject} as {phrase}",
                    any(
                        phrase.upper() in " ".join(row.replace("**", "").split()).upper()
                        for row in _phase_status_rows(body, subject)
                    ),
                    "the status and the boundary are one claim; dropping half of it misleads",
                )
            f.check(
                f"{name} keeps pre-merge wording out of the {subject} row",
                not [
                    wording
                    for row in _phase_status_rows(body, subject)
                    for wording in PRE_MERGE_STATUS_WORDING
                    if wording.upper() in row.replace("**", "").upper()
                ],
                "PR #17 merged, so the condition is satisfied and the row must say so",
            )
        f.check(
            f"{name} keeps pre-merge wording out of its ADR status rows",
            not [
                wording
                for adr, _ in MERGED_ADR_STATUS
                for row in _current_status_rows(body, adr)
                for wording in PRE_MERGE_STATUS_WORDING
                if wording.upper() in row.replace("**", "").upper()
            ],
            "an ADR's own status line may say it; a current-status row may not",
        )
        f.check(
            f"{name} records that the caller keeps ownership of what it passed in",
            "caller-owned arguments" in body
            and "keeps ownership of every argument it passes in" in flat,
            "an argument does not stop existing because the callee returned",
        )
        f.check(
            f"{name} scopes the retention claim away from object lifetime",
            "about what *this function and its result* retain, not about object lifetimes" in flat
            and "not asserted on an exception path" in flat,
            "a traceback can hold a frame for as long as the caller keeps the exception",
        )
        f.check(
            f"{name} makes no composition overclaim",
            not _composition_overclaims(body),
            "each of these was written once and each is stronger than the code supports",
        )
        f.check(
            f"{name} states that the guards were narrowed rather than deleted",
            "architecture guards were narrowed, not deleted" in flat,
            "a guard removed to accommodate a slice is a guard that stopped guarding",
        )

    # -- 22. ADR-0015: the dormant private-binding preflight -----------------
    #
    # The slice narrows three standing absence claims at once -- no SDK client,
    # no credential source, no composition caller -- so the replacements have to
    # be held to, and the three future operational events have to stay separate.

    f.check(
        "ADR-0015 exists",
        ADR_BINDING.is_file(),
        f"missing: {ADR_BINDING}",
    )
    if ADR_BINDING.is_file():
        adr15 = read(ADR_BINDING)
        flat15 = " ".join(
            " ".join(line.lstrip("> ") for line in adr15.replace("**", "").splitlines()).split()
        )
        f.check(
            "ADR-0015 is accepted on merge and not before",
            "Accepted \u2014 effective on the merge" in adr15 and "carries no authority" in adr15,
            "the ADR must carry no authority until its pull request merges",
        )
        f.check(
            "ADR-0015 records the owner's authorization boundary verbatim",
            "code, tests, documentation, audits, and synthetic/local validation only" in flat15,
            "the boundary a slice was given is the boundary it must be read against",
        )
        f.check(
            "ADR-0015 separates the three future operational events",
            "Three separate future events" in flat15
            and "Private credential setup" in flat15
            and "A real binding preflight" in flat15
            and "authenticated Sharadar qualification run" in flat15
            and "implementing this path is none of them" in flat15,
            "setup, binding and running are three decisions, not one",
        )
        f.check(
            "ADR-0015 records the entry point as refused by default",
            "Refusing by default" in flat15
            and "no environment lookup, no credential lookup, no SDK construction" in flat15,
            "a path that does work on an ordinary invocation is not dormant",
        )
        f.check(
            "ADR-0015 records the boolean-authorization defect and its replacement",
            "The authorization is one object, admitted by identity" in flat15
            and "a boolean is the one value every" in flat15
            and "A field is copyable" in flat15
            and "copying manufactured a second bearer of authority" in flat15,
            "an authorization any caller can supply, or copy, is not an authorization",
        )
        f.check(
            "ADR-0015 scopes the capability claim away from runtime introspection",
            "not a claim about hostile runtime introspection" in flat15.lower(),
            "a process that can reach private names can build one, in any Python program",
        )
        f.check(
            "ADR-0015 records the argv secret-identifier defect and its replacement",
            "The secret identifier never travels in argv" in flat15
            and "shell history and every process listing" in flat15
            and "injected zero-argument source" in flat15,
            "redacting output does not help once the value is on the command line",
        )
        f.check(
            "ADR-0015 scopes the environment claim honestly",
            "One honest limit" in flat15
            and "would be false, and this ADR does not claim it" in flat15
            and "no credential-bearing variable" in flat15,
            "argparse reads locale and width variables whatever the program does",
        )
        f.check(
            "ADR-0015 records the authorizing flag and what it does not authorize",
            "i-am-the-operator-authorizing-binding-preflight" in adr15
            and "does not mint, imply or stand in for authorization to execute" in flat15,
            "a binding authorization that could be read as a run authorization is a defect",
        )
        f.check(
            "ADR-0015 records the ordering as the security property",
            "which is the security property" in flat15
            and "never reaches a secret" in flat15
            and "never reaches a credential" in flat15,
            "identity before state, bucket before secret, secret before construction",
        )
        f.check(
            "ADR-0015 reimplements no governed gate",
            "Nothing here reimplements a gate" in flat15,
            "a second copy of account matching is a second thing to get wrong",
        )
        f.check(
            "ADR-0015 binds the licensed bucket and refuses the control one",
            "The licensed bucket, never CONTROL" in flat15,
            "substituting the control bucket would put licensed rows in the wrong place",
        )
        f.check(
            "ADR-0015 records the one secrets operation and its refusals",
            "get_secret_value" in adr15
            and "SecretString` only" in flat15
            and "refused, not decoded" in flat15
            and "no JSON parsing, no key guessing, no alias, no default" in flat15,
            "multi-key guessing selects a wrong value silently",
        )
        f.check(
            "ADR-0015 keeps the SDK out of the data platform",
            "no module under `src/` imports the SDK" in adr15,
            "importing the platform must still open no socket",
        )
        f.check(
            "ADR-0015 records that only the offline composition is called",
            "calls `preflight_qualification_composition` and **nothing else**" in adr15,
            "one operation, and no route to a fetch or a publication",
        )
        f.check(
            "ADR-0015 admits no permission-bearing output vocabulary",
            "No permission-bearing vocabulary is added" in flat15
            and all(word in adr15 for word in ("READY", "APPROVED", "PROCEED", "QUALIFIED")),
            "a status word a caller could read as permission is a governance defect",
        )
        f.check(
            "ADR-0015 records the exit status as a command status, not a verdict",
            "reports command success or refusal only" in flat15,
            "an exit code that meant 'qualified' would be a provider conclusion in a shell",
        )
        f.check(
            "ADR-0015 leaves the private harness alone",
            "does not import, invoke, modify or repurpose it" in flat15,
            "the published-token harness is a separate historical instrument",
        )
        f.check(
            "ADR-0015 names the three claims it narrows",
            "Given up" in flat15
            and "no credential source exists" in flat15
            and "has ever been run" in flat15,
            "a superseded claim must be replaced by a narrower one, not dropped",
        )
        f.check(
            "ADR-0015 selects no provider and closes no gate",
            "selects no provider" in flat15
            and all(
                token in adr15
                for token in ("G1 OPEN", "G2 OPEN", "G4 OPEN", "G5 OPEN", "G6 OPEN", "G7 OPEN")
            )
            and "ADR-0005 remains" in adr15
            and "INC-0002 remains" in adr15,
            "writing a binding path is not selecting a production provider",
        )
        f.check(
            "ADR-0015 states its non-authorizations exhaustively",
            "retrieving, revealing, copying, rotating or storing a real API key" in flat15
            and "creating or updating a Secrets Manager secret" in flat15
            and "Terraform init, plan, apply, output or verification" in flat15,
            "an implementation path is not permission to walk it",
        )
        f.check(
            "ADR-0015 keeps every accepted decision unchanged",
            "Unchanged." in adr15
            and "AcquisitionMode.QUALIFICATION" in adr15
            and "PROVIDER_REALISTIC_PIT" in adr15
            and "CONTROL deferral" in flat15,
            "a binding path changes no contract",
        )

    # -- the entry point, as code --------------------------------------------
    f.check(
        "the binding preflight entry point exists",
        BINDING_PREFLIGHT.is_file(),
        f"missing: {BINDING_PREFLIGHT}",
    )
    if BINDING_PREFLIGHT.is_file():
        binding = _executable_python(BINDING_PREFLIGHT)
        f.check(
            "the entry point refuses without an explicit operator authorization",
            "BINDING_AUTHORIZATION_FLAG" in binding
            and "i-am-the-operator-authorizing-binding-preflight" in binding
            and "if not _is_authorized(authorization):" in binding,
            "a minted capability; a boolean is the one value every caller already has",
        )
        f.check(
            "the authorization is one object, admitted by identity",
            "class _BindingAuthorization" in binding
            and "candidate is _BINDING_PREFLIGHT_AUTHORIZATION" in binding,
            "identity against the single instance; a copy is a different object",
        )
        f.check(
            "admission reads no copyable field",
            "_mint" not in binding and "_AUTHORIZATION_MINT" not in binding,
            "a field is copyable, and copy.copy admitted a distinct bearer through one",
        )
        f.check(
            "the capability carries no state to copy",
            "__slots__ = ()" in binding,
            "no state means no field for a copy to carry across",
        )
        f.check(
            "every route to a second instance is closed",
            all(
                closure in binding
                for closure in (
                    "def __new__",
                    "def __copy__",
                    "def __deepcopy__",
                    "def __reduce__",
                    "def __init_subclass__",
                )
            ),
            "construction, copying, deep copying, pickling and subclassing each refuse",
        )
        f.check(
            "no boolean authorization parameter survives anywhere in the entry point",
            "binding_authorized" not in binding,
            "the first revision took a bool, so any importer could pass True",
        )
        f.check(
            "the capability refuses subclassing, copying and serialisation",
            all(
                refusal in read(BINDING_PREFLIGHT)
                for refusal in (
                    "may not be subclassed",
                    "may not be copied",
                    "may not be serialised",
                )
            ),
            "each is a route to a second object, and a second object is a second bearer",
        )
        f.check(
            "the capability class and the authorization object are not exported",
            all(
                name not in _entry_point_exports()
                for name in ("_BindingAuthorization", "_BINDING_PREFLIGHT_AUTHORIZATION")
            )
            # The retired field-based names must not come back either.
            and all(
                name not in read(BINDING_PREFLIGHT)
                for name in ("_AUTHORIZATION_MINT", "_mint_binding_authorization")
            ),
            "an exported authorization is a public constructor by another name",
        )
        f.check(
            "the authorization is handed over at exactly one place",
            _authorization_handover_sites() == ["main"],
            "one site, inside the branch the flag has already been checked in",
        )
        f.check(
            "no secret identifier is accepted on the command line",
            not _argv_secret_identifier_options(),
            "a private identifier in argv enters shell history and every process listing",
        )
        f.check(
            "the command-line secret spellings are refused by name",
            all(
                option in binding
                for option in ("--secret-id", "--secret-name", "--secretid", "--secret-arn")
            ),
            "silently ignoring a spelling invites a second attempt with another",
        )
        f.check(
            "the secret identifier comes from an injected source, resolved late",
            "secret_id_source: Callable[[], str]" in read(BINDING_PREFLIGHT)
            and "secret_id = secret_id_source()" in binding,
            "a private identifier must not be resolved on a path that will refuse",
        )
        f.check(
            "the production identifier source reads one fixed variable name",
            "SECRET_ID_ENV_VAR" in binding and binding.count("os.environ") <= 2,
            "one name, on the authorized path, and nothing ambient anywhere else",
        )
        f.check(
            "the entry point imports os only inside a factory body",
            not any(
                node_line.strip() == "import os"
                for node_line in read(BINDING_PREFLIGHT).splitlines()
                if not node_line.startswith(" ")
            ),
            "a module-level os import would make an ordinary import read an environment",
        )
        f.check(
            "the entry point refuses the habitual flags by name",
            all(option in binding for option in ("--run", "--live", "--execute", "--force")),
            "an unrecognised-argument error teaches nothing and invites a second spelling",
        )
        f.check(
            "the entry point calls only the offline composition",
            "preflight_qualification_composition(" in binding
            and not any(
                forbidden in binding
                for forbidden in (
                    ".execute(",
                    "put_object",
                    "head_object",
                    "put_if_absent",
                    "publish_bronze_payload",
                    "publish_sharadar_payload",
                )
            ),
            "one operation, and no route to a fetch or a publication",
        )
        f.check(
            "the entry point reuses the governed identity gate and state read",
            "identity_gate" in binding and "tf_outputs" in binding,
            "a second implementation of account matching is a second thing to get wrong",
        )
        f.check(
            "the entry point names the licensed bucket output and no control one",
            "licensed_bucket_name" in binding
            and "control_bucket_name" not in binding
            and "CONTROL" not in binding,
            "the control bucket must not be substitutable for the licensed one",
        )
        f.check(
            "the entry point pins the governed profile and region",
            'EXPECTED_PROFILE: Final = "kalpamani-foundation"' in read(BINDING_PREFLIGHT)
            and 'EXPECTED_REGION: Final = "us-east-1"' in read(BINDING_PREFLIGHT),
            "an unpinned profile is the wrong-account hazard CLAUDE.md 4.24 names",
        )
        f.check(
            "the entry point emits only an allowlisted vocabulary",
            "class PreflightOutcome" in binding
            and not any(
                word in _emitted_preflight_sentences(BINDING_PREFLIGHT).upper()
                for word in ("READY", "APPROVED", "AUTHORIZED", "PROCEED", "QUALIFIED", "BOUND")
            ),
            "a caller must not read a status line as permission to run",
        )
        f.check(
            "the entry point carries no private identifier",
            not any(
                marker in read(BINDING_PREFLIGHT)
                for marker in ("arn:aws:", "amazonaws.com", "s3://", "test-api-key")
            )
            and re.search(r"\b\d{12}\b", read(BINDING_PREFLIGHT)) is None,
            "a private identifier in a tracked file is a public one",
        )
        f.check(
            "the entry point scopes what is injected against what it alone may construct",
            all(
                phrase in " ".join(read(BINDING_PREFLIGHT).replace("**", "").split())
                for phrase in BINDING_SOURCE_SCOPE
            ),
            "'no credential source, no bucket resolution, no constructed AWS client' denied "
            "the boundary this file is",
        )
        f.check(
            "the entry point claims no absent credential source or construction path",
            not [
                claim
                for claim in STALE_BINDING_ABSENCE_CLAIMS
                if claim in " ".join(read(BINDING_PREFLIGHT).replace("**", "").split()).upper()
            ],
            "the downstream components cannot discover a binding; this file can resolve one",
        )
        f.check(
            "the entry point documents the four authorized attempts and their scope",
            all(
                phrase in " ".join(read(BINDING_PREFLIGHT).replace("**", "").split())
                for phrase in BINDING_SOURCE_HISTORY
            ),
            "'never run' was true of the merge and false of the operation",
        )
        f.check(
            "the entry point documents the fourth attempt and its identity refusal",
            all(
                phrase in " ".join(read(BINDING_PREFLIGHT).replace("**", "").split())
                for phrase in BINDING_SOURCE_FOURTH
            ),
            "the source documentation is a current-status surface like any other",
        )
        f.check(
            "the entry point's main docstring records which attempts reached construction",
            all(
                phrase in " ".join(read(BINDING_PREFLIGHT).replace("**", "").split())
                for phrase in BINDING_SOURCE_MAIN_HISTORY
            ),
            "a stale count beside the one authorized SDK construction is the worst place for one",
        )
        f.check(
            "the entry point records which real factories have run, per factory",
            all(phrase in read(BINDING_PREFLIGHT) for phrase in BINDING_SOURCE_FACTORY_HISTORY),
            "two ran on every attempt, one on three, one twice, and three ran once",
        )
        f.check(
            "the entry point accepts exactly the authorization flag, --subject and --execution-id",
            # Read from the parser, not from a fingerprint. A fingerprint says the
            # file changed; this says what the program accepts, so renaming or
            # adding an option fails here with the reason rather than as a hash
            # mismatch somebody has to interpret.
            _accepted_cli_options(BINDING_PREFLIGHT)
            == (
                ("--i-am-the-operator-authorizing-binding-preflight",),
                ("--subject",),
                ("--execution-id",),
            ),
            "the operator surface is three options; a fourth, a rename or an "
            "unresolvable declaration all widen what can be asked of it",
        )
        f.check(
            "the entry point documents the fifth attempt and what it did not establish",
            all(
                phrase in " ".join(read(BINDING_PREFLIGHT).replace("**", "").split())
                for phrase in BINDING_SOURCE_FIFTH
            ),
            "the source documentation is a current-status surface, and it is read alone",
        )
        f.check(
            "the entry point carries no stale or overstated fifth-attempt claim",
            not [
                claim
                for claim in STALE_FIFTH_ATTEMPT_CLAIMS
                if claim in " ".join(read(BINDING_PREFLIGHT).replace("**", "").split()).upper()
            ],
            "the file that ran is the last place a superseded count should survive",
        )
        f.check(
            "the entry point's required documentation stays out of executable source",
            not [
                phrase
                for phrase in BINDING_SOURCE_FIFTH
                if phrase in " ".join(_executable_python(BINDING_PREFLIGHT).split())
            ],
            "a required sentence moved into a string literal would satisfy the guard while "
            "changing what the program is",
        )
        preflight_prose, _, factory_region = read(BINDING_PREFLIGHT).partition(
            FACTORY_SECTION_MARKER
        )
        f.check(
            "the entry point splits its prose from its real-factory section",
            bool(factory_region),
            "without the banner the two surfaces cannot be held to separate requirements",
        )
        f.check(
            "the module event table names the variable the fourth attempt did not read",
            EVENT_TABLE_IDENTIFIER_SCOPE in " ".join(preflight_prose.replace("**", "").split()),
            "'the environment variable' is the wording that was wrong; naming it is the fix",
        )
        f.check(
            "the real-factory commentary names that variable and scopes the profile read",
            all(phrase in factory_region for phrase in FACTORY_IDENTIFIER_SCOPE),
            "the same correction is needed twice, because it is stated in two places",
        )
        f.check(
            "the entry point claims no blanket environment-read absence",
            not [
                claim
                for claim in STALE_ENVIRONMENT_READ_CLAIMS
                if claim in _comment_prose(read(BINDING_PREFLIGHT))
            ],
            "_ambient_profile read AWS_PROFILE on all four attempts, the fourth included",
        )
        f.check(
            "the entry point denies no AWS_PROFILE read",
            not [
                denial
                for denial in PROFILE_READ_DENIALS
                if denial in _comment_prose(read(BINDING_PREFLIGHT))
            ],
            "correcting an overbroad absence must not manufacture the opposite one",
        )
        f.check(
            "the entry point records the post-fourth diagnosis as a distinct completed event",
            all(
                phrase in _comment_prose(read(BINDING_PREFLIGHT))
                for phrase in BINDING_SOURCE_DIAGNOSIS
            ),
            "its docstring is a current-status surface, and diagnosis is no longer future",
        )
        binding_docs = _documentation_surface(BINDING_PREFLIGHT)
        for label, phrase in BINDING_SOURCE_ATTEMPT4_REQUIRED:
            f.check(
                f"the binding preflight's own documentation {label}",
                phrase in binding_docs,
                f"missing from the binding preflight's documentation: {phrase}",
            )
        stale_binding_source = [
            claim for claim in BINDING_SOURCE_ATTEMPT4_FORBIDDEN if claim in binding_docs.upper()
        ]
        f.check(
            "the binding preflight's own documentation fixes no STS, network or SSO conclusion",
            not stale_binding_source,
            ", ".join(stale_binding_source),
        )
        f.check(
            "the attempt-4 source denylist states its own size, derived from its tuple",
            (
                f"{len(BINDING_SOURCE_ATTEMPT4_FORBIDDEN)} attempt-4 STS and SSO claims "
                "are refused here" in read(Path(__file__).resolve())
            ),
            "a denylist that quietly loses an entry checks less and reports the same",
        )
        f.check(
            "the entry point carries no stale claim that no diagnosis occurred",
            not [
                claim
                for claim in STALE_NO_DIAGNOSIS_CLAIMS
                if claim in _comment_prose(read(BINDING_PREFLIGHT)).upper()
            ],
            "the module said diagnosis and an SSO refresh were one unperformed action",
        )
        f.check(
            "the entry point claims nothing the diagnosis did not establish",
            not [
                claim
                for claim in DIAGNOSIS_OVERCLAIMS
                if claim in _comment_prose(read(BINDING_PREFLIGHT)).upper()
            ],
            "missing or expired, undistinguished, and nothing repaired afterwards",
        )
        f.check(
            "the entry point records the timed-out SSO-login attempt",
            all(
                phrase in _comment_prose(read(BINDING_PREFLIGHT))
                for phrase in BINDING_SOURCE_SSO_LOGIN
            ),
            "an operator opening this file must not need a status document to learn it failed",
        )
        f.check(
            "the entry point carries no stale zero-SSO-login claim",
            not [
                claim
                for claim in STALE_SSO_LOGIN_CLAIMS
                if claim in _comment_prose(read(BINDING_PREFLIGHT)).upper()
            ],
            "its docstring said an SSO refresh was entirely future; one has been attempted",
        )
        f.check(
            "the entry point claims nothing the timed-out SSO-login attempt did not establish",
            not [
                claim
                for claim in SSO_LOGIN_OVERCLAIMS
                if claim in _comment_prose(read(BINDING_PREFLIGHT)).upper()
            ],
            "the first attempt brought no success, no identity and no proven cause",
        )
        f.check(
            "the entry point records the corrected SSO login and the identity confirmation",
            all(
                phrase in _comment_prose(read(BINDING_PREFLIGHT))
                for phrase in BINDING_SOURCE_CORRECTED_SSO
            ),
            "an operator opening this file must not need a status document to learn it worked",
        )
        f.check(
            "the entry point carries no stale zero-refresh or never-confirmed claim",
            not [
                claim
                for claim in STALE_CORRECTED_SSO_CLAIMS
                if claim in _comment_prose(read(BINDING_PREFLIGHT)).upper()
            ],
            "its docstring is a current-status surface, and the session has been refreshed",
        )
        f.check(
            "the entry point claims nothing the corrected refresh established",
            not [
                claim
                for claim in CORRECTED_SSO_OVERCLAIMS
                if claim in _comment_prose(read(BINDING_PREFLIGHT)).upper()
            ],
            "a refreshed session is not a verified secret and not a standing identity",
        )
        binding_documentation = _source_documentation(BINDING_PREFLIGHT)
        f.check(
            "the entry point's documentation region is extractable",
            bool(binding_documentation),
            "an unresolvable region would guard nothing while reporting a pass",
        )
        f.check(
            "the entry point separates the observed contrast from an inferred cause",
            all(fact in binding_documentation for fact in BINDING_SOURCE_CAUSE_SCOPE),
            "docstrings and comments only, so executable text cannot answer for them",
        )
        f.check(
            "the entry point claims no proven cause for the first attempt's timeout",
            not [claim for claim in SSO_CAUSE_OVERCLAIMS if claim in binding_documentation.upper()],
            "wrapping hid this for two rounds; the region is flattened before it is read",
        )
        f.check(
            "the entry point's factory commentary no longer calls all diagnosis future",
            "Diagnosis is no longer entirely future:" in read(BINDING_PREFLIGHT)
            and "further AWS authentication diagnosis, another SSO refresh, additional"
            in read(BINDING_PREFLIGHT),
            "one diagnosis ran; only a further one is gated",
        )
        f.check(
            "the entry point claims no absent STS identity call for attempt 4",
            not [
                claim
                for claim in STALE_GATE_PROBE_CLAIMS
                if claim in _comment_prose(read(BINDING_PREFLIGHT)).upper()
            ],
            "its own gate runs sts get-caller-identity; the docstring may not deny it",
        )
        f.check(
            "the entry point neither merges the two operations nor totals them",
            not [
                claim
                for claim in GATE_DIAGNOSIS_CONFLATIONS
                if claim in _comment_prose(read(BINDING_PREFLIGHT)).upper()
            ],
            "the gate's call and the standalone command are separate, uncounted events",
        )
        audit_source = read(Path(__file__).resolve())
        try:
            fixture_start, fixture_end = _audit_fixture_span(audit_source)
            audit_outside_fixture = _audit_prose_excluding_own_fixture(audit_source)
            exclusion_resolved = True
        except (ValueError, SyntaxError):
            # Fail closed. An unresolvable boundary leaves nothing scanned, so
            # both guards below must report the failure rather than pass on an
            # empty surface.
            fixture_start, fixture_end = 0, 0
            audit_outside_fixture = ""
            exclusion_resolved = False
        f.check(
            "the fixture exclusion resolves to exactly the assignment's own lines",
            exclusion_resolved
            and len(audit_source.splitlines()) - len(audit_outside_fixture.splitlines())
            == fixture_end - fixture_start + 1,
            "a raw-delimiter boundary ran past the tuple and hid unrelated prose",
        )
        f.check(
            "the fixture exclusion keeps the prose on either side of the assignment",
            exclusion_resolved
            and audit_source.splitlines()[fixture_start - 2] in audit_outside_fixture
            and audit_source.splitlines()[fixture_end] in audit_outside_fixture,
            "the lines around the fixture are exactly where a stale claim reappears",
        )
        f.check(
            "this audit's own diagnostics do not deny the completed diagnosis",
            exclusion_resolved
            and not [
                claim
                for claim in STALE_AUDIT_DIAGNOSTICS
                if claim in _comment_prose(audit_outside_fixture)
            ],
            "its comments and labels are a status surface, and one diagnosis has run",
        )
        f.check(
            "the refused phrases are still members of the denylists that enforce them",
            # Membership, not occurrence. The previous form asked whether these
            # strings appeared anywhere in this file, and each appears twice --
            # once in the real denylist and once in the check's own tuple -- so
            # deleting the enforcing entry left the guard green on its own copy.
            all(phrase in denylist for phrase, denylist in REQUIRED_FIXTURE_MEMBERSHIP),
            "a fixture is test data only while the denylist that enforces it still holds it",
        )
        f.check(
            "the entry point makes no unqualified profile-disclosure claim",
            not [
                claim
                for claim in STALE_PROFILE_DISCLOSURE_CLAIMS
                if claim in _comment_prose(read(BINDING_PREFLIGHT)).upper()
            ],
            "EXPECTED_PROFILE already existed in tracked source before the diagnosis ran",
        )
        f.check(
            "the entry point carries no stale three-attempt claim",
            not [
                claim
                for claim in STALE_ATTEMPT_COUNT_CLAIMS
                if claim in " ".join(read(BINDING_PREFLIGHT).replace("**", "").split()).upper()
            ],
            "a fourth attempt happened; its own docstring may not still say three",
        )
        f.check(
            "the entry point states no definite network-request count for the fourth attempt",
            not [
                claim
                for claim in FOURTH_ATTEMPT_NETWORK_CLAIMS
                if claim in " ".join(read(BINDING_PREFLIGHT).replace("**", "").split()).upper()
            ],
            "neither zero nor one is established by an identity gate that did not pass",
        )
        f.check(
            "the entry point does not overstate the post-fourth diagnosis as an exact "
            "or contemporaneous cause",
            not [
                claim
                for claim in SSO_EXACT_STATE_OVERCLAIMS
                if claim in " ".join(read(BINDING_PREFLIGHT).replace("**", "").split()).upper()
            ],
            "the later diagnosis is direct evidence; it fixes neither the exact state nor "
            "a request count",
        )
        f.check(
            "the entry point makes no stale zero-AWS or never-run claim",
            not [
                claim
                for claim in STALE_PREFLIGHT_CLAIMS
                if claim in " ".join(read(BINDING_PREFLIGHT).split()).upper()
            ],
            "the source documentation is a current-status surface like any other",
        )
        f.check(
            "the entry point claims nothing about the owner's setup that it established",
            not [
                claim
                for claim in OWNER_SETUP_FORBIDDEN_CLAIMS
                if claim in " ".join(read(BINDING_PREFLIGHT).replace("**", "").split()).upper()
            ],
            "this file has resolved no identifier, built no client and retrieved no credential",
        )
        f.check(
            "the entry point does not still call the identifier configuration unknown",
            not [
                claim
                for claim in STALE_IDENTIFIER_UNKNOWN_CLAIMS
                if claim in " ".join(read(BINDING_PREFLIGHT).replace("**", "").split()).upper()
            ],
            "its docstring is a current-status surface, and the owner has since configured it",
        )
        f.check(
            "the entry point does not touch the private harness",
            # Docstring-stripped: the module *says* it leaves the harness alone,
            # and a raw scan would forbid saying so.
            "sharadar_private_qualification" not in binding,
            "the published-token harness is a separate instrument",
        )

    # -- the secrets boundary -------------------------------------------------
    f.check(
        "the secrets boundary exists",
        SECRETS_BOUNDARY.is_file(),
        f"missing: {SECRETS_BOUNDARY}",
    )
    if SECRETS_BOUNDARY.is_file():
        secrets = _executable_python(SECRETS_BOUNDARY)
        f.check(
            "the secrets boundary imports no SDK and constructs no client",
            not any(marker in secrets for marker in ("boto3", "botocore", "environ", "open(")),
            "the client is injected here as it is everywhere else",
        )
        f.check(
            "the secrets boundary exposes one operation and no other",
            "get_secret_value" in secrets
            and not any(
                other in secrets
                for other in (
                    "list_secrets",
                    "describe_secret",
                    "put_secret_value",
                    "update_secret",
                    "delete_secret",
                )
            ),
            "reading one value is the least authority that does the job",
        )
        f.check(
            "the secrets boundary refuses binary rather than decoding it",
            "SECRET_BINARY_REFUSED" in secrets and "SecretBinary" in secrets,
            "guessing at an encoding is how a wrong value reaches a request",
        )
        f.check(
            "the secrets boundary hands the value straight to the credential",
            "SharadarCredential(value)" in secrets,
            "a value held anywhere else is a value that can be logged",
        )
        f.check(
            "every secrets refusal suppresses its cause",
            secrets.count("from None") >= 6,
            "a backend exception quotes the secret name and often the account",
        )

    f.check(
        "only the authorized operator entry points construct an SDK client",
        # ADR-0015 authorized one; ADR-0017 a second; the ADR-0018 implementation
        # candidate adds its two operator entry points. All four are named, so a
        # fifth arriving anywhere fails -- a count could drift, a list cannot.
        sorted(path.name for path in _sdk_client_construction_sites()) == list(SDK_CONSTRUCTORS),
        "four named modules, not a count that could drift",
    )
    f.check(
        "no module under src/ imports the AWS SDK",
        not _aws_sdk_import_sites(),
        "importing the data platform must still open no socket",
    )

    # -- the behavioural suite -------------------------------------------------
    if BINDING_TESTS.is_file():
        binding_tests = read(BINDING_TESTS)
        for label, needle in (
            ("import doing nothing", "test_importing_the_entry_point_runs_nothing"),
            (
                "refusal without an authorization",
                "test_invocation_without_an_authorization_refuses_before_any_stage",
            ),
            ("unforgeable authorization", "test_authorization_cannot_be_forged"),
            ("no second construction", "test_the_capability_cannot_be_constructed_a_second_time"),
            ("refused subclassing", "test_the_capability_refuses_subclassing"),
            ("an uninitialised instance", "test_an_uninitialised_instance_is_not_an_authorization"),
            ("copying producing no object", "test_copying_produces_no_object_at_all"),
            ("no distinct object admitted", "test_no_distinct_object_is_ever_admitted"),
            ("refused serialisation", "test_serialisation_produces_no_object_either"),
            ("identity admission with no field", "test_admission_is_identity_and_reads_no_field"),
            (
                "the parser handing over that object",
                "test_the_parser_path_hands_over_exactly_that_object",
            ),
            ("one hand-over site", "test_only_main_hands_over_the_authorization"),
            (
                "a refused command-line identifier",
                "test_a_command_line_secret_identifier_is_refused_by_name",
            ),
            (
                "the identifier untouched by earlier refusals",
                "test_the_identifier_source_is_untouched_by_every_earlier_refusal",
            ),
            (
                "one identifier resolution, in order",
                "test_the_identifier_source_is_called_exactly_once_in_order",
            ),
            (
                "no credential-bearing default lookup",
                "test_the_default_path_reads_no_credential_bearing_environment_variable",
            ),
            ("a profile mismatch", "test_a_profile_mismatch_refuses_before_the_identity_call"),
            (
                "an identity failure",
                "test_an_identity_failure_refuses_before_state_secret_or_composition",
            ),
            ("a bucket failure", "test_a_bucket_failure_refuses_before_secret_retrieval"),
            ("a secret failure", "test_a_secret_failure_refuses_before_composition"),
            ("the exact ordering", "test_the_full_ordering_is_exact_on_the_authorized_path"),
            ("every unusable secret response", "test_every_unusable_secret_response_is_refused"),
            ("suppressed causes", "test_every_secret_refusal_is_raised_from_none"),
            ("the leak canaries", "test_no_canary_reaches_a_refusal_at_any_stage"),
            ("the licensed bucket", "test_the_entry_point_names_the_licensed_bucket_output"),
            ("one composition call", "test_the_authorized_path_invokes_the_composition_preflight"),
            ("no runtime execution", "test_no_qualification_runtime_execution_occurs"),
            (
                "zero provider and S3 calls",
                "test_provider_and_object_store_call_counts_remain_zero",
            ),
            ("no credential reveal", "test_the_credential_is_never_revealed_during_preflight"),
            ("nothing escaping", "test_nothing_escapes_in_the_result"),
            ("the offline status", "test_the_status_is_exactly_validated_offline"),
            (
                "the output vocabulary",
                "test_the_output_vocabulary_admits_no_permission_bearing_word",
            ),
            (
                "the authorized SDK constructors",
                "test_only_the_authorized_entry_points_construct_an_sdk_client",
            ),
        ):
            f.check(
                f"a binding-preflight test covers {label}",
                needle in binding_tests,
                "the ADR's verification table must name tests that exist",
            )

    # -- the current documentation --------------------------------------------
    for name, path in (
        ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
        ("README.md", REPO_ROOT / "README.md"),
    ):
        if not path.is_file():
            continue
        body = read(path)
        flat = " ".join(body.replace("**", "").split())
        f.check(
            f"{name} records the dormant private-binding preflight",
            "ADR-0015" in flat and "default behaviour     REFUSE" in body,
            "the standing 'no credential source exists' claim is no longer true as written",
        )
        f.check(
            f"{name} records the two authorization defects and the identity replacement",
            "One object, admitted by identity" in flat
            and "any importer could pass" in flat
            and "a field is copyable" in flat.lower()
            and "copying manufactured a second bearer" in flat,
            "a boolean any caller has, and a field any caller can copy, are both forgeable",
        )
        f.check(
            f"{name} records that no route to a second object survives",
            "Nothing to copy, and no route to a second" in flat
            and "yield no object at all" in flat,
            "construction, copying, deep copying, pickling and subclassing each refuse",
        )
        f.check(
            f"{name} records that the secret identifier never enters argv",
            "The secret identifier never enters argv" in flat
            and "shell history and every process listing" in flat,
            "a private identifier on the command line is disclosed before anything runs",
        )
        f.check(
            f"{name} states the bucket facts rather than a binding verdict",
            # "real bucket binding performed: NONE" was the wrong shape once the
            # fifth attempt resolved the governed bucket and built a real S3
            # client. The repository never defined the threshold that phrase
            # names -- the composition root reports it NONE while constructing a
            # store from a caller-supplied bucket string, and the ADR-0011
            # section lists a constructed SDK client and a bound bucket as two
            # separate absent items without naming the act that produces the
            # second. So the guard requires the three checkable facts and
            # refuses a claim in either direction.
            all(fact in body for fact in BUCKET_FACTS_NOT_A_VERDICT),
            "the term is undefined here; bucket resolution, client construction and "
            "object operations are the facts",
        )
        f.check(
            f"{name} separates owner-side secret creation from reads by this repository",
            all(fact in body for fact in SECRET_CREATION_AND_READ_FACTS),
            "one sentence reported two subjects, and could only be right about one",
        )
        f.check(
            f"{name} no longer carries the combined secret creation-or-read line",
            STALE_SECRET_CREATED_OR_READ not in body,
            "owner-side creation is attested; that line denies it to report the read count",
        )
        f.check(
            f"{name} states the corrected top-level credential-setup row",
            bool(_phase_status_rows(body, CREDENTIAL_SETUP_ROW_SUBJECT))
            and all(
                fact in " ".join(row.replace("**", "").split()).upper()
                for row in _phase_status_rows(body, CREDENTIAL_SETUP_ROW_SUBJECT)
                for fact in CREDENTIAL_SETUP_ROW_FACTS
            ),
            "one verdict over setup, access and ingestion goes stale when any one moves",
        )
        f.check(
            f"{name} states the corrected provider-credential-state row",
            bool(_phase_status_rows(body, PROVIDER_CREDENTIAL_ROW_SUBJECT))
            and all(
                fact in " ".join(row.replace("**", "").split()).upper()
                for row in _phase_status_rows(body, PROVIDER_CREDENTIAL_ROW_SUBJECT)
                for fact in PROVIDER_CREDENTIAL_ROW_FACTS
            ),
            "an owner-held key is not repository access, and the row must say both",
        )
        f.check(
            f"{name} scopes the four remaining future actions separately",
            all(
                boundary in _document_section(body, ADR_0015_SECTION_HEADING)
                for boundary in FUTURE_ACTION_BOUNDARIES
            ),
            "one of the three has happened; a shared verdict cannot report that",
        )
        f.check(
            f"{name} no longer carries the combined future-action line",
            STALE_FUTURE_ACTION_LINE not in body,
            "a synchronization was authorized and performed; only a further one is gated",
        )
        f.check(
            f"{name} does not deny the environment synchronization that occurred",
            not [claim for claim in DENIED_SYNCHRONIZATION_CLAIMS if claim in flat.upper()],
            "the chronology records it; a current-status line may not contradict it",
        )
        f.check(
            f"{name} no longer carries the collective credential-setup row",
            not [
                row
                for row in body.splitlines()
                if row.lstrip().startswith("|")
                and STALE_CREDENTIAL_SETUP_ROW_SUBJECT in row.split("|")[1]
            ],
            "owner-side setup has happened; a row labelling it NOT AUTHORIZED is false",
        )
        f.check(
            f"{name} records the scoped counts the four attempts left at zero",
            all(
                token in _document_section(body, ADR_0015_SECTION_HEADING)
                for token in ADR_0015_SECTION_COUNTS
            ),
            "the zeros are Secrets Manager, S3 and Sharadar -- not AWS as a whole",
        )
        f.check(
            f"{name} records the operational history of the four authorized attempts",
            all(
                phrase
                in " ".join(
                    _document_section(body, ADR_0015_SECTION_HEADING).replace("**", "").split()
                )
                for phrase in ADR_0015_SECTION_HISTORY
            ),
            "implementation-time inactivity and four later operator runs are different facts",
        )
        f.check(
            f"{name} makes no stale zero-AWS or never-run claim in the ADR-0015 section",
            not [
                claim
                for claim in STALE_PREFLIGHT_CLAIMS
                if claim
                in " ".join(
                    _document_section(body, ADR_0015_SECTION_HEADING).replace("**", "").split()
                ).upper()
            ],
            "identity-gate activity occurred, so 'no AWS activity' is false as written",
        )
        f.check(
            f"{name} makes no stale zero-AWS claim in the ADR-0016 section",
            not [
                claim
                for claim in STALE_PREFLIGHT_CLAIMS
                if claim
                in " ".join(
                    _document_section(body, ADR_0016_SECTION_HEADING).replace("**", "").split()
                ).upper()
            ],
            "the same unscoped wording was copied into the correction's own section",
        )
        f.check(
            f"{name} states in the ADR-0015 row what the four attempts did and did not reach",
            bool(_current_status_rows(body, "ADR-0015"))
            and all(
                phrase in " ".join(row.replace("**", "").split()).upper()
                for row in _current_status_rows(body, "ADR-0015")
                for phrase in ADR_0015_ROW_HISTORY
            ),
            "a row claiming zero AWS activity survived four runs that produced some",
        )
        f.check(
            f"{name} makes no stale operational claim in the ADR-0015 row",
            not [
                claim
                for row in _current_status_rows(body, "ADR-0015")
                for claim in STALE_PREFLIGHT_CLAIMS
                if claim in " ".join(row.replace("**", "").split()).upper()
            ],
            "'credential source configured NONE' and 'AWS requests ZERO' are both stale",
        )
        f.check(
            f"{name} does not still call the identifier configuration unknown in a status row",
            not [
                claim
                for row in (
                    _current_status_rows(body, "ADR-0015")
                    + _phase_status_rows(body, BINDING_STATUS_ROW_SUBJECT)
                )
                for claim in STALE_IDENTIFIER_UNKNOWN_CLAIMS
                if claim in " ".join(row.replace("**", "").split()).upper()
            ],
            "the owner configured it after the third attempt; a row saying UNKNOWN is stale",
        )
        binding_section = _document_section(body, ADR_0015_SECTION_HEADING)
        binding_flat = " ".join(binding_section.replace("**", "").split())
        f.check(
            f"{name} does not call the identifier configuration unknown in the count block",
            STALE_SECTION_IDENTIFIER_LINE not in binding_section,
            "the fenced block is a current-status surface, not the historical narrative",
        )
        f.check(
            f"{name} still records that the identifier was unknown to the earlier attempts",
            all(
                phrase in binding_flat
                for phrase in ("UNKNOWN at the time of the second attempt", THIRD_ATTEMPT_ANCHOR)
            ),
            "a secret configured afterwards does not change what those runs saw",
        )
        f.check(
            f"{name} places the owner's credential setup after the third attempt",
            THIRD_ATTEMPT_ANCHOR in binding_flat
            and OWNER_SETUP_ANCHOR in binding_flat
            and binding_flat.index(THIRD_ATTEMPT_ANCHOR) < binding_flat.index(OWNER_SETUP_ANCHOR),
            "printed the other way round, the third attempt refused with a secret available",
        )
        f.check(
            f"{name} claims nothing about the owner's setup that no run established",
            not [claim for claim in OWNER_SETUP_FORBIDDEN_CLAIMS if claim in flat.upper()],
            "owner attestation is not resolution, construction, invocation or retrieval",
        )
        f.check(
            f"{name} keeps the fifth attempt, diagnosis, credential access and qualification gated",
            bool(_current_status_rows(body, "ADR-0015"))
            and all(
                phrase in " ".join(row.replace("**", "").split()).upper()
                for row in _current_status_rows(body, "ADR-0015")
                for phrase in ADR_0015_STILL_GATED
            ),
            "a configured secret is the thing most easily mistaken for permission",
        )
        f.check(
            f"{name} records the fourth attempt's REFUSED_IDENTITY outcome",
            "REFUSED_IDENTITY" in binding_section
            and bool(_current_status_rows(body, "ADR-0015"))
            and all(
                "REFUSED_IDENTITY" in " ".join(row.replace("**", "").split()).upper()
                for row in _current_status_rows(body, "ADR-0015")
            ),
            "the outcome is required in the section and in the row, independently",
        )
        f.check(
            f"{name} records the fourth attempt's scoped counts",
            all(token in binding_section for token in FOURTH_ATTEMPT_COUNTS),
            "an outcome word alone reads as a run that got as far as the third did",
        )
        f.check(
            f"{name} records the fourth attempt's operational history",
            all(phrase in binding_flat for phrase in FOURTH_ATTEMPT_HISTORY),
            "the stage it reached and the two it did not are the finding",
        )
        f.check(
            f"{name} keeps the four attempts and the owner's setup in order",
            all(event in binding_flat for event in CHRONOLOGY_ORDER)
            and [binding_flat.index(event) for event in CHRONOLOGY_ORDER]
            == sorted(binding_flat.index(event) for event in CHRONOLOGY_ORDER),
            "a chronology in the wrong order reads as a sequence somebody verified",
        )
        f.check(
            f"{name} places the owner's setup before the fourth attempt",
            OWNER_SETUP_ANCHOR in binding_flat
            and FOURTH_ATTEMPT_ANCHOR in binding_flat
            and binding_flat.index(OWNER_SETUP_ANCHOR) < binding_flat.index(FOURTH_ATTEMPT_ANCHOR),
            "the fourth ran after the secret existed and still never reached it",
        )
        f.check(
            f"{name} never places the owner's setup after the fourth attempt",
            not [claim for claim in REVERSED_CHRONOLOGY_CLAIMS if claim in flat.upper()],
            "a sentence can reverse the claim while leaving both anchors in place",
        )
        f.check(
            f"{name} leaves the fourth attempt's AWS network-request count UNKNOWN",
            all(phrase in binding_flat for phrase in FOURTH_ATTEMPT_NETWORK_UNKNOWN),
            "a gate can fail before anything leaves the machine, and the later diagnosis "
            "fixes no count",
        )
        f.check(
            f"{name} states no definite network-request count for the fourth attempt",
            not [claim for claim in FOURTH_ATTEMPT_NETWORK_CLAIMS if claim in flat.upper()],
            "neither zero nor one is established by an identity gate that did not pass",
        )
        f.check(
            f"{name} does not overstate the post-fourth diagnosis as an exact or "
            "contemporaneous cause",
            not [claim for claim in SSO_EXACT_STATE_OVERCLAIMS if claim in flat.upper()],
            "the later diagnosis is direct evidence; it fixes neither the exact state nor "
            "a request count",
        )
        f.check(
            f"{name} carries no stale three-attempt current status",
            not [claim for claim in STALE_ATTEMPT_COUNT_CLAIMS if claim in flat.upper()],
            "a fourth attempt happened; the counts and the next-attempt boundary both moved",
        )
        f.check(
            f"{name} keeps a sixth attempt and AWS authentication diagnosis unauthorized",
            all(boundary in binding_section for boundary in SIXTH_ATTEMPT_BOUNDARIES),
            "a refusal is a completed diagnostic result, not permission to repair and retry",
        )
        f.check(
            f"{name} records the fifth attempt's outcome and conservative counts",
            all(token in binding_section for token in FIFTH_ATTEMPT_FACTS),
            "a completed attempt absent from the count block reads as one that never ran",
        )
        f.check(
            f"{name} states the five-attempt chronology in order",
            all(step in binding_flat for step in FIFTH_ATTEMPT_CHRONOLOGY)
            and [binding_flat.index(step) for step in FIFTH_ATTEMPT_CHRONOLOGY]
            == sorted(binding_flat.index(step) for step in FIFTH_ATTEMPT_CHRONOLOGY),
            "an identity confirmation printed before the refresh that caused it is a "
            "different history",
        )
        f.check(
            f"{name} keeps the first four refusals as refusals",
            "The first four refusals remain refusals." in binding_flat
            and "the fifth attempt's completion converts none of them into a success"
            in binding_flat,
            "a later success does not rewrite what the earlier runs did",
        )
        f.check(
            f"{name} separates the retrieved credential from provider authentication",
            all(fact in binding_flat for fact in FIFTH_ATTEMPT_CREDENTIAL_SCOPE),
            "structurally accepted is what happened; authenticating against Sharadar is not",
        )
        f.check(
            f"{name} records the fifth attempt in the ADR-0015 current-status row",
            bool(_current_status_rows(body, "ADR-0015"))
            and all(
                fact in " ".join(row.replace("**", "").split()).upper()
                for row in _current_status_rows(body, "ADR-0015")
                for fact in FIFTH_ATTEMPT_ROW_FACTS
            ),
            "the row and the section are independent surfaces, and both are read alone",
        )
        f.check(
            f"{name} carries no stale or overstated fifth-attempt claim",
            not [claim for claim in STALE_FIFTH_ATTEMPT_CLAIMS if claim in flat.upper()],
            "a zero the attempt moved, and an access it never made, are the same defect",
        )
        f.check(
            f"{name} records the post-fourth AWS identity diagnosis and its counts",
            all(token in binding_section for token in POST_FOURTH_DIAGNOSIS_COUNTS),
            "a completed diagnosis absent from the block reads as one that never happened",
        )
        f.check(
            f"{name} records the diagnosis outcome REFUSED_SSO_SESSION_MISSING_OR_EXPIRED",
            "REFUSED_SSO_SESSION_MISSING_OR_EXPIRED" in binding_section
            and bool(_current_status_rows(body, "ADR-0015"))
            and all(
                "REFUSED_SSO_SESSION_MISSING_OR_EXPIRED"
                in " ".join(row.replace("**", "").split()).upper()
                for row in _current_status_rows(body, "ADR-0015")
            ),
            "the outcome is required in the section and in the row, independently",
        )
        f.check(
            f"{name} states the diagnosis narrative, not only its counts",
            all(phrase in binding_flat for phrase in POST_FOURTH_DIAGNOSIS_HISTORY),
            "what it established and what it left unknown are both the finding",
        )
        f.check(
            f"{name} keeps the two standalone diagnoses distinct",
            all(entry in binding_flat for entry in DISTINCT_DIAGNOSES),
            "merged, they read as one diagnosis whose session was then refreshed",
        )
        f.check(
            f"{name} places the post-fourth diagnosis after the fourth attempt",
            POST_FOURTH_DIAGNOSIS_ANCHOR in binding_flat
            and "fourth authorized attempt, after that setup" in binding_flat
            and binding_flat.index("fourth authorized attempt, after that setup")
            < binding_flat.index(POST_FOURTH_DIAGNOSIS_ANCHOR),
            "a diagnosis printed before the attempt describes the first one, not this one",
        )
        f.check(
            f"{name} records how the governed profile was pinned, and that it was not disclosed",
            all(fact in binding_flat for fact in PROFILE_PIN_FACTS),
            "a pin nobody recorded reads as an alternate profile nobody noticed",
        )
        f.check(
            f"{name} discloses no profile value in the ADR-0015 section",
            bool(_governed_profile_value(read(BINDING_PREFLIGHT)))
            and _governed_profile_value(read(BINDING_PREFLIGHT)) not in binding_section,
            "the governed profile name belongs in the pinned constant, not in a status narrative",
        )
        f.check(
            f"{name} carries no stale claim that no diagnosis occurred",
            not [claim for claim in STALE_NO_DIAGNOSIS_CLAIMS if claim in flat.upper()],
            "one has completed; the attempt-time statement stays and the blanket one cannot",
        )
        f.check(
            f"{name} scopes the attempt-time statement and leaves the STS call unknown",
            "No standalone diagnosis was performed as part of attempt 4" in flat
            and "So the fourth attempt's STS command invocation is UNKNOWN" in flat,
            "an extra command was absent, and whether the gate reached its own is unknown",
        )
        f.check(
            f"{name} distinguishes the gate's own STS operation from the standalone diagnosis",
            all(phrase in binding_flat for phrase in GATE_VERSUS_DIAGNOSIS),
            "one is the gate's, one is a separate command, and neither is the other",
        )
        f.check(
            f"{name} claims no absent STS identity call for attempt 4",
            not [claim for claim in STALE_GATE_PROBE_CLAIMS if claim in flat.upper()],
            "the governed verifier issues one by construction; the source refutes it",
        )
        f.check(
            f"{name} states no STS command count for either attempt",
            not [claim for claim in ATTEMPT_STS_COUNT_CLAIMS if claim in flat.upper()],
            "the gate refuses before its own STS call on two paths; ONE and ZERO are both numbers",
        )
        f.check(
            f"{name} infers no SSO conclusion from an identity refusal",
            not [claim for claim in ATTEMPT_SSO_INFERENCES if claim in flat.upper()],
            "a gate that did not pass says nothing about why, in either attempt",
        )
        f.check(
            f"{name} denies neither the one invocation nor the absent completion",
            not [claim for claim in ATTEMPT_INVOCATION_DENIALS if claim in flat.upper()],
            "never completed is true, never invoked is false, and one may not imply the other",
        )
        for label, phrase in FIRST_ATTEMPT_REQUIRED_FACTS:
            f.check(
                f"{name} {label}",
                phrase in flat,
                f"missing: {phrase}",
            )
        f.check(
            f"{name} neither merges the two operations nor totals them",
            not [claim for claim in GATE_DIAGNOSIS_CONFLATIONS if claim in flat.upper()],
            "two scopes, no shared count, and no number either establishes",
        )
        f.check(
            f"{name} makes no unqualified claim about the profile value never being written",
            not [claim for claim in STALE_PROFILE_DISCLOSURE_CLAIMS if claim in flat.upper()],
            "the governed constant predates the diagnosis in tracked source",
        )
        f.check(
            f"{name} claims nothing the diagnosis did not establish",
            not [claim for claim in DIAGNOSIS_OVERCLAIMS if claim in flat.upper()],
            "one closed word: not which of missing or expired, and not a repair",
        )
        f.check(
            f"{name} records the timed-out AWS SSO-login attempt and its counts",
            all(token in binding_section for token in SSO_LOGIN_ATTEMPT_COUNTS),
            "an authorized command that ran and failed is current status, not an omission",
        )
        f.check(
            f"{name} states the SSO-login attempt's chronology, not only its counts",
            all(phrase in binding_flat for phrase in SSO_LOGIN_ATTEMPT_HISTORY),
            "what it did, what it left unrevised and what it never reached are all the finding",
        )
        f.check(
            f"{name} records the SSO-login exit status as unavailable rather than numeric",
            "SSO-login exit code: NOT AVAILABLE / PROCESS TERMINATED ON TIMEOUT" in binding_section
            and "never as a numeric exit code" in binding_flat,
            "a terminated process returns no status; any number would be invented",
        )
        f.check(
            f"{name} leaves the SSO-login attempt's AWS network-request count UNKNOWN",
            "SSO-login underlying AWS network requests: UNKNOWN" in binding_section
            and "Its underlying AWS network-request count is UNKNOWN" in binding_flat,
            "a CLI invocation is not one network request, and it may fail before sending any",
        )
        f.check(
            f"{name} scopes the SSO-login failure as likely, not as a proven AWS defect",
            all(phrase in binding_flat for phrase in SSO_LOGIN_CAUSE_SCOPE),
            "operator handling explains it; nothing inspected an AWS configuration",
        )
        sso_narrative = _sso_login_narrative(binding_section)
        f.check(
            f"{name} bounds the SSO-login narrative so its guards stay scoped",
            bool(sso_narrative),
            "an unresolvable span would guard nothing while reporting a pass",
        )
        f.check(
            f"{name} records how the child environment was built, and what copying is not",
            all(fact in sso_narrative for fact in SSO_LOGIN_ENVIRONMENT_FACTS),
            "copying an environment materializes its values; not inspecting them is the claim",
        )
        f.check(
            f"{name} claims no absence the environment copy cannot support",
            not [
                claim
                for claim in SSO_LOGIN_ENVIRONMENT_OVERCLAIMS
                if claim in sso_narrative.upper()
            ],
            "not read, never materialized and not copied are each stronger than what happened",
        )
        f.check(
            f"{name} keeps every boundary a failed login does not move",
            all(phrase in binding_flat for phrase in SSO_LOGIN_FORWARD_BOUNDARIES),
            "a failed operation reads as an invitation to repeat it unless it is refused",
        )
        f.check(
            f"{name} places the SSO-login attempt after the post-fourth diagnosis",
            SSO_LOGIN_ATTEMPT_ANCHOR in binding_flat
            and POST_FOURTH_DIAGNOSIS_ANCHOR in binding_flat
            and binding_flat.index(POST_FOURTH_DIAGNOSIS_ANCHOR)
            < binding_flat.index(SSO_LOGIN_ATTEMPT_ANCHOR),
            "printed first it reads as the login that preceded the second attempt",
        )
        f.check(
            f"{name} records the SSO-login attempt in the ADR-0015 current-status row",
            bool(_current_status_rows(body, "ADR-0015"))
            and all(
                "REFUSED_SSO_LOGIN" in " ".join(row.replace("**", "").split()).upper()
                and "TIMED OUT AFTER 420 SECONDS" in " ".join(row.replace("**", "").split()).upper()
                for row in _current_status_rows(body, "ADR-0015")
            ),
            "the row and the section are independent surfaces, and both are read alone",
        )
        f.check(
            f"{name} carries no stale zero-SSO-login current status",
            not [claim for claim in STALE_SSO_LOGIN_CLAIMS if claim in flat.upper()],
            "one login was attempted; a document still reporting none is wrong, not cautious",
        )
        f.check(
            f"{name} claims nothing the timed-out SSO-login attempt did not establish",
            not [claim for claim in SSO_LOGIN_OVERCLAIMS if claim in flat.upper()],
            "the first attempt did not succeed, confirm an identity or prove a cause",
        )
        f.check(
            f"{name} records the corrected AWS SSO refresh and its counts",
            all(token in binding_section for token in CORRECTED_SSO_REFRESH_COUNTS),
            "a login that was authorized and worked is current status, not an omission",
        )
        f.check(
            f"{name} states the corrected refresh's chronology, not only its counts",
            all(phrase in binding_flat for phrase in CORRECTED_SSO_REFRESH_HISTORY),
            "what it did, and what changed because it worked, are both the finding",
        )
        f.check(
            f"{name} keeps the live-console handling apart from the captured one",
            all(phrase in binding_flat for phrase in SSO_OUTPUT_HANDLING_CONTRAST),
            "the observed contrast is required; the cause is not, because it is not known",
        )
        f.check(
            f"{name} claims no proven cause for the first attempt's timeout",
            not [claim for claim in SSO_CAUSE_OVERCLAIMS if claim in flat.upper()],
            "a sequence consistent with a cause is not that cause, sole or otherwise",
        )
        f.check(
            f"{name} records how the corrected child environment was built",
            all(phrase in binding_flat for phrase in CORRECTED_CHILD_ENVIRONMENT_FACTS),
            "minimal and allowlisted is a claim about this run, never about the first",
        )
        corrected_narrative = _corrected_sso_narrative(binding_section)
        f.check(
            f"{name} bounds the corrected-refresh narrative so its guards stay scoped",
            bool(corrected_narrative),
            "an unresolvable span would guard nothing while reporting a pass",
        )
        f.check(
            f"{name} states the corrected refresh's handling in its own narrative",
            all(fact in corrected_narrative for fact in CORRECTED_SSO_NARRATIVE_FACTS),
            "the event table states the same facts, and a row cannot answer for the prose",
        )
        f.check(
            f"{name} separates the observed contrast from an inferred cause",
            all(fact in corrected_narrative for fact in SSO_CAUSE_EVIDENCE_SCOPE),
            "what was observed, what was corrected on purpose, and what stays unknown",
        )
        f.check(
            f"{name} records the one sanitized identity confirmation and its limits",
            all(phrase in binding_flat for phrase in IDENTITY_CONFIRMATION_FACTS),
            "a session fact at one instant is not a verified secret and not a standing identity",
        )
        f.check(
            f"{name} keeps every boundary a successful refresh does not move",
            all(phrase in binding_flat for phrase in CORRECTED_SSO_FORWARD_BOUNDARIES),
            "a completed operation reads as a standing permission unless it is refused",
        )
        f.check(
            f"{name} places the corrected refresh after the timed-out attempt",
            CORRECTED_SSO_ANCHOR in binding_flat
            and SSO_LOGIN_ATTEMPT_ANCHOR in binding_flat
            and binding_flat.index(SSO_LOGIN_ATTEMPT_ANCHOR)
            < binding_flat.index(CORRECTED_SSO_ANCHOR),
            "printed first it reads as the login that preceded the timeout",
        )
        f.check(
            f"{name} places the identity confirmation after the corrected refresh",
            IDENTITY_CONFIRMATION_ANCHOR in binding_flat
            and CORRECTED_SSO_ANCHOR in binding_flat
            and binding_flat.index(CORRECTED_SSO_ANCHOR)
            < binding_flat.index(IDENTITY_CONFIRMATION_ANCHOR),
            "it ran because that login returned zero; before it, it is a different claim",
        )
        f.check(
            f"{name} records the corrected refresh in the ADR-0015 current-status row",
            bool(_current_status_rows(body, "ADR-0015"))
            and all(
                clause in " ".join(row.replace("**", "").split()).upper()
                for row in _current_status_rows(body, "ADR-0015")
                for clause in ADR_0015_ROW_CORRECTED
            ),
            "the row and the section are independent surfaces, and both are read alone",
        )
        f.check(
            f"{name} carries no stale zero-refresh or never-confirmed status",
            not [claim for claim in STALE_CORRECTED_SSO_CLAIMS if claim in flat.upper()],
            "one login worked and one identity was confirmed; reporting none is wrong",
        )
        f.check(
            f"{name} claims nothing the corrected refresh and the confirmation established",
            not [claim for claim in CORRECTED_SSO_OVERCLAIMS if claim in flat.upper()],
            "no standing session, no verified secret, no counted request and no new authority",
        )
        f.check(
            f"{name} records ADR-0015 as in force in a merge-stable sentence",
            ADR_0015_STATUS_SENTENCE in body,
            "a merged decision described as conditional reads as carrying no authority",
        )
        f.check(
            f"{name} no longer carries the superseded ADR-0015 status sentence",
            ADR_0015_STALE_SENTENCE not in flat,
            "the ADR file's own status line may say it; a current-status document may not",
        )
        f.check(
            f"{name} states in the ADR-0015 row what merging it did not authorize",
            bool(_current_status_rows(body, "ADR-0015"))
            and all(
                phrase.upper() in " ".join(row.replace("**", "").split()).upper()
                for row in _current_status_rows(body, "ADR-0015")
                for phrase in ADR_0015_ROW_BOUNDARY
            ),
            "in force is the status; dormant and unbound is the boundary, and both are the claim",
        )
        f.check(
            f"{name} claims nothing bound or run in the ADR-0015 row",
            not [
                overclaim
                for row in _current_status_rows(body, "ADR-0015")
                for overclaim in ADR_0015_ROW_OVERCLAIMS
                if overclaim in " ".join(row.replace("**", "").split()).upper()
            ],
            "implementing the path that will supply a binding is not performing one",
        )
        f.check(
            f"{name} states that this slice's three claims were narrowed, not removed",
            # ADR-0014's section already says "narrowed, not deleted" about the
            # architecture guards, so the bare phrase proves nothing here.
            "Three standing claims are narrowed, not deleted" in flat,
            "a guard removed to accommodate a slice is a guard that stopped guarding",
        )

    if ADR_BOUNDARIES.is_file():
        f.check(
            "ADR-0016 keeps its own immutable accepted-on-merge status line",
            ADR_0016_IMMUTABLE_STATUS in read(ADR_BOUNDARIES),
            "a status sync changes the documents, never the decision record",
        )

    claude_md = REPO_ROOT / "CLAUDE.md"
    if claude_md.is_file():
        claude_body = read(claude_md)
        f.check(
            "the CLAUDE.md in-force matrix records ADR-0016 exactly once",
            claude_body.count(ADR_0016_MATRIX_LINE) == 1
            and bool(_matrix_entry(claude_body, ADR_0016_MATRIX_LINE)),
            "a merged decision absent from the in-force list reads as one that did not merge",
        )
        f.check(
            "the CLAUDE.md matrix carries exactly one environment stanza",
            claude_body.count(ENVIRONMENT_MATRIX_LINE) == 1,
            "two stanzas for one machine is two places for it to go stale",
        )
        environment_stanza = _matrix_entry(
            claude_body, ENVIRONMENT_MATRIX_LINE, ENVIRONMENT_MATRIX_INDENT
        )
        f.check(
            "the environment stanza is extractable as a bounded entry",
            bool(environment_stanza),
            "an unbounded stanza cannot be told apart from the rest of the document",
        )
        f.check(
            "the environment stanza records the fingerprint and what stays gated",
            # Scoped to the stanza, not to `claude_body`. The first revision of
            # this guard searched the whole document, and several of these
            # clauses also appear in the narrative environment section -- so a
            # clause could vanish from the matrix while its duplicate elsewhere
            # kept the guard green. That is the failure the entry-scoped ADR-0015
            # and ADR-0016 guards were already written to avoid.
            bool(environment_stanza)
            and all(clause in environment_stanza for clause in ENVIRONMENT_MATRIX_CLAUSES),
            "the matrix states the boundary beside the state, or it states half a fact",
        )
        f.check(
            "the environment stanza records the corrected refresh and the confirmation",
            bool(environment_stanza)
            and all(clause in environment_stanza for clause in MATRIX_CORRECTED_SSO_CLAUSES),
            "the stanza is extracted and read alone; a narrative duplicate cannot answer it",
        )
        f.check(
            "the environment stanza carries no stale zero-refresh status",
            bool(environment_stanza)
            and not [
                claim for claim in STALE_CORRECTED_SSO_CLAIMS if claim in environment_stanza.upper()
            ],
            "the machine stanza said the session was unrefreshed, and it no longer is",
        )
        f.check(
            "the ADR-0016 matrix entry names its pull request and its boundary",
            all(
                clause in _matrix_entry(claude_body, ADR_0016_MATRIX_LINE)
                for clause in ADR_0016_MATRIX_CLAUSES
            ),
            "the matrix states the boundary beside the status, or it states half a fact",
        )
        f.check(
            "the CLAUDE.md in-force matrix records ADR-0015",
            ADR_0015_MATRIX_LINE in claude_body,
            "a merged decision absent from the in-force list reads as one that did not merge",
        )
        f.check(
            "the in-force matrix names the pull request that put ADR-0015 in force",
            "PR #22 MERGED, CODE ONLY, REFUSED BY DEFAULT, BINDING" in claude_body,
            "in force without a pull request is a status a reader cannot check",
        )
        f.check(
            "the in-force matrix records what ADR-0015's four attempts reached",
            all(
                clause in _matrix_entry(claude_body, ADR_0015_MATRIX_LINE)
                for clause in ADR_0015_MATRIX_CLAUSES
            ),
            "the matrix states the boundary beside the status, or it states half a fact",
        )
        f.check(
            "the in-force matrix records the corrected refresh and the confirmation",
            all(
                clause in _matrix_entry(claude_body, ADR_0015_MATRIX_LINE)
                for clause in MATRIX_CORRECTED_SSO_CLAUSES
            ),
            "narrative elsewhere cannot answer a guard over the entry a reader consults",
        )
        f.check(
            "the ADR-0015 matrix entry carries no stale zero-refresh status",
            not [
                claim
                for claim in STALE_CORRECTED_SSO_CLAIMS
                if claim in _matrix_entry(claude_body, ADR_0015_MATRIX_LINE).upper()
            ],
            "a compact entry may be short, and it may not be false",
        )
        f.check(
            "the ADR-0015 matrix entry cannot regress to never-run or zero AWS activity",
            not [
                claim
                for claim in STALE_PREFLIGHT_CLAIMS
                if claim in _matrix_entry(claude_body, ADR_0015_MATRIX_LINE).upper()
            ],
            "four authorized attempts happened; a compact entry may be short, not false",
        )
        f.check(
            "the unauthorized stanza forbids use rather than owner-side setup",
            all(
                clause
                in _matrix_entry(
                    claude_body, NOT_AUTHORIZED_STANZA_LINE, NOT_AUTHORIZED_STANZA_INDENT
                )
                for clause in NOT_AUTHORIZED_STANZA_CLAUSES
            ),
            "the boundary sits at use; a stanza forbidding setup contradicts ENVIRONMENT",
        )
        f.check(
            "the unauthorized stanza no longer forbids setup that has since happened",
            not [
                clause
                for clause in STALE_NOT_AUTHORIZED_CLAUSES
                if clause
                in _matrix_entry(
                    claude_body, NOT_AUTHORIZED_STANZA_LINE, NOT_AUTHORIZED_STANZA_INDENT
                )
            ],
            "a matrix that contradicts itself teaches a reader to trust neither half",
        )

    # -- 23. ADR-0016: the corrected private-binding failure boundaries -------
    #
    # ADR-0015 shipped one `REFUSED_CREDENTIAL` covering the identifier source,
    # the local SDK and client construction, and the one GetSecretValue call. An
    # operator ran it against the real foundation on a machine with no `boto3`,
    # and was told the private credential could not be retrieved -- for a missing
    # local package, with no request ever sent. These guards keep the three
    # boundaries distinct, keep their request counts honest, and refuse the
    # claims a future edit would be tempted to make about either.

    f.check(
        "the ADR-0016 decision record exists",
        ADR_BOUNDARIES.is_file(),
        f"missing: {ADR_BOUNDARIES}",
    )
    if ADR_BOUNDARIES.is_file():
        adr16 = read(ADR_BOUNDARIES)
        flat16 = " ".join(adr16.replace("**", "").split())
        f.check(
            "ADR-0016 records both real preflight refusals",
            "REFUSED_IDENTITY" in adr16
            and "refreshed the approved AWS SSO session" in flat16
            and "refused with `REFUSED_CREDENTIAL`" in flat16,
            "the decision rests on two runs, and a reader must be able to see both",
        )
        f.check(
            "ADR-0016 records the operational finding and the absent SDK",
            "neither `boto3` nor `botocore`" in adr16
            and "operational project virtual environment" in flat16,
            "the environment fact is evidence, and evidence that is not written down is lost",
        )
        f.check(
            "ADR-0016 states that no invocation and no AWS network request occurred",
            "no `get_secret_value` invocation could have occurred" in adr16
            and "invocations by this repository: zero" in flat16.lower(),
            "the false implication was that AWS had been contacted; the record must deny it",
        )
        f.check(
            "ADR-0016 keeps a method invocation apart from an AWS network request",
            ADR_0016_INVOCATION_SENTENCE in adr16,
            "a counter sees a method call; it does not see the wire",
        )
        f.check(
            "ADR-0016 reads no counter as proof that AWS was contacted",
            not [
                claim
                for claim in ADR_0016_INVOCATION_CONFLATIONS
                if claim in " ".join(adr16.replace("**", "").split()).upper()
            ],
            "a smaller version of the mistake this ADR was written to correct",
        )
        f.check(
            "ADR-0016 no longer lists the credential default as kept",
            ADR_0016_KEPT_DEFAULT_SENTENCE not in adr16,
            "round 1 removed the default; a section still calling it kept contradicts the code",
        )
        f.check(
            "ADR-0016 records the alternative as rejected and removed",
            "**Rejected, and removed**" in adr16 and "circular" in flat16,
            "an alternative silently reversed is an alternative nobody can review",
        )
        f.check(
            "ADR-0016 records the second correction round",
            "correction round 2" in flat16.lower()
            and "last credential-default path" in flat16.lower()
            and "length boundary" in flat16.lower(),
            "a correction to a correction is recorded, not silently substituted",
        )
        f.check(
            "ADR-0016 states only what a refusal can establish about AWS",
            "Not whether AWS received anything" in adr16,
            "a method counter cannot establish that AWS was contacted",
        )
        f.check(
            "ADR-0016 records the first correction round",
            "correction round 1" in flat16.lower()
            and "credential-default" in flat16.lower()
            and "identifier grammar" in flat16.lower(),
            "a correction to a correction is recorded, not silently substituted",
        )
        f.check(
            "ADR-0016 names the incorrect mapping it corrects",
            "inside the same broad exception boundary" in flat16
            and "reported as a private-credential failure" in flat16.lower(),
            "a correction that does not state the defect is a rewrite, not a correction",
        )
        f.check(
            "ADR-0016 records that the identifier stage was indistinguishable",
            "remains unknown" in flat16 and "not separately classified" in flat16,
            "the second run could not say whether the identifier was configured; nor may this",
        )
        f.check(
            "ADR-0016 states the three corrected boundaries",
            all(
                member in adr16
                for member in (
                    "REFUSED_SECRET_IDENTIFIER",
                    "REFUSED_DEPENDENCY",
                    "REFUSED_CREDENTIAL",
                )
            ),
            "three stages, three closed outcomes",
        )
        f.check(
            "ADR-0016 keeps environment synchronization a separate unauthorized action",
            "separate action and is not authorized by this ADR" in flat16
            and "No dependency is installed" in flat16,
            "installing the package would have hidden the defect it misreported",
        )
        f.check(
            "ADR-0016 keeps another binding-preflight attempt separately authorized",
            "Another binding-preflight attempt is separately authorized and has not been "
            "authorized" in flat16,
            "correcting what a refusal says is not permission to produce another one",
        )
        f.check(
            "ADR-0016 records nothing private",
            not any(
                marker in adr16
                for marker in ("arn:aws:", "amazonaws.com", "s3://", "AKIA", "test-api-key")
            )
            and re.search(r"\b\d{12}\b", adr16) is None,
            "no credential, account, ARN, secret identifier, bucket or exception text",
        )
        f.check(
            "ADR-0016 does not edit or retract ADR-0015",
            "ADR-0015 is not edited" in flat16 and "and nothing else" in flat16,
            "the immutable record stands; only the live semantics it produced are superseded",
        )
        f.check(
            "ADR-0016 changes no gate and no phase status",
            all(
                token in flat16
                for token in (
                    "G1 OPEN",
                    "G2 OPEN",
                    "G3 CLOSED",
                    f"G4{EN_DASH}G7 OPEN",
                    "Phase 3 NOT COMPLETE",
                    "live trading HARD-DISABLED",
                )
            ),
            "a correction to a refusal message resolves nothing",
        )

    # -- the corrected vocabulary, as code ------------------------------------
    if BINDING_PREFLIGHT.is_file():
        boundaries = _executable_python(BINDING_PREFLIGHT)
        f.check(
            "the entry point carries three distinct failure boundaries",
            all(
                member in boundaries
                for member in (
                    "REFUSED_SECRET_IDENTIFIER",
                    "REFUSED_DEPENDENCY",
                    "REFUSED_CREDENTIAL",
                )
            ),
            "one member for three stages is what misreported a missing package",
        )
        f.check(
            "the entry point makes no blanket claim about what a dependency refusal counts",
            not [
                claim
                for claim in ADR_0016_BLANKET_COUNT_CLAIMS
                if claim in " ".join(read(BINDING_PREFLIGHT).split()).upper()
            ]
            and "determines neither the" in read(BINDING_PREFLIGHT),
            "that outcome occurs both before a client exists and after a retrieval",
        )
        f.check(
            "the entry point has a word for a refusal it cannot classify",
            "REFUSED_UNCLASSIFIED" in boundaries,
            "not knowing which boundary was reached is not a credential fact",
        )
        f.check(
            "no credential default survives in the classifier",
            "REFUSED_CREDENTIAL" not in _function_body(BINDING_PREFLIGHT, "_secret_failure_outcome")
            and "SECRET_FAILURE_OUTCOME.get(token)"
            in _function_body(BINDING_PREFLIGHT, "_secret_failure_outcome"),
            "a .get default and a non-string branch both recreated the false claim",
        )
        f.check(
            "an unreadable or unmapped refusal is unclassified, not a credential",
            _function_body(BINDING_PREFLIGHT, "_secret_failure_outcome").count(
                "REFUSED_UNCLASSIFIED"
            )
            == 3,
            "hostile attribute access, a non-string token and an unmapped token",
        )
        f.check(
            "an unexpected exception from the retrieval is not a credential claim",
            "does not establish that `get_secret_value`" in read(BINDING_PREFLIGHT)
            and "REFUSED_CREDENTIAL"
            not in _function_body(BINDING_PREFLIGHT, "run_binding_preflight"),
            "an exception of an unknown type says nothing about what was invoked",
        )
        f.check(
            "the non-member outcome fallback claims nothing either",
            "else PreflightOutcome.REFUSED_UNCLASSIFIED" in boundaries,
            "it asserted a dependency failure on evidence that established none",
        )
        f.check(
            "the superseded plural member survives nowhere in the entry point",
            "REFUSED_DEPENDENCIES" not in read(BINDING_PREFLIGHT),
            "a rename, not a synonym: an alias would let one stage answer to two names",
        )
        f.check(
            "no refusal short of the invocation is worded as a credential failure",
            not any(
                "credential" in sentence
                for sentence in (
                    _outcome_sentence(BINDING_PREFLIGHT, "REFUSED_SECRET_IDENTIFIER"),
                    _outcome_sentence(BINDING_PREFLIGHT, "REFUSED_DEPENDENCY"),
                    _outcome_sentence(BINDING_PREFLIGHT, "REFUSED_UNCLASSIFIED"),
                )
            )
            and "credential" in _outcome_sentence(BINDING_PREFLIGHT, "REFUSED_CREDENTIAL"),
            "the sentence an operator reads must not name a boundary that was not reached",
        )
        f.check(
            "the identifier is validated before any client is constructed",
            _binding_stage_order(boundaries)
            == ["secret_id_source", "secrets_client_factory", "sharadar_credential_from_secret"],
            "resolve, then construct, then ask -- and refuse at whichever one fails",
        )
        f.check(
            "the identifier rule is the boundary's own, imported rather than restated",
            "is_usable_secret_identifier(secret_id)" in boundaries
            and "is_usable_secret_identifier" in _executable_python(SECRETS_BOUNDARY),
            "two spellings of one rule disagree about which outcome an operator sees",
        )
    if SECRETS_BOUNDARY.is_file():
        grammar = _executable_python(SECRETS_BOUNDARY)
        f.check(
            "the identifier rule is a Secrets Manager grammar, not a printability test",
            all(
                token in grammar
                for token in (
                    "_is_secret_name",
                    "_is_complete_secret_arn",
                    "_AWS_PARTITIONS",
                    "_AWS_REGION",
                    "_AWS_ACCOUNT",
                    "_ARN_GENERATED_SUFFIX",
                    "MAX_SECRET_ID_LENGTH",
                    "MAX_SECRET_NAME_LENGTH",
                )
            ),
            "a printable unspaced string reaches a client that rejects it locally",
        )
        f.check(
            "the ARN grammar pins every field it can",
            all(
                token in grammar
                for token in (
                    # Exact equality, not mere presence: a guard satisfied by the
                    # *name* appearing anywhere would pass a grammar that had been
                    # widened to `service in {'secretsmanager', 'ssm'}`.
                    "service == 'secretsmanager'",
                    "resource_type == 'secret'",
                    "len(fields) != 7",
                )
            ),
            "service, resource type and field count, or it is not a complete ARN",
        )
        f.check(
            "the identifier grammar transforms nothing",
            not any(
                transform in _function_body(SECRETS_BOUNDARY, "is_usable_secret_identifier")
                for transform in (".strip()", ".lower()", ".upper()", ".replace(")
            ),
            "a verdict about a normalised string is a verdict about a different string",
        )
        f.check(
            "the error constructor cannot normalise into a credential-mapped member",
            not any(
                token in _method_body(SECRETS_BOUNDARY, "SecretRetrievalError", "__init__")
                for token in CREDENTIAL_MAPPED_FAILURES
            )
            and "SecretRetrievalFailure.UNCLASSIFIED"
            in _method_body(SECRETS_BOUNDARY, "SecretRetrievalError", "__init__"),
            "normalising a non-member to RESPONSE_MALFORMED manufactured a credential claim",
        )
        f.check(
            "the unclassified boundary member exists and is mapped away from the credential",
            "UNCLASSIFIED = 'UNCLASSIFIED'" in grammar
            and "'UNCLASSIFIED': PreflightOutcome.REFUSED_UNCLASSIFIED"
            in _executable_python(BINDING_PREFLIGHT),
            "the constructor needs somewhere to put a value it cannot recognise",
        )
        f.check(
            "the ARN resource is split before the name ceiling is applied",
            "_split_arn_resource" in grammar
            and "_is_secret_name(secret_name)" in grammar
            and "_is_secret_name(resource)" not in grammar
            and "_is_secret_name(name)" not in grammar,
            "the 512 ceiling is the name's; AWS appends seven characters after it",
        )
        f.check(
            "the suffix is measured on its own, not on the whole resource",
            "_ARN_GENERATED_SUFFIX.fullmatch(suffix)" in grammar and "ARN_SUFFIX_LENGTH" in grammar,
            "a 512-character secret has a 519-character ARN resource, and it is legitimate",
        )
        f.check(
            "the boundary claims structure rather than provenance for the suffix",
            "Syntax is not provenance" in read(SECRETS_BOUNDARY),
            "a name ending that way is lexically identical to a generated suffix",
        )
        f.check(
            "the boundary compiles no account, ARN or identifier value",
            not any(marker in read(SECRETS_BOUNDARY) for marker in ("arn:aws:", "amazonaws.com"))
            and re.search(r"\b\d{12}\b", read(SECRETS_BOUNDARY)) is None,
            "a grammar needs a shape, never an instance",
        )
        f.check(
            "the secrets-boundary failures are classified by a total closed mapping",
            "SECRET_FAILURE_OUTCOME" in boundaries
            and all(
                token in boundaries
                for token in (
                    "'CLIENT_UNUSABLE': PreflightOutcome.REFUSED_DEPENDENCY",
                    "'SECRET_IDENTIFIER_MALFORMED': PreflightOutcome.REFUSED_SECRET_IDENTIFIER",
                    "'BACKEND_REFUSED': PreflightOutcome.REFUSED_CREDENTIAL",
                    "'RESPONSE_MALFORMED': PreflightOutcome.REFUSED_CREDENTIAL",
                    "'SECRET_BINARY_REFUSED': PreflightOutcome.REFUSED_CREDENTIAL",
                    "'SECRET_VALUE_UNUSABLE': PreflightOutcome.REFUSED_CREDENTIAL",
                )
            ),
            "the two refusals the boundary reaches before the request are not credential facts",
        )
        f.check(
            "the constructed client is checked for the one operation it must serve",
            "callable(getattr(secrets_client, 'get_secret_value', None))" in boundaries,
            "an object that cannot send a request is a dependency fact, not a credential one",
        )
        f.check(
            "no kalpamani import runs at entry-point import time",
            "kalpamani" not in _module_level_imports(BINDING_PREFLIGHT),
            "the refusing default path must stay clean on the machine the defect was found on",
        )

    # -- the behavioural evidence ---------------------------------------------
    if BINDING_TESTS.is_file():
        boundary_tests = read(BINDING_TESTS)
        for label, needle in (
            (
                "an identifier failure sending nothing",
                "test_an_identifier_failure_is_its_own_outcome_and_sends_nothing",
            ),
            (
                "an identifier failure disclosing nothing",
                "test_an_identifier_failure_discloses_neither_value_nor_cause",
            ),
            (
                "a usable identifier shape",
                "test_a_usable_identifier_shape_reaches_the_backend_exactly_once",
            ),
            (
                "a missing SDK as a dependency refusal",
                "test_a_client_construction_failure_is_a_dependency_refusal",
            ),
            (
                "a dependency failure disclosing no underlying text",
                "test_a_dependency_failure_discloses_no_underlying_text",
            ),
            (
                "a client that cannot serve the operation",
                "test_a_constructed_client_that_cannot_serve_the_operation_is_a_dependency_refusal",
            ),
            (
                "an unimportable secrets boundary",
                "test_an_unimportable_secrets_boundary_is_a_dependency_refusal",
            ),
            (
                "a dependency failure after the credential",
                "test_a_late_dependency_failure_is_still_a_dependency_refusal",
            ),
            (
                "a backend refusal after exactly one attempt",
                "test_a_backend_refusal_is_a_credential_refusal_after_exactly_one_attempt",
            ),
            (
                "an unusable response after exactly one attempt",
                "test_an_unusable_response_is_a_credential_refusal_after_exactly_one_attempt",
            ),
            (
                "a valid synthetic secret",
                "test_a_valid_synthetic_secret_completes_with_one_attempt",
            ),
            ("a total classification", "test_every_secrets_boundary_failure_is_classified"),
            (
                "pre-invocation failures never credential",
                "test_the_pre_invocation_failures_are_never_credential_failures",
            ),
            (
                "post-invocation failures always credential",
                "test_the_post_invocation_failures_are_credential_failures",
            ),
            ("a closed outcome vocabulary", "test_the_outcome_vocabulary_is_exactly_these_members"),
            ("no surviving plural member", "test_the_superseded_plural_member_is_gone"),
            (
                "no pre-invocation refusal worded as a credential failure",
                "test_no_refusal_before_the_invocation_is_worded_as_a_credential_failure",
            ),
            (
                "a non-member failure normalising to unclassified",
                "test_a_non_member_failure_normalises_to_unclassified",
            ),
            (
                "a non-member failure never becoming a credential refusal",
                "test_a_non_member_failure_can_never_become_a_credential_refusal",
            ),
            (
                "a non-member construction with no invented count",
                "test_a_non_member_construction_surfaces_as_unclassified_with_no_invented_count",
            ),
            (
                "a constructor naming no credential-mapped member",
                "test_the_constructor_never_names_a_credential_mapped_member",
            ),
            ("the ARN resource length boundary", "test_the_arn_resource_length_boundary"),
            (
                "a maximum-length ARN admitted with the name ceiling still binding",
                "test_the_maximum_length_arn_is_admitted_and_the_name_ceiling_still_binds",
            ),
            (
                "the SecretId ceiling still binding above the name ceiling",
                "test_the_secret_id_ceiling_still_binds_above_the_name_ceiling",
            ),
            (
                "a suffix check claiming structure and not provenance",
                "test_the_suffix_check_claims_structure_and_not_provenance",
            ),
            ("witnessed call counts", "test_every_outcome_has_its_witnessed_call_counts"),
            (
                "a refusing path needing neither SDK nor package",
                "test_the_refusing_default_path_needs_neither_the_sdk_nor_the_package",
            ),
            (
                "every well-formed identifier admitted",
                "test_the_grammar_admits_every_well_formed_identifier",
            ),
            (
                "every malformed identifier refused",
                "test_the_grammar_refuses_every_malformed_identifier",
            ),
            (
                "a malformed identifier never reaching a client",
                "test_a_malformed_identifier_never_reaches_a_client",
            ),
            ("a grammar that transforms nothing", "test_the_grammar_transforms_nothing"),
            (
                "an unclassifiable refusal claiming no credential",
                "test_an_unclassifiable_refusal_never_claims_a_credential",
            ),
            (
                "an unclassifiable refusal disclosing nothing",
                "test_an_unclassifiable_refusal_surfaces_without_disclosure",
            ),
            (
                "an unexpected boundary exception as a dependency refusal",
                "test_an_unexpected_exception_from_the_boundary_is_a_dependency_refusal",
            ),
            (
                "no credential default in the classifier",
                "test_the_classifier_has_no_credential_default",
            ),
            (
                "credential reachable only from the four mapped members",
                "test_credential_is_reachable_only_from_the_four_mapped_members",
            ),
            (
                "a non-member outcome claiming no dependency",
                "test_a_non_member_outcome_is_unclassified_rather_than_a_dependency_claim",
            ),
        ):
            f.check(
                f"a failure-boundary test covers {label}",
                needle in boundary_tests,
                "ADR-0016's verification table must name tests that exist",
            )
        f.check(
            "the invocation counts are read from counters rather than asserted",
            "self.secrets_factory_calls += 1" in boundary_tests
            and "self.calls += 1" in boundary_tests
            and "_counts(harness)" in boundary_tests,
            "a count argued from which line raised is the inference that misreported",
        )
        f.check(
            "the synthetic account component is built rather than committed",
            'SYNTHETIC_ACCOUNT: Final = "9" * 12' in boundary_tests
            and re.search(r"\b\d{12}\b", boundary_tests) is None,
            "a grammar test needs twelve digits; a repository does not need the literal",
        )

    # -- the current documentation --------------------------------------------
    for name, path in (
        ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
        ("README.md", REPO_ROOT / "README.md"),
    ):
        if not path.is_file():
            continue
        body = read(path)
        flat = " ".join(body.replace("**", "").split())
        upper = flat.upper()
        f.check(
            f"{name} records the corrected failure boundaries",
            "ADR-0016" in body and "The private-binding failure boundaries — corrected" in body,
            "a superseded live semantic left undescribed is a live semantic a reader will trust",
        )
        f.check(
            f"{name} distinguishes all three refusals by name",
            all(
                member in body
                for member in (
                    "`REFUSED_SECRET_IDENTIFIER`",
                    "`REFUSED_DEPENDENCY`",
                    "`REFUSED_CREDENTIAL`",
                )
            ),
            "three stages, three closed outcomes, and a reader must see which is which",
        )
        f.check(
            f"{name} states the witnessed invocation-count rules",
            all(row in body for row in ADR_0016_COUNT_ROWS),
            "the counts are the correction; a document without them describes the old behaviour",
        )
        f.check(
            f"{name} states the one invocation and the one retrieval, and their limits",
            # The zeros this guard once required were true of the first four
            # attempts and false after the fifth. What replaces them keeps the
            # correction's point: a method invocation is still not a proven
            # network request, so the network count is UNKNOWN and not one.
            "get_secret_value invocations by this repository: ONE -- admitted, on the fifth attempt"
            in body
            and "Secrets Manager client constructions: ONE -- on the fifth attempt" in body
            and "Secrets Manager underlying network requests: UNKNOWN" in body
            and "AWS identity-gate activity: OCCURRED" in body
            and "real credential retrieval: ONE -- STRUCTURALLY ACCEPTED" in body
            and "Sharadar authentication by that credential: UNKNOWN -- NO PROVIDER "
            "REQUEST WAS MADE"
            in body,
            "one invocation is not a proven request, and a structurally accepted secret "
            "is not a provider-authenticated credential",
        )
        f.check(
            f"{name} keeps a method invocation apart from an AWS network request",
            ADR_0016_INVOCATION_SENTENCE in body,
            "a counter sees a method call; it does not see the wire",
        )
        f.check(
            f"{name} reads no counter as proof that AWS was contacted",
            not [claim for claim in ADR_0016_INVOCATION_CONFLATIONS if claim in upper],
            "a smaller version of the mistake this correction exists to remove",
        )
        f.check(
            f"{name} records the tightened identifier grammar",
            "a well-formed secret name or a complete secret ARN" in flat,
            "the earlier rule admitted shapes a client rejects locally, after the call began",
        )
        f.check(
            f"{name} carries exactly one binding status row",
            len(_phase_status_rows(body, BINDING_STATUS_ROW_SUBJECT)) == 1,
            "two rows for one subject is two places for it to go stale",
        )
        f.check(
            f"{name} separates the binding boundary's existence from its execution",
            bool(_phase_status_rows(body, BINDING_STATUS_ROW_SUBJECT))
            and all(
                fact in " ".join(row.replace("**", "").split()).upper()
                for row in _phase_status_rows(body, BINDING_STATUS_ROW_SUBJECT)
                for fact in BINDING_ROW_FACTS
            ),
            "a credential-source boundary exists and has been invoked; the row must say both",
        )
        f.check(
            f"{name} claims no absent credential source, bucket resolution or SDK path",
            not [
                claim
                for row in _phase_status_rows(body, BINDING_STATUS_ROW_SUBJECT)
                for claim in STALE_BINDING_ABSENCE_CLAIMS
                if claim in " ".join(row.replace("**", "").split()).upper()
            ],
            "'none exists' denied an architecture that ADR-0015 built and ran three times",
        )
        f.check(
            f"{name} carries exactly one ADR-0016 current-status row",
            len(_current_status_rows(body, "ADR-0016")) == 1,
            "two rows for one decision is two places for it to go stale",
        )
        f.check(
            f"{name} states ADR-0016 as in force, naming the pull request",
            all(
                "ACCEPTED / IN FORCE" in " ".join(row.replace("**", "").split()).upper()
                and "PR #24 MERGED" in " ".join(row.replace("**", "").split()).upper()
                for row in _current_status_rows(body, "ADR-0016")
            )
            and bool(_current_status_rows(body, "ADR-0016")),
            "in force without a pull request is a status a reader cannot check",
        )
        f.check(
            f"{name} carries no pre-merge wording in the ADR-0016 row",
            not [
                wording
                for row in _current_status_rows(body, "ADR-0016")
                for wording in (*PRE_MERGE_STATUS_WORDING, "PROPOSED")
                if wording.upper() in " ".join(row.replace("**", "").split()).upper()
            ],
            "a merged decision described as conditional reads as carrying no authority",
        )
        f.check(
            f"{name} states in the ADR-0016 row what merging it did not authorize",
            bool(_current_status_rows(body, "ADR-0016"))
            and all(
                phrase in " ".join(row.replace("**", "").split()).upper()
                for row in _current_status_rows(body, "ADR-0016")
                for phrase in ADR_0016_ROW_BOUNDARY
            ),
            "in force is the status; the boundaries and what stays unauthorized are the claim",
        )
        f.check(
            f"{name} records ADR-0016 as in force in a merge-stable sentence",
            ADR_0016_STATUS_SENTENCE in body,
            "prose is not a table row, and no row guard reaches it",
        )
        f.check(
            f"{name} no longer carries the superseded ADR-0016 status sentence",
            ADR_0016_STALE_SENTENCE not in flat,
            "the ADR's own status line may say it; a current-status document may not",
        )
        f.check(
            f"{name} makes no blanket claim about what a dependency refusal counts",
            not [claim for claim in ADR_0016_BLANKET_COUNT_CLAIMS if claim in upper],
            "that outcome occurs both before a client exists and after a retrieval",
        )
        f.check(
            f"{name} records that an unclassifiable refusal claims nothing",
            "`REFUSED_UNCLASSIFIED`" in body,
            "the two places that needed a word for 'I do not know' were asserting a boundary",
        )
        f.check(
            f"{name} records the environment as synchronized and verified, and still gated",
            # Scoped to the ADR-0016 section, not to `body`. The document-wide
            # form could not tell which fenced block still carried the clause:
            # the same sentence appears in the environment and ADR-0015 blocks,
            # so authorizing a fifth attempt *here* left the guard green. A
            # negative control found it.
            all(
                clause in _document_section(body, ADR_0016_SECTION_HEADING)
                for clause in (
                    "operational environment synchronized: DONE AND VERIFIED",
                    "Python dependency lock: ABSENT",
                    "a sixth binding-preflight attempt: NOT AUTHORIZED",
                )
            ),
            "the drift was real evidence; a separately authorized action has since fixed it",
        )
        f.check(
            f"{name} carries the operational-environment section",
            ENVIRONMENT_SECTION_HEADING in body,
            "a machine state nobody wrote down is a machine state nobody can check",
        )
        f.check(
            f"{name} records the exact environment fingerprint",
            all(
                token in _document_section(body, ENVIRONMENT_SECTION_HEADING)
                for token in ENVIRONMENT_FINGERPRINT
            ),
            "'the SDK is present' cannot be checked against the machine it describes",
        )
        f.check(
            f"{name} keeps the four environment events distinct",
            all(
                phrase
                in " ".join(
                    _document_section(body, ENVIRONMENT_SECTION_HEADING).replace("**", "").split()
                )
                for phrase in ENVIRONMENT_CHRONOLOGY
            ),
            "a review that installed nothing must not read as the action that installed",
        )
        f.check(
            f"{name} states the dependency-lock limitation and defers the lock",
            all(
                phrase
                in " ".join(
                    _document_section(body, ENVIRONMENT_SECTION_HEADING).replace("**", "").split()
                )
                for phrase in ENVIRONMENT_LOCK_LIMITATION
            ),
            "recording a missing lock does not supply one",
        )
        f.check(
            f"{name} restates every operational boundary in the environment section",
            all(
                token in _document_section(body, ENVIRONMENT_SECTION_HEADING)
                for token in ENVIRONMENT_BOUNDARIES
            ),
            "a usable environment is not a permission, and the zeros are unchanged",
        )
        f.check(
            f"{name} separates a confirmed identity from a guaranteed session",
            "identity status: CONFIRMED AT THE TIME OF THAT COMMAND -- "
            "future session validity NOT GUARANTEED"
            in _document_section(body, ENVIRONMENT_SECTION_HEADING)
            and "no current or future session validity is guaranteed" in flat,
            "a session can expire between one command and the next, and the block is read alone",
        )
        f.check(
            f"{name} separates what the machine did from what is authorized next",
            "A usable environment is not a permission." in flat
            and "That is a statement about what happened on this machine, not a permission "
            "for the next thing."
            in flat,
            "the one attempt this environment was ready for has been run; readiness is "
            "still a fact about a machine, never about a decision",
        )
        f.check(
            f"{name} makes no stale environment-absence claim",
            not [claim for claim in STALE_ENVIRONMENT_CLAIMS if claim in upper],
            "two separately authorized events made each of these false",
        )
        f.check(
            f"{name} reads a usable environment as granting nothing",
            not [claim for claim in ENVIRONMENT_FORBIDDEN_CLAIMS if claim in upper],
            "each names a decision, and none of those decisions has been taken",
        )
        f.check(
            f"{name} does not describe a missing SDK as a credential failure",
            "never implies credential retrieval" in flat
            and "only the witnessed stage-specific count says which" in flat,
            "the dependency outcome must say what it does not mean, or it means the old thing",
        )
        f.check(
            f"{name} does not describe an identifier failure as credential retrieval",
            "No client is built, so nothing is invoked and nothing can reach AWS." in flat,
            "the identifier outcome is refused before anything is constructed or sent",
        )
        f.check(
            f"{name} claims no repair, no completion and no qualification authority",
            not [claim for claim in ADR_0016_FORBIDDEN_CLAIMS if claim in upper],
            "each is an affirmative claim about something that has not happened",
        )

    f.check(
        "the retired-prohibition count this audit states about itself is derived, not written",
        (
            f"{COUNT_WORDS[len(RETIRED_ENVIRONMENT_PROHIBITIONS)]} environment-repair entries "
            "stood here and are gone" in read(Path(__file__).resolve())
        )
        and not [p for p in RETIRED_ENVIRONMENT_PROHIBITIONS if p in ADR_0016_FORBIDDEN_CLAIMS]
        and all(p in ADR_0016_FORBIDDEN_CLAIMS for p in SURVIVING_PROHIBITIONS),
        "the comment said five and listed six; the word now comes from the tuple's length",
    )
    f.check(
        "the retired preflight-prohibition count is derived, and its survivors are kept",
        # The same membership protection the environment retirements carry. A
        # denylist may only be weakened beside a tuple naming what left it and a
        # tuple naming what must stay, both checked here -- otherwise "the fifth
        # attempt made it true" becomes a way to delete any guard at all.
        (
            f"{COUNT_WORDS[len(RETIRED_PREFLIGHT_PROHIBITIONS)]} preflight entries "
            "stood here and are gone" in read(Path(__file__).resolve())
        )
        and not [p for p in RETIRED_PREFLIGHT_PROHIBITIONS if p in ADR_0016_FORBIDDEN_CLAIMS]
        and all(p in ADR_0016_FORBIDDEN_CLAIMS for p in SURVIVING_PROHIBITIONS),
        "a prohibition the fifth attempt made true is retired by name, never quietly dropped",
    )
    f.check(
        "each denylist this slice touches states its own size, derived from its tuple",
        # The membership protection the retirement rule needs on its other side.
        # Retiring an entry by name is guarded above; *deleting* one from the
        # tuple and from its membership list together leaves no document-side
        # symptom, because a denylist with one fewer entry still passes. Both
        # sentences are written in the source and both numbers come from
        # `len()`, so the two have to be changed deliberately and together.
        (
            f"{len(STALE_FIFTH_ATTEMPT_CLAIMS)} stale-or-overstated fifth-attempt claims "
            "are listed here" in read(Path(__file__).resolve())
        )
        and (
            f"{len(SURVIVING_PROHIBITIONS)} prohibitions survive here"
            in read(Path(__file__).resolve())
        ),
        "a denylist that quietly loses an entry checks less and reports the same",
    )

    # ------------------- 21. ADR-0017 proposes an architecture, and builds nothing
    print("\n[21/21] ADR-0017 is proposed, and nothing is implemented or executed")

    f.check(
        "ADR-0017 exists as a tracked decision record",
        ADR_0017.exists(),
        "both status documents cite a decision record that must be readable",
    )
    adr_0017_text = read(ADR_0017) if ADR_0017.exists() else ""
    adr_0017_flat = " ".join(adr_0017_text.replace("**", "").split()).lower()
    for name, phrase in ADR_0017_SELF_REQUIRED:
        f.check(name, phrase in adr_0017_flat, f"missing: {phrase}")

    f.check(
        "ADR-0017 is governed by the merged-ADR registry",
        # Inverted, not deleted. Until PR #33 merged this check required the
        # opposite, and deleting it then would have left the reverted claim
        # unguarded. The registry governs rows claiming a merge; an in-force row
        # outside it is a row nothing governs.
        dict(MERGED_ADR_STATUS).get("ADR-0017") == f"PR {ADR_0017_PR} merged",
        f"ADR-0017 must be registered as 'PR {ADR_0017_PR} merged'",
    )
    f.check(
        "both status documents make ADR-0017's in-force claim against the right pull request",
        [
            _in_force_adr_claims(read(path)).get("ADR-0017")
            for path in (REPO_ROOT / "CLAUDE.md", REPO_ROOT / "README.md")
        ]
        == [f"PR {ADR_0017_PR} merged"] * 2,
        "an accepted ADR must claim its merge, in both documents, naming the same pull request",
    )

    for name, path in (
        ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
        ("README.md", REPO_ROOT / "README.md"),
    ):
        body = read(path)
        flat = " ".join(body.replace("**", "").split()).lower()

        for label, phrase in ADR_0017_REQUIRED_PROSE:
            f.check(f"{name} {label}", phrase in flat, f"missing: {phrase}")

        present = [claim for claim in ADR_0017_FORBIDDEN if claim in flat]
        f.check(
            f"{name} claims no implementation, execution or resolution for ADR-0017",
            not present,
            # Each is an affirmative statement about something that has not
            # happened. A proposal that reads like a built and exercised surface
            # is exactly the drift these documents exist to prevent.
            ", ".join(present),
        )

        # Scoped checks. The document-wide pass above catches a fact that has
        # left the file entirely; these catch the commoner failure, where a fact
        # survives in one place and goes stale in the other. Negative controls
        # proved a whole-file scan passes while the row is deleted and while the
        # narrative names the wrong script as the runner.
        row = _adr_0017_row(body)
        section = _adr_0017_section(body)
        section_flat = " ".join(section.replace("**", "").split()).lower()
        section_raw = section.lower()

        f.check(
            f"{name} carries an ADR-0017 status row",
            bool(row),
            "the narrative may not answer for a row a reader looks up in the table",
        )
        f.check(
            f"{name} carries the ADR-0017 narrative section",
            bool(section),
            "the row may not answer for the section either",
        )
        for label, phrase in ADR_0017_ROW_REQUIRED:
            f.check(
                f"{name} ADR-0017 row {label}",
                phrase in row,
                f"missing from the row: {phrase}",
            )
        for label, phrase in ADR_0017_SECTION_REQUIRED:
            f.check(
                f"{name} ADR-0017 section {label}",
                phrase in section_flat,
                f"missing from the section: {phrase}",
            )
        for label, phrase in ADR_0017_REQUIRED_COUNTS:
            f.check(
                f"{name} ADR-0017 section {label}",
                phrase in section_raw,
                f"missing count line: {phrase}",
            )

        # Ordering, not presence. A document can carry all seven sentences and
        # still tell a reader the ADR was accepted before the pull request
        # merged; that ordering is the one claim this slice must never make, so
        # the positions are what is checked.
        positions = [section_flat.find(step) for step in ADR_0017_CHRONOLOGY]
        f.check(
            f"{name} carries all seventeen ADR-0017 chronology steps",
            all(pos >= 0 for pos in positions),
            ", ".join(
                step for step, pos in zip(ADR_0017_CHRONOLOGY, positions, strict=True) if pos < 0
            ),
        )
        f.check(
            f"{name} keeps the ADR-0017 chronology in order",
            all(pos >= 0 for pos in positions) and positions == sorted(positions),
            "acceptance may not be narrated before the merge that caused it",
        )

    matrix = _governance_matrix(read(REPO_ROOT / "CLAUDE.md")).lower()
    f.check(
        "CLAUDE.md carries the fenced governance matrix",
        bool(matrix),
        "neither the row nor the narrative may answer for the matrix",
    )
    for label, phrase in ADR_0017_MATRIX_IN_FORCE:
        f.check(
            f"the governance matrix {label}",
            phrase in matrix,
            f"missing from the matrix: {phrase}",
        )
    for label, phrase in ADR_0017_MATRIX_NOT_AUTHORIZED:
        f.check(
            f"the governance matrix {label}",
            phrase in matrix,
            f"missing from the matrix: {phrase}",
        )

    # Argument *lines* rather than a substring scan. The ADR names the refused
    # spellings in prose, inside backticks and mid-sentence, so a scan over the
    # whole text cannot tell an approved argument from a refused one. A line that
    # begins with `--` is the argument list and nothing else.
    adr_0017_arg_lines = tuple(
        line.strip()
        for line in adr_0017_text.splitlines()
        # A Markdown horizontal rule also begins with two dashes, and this file is
        # full of them. An argument carries a letter; a rule never does.
        if line.strip().startswith("--") and line.strip().strip("-") != ""
    )
    f.check(
        "ADR-0017 presents exactly the three approved CLI arguments, in order",
        len(ADR_0017_CLI) == 3 and adr_0017_arg_lines == ADR_0017_CLI,
        f"argument lines found: {adr_0017_arg_lines}",
    )
    f.check(
        "no forbidden CLI spelling is presented as an approved argument",
        not [s for s in ADR_0017_FORBIDDEN_CLI if s in adr_0017_arg_lines],
        "an approved-looking argument line is how a locked surface acquires a switch",
    )
    f.check(
        "ADR-0017 refuses the forbidden CLI concepts by name",
        "forbidden cli concepts" in adr_0017_flat,
        "refusing by name is what makes a wrong reflex fail loudly rather than silently",
    )
    f.check(
        "each ADR-0017 denylist states its own size, derived from its tuple",
        # The membership protection the other slices carry. Deleting an entry
        # from a denylist leaves no document-side symptom -- a shorter list still
        # passes -- so both sentences are written in the source and both numbers
        # come from `len()`, and the two have to be changed deliberately together.
        (
            f"{len(ADR_0017_FORBIDDEN)} claims about an implemented, twice-attempted "
            "surface are listed here" in read(Path(__file__).resolve())
        )
        and (
            f"{len(ADR_0017_FORBIDDEN_CLI)} forbidden CLI spellings are listed here"
            in read(Path(__file__).resolve())
        ),
        "a denylist that quietly loses an entry checks less and reports the same",
    )
    f.check(
        "the protected ADR-0017 claims are still on the denylist",
        # The other half of the membership protection. The size sentence above
        # catches an entry vanishing alone; this catches one deleted together
        # with the number, which is the shape a weakening actually takes.
        len(ADR_0017_SURVIVING_CLAIMS) == 19
        and all(claim in ADR_0017_FORBIDDEN for claim in ADR_0017_SURVIVING_CLAIMS)
        and f"{len(ADR_0017_SURVIVING_CLAIMS)} claims are protected by membership here"
        in read(Path(__file__).resolve()),
        "updating the count beside a deletion is what a weakening looks like",
    )

    # -- the ADR-0017 implementation, structurally ----------------------------
    #
    # Source and AST checks only. Executable invariants -- gate ordering, exact
    # operation counts, the window arithmetic, the exit-code mapping -- belong in
    # the two dedicated unit suites, and a text search must not pretend to prove
    # them. What is checked here is what a text search *can* establish: that the
    # named files exist, that the surface has not widened, and that the
    # separations the ADR rests on are still visible in the source.
    f.check(
        "the ADR-0017 entry point exists at its exact path",
        ADR_0017_ENTRY_POINT.is_file(),
        "the status documents name a script that must be readable",
    )
    if ADR_0017_ENTRY_POINT.is_file():
        entry = read(ADR_0017_ENTRY_POINT)
        entry_exec = _executable_python(ADR_0017_ENTRY_POINT)

        f.check(
            "the entry point declares the exact authorization flag",
            f'AUTHORIZATION_FLAG: Final = "{ADR_0017_CLI[0]}"' in entry,
            "one long, explicit flag; an alias is how a wrong reflex succeeds quietly",
        )
        cli_lines = tuple(
            line.strip().strip('"').strip("',")
            for line in entry.splitlines()
            if line.strip().startswith('"--') or line.strip().startswith("AUTHORIZATION_FLAG")
        )
        f.check(
            "the entry point adds exactly the two non-flag arguments",
            entry.count('parser.add_argument(\n        "--') == 2,
            f"the CLI is three arguments and no more. Found lines: {len(cli_lines)}",
        )
        for spelling in ADR_0017_FORBIDDEN_CLI:
            f.check(
                f"the entry point refuses {spelling} by name",
                f'"{spelling}":' in entry,
                "an unrecognised flag teaches nothing; a named refusal says why",
            )
        f.check(
            "the entry point calls the accepted composition root",
            "execute_qualification_acquisition" in entry_exec,
            "the root is extended and reused, never re-implemented",
        )
        f.check(
            "the entry point constructs no store, client or runtime of its own",
            not any(
                name in entry_exec
                for name in ("S3ResearchObjectStore(", "QualificationRuntime(", "SharadarClient(")
            ),
            "a second construction site is a second thing to review",
        )
        f.check(
            "the entry point introduces no parser",
            not any(
                name in entry_exec
                for name in ("csv", "DictReader", "json.loads", "splitlines", ".decode(")
            ),
            "the payload is opaque at every layer, and a parser here would end that",
        )
        f.check(
            "the entry point writes no file and names no runtime directory",
            not any(
                name in entry_exec
                for name in (".runtime/", "write_text", "write_bytes", "mkdir", "tempfile")
            ),
            "no local staging, and no report beside the acquisition record",
        )
        f.check(
            "the entry point names no CONTROL destination",
            "control_bucket_name" not in entry_exec,
            "the licensed bucket has a different output key, and only it is named",
        )
        f.check(
            "the entry point neither imports the public harness nor the binding preflight",
            "sharadar_private_qualification" not in entry_exec
            and "sharadar_binding_preflight" not in entry_exec,
            "both stay separate; reusing either would destroy the evidence of separation",
        )
        f.check(
            "the entry point locks the dataset, the page and the retry policy",
            'LOCKED_DATASET_NAME: Final = "stocks"' in entry
            and "PAGE_SKIP: Final = 0" in entry
            and "RetryPolicy(max_attempts=1, backoff_seconds=())" in entry,
            "an operator who could choose these could choose a retrieval nobody reviewed",
        )
        f.check(
            "the entry point's page limit ceiling is at most ten",
            "PAGE_LIMIT_CEILING: Final = 10" in entry,
            "ADR-0017 fixed the ceiling far below the model's own",
        )
        f.check(
            "the entry point locks a seven-day window",
            "WINDOW_DAYS: Final = 7" in entry,
            "deterministic from the injected clock, and never operator-supplied",
        )
        # Whitespace-collapsed, so a docstring rewrapped across lines cannot
        # evade the guard, and case-folded for the same reason the document
        # scans are. The script is what an operator reads before running
        # anything, so its own status may not go stale behind the markdown.
        entry_flat = " ".join(entry.replace("**", "").split()).lower()
        for label, phrase in ADR_0017_ENTRY_POINT_REQUIRED:
            f.check(
                f"the entry point {label}",
                phrase in entry_flat,
                f"missing from the entry point: {phrase}",
            )
        stale = [claim for claim in ADR_0017_ENTRY_POINT_FORBIDDEN if claim in entry_flat]
        f.check(
            "the entry point no longer claims it has never been run",
            not stale,
            ", ".join(stale),
        )

    f.check(
        "the composition root exposes exactly one acquisition execution surface",
        _executable_python(COMPOSITION_ROOT).count("def execute_qualification_acquisition(") == 1
        and _executable_python(COMPOSITION_ROOT).count(".execute(") == 1,
        "one authorized surface, one call, and no second under any spelling",
    )
    f.check(
        "the accepted composition root was extended, not duplicated",
        "composition.py" in [path.name for path in _store_construction_sites()]
        and _executable_python(COMPOSITION_ROOT).count("def execute_qualification_acquisition(")
        == 1,
        "ADR-0017's surface stays one function in the module that already composed",
    )
    f.check(
        "the composition root declares the qualification acquisition mode once",
        "QUALIFICATION_ACQUISITION_MODE" in _executable_python(COMPOSITION_ROOT),
        "one statement, not two that could drift",
    )
    f.check(
        "the two dedicated ADR-0017 test suites exist",
        ADR_0017_ENTRY_TESTS.is_file() and ADR_0017_COMPOSITION_TESTS.is_file(),
        "executable invariants belong in unit tests, and the audit must not stand in for them",
    )
    if ADR_0017_ENTRY_TESTS.is_file():
        entry_tests = read(ADR_0017_ENTRY_TESTS)
        entry_tests_flat = " ".join(entry_tests.split()).lower()
        for label, phrase in ADR_0017_STATUS_TEST_REQUIRED:
            f.check(
                f"the ADR-0017 status test {label}",
                phrase.lower() in entry_tests_flat,
                f"missing from the entry-point tests: {phrase}",
            )
        stale_assertions = [
            claim for claim in ADR_0017_STATUS_TEST_FORBIDDEN if claim.lower() in entry_tests_flat
        ]
        f.check(
            "the ADR-0017 status test has not reverted to the bare substring check",
            not stale_assertions,
            ", ".join(stale_assertions),
        )
        for label, needle in (
            ("import safety", "test_importing_the_entry_point_performs_no_activity"),
            ("the exact CLI", "test_the_cli_carries_exactly_the_three_approved_arguments"),
            ("the exact flag", "test_the_authorization_flag_is_exactly_the_approved_spelling"),
            ("forbidden aliases", "test_every_forbidden_alias_is_absent_from_the_cli"),
            ("the exit-code mapping", "test_every_outcome_has_an_exact_exit_status"),
            ("gate ordering", "test_an_identity_refusal_prevents_bucket_resolution"),
            ("the locked dataset", "test_the_locked_dataset_is_exactly_stocks"),
            ("the window arithmetic", "test_the_window_is_seven_calendar_days"),
            ("harness separation", "test_the_script_never_imports_the_public_test_token_harness"),
            ("preflight separation", "test_the_script_never_invokes_the_binding_preflight"),
        ):
            f.check(
                f"an ADR-0017 entry-point test covers {label}",
                needle in entry_tests,
                "the guard this audit names must be a test that exists",
            )
    if ADR_0017_COMPOSITION_TESTS.is_file():
        composition_tests = read(ADR_0017_COMPOSITION_TESTS)
        for label, needle in (
            ("one provider request", "test_one_provider_request_is_issued"),
            ("three PutObject calls", "test_one_ordinary_success_issues_exactly_three_put_object"),
            ("no preflight HeadObject", "test_an_ordinary_success_issues_no_preflight_head_object"),
            ("the conditional HeadObject bound", "test_conditional_head_object_calls_never_exceed"),
            ("zero object-byte reads", "test_no_object_byte_read_occurs"),
            ("no CONTROL write", "test_no_control_classified_object_is_written"),
            ("no retry after a failure", "test_a_transport_failure_produces_no_second_request"),
            ("the qualification mode", "test_the_acquisition_mode_recorded_is_qualification"),
            ("no parser", "test_the_module_introduces_no_parser"),
            ("no second root", "test_no_second_composition_module_exists"),
        ):
            f.check(
                f"an ADR-0017 composition test covers {label}",
                needle in composition_tests,
                "the guard this audit names must be a test that exists",
            )

    # ------------------------------------ ADR-0018, accepted architecture only
    #
    # PR #39 merged, so the conditional acceptance took effect and the absence
    # guards that governed the proposed state are inverted rather than deleted.
    # What still has to be checked as hard as the acceptance is the *scope* of
    # it: everything below is either "the document says the true thing" or "the
    # thing it designs does not exist yet", and the second half is what stops
    # "architecture only" from being a sentence nobody can falsify.
    f.check(
        "ADR-0018 exists",
        ADR_0018.is_file(),
        "the ADR this section governs must be the file it names",
    )
    if ADR_0018.is_file():
        adr_0018_flat = " ".join(read(ADR_0018).replace("**", "").split()).lower()
        for label, phrase in ADR_0018_SELF_REQUIRED:
            f.check(
                f"ADR-0018 {label}",
                phrase in adr_0018_flat,
                f"missing from ADR-0018: {phrase}",
            )
        overstated = [claim for claim in ADR_0018_SELF_FORBIDDEN if claim in adr_0018_flat]
        f.check(
            "ADR-0018 claims no authority it does not have",
            not overstated,
            ", ".join(overstated),
        )
        carriers = [name for name in ADR_0018_SUBJECT_CARRIERS if name in adr_0018_flat]
        f.check(
            "ADR-0018 carries no concrete subject list",
            not carriers,
            ", ".join(carriers),
        )

    adr_0018_documents = {
        "CLAUDE.md": read(REPO_ROOT / "CLAUDE.md"),
        "README.md": read(REPO_ROOT / "README.md"),
    }
    for name, document in sorted(adr_0018_documents.items()):
        flat = " ".join(document.replace("**", "").split()).lower()
        for label, phrase in ADR_0018_STATUS_REQUIRED:
            f.check(
                f"{name} {label} for ADR-0018",
                phrase in flat,
                f"missing from {name}: {phrase}",
            )
        overstated = [claim for claim in ADR_0018_STATUS_FORBIDDEN if claim in flat]
        f.check(
            f"{name} does not overstate ADR-0018",
            not overstated,
            ", ".join(overstated),
        )

    f.check(
        "ADR-0018 is governed by the merged-ADR registry",
        # Inverted, not deleted. Until PR #39 merged this check required the
        # opposite, and deleting it then would have left the reverted claim
        # unguarded -- the same treatment ADR-0017's guard was given when
        # PR #33 merged.
        dict(MERGED_ADR_STATUS).get("ADR-0018") == f"PR {ADR_0018_PR} merged",
        f"ADR-0018 must be registered as 'PR {ADR_0018_PR} merged'",
    )
    f.check(
        "both status documents make ADR-0018's in-force claim against the right pull request",
        all(
            _in_force_adr_claims(t).get("ADR-0018") == f"PR {ADR_0018_PR} merged"
            for t in adr_0018_documents.values()
        ),
        "an accepted ADR must claim its merge, in both documents, naming the same pull request",
    )

    for label, phrase in ADR_0018_RUNBOOK_REQUIRED:
        f.check(
            f"the deletion runbook {label}",
            phrase in " ".join(read(DELETION_RUNBOOK).replace("**", "").split()).lower(),
            f"missing from the deletion runbook: {phrase}",
        )

    adr_0018_plan = " ".join(
        read(PHASE3 / "implementation-plan.md").replace("**", "").split()
    ).lower()
    for label, phrase in ADR_0018_PLAN_REQUIRED:
        f.check(
            f"the implementation plan {label}",
            phrase in adr_0018_plan,
            f"missing from the implementation plan: {phrase}",
        )

    # ---------------------------------------------------------------- ADR-0019
    #
    # The merged write-only acquisition amendment. PR #46 merged, so every check
    # here is about an *accepted architecture with an uncorrected implementation*:
    # the ADR must exist, it must keep the conditional line it was written with as
    # history beside the event that satisfied it, it must not read itself as built,
    # it must be registered in MERGED_ADR_STATUS, and the status documents must
    # carry the governing arithmetic without leaving the arithmetic it replaced
    # standing anywhere as current.
    f.check(
        "ADR-0019 exists",
        ADR_0019.is_file(),
        "the proposed write-only acquisition amendment must be the file it names",
    )
    if ADR_0019.is_file():
        adr_0019_flat = " ".join(read(ADR_0019).replace("**", "").split()).lower()
        for label, phrase in ADR_0019_SELF_REQUIRED:
            f.check(
                f"ADR-0019 {label}",
                phrase in adr_0019_flat,
                f"missing from ADR-0019: {phrase}",
            )
        overstated = [claim for claim in ADR_0019_SELF_FORBIDDEN if claim in adr_0019_flat]
        f.check(
            "ADR-0019 claims no authority it does not have",
            not overstated,
            ", ".join(overstated),
        )

    f.check(
        # Inverted on the merge of PR #46, not deleted. This required ABSENCE from
        # the registry while ADR-0019 sat on an open pull request; the merge is the
        # event that flips it, and deleting it would leave the reverted claim
        # unguarded -- the same treatment ADR-0018's guard was given on PR #39.
        "ADR-0019 is registered as a merged ADR",
        dict(MERGED_ADR_STATUS).get("ADR-0019") == f"PR {ADR_0019_PR} merged",
        f"ADR-0019 must be registered as 'PR {ADR_0019_PR} merged'",
    )

    for name, document in sorted(adr_0018_documents.items()):
        flat = " ".join(document.replace("**", "").split()).lower()
        for label, phrase in ADR_0019_STATUS_REQUIRED:
            f.check(
                f"{name} {label} for ADR-0019",
                phrase in flat,
                f"missing from {name}: {phrase}",
            )
        overstated = [claim for claim in ADR_0019_STATUS_FORBIDDEN if claim in flat]
        f.check(
            f"{name} does not overstate ADR-0019",
            not overstated,
            ", ".join(overstated),
        )

        # The contextual half of the retirement, and the reason it exists: the
        # phrase checks above establish that each document says the old figures no
        # longer govern, and say nothing about whether the old figures are still
        # standing somewhere else in the same file presented as current. They were.
        retired = scan_retired_arithmetic(document)
        f.check(
            f"{name} delimits its retired ADR-0018 arithmetic",
            retired.balanced and retired.blocks >= RETIRED_ARITHMETIC_BLOCKS,
            "an unclosed, unopened or nested marker would make the scan below vacuous",
        )
        f.check(
            f"{name} presents no retired ADR-0018 arithmetic as current",
            retired.balanced and not retired.findings,
            ", ".join(f"line {number}: {label}" for number, label in retired.findings),
        )

    for phrase, framing in HISTORICAL_ONLY_STATUS_LINES:
        f.check(
            # The pairing itself, before anything is measured with it. A framing
            # that did not contain its phrase would make every subtraction below
            # meaningless and every check vacuously green.
            f"the historical framing contains the line it frames: {phrase[:44]}",
            phrase in framing,
            "a framing that does not contain its phrase measures nothing",
        )
    for name, path in (
        ("CLAUDE.md", REPO_ROOT / "CLAUDE.md"),
        ("README.md", REPO_ROOT / "README.md"),
        ("the implementation plan", PHASE3 / "implementation-plan.md"),
    ):
        reading = " ".join(read(path).replace("**", "").split()).lower()
        for phrase, framing in HISTORICAL_ONLY_STATUS_LINES:
            f.check(
                f"{name} keeps a superseded status line historical: {phrase[:44]}",
                _unframed_occurrences(reading, phrase, framing) == 0,
                f"{phrase} stands outside its historical framing in {name}",
            )
            f.check(
                # The other half. Zero unframed copies is also what a document
                # that deleted the record entirely would report, and deleting the
                # record is how a status document stops being able to show that
                # it moved.
                f"{name} still carries the superseded line as history: {phrase[:44]}",
                framing in reading,
                f"the historical record of {phrase} was deleted from {name}",
            )

    for label, phrase in ADR_0019_PLAN_REQUIRED:
        f.check(
            f"the implementation plan {label} for ADR-0019",
            phrase in adr_0018_plan,
            f"missing from the implementation plan: {phrase}",
        )

    # ---------------------------------------------------------------- ADR-0020
    #
    # The request-scoped qualification payload identity, ACCEPTED / IN FORCE on
    # the merge of PR #49. Every check here holds one distinction: the
    # architecture is accepted and the implementation is not. The ADR must exist,
    # it must still carry the conditional line it was written with AND the
    # adjacent post-merge note beside it, it must be in MERGED_ADR_STATUS exactly
    # once, its sample keys must carry no security symbol, and both status
    # documents and the implementation plan must record the merge, the historical
    # proposed period, the open implementation gap and the still-open, still
    # uncorrected pull request.
    f.check(
        "ADR-0020 exists",
        ADR_0020.is_file(),
        "the proposed payload-identity amendment must be the file it names",
    )
    if ADR_0020.is_file():
        adr_0020_text = read(ADR_0020)
        adr_0020_flat = " ".join(adr_0020_text.replace("**", "").split()).lower()
        for label, phrase in ADR_0020_SELF_REQUIRED:
            f.check(
                f"ADR-0020 {label}",
                phrase in adr_0020_flat,
                f"missing from ADR-0020: {phrase}",
            )
        overstated = [claim for claim in ADR_0020_SELF_FORBIDDEN if claim in adr_0020_flat]
        f.check(
            "ADR-0020 claims no authority it does not have",
            not overstated,
            ", ".join(overstated),
        )
        leaked = _sample_key_subject_segments(adr_0020_text)
        f.check(
            "ADR-0020 exposes no subject-shaped literal in a sample key",
            not leaked,
            ", ".join(sorted(set(leaked))),
        )

    f.check(
        # Inverted on the merge, not deleted. While ADR-0020 sat on an open pull
        # request this asserted its ABSENCE from the registry; PR #49 is the event
        # that flips it, and deleting the guard would leave the reverted claim
        # unguarded -- the treatment ADR-0017, ADR-0018 and ADR-0019 were each
        # given. The registry is what governs an in-force claim, so this is the
        # entry every ADR-0020 status row is measured against.
        "ADR-0020 is registered as a merged ADR",
        dict(MERGED_ADR_STATUS).get("ADR-0020") == f"PR {ADR_0020_PR} merged",
        f"ADR-0020 must be registered as 'PR {ADR_0020_PR} merged'",
    )
    f.check(
        # A duplicate entry is invisible to ``dict``, so the tuple is counted
        # rather than the mapping: two rows for one decision is two answers to
        # one question, and the second could carry a different pull request --
        # which every guard reading ``dict(MERGED_ADR_STATUS)`` would then adopt
        # silently.
        "the merged-ADR registry registers each ADR exactly once",
        not _duplicate_registry_entries(MERGED_ADR_STATUS),
        ", ".join(_duplicate_registry_entries(MERGED_ADR_STATUS)),
    )

    for name, document in sorted(adr_0018_documents.items()):
        flat = " ".join(document.replace("**", "").split()).lower()
        # The section, not the file. Every phrase below is a claim ADR-0020's own
        # status section must carry, and 46 of the 49 are spelled somewhere else
        # in the same document as well -- ADR-0018's and ADR-0019's status blocks
        # carry their own "run a: not authorized / not run". Scanned flat, a
        # deletion from ADR-0020's section was answered by ADR-0019's copy and
        # went unreported: 0 of 12 disclosed section-local removals were caught.
        # The section is extracted by its heading, never by a phrase under test.
        scan = scan_adr_0020_status_sections(document)
        f.check(
            # One section, and structurally sound. Cardinality is checked because a
            # phrase scan cannot see a duplicate -- a second copy only ever adds
            # occurrences, so every phrase check stays green while two sections
            # disagree about one decision. ``defects`` is checked in the same place
            # because a malformed structure can still yield exactly one
            # plausible-looking section, and a vacuous pass is the failure mode.
            f"{name} carries exactly one ADR-0020 status section",
            len(scan.sections) == 1 and not scan.defects,
            "; ".join((f"{len(scan.sections)} sections", *scan.defects)),
        )
        section = " ".join(" ".join(scan.sections).replace("**", "").split()).lower()
        for label, phrase in ADR_0020_STATUS_REQUIRED:
            f.check(
                f"{name} {label} for ADR-0020",
                phrase in section,
                f"missing from the ADR-0020 status section of {name}: {phrase}",
            )
        # The denylist keeps whole-document scope and gains the section as well.
        # For a *presence* denylist document scope already contains section scope,
        # so this widening removes nothing and can add no failure the file-wide
        # scan would miss; the section is named in the detail so a reader is told
        # where the claim sits. It is deliberately not split into a section-only
        # list: a forbidden phrase that never legitimately appears outside the
        # section would be a guard that cannot fire, and the proposed-state
        # language that *does* legitimately appear -- "adr-0020 was proposed and
        # carried no authority" -- is history the section is required to keep.
        overstated = [
            f"{claim} (in the ADR-0020 status section)" if claim in section else claim
            for claim in ADR_0020_STATUS_FORBIDDEN
            if claim in flat or claim in section
        ]
        f.check(
            f"{name} does not overstate ADR-0020",
            not overstated,
            ", ".join(overstated),
        )

    for label, phrase in ADR_0020_PLAN_REQUIRED:
        f.check(
            f"the implementation plan {label} for ADR-0020",
            phrase in adr_0018_plan,
            f"missing from the implementation plan: {phrase}",
        )

    # The implementation half. The offline implementation candidate exists, and
    # every boundary it rests on is checked against the repository rather than
    # asserted in prose. Implementation, infrastructure mutation and execution are
    # three separate gates, and only the first has been crossed.
    f.check(
        "the ADR-0018 qualification package exists",
        ADR_0018_QUALIFY_PACKAGE.is_dir(),
        "the offline implementation candidate is present on this branch",
    )
    f.check(
        "the ADR-0018 acquisition entry point exists",
        ADR_0018_ACQUIRE_ENTRY.is_file(),
        "the offline implementation candidate is present on this branch",
    )
    f.check(
        "the ADR-0018 assessment entry point exists",
        ADR_0018_ASSESS_ENTRY.is_file(),
        "the offline implementation candidate is present on this branch",
    )
    f.check(
        "the qualification package sits outside the ingestion path",
        not ADR_0018_QUALIFY_PACKAGE.is_relative_to(ADR_0018_INGEST_PACKAGE),
        "a parser under data/ingest/ would put one on the opaque-payload path",
    )
    f.check(
        "no ingestion module imports the qualification package",
        not [
            path
            for path in _qualification_python_files(ADR_0018_INGEST_PACKAGE)
            if "data.qualify" in read(path)
        ],
        "the separation is a property of the import graph, not a rule to remember",
    )
    f.check(
        "the qualification package never imports the public-test-key harness",
        not [
            path
            for path in _qualification_python_files(ADR_0018_QUALIFY_PACKAGE)
            if "sharadar_private_qualification" in read(path)
        ],
        "that harness stays untouched, unimported and unauthorized to execute",
    )
    f.check(
        "the acquisition composition reaches no parser and no evaluator",
        ADR_0018_ACQUISITION.is_file()
        and "parser" not in _executable_python(ADR_0018_ACQUISITION)
        and "evaluator" not in _executable_python(ADR_0018_ACQUISITION),
        "the acquisition path publishes opaque bytes and interprets none of them",
    )
    f.check(
        "the assessment composition reaches no credential, secret or transport",
        ADR_0018_ASSESSMENT.is_file()
        and not any(
            token in _executable_python(ADR_0018_ASSESSMENT)
            for token in ("SharadarCredential", "get_secret_value", "UrllibTransport")
        ),
        "a provider failure must not be convertible into an assessment result",
    )
    f.check(
        "no qualification module constructs an SDK client",
        not [
            path
            for path in _qualification_python_files(ADR_0018_QUALIFY_PACKAGE)
            if "boto3" in _executable_python(path)
        ],
        "importing the data platform must still open no socket",
    )
    f.check(
        "PUBLIC_PIT is not expressible in the qualification package",
        not [
            path
            for path in _qualification_python_files(ADR_0018_QUALIFY_PACKAGE)
            if "PUBLIC_PIT" in _executable_python(path)
        ],
        "price origin stays PROVIDER_DERIVED, and Q7 is unchanged by this package",
    )
    f.check(
        "no qualification module carries a real security symbol",
        not [
            path
            for path in _qualification_python_files(ADR_0018_QUALIFY_PACKAGE)
            if _subject_shaped_literals(path)
        ],
        "which securities the owner evaluates is private evaluation information",
    )
    f.check(
        "the owner-only private inventory location is git-ignored",
        ".runtime/phase3/sharadar/empirical-inventory.json" in read(REPO_ROOT / ".gitignore"),
        "a subject list in Git history is a disclosure a later deletion does not undo",
    )
    f.check(
        "the owner-only private inventory does not exist in this repository",
        not (REPO_ROOT / ".runtime" / "phase3" / "sharadar" / "empirical-inventory.json").exists(),
        "it is the owner's file; a scaffolded placeholder would be mistaken for a decision",
    )
    f.check(
        "the two entry points use different authorization flags",
        ADR_0018_ACQUIRE_ENTRY.is_file()
        and ADR_0018_ASSESS_ENTRY.is_file()
        and ACQUIRE_FLAG in read(ADR_0018_ACQUIRE_ENTRY)
        and ASSESS_FLAG in read(ADR_0018_ASSESS_ENTRY)
        and ASSESS_FLAG not in read(ADR_0018_ACQUIRE_ENTRY),
        "two processes, two authorizations; neither can be given by pasting the other",
    )
    for label, option in ADR_0018_ACQUIRE_REFUSED:
        f.check(
            f"the acquisition entry point refuses {label} on the command line",
            ADR_0018_ACQUIRE_ENTRY.is_file() and f'"{option}"' in read(ADR_0018_ACQUIRE_ENTRY),
            "an operator who could choose it could choose a retrieval nobody reviewed",
        )
    for label, option in ADR_0018_ASSESS_REFUSED:
        f.check(
            f"the assessment entry point refuses {label} on the command line",
            ADR_0018_ASSESS_ENTRY.is_file() and f'"{option}"' in read(ADR_0018_ASSESS_ENTRY),
            "no listing exists anywhere, and no finding is ever emitted publicly",
        )
    for suite in ADR_0018_TEST_SUITES:
        f.check(
            f"the offline suite {suite.name} exists",
            suite.is_file(),
            "executable invariants belong in unit tests, and this audit must not replace them",
        )
    f.check(
        "no Terraform declares either designed qualification role",
        not _qualification_role_declarations(),
        "designing a role is not creating one; infrastructure mutation is a separate gate",
    )
    # This audit is excluded by name, and only this audit. It is a governance
    # guard, so it *has* to name the ADR it guards -- but it constructs no client,
    # sends no request and is not an operational surface. Excluding it by exact
    # filename rather than by directory keeps every other script in scope,
    # including the two entry points asserted absent above.
    f.check(
        "only the implementation candidate names ADR-0018",
        # Scanned on disk rather than through git, unlike the identifier scans:
        # this is about source modules that are part of the slice, and an audit that
        # only saw committed files would pass on an uncommitted branch by default.
        # No ``.py`` file under ``src/`` or ``scripts/`` is git-ignored, so none of
        # the reasons ``tracked_files`` exists applies here.
        sorted(
            path.name
            for path in _qualification_python_files(REPO_ROOT / "src")
            + _qualification_python_files(REPO_ROOT / "scripts")
            if path.name != "phase3_docs_audit.py" and "ADR-0018" in read(path)
        )
        == [
            "__init__.py",
            "__init__.py",
            "acquisition.py",
            "operations.py",
            "plan.py",
            "publication.py",
            "sharadar_empirical_qualification.py",
            "sharadar_qualification_assessment.py",
        ],
        "the modules implementing it cite it, as every other module cites its own ADR",
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
