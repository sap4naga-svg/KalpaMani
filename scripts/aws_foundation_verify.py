"""Verify the deployed AWS research foundation against ADR-0007's stated posture.

ADR-0007 makes structural claims -- the licensed bucket has no versioning, the task
security group admits nothing, the routine research role cannot delete, the deletion
role cannot read. Those claims are worth exactly as much as the deployed account agrees
with them, and prose drifts from reality silently.

This script asks AWS. It is READ-ONLY: every call is a describe/get/list or an IAM
policy *simulation*, which evaluates permissions without exercising them.

**IT FAILS CLOSED, AND THAT IS THE POINT OF ITS STRUCTURE.**

An earlier revision treated *any* non-zero AWS exit status as "the configuration is
absent". That makes access-denied, an expired SSO session, a network failure,
throttling and a genuine absence indistinguishable -- so "licensed bucket has no
replication" would report PASS when the truth was "we were not allowed to look". A
verification tool whose failure mode is a green tick is worse than no tool.

Two rules follow, and both are enforced structurally rather than by care:

1. **An absence must be proved by a specific AWS error code**, declared per call and
   observed against the real API (see ``EXPECTED_ABSENCE``). Any other failure is a
   verification failure, never an absence.
2. **An IAM decision must be explicit.** ``allowed`` means allowed; ``implicitDeny``
   and ``explicitDeny`` mean denied. Anything else -- including a failed simulation --
   is a verification failure. A simulation that did not run must never be read as proof
   that a permission is denied.

**It prints verdicts, never identifiers.** Bucket names, ARNs, account ids, VPC ids,
subnet ids and repository URLs are read into memory to make the calls and are never
written to stdout. AWS *stderr* is never printed either -- it can quote a bucket name or
an ARN -- so failures are reported as a sanitized error code alone.

Order matters. The identity gate runs before any Terraform state is read, so a stale
profile or an expired session refuses immediately instead of reading remote state under
the wrong identity:

    profile pinned -> STS identity vs local binding -> remote state -> verification

Usage:
    AWS_PROFILE=kalpamani-foundation python scripts/aws_foundation_verify.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
INFRA = REPO_ROOT / "infra" / "aws" / "research-data-plane"
TERRAFORM = REPO_ROOT / ".runtime" / "tools" / "terraform" / "bin" / "terraform.exe"
TFVARS = INFRA / "terraform.tfvars"
BACKEND_HCL = REPO_ROOT / ".runtime" / "aws-foundation" / "backend.hcl"

EXPECTED_PROFILE = "kalpamani-foundation"
EXPECTED_REGION = "us-east-1"

#: CloudWatch retention that would count as unbounded. ADR-0007 §8: an unbounded
#: retention turns any redaction failure into a permanent one.
MAX_RETENTION_DAYS = 365

#: AWS error codes that genuinely mean "this configuration does not exist", observed
#: against the live API rather than assumed. Nothing else is ever read as an absence.
EXPECTED_ABSENCE = {
    "object_lock": ("ObjectLockConfigurationNotFoundError",),
    "replication": ("ReplicationConfigurationNotFoundError",),
    "lifecycle": ("NoSuchLifecycleConfiguration",),
    "bucket_policy": ("NoSuchBucketPolicy",),
    "ecr_repo_policy": ("RepositoryPolicyNotFoundException",),
}

#: IAM simulation decisions that are meaningful. Anything outside this mapping -- a
#: failed call, an empty result, a decision string AWS may add later -- is a failure.
DECISION_ALLOWED = "allowed"
DECISION_DENIED = frozenset({"implicitDeny", "explicitDeny"})

ERROR_CODE_RE = re.compile(r"An error occurred \(([A-Za-z0-9_.-]+)\)")


class VerificationError(Exception):
    """An AWS call or decision that could not be resolved.

    Raised rather than swallowed. Every path that catches this records a FAILED check,
    so an unresolvable call can never be counted as a satisfied invariant.
    """


@dataclass(frozen=True)
class AwsOutcome:
    """Result of one AWS CLI call, with stderr reduced to a sanitized error code."""

    ok: bool
    data: Any
    code: str


def _run_aws(args: tuple[str, ...]) -> AwsOutcome:
    try:
        result = subprocess.run(  # noqa: S603
            ["aws", *args, "--output", "json"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return AwsOutcome(ok=False, data=None, code="Timeout")
    except OSError:
        return AwsOutcome(ok=False, data=None, code="CliUnavailable")

    if result.returncode != 0:
        match = ERROR_CODE_RE.search(result.stderr or "")
        # Never surface stderr itself: it can quote a bucket name or an ARN.
        return AwsOutcome(ok=False, data=None, code=match.group(1) if match else "UnknownError")

    if not (result.stdout or "").strip():
        return AwsOutcome(ok=True, data={}, code="")
    try:
        return AwsOutcome(ok=True, data=json.loads(result.stdout), code="")
    except json.JSONDecodeError:
        return AwsOutcome(ok=False, data=None, code="UnparsableResponse")


def aws_required(*args: str) -> Any:
    """A call that must succeed. Any failure is a verification failure."""
    outcome = _run_aws(args)
    if not outcome.ok:
        raise VerificationError(f"{args[0]} {args[1]}: {outcome.code}")
    return outcome.data


def aws_absent_or(*args: str, absent: tuple[str, ...]) -> Any | None:
    """A call whose absence is a legitimate answer -- but only via a declared code.

    Returns the parsed document, or ``None`` when AWS reported one of ``absent``.
    Every other failure raises, so access-denied never masquerades as absence.
    """
    outcome = _run_aws(args)
    if outcome.ok:
        return outcome.data
    if outcome.code in absent:
        return None
    raise VerificationError(f"{args[0]} {args[1]}: {outcome.code}")


def classify_decision(decision: str) -> bool:
    """True if allowed, False if denied. Raises on anything else.

    Separated out and kept pure so the fail-closed rule is unit-testable without AWS.
    `denied = decision != "allowed"` was the earlier bug: it silently converted a
    failed simulation into proof of denial.
    """
    if decision == DECISION_ALLOWED:
        return True
    if decision in DECISION_DENIED:
        return False
    raise VerificationError(f"unresolved IAM decision: {decision!r}")


def simulate(role_arn: str, action: str, resource: str) -> bool:
    """Effective IAM decision for one action. True = allowed. Raises if unresolved."""
    data = aws_required(
        "iam",
        "simulate-principal-policy",
        "--policy-source-arn",
        role_arn,
        "--action-names",
        action,
        "--resource-arns",
        resource,
    )
    results = (data or {}).get("EvaluationResults") or []
    if not results:
        raise VerificationError("IAM simulation returned no evaluation result")
    return classify_decision(str(results[0].get("EvalDecision", "")))


class Report:
    """Collects PASS/FAIL verdicts. Detail strings must never carry identifiers."""

    def __init__(self) -> None:
        self.failures = 0
        self.total = 0
        self.api_errors = 0

    def section(self, title: str) -> None:
        print()
        print(f"-- {title} " + "-" * max(0, 74 - len(title)))

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        self.total += 1
        if not ok:
            self.failures += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok and detail:
            print(f"         {detail}")

    def guard(self, label: str, fn: Any, *args: Any) -> None:
        """Run one check whose evaluation may itself fail. A failure is a FAIL."""
        self.total += 1
        try:
            ok, detail = fn(*args)
        except VerificationError as exc:
            self.failures += 1
            self.api_errors += 1
            print(f"  [FAIL] {label}")
            print(f"         verification could not be completed: {exc}")
            return
        if not ok:
            self.failures += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok and detail:
            print(f"         {detail}")


# ---------------------------------------------------------------------------
# Gate 1 + 2 -- identity, before any state is read
# ---------------------------------------------------------------------------


def expected_account() -> str | None:
    """The local account binding. Read, never printed."""
    if not TFVARS.is_file():
        return None
    match = re.search(
        r'^allowed_account_ids\s*=\s*\["([0-9]{12})"\]',
        TFVARS.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return match.group(1) if match else None


def identity_gate() -> str | None:
    """Refuse unless the pinned profile resolves to the bound account.

    Returns an error reason, or None on success. Never prints the account id, the ARN,
    the user id or the SSO URL.
    """
    if os.environ.get("AWS_PROFILE", "") != EXPECTED_PROFILE:
        return f"AWS_PROFILE is not pinned to {EXPECTED_PROFILE}"

    bound = expected_account()
    if bound is None:
        return "no 12-digit account binding found in the local terraform.tfvars"

    outcome = _run_aws(("sts", "get-caller-identity"))
    if not outcome.ok:
        return f"could not resolve an authenticated AWS identity ({outcome.code})"

    actual = str((outcome.data or {}).get("Account", ""))
    if not re.fullmatch(r"[0-9]{12}", actual):
        return "the authenticated identity returned no usable account"
    if actual != bound:
        return "the authenticated account does not match the local account binding"
    return None


# ---------------------------------------------------------------------------
# Terraform state backend
# ---------------------------------------------------------------------------


def backend_settings() -> dict[str, str]:
    """Backend values from the uncommitted local file. Values are never printed."""
    if not BACKEND_HCL.is_file():
        raise VerificationError("the local backend configuration file is missing")
    settings: dict[str, str] = {}
    for line in BACKEND_HCL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        settings[key.strip()] = value.strip().strip('"')
    return settings


def check_state_backend(r: Report) -> None:
    r.section("Terraform state backend -- infrastructure-control data")

    try:
        settings = backend_settings()
    except VerificationError as exc:
        r.check("the local backend configuration file exists", False, str(exc))
        return
    r.check("the local backend configuration file exists", True)

    r.check(
        "backend region is us-east-1",
        settings.get("region") == EXPECTED_REGION,
        f"region={settings.get('region')!r}",
    )
    r.check("backend encryption is enabled", settings.get("encrypt") == "true")
    r.check(
        "backend uses the S3 native lockfile (no DynamoDB table)",
        settings.get("use_lockfile") == "true",
    )

    bucket = settings.get("bucket", "")
    if not bucket:
        r.check("the backend names a state bucket", False, "no bucket key in the backend file")
        return
    r.check("the backend names a state bucket", True)

    def _exists() -> tuple[bool, str]:
        aws_required("s3api", "head-bucket", "--bucket", bucket)
        return True, ""

    def _bpa() -> tuple[bool, str]:
        cfg = aws_required("s3api", "get-public-access-block", "--bucket", bucket)
        block = cfg.get("PublicAccessBlockConfiguration", {})
        keys = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")
        return all(block.get(k) is True for k in keys), "not all four settings are ON"

    def _owner() -> tuple[bool, str]:
        cfg = aws_required("s3api", "get-bucket-ownership-controls", "--bucket", bucket)
        rules = cfg.get("OwnershipControls", {}).get("Rules", [])
        return any(x.get("ObjectOwnership") == "BucketOwnerEnforced" for x in rules), "ACLs enabled"

    def _encryption() -> tuple[bool, str]:
        cfg = aws_required("s3api", "get-bucket-encryption", "--bucket", bucket)
        rules = cfg.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
        algos = [x.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm") for x in rules]
        return "AES256" in algos, "default encryption is not AES256"

    def _versioning() -> tuple[bool, str]:
        cfg = aws_required("s3api", "get-bucket-versioning", "--bucket", bucket)
        return cfg.get("Status") == "Enabled", "state history would be unrecoverable"

    def _not_public() -> tuple[bool, str]:
        cfg = aws_absent_or(
            "s3api",
            "get-bucket-policy-status",
            "--bucket",
            bucket,
            absent=EXPECTED_ABSENCE["bucket_policy"],
        )
        if cfg is None:
            return True, ""
        return cfg.get("PolicyStatus", {}).get("IsPublic") is False, "the bucket policy is public"

    def _policy_scope() -> tuple[bool, str]:
        cfg = aws_absent_or(
            "s3api",
            "get-bucket-policy",
            "--bucket",
            bucket,
            absent=EXPECTED_ABSENCE["bucket_policy"],
        )
        if cfg is None:
            return True, ""
        doc = json.loads(cfg.get("Policy", "{}"))
        statements = doc.get("Statement", [])
        # Only a TLS-only Deny is expected. Any Allow, or any principal naming another
        # account, would be a grant this bucket must not carry.
        for st in statements:
            if st.get("Effect") != "Deny":
                return False, "the state bucket policy contains a non-Deny statement"
            principal = st.get("Principal")
            if principal != "*" and principal != {"AWS": "*"}:
                return False, "the state bucket policy names a specific principal"
            if "aws:SecureTransport" not in json.dumps(st.get("Condition", {})):
                return False, "a Deny statement is not the TLS-only guard"
        return True, ""

    r.guard("state bucket exists", _exists)
    r.guard("state bucket Block Public Access -- all four ON", _bpa)
    r.guard("state bucket ACLs disabled (BucketOwnerEnforced)", _owner)
    r.guard("state bucket default encryption is AES256", _encryption)
    r.guard("state bucket versioning IS enabled", _versioning)
    r.guard("state bucket is not public", _not_public)
    r.guard("state bucket carries no cross-account or Allow policy", _policy_scope)


# ---------------------------------------------------------------------------
# Research foundation
# ---------------------------------------------------------------------------


def tf_outputs() -> dict[str, Any]:
    """Resource identifiers from Terraform state. Held in memory; never printed."""
    exe = str(TERRAFORM) if TERRAFORM.is_file() else "terraform"
    result = subprocess.run(  # noqa: S603
        [exe, f"-chdir={INFRA}", "output", "-json"],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if result.returncode != 0:
        raise VerificationError("terraform output failed")
    raw = json.loads(result.stdout)
    return {k: v["value"] for k, v in raw.items()}


def check_storage(r: Report, o: dict[str, Any]) -> None:
    lic, ctl = o["licensed_bucket_name"], o["control_bucket_name"]
    r.section("S3 -- licensed and control research buckets")

    for label, b in (("licensed", lic), ("control", ctl)):

        def _exists(bucket: str = b) -> tuple[bool, str]:
            aws_required("s3api", "head-bucket", "--bucket", bucket)
            return True, ""

        def _bpa(bucket: str = b) -> tuple[bool, str]:
            cfg = aws_required("s3api", "get-public-access-block", "--bucket", bucket)
            blk = cfg.get("PublicAccessBlockConfiguration", {})
            keys = (
                "BlockPublicAcls",
                "IgnorePublicAcls",
                "BlockPublicPolicy",
                "RestrictPublicBuckets",
            )
            return all(blk.get(k) is True for k in keys), "not all four settings are ON"

        def _not_public(bucket: str = b) -> tuple[bool, str]:
            cfg = aws_absent_or(
                "s3api",
                "get-bucket-policy-status",
                "--bucket",
                bucket,
                absent=EXPECTED_ABSENCE["bucket_policy"],
            )
            if cfg is None:
                return True, ""
            return cfg.get("PolicyStatus", {}).get("IsPublic") is False, "bucket policy is public"

        def _owner(bucket: str = b) -> tuple[bool, str]:
            cfg = aws_required("s3api", "get-bucket-ownership-controls", "--bucket", bucket)
            rules = cfg.get("OwnershipControls", {}).get("Rules", [])
            ok = any(x.get("ObjectOwnership") == "BucketOwnerEnforced" for x in rules)
            return ok, "ACLs are enabled"

        def _encryption(bucket: str = b) -> tuple[bool, str]:
            cfg = aws_required("s3api", "get-bucket-encryption", "--bucket", bucket)
            rules = cfg.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
            algos = [
                x.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm") for x in rules
            ]
            return "AES256" in algos, "default encryption is not AES256"

        def _tls(bucket: str = b) -> tuple[bool, str]:
            cfg = aws_absent_or(
                "s3api",
                "get-bucket-policy",
                "--bucket",
                bucket,
                absent=EXPECTED_ABSENCE["bucket_policy"],
            )
            if cfg is None:
                return False, "no bucket policy at all, so no TLS-only guard"
            doc = cfg.get("Policy", "")
            return "aws:SecureTransport" in doc and "Deny" in doc, "no TLS-only deny statement"

        r.guard(f"{label} bucket exists", _exists)
        r.guard(f"{label} bucket Block Public Access -- all four ON", _bpa)
        r.guard(f"{label} bucket is not public", _not_public)
        r.guard(f"{label} bucket ACLs disabled (BucketOwnerEnforced)", _owner)
        r.guard(f"{label} bucket default encryption is AES256", _encryption)
        r.guard(f"{label} bucket has a TLS-only deny policy", _tls)

    r.section("S3 -- deletion-first posture (licensed) vs durability (control)")

    def _lic_versioning() -> tuple[bool, str]:
        cfg = aws_required("s3api", "get-bucket-versioning", "--bucket", lic)
        status = cfg.get("Status")
        return status != "Enabled", f"status={status!r}"

    def _ctl_versioning() -> tuple[bool, str]:
        cfg = aws_required("s3api", "get-bucket-versioning", "--bucket", ctl)
        status = cfg.get("Status")
        return status == "Enabled", f"status={status!r}"

    def _no_lock() -> tuple[bool, str]:
        cfg = aws_absent_or(
            "s3api",
            "get-object-lock-configuration",
            "--bucket",
            lic,
            absent=EXPECTED_ABSENCE["object_lock"],
        )
        return cfg is None, "an Object Lock configuration exists"

    def _no_replication() -> tuple[bool, str]:
        cfg = aws_absent_or(
            "s3api",
            "get-bucket-replication",
            "--bucket",
            lic,
            absent=EXPECTED_ABSENCE["replication"],
        )
        return cfg is None, "a replication configuration exists"

    def _lifecycle() -> tuple[bool, str]:
        cfg = aws_absent_or(
            "s3api",
            "get-bucket-lifecycle-configuration",
            "--bucket",
            lic,
            absent=EXPECTED_ABSENCE["lifecycle"],
        )
        rules = (cfg or {}).get("Rules", [])
        archival = [
            x for x in rules if x.get("Transitions") or x.get("NoncurrentVersionTransitions")
        ]
        return not archival, "an archival transition rule exists"

    def _multipart() -> tuple[bool, str]:
        cfg = aws_absent_or(
            "s3api",
            "get-bucket-lifecycle-configuration",
            "--bucket",
            lic,
            absent=EXPECTED_ABSENCE["lifecycle"],
        )
        rules = (cfg or {}).get("Rules", [])
        ok = any(x.get("AbortIncompleteMultipartUpload") for x in rules)
        return ok, "incomplete multipart parts are billed and invisible to a list-and-delete"

    r.guard("licensed bucket versioning is NOT enabled", _lic_versioning)
    r.guard("control bucket versioning IS enabled", _ctl_versioning)
    r.guard("licensed bucket has no Object Lock", _no_lock)
    r.guard("licensed bucket has no replication", _no_replication)
    r.guard("licensed bucket has no archival transition rule", _lifecycle)
    r.guard("licensed bucket aborts incomplete multipart uploads", _multipart)


def check_network(r: Report, o: dict[str, Any]) -> None:
    r.section("Network -- egress only, nothing answers")
    vpc_id, sg_id = o["vpc_id"], o["task_security_group_id"]
    subnets = o["public_subnet_ids"]

    def _vpc() -> tuple[bool, str]:
        data = aws_required("ec2", "describe-vpcs", "--vpc-ids", vpc_id)
        return len(data.get("Vpcs", [])) == 1, "the research VPC was not found"

    def _subnets() -> tuple[bool, str]:
        data = aws_required("ec2", "describe-subnets", "--subnet-ids", *subnets)
        found = len(data.get("Subnets", []))
        return found == len(subnets) and found >= 1, f"{found} of {len(subnets)} subnets found"

    def _no_inbound() -> tuple[bool, str]:
        data = aws_required(
            "ec2", "describe-security-group-rules", "--filters", f"Name=group-id,Values={sg_id}"
        )
        rules = data.get("SecurityGroupRules", [])
        inbound = [x for x in rules if not x.get("IsEgress", False)]
        return not inbound, f"{len(inbound)} inbound rule(s) present"

    def _has_egress() -> tuple[bool, str]:
        data = aws_required(
            "ec2", "describe-security-group-rules", "--filters", f"Name=group-id,Values={sg_id}"
        )
        rules = [x for x in data.get("SecurityGroupRules", []) if x.get("IsEgress")]
        return len(rules) >= 1, "no egress rule, so the task could not reach anything"

    def _no_nat() -> tuple[bool, str]:
        data = aws_required(
            "ec2", "describe-nat-gateways", "--filter", f"Name=vpc-id,Values={vpc_id}"
        )
        live = [
            x for x in data.get("NatGateways", []) if x.get("State") not in ("deleted", "deleting")
        ]
        return not live, f"{len(live)} NAT gateway(s) -- an always-on hourly charge"

    def _no_lb() -> tuple[bool, str]:
        albs = aws_required("elbv2", "describe-load-balancers")
        classic = aws_required("elb", "describe-load-balancers")
        in_vpc = [x for x in albs.get("LoadBalancers", []) if x.get("VpcId") == vpc_id]
        old = [x for x in classic.get("LoadBalancerDescriptions", []) if x.get("VPCId") == vpc_id]
        return not in_vpc and not old, "a load balancer accepts inbound connections"

    r.guard("research VPC exists", _vpc)
    r.guard(f"expected subnets exist ({len(subnets)} declared)", _subnets)
    r.guard("task security group has ZERO inbound rules", _no_inbound)
    r.guard("task security group has egress rules", _has_egress)
    r.guard("no NAT Gateway", _no_nat)
    r.guard("no load balancer in the research VPC", _no_lb)


def check_registry_and_compute(r: Report, o: dict[str, Any]) -> None:
    r.section("ECR -- private registry, empty")
    repo_name = o["ecr_repository_url"].rsplit("/", 1)[-1]

    def _repo() -> tuple[bool, str]:
        data = aws_required("ecr", "describe-repositories", "--repository-names", repo_name)
        return len(data.get("repositories", [])) == 1, "the research repository was not found"

    def _attr(key: str, want: Any, path: tuple[str, ...] = ()) -> tuple[bool, str]:
        data = aws_required("ecr", "describe-repositories", "--repository-names", repo_name)
        repo = data["repositories"][0]
        node: Any = repo
        for part in path:
            node = node.get(part, {})
        return node.get(key) == want if path else repo.get(key) == want, f"{key} is not {want!r}"

    def _no_policy() -> tuple[bool, str]:
        cfg = aws_absent_or(
            "ecr",
            "get-repository-policy",
            "--repository-name",
            repo_name,
            absent=EXPECTED_ABSENCE["ecr_repo_policy"],
        )
        return cfg is None, "a repository policy exists (cross-account or public risk)"

    def _empty() -> tuple[bool, str]:
        data = aws_required("ecr", "list-images", "--repository-name", repo_name)
        n = len(data.get("imageIds", []))
        return n == 0, f"{n} image(s) present; no image build was authorized"

    r.guard("research ECR repository exists", _repo)
    r.guard("ECR image tags are IMMUTABLE", lambda: _attr("imageTagMutability", "IMMUTABLE"))
    r.guard(
        "ECR scan-on-push enabled",
        lambda: _attr("scanOnPush", True, ("imageScanningConfiguration",)),
    )
    r.guard(
        "ECR encryption is AES256",
        lambda: _attr("encryptionType", "AES256", ("encryptionConfiguration",)),
    )
    r.guard("ECR repository has no cross-account or public policy", _no_policy)
    r.guard("ECR repository is empty -- no image was built or pushed", _empty)

    r.section("ECS -- cluster exists, nothing runs")
    cluster = o["ecs_cluster_name"]

    def _cluster() -> tuple[bool, str]:
        data = aws_required("ecs", "describe-clusters", "--clusters", cluster)
        active = [c for c in data.get("clusters", []) if c.get("status") == "ACTIVE"]
        return len(active) == 1, "the research cluster is not ACTIVE"

    def _no_service() -> tuple[bool, str]:
        data = aws_required("ecs", "list-services", "--cluster", cluster)
        n = len(data.get("serviceArns", []))
        return n == 0, f"{n} service(s); compute must stay ephemeral"

    def _no_tasks(state: str) -> tuple[bool, str]:
        data = aws_required("ecs", "list-tasks", "--cluster", cluster, "--desired-status", state)
        n = len(data.get("taskArns", []))
        return n == 0, f"{n} {state} task(s)"

    def _no_families() -> tuple[bool, str]:
        data = aws_required("ecs", "list-task-definition-families")
        n = len(data.get("families", []))
        return n == 0, f"{n} task-definition family/families present"

    r.guard("research ECS cluster exists and is ACTIVE", _cluster)
    r.guard("no ECS service (compute is ephemeral)", _no_service)
    r.guard("no RUNNING ECS task", lambda: _no_tasks("RUNNING"))
    r.guard("no PENDING ECS task", lambda: _no_tasks("PENDING"))
    r.guard("no task definition family was created by this work", _no_families)

    r.section("CloudWatch Logs -- bounded retention")
    lg_name = o["log_group_name"]

    def _group() -> tuple[bool, str]:
        data = aws_required("logs", "describe-log-groups", "--log-group-name-prefix", lg_name)
        exact = [g for g in data.get("logGroups", []) if g.get("logGroupName") == lg_name]
        return len(exact) == 1, "the research log group was not found"

    def _retention() -> tuple[bool, str]:
        data = aws_required("logs", "describe-log-groups", "--log-group-name-prefix", lg_name)
        exact = [g for g in data.get("logGroups", []) if g.get("logGroupName") == lg_name]
        if not exact:
            raise VerificationError("log group missing, so retention cannot be read")
        retention = exact[0].get("retentionInDays")
        ok = isinstance(retention, int) and 0 < retention <= MAX_RETENTION_DAYS
        return ok, f"retentionInDays={retention!r}"

    r.guard("research log group exists", _group)
    r.guard("log retention is bounded (never-expire is not permitted)", _retention)


def check_iam(r: Report, o: dict[str, Any]) -> None:
    r.section("IAM -- the routine role cannot destroy; the deletion role cannot read")
    lic, ctl = o["licensed_bucket_name"], o["control_bucket_name"]
    task, deletion = o["task_role_arn"], o["licensed_data_deletion_role_arn"]
    execution = o["task_execution_role_arn"]
    lic_arn, ctl_arn = f"arn:aws:s3:::{lic}", f"arn:aws:s3:::{ctl}"

    def denied(role: str, action: str, resource: str) -> tuple[bool, str]:
        return (not simulate(role, action, resource)), "the permission is ALLOWED"

    def allowed(role: str, action: str, resource: str) -> tuple[bool, str]:
        return simulate(role, action, resource), "the permission is DENIED"

    r.guard(
        "routine task role CANNOT s3:DeleteObject on licensed",
        denied,
        task,
        "s3:DeleteObject",
        f"{lic_arn}/*",
    )
    r.guard(
        "routine task role CANNOT s3:DeleteObjectVersion on licensed",
        denied,
        task,
        "s3:DeleteObjectVersion",
        f"{lic_arn}/*",
    )
    r.guard(
        "routine task role CANNOT s3:DeleteObject on control",
        denied,
        task,
        "s3:DeleteObject",
        f"{ctl_arn}/*",
    )
    r.guard(
        "routine task role CAN read/write licensed objects",
        allowed,
        task,
        "s3:PutObject",
        f"{lic_arn}/*",
    )
    r.guard(
        "deletion role CAN s3:DeleteObject on licensed",
        allowed,
        deletion,
        "s3:DeleteObject",
        f"{lic_arn}/*",
    )
    r.guard(
        "deletion role CANNOT s3:GetObject on licensed",
        denied,
        deletion,
        "s3:GetObject",
        f"{lic_arn}/*",
    )
    r.guard(
        "deletion role CANNOT s3:PutObject on licensed",
        denied,
        deletion,
        "s3:PutObject",
        f"{lic_arn}/*",
    )
    r.guard(
        "deletion role CANNOT reach the control bucket", denied, deletion, "s3:ListBucket", ctl_arn
    )
    r.guard(
        "deletion role CANNOT read control objects",
        denied,
        deletion,
        "s3:GetObject",
        f"{ctl_arn}/*",
    )

    # Nothing may launch a task that RUNS AS the deletion role. The role's trust policy
    # does admit ecs-tasks.amazonaws.com -- it is not "unassumable" -- so the property
    # that actually holds it inert is the absence of PassRole plus the absence of any
    # task definition or workflow.
    for label, role in (("task", task), ("execution", execution), ("deletion", deletion)):
        r.guard(
            f"no iam:PassRole on the deletion role from the {label} role",
            denied,
            role,
            "iam:PassRole",
            deletion,
        )

    r.guard(
        "task role CANNOT read any Secrets Manager secret (provider_secret_arns empty)",
        denied,
        task,
        "secretsmanager:GetSecretValue",
        "arn:aws:secretsmanager:us-east-1:*:secret:*",
    )

    r.section("IAM -- no long-lived credentials anywhere in the account")

    def _no_users() -> tuple[bool, str]:
        data = aws_required("iam", "list-users")
        n = len(data.get("Users", []))
        return n == 0, f"{n} IAM user(s)"

    def _no_keys() -> tuple[bool, str]:
        data = aws_required("iam", "list-users")
        total = 0
        for u in data.get("Users", []):
            keys = aws_required("iam", "list-access-keys", "--user-name", u["UserName"])
            total += len(keys.get("AccessKeyMetadata", []))
        return total == 0, f"{total} access key(s)"

    def _root_key() -> tuple[bool, str]:
        data = aws_required("iam", "get-account-summary")
        return data.get("SummaryMap", {}).get(
            "AccountAccessKeysPresent", 1
        ) == 0, "a root key exists"

    def _root_mfa() -> tuple[bool, str]:
        data = aws_required("iam", "get-account-summary")
        return data.get("SummaryMap", {}).get("AccountMFAEnabled", 0) == 1, "root MFA is off"

    r.guard("no IAM user exists in the account", _no_users)
    r.guard("no IAM access key exists in the account", _no_keys)
    r.guard("root account has no access key", _root_key)
    r.guard("root account MFA is enabled", _root_mfa)


def main() -> int:
    print("=" * 78)
    print("KalpaMani -- AWS research foundation verification (read-only)")
    print("=" * 78)

    reason = identity_gate()
    if reason is not None:
        print("\n  AWS IDENTITY CHECK: FAIL")
        print(f"  REFUSED: {reason}")
        return 2
    print("\n  AWS IDENTITY CHECK: PASS")

    r = Report()
    check_state_backend(r)

    try:
        outputs = tf_outputs()
    except VerificationError:
        print("\n  REFUSED: could not read Terraform outputs from remote state.")
        return 2

    for fn in (check_storage, check_network, check_registry_and_compute, check_iam):
        fn(r, outputs)

    print()
    print("=" * 78)
    verdict = "PASS" if r.failures == 0 else "FAIL"
    print(f"FOUNDATION VERIFICATION: {verdict}  ({r.total - r.failures}/{r.total} checks passed)")
    if r.api_errors:
        print(f"  unresolved AWS calls or IAM decisions: {r.api_errors} -- treated as FAILURES")
    print("=" * 78)
    return 0 if r.failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
