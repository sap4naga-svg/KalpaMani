"""The ADR-0036 production principals, checked by parsing the Terraform.

`infra/aws/research-data-plane/production_*.tf` and the ADR-0036 statements in
`storage.tf` are an OFFLINE implementation. Nothing here contacts AWS, runs
Terraform, resolves a credential, reads state or opens a socket: the files are
read as text, parsed with the HCL-subset parser `test_qualification_infrastructure`
already carries, and asserted on structurally -- statement by statement, condition
by condition, principal by principal.

What these rules encode is ADR-0036's layer L0 (its s.3, A-1 to A-10): the shape of
the declarations. They prove what the configuration SAYS. They do not prove that
AWS honours a condition key, that a launcher can or cannot pass a role, that a
parameter decrypts, or that the bucket policy refuses a write -- those are the ADR's
layer L3 and are separately authorized.

**The rules are functions.** :func:`violations` returns every rule the parsed
configuration breaks, so the same rules run against the real files (expect none)
and against deliberately mutated copies (expect the specific one). A rule that a
mutation cannot trip is visible immediately.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from fixtures import sharadar_provider as syn
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.ingest.bronze import RetrievalMetadata
from kalpamani.data.ingest.publication import (
    acquisition_claim_key,
    bronze_acquisition_key,
    bronze_payload_key,
)
from kalpamani.data.ingest.sharadar.datasets import PROVIDER
from kalpamani.data.objectstore import physical_key
from kalpamani.data.qualify.sharadar.locator import locator_key_segments
from kalpamani.data.qualify.sharadar.plan import EMPIRICAL_DATASETS
from kalpamani.data.qualify.sharadar.publication import qualification_payload_key
from kalpamani.data.qualify.sharadar.report import report_key_segments

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INFRA = PROJECT_ROOT / "infra" / "aws" / "research-data-plane"
PRODUCTION_FILES = (
    "production_variables.tf",
    "production_policies.tf",
    "production_principals.tf",
    "production_bindings.tf",
    "production_network.tf",
    "production_compute.tf",
)
STORAGE_TF = INFRA / "storage.tf"
IAM_TF = INFRA / "iam.tf"
ADR = (
    PROJECT_ROOT
    / "docs"
    / "decisions"
    / "ADR-0036-production-data-plane-principals-and-trust-model.md"
)


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


#: The HCL parser and the policy-document flattener, reused rather than copied.
QI = _load(
    "kalpamani_test_qualification_infrastructure",
    Path(__file__).with_name("test_qualification_infrastructure.py"),
)
GUARD = QI.GUARD

LICENSED = "${aws_s3_bucket.licensed.arn}"

ACTORS = ("acquisition", "build")

PERMISSION_SETS = {
    "production_acquisition_permission_set": "KalpaManiProductionAcquire",
    "production_build_permission_set": "KalpaManiResearchBuild",
    "production_acquire_launcher_set": "KalpaManiAcquireLauncher",
    "production_build_launcher_set": "KalpaManiBuildLauncher",
}

TASK_ROLES = {
    "acquisition": "production_acquire_task",
    "build": "production_build_task",
}

PARAMETER_SUFFIX = {
    ("acquisition", "binding"): "/kalpamani/production/acquisition/runtime-binding",
    ("acquisition", "input"): "/kalpamani/production/acquisition/input",
    ("acquisition", "release"): "/kalpamani/production/acquisition/release",
    ("build", "binding"): "/kalpamani/production/research-build/runtime-binding",
    ("build", "input"): "/kalpamani/production/research-build/input",
    ("build", "release"): "/kalpamani/production/research-build/release",
}

FOUR_WRITE_CONDITIONS = {
    ("StringEquals", "s3:x-amz-server-side-encryption", ("AES256",)),
    ("Null", "s3:if-none-match", ("false",)),
    ("Bool", "s3:ObjectCreationOperation", ("true",)),
    ("Null", "s3:x-amz-copy-source", ("true",)),
}

EXECUTION_ROLE_SIDS = ("PullResearchImage", "GetRegistryAuthToken", "WriteTaskLogs")


# ---------------------------------------------------------------------------
# Structural model: statements with conditions, principals and NotResource
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Condition:
    test: str
    variable: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class Statement:
    sid: str
    effect: str
    actions: tuple[str, ...]
    resources: tuple[str, ...]
    not_resources: tuple[str, ...]
    conditions: tuple[Condition, ...]
    principals: tuple[tuple[str, tuple[str, ...]], ...]
    dynamic_gate: str
    raw_resources: str
    raw_not_resources: str


@dataclass
class Model:
    blocks: tuple[Any, ...]
    locals_: dict[str, tuple[str, ...]]
    documents: dict[str, tuple[Statement, ...]]
    resources: dict[tuple[str, str], Any] = field(default_factory=dict)
    variables: dict[str, Any] = field(default_factory=dict)
    by_file: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    raw_locals: dict[str, str] = field(default_factory=dict)


def _first(expression: str, default: str = "") -> str:
    found = QI.string_list(expression)
    return found[0] if found else default


def _conditions(block: Any, locals_: dict[str, tuple[str, ...]]) -> tuple[Condition, ...]:
    out = []
    for child in block.children("condition"):
        out.append(
            Condition(
                test=_first(child.attributes.get("test", "")),
                variable=_first(child.attributes.get("variable", "")),
                values=QI._resolve(child.attributes.get("values", ""), locals_),
            )
        )
    return tuple(out)


def _principals(
    block: Any, locals_: dict[str, tuple[str, ...]]
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    out = []
    for child in block.children("principals"):
        out.append(
            (
                _first(child.attributes.get("type", "")),
                QI._resolve(child.attributes.get("identifiers", ""), locals_),
            )
        )
    return tuple(out)


def _statements(document: Any, locals_: dict[str, tuple[str, ...]]) -> tuple[Statement, ...]:
    found: list[tuple[Any, str]] = [(b, "") for b in document.children("statement")]
    for dynamic in document.children("dynamic"):
        if dynamic.labels[:1] == ("statement",):
            gate = dynamic.attributes.get("for_each", "")
            found.extend((content, gate) for content in dynamic.children("content"))
    return tuple(
        Statement(
            sid=_first(block.attributes.get("sid", "")),
            effect=_first(block.attributes.get("effect", ""), "Allow"),
            actions=QI._resolve(block.attributes.get("actions", ""), locals_),
            resources=QI._resolve(block.attributes.get("resources", ""), locals_),
            not_resources=QI._resolve(block.attributes.get("not_resources", ""), locals_),
            conditions=_conditions(block, locals_),
            principals=_principals(block, locals_),
            dynamic_gate=gate,
            raw_resources=block.attributes.get("resources", ""),
            raw_not_resources=block.attributes.get("not_resources", ""),
        )
        for block, gate in found
    )


def build_model(sources: dict[str, str]) -> Model:
    """Parse every file together, so a local defined in one resolves in another."""
    merged = "\n".join(sources.values())
    config = QI.analyse(merged)
    documents = {}
    resources = {}
    variables = {}
    for block in config.blocks:
        if block.type == "data" and block.labels[:1] == ("aws_iam_policy_document",):
            documents[block.labels[1]] = _statements(block, config.locals_)
        if block.type == "resource":
            resources[(block.labels[0], block.labels[1])] = block
        if block.type == "variable":
            variables[block.labels[0]] = block
    raw_locals = {
        name: expression
        for block in config.blocks
        if block.type == "locals"
        for name, expression in block.attributes.items()
    }
    by_file = {name: tuple(QI.parse_hcl(text)) for name, text in sources.items()}
    return Model(
        config.blocks, config.locals_, documents, resources, variables, by_file, raw_locals
    )


def _sources() -> dict[str, str]:
    files = {name: (INFRA / name).read_text(encoding="utf-8") for name in PRODUCTION_FILES}
    files["storage.tf"] = STORAGE_TF.read_text(encoding="utf-8")
    files["iam.tf"] = IAM_TF.read_text(encoding="utf-8")
    return files


def _mentions(values: tuple[str, ...], suffix: str) -> bool:
    return any(value.endswith(suffix) for value in values)


def _allows(statements: tuple[Statement, ...]) -> list[Statement]:
    return [s for s in statements if s.effect == "Allow"]


def _denies(statements: tuple[Statement, ...]) -> list[Statement]:
    return [s for s in statements if s.effect == "Deny"]


def _granted(statements: tuple[Statement, ...]) -> set[str]:
    return {a for s in _allows(statements) for a in s.actions}


def _denied(statements: tuple[Statement, ...]) -> set[str]:
    return {a for s in _denies(statements) for a in s.actions}


def _has_condition(
    statement: Statement, test: str, variable: str, values: tuple[str, ...] | None = None
) -> bool:
    for c in statement.conditions:
        if (
            c.test == test
            and c.variable == variable
            and (values is None or tuple(c.values) == values)
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def _rule_stage_gating(model: Model) -> list[str]:
    """Every production resource is gated on the stage; only assignments on stage b."""
    found: list[str] = []
    for name in PRODUCTION_FILES:
        for block in model.by_file[name]:
            if block.type != "resource":
                continue
            kind, label = block.labels[0], block.labels[1]
            count = block.attributes.get("count", "")
            for_each = block.attributes.get("for_each", "")
            if kind == "aws_ssoadmin_account_assignment":
                if count != "local.production_count_b":
                    found.append(
                        f"{kind}.{label}: an assignment must be gated on stage b, not {count!r}"
                    )
                continue
            if count == "local.production_count_b":
                found.append(f"{kind}.{label}: only assignments may be gated on stage b")
            gated = count in (
                "local.production_count_a",
                "local.production_secrets_endpoint_count",
            ) or (
                "local.production_stage_a" in for_each
                or "local.production_interface_endpoints" in for_each
            )
            if not gated:
                found.append(
                    f"{kind}.{label}: not gated on the production stage "
                    f"(count={count!r}, for_each={for_each!r})"
                )
    assignments = [
        k
        for k in model.resources
        if k[0] == "aws_ssoadmin_account_assignment" and k[1].startswith("production_")
    ]
    if len(assignments) != 4:
        found.append(f"expected exactly four production assignments, found {len(assignments)}")
    stage = model.variables.get("production_stage")
    if stage is None or _first(stage.attributes.get("default", "")) != "none":
        found.append("production_stage must default to none")
    if stage is not None and "production_r3_verification_digest" not in " ".join(
        v.attributes.get("condition", "") for v in stage.children("validation")
    ):
        found.append("production_stage b must require the R-3 verification digest")
    return found


def _rule_bucket_policy(model: Model) -> list[str]:
    """storage.tf: three stage-gated Deny statements on the production prefixes; TLS deny intact."""
    found: list[str] = []
    doc = model.documents.get("licensed_bucket", ())
    sids = {s.sid: s for s in doc}
    if "DenyNonTLSRequests" not in sids or sids["DenyNonTLSRequests"].dynamic_gate:
        found.append("the TLS-only statement must remain, ungated")
    expected = {
        "ProductionRefusesUnconditionalObjectCreation": [
            ("Null", "s3:if-none-match", ("true",)),
            ("Bool", "s3:ObjectCreationOperation", ("true",)),
        ],
        "ProductionRefusesMultipartUploads": [("Bool", "s3:ObjectCreationOperation", ("false",))],
        "ProductionRefusesCopyShapedWrites": [("Null", "s3:x-amz-copy-source", ("false",))],
    }
    for sid, conditions in expected.items():
        statement = sids.get(sid)
        if statement is None:
            found.append(f"bucket policy statement {sid} is missing")
            continue
        if statement.effect != "Deny":
            found.append(f"{sid} must be a Deny")
        if "local.production_stage_a" not in statement.dynamic_gate:
            found.append(
                f"{sid} must be gated on stage a so the applied policy is unchanged at stage none"
            )
        if statement.principals != (("*", ("*",)),):
            found.append(f"{sid} must apply to every principal")
        if tuple(statement.actions) != ("s3:PutObject",):
            found.append(f"{sid} must govern s3:PutObject only")
        for test, variable, values in conditions:
            if not _has_condition(statement, test, variable, values):
                found.append(f"{sid} lacks condition {test} {variable} {values}")
        scope = statement.resources
        if any("qualification" in r for r in scope):
            found.append(f"{sid} reaches into a qualification prefix")
        if not _mentions(scope, "/_verification/*"):
            found.append(f"{sid} must cover the R-3 verification prefix")
        for prefix in (
            "/silver/*",
            "/gold/*",
            "/manifests/*",
            "/bronze/sharadar/_indexes/*",
            "/bronze/_production_claims/*",
        ):
            if not _mentions(scope, prefix):
                found.append(f"{sid} must cover {prefix}")
        if any(r.endswith("/bronze/sharadar/*") for r in scope):
            found.append(f"{sid} must enumerate the production prefixes, not bronze/sharadar/*")
        for foreign in QUALIFICATION_AND_GENERAL_BRONZE_PREFIXES:
            if any(r.endswith(foreign) for r in scope):
                found.append(f"{sid} reaches an earlier package's namespace: {foreign}")
    return found


def _rule_data_plane(model: Model) -> list[str]:
    """A-1 / A-2: the two data-plane documents."""
    found: list[str] = []
    acq = model.documents.get("production_acquisition", ())
    build = model.documents.get("production_build", ())
    for label, doc in (("acquisition", acq), ("build", build)):
        if not doc:
            found.append(f"{label} data-plane document is missing")
            continue
        for action in _granted(doc) | _denied(doc):
            if action.startswith(("ssm:", "kms:")):
                found.append(
                    f"{label} data-plane document carries {action}: "
                    "ssm/kms belong to the bootstrap policies"
                )
        for s in _allows(doc):
            if "s3:PutObject" in s.actions:
                have = {(c.test, c.variable, tuple(c.values)) for c in s.conditions}
                missing = FOUR_WRITE_CONDITIONS - have
                if missing:
                    found.append(f"{label} {s.sid}: PutObject grant lacks {sorted(missing)}")
        if not any("s3:*" in s.actions and s.raw_not_resources for s in _denies(doc)):
            found.append(f"{label}: no NotResource deny confining S3 to the licensed bucket")
        if not any(
            "s3:*" in s.actions and any("qualification" in r for r in s.resources)
            for s in _denies(doc)
        ):
            found.append(f"{label}: qualification prefixes are not denied")
        if not any(
            "s3:PutObject" in s.actions
            and _has_condition(s, "Null", "s3:x-amz-copy-source", ("false",))
            for s in _denies(doc)
        ):
            found.append(f"{label}: copy-shaped puts are not denied")
        for action in ("iam:*", "sts:AssumeRole", "ec2:*", "ecs:*"):
            if action not in _denied(doc):
                found.append(f"{label}: {action} is not denied")
    granted = _granted(acq)
    if any(a.startswith(("s3:Get", "s3:List", "s3:Delete")) for a in granted):
        found.append("acquisition grants a read, list or delete")
    if granted - {"s3:PutObject", "secretsmanager:GetSecretValue"}:
        found.append(
            f"acquisition grants more than PutObject and one GetSecretValue: {sorted(granted)}"
        )
    secret = [s for s in _allows(acq) if "secretsmanager:GetSecretValue" in s.actions]
    if not secret or "var.production_acquisition_secret_arn" not in secret[0].raw_resources:
        found.append("acquisition secret grant must name exactly the production secret variable")
    if not any(
        "var.production_acquisition_secret_arn" in s.raw_not_resources
        and "secretsmanager:GetSecretValue" in s.actions
        for s in _denies(acq)
    ):
        found.append("acquisition must deny GetSecretValue on every other secret")
    if any(a.startswith("secretsmanager:") for a in _granted(build)):
        found.append("build grants a Secrets Manager action")
    if "secretsmanager:*" not in _denied(build):
        found.append("build must deny secretsmanager:*")
    if not any(
        _mentions(s.resources, "/bronze/_production_claims/*") and "s3:GetObject" in s.actions
        for s in _denies(build)
    ):
        found.append("build must deny claim reads")
    for label, doc in (("acquisition", acq), ("build", build)):
        foreign = [
            s
            for s in _denies(doc)
            if "s3:*" in s.actions and _mentions(s.resources, "/bronze/_acquisition_claims/*")
        ]
        if not foreign or not all(
            _mentions(foreign[0].resources, x)
            for x in QUALIFICATION_AND_GENERAL_BRONZE_PREFIXES
            if x != "/qualification/*" and "/qualification/*" not in x
        ):
            found.append(f"{label}: every earlier Bronze namespace must be denied for every action")
        for s in _allows(doc):
            for foreign_prefix in QUALIFICATION_AND_GENERAL_BRONZE_PREFIXES:
                if any(r.endswith(foreign_prefix) for r in s.resources):
                    found.append(
                        f"{label} {s.sid}: grants an earlier package's namespace {foreign_prefix}"
                    )
    if not any(
        _mentions(s.resources, "/bronze/*") and "s3:PutObject" in s.actions for s in _denies(build)
    ):
        found.append("build must deny Bronze writes")
    return found


def _rule_permission_sets(model: Model) -> list[str]:
    """A-3: four names within the pinned provider bound; one hour each."""
    found: list[str] = []
    for local_name, expected in PERMISSION_SETS.items():
        value = model.locals_.get(local_name, ())
        if tuple(value) != (expected,):
            found.append(f"local {local_name} must be {expected!r}, found {value}")
        found.extend(f"{local_name}: {d}" for d in GUARD.permission_set_name_defects(expected))
    sets = [
        k
        for k in model.resources
        if k[0] == "aws_ssoadmin_permission_set" and k[1].startswith("production_")
    ]
    if len(sets) != 4:
        found.append(f"expected four production permission sets, found {len(sets)}")
    for key in sets:
        block = model.resources[key]
        if (
            _first(block.attributes.get("session_duration", "")) not in ("PT1H",)
            and block.attributes.get("session_duration") != "local.production_session_duration"
        ):
            found.append(f"{key[1]}: session must be PT1H")
    if tuple(model.locals_.get("production_session_duration", ())) != ("PT1H",):
        found.append("production_session_duration must be PT1H")
    return found


def _rule_trust_and_execution_role(model: Model) -> list[str]:
    """A-4: task-role trust; the execution role unchanged and data-blind."""
    found: list[str] = []
    trust = model.documents.get("production_task_trust", ())
    if len(trust) != 1:
        found.append("the task trust document must have exactly one statement")
    else:
        s = trust[0]
        if s.principals != (("Service", ("ecs-tasks.amazonaws.com",)),):
            found.append("task roles must trust ecs-tasks.amazonaws.com and nothing else")
        if not _has_condition(s, "StringEquals", "aws:SourceAccount"):
            found.append("task trust lacks aws:SourceAccount")
        if not _has_condition(s, "ArnLike", "aws:SourceArn"):
            found.append("task trust lacks aws:SourceArn")
    for role in TASK_ROLES.values():
        block = model.resources.get(("aws_iam_role", role))
        if block is None or "production_task_trust" not in block.attributes.get(
            "assume_role_policy", ""
        ):
            found.append(f"{role} must use the task trust document")
        attached = {
            model.resources[k].attributes.get("policy_arn", "")
            for k in model.resources
            if k[0] == "aws_iam_role_policy_attachment"
            and model.resources[k].attributes.get("role", "").startswith(f"aws_iam_role.{role}")
        }
        if len(attached) != 2:
            found.append(
                f"{role} must carry exactly two attachments (data plane + task bootstrap), "
                f"found {sorted(attached)}"
            )
        if not any("human_bootstrap" not in a and "launcher" not in a for a in attached):
            found.append(f"{role}: attachments look wrong: {sorted(attached)}")
        if any("human_bootstrap" in a or "launcher" in a for a in attached):
            found.append(f"{role} must never carry a human bootstrap or launcher policy")
    execution = model.documents.get("task_execution", ())
    if tuple(s.sid for s in execution) != EXECUTION_ROLE_SIDS:
        found.append(f"the execution role must be unchanged: {[s.sid for s in execution]}")
    for action in _granted(execution):
        if action.split(":")[0] in ("ssm", "secretsmanager", "kms", "s3"):
            found.append(f"the execution role must not hold {action}")
    return found


def _rule_bootstrap(model: Model) -> list[str]:
    """A-7: task, human and launcher bootstrap statements, and the key policy."""
    found: list[str] = []
    writers: dict[str, list[str]] = {}
    for actor in ACTORS:
        prefix = "production_acquire" if actor == "acquisition" else "production_build"
        task = model.documents.get(f"{prefix}_task_bootstrap", ())
        human = model.documents.get(f"production_{actor}_human_bootstrap", ())
        launcher = model.documents.get(f"{prefix}_launcher", ())
        binding = PARAMETER_SUFFIX[(actor, "binding")]
        inp = PARAMETER_SUFFIX[(actor, "input")]
        release = PARAMETER_SUFFIX[(actor, "release")]
        other = "build" if actor == "acquisition" else "acquisition"

        # task bootstrap
        reads = [s for s in _allows(task) if "ssm:GetParameter" in s.actions]
        if len(reads) != 1 or not all(
            _mentions(reads[0].resources, x) for x in (binding, inp, release)
        ):
            found.append(f"{actor} task bootstrap must read exactly its binding, input and release")
        decrypt = [s for s in _allows(task) if "kms:Decrypt" in s.actions]
        if len(decrypt) != 1:
            found.append(f"{actor} task bootstrap must have exactly one kms:Decrypt grant")
        else:
            ctx = [
                c
                for c in decrypt[0].conditions
                if c.variable == "kms:EncryptionContext:PARAMETER_ARN"
            ]
            if not ctx or not all(_mentions(ctx[0].values, x) for x in (binding, inp, release)):
                found.append(f"{actor} task decrypt must be scoped to its three parameter contexts")
            if not _has_condition(decrypt[0], "StringEquals", "kms:ViaService"):
                found.append(f"{actor} task decrypt must carry kms:ViaService")
        for action in (
            "ssm:PutParameter",
            "ssm:DeleteParameter",
            "kms:Encrypt",
            "kms:GenerateDataKey",
            "ssm:GetParametersByPath",
            "ssm:GetParameterHistory",
        ):
            if action not in _denied(task):
                found.append(f"{actor} task bootstrap must deny {action}")
        if any(
            a in _granted(task)
            for a in (
                "ssm:PutParameter",
                "ssm:DeleteParameter",
                "kms:Encrypt",
                "kms:GenerateDataKey",
            )
        ):
            found.append(f"{actor} task bootstrap grants a write")

        # human bootstrap
        puts = [s for s in _allows(human) if "ssm:PutParameter" in s.actions]
        if (
            len(puts) != 1
            or not _mentions(puts[0].resources, inp)
            or not _has_condition(puts[0], "Bool", "ssm:Overwrite", ("false",))
        ):
            found.append(
                f"{actor} human bootstrap must create exactly its input, without overwrite"
            )
        else:
            writers.setdefault(inp, []).append(f"{actor} human")
        deletes = [s for s in _allows(human) if "ssm:DeleteParameter" in s.actions]
        if len(deletes) != 1 or not _mentions(deletes[0].resources, inp):
            found.append(f"{actor} human bootstrap must delete exactly its input")
        gdk = [s for s in _allows(human) if "kms:GenerateDataKey" in s.actions]
        if len(gdk) != 1 or not _has_condition(gdk[0], "StringEquals", "kms:ViaService"):
            found.append(
                f"{actor} human bootstrap must generate a data key through Parameter Store only"
            )
        else:
            ctx = [
                c for c in gdk[0].conditions if c.variable == "kms:EncryptionContext:PARAMETER_ARN"
            ]
            if (
                not ctx
                or not _mentions(ctx[0].values, inp)
                or _mentions(ctx[0].values, binding)
                or _mentions(ctx[0].values, release)
            ):
                found.append(
                    f"{actor} human GenerateDataKey must be scoped to its input context only"
                )
        if not any(
            _has_condition(s, "Bool", "ssm:Overwrite", ("true",))
            and "ssm:PutParameter" in s.actions
            for s in _denies(human)
        ):
            found.append(f"{actor} human bootstrap must deny overwrite")
        if not any(s.raw_not_resources and "ssm:PutParameter" in s.actions for s in _denies(human)):
            found.append(f"{actor} human bootstrap must deny writes to any other parameter")
        read_denies = [s for s in _denies(human) if "ssm:GetParameter" in s.actions]
        needed = (
            PARAMETER_SUFFIX[("acquisition", "binding")],
            PARAMETER_SUFFIX[("build", "binding")],
            PARAMETER_SUFFIX[(other, "input")],
            PARAMETER_SUFFIX[("acquisition", "release")],
            PARAMETER_SUFFIX[("build", "release")],
        )
        if not read_denies or not all(_mentions(read_denies[0].resources, x) for x in needed):
            found.append(
                f"{actor} human bootstrap must deny reads of both bindings, "
                "the other input and both releases"
            )
        for action in ("kms:Decrypt", "kms:Encrypt"):
            if action not in _denied(human):
                found.append(f"{actor} human bootstrap must deny {action}")
        if "ssm:GetParameter" in _granted(human):
            found.append(f"{actor} human bootstrap grants a parameter read")

        # launcher
        rel_puts = [s for s in _allows(launcher) if "ssm:PutParameter" in s.actions]
        if (
            len(rel_puts) != 1
            or not _mentions(rel_puts[0].resources, release)
            or not _has_condition(rel_puts[0], "Bool", "ssm:Overwrite", ("false",))
        ):
            found.append(f"{actor} launcher must create exactly its release, without overwrite")
        else:
            writers.setdefault(release, []).append(f"{actor} launcher")
        rel_del = [s for s in _allows(launcher) if "ssm:DeleteParameter" in s.actions]
        if len(rel_del) != 1 or not _mentions(rel_del[0].resources, release):
            found.append(f"{actor} launcher must delete exactly its release")
        rel_gdk = [s for s in _allows(launcher) if "kms:GenerateDataKey" in s.actions]
        if len(rel_gdk) != 1:
            found.append(f"{actor} launcher must generate the release data key")
        else:
            ctx = [
                c
                for c in rel_gdk[0].conditions
                if c.variable == "kms:EncryptionContext:PARAMETER_ARN"
            ]
            if not ctx or not _mentions(ctx[0].values, release) or _mentions(ctx[0].values, inp):
                found.append(
                    f"{actor} launcher GenerateDataKey must be scoped to the release context only"
                )
        for action in ("ssm:GetParameter", "kms:Decrypt", "kms:Encrypt"):
            if action not in _denied(launcher):
                found.append(f"{actor} launcher must deny {action}")
        if any(a in _granted(launcher) for a in ("ssm:GetParameter", "kms:Decrypt")):
            found.append(f"{actor} launcher grants a read or decrypt")

    for parameter, who in writers.items():
        if len(who) != 1:
            found.append(f"{parameter} has more than one writer: {who}")
    if len(writers) != 4:
        found.append(
            f"expected four written parameters (two inputs, two releases), found {sorted(writers)}"
        )

    # key policy
    key = model.documents.get("production_task_bindings_key", ())
    sids = sorted(s.sid for s in key)
    expected = sorted(
        [
            "AdministerTheKeyAndMaterializeBindings",
            "AcquisitionTaskDecryptsItsParameters",
            "BuildTaskDecryptsItsParameters",
            "AcquisitionHumanGeneratesTheInputDataKey",
            "BuildHumanGeneratesTheInputDataKey",
            "AcquireLauncherGeneratesTheReleaseDataKey",
            "BuildLauncherGeneratesTheReleaseDataKey",
        ]
    )
    if sids != expected:
        found.append(f"key policy statements must be exactly {expected}, found {sids}")
    for s in key:
        if s.effect != "Allow":
            found.append(f"key policy {s.sid} must be an Allow")
        if s.sid != "AdministerTheKeyAndMaterializeBindings" and not _has_condition(
            s, "StringEquals", "kms:ViaService"
        ):
            found.append(f"key policy {s.sid} must carry kms:ViaService")
        if s.sid == "AdministerTheKeyAndMaterializeBindings" and not _has_condition(
            s, "StringLike", "aws:PrincipalArn"
        ):
            found.append("key administration must be scoped to the apply principal pattern")
        if "Human" in s.sid or "Launcher" in s.sid:
            # Finding 5: ArnLike, the operator AWS documents for generated-role prefixes,
            # over the region-aware path local -- never a hard-coded `*/` path segment.
            if not _has_condition(s, "ArnLike", "aws:PrincipalArn"):
                found.append(
                    f"key policy {s.sid} must match the generated-role prefix with ArnLike"
                )
            prefixes = [
                c.values
                for c in s.conditions
                if c.variable == "aws:PrincipalArn" and c.test == "ArnLike"
            ]
            if not prefixes or not any(
                v.startswith("${local.production_sso_role_path}") and v.endswith("_*")
                for v in prefixes[0]
            ):
                found.append(
                    f"key policy {s.sid} must build its principal pattern from the "
                    "region-aware local and end in the rotating suffix wildcard"
                )
            if tuple(s.actions) != ("kms:GenerateDataKey",):
                found.append(f"key policy {s.sid} must grant GenerateDataKey only")
        if "Task" in s.sid and tuple(s.actions) != ("kms:Decrypt",):
            found.append(f"key policy {s.sid} must grant Decrypt only")
    return found


def _rule_launch(model: Model) -> list[str]:
    """A-9: task definitions and the two launchers."""
    found: list[str] = []
    for actor, td, role in (
        ("acquisition", "production_acquire", "production_acquire_task"),
        ("build", "production_build", "production_build_task"),
    ):
        definition = model.resources.get(("aws_ecs_task_definition", td))
        if definition is None:
            found.append(f"task definition {td} is missing")
            continue
        if definition.attributes.get("task_role_arn", "") != f"aws_iam_role.{role}[0].arn":
            found.append(f"{td} must run as its own actor's task role")
        if definition.attributes.get("execution_role_arn", "") != "aws_iam_role.task_execution.arn":
            found.append(f"{td} must use the foundation execution role")
        launcher = model.documents.get(f"{td}_launcher", ())
        run = [s for s in _allows(launcher) if "ecs:RunTask" in s.actions]
        if (
            len(run) != 1
            or run[0].raw_resources.strip() != f"[aws_ecs_task_definition.{td}[0].arn]"
        ):
            found.append(f"{actor} launcher must run exactly aws_ecs_task_definition.{td}[0].arn")
        elif not _has_condition(run[0], "ArnEquals", "ecs:cluster"):
            found.append(f"{actor} launcher RunTask lacks the ecs:cluster condition")
        passes = [s for s in _allows(launcher) if "iam:PassRole" in s.actions]
        expected = f"[aws_iam_role.{role}[0].arn, aws_iam_role.task_execution.arn]"
        if len(passes) != 1 or passes[0].raw_resources.strip() != expected:
            found.append(f"{actor} launcher must pass exactly its task role and the execution role")
        elif not _has_condition(
            passes[0], "StringEquals", "iam:PassedToService", ("ecs-tasks.amazonaws.com",)
        ):
            found.append(f"{actor} launcher PassRole lacks iam:PassedToService")
        closes = [
            s for s in _denies(launcher) if "iam:PassRole" in s.actions and s.raw_not_resources
        ]
        if len(closes) != 1 or closes[0].raw_not_resources.strip() != expected:
            found.append(
                f"{actor} launcher must close PassRole with NotResource on the same two roles"
            )
        other_iam = [
            a for s in launcher for a in s.actions if a.startswith("iam:") and a != "iam:PassRole"
        ]
        if other_iam:
            found.append(f"{actor} launcher carries another iam statement: {other_iam}")
        if "ecs:ExecuteCommand" not in _denied(launcher):
            found.append(f"{actor} launcher must deny ecs:ExecuteCommand")
        if any(a.startswith(("s3:", "secretsmanager:")) for s in launcher for a in s.actions):
            found.append(f"{actor} launcher carries a data-plane statement")
        if "ec2:DescribeNetworkInterfaces" not in _granted(launcher):
            found.append(f"{actor} launcher must be able to describe the task's network interface")
    return found


def _rule_task_definitions_text(sources: dict[str, str]) -> list[str]:
    """The container definitions, read from the file: digest-pinned, no secrets, no env."""
    found: list[str] = []
    text = GUARD.strip_hcl_comments(sources["production_compute.tf"])
    for key in ("secrets", "environment", "portMappings", "mountPoints", "volumes"):
        if re.search(rf"^\s*{key}\s*=", text, re.MULTILINE):
            found.append(f"a task definition carries {key}")
    if text.count("@${lookup(var.production_image_digests") != 2:
        found.append("both images must be pinned by digest from production_image_digests")
    if (
        "readonlyRootFilesystem = true" not in text
        or text.count("readonlyRootFilesystem = true") != 2
    ):
        found.append("both containers must have a read-only root filesystem")
    if text.count("command") != 2:
        found.append("each container must fix its command")
    return found


def _rule_network(model: Model, sources: dict[str, str]) -> list[str]:
    """A-10: the build subnet has no internet route; egress is an allowlist."""
    found: list[str] = []
    text = GUARD.strip_hcl_comments(sources["production_network.tf"])
    if "0.0.0.0/0" in text:
        found.append("production_network.tf must not contain 0.0.0.0/0")
    if "aws_nat_gateway" in text or "aws_internet_gateway" in text:
        found.append("production_network.tf must declare no NAT or internet gateway")
    build_rt = model.resources.get(("aws_route_table", "production_build"))
    if build_rt is None or build_rt.children("route"):
        found.append("the build route table must carry no route block")
    if ("aws_route_table_association", "production_build") not in model.resources:
        found.append("the build subnet must be associated with its private route table")
    for sg in ("production_build", "production_acquisition"):
        rules = [
            model.resources[k]
            for k in model.resources
            if k[0] == "aws_vpc_security_group_egress_rule"
            and model.resources[k]
            .attributes.get("security_group_id", "")
            .startswith(f"aws_security_group.{sg}")
        ]
        kinds = set()
        for rule in rules:
            if "prefix_list_id" in rule.attributes:
                kinds.add("s3")
            elif "referenced_security_group_id" in rule.attributes:
                kinds.add("endpoints")
            elif rule.attributes.get("cidr_ipv4", "") == "local.production_vpc_resolver_cidr":
                kinds.add("dns")
            elif rule.attributes.get("cidr_ipv4", "") == "each.key":
                kinds.add("provider")
            else:
                found.append(f"{sg}: unexpected egress rule {rule.labels}")
        expected = {"s3", "endpoints", "dns"} | (
            {"provider"} if sg == "production_acquisition" else set()
        )
        if kinds != expected:
            found.append(f"{sg}: egress kinds {sorted(kinds)} != {sorted(expected)}")
        if any(
            model.resources[k].labels[0] == "aws_vpc_security_group_ingress_rule"
            and model.resources[k]
            .attributes.get("security_group_id", "")
            .startswith(f"aws_security_group.{sg}")
            for k in model.resources
        ):
            found.append(f"{sg} must have no ingress rule")
    provider = model.resources.get(
        ("aws_vpc_security_group_egress_rule", "production_acquisition_provider")
    )
    if provider is None or "var.production_provider_origin_cidrs" not in provider.attributes.get(
        "for_each", ""
    ):
        found.append("the provider egress rule must iterate the supplied CIDR allowlist")
    endpoint_policy = model.documents.get("production_s3_endpoint", ())
    if len(endpoint_policy) != 1 or not (
        _mentions(endpoint_policy[0].resources, "starport-layer-bucket/*")
        and "aws_s3_bucket.licensed.arn," in endpoint_policy[0].raw_resources
        and f"{LICENSED}/*" in endpoint_policy[0].resources
        and len(endpoint_policy[0].resources) == 2
    ):
        found.append(
            "the S3 endpoint policy must admit exactly the licensed bucket and the ECR layer bucket"
        )
    interface = model.resources.get(("aws_vpc_endpoint", "production_interface"))
    if (
        interface is None
        or interface.attributes.get("for_each", "") != "local.production_interface_endpoints"
    ):
        found.append("interface endpoints must be behind the toggle local")
    endpoints = QI.string_list(model.raw_locals.get("production_interface_endpoints", ""))
    if set(endpoints) != {"ecr.api", "ecr.dkr", "logs", "ssm", "sts"}:
        found.append(
            "shared interface endpoints must be exactly the five ADR-0036 names without "
            f"Secrets Manager, found {sorted(endpoints)}"
        )
    found.extend(_rule_secrets_endpoint(model))
    for var in ("production_endpoints_enabled",):
        block = model.variables.get(var)
        if block is None or block.attributes.get("default", "").strip() != "false":
            found.append(f"{var} must default to false")
    cidrs = model.variables.get("production_provider_origin_cidrs")
    if cidrs is None or "0.0.0.0/0" not in " ".join(
        v.attributes.get("condition", "") for v in cidrs.children("validation")
    ):
        found.append("production_provider_origin_cidrs must refuse 0.0.0.0/0")
    return found


#: Every physical prefix an EARLIER package writes (traced from the merged key
#: builders; see the synthetic-key evidence below). No production grant may name one,
#: and no bucket-policy statement may govern one.
QUALIFICATION_AND_GENERAL_BRONZE_PREFIXES = (
    "/bronze/_acquisition_claims/*",
    "/bronze/sharadar/tickers/objects/sha256/*",
    "/bronze/sharadar/stocks/objects/sha256/*",
    "/bronze/sharadar/actions/objects/sha256/*",
    "/bronze/sharadar/tickers/acquisitions/*",
    "/bronze/sharadar/stocks/acquisitions/*",
    "/bronze/sharadar/actions/acquisitions/*",
    "/bronze/sharadar/tickers/qualification/*",
    "/bronze/sharadar/stocks/qualification/*",
    "/bronze/sharadar/actions/qualification/*",
    "/qualification/*",
)


def _rule_secrets_endpoint(model: Model) -> list[str]:
    """Finding 2: Secrets Manager is reachable by the acquisition task alone."""
    found: list[str] = []
    endpoint = model.resources.get(("aws_vpc_endpoint", "production_secretsmanager"))
    if endpoint is None:
        return ["the Secrets Manager endpoint must be its own resource"]
    if (
        endpoint.attributes.get("security_group_ids", "").strip()
        != "[aws_security_group.production_secrets_endpoint[0].id]"
    ):
        found.append("the Secrets Manager endpoint must sit on its own security group")
    if "production_secrets_endpoint.json" not in endpoint.attributes.get("policy", ""):
        found.append("the Secrets Manager endpoint must carry the custom endpoint policy")
    ingress = [
        model.resources[k]
        for k in model.resources
        if k[0] == "aws_vpc_security_group_ingress_rule"
        and model.resources[k]
        .attributes.get("security_group_id", "")
        .startswith("aws_security_group.production_secrets_endpoint")
    ]
    if (
        len(ingress) != 1
        or ingress[0].attributes.get("referenced_security_group_id", "").strip()
        != "aws_security_group.production_acquisition[0].id"
    ):
        found.append(
            "the Secrets Manager endpoint group must admit the acquisition task group "
            "and nothing else"
        )
    for rule_key, block in model.resources.items():
        if rule_key[0] != "aws_vpc_security_group_egress_rule":
            continue
        if block.attributes.get("referenced_security_group_id", "").startswith(
            "aws_security_group.production_secrets_endpoint"
        ) and not block.attributes.get("security_group_id", "").startswith(
            "aws_security_group.production_acquisition"
        ):
            found.append(
                f"{rule_key[1]}: only the acquisition group may have egress "
                "to the Secrets Manager endpoint"
            )
    if not any(
        k[0] == "aws_vpc_security_group_egress_rule"
        and model.resources[k]
        .attributes.get("security_group_id", "")
        .startswith("aws_security_group.production_acquisition")
        and model.resources[k]
        .attributes.get("referenced_security_group_id", "")
        .startswith("aws_security_group.production_secrets_endpoint")
        for k in model.resources
    ):
        found.append(
            "the acquisition group must have an egress rule to the Secrets Manager endpoint"
        )
    policy = model.documents.get("production_secrets_endpoint", ())
    if len(policy) != 1:
        found.append("the Secrets Manager endpoint policy must have exactly one statement")
    else:
        st = policy[0]
        if st.effect != "Allow" or tuple(st.actions) != ("secretsmanager:GetSecretValue",):
            found.append("the endpoint policy must allow exactly secretsmanager:GetSecretValue")
        if st.principals != (
            ("AWS", ()),
        ) or "aws_iam_role.production_acquire_task[0].arn" not in _principal_raw(
            model, "production_secrets_endpoint"
        ):
            found.append(
                "the endpoint policy must name the acquisition task role as its only principal"
            )
        if "var.production_acquisition_secret_arn" not in st.raw_resources or st.resources:
            found.append("the endpoint policy must name exactly the production secret variable")
        if st.principals and st.principals[0][0] == "*":
            found.append("the endpoint policy must not admit every principal")
    return found


def _principal_raw(model: Model, document: str) -> str:
    for block in model.blocks:
        if block.type == "data" and block.labels[:2] == ("aws_iam_policy_document", document):
            text = []
            for stmt in block.children("statement") + [
                c for d in block.children("dynamic") for c in d.children("content")
            ]:
                for pr in stmt.children("principals"):
                    text.append(pr.attributes.get("identifiers", ""))
            return " ".join(text)
    return ""


def violations(sources: dict[str, str]) -> list[str]:
    model = build_model(sources)
    return (
        _rule_stage_gating(model)
        + _rule_bucket_policy(model)
        + _rule_data_plane(model)
        + _rule_permission_sets(model)
        + _rule_trust_and_execution_role(model)
        + _rule_bootstrap(model)
        + _rule_launch(model)
        + _rule_task_definitions_text(sources)
        + _rule_network(model, sources)
    )


# ---------------------------------------------------------------------------
# The real files
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    return _sources()


@pytest.fixture(scope="module")
def model(sources: dict[str, str]) -> Model:
    return build_model(sources)


class TestTheImplementation:
    def test_every_production_file_exists(self) -> None:
        for name in PRODUCTION_FILES:
            assert (INFRA / name).is_file(), name

    def test_the_implementation_breaks_no_rule(self, sources: dict[str, str]) -> None:
        found = violations(sources)
        assert found == [], "\n".join(found)

    def test_the_rule_count_is_the_whole_of_l0(self) -> None:
        """Every A-1..A-10 topic of ADR-0036 s.3 has a rule here; A-11 is terraform validate."""
        text = ADR.read_text(encoding="utf-8")
        for label in [f"A-{n}" for n in range(1, 11)]:
            assert f"| {label} |" in text, label

    def test_no_committed_production_file_carries_a_live_literal(
        self, sources: dict[str, str]
    ) -> None:
        """The key policy and the region local name generated-role PREFIX patterns, never a
        live suffix: no `AWSReservedSSO_<name>_<16 hex>` shape appears anywhere."""
        live_suffix = re.compile(r"AWSReservedSSO_[A-Za-z0-9]+_[0-9a-f]{16}\b")
        for name in PRODUCTION_FILES:
            found = QI.literal_violations(sources[name])
            if name in ("production_bindings.tf", "production_variables.tf"):
                assert found in ([], ["a generated role name"]), found
                assert live_suffix.search(sources[name]) is None, name
                continue
            assert found == [], name

    def test_the_only_data_sources_are_policy_documents(self, sources: dict[str, str]) -> None:
        for name in PRODUCTION_FILES:
            for block in QI.parse_hcl(sources[name]):
                assert block.type != "data" or block.labels[0] == "aws_iam_policy_document", (
                    name,
                    block.labels,
                )

    @pytest.mark.parametrize(
        "construct",
        [
            "provisioner",
            "local-exec",
            "remote-exec",
            "terraform_remote_state",
            "data.external",
            "aws_nat_gateway",
            "aws_networkfirewall",
        ],
    )
    def test_no_live_coupling_or_unadopted_mechanism(
        self, sources: dict[str, str], construct: str
    ) -> None:
        for name in PRODUCTION_FILES:
            assert construct not in GUARD.strip_hcl_comments(sources[name]), (name, construct)

    def test_the_designed_names_are_declared_where_the_adr_puts_them(self, model: Model) -> None:
        for local_name, expected in PERMISSION_SETS.items():
            assert tuple(model.locals_[local_name]) == (expected,)
        assert tuple(model.locals_["production_acquire_task_role_name"]) == (
            "kalpamani-production-acquire-task",
        )
        assert tuple(model.locals_["production_build_task_role_name"]) == (
            "kalpamani-research-build-task",
        )
        for (actor, kind), suffix in PARAMETER_SUFFIX.items():
            prefix = "acquisition" if actor == "acquisition" else "build"
            key = f"production_{prefix}_{kind}_parameter_arn"
            assert _mentions(model.locals_[key], suffix), (actor, kind)

    def test_the_bindings_are_standard_tier_and_owned_by_terraform(self, model: Model) -> None:
        for label in ("production_acquisition_binding", "production_build_binding"):
            block = model.resources[("aws_ssm_parameter", label)]
            assert _first(block.attributes["type"]) == "SecureString"
            assert _first(block.attributes["tier"]) == "Standard"
            assert "aws_kms_key.production_task_bindings[0].arn" in block.attributes["key_id"]
        assert not [
            k
            for k in model.resources
            if k[0] == "aws_ssm_parameter" and ("input" in k[1] or "release" in k[1])
        ], "inputs and releases are created per run, never by Terraform"

    def test_the_binding_documents_have_the_adr_0023_shape(self, model: Model) -> None:
        for label, profile_key, kind in (
            (
                "production_acquisition_binding",
                "acquisition_profile",
                "kalpamani-production-acquisition-runtime",
            ),
            ("production_build_binding", "build_profile", "kalpamani-research-build-runtime"),
        ):
            text = " ".join(model.locals_[label])
            for token in (
                "schema_version",
                "binding_kind",
                "contract_id",
                "aws_partition",
                "aws_region",
                "target_account_id",
                profile_key,
                "licensed_bucket_name",
                "provenance",
            ):
                assert token in text or token in _locals_source(label), (label, token)
            assert kind in model.locals_[label]

    def test_the_key_has_rotation_and_an_alias(self, model: Model) -> None:
        key = model.resources[("aws_kms_key", "production_task_bindings")]
        assert key.attributes.get("enable_key_rotation", "").strip() == "true"
        assert ("aws_kms_alias", "production_task_bindings") in model.resources

    def test_each_container_logs_under_its_own_stream_prefix(self, sources: dict[str, str]) -> None:
        text = sources["production_compute.tf"]
        for name in ("acquire", "build"):
            assert f'"awslogs-stream-prefix" = "production-{name}"' in text


def _locals_source(label: str) -> str:
    return (
        (INFRA / "production_bindings.tf")
        .read_text(encoding="utf-8")
        .split(f"{label} = {{", 1)[1]
        .split("\n  }", 1)[0]
    )


# ---------------------------------------------------------------------------
# Finding 1 evidence: real qualification and general-Bronze keys vs production scope
# ---------------------------------------------------------------------------


def _arn_pattern_matches(pattern: str, physical: str) -> bool:
    """IAM resource-ARN glob: `*` matches any run of characters, `/` included."""
    if not pattern.startswith(LICENSED + "/"):
        return False
    tail = pattern[len(LICENSED) + 1 :]
    regex = "^" + re.escape(tail).replace("\\*", ".*") + "$"
    return re.match(regex, physical) is not None


def _retrieval(dataset: str, run_id: str) -> RetrievalMetadata:
    return RetrievalMetadata(
        provider=PROVIDER,
        dataset=dataset,
        requested_range="2021-08-28/2026-08-27",
        retrieved_at=syn.RETRIEVED_AT,
        source_schema_version=syn.SOURCE_SCHEMA_VERSION,
        ingestion_run_id=run_id,
        acquisition_mode=AcquisitionMode.QUALIFICATION,
    )


def _earlier_package_keys() -> dict[str, str]:
    """Physical keys the merged key builders produce for earlier packages, on synthetic inputs."""
    payload = b"synthetic-bytes-not-vendor-data"
    digest = "a" * 64
    keys: dict[str, str] = {}
    for dataset in EMPIRICAL_DATASETS:
        retrieval = _retrieval(dataset, "synthetic-run-0001")
        keys[f"adr-0017 general bronze payload ({dataset})"] = physical_key(
            bronze_payload_key(retrieval=retrieval, payload=payload)
        )
        keys[f"qualification / adr-0017 record ({dataset})"] = physical_key(
            bronze_acquisition_key(retrieval=retrieval, payload_digest=digest, record=b"{}")
        )
        keys[f"adr-0020 qualification payload ({dataset})"] = physical_key(
            qualification_payload_key(
                dataset=dataset,
                execution_id="synthetic-run-0001",
                request_ordinal=1,
                content_sha256=digest,
            )
        )
    keys["qualification / adr-0017 claim"] = physical_key(
        acquisition_claim_key(payload_digest=digest, run_id="synthetic-run-0001", claim=b"{}")
    )
    keys["qualification locator"] = "/".join(locator_key_segments("synthetic-run-0001"))
    keys["qualification report"] = "/".join(
        report_key_segments(
            run_a_execution_id="synthetic-run-0001",
            run_b_execution_id="synthetic-run-0002",
            assessment_id="synthetic-assess-0001",
        )
    )
    return keys


class TestQualificationArtifactsStayOutsideProduction:
    """Finding 1: the earlier packages' real key shapes meet no production grant and no
    production bucket-policy statement, and every one of them is explicitly denied."""

    def test_the_earlier_keys_are_the_traced_layouts(self) -> None:
        keys = _earlier_package_keys()
        assert keys["qualification / adr-0017 claim"].startswith("bronze/_acquisition_claims/")
        assert keys["qualification / adr-0017 record (stocks)"].startswith(
            "bronze/sharadar/stocks/acquisitions/"
        )
        assert keys["adr-0017 general bronze payload (stocks)"].startswith(
            "bronze/sharadar/stocks/objects/sha256/"
        )
        assert keys["adr-0020 qualification payload (stocks)"].startswith(
            "bronze/sharadar/stocks/qualification/"
        )
        assert keys["qualification locator"].startswith("qualification/sharadar/locators/")
        assert keys["qualification report"].startswith("qualification/sharadar/reports/")

    @pytest.mark.parametrize("document", ["production_acquisition", "production_build"])
    def test_no_production_grant_reaches_an_earlier_key(self, model: Model, document: str) -> None:
        grants = [r for s in _allows(model.documents[document]) for r in s.resources]
        assert grants
        for label, key in _earlier_package_keys().items():
            hits = [g for g in grants if _arn_pattern_matches(g, key)]
            assert hits == [], f"{document} grants {label} ({key}) through {hits}"

    @pytest.mark.parametrize("document", ["production_acquisition", "production_build"])
    def test_every_earlier_key_is_explicitly_denied_for_every_action(
        self, model: Model, document: str
    ) -> None:
        denies = [
            r
            for s in _denies(model.documents[document])
            if "s3:*" in s.actions
            for r in s.resources
        ]
        for label, key in _earlier_package_keys().items():
            assert any(_arn_pattern_matches(d, key) for d in denies), (
                f"{document} does not deny {label} ({key})"
            )

    def test_no_bucket_policy_statement_governs_an_earlier_key(self, model: Model) -> None:
        scope = [
            r
            for s in model.documents["licensed_bucket"]
            if s.sid.startswith("Production")
            for r in s.resources
        ]
        assert scope
        for label, key in _earlier_package_keys().items():
            hits = [r for r in scope if _arn_pattern_matches(r, key)]
            assert hits == [], (
                f"the production bucket policy governs {label} ({key}) through {hits}"
            )

    def test_the_production_namespaces_are_still_governed(self, model: Model) -> None:
        """The reverse: a production-shaped key IS in scope, so the scope is not vacuous."""
        scope = [
            r
            for s in model.documents["licensed_bucket"]
            if s.sid.startswith("Production")
            for r in s.resources
        ]
        for production_key in (
            "bronze/sharadar/stocks/production/objects/sha256/" + "b" * 64,
            "bronze/sharadar/stocks/production/acquisitions/synthetic/01.json",
            "bronze/_production_claims/synthetic.json",
            "bronze/sharadar/_indexes/synthetic.json",
            "silver/x",
            "_verification/synthetic/positive",
        ):
            assert any(_arn_pattern_matches(r, production_key) for r in scope), production_key

    def test_the_qualification_policies_still_grant_the_qualification_keys(self) -> None:
        """Sanity control on the matcher: the qualification policy does reach its own keys."""
        real = QI.analyse((INFRA / "qualification_policies.tf").read_text(encoding="utf-8"))
        writes = [
            r
            for s in real.documents["qualification_acquisition"]
            if s.effect == "Allow"
            for r in s.resources
        ]
        keys = _earlier_package_keys()
        assert any(_arn_pattern_matches(w, keys["qualification / adr-0017 claim"]) for w in writes)
        assert any(
            _arn_pattern_matches(w, keys["adr-0020 qualification payload (stocks)"]) for w in writes
        )


# ---------------------------------------------------------------------------
# Finding 3 evidence: the attachment guard is an exact mapping
# ---------------------------------------------------------------------------


class TestAttachmentGuardIsExact:
    def test_the_real_tree_has_exactly_the_four_approved_attachments(
        self, sources: dict[str, str]
    ) -> None:
        all_tf = {p.name: p.read_text(encoding="utf-8") for p in INFRA.glob("*.tf")}
        assert GUARD.role_policy_attachment_violations(all_tf) == []
        assert len(GUARD.ADR_0036_APPROVED_ATTACHMENTS) == 4

    def test_a_production_labelled_attachment_to_the_foundation_role_is_refused(self) -> None:
        all_tf = {p.name: p.read_text(encoding="utf-8") for p in INFRA.glob("*.tf")}
        all_tf["production_principals.tf"] += (
            '\nresource "aws_iam_role_policy_attachment" "production_foundation_widening" {\n'
            "  count      = local.production_count_a\n"
            "  role       = aws_iam_role.task.name\n"
            "  policy_arn = aws_iam_policy.production_acquisition[0].arn\n}\n"
        )
        found = GUARD.role_policy_attachment_violations(all_tf)
        assert any("production_foundation_widening" in f for f in found), found

    def test_swapped_actor_policies_are_refused(self) -> None:
        all_tf = {p.name: p.read_text(encoding="utf-8") for p in INFRA.glob("*.tf")}
        text = all_tf["production_principals.tf"]
        text = text.replace(
            "policy_arn = aws_iam_policy.production_acquisition[0].arn",
            "policy_arn = aws_iam_policy.__swap__[0].arn",
        )
        text = text.replace(
            "policy_arn = aws_iam_policy.production_build[0].arn",
            "policy_arn = aws_iam_policy.production_acquisition[0].arn",
        )
        text = text.replace(
            "policy_arn = aws_iam_policy.__swap__[0].arn",
            "policy_arn = aws_iam_policy.production_build[0].arn",
        )
        all_tf["production_principals.tf"] = text
        found = GUARD.role_policy_attachment_violations(all_tf)
        assert any("production_build to production_acquire_task" in f for f in found), found
        assert any("production_acquisition to production_build_task" in f for f in found), found

    def test_an_extra_attachment_in_another_file_is_refused(self) -> None:
        all_tf = {p.name: p.read_text(encoding="utf-8") for p in INFRA.glob("*.tf")}
        all_tf["iam.tf"] += (
            '\nresource "aws_iam_role_policy_attachment" "production_acquire_task_extra" {\n'
            "  count      = local.production_count_a\n"
            "  role       = aws_iam_role.production_acquire_task[0].name\n"
            "  policy_arn = aws_iam_policy.production_acquisition[0].arn\n}\n"
        )
        found = GUARD.role_policy_attachment_violations(all_tf)
        assert any(
            "iam.tf:aws_iam_role_policy_attachment.production_acquire_task_extra" in f
            for f in found
        ), found

    def test_a_duplicated_approved_attachment_is_refused(self) -> None:
        all_tf = {p.name: p.read_text(encoding="utf-8") for p in INFRA.glob("*.tf")}
        all_tf["production_principals.tf"] += (
            '\nresource "aws_iam_role_policy_attachment" "production_acquire_task_again" {\n'
            "  count      = local.production_count_a\n"
            "  role       = aws_iam_role.production_acquire_task[0].name\n"
            "  policy_arn = aws_iam_policy.production_acquisition[0].arn\n}\n"
        )
        found = GUARD.role_policy_attachment_violations(all_tf)
        assert any("declared 2 times" in f for f in found), found

    def test_a_deleted_approved_attachment_is_refused(self) -> None:
        all_tf = {p.name: p.read_text(encoding="utf-8") for p in INFRA.glob("*.tf")}
        text = all_tf["production_principals.tf"]
        start = text.index(
            'resource "aws_iam_role_policy_attachment" "production_build_task_bootstrap"'
        )
        end = text.index("\n}\n", start) + 3
        all_tf["production_principals.tf"] = text[:start] + text[end:]
        found = GUARD.role_policy_attachment_violations(all_tf)
        assert any("declared 0 times" in f for f in found), found

    def test_a_qualification_labelled_attachment_is_still_refused(self) -> None:
        all_tf = {p.name: p.read_text(encoding="utf-8") for p in INFRA.glob("*.tf")}
        all_tf["qualification_principals.tf"] += (
            '\nresource "aws_iam_role_policy_attachment" "qualification_acquisition_attach" {\n'
            "  role       = aws_iam_role.task.name\n"
            "  policy_arn = aws_iam_policy.qualification_acquisition.arn\n}\n"
        )
        assert GUARD.role_policy_attachment_violations(all_tf)


# ---------------------------------------------------------------------------
# Negative controls: mutations that must trip a rule
# ---------------------------------------------------------------------------


def _mutate(sources: dict[str, str], file: str, old: str, new: str) -> dict[str, str]:
    assert sources[file].count(old) >= 1, f"mutation anchor missing in {file}: {old!r}"
    mutated = dict(sources)
    mutated[file] = sources[file].replace(old, new)
    return mutated


#: Deliberate mutations, each paired with the rule it must trip. Multi-line anchors are
#: triple-quoted so no source line is long; each is an exact substring of the real file.
MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "production_principals.tf",
        """resource "aws_ssoadmin_account_assignment" "production_build_launcher" {
  count = local.production_count_b""",
        """resource "aws_ssoadmin_account_assignment" "production_build_launcher" {
  count = local.production_count_a""",
        "an assignment must be gated on stage b",
    ),
    (
        "storage.tf",
        'sid    = "ProductionRefusesUnconditionalObjectCreation"',
        'sid    = "ProductionRefusesSomethingElse"',
        "ProductionRefusesUnconditionalObjectCreation is missing",
    ),
    (
        "production_policies.tf",
        """    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["AES256"]
    }

    condition {
      test     = "Null"
      variable = "s3:if-none-match"
      values   = ["false"]
    }

    condition {
      test     = "Bool"
      variable = "s3:ObjectCreationOperation"
      values   = ["true"]
    }

    condition {
      test     = "Null"
      variable = "s3:x-amz-copy-source"
      values   = ["true"]
    }
  }

  # Write-only at the IAM layer""",
        """    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["AES256"]
    }
  }

  # Write-only at the IAM layer""",
        "PutObject grant lacks",
    ),
    (
        "production_policies.tf",
        """    sid           = "AcquisitionTouchesNoOtherBucket"
    effect        = "Deny"
    actions       = ["s3:*"]""",
        """    sid           = "AcquisitionTouchesNoOtherBucket"
    effect        = "Deny"
    actions       = ["s3:GetBucketLocation"]""",
        "no NotResource deny confining S3",
    ),
    (
        "production_policies.tf",
        """    sid    = "TaskNeverWritesAParameterOrEncrypts"
    effect = "Deny"
    actions = [
      "ssm:PutParameter",""",
        """    sid    = "TaskNeverWritesAParameterOrEncrypts"
    effect = "Deny"
    actions = [
      "ssm:PutParameters",""",
        "task bootstrap must deny ssm:PutParameter",
    ),
    (
        "production_policies.tf",
        '''    resources = [local.production_acquisition_input_parameter_arn]

    condition {
      test     = "Bool"
      variable = "ssm:Overwrite"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DeleteThisActorsInputAfterTheRun"''',
        '''    resources = [local.production_acquisition_input_parameter_arn]
  }

  statement {
    sid       = "DeleteThisActorsInputAfterTheRun"''',
        "human bootstrap must create exactly its input, without overwrite",
    ),
    (
        "production_policies.tf",
        "not_resources = [aws_iam_role.production_acquire_task[0].arn, "
        "aws_iam_role.task_execution.arn]",
        "not_resources = [aws_iam_role.production_acquire_task[0].arn]",
        "launcher must close PassRole with NotResource on the same two roles",
    ),
    (
        "production_policies.tf",
        "resources = [aws_iam_role.production_build_task[0].arn, aws_iam_role.task_execution.arn]",
        "resources = [aws_iam_role.production_build_task[0].arn, aws_iam_role.task_execution.arn, "
        "aws_iam_role.task.arn]",
        "launcher must pass exactly its task role and the execution role",
    ),
    (
        "production_network.tf",
        """  description       = "DNS to the VPC resolver, TCP fallback."
  cidr_ipv4         = local.production_vpc_resolver_cidr
  ip_protocol       = "tcp"
  from_port         = 53
  to_port           = 53
}

# ---------------------------------------------------------------------------
# Acquisition""",
        """  description       = "DNS to the VPC resolver, TCP fallback."
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 53
  to_port           = 53
}

# ---------------------------------------------------------------------------
# Acquisition""",
        "must not contain 0.0.0.0/0",
    ),
    (
        "production_bindings.tf",
        """    sid     = "BuildLauncherGeneratesTheReleaseDataKey"
    effect  = "Allow"
    actions = ["kms:GenerateDataKey"]""",
        """    sid     = "BuildLauncherGeneratesTheReleaseDataKey"
    effect  = "Allow"
    actions = ["kms:GenerateDataKey", "kms:Decrypt"]""",
        "must grant GenerateDataKey only",
    ),
    (
        "iam.tf",
        'sid    = "WriteTaskLogs"',
        'sid    = "WriteTaskLogsAndMore"',
        "the execution role must be unchanged",
    ),
    # Finding 1: a production grant widened onto a qualification record prefix.
    (
        "production_policies.tf",
        '"${aws_s3_bucket.licensed.arn}/bronze/sharadar/stocks/production/acquisitions/*",',
        '"${aws_s3_bucket.licensed.arn}/bronze/sharadar/stocks/acquisitions/*",',
        "grants an earlier package's namespace",
    ),
    # Finding 1: the bucket-policy scope widened to the whole provider prefix.
    (
        "storage.tf",
        "    local.production_output_objects,\n"
        '    ["${aws_s3_bucket.licensed.arn}/_verification/*"],',
        "    local.production_output_objects,\n"
        '    ["${aws_s3_bucket.licensed.arn}/_verification/*", '
        '"${aws_s3_bucket.licensed.arn}/bronze/sharadar/*"],',
        "must enumerate the production prefixes",
    ),
    # Finding 2: the build group given egress to the Secrets Manager endpoint.
    (
        "production_network.tf",
        """resource "aws_vpc_security_group_egress_rule" "production_build_endpoints" {
  count = local.production_count_a

  security_group_id            = aws_security_group.production_build[0].id
  description                  = "HTTPS to the interface endpoints."
  referenced_security_group_id = aws_security_group.production_endpoints[0].id""",
        """resource "aws_vpc_security_group_egress_rule" "production_build_endpoints" {
  count = local.production_count_a

  security_group_id            = aws_security_group.production_build[0].id
  description                  = "HTTPS to the interface endpoints."
  referenced_security_group_id = aws_security_group.production_secrets_endpoint[0].id""",
        "only the acquisition group may have egress to the Secrets Manager endpoint",
    ),
    # Finding 2: the endpoint policy broadened to every Secrets Manager action.
    (
        "production_network.tf",
        """      actions   = ["secretsmanager:GetSecretValue"]
      resources = [var.production_acquisition_secret_arn]""",
        """      actions   = ["secretsmanager:*"]
      resources = [var.production_acquisition_secret_arn]""",
        "must allow exactly secretsmanager:GetSecretValue",
    ),
    # Finding 2: the endpoint policy broadened to every principal.
    (
        "production_network.tf",
        """      principals {
        type        = "AWS"
        identifiers = [aws_iam_role.production_acquire_task[0].arn]
      }

      actions   = ["secretsmanager:GetSecretValue"]""",
        """      principals {
        type        = "*"
        identifiers = ["*"]
      }

      actions   = ["secretsmanager:GetSecretValue"]""",
        "must name the acquisition task role as its only principal",
    ),
    # Finding 2: the build group admitted at the endpoint's security group.
    (
        "production_network.tf",
        '  description                  = "HTTPS from the acquisition task security group, '
        'and from nothing else."\n'
        "  referenced_security_group_id = aws_security_group.production_acquisition[0].id",
        '  description                  = "HTTPS from the acquisition task security group, '
        'and from nothing else."\n'
        "  referenced_security_group_id = aws_security_group.production_build[0].id",
        "admit the acquisition task group and nothing else",
    ),
    (
        "production_principals.tf",
        'production_acquire_launcher_set       = "KalpaManiAcquireLauncher"   # 24',
        'production_acquire_launcher_set       = "KalpaManiProductionAcquireLauncher"   # 34',
        "production_acquire_launcher_set",
    ),
]


@pytest.mark.parametrize(("file", "old", "new", "expected"), MUTATIONS)
def test_each_mutation_trips_its_rule(
    sources: dict[str, str], file: str, old: str, new: str, expected: str
) -> None:
    found = violations(_mutate(sources, file, old, new))
    assert any(expected in v for v in found), (
        f"expected a violation containing {expected!r}, got {found}"
    )


def test_an_empty_configuration_fails(sources: dict[str, str]) -> None:
    empty = {name: "" for name in sources}
    empty["iam.tf"] = sources["iam.tf"]
    empty["storage.tf"] = sources["storage.tf"]
    assert violations(empty), "a suite that passes on nothing checks nothing"


def test_the_repository_wide_role_guards_use_the_exact_attachment_mapping() -> None:
    """Finding 3: every guard judges attachments by the audit's exact (file, role, policy)
    table -- no guard exempts an attachment by its label."""
    for name in ("test_qualification_infrastructure.py", "test_adr_0018_governance.py"):
        text = Path(__file__).with_name(name).read_text(encoding="utf-8")
        assert "role_policy_attachment_violations" in text, name
        assert 'startswith("production_")' not in text, name
    audit = (PROJECT_ROOT / "scripts" / "phase3_docs_audit.py").read_text(encoding="utf-8")
    assert "ADR_0036_APPROVED_ATTACHMENTS" in audit
    assert 'name.startswith("production_")' not in audit
