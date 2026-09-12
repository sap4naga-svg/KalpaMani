"""ADR-0036 governance: a production principal design that declares, applies and runs nothing.

The decision designs the two production principals ADR-0035 §3.10 named -- a write-only
acquisition actor with one bounded secret grant and a research-build actor with exact reads and
no secret -- each as a human permission set plus an ECS task role. The checks here hold the
document to its own claims: it is proposed and not in force, it was produced without running
anything, it declares no Terraform and no policy under ``infra/``, it keeps the qualification
principals isolated and CONTROL deferred, and it carries no private value. The acceptance tests
it lists are checked for presence, not for satisfaction -- none is satisfied by its merge.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0036-production-data-plane-principals-and-trust-model.md"
ADR_0035: Final = DECISIONS / "ADR-0035-initial-breakout-long-research-dataset-ingestion-design.md"
INFRA: Final = PROJECT_ROOT / "infra"
README: Final = PROJECT_ROOT / "README.md"
CLAUDE: Final = PROJECT_ROOT / "CLAUDE.md"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""
ADR_FLAT: Final = " ".join(ADR_TEXT.split())

#: Names the design introduces. None may exist under ``infra/`` until the Terraform gate.
DESIGNED_NAMES: Final = (
    "kalpamani-production-acquisition",
    "kalpamani-research-build",
    "KalpaManiProductionAcquire",
    "KalpaManiResearchBuild",
    "KalpaManiAcquireLauncher",
    "KalpaManiBuildLauncher",
    "kalpamani-production-acquire-task",
    "kalpamani-research-build-task",
)

#: The pinned provider's permission-set name bound, as ADR-0022 records it.
PERMISSION_SET_NAME_LIMIT: Final = 32

TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")
HEX_40_OR_64: Final = re.compile(r"\b[0-9a-f]{40}\b|\b[0-9a-f]{64}\b")
REAL_ARN: Final = re.compile(r"\barn:aws\b")
IDENTIFIER_SHAPED: Final = re.compile(r"\b(?:runa|runb|assess)[a-z0-9]*-\d{8}-[a-z0-9]+\b")
SSO_START_URL: Final = re.compile(r"https?://[a-z0-9-]+\.awsapps\.com", re.IGNORECASE)


# -- existence and authority --------------------------------------------------


def test_the_adr_exists_at_its_exact_path() -> None:
    assert ADR.is_file()


def test_exactly_one_adr_0036_exists() -> None:
    assert [path.name for path in sorted(DECISIONS.glob("ADR-0036-*.md"))] == [ADR.name]


def test_the_adr_carries_a_conditional_acceptance_status() -> None:
    assert "Status: PROPOSED — NOT IN FORCE" in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "architecture and acceptance tests only" in ADR_FLAT


def test_the_adr_states_that_nothing_was_run_and_authorizes_no_implementation() -> None:
    assert "Nothing was run to produce this design" in ADR_FLAT
    assert "no Terraform command of any kind" in ADR_FLAT
    assert "Accepting this ADR authorizes no implementation and no execution" in ADR_FLAT
    assert "no Terraform declaration, plan or apply" in ADR_FLAT
    assert "five separate gates" in ADR_FLAT


def test_the_adr_supersedes_and_amends_nothing() -> None:
    assert "This ADR supersedes no earlier decision and amends no earlier ADR document" in ADR_FLAT


@pytest.mark.parametrize("number", [f"{n:04d}" for n in range(1, 35)])
def test_no_earlier_adr_mentions_this_one(number: str) -> None:
    earlier = sorted(DECISIONS.glob(f"ADR-{number}-*.md"))
    assert earlier, number
    for path in earlier:
        assert "ADR-0036" not in path.read_text(encoding="utf-8")


def test_adr_0035_names_this_one_only_in_its_post_merge_note() -> None:
    # ADR-0035 §3.10 left the production principals to a later gate; its post-merge note may
    # point forward to this design, but the decision text it was accepted with may not.
    text = ADR_0035.read_text(encoding="utf-8")
    note = text.index("The condition above has since been satisfied")
    assert "ADR-0036" not in text[:note]
    assert "ADR-0036" in text[note:]
    assert "itself proposed and not in force" in " ".join(text[note:].split())


def test_the_adr_is_built_on_adr_0035_and_the_accepted_trust_model() -> None:
    assert ADR_0035.name in ADR_TEXT
    assert "§3.10" in ADR_TEXT
    for earlier in ("ADR-0018", "ADR-0019", "ADR-0021", "ADR-0022", "ADR-0023"):
        assert earlier in ADR_TEXT, earlier


# -- the design itself --------------------------------------------------------


def test_the_two_actors_have_four_principals_and_no_long_lived_credential() -> None:
    assert "Two actors, four principals" in ADR_TEXT
    for name in DESIGNED_NAMES:
        assert f"`{name}`" in ADR_TEXT or f"({name})" in ADR_TEXT, name
    assert "No IAM user, no access key, no cross-account principal" in ADR_FLAT
    assert "`PT1H`" in ADR_TEXT


@pytest.mark.parametrize("name", ["KalpaManiProductionAcquire", "KalpaManiResearchBuild"])
def test_permission_set_names_fit_the_pinned_provider_bound(name: str) -> None:
    assert 1 <= len(name) <= PERMISSION_SET_NAME_LIMIT
    assert re.fullmatch(r"[\w+=,.@-]+", name) is not None
    assert f"`{name}` ({len(name)})" in ADR_TEXT


def test_the_acquisition_actor_is_write_only_with_one_bounded_secret() -> None:
    assert "bounded secret access, write-only Bronze" in ADR_TEXT
    assert "on exactly ONE secret ARN" in ADR_FLAT
    assert "the qualification secret is a different resource" in ADR_FLAT
    assert "it cannot read what it wrote, cannot list, cannot delete, cannot copy" in ADR_FLAT
    assert "DENY   s3:GetObject, s3:GetObjectVersion, s3:GetObjectAttributes" in ADR_TEXT


def test_the_build_actor_reads_exactly_and_holds_no_secret() -> None:
    assert "exact reads, licensed Silver/Gold writes, no secret" in ADR_TEXT
    assert "DENY   secretsmanager:*  (no secret of any kind)" in ADR_TEXT
    assert "no route to the internet gateway and no NAT" in ADR_FLAT
    assert "claims are validated from the locator, never read" in ADR_FLAT
    assert "Manifests stay LICENSED while CONTROL is deferred" in ADR_FLAT


def test_exact_object_references_come_from_a_run_locator_and_never_from_listing() -> None:
    assert "`licensed/bronze/sharadar/_indexes/<run-id>.json`" in ADR_TEXT
    assert "The build actor may not list" in ADR_FLAT
    assert "no fallback that reconstructs by listing, probing or guessing" in ADR_FLAT
    assert "`read_exact`" in ADR_TEXT


def test_the_exact_read_boundary_is_stated_as_two_boundaries() -> None:
    # Finding 7: prefix confinement is IAM's; locator-only reads are the application's.
    assert "The exact-read boundary is two boundaries" in ADR_FLAT
    assert "wildcard `s3:GetObject` grants" in ADR_FLAT
    assert "**IAM does not prove this**" in ADR_FLAT
    assert "not** an IAM property" in ADR_FLAT
    assert "**Locator validation, before any object it names is read**" in ADR_FLAT
    for clause in ("Identity binding", "Prefix allowlist", "Request scope", "Completeness"):
        assert f"**{clause}.**" in ADR_TEXT, clause


def test_bindings_are_validated_by_one_loader_and_delivered_two_ways() -> None:
    for contract in (
        "kalpamani-production-acquisition-runtime-binding/v1",
        "kalpamani-research-build-runtime-binding/v1",
        "KALPAMANI_PRODUCTION_ACQUISITION_RUNTIME_BINDING_FILE",
        "KALPAMANI_RESEARCH_BUILD_RUNTIME_BINDING_FILE",
    ):
        assert contract in ADR_TEXT, contract
    assert "neither loads as a qualification binding" in ADR_FLAT
    assert "per-actor SSM `SecureString` parameter" in ADR_FLAT
    assert "The **same loader** validates the document" in ADR_FLAT
    assert "loading is not identity proof" in ADR_FLAT
    assert "Identity proof is unchanged in kind and extended in shape" in ADR_FLAT
    # Finding 3: bootstrap permissions separate from the data plane; no parameter-policy grant;
    # KMS scoped by encryption context; ordering without circularity.
    assert (
        "**Three policy layers per actor, kept apart on purpose, and no layer contradicts"
        " another.**" in ADR_FLAT
    )
    assert "**Complete effective permissions, per principal.**" in ADR_FLAT
    # the shared data-plane policy carries no ssm/kms statement, so it cannot block the human writer
    assert "no ssm:* or kms:* statement of either effect lives here" in ADR_FLAT
    assert (
        "ssm:PutParameter, ssm:DeleteParameter, kms:Encrypt, kms:GenerateDataKey"
        not in " ".join(line for line in ADR_TEXT.splitlines() if line.startswith("DENY   iam:*"))
    )
    assert "**The task-only bootstrap policy**" in ADR_FLAT
    assert "kms:EncryptionContext:PARAMETER_ARN" in ADR_TEXT
    assert "kms:ViaService = ssm.<region>.amazonaws.com" in ADR_TEXT
    assert "**grant no access**" in ADR_FLAT
    assert "parameter policies are lifecycle instruments" in ADR_FLAT
    assert "**The key policy** of `kalpamani-task-bindings`" in ADR_FLAT
    assert "**Ordering, without a circular dependency.**" in ADR_FLAT
    assert "a constant in the image, not a field of the binding" in ADR_FLAT
    assert "parameter policy naming that role" not in ADR_FLAT


def test_advanced_securestring_writers_hold_generate_data_key_and_a_key_policy_statement() -> None:
    # Finding 2 (this cycle): advanced-tier inputs are envelope-encrypted, so the writer needs
    # GenerateDataKey, scoped to its own input parameter; tasks decrypt only; cleanup is one delete.
    assert "**The human bootstrap policy**" in ADR_FLAT
    assert (
        "ALLOW  kms:GenerateDataKey                on exactly ONE key ARN: kalpamani-task-bindings"
        in ADR_TEXT
    )
    assert "Bool ssm:Overwrite = false" in ADR_TEXT
    assert "DENY   kms:Decrypt, kms:Encrypt           (a human writes an input" in ADR_TEXT
    assert (
        "DENY   ssm:PutParameter, ssm:DeleteParameter, kms:Encrypt, kms:GenerateDataKey"
        "   (a task never writes" in ADR_TEXT
    )
    assert "| human input materialization |" in ADR_TEXT
    assert "`aws:PrincipalArn` `StringLike`" in ADR_FLAT
    assert "the writer needs `GenerateDataKey`, not `Encrypt`" in ADR_FLAT
    assert "**The cleanup procedure is therefore exactly one permitted operation**" in ADR_FLAT
    assert "created fresh for each run and never overwritten" in ADR_FLAT
    assert "tombstone" not in ADR_FLAT


def test_actor_role_matching_and_placement_verification_are_documented_mechanisms() -> None:
    # Finding 3 (this cycle).
    assert "**Where actor-to-role matching is enforced — three places, each named.**" in ADR_FLAT
    for layer in ("| **IAM** |", "| **task definition** |", "| **runner (application)** |"):
        assert layer in ADR_TEXT, layer
    assert "**Placement verification — a documented mechanism, on the launcher side.**" in ADR_FLAT
    assert "the earlier claim that it exposes a subnet CIDR or a public IP is withdrawn" in ADR_FLAT
    assert "`ecs:DescribeTasks` on the task ARN" in ADR_FLAT
    assert "`ec2:DescribeNetworkInterfaces` on that interface ID" in ADR_FLAT
    assert "`Association.PublicIp`" in ADR_TEXT
    assert "over the public ECS and EC2 endpoints (no VPC dependency)" in ADR_FLAT
    assert "This is a **detective** control on the launcher side" in ADR_FLAT
    assert "documented fields only: ImageID == compiled digest" in ADR_FLAT
    assert "subnet CIDR == bound actor subnet" not in ADR_FLAT


def test_the_acceptance_procedure_is_executable_and_attributes_the_refusal() -> None:
    # Finding 4 (this cycle): no resource-policy simulation for roles; R-3 has a control
    # principal, a fresh positive control, attribution, counts, staging and cleanup.
    assert "simulation of resource-based policies isn't supported" in ADR_FLAT
    assert "**no bucket-policy simulation is part of this design**" in ADR_FLAT
    assert "with the bucket policy as resource policy" not in ADR_FLAT
    assert "**The R-3 procedure — executable, staged, counted.**" in ADR_FLAT
    assert "**Staging.**" in ADR_FLAT and "Stage B (assignments) is applied only after" in ADR_FLAT
    assert "**The control principal.**" in ADR_FLAT
    assert "`with an explicit deny in a resource-based policy`" in ADR_FLAT
    assert "records **only the classification** of the error context" in ADR_FLAT
    assert (
        "**the positive control, fresh in this session; historical qualification writes are"
        " not it**" in ADR_FLAT
    )
    assert "one `GetCallerIdentity` first; nine S3 operations" in ADR_FLAT
    for row in (
        "| 1 | `PutObject`",
        "| 3 | `HeadObject`",
        "| 6 | `CreateMultipartUpload`",
        "| 8 | `DeleteObject`",
        "| 9 | `HeadObject`",
    ):
        assert row in ADR_TEXT, row
    assert "`licensed/_verification/`" in ADR_TEXT
    assert "a `403` without the resource-based context" in ADR_FLAT


def test_the_placement_release_barrier_holds_the_task_until_the_launcher_releases_it() -> None:
    # Amendment (this cycle) 1: an application-level barrier bound to the exact task and run.
    assert (
        "**The placement release barrier — an application-level gate the task cannot pass"
        in ADR_FLAT
    )
    for name in (
        "/kalpamani/production/acquisition/release",
        "/kalpamani/production/research-build/release",
        "kalpamani-placement-release/v1",
    ):
        assert name in ADR_TEXT, name
    for row in (
        "| **content** |",
        "| **writer** |",
        "| **reader** |",
        "| **who may not** |",
        "| **binding to the exact task and run** |",
        "| **bounded waiting** |",
        "| **stop conditions** |",
        "| **expiry** |",
        "| **cleanup** |",
    ):
        assert ADR_TEXT.count(row) >= 1, row
    assert "`task_arn` equals its own `TaskARN` from task metadata v4" in ADR_FLAT
    assert "`input_digest` equals the digest it computed over that input" in ADR_FLAT
    assert "**300 s**, at most 60 reads, each counted" in ADR_FLAT
    assert "`REFUSED_NO_RELEASE`" in ADR_TEXT and "`REFUSED_RELEASE_MISMATCH`" in ADR_TEXT
    assert "**zero** S3, secret and provider operations have occurred" in ADR_FLAT
    # writer/reader permissions are disjoint from the create-only input rule
    assert "**Why this is not a circular dependency with the input.**" in ADR_FLAT
    assert "enforced by disjoint statements on disjoint principals" in ADR_FLAT
    assert "this actor's placement-release parameter (2.9)" in ADR_FLAT
    assert "| launcher release materialization |" in ADR_TEXT
    assert " 6a release barrier" in ADR_TEXT
    assert "**The same run when placement fails.**" in ADR_FLAT
    assert "**writes no release**" in ADR_FLAT
    assert "placement release barrier:                    DESIGNED -- NOT IMPLEMENTED" in ADR_TEXT


def test_r3_failure_path_cleanup_is_defined_budgeted_and_confirmed() -> None:
    # Amendment (this cycle) 2: failure-path cleanup, counted separately from the expected path.
    assert (
        "the expected-path count; failure-path operations are counted separately below" in ADR_FLAT
    )
    assert (
        "**Failure-path cleanup — runs after any failed row, before the result is recorded.**"
        in ADR_FLAT
    )
    assert "captures every returned `UploadId`" in ADR_FLAT
    assert "`AbortMultipartUpload` `…/multipart` with that `UploadId`" in ADR_FLAT
    assert "`ListParts` with that `UploadId` → `NoSuchUpload`" in ADR_FLAT
    assert "at most **one** repeat is permitted" in ADR_FLAT
    assert "**at most 10 S3 operations** in addition to the nine of the expected path" in ADR_FLAT
    assert "**Unresolved cleanup keeps the gate closed**" in ADR_FLAT
    assert "not verified — cleanup unresolved" in ADR_FLAT
    assert "cleanup restores the bucket, it does not restore the result" in ADR_FLAT
    assert "The verification result is computed **after** cleanup" in ADR_FLAT
    assert "`AbortIncompleteMultipartUpload` lifecycle rule is a backstop" in ADR_FLAT


def test_the_historical_qualification_write_claim_is_gone_from_the_prerequisite() -> None:
    # Amendment (this cycle) 3.
    assert "Run A and Run B, whose 290" not in ADR_FLAT
    assert "290 conditional `PutObject`" not in ADR_FLAT
    assert "demonstrated in the same session by R-3's fresh positive control" in ADR_FLAT


def test_network_dependencies_are_a_per_actor_matrix_with_named_mechanisms() -> None:
    # Finding 1.
    assert "### 2.8 Network dependencies" in ADR_TEXT
    for dep in (
        "ECR API + registry",
        "CloudWatch Logs",
        "SSM Parameter Store",
        "| KMS |",
        "STS regional",
        "Secrets Manager",
        "provider origin (HTTPS)",
    ):
        assert dep in ADR_TEXT, dep
    assert "**no network path**" in ADR_FLAT
    assert "opens no KMS connection" in ADR_FLAT
    assert "the runner pins the **regional** endpoint" in ADR_FLAT
    assert (
        "**The mechanism enforcing its provider-origin restriction is the security group**"
        in ADR_FLAT
    )
    assert "no `0.0.0.0/0` rule" in ADR_FLAT
    assert "This is an **address** restriction, not a **hostname** restriction" in ADR_FLAT
    assert "**Interface endpoints bill hourly**" in ADR_FLAT
    assert "§4.21" in ADR_TEXT


def test_compute_inputs_are_delivered_without_an_owner_local_file() -> None:
    # Finding 5.
    assert "### 2.6 Compute-input delivery" in ADR_TEXT
    for name in (
        "/kalpamani/production/acquisition/input",
        "/kalpamani/production/research-build/input",
    ):
        assert name in ADR_TEXT, name
    for row in (
        "**authorized writer**",
        "**integrity and version**",
        "**size**",
        "**reconciliation**",
        "**retention**",
        "**cleanup**",
    ):
        assert row in ADR_TEXT, row
    assert "`expires_at - issued_at <= 24 h`" in ADR_TEXT
    assert "at most 32 run identities per build" in ADR_FLAT
    assert "**The acquisition task never writes the ledger**" in ADR_FLAT
    assert "`Expiration` parameter policy (lifecycle, not access)" in ADR_FLAT


def test_the_human_operating_environment_claims_no_network_isolation() -> None:
    # Finding 8.
    assert "### 2.10 The human operating environment" in ADR_TEXT
    assert "**ECS network isolation does not extend to a human profile on a laptop" in ADR_FLAT
    assert "this ADR does not claim that it does" in ADR_FLAT
    assert "**read no licensed payload bytes on the workstation**" in ADR_FLAT
    assert (
        "**The compensating control for the missing isolation is the absence of capability**"
        in ADR_FLAT
    )
    assert "the workstation's network **not** restricted by this design" in ADR_FLAT


def test_one_run_is_walked_end_to_end() -> None:
    assert "### 2.12 One run, end to end" in ADR_TEXT
    for step in (
        " 0  authorization",
        " 1  launch",
        " 2  image + log",
        " 4  binding + input",
        " 6  identity proof",
        " 7  data operations",
        " 9  termination",
        "10  cleanup",
    ):
        assert step in ADR_TEXT, step
    assert (
        "Every refusal between steps 4 and 6a happens before any S3, secret or provider operation"
        in ADR_FLAT
    )


def test_server_side_immutable_writes_are_a_prerequisite_with_no_fallback() -> None:
    # Finding 4: server-side refusal is required before application; no application-only fallback.
    assert "`s3:if-none-match`" in ADR_TEXT
    assert "`s3:ObjectCreationOperation`" in ADR_TEXT
    assert "`s3:x-amz-copy-source`" in ADR_TEXT
    assert "a prerequisite for application, not an invariant with a fallback" in ADR_FLAT
    assert "**Application is blocked until the server-side refusal is verified.**" in ADR_FLAT
    assert "There is no fallback to application-only enforcement" in ADR_FLAT
    assert "pending a **revised design**" in ADR_FLAT
    assert "`CopyObject` requests without a conditional header fail with `403`" in ADR_FLAT
    assert "multipart parts are refused outright" in ADR_FLAT
    assert "conditional-writes-enforce.html" in ADR_TEXT
    # the earlier two-strength wording is gone
    assert "fall back to the weaker one" not in ADR_FLAT
    assert "claiming enforcement it cannot prove" not in ADR_FLAT


def test_launch_is_gated_and_overrides_are_assigned_to_the_layer_that_controls_them() -> None:
    # Finding 2: execution role exact, launcher scoped, overrides split IAM vs launcher validation.
    assert "### 2.9 Launch" in ADR_TEXT
    assert "ecs-tasks.amazonaws.com" in ADR_TEXT
    assert "`<prefix>-task-execution` role is reused **unchanged**" in ADR_FLAT
    assert "NO     ssm:*, secretsmanager:*, kms:*" in ADR_TEXT
    assert "do not use the container `secrets` field" in ADR_FLAT
    assert "image pinned **by digest**" in ADR_FLAT
    assert "`KalpaManiAcquireLauncher`, 24 characters" in ADR_FLAT
    assert "`KalpaManiBuildLauncher`, 22" in ADR_FLAT
    assert "an **allowlist, not a binding**" in ADR_FLAT
    assert "DENY   iam:PassRole       NotResource those two role ARNs" in ADR_TEXT
    assert (
        "no other iam:* statement of either effect exists, so the PassRole grant is never"
        " overridden" in ADR_FLAT
    )
    assert "KalpaManiTaskLauncher" not in ADR_TEXT
    assert "ArnEquals ecs:cluster" in ADR_TEXT
    assert "iam:PassedToService = ecs-tasks.amazonaws.com" in ADR_TEXT
    assert "**IAM has no condition key for container overrides" in ADR_FLAT
    for override in (
        "`command`",
        "`environment`",
        "`taskRoleArn`, `executionRoleArn`",
        "`networkConfiguration`",
        "`count`",
        "`enableExecuteCommand`",
    ):
        assert f"| {override}" in ADR_TEXT, override
    assert "**One task per authorized run.**" in ADR_FLAT
    assert "a second launch is an incident, not a retry" in ADR_FLAT


def test_deletion_responsibilities_are_widened_and_still_cannot_read() -> None:
    assert "Unchanged in principle, widened in scope" in ADR_FLAT
    assert "cannot read any of them" in ADR_FLAT
    assert "Neither production actor can delete anything" in ADR_FLAT
    assert "the runbook never depends on one to discover licensed objects" in ADR_FLAT


def test_the_acceptance_tests_are_layered_and_present() -> None:
    # Finding 6: four layers, each case assigned to the weakest layer that can decide it.
    for label in [f"A-{n}" for n in range(1, 11)]:
        assert f"| {label} |" in ADR_TEXT, label
    assert "A-11" in ADR_TEXT
    for label in [f"R-{n}" for n in range(1, 10)]:
        assert f"| {label} |" in ADR_TEXT, label
    for layer in (
        "**L0 — static",
        "**L1 — offline Terraform",
        "**L2 — IAM simulation",
        "**L3 — runtime verification",
    ):
        assert layer in ADR_TEXT, layer
    assert "no layer's pass is reported as a stronger layer's" in ADR_FLAT
    assert (
        "task startup, image pull, endpoint reachability, KMS decryption, network isolation"
        in ADR_FLAT
    )
    assert (
        "Wording tests in this repository prove what a document says, not what AWS does" in ADR_FLAT
    )
    assert "recorded as **not exercised**, never as passed" in ADR_FLAT
    assert "recorded as **simulated**, never as verified" in ADR_FLAT
    assert "**R-3 is the gate**" in ADR_FLAT


def test_qualification_stays_isolated_and_control_stays_deferred() -> None:
    assert "licensed/qualification/*" in ADR_TEXT
    assert "the qualification policies gain nothing" in ADR_FLAT
    assert "qualification principals and artifacts:       UNCHANGED / ISOLATED" in ADR_TEXT
    assert "server-side conditional-write refusal (R-3):  NOT VERIFIED" in ADR_TEXT
    assert (
        "foundation <prefix>-task role:                UNCHANGED / NOT USED BY EITHER ACTOR"
        in ADR_TEXT
    )
    assert "CONTROL:                                      DEFERRED" in ADR_TEXT
    assert "first bounded ingestion:                      NOT AUTHORIZED / NOT RUN" in ADR_TEXT
    assert "live trading:                                 HARD-DISABLED" in ADR_TEXT


# -- nothing is declared, and nothing private is recorded ----------------------


def test_no_designed_name_exists_under_infra() -> None:
    files = [
        path
        for path in INFRA.rglob("*")
        if path.is_file() and path.suffix in {".tf", ".example", ".md", ".json"}
    ]
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in DESIGNED_NAMES:
            assert name not in text, f"{name} is designed, not declared: {path}"


def test_the_adr_carries_no_private_value() -> None:
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    assert HEX_40_OR_64.search(ADR_TEXT) is None
    assert REAL_ARN.search(ADR_TEXT) is None
    assert IDENTIFIER_SHAPED.search(ADR_TEXT) is None
    assert SSO_START_URL.search(ADR_TEXT) is None
    for word in ("PROCEED", "APPROVED", "QUALIFIED", "READY"):
        assert re.search(rf"\b{word}\b", ADR_TEXT) is None, word


# -- the status documents -----------------------------------------------------


@pytest.mark.parametrize("path", [README, CLAUDE])
def test_status_documents_record_the_adr_as_proposed(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "ADR-0036" in text
    assert re.search(r"ADR-0036[^\n]{0,200}PROPOSED — NOT IN FORCE", text) is not None
    assert "CONTROL stays DEFERRED" in text
