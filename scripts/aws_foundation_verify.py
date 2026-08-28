"""Verify the deployed AWS research foundation against ADR-0007's stated posture.

ADR-0007 makes structural claims -- the licensed bucket has no versioning, the
task security group admits nothing, the routine research role cannot delete, the
deletion role cannot read. Those claims are worth exactly as much as the deployed
account agrees with them, and prose drifts from reality silently.

This script asks AWS. It is READ-ONLY: every call is a describe/get/list or an
IAM policy *simulation*, which evaluates permissions without exercising them.

**It prints verdicts, never identifiers.** Bucket names, ARNs, account ids, VPC
ids, subnet ids and repository URLs are read into memory to make the calls and
are never written to stdout. The output is safe to paste into a pull request;
the values behind it are not, which is the whole point of the split.

The IAM section deliberately uses `iam:SimulatePrincipalPolicy` rather than
reading the policy JSON back. Parsing a policy document proves what Terraform
wrote; simulation proves what AWS will actually decide, including the effect of
anything attached outside this configuration.

Usage:
    AWS_PROFILE=kalpamani-foundation python scripts/aws_foundation_verify.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
INFRA = REPO_ROOT / "infra" / "aws" / "research-data-plane"
TERRAFORM = REPO_ROOT / ".runtime" / "tools" / "terraform" / "bin" / "terraform.exe"
EXPECTED_PROFILE = "kalpamani-foundation"

#: CloudWatch retention that would count as unbounded. ADR-0007 §8: an unbounded
#: retention turns any redaction failure into a permanent one.
MAX_RETENTION_DAYS = 365


class AwsCallError(Exception):
    """An AWS call that could not be completed."""


def aws(*args: str, allow_fail: bool = False) -> Any:
    """Run one read-only AWS CLI call and return parsed JSON.

    With `allow_fail`, an API error returns None instead of raising -- which is
    how "this configuration does not exist" is expressed for the S3 sub-resource
    APIs that raise rather than returning an empty document.
    """
    result = subprocess.run(  # noqa: S603
        ["aws", *args, "--output", "json"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        if allow_fail:
            return None
        raise AwsCallError(args[0] if args else "aws")
    if not result.stdout.strip():
        return {}
    return json.loads(result.stdout)


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
        raise AwsCallError("terraform output")
    raw = json.loads(result.stdout)
    return {k: v["value"] for k, v in raw.items()}


class Report:
    """Collects PASS/FAIL verdicts. Detail strings must never carry identifiers."""

    def __init__(self) -> None:
        self.failures = 0
        self.total = 0

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


def simulate(role_arn: str, action: str, resource: str) -> str:
    """Effective IAM decision for one action. 'allowed' / 'implicitDeny' / 'explicitDeny'."""
    out = aws(
        "iam",
        "simulate-principal-policy",
        "--policy-source-arn",
        role_arn,
        "--action-names",
        action,
        "--resource-arns",
        resource,
        allow_fail=True,
    )
    if not out:
        return "unknown"
    results = out.get("EvaluationResults") or []
    return str(results[0].get("EvalDecision", "unknown")) if results else "unknown"


def check_storage(r: Report, o: dict[str, Any]) -> None:
    lic, ctl = o["licensed_bucket_name"], o["control_bucket_name"]
    r.section("S3 -- licensed and control buckets")

    for label, b in (("licensed", lic), ("control", ctl)):
        r.check(
            f"{label} bucket exists",
            aws("s3api", "head-bucket", "--bucket", b, allow_fail=True) is not None,
        )

        bpa = (aws("s3api", "get-public-access-block", "--bucket", b, allow_fail=True) or {}).get(
            "PublicAccessBlockConfiguration", {}
        )
        r.check(
            f"{label} bucket Block Public Access -- all four ON",
            all(
                bpa.get(k) is True
                for k in (
                    "BlockPublicAcls",
                    "IgnorePublicAcls",
                    "BlockPublicPolicy",
                    "RestrictPublicBuckets",
                )
            ),
        )

        status = aws("s3api", "get-bucket-policy-status", "--bucket", b, allow_fail=True)
        is_public = bool((status or {}).get("PolicyStatus", {}).get("IsPublic", False))
        r.check(f"{label} bucket is not public", not is_public)

        oc = aws("s3api", "get-bucket-ownership-controls", "--bucket", b, allow_fail=True) or {}
        rules = oc.get("OwnershipControls", {}).get("Rules", [])
        r.check(
            f"{label} bucket ACLs disabled (BucketOwnerEnforced)",
            any(x.get("ObjectOwnership") == "BucketOwnerEnforced" for x in rules),
        )

        enc = aws("s3api", "get-bucket-encryption", "--bucket", b, allow_fail=True) or {}
        algos = [
            x.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm")
            for x in enc.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
        ]
        r.check(f"{label} bucket default encryption is AES256", "AES256" in algos)

        pol = aws("s3api", "get-bucket-policy", "--bucket", b, allow_fail=True) or {}
        doc = pol.get("Policy", "")
        r.check(
            f"{label} bucket has a TLS-only deny policy",
            "aws:SecureTransport" in doc
            and '"Effect": "Deny"' in doc.replace('"Effect":"Deny"', '"Effect": "Deny"'),
        )

    r.section("S3 -- deletion-first posture (licensed) vs durability (control)")

    lic_ver = (aws("s3api", "get-bucket-versioning", "--bucket", lic, allow_fail=True) or {}).get(
        "Status"
    )
    r.check(
        "licensed bucket versioning is NOT enabled", lic_ver != "Enabled", f"status={lic_ver!r}"
    )

    ctl_ver = (aws("s3api", "get-bucket-versioning", "--bucket", ctl, allow_fail=True) or {}).get(
        "Status"
    )
    r.check("control bucket versioning IS enabled", ctl_ver == "Enabled", f"status={ctl_ver!r}")

    lock = aws("s3api", "get-object-lock-configuration", "--bucket", lic, allow_fail=True)
    r.check("licensed bucket has no Object Lock", lock is None)

    repl = aws("s3api", "get-bucket-replication", "--bucket", lic, allow_fail=True)
    r.check("licensed bucket has no replication", repl is None)

    lifecycle = (
        aws("s3api", "get-bucket-lifecycle-configuration", "--bucket", lic, allow_fail=True) or {}
    )
    lic_rules = lifecycle.get("Rules", [])
    transitions = [
        x for x in lic_rules if x.get("Transitions") or x.get("NoncurrentVersionTransitions")
    ]
    r.check("licensed bucket has no archival transition rule", not transitions)
    r.check(
        "licensed bucket aborts incomplete multipart uploads",
        any(x.get("AbortIncompleteMultipartUpload") for x in lic_rules),
        "parts of an incomplete upload are billed and invisible to a list-and-delete deletion",
    )


def check_network(r: Report, o: dict[str, Any]) -> None:
    r.section("Network -- egress only, nothing answers")
    vpc_id, sg_id = o["vpc_id"], o["task_security_group_id"]
    subnets = o["public_subnet_ids"]

    vpcs = aws("ec2", "describe-vpcs", "--vpc-ids", vpc_id, allow_fail=True) or {}
    r.check("research VPC exists", len(vpcs.get("Vpcs", [])) == 1)

    found = aws("ec2", "describe-subnets", "--subnet-ids", *subnets, allow_fail=True) or {}
    r.check(
        f"expected subnets exist ({len(subnets)} declared)",
        len(found.get("Subnets", [])) == len(subnets) and len(subnets) >= 1,
    )

    rules = (
        aws(
            "ec2",
            "describe-security-group-rules",
            "--filters",
            f"Name=group-id,Values={sg_id}",
            allow_fail=True,
        )
        or {}
    )
    all_rules = rules.get("SecurityGroupRules", [])
    inbound = [x for x in all_rules if not x.get("IsEgress", False)]
    r.check(
        "task security group has ZERO inbound rules",
        not inbound,
        f"{len(inbound)} inbound rule(s) present",
    )
    r.check(
        "task security group has egress rules",
        len([x for x in all_rules if x.get("IsEgress")]) >= 1,
    )

    nat = (
        aws(
            "ec2",
            "describe-nat-gateways",
            "--filter",
            f"Name=vpc-id,Values={vpc_id}",
            allow_fail=True,
        )
        or {}
    )
    live_nat = [
        x for x in nat.get("NatGateways", []) if x.get("State") not in ("deleted", "deleting")
    ]
    r.check("no NAT Gateway", not live_nat, f"{len(live_nat)} NAT gateway(s)")

    albs = aws("elbv2", "describe-load-balancers", allow_fail=True) or {}
    in_vpc = [x for x in albs.get("LoadBalancers", []) if x.get("VpcId") == vpc_id]
    classic = aws("elb", "describe-load-balancers", allow_fail=True) or {}
    classic_in_vpc = [
        x for x in classic.get("LoadBalancerDescriptions", []) if x.get("VPCId") == vpc_id
    ]
    r.check("no load balancer in the research VPC", not in_vpc and not classic_in_vpc)


def check_registry_and_compute(r: Report, o: dict[str, Any]) -> None:
    r.section("ECR -- private registry, empty")
    repo_url = o["ecr_repository_url"]
    repo_name = repo_url.rsplit("/", 1)[-1]

    desc = (
        aws("ecr", "describe-repositories", "--repository-names", repo_name, allow_fail=True) or {}
    )
    repos = desc.get("repositories", [])
    r.check("research ECR repository exists", len(repos) == 1)
    if repos:
        repo = repos[0]
        r.check("ECR image tags are IMMUTABLE", repo.get("imageTagMutability") == "IMMUTABLE")
        r.check(
            "ECR scan-on-push enabled",
            bool(repo.get("imageScanningConfiguration", {}).get("scanOnPush")),
        )
        r.check(
            "ECR encryption is AES256",
            repo.get("encryptionConfiguration", {}).get("encryptionType") == "AES256",
        )

    pol = aws("ecr", "get-repository-policy", "--repository-name", repo_name, allow_fail=True)
    r.check("ECR repository has no cross-account or public policy", pol is None)

    images = aws("ecr", "list-images", "--repository-name", repo_name, allow_fail=True) or {}
    r.check("ECR repository is empty -- no image was built or pushed", not images.get("imageIds"))

    r.section("ECS -- cluster exists, nothing runs")
    cluster = o["ecs_cluster_name"]
    clusters = aws("ecs", "describe-clusters", "--clusters", cluster, allow_fail=True) or {}
    active = [c for c in clusters.get("clusters", []) if c.get("status") == "ACTIVE"]
    r.check("research ECS cluster exists and is ACTIVE", len(active) == 1)

    services = aws("ecs", "list-services", "--cluster", cluster, allow_fail=True) or {}
    r.check("no ECS service (compute is ephemeral)", not services.get("serviceArns"))

    for state in ("RUNNING", "PENDING"):
        tasks = (
            aws(
                "ecs",
                "list-tasks",
                "--cluster",
                cluster,
                "--desired-status",
                state,
                allow_fail=True,
            )
            or {}
        )
        r.check(f"no {state} ECS task", not tasks.get("taskArns"))

    families = aws("ecs", "list-task-definition-families", allow_fail=True) or {}
    r.check(
        "no task definition family was created by this work",
        not families.get("families"),
        f"{len(families.get('families', []))} family/families present",
    )

    r.section("CloudWatch Logs -- bounded retention")
    lg_name = o["log_group_name"]
    groups = (
        aws("logs", "describe-log-groups", "--log-group-name-prefix", lg_name, allow_fail=True)
        or {}
    )
    exact = [g for g in groups.get("logGroups", []) if g.get("logGroupName") == lg_name]
    r.check("research log group exists", len(exact) == 1)
    if exact:
        retention = exact[0].get("retentionInDays")
        r.check(
            "log retention is bounded (never-expire is not permitted)",
            isinstance(retention, int) and 0 < retention <= MAX_RETENTION_DAYS,
            f"retentionInDays={retention!r}",
        )


def check_iam(r: Report, o: dict[str, Any]) -> None:
    r.section("IAM -- the routine role cannot destroy; the deletion role cannot read")
    lic, ctl = o["licensed_bucket_name"], o["control_bucket_name"]
    task, deletion = o["task_role_arn"], o["licensed_data_deletion_role_arn"]
    execution = o["task_execution_role_arn"]
    lic_arn, ctl_arn = f"arn:aws:s3:::{lic}", f"arn:aws:s3:::{ctl}"

    def denied(role: str, action: str, resource: str) -> bool:
        return simulate(role, action, resource) != "allowed"

    def allowed(role: str, action: str, resource: str) -> bool:
        return simulate(role, action, resource) == "allowed"

    # The separation ADR-0007 and iam.tf rest on: routine research code holds no
    # destructive authority over an unversioned, unbacked-up store.
    r.check(
        "routine task role CANNOT s3:DeleteObject on licensed",
        denied(task, "s3:DeleteObject", f"{lic_arn}/*"),
    )
    r.check(
        "routine task role CANNOT s3:DeleteObjectVersion on licensed",
        denied(task, "s3:DeleteObjectVersion", f"{lic_arn}/*"),
    )
    r.check(
        "routine task role CANNOT s3:DeleteObject on control",
        denied(task, "s3:DeleteObject", f"{ctl_arn}/*"),
    )
    r.check(
        "routine task role CAN read/write licensed objects",
        allowed(task, "s3:PutObject", f"{lic_arn}/*"),
    )

    r.check(
        "deletion role CAN s3:DeleteObject on licensed",
        allowed(deletion, "s3:DeleteObject", f"{lic_arn}/*"),
    )
    r.check(
        "deletion role CANNOT s3:GetObject on licensed",
        denied(deletion, "s3:GetObject", f"{lic_arn}/*"),
    )
    r.check(
        "deletion role CANNOT s3:PutObject on licensed",
        denied(deletion, "s3:PutObject", f"{lic_arn}/*"),
    )
    r.check(
        "deletion role CANNOT reach the control bucket", denied(deletion, "s3:ListBucket", ctl_arn)
    )
    r.check(
        "deletion role CANNOT read control objects",
        denied(deletion, "s3:GetObject", f"{ctl_arn}/*"),
    )

    # Nothing may launch a task that runs AS the deletion role. Without PassRole
    # the role is inert, which is what makes "committed but unusable" true.
    for label, role in (("task", task), ("execution", execution), ("deletion", deletion)):
        r.check(
            f"no iam:PassRole on the deletion role from the {label} role",
            denied(role, "iam:PassRole", deletion),
        )

    # G1/G3 are OPEN: no provider secret exists, and the interface must stay unwired.
    r.check(
        "task role CANNOT read any Secrets Manager secret (provider_secret_arns empty)",
        denied(
            task, "secretsmanager:GetSecretValue", "arn:aws:secretsmanager:us-east-1:*:secret:*"
        ),
    )

    r.section("IAM -- no long-lived credentials anywhere in the account")
    users = aws("iam", "list-users", allow_fail=True) or {}
    user_list = users.get("Users", [])
    r.check("no IAM user exists in the account", not user_list, f"{len(user_list)} IAM user(s)")

    stale_keys = 0
    for u in user_list:
        keys = aws("iam", "list-access-keys", "--user-name", u["UserName"], allow_fail=True) or {}
        stale_keys += len(keys.get("AccessKeyMetadata", []))
    r.check(
        "no IAM access key exists in the account", stale_keys == 0, f"{stale_keys} access key(s)"
    )

    summary = aws("iam", "get-account-summary", allow_fail=True) or {}
    m = summary.get("SummaryMap", {})
    r.check("root account has no access key", m.get("AccountAccessKeysPresent", 1) == 0)
    r.check("root account MFA is enabled", m.get("AccountMFAEnabled", 0) == 1)


def main() -> int:
    profile = os.environ.get("AWS_PROFILE", "")
    print("=" * 78)
    print("KalpaMani -- AWS research foundation verification (read-only)")
    print("=" * 78)
    if profile != EXPECTED_PROFILE:
        print(f"  REFUSED: AWS_PROFILE must be pinned to {EXPECTED_PROFILE}.")
        return 2

    try:
        outputs = tf_outputs()
    except AwsCallError:
        print("  REFUSED: could not read Terraform outputs. Has the foundation been applied?")
        return 2

    r = Report()
    for fn in (check_storage, check_network, check_registry_and_compute, check_iam):
        try:
            fn(r, outputs)
        except AwsCallError as exc:
            r.check(f"{fn.__name__} completed", False, f"AWS call failed: {exc}")

    print()
    print("=" * 78)
    verdict = "PASS" if r.failures == 0 else "FAIL"
    print(f"FOUNDATION VERIFICATION: {verdict}  ({r.total - r.failures}/{r.total} checks passed)")
    print("=" * 78)
    return 0 if r.failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
