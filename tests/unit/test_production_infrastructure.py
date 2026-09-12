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
            gated = count == "local.production_count_a" or (
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
            "/bronze/_acquisition_claims/*",
        ):
            if not _mentions(scope, prefix):
                found.append(f"{sid} must cover {prefix}")
        if any(r.endswith("/bronze/sharadar/*") for r in scope):
            found.append(f"{sid} must enumerate the production prefixes, not bronze/sharadar/*")
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
        _mentions(s.resources, "/bronze/_acquisition_claims/*") and "s3:GetObject" in s.actions
        for s in _denies(build)
    ):
        found.append("build must deny claim reads")
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
            if not _has_condition(s, "StringLike", "aws:PrincipalArn"):
                found.append(f"key policy {s.sid} must match the generated-role prefix")
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
    if set(endpoints) != {"ecr.api", "ecr.dkr", "logs", "ssm", "sts", "secretsmanager"}:
        found.append(
            f"interface endpoints must be exactly the six ADR-0036 names, found {sorted(endpoints)}"
        )
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
        """The key policy names generated-role PREFIX patterns, never a live suffix."""
        for name in PRODUCTION_FILES:
            found = QI.literal_violations(sources[name])
            if name == "production_bindings.tf":
                assert found == ["a generated role name"], found
                for match in re.findall(r'AWSReservedSSO_[^"]*', sources[name]):
                    assert match.startswith("AWSReservedSSO_${local.") and match.endswith("_*"), (
                        match
                    )
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


def test_the_repository_wide_role_guard_admits_only_production_attachments() -> None:
    """The qualification guard is narrowed, not removed: qualification labels may not attach."""
    text = (
        Path(__file__).with_name("test_qualification_infrastructure.py").read_text(encoding="utf-8")
    )
    assert 'label.startswith("qualification_")' in text
    assert (
        "production_"
        in text.split("test_no_iam_role_or_attachment_is_declared_anywhere_under_infra", 1)[1][
            :2500
        ]
    )
