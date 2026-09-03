"""The ADR-0018 qualification permission sets, checked by parsing the Terraform.

`infra/aws/research-data-plane/qualification_policies.tf` is an OFFLINE
implementation candidate. Nothing here contacts AWS, runs Terraform, resolves a
credential, reads state or opens a socket: the file is read as text, parsed into
blocks and attributes, and asserted on.

**The parser is the point.** Every existing infrastructure guard in this
repository is a regex over the raw file, which is enough for "is this token
present" and not enough for "which statement grants which action on which
resource". A substring scan cannot tell an Allow from a Deny, cannot tell the
acquisition document from the assessment one, and reports every deliberate
omission explained in a comment as a violation. So this module parses the subset
of HCL these files use -- blocks with labels, attributes, lists, strings,
heredocs, `dynamic` blocks -- and evaluates the policy documents structurally.

**The rules are functions, not assertions.** :func:`violations` returns every rule
the parsed configuration breaks, so the same rule set can be pointed at the real
file (expect none) and at a deliberately mutated copy (expect the specific one).
That is what makes these tests non-tautological: a rule that could not fail is
visible immediately, because the mutation that should trip it does not.

There is also a negative control. An empty Terraform document, and an unrelated
one, must both fail -- a suite that passes on a file containing nothing is not
checking anything.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import pytest

from kalpamani.data.ingest.publication import BRONZE_NAMESPACE, CLAIM_NAMESPACE
from kalpamani.data.ingest.sharadar.datasets import PROVIDER
from kalpamani.data.qualify.sharadar.locator import LOCATOR_SEGMENTS
from kalpamani.data.qualify.sharadar.plan import EMPIRICAL_DATASETS
from kalpamani.data.qualify.sharadar.publication import QUALIFICATION_SEGMENT
from kalpamani.data.qualify.sharadar.report import REPORT_SEGMENTS

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT = PROJECT_ROOT / "scripts" / "phase3_docs_audit.py"
INFRA = PROJECT_ROOT / "infra" / "aws" / "research-data-plane"
QUALIFICATION_TF = INFRA / "qualification_policies.tf"
OUTPUTS_TF = INFRA / "outputs.tf"

#: The bucket the ARN interpolation resolves to. Written as the reference rather
#: than a name: a licensed bucket name is an identifier and is never committed.
LICENSED_ARN = "${aws_s3_bucket.licensed.arn}"

#: The two policy documents this candidate declares.
ACQUISITION = "qualification_acquisition"
ASSESSMENT = "qualification_assessment"

#: Read actions AWS authorises through the object-read permission. ADR-0019 s.3
#: records the finding that makes this list matter: HeadObject and
#: GetObjectAttributes are not independently grantable.
OBJECT_READ_ACTIONS = frozenset(
    {
        "s3:GetObject",
        "s3:GetObjectVersion",
        "s3:GetObjectAttributes",
        "s3:GetObjectVersionAttributes",
    }
)

#: Enumeration actions. Their resource is the bucket, not an object.
LISTING_ACTIONS = frozenset(
    {"s3:ListBucket", "s3:ListBucketVersions", "s3:ListBucketMultipartUploads"}
)

#: Destruction actions. Deletion authority lives with the separate deletion role.
DELETE_ACTIONS = frozenset({"s3:DeleteObject", "s3:DeleteObjectVersion"})

#: Anything that could hand a process a provider credential.
CREDENTIAL_ACTIONS = frozenset(
    {
        "secretsmanager:GetSecretValue",
        "secretsmanager:BatchGetSecretValue",
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath",
    }
)


# ---------------------------------------------------------------------------
# A parser for the HCL subset these files use
# ---------------------------------------------------------------------------


@dataclass
class Block:
    """One HCL block: a type, its labels, its attributes and its child blocks."""

    type: str
    labels: tuple[str, ...]
    attributes: dict[str, str] = field(default_factory=dict)
    blocks: list[Block] = field(default_factory=list)

    def children(self, block_type: str) -> list[Block]:
        return [child for child in self.blocks if child.type == block_type]


class HclSyntaxError(Exception):
    """The document could not be parsed. Never silently treated as empty."""


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_HEREDOC = re.compile(r"<<-?([A-Za-z_][A-Za-z0-9_]*)\r?\n")


def _strip_noise(text: str) -> str:
    """Blank out comments, string bodies and heredoc bodies, preserving offsets.

    Structure is found on the blanked copy and content is read from the original,
    so a brace inside a comment or a string cannot open a block. Offsets are
    preserved exactly -- every removed character becomes a space or is left as a
    newline -- which is what lets the two copies be indexed interchangeably.
    """
    out = list(text)
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "#" or text.startswith("//", index):
            while index < length and text[index] != "\n":
                out[index] = " "
                index += 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = length if end == -1 else end + 2
            for position in range(index, end):
                if text[position] != "\n":
                    out[position] = " "
            index = end
            continue
        heredoc = _HEREDOC.match(text, index)
        if heredoc is not None:
            marker = heredoc.group(1)
            body = heredoc.end()
            terminator = re.compile(rf"^[ \t]*{re.escape(marker)}[ \t]*$", re.MULTILINE)
            found = terminator.search(text, body)
            if found is None:
                raise HclSyntaxError(f"unterminated heredoc {marker}")
            for position in range(index, found.end()):
                if text[position] != "\n":
                    out[position] = " "
            index = found.end()
            continue
        if char == '"':
            index += 1
            while index < length:
                if text[index] == "\\":
                    out[index] = " "
                    if index + 1 < length:
                        out[index + 1] = " "
                    index += 2
                    continue
                if text[index] == '"':
                    break
                if text[index] != "\n":
                    out[index] = " "
                index += 1
            if index >= length:
                raise HclSyntaxError("unterminated string")
            index += 1
            continue
        index += 1
    return "".join(out)


def _matching(masked: str, start: int, opening: str, closing: str) -> int:
    """The index of the delimiter closing the one at ``start``."""
    depth = 0
    for position in range(start, len(masked)):
        if masked[position] == opening:
            depth += 1
        elif masked[position] == closing:
            depth -= 1
            if depth == 0:
                return position
    raise HclSyntaxError(f"unbalanced {opening!r}")


def _parse_body(text: str, masked: str, start: int, end: int) -> tuple[dict[str, str], list[Block]]:
    attributes: dict[str, str] = {}
    blocks: list[Block] = []
    index = start
    while index < end:
        if masked[index] in " \t\r\n":
            index += 1
            continue
        identifier = _IDENT.match(masked, index)
        if identifier is None:
            raise HclSyntaxError(f"unexpected character {masked[index]!r} at {index}")
        name = identifier.group(0)
        cursor = identifier.end()
        while cursor < end and masked[cursor] in " \t":
            cursor += 1
        if cursor < end and masked[cursor] == "=":
            cursor += 1
            value_start = cursor
            value_end = _expression_end(masked, cursor, end)
            attributes[name] = text[value_start:value_end].strip()
            index = value_end
            continue
        labels: list[str] = []
        while cursor < end and masked[cursor] == '"':
            close = masked.index('"', cursor + 1)
            labels.append(text[cursor + 1 : close])
            cursor = close + 1
            while cursor < end and masked[cursor] in " \t":
                cursor += 1
        if cursor >= end or masked[cursor] != "{":
            raise HclSyntaxError(f"block {name!r} has no body")
        close = _matching(masked, cursor, "{", "}")
        child_attributes, child_blocks = _parse_body(text, masked, cursor + 1, close)
        blocks.append(Block(name, tuple(labels), child_attributes, child_blocks))
        index = close + 1
    return attributes, blocks


def _expression_end(masked: str, start: int, end: int) -> int:
    """Where one attribute expression stops: a newline outside any bracket."""
    depth = 0
    index = start
    while index < end:
        char = masked[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "\n" and depth <= 0:
            return index
        index += 1
    return end


def parse_hcl(text: str) -> list[Block]:
    """Every top-level block in ``text``.

    Raises:
        HclSyntaxError: on anything this subset cannot represent. A parse failure
            is never rounded down to an empty document -- that is how a suite
            starts passing against a file it no longer understands.
    """
    masked = _strip_noise(text)
    _, blocks = _parse_body(text, masked, 0, len(masked))
    return blocks


def string_list(expression: str) -> list[str]:
    """Every double-quoted string literal in one attribute expression.

    `concat([...], local.x)` and a bare list both answer with the literals they
    contain; a reference contributes none, which is why the locals are resolved
    before a policy document is evaluated rather than after.
    """
    return re.findall(r'"((?:[^"\\]|\\.)*)"', expression)


# ---------------------------------------------------------------------------
# The parsed configuration, with locals resolved
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Statement:
    """One IAM policy statement, flattened out of its document.

    ``actions_raw`` and ``resources_raw`` are kept beside the resolved literals
    because the two answer different questions. ``var.provider_secret_arns``
    resolves to no literal and is still a scope; an absent ``resources`` is not.
    Collapsing them would report the accepted conditional secret statement as
    unscoped, which is a rule firing on the one statement it should not.
    """

    sid: str
    effect: str
    actions: tuple[str, ...]
    resources: tuple[str, ...]
    actions_raw: str = ""
    resources_raw: str = ""


@dataclass(frozen=True)
class Configuration:
    """One parsed Terraform document, with `local.*` references resolved."""

    blocks: tuple[Block, ...]
    locals_: dict[str, tuple[str, ...]]
    documents: dict[str, tuple[Statement, ...]]
    policies: dict[str, Block]


def _resolve(expression: str, locals_: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """The strings one expression denotes, following `local.*` references once.

    Deliberately shallow and deliberately total: an unresolvable reference
    contributes nothing rather than raising, so a policy that scopes itself
    through an undefined local resolves to an empty resource set -- and an empty
    resource set fails the rules below rather than passing them silently.
    """
    values = list(string_list(expression))
    for name in re.findall(r"local\.([A-Za-z_][A-Za-z0-9_-]*)", expression):
        values.extend(locals_.get(name, ()))
    return tuple(values)


def analyse(text: str) -> Configuration:
    """Parse one Terraform document and flatten its IAM policy statements."""
    blocks = tuple(parse_hcl(text))

    locals_: dict[str, tuple[str, ...]] = {}
    for block in blocks:
        if block.type != "locals":
            continue
        # Two passes, so a local built by `concat` over earlier locals resolves.
        for _ in range(2):
            for name, expression in block.attributes.items():
                locals_[name] = _resolve(expression, locals_)

    documents: dict[str, tuple[Statement, ...]] = {}
    policies: dict[str, Block] = {}
    for block in blocks:
        if block.type == "data" and block.labels[:1] == ("aws_iam_policy_document",):
            documents[block.labels[1]] = tuple(_statements(block, locals_))
        if block.type == "resource" and block.labels[:1] == ("aws_iam_policy",):
            policies[block.labels[1]] = block
    return Configuration(blocks, locals_, documents, policies)


def _statements(document: Block, locals_: dict[str, tuple[str, ...]]) -> list[Statement]:
    """Every statement in one document, including those inside `dynamic` blocks."""
    found: list[Block] = list(document.children("statement"))
    for dynamic in document.children("dynamic"):
        if dynamic.labels[:1] == ("statement",):
            for content in dynamic.children("content"):
                found.append(content)
    return [
        Statement(
            sid=string_list(block.attributes.get("sid", ""))[0]
            if string_list(block.attributes.get("sid", ""))
            else "",
            effect=(string_list(block.attributes.get("effect", "")) or ["Allow"])[0],
            actions=_resolve(block.attributes.get("actions", ""), locals_),
            resources=_resolve(block.attributes.get("resources", ""), locals_),
            actions_raw=block.attributes.get("actions", ""),
            resources_raw=block.attributes.get("resources", ""),
        )
        for block in found
    ]


def allows(statements: tuple[Statement, ...]) -> list[Statement]:
    return [statement for statement in statements if statement.effect == "Allow"]


def denies(statements: tuple[Statement, ...]) -> list[Statement]:
    return [statement for statement in statements if statement.effect == "Deny"]


def granted(statements: tuple[Statement, ...]) -> set[str]:
    """Every action any Allow statement grants."""
    return {action for statement in allows(statements) for action in statement.actions}


def denied(statements: tuple[Statement, ...]) -> set[str]:
    return {action for statement in denies(statements) for action in statement.actions}


def granted_on(statements: tuple[Statement, ...], action: str) -> set[str]:
    """Every resource on which ``action`` is allowed."""
    return {
        resource
        for statement in allows(statements)
        if action in statement.actions
        for resource in statement.resources
    }


# ---------------------------------------------------------------------------
# The expected object prefixes, derived from the merged key builders
# ---------------------------------------------------------------------------


def _dataset_names() -> tuple[str, ...]:
    return tuple(dataset.value for dataset in EMPIRICAL_DATASETS)


CLAIM_PREFIX = f"{LICENSED_ARN}/{BRONZE_NAMESPACE}/{CLAIM_NAMESPACE}/*"
LOCATOR_PREFIX = f"{LICENSED_ARN}/{'/'.join(LOCATOR_SEGMENTS)}/*"
REPORT_PREFIX = f"{LICENSED_ARN}/{'/'.join(REPORT_SEGMENTS)}/*"
PAYLOAD_PREFIXES = frozenset(
    f"{LICENSED_ARN}/{BRONZE_NAMESPACE}/{PROVIDER}/{name}/{QUALIFICATION_SEGMENT}/*"
    for name in _dataset_names()
)
RECORD_PREFIXES = frozenset(
    f"{LICENSED_ARN}/{BRONZE_NAMESPACE}/{PROVIDER}/{name}/acquisitions/*"
    for name in _dataset_names()
)

#: What the acquisition actor publishes: claim, payload and record per completed
#: request, and one locator last.
ACQUISITION_WRITE_PREFIXES = (
    frozenset({CLAIM_PREFIX, LOCATOR_PREFIX}) | PAYLOAD_PREFIXES | RECORD_PREFIXES
)

#: What the assessment actor reads as evidence. ZERO claims (ADR-0018 s.9.4).
ASSESSMENT_READ_PREFIXES = frozenset({LOCATOR_PREFIX}) | PAYLOAD_PREFIXES | RECORD_PREFIXES


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def violations(config: Configuration) -> list[str]:
    """Every accepted-architecture rule the parsed configuration breaks.

    One function rather than thirty assertions, so the identical rule set can be
    run against the real file and against a mutation of it. A rule that never
    fires is visible: its mutation test goes green with an empty result.
    """
    broken: list[str] = []

    # -- no role, no trust, no attachment ---------------------------------
    #
    # Checked FIRST, and before the completeness check below returns. A mutation
    # that adds a role while removing a policy document must still be reported as
    # a role, not only as a missing document.
    for block in config.blocks:
        if block.type == "resource" and block.labels[:1] in (
            ("aws_iam_role",),
            ("aws_iam_role_policy",),
            ("aws_iam_role_policy_attachment",),
            ("aws_iam_policy_attachment",),
            ("aws_iam_user",),
            ("aws_iam_user_policy_attachment",),
            ("aws_iam_group_policy_attachment",),
            ("aws_iam_access_key",),
        ):
            broken.append(f"declares an identity or attachment: {block.labels}")
        if block.type == "data" and block.labels[:1] not in (("aws_iam_policy_document",),):
            broken.append(f"declares a data source that is not a policy document: {block.labels}")
    for name, statements in config.documents.items():
        for statement in statements:
            if "sts:AssumeRole" in statement.actions:
                broken.append(f"{name} names sts:AssumeRole")
            for action in statement.actions:
                if action.startswith("iam:"):
                    broken.append(f"{name} grants an IAM action: {action}")

    for name in (ACQUISITION, ASSESSMENT):
        if name not in config.documents:
            broken.append(f"missing policy document: {name}")
        if name not in config.policies:
            broken.append(f"missing managed policy: {name}")
    if ACQUISITION not in config.documents or ASSESSMENT not in config.documents:
        return broken

    acquisition = config.documents[ACQUISITION]
    assessment = config.documents[ASSESSMENT]

    # -- no wildcard grant ------------------------------------------------
    for name, statements in config.documents.items():
        for statement in allows(statements):
            for action in statement.actions:
                if "*" in action:
                    broken.append(f"{name}/{statement.sid} allows a wildcard action: {action}")
            for resource in statement.resources:
                if resource == "*" or resource.endswith(":*") or resource == f"{LICENSED_ARN}/*":
                    broken.append(f"{name}/{statement.sid} allows a wildcard resource: {resource}")
            if not statement.resources_raw.strip():
                broken.append(f"{name}/{statement.sid} allows an unscoped statement")
            if not statement.actions_raw.strip():
                broken.append(f"{name}/{statement.sid} allows no action, so it says nothing")

    # -- acquisition: write-only ------------------------------------------
    acquisition_allowed = granted(acquisition)
    forbidden = acquisition_allowed & (OBJECT_READ_ACTIONS | LISTING_ACTIONS | DELETE_ACTIONS)
    for action in sorted(forbidden):
        broken.append(f"acquisition is granted {action}; ADR-0019 s.4.1 withholds it")
    if acquisition_allowed - {"s3:PutObject"} - CREDENTIAL_ACTIONS:
        extra = sorted(acquisition_allowed - {"s3:PutObject"} - CREDENTIAL_ACTIONS)
        broken.append(f"acquisition is granted actions outside its accepted set: {extra}")
    if "s3:PutObject" not in acquisition_allowed:
        broken.append("acquisition cannot publish anything")
    if acquisition_allowed & (CREDENTIAL_ACTIONS - {"secretsmanager:GetSecretValue"}):
        broken.append("acquisition is granted more than the one governed secret retrieval")

    acquisition_writes = granted_on(acquisition, "s3:PutObject")
    for missing in sorted(ACQUISITION_WRITE_PREFIXES - acquisition_writes):
        broken.append(f"acquisition cannot write a required prefix: {missing}")
    for extra_prefix in sorted(acquisition_writes - ACQUISITION_WRITE_PREFIXES):
        broken.append(f"acquisition may write an unexpected prefix: {extra_prefix}")

    acquisition_denied = denied(acquisition)
    for action in sorted(OBJECT_READ_ACTIONS | LISTING_ACTIONS | DELETE_ACTIONS):
        if action not in acquisition_denied:
            broken.append(f"acquisition does not explicitly deny {action}")

    # -- assessment: reads evidence, writes one report --------------------
    assessment_allowed = granted(assessment)
    if assessment_allowed & CREDENTIAL_ACTIONS:
        broken.append("assessment is granted credential access")
    if assessment_allowed & LISTING_ACTIONS:
        broken.append("assessment is granted listing")
    if assessment_allowed & DELETE_ACTIONS:
        broken.append("assessment is granted deletion")
    if assessment_allowed - {"s3:GetObject", "s3:PutObject"}:
        extra = sorted(assessment_allowed - {"s3:GetObject", "s3:PutObject"})
        broken.append(f"assessment is granted actions outside its accepted set: {extra}")

    assessment_reads = granted_on(assessment, "s3:GetObject")
    for missing in sorted(ASSESSMENT_READ_PREFIXES - assessment_reads - {REPORT_PREFIX}):
        broken.append(f"assessment cannot read a required prefix: {missing}")
    for extra_prefix in sorted(assessment_reads - ASSESSMENT_READ_PREFIXES - {REPORT_PREFIX}):
        broken.append(f"assessment may read an unexpected prefix: {extra_prefix}")
    if CLAIM_PREFIX in assessment_reads:
        broken.append("assessment may read an acquisition claim; ADR-0018 s.9.4 fixes that at zero")

    assessment_writes = granted_on(assessment, "s3:PutObject")
    if assessment_writes != {REPORT_PREFIX}:
        broken.append(
            f"assessment write scope is not the report prefix alone: {sorted(assessment_writes)}"
        )

    assessment_denied = denied(assessment)
    for action in sorted(LISTING_ACTIONS | DELETE_ACTIONS | CREDENTIAL_ACTIONS):
        if action not in assessment_denied:
            broken.append(f"assessment does not explicitly deny {action}")
    denied_writes = {
        resource
        for statement in denies(assessment)
        if "s3:PutObject" in statement.actions
        for resource in statement.resources
    }
    for missing in sorted(ACQUISITION_WRITE_PREFIXES - denied_writes):
        broken.append(f"assessment is not denied writing acquisition evidence at {missing}")
    denied_reads = {
        resource
        for statement in denies(assessment)
        if "s3:GetObject" in statement.actions
        for resource in statement.resources
    }
    if CLAIM_PREFIX not in denied_reads:
        broken.append("assessment is not denied reading the acquisition claim prefix")

    # -- no CONTROL authority, no literal identifier ----------------------
    for name, statements in config.documents.items():
        for statement in statements:
            for resource in statement.resources:
                if "control" in resource.lower():
                    broken.append(f"{name}/{statement.sid} names the control bucket")
                if resource.startswith("arn:"):
                    broken.append(f"{name}/{statement.sid} carries a literal ARN")

    return broken


# ---------------------------------------------------------------------------
# The parser, exercised on its own terms
# ---------------------------------------------------------------------------


class TestTheParser:
    def test_a_brace_inside_a_comment_does_not_open_a_block(self) -> None:
        blocks = parse_hcl('# resource "x" "y" {\nlocals {\n  a = "1"\n}\n')
        assert [block.type for block in blocks] == ["locals"]

    def test_a_brace_inside_a_string_does_not_open_a_block(self) -> None:
        blocks = parse_hcl('locals {\n  a = "{"\n}\n')
        assert blocks[0].attributes["a"] == '"{"'

    def test_a_heredoc_body_is_not_parsed_as_structure(self) -> None:
        text = (
            'output "x" {\n'
            "  description = <<-EOT\n"
            '    resource "a" "b" {\n'
            "  EOT\n"
            '  value = "1"\n'
            "}\n"
        )
        blocks = parse_hcl(text)
        assert blocks[0].labels == ("x",)
        assert blocks[0].attributes["value"] == '"1"'

    def test_nested_blocks_and_labels_are_recovered(self) -> None:
        text = 'data "aws_iam_policy_document" "d" {\n  statement {\n    effect = "Deny"\n  }\n}\n'
        blocks = parse_hcl(text)
        assert blocks[0].labels == ("aws_iam_policy_document", "d")
        assert blocks[0].children("statement")[0].attributes["effect"] == '"Deny"'

    def test_a_multi_line_list_is_one_attribute(self) -> None:
        blocks = parse_hcl('locals {\n  a = [\n    "x",\n    "y",\n  ]\n}\n')
        assert string_list(blocks[0].attributes["a"]) == ["x", "y"]

    def test_an_unbalanced_brace_raises_rather_than_reading_as_empty(self) -> None:
        with pytest.raises(HclSyntaxError):
            parse_hcl('locals {\n  a = "1"\n')

    def test_an_unterminated_heredoc_raises(self) -> None:
        with pytest.raises(HclSyntaxError):
            parse_hcl('output "x" {\n  description = <<-EOT\n    body\n}\n')

    def test_a_dynamic_statement_is_flattened_into_the_document(self) -> None:
        text = (
            'data "aws_iam_policy_document" "d" {\n'
            '  dynamic "statement" {\n'
            "    for_each = []\n"
            "    content {\n"
            '      sid = "S"\n'
            '      effect = "Allow"\n'
            '      actions = ["a:B"]\n'
            '      resources = ["r"]\n'
            "    }\n"
            "  }\n"
            "}\n"
        )
        config = analyse(text)
        assert [statement.sid for statement in config.documents["d"]] == ["S"]

    def test_a_local_reference_is_resolved_into_the_statement(self) -> None:
        text = (
            "locals {\n"
            '  target = ["one", "two"]\n'
            "}\n"
            'data "aws_iam_policy_document" "d" {\n'
            "  statement {\n"
            '    effect = "Allow"\n'
            '    actions = ["s3:PutObject"]\n'
            "    resources = local.target\n"
            "  }\n"
            "}\n"
        )
        config = analyse(text)
        assert config.documents["d"][0].resources == ("one", "two")

    def test_a_concat_over_locals_resolves_transitively(self) -> None:
        text = 'locals {\n  a = ["one"]\n  b = concat(local.a, ["two"])\n}\n'
        config = analyse(text)
        assert set(config.locals_["b"]) == {"one", "two"}


# ---------------------------------------------------------------------------
# The real file
# ---------------------------------------------------------------------------


def _real_text() -> str:
    return QUALIFICATION_TF.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def real() -> Configuration:
    return analyse(_real_text())


class TestTheCandidate:
    def test_the_candidate_exists(self) -> None:
        assert QUALIFICATION_TF.is_file(), (
            "the offline qualification infrastructure candidate is missing"
        )

    def test_the_candidate_breaks_no_rule(self, real: Configuration) -> None:
        found = violations(real)
        assert found == [], "\n".join(found)

    def test_both_permission_sets_are_declared_as_managed_policies(
        self, real: Configuration
    ) -> None:
        assert sorted(real.policies) == [ACQUISITION, ASSESSMENT]

    def test_each_managed_policy_is_named_from_the_governed_prefix(
        self, real: Configuration
    ) -> None:
        for name, block in real.policies.items():
            assert "${var.name_prefix}" in block.attributes["name"], (
                f"{name} does not take its name from var.name_prefix"
            )
            assert f"data.aws_iam_policy_document.{name}.json" in block.attributes["policy"]

    def test_no_iam_role_or_attachment_is_declared_anywhere_under_infra(self) -> None:
        """The second gate is infrastructure mutation, and it is not this one."""
        offenders: list[str] = []
        for path in sorted(INFRA.glob("*.tf")):
            for block in parse_hcl(path.read_text(encoding="utf-8")):
                if block.type != "resource":
                    continue
                if block.labels[0] in ("aws_iam_role", "aws_iam_role_policy") and any(
                    label.startswith("qualification_") for label in block.labels[1:]
                ):
                    offenders.append(f"{path.name}: {block.labels}")
                if block.labels[0] in (
                    "aws_iam_policy_attachment",
                    "aws_iam_role_policy_attachment",
                    "aws_iam_user_policy_attachment",
                    "aws_iam_group_policy_attachment",
                ):
                    offenders.append(f"{path.name}: {block.labels}")
        assert offenders == [], f"an identity or attachment appeared: {offenders}"

    def test_no_trust_policy_is_declared_for_either_permission_set(self) -> None:
        """Read on the comment-stripped copy: the header explains the absence by name."""
        hcl = _strip_noise(_real_text())
        assert "assume_role_policy" not in hcl
        assert "sts:AssumeRole" not in hcl

    def test_the_dataset_list_matches_the_merged_plan_constant(self, real: Configuration) -> None:
        """A prefix nobody writes to, or a dataset nobody scoped, is caught here."""
        assert list(real.locals_["qualification_datasets"]) == list(_dataset_names())

    def test_the_candidate_declares_no_data_source_that_queries_aws(self) -> None:
        for block in parse_hcl(_real_text()):
            assert block.type != "data" or block.labels[0] == "aws_iam_policy_document", (
                f"a live-querying data source appeared: {block.labels}"
            )

    @pytest.mark.parametrize(
        "construct",
        [
            "provisioner",
            "local-exec",
            "remote-exec",
            "terraform_remote_state",
            "data.external",
            "aws_kms",
            "backend",
            "terraform.workspace",
        ],
    )
    def test_the_candidate_introduces_no_live_coupling(self, construct: str) -> None:
        """Scanned on real HCL. A comment naming a construct is explaining its absence."""
        assert construct not in _strip_noise(_real_text()), (
            f"{construct} would couple an offline candidate to something live"
        )

    def test_the_candidate_declares_only_managed_policies(self) -> None:
        declared = {
            block.labels[0] for block in parse_hcl(_real_text()) if block.type == "resource"
        }
        assert declared == {"aws_iam_policy"}, (
            f"the candidate creates something other than a managed policy: {sorted(declared)}"
        )

    @pytest.mark.parametrize(
        ("label", "pattern"),
        [
            ("AWS access key id", r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA)[A-Z0-9]{16}\b"),
            ("12-digit account id", r"(?<![\d.])\d{12}(?![\d.])"),
            ("email address", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
            ("account-bearing ARN", r"arn:aws:[a-z0-9-]*:[a-z0-9-]*:\d{12}:"),
        ],
    )
    def test_the_candidate_carries_no_identifier(self, label: str, pattern: str) -> None:
        assert re.search(pattern, _real_text()) is None, f"{label} committed in the candidate"

    def test_the_only_wildcard_resource_is_on_a_deny(self, real: Configuration) -> None:
        """Reported and tested, because it is the one exception in the file."""
        wildcards = [
            (name, statement.sid, statement.effect)
            for name, statements in real.documents.items()
            for statement in statements
            if "*" in statement.resources
        ]
        assert wildcards == [(ASSESSMENT, "AssessmentNeverRetrievesACredential", "Deny")]

    def test_neither_policy_can_reach_the_control_bucket(self, real: Configuration) -> None:
        for statements in real.documents.values():
            for statement in statements:
                for resource in statement.resources:
                    assert "control" not in resource.lower()

    def test_the_acquisition_grant_is_exactly_put_object(self, real: Configuration) -> None:
        assert granted(real.documents[ACQUISITION]) == {
            "s3:PutObject",
            "secretsmanager:GetSecretValue",
        }

    def test_the_assessment_grant_is_exactly_get_and_put(self, real: Configuration) -> None:
        assert granted(real.documents[ASSESSMENT]) == {"s3:GetObject", "s3:PutObject"}

    def test_the_acquisition_write_scope_is_the_four_evidence_classes(
        self, real: Configuration
    ) -> None:
        assert granted_on(real.documents[ACQUISITION], "s3:PutObject") == set(
            ACQUISITION_WRITE_PREFIXES
        )

    def test_the_assessment_read_scope_is_the_evidence_plus_its_own_report(
        self, real: Configuration
    ) -> None:
        assert granted_on(real.documents[ASSESSMENT], "s3:GetObject") == set(
            ASSESSMENT_READ_PREFIXES
        ) | {REPORT_PREFIX}

    def test_the_assessment_never_reads_a_claim(self, real: Configuration) -> None:
        assert CLAIM_PREFIX not in granted_on(real.documents[ASSESSMENT], "s3:GetObject")

    def test_the_secret_retrieval_is_conditional_on_a_supplied_arn(self) -> None:
        """Empty by default is the current correct value, so the grant is absent by default."""
        document = next(
            block
            for block in parse_hcl(_real_text())
            if block.type == "data" and block.labels[1] == ACQUISITION
        )
        dynamic = document.children("dynamic")
        assert [block.labels for block in dynamic] == [("statement",)]
        assert "var.provider_secret_arns" in dynamic[0].attributes["for_each"]

    def test_both_policy_arns_are_exposed_as_outputs(self) -> None:
        outputs = {
            block.labels[0]
            for block in parse_hcl(OUTPUTS_TF.read_text(encoding="utf-8"))
            if block.type == "output"
        }
        assert {
            "qualification_acquisition_policy_arn",
            "qualification_assessment_policy_arn",
        } <= outputs

    def test_no_output_exposes_a_secret_or_a_private_evidence_identifier(self) -> None:
        """Every output is an apply-time reference; none names private material.

        ``execution`` alone is not on the list. The pre-existing ECS
        ``task_execution_role_arn`` is not an ADR-0018 execution identity, and a
        term that flags it would be a rule about a word rather than about
        evidence.
        """
        private_terms = (
            "secret",
            "credential",
            "locator",
            "execution_id",
            "assessment_id",
            "payload",
            "subject",
            "digest",
        )
        for block in parse_hcl(OUTPUTS_TF.read_text(encoding="utf-8")):
            if block.type != "output":
                continue
            value = block.attributes.get("value", "").lower()
            for private in private_terms:
                assert private not in value, f"{block.labels[0]} exposes {private}"


# ---------------------------------------------------------------------------
# Mutation coverage -- every rule above is shown to fire
# ---------------------------------------------------------------------------

#: Each entry is a textual mutation of the real file and the substring the rule it
#: should trip reports. A mutation that changes nothing is itself a failure, so the
#: applier asserts the text actually moved.
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "acquisition gains GetObject",
        'actions   = ["s3:PutObject"]',
        'actions   = ["s3:PutObject", "s3:GetObject"]',
        "acquisition is granted s3:GetObject",
    ),
    (
        "acquisition gains GetObjectAttributes",
        'actions   = ["s3:PutObject"]',
        'actions   = ["s3:PutObject", "s3:GetObjectAttributes"]',
        "acquisition is granted s3:GetObjectAttributes",
    ),
    (
        "acquisition gains ListBucket",
        'actions   = ["s3:PutObject"]',
        'actions   = ["s3:PutObject", "s3:ListBucket"]',
        "acquisition is granted s3:ListBucket",
    ),
    (
        "acquisition gains DeleteObject",
        'actions   = ["s3:PutObject"]',
        'actions   = ["s3:PutObject", "s3:DeleteObject"]',
        "acquisition is granted s3:DeleteObject",
    ),
    (
        "acquisition gains a wildcard action",
        'actions   = ["s3:PutObject"]',
        'actions   = ["s3:*"]',
        "allows a wildcard action",
    ),
    (
        "acquisition gains a wildcard resource",
        "resources = local.qualification_acquisition_writes",
        'resources = ["${aws_s3_bucket.licensed.arn}/*"]',
        "allows a wildcard resource",
    ),
    (
        "acquisition gains the report prefix",
        "qualification_acquisition_writes = concat(",
        "qualification_acquisition_writes = concat([local.qualification_report_objects],",
        "acquisition may write an unexpected prefix",
    ),
    (
        "acquisition loses its explicit read deny",
        '"s3:GetObject",\n      "s3:GetObjectVersion",',
        '"s3:GetObjectVersion",',
        "acquisition does not explicitly deny s3:GetObject",
    ),
    (
        "acquisition gains the SSM parameter reads",
        'actions   = ["secretsmanager:GetSecretValue"]',
        'actions   = ["secretsmanager:GetSecretValue", "ssm:GetParameter"]',
        "acquisition is granted more than the one governed secret retrieval",
    ),
    (
        "assessment gains an evidence write prefix",
        "resources = [local.qualification_report_objects]\n  }\n\n  # HeadObject",
        "resources = concat([local.qualification_report_objects], "
        "local.qualification_payload_objects)\n  }\n\n  # HeadObject",
        "assessment write scope is not the report prefix alone",
    ),
    (
        "assessment gains the claim read prefix",
        "qualification_assessment_reads = concat(\n    [local.qualification_locator_objects],",
        "qualification_assessment_reads = concat(\n"
        "    [local.qualification_claim_objects],\n"
        "    [local.qualification_locator_objects],",
        "assessment may read an acquisition claim",
    ),
    (
        "assessment gains credential access",
        'actions   = ["s3:GetObject"]\n    resources = local.qualification_assessment_reads',
        'actions   = ["s3:GetObject", "secretsmanager:GetSecretValue"]\n'
        "    resources = local.qualification_assessment_reads",
        "assessment is granted credential access",
    ),
    (
        "assessment loses its credential deny",
        '"secretsmanager:BatchGetSecretValue",',
        "",
        "assessment does not explicitly deny secretsmanager:BatchGetSecretValue",
    ),
    (
        "assessment loses its evidence-write deny",
        '      "s3:PutObject",\n      "s3:DeleteObject",\n      "s3:DeleteObjectVersion",',
        '      "s3:DeleteObject",\n      "s3:DeleteObjectVersion",',
        "assessment is not denied writing acquisition evidence",
    ),
    (
        "a trust policy is added",
        'resource "aws_iam_policy" "qualification_acquisition" {',
        'resource "aws_iam_role" "qualification_acquisition" {',
        "declares an identity or attachment",
    ),
    (
        "a live data source is added",
        'data "aws_iam_policy_document" "qualification_acquisition" {',
        'data "aws_caller_identity" "qualification_acquisition" {',
        "declares a data source that is not a policy document",
    ),
    (
        "a dataset prefix is dropped",
        '"${aws_s3_bucket.licensed.arn}/bronze/sharadar/actions/qualification/*",',
        "",
        "acquisition cannot write a required prefix",
    ),
    (
        "an unexpected prefix is added",
        '"${aws_s3_bucket.licensed.arn}/bronze/sharadar/actions/acquisitions/*",',
        '"${aws_s3_bucket.licensed.arn}/bronze/sharadar/actions/acquisitions/*",\n'
        '    "${aws_s3_bucket.licensed.arn}/silver/*",',
        "unexpected prefix",
    ),
    (
        "the control bucket is named",
        "qualification_locator_objects = "
        '"${aws_s3_bucket.licensed.arn}/qualification/sharadar/locators/*"',
        "qualification_locator_objects = "
        '"${aws_s3_bucket.control.arn}/qualification/sharadar/locators/*"',
        "names the control bucket",
    ),
)


class TestMutations:
    @pytest.mark.parametrize(
        ("label", "before", "after", "expected"), MUTATIONS, ids=[m[0] for m in MUTATIONS]
    )
    def test_each_mutation_is_caught(
        self, label: str, before: str, after: str, expected: str
    ) -> None:
        text = _real_text()
        assert before in text, f"the {label!r} mutation no longer applies to the file"
        mutated = text.replace(before, after, 1)
        assert mutated != text, f"the {label!r} mutation changed nothing"
        found = violations(analyse(mutated))
        assert any(expected in entry for entry in found), (
            f"{label}: expected a violation containing {expected!r}, got {found}"
        )

    def test_the_unmutated_file_is_the_control(self) -> None:
        """Every mutation above is compared against a clean baseline of zero."""
        assert violations(analyse(_real_text())) == []


class TestNegativeControls:
    """A suite that passes on nothing is not a suite."""

    def test_an_empty_document_fails(self) -> None:
        assert violations(analyse(""))

    def test_an_unrelated_document_fails(self) -> None:
        assert violations(analyse('resource "aws_s3_bucket" "x" {\n  bucket = "y"\n}\n'))

    def test_a_document_with_the_right_names_but_no_statements_fails(self) -> None:
        text = (
            'data "aws_iam_policy_document" "qualification_acquisition" {\n}\n'
            'data "aws_iam_policy_document" "qualification_assessment" {\n}\n'
            'resource "aws_iam_policy" "qualification_acquisition" {\n  name = "a"\n}\n'
            'resource "aws_iam_policy" "qualification_assessment" {\n  name = "b"\n}\n'
        )
        assert violations(analyse(text))


# ---------------------------------------------------------------------------
# Canonical formatting, checked offline because `terraform fmt` may not be available
# ---------------------------------------------------------------------------
#
# A test suite cannot assume a `terraform` binary: it is not a declared dependency of
# this repository, and where it is absent `terraform fmt -check` is unavailable and a
# candidate would ship with its formatting merely believed. (It IS present on the
# workstation this section was last exercised on, and the ADR-0021 principals
# candidate was checked with it as well as here -- which is a fact about one machine
# on one day, not a property this suite may rely on.) This checks the subset of
# `terraform fmt`'s output that can be decided
# from the text alone: two-space indentation, no tabs, no trailing whitespace, one
# final newline, and `=` alignment across each run of consecutive single-line
# attributes inside one block.
#
# **The pre-existing files are the control.** They were written and
# committed under a working `terraform fmt`, so a checker that reported them as
# unformatted would be wrong about the rule rather than right about the file --
# which is exactly the failure a hand-rolled formatter check invites.


def formatting_violations(text: str) -> list[str]:
    """Every canonical-formatting rule ``text`` breaks."""
    broken: list[str] = []
    if "\t" in text:
        broken.append("contains a tab")
    if text and not text.endswith("\n"):
        broken.append("does not end with a newline")
    if text.endswith("\n\n"):
        broken.append("ends with a blank line")

    masked = _strip_noise(text).splitlines()
    lines = text.splitlines()
    for number, line in enumerate(lines, start=1):
        if line != line.rstrip():
            broken.append(f"line {number} has trailing whitespace")
        indent = len(line) - len(line.lstrip(" "))
        if line.strip() and indent % 2:
            broken.append(f"line {number} is indented by {indent}, which is not a multiple of two")

    # An attribute line is one that assigns and closes on the same line. Depth is
    # tracked on the masked copy so a bracket inside a string or a comment cannot
    # open a continuation.
    group: list[tuple[int, int, str]] = []
    depth = 0
    for number, mask in enumerate(masked, start=1):
        opening = sum(mask.count(character) for character in "([")
        closing = sum(mask.count(character) for character in ")]")
        assignment = re.match(r"^(\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*)=(\s)", mask)
        single_line = assignment is not None and depth == 0 and opening == closing
        if single_line and assignment is not None:
            indent = len(assignment.group(1))
            column = len(assignment.group(1)) + len(assignment.group(2)) + len(assignment.group(3))
            group.append((indent, column, f"line {number}"))
        else:
            broken.extend(_alignment_violations(group))
            group = []
        depth += opening - closing
    broken.extend(_alignment_violations(group))
    return broken


def _alignment_violations(group: list[tuple[int, int, str]]) -> list[str]:
    """`terraform fmt` aligns each run of consecutive single-line attributes."""
    if len(group) < 2:
        return []
    indents = {indent for indent, _, _ in group}
    if len(indents) != 1:
        return []
    columns = {column for _, column, _ in group}
    if len(columns) == 1:
        return []
    return [f"misaligned '=' across {group[0][2]}..{group[-1][2]}: columns {sorted(columns)}"]


TRACKED_TF = sorted(INFRA.glob("*.tf"))


class TestCanonicalFormatting:
    def test_every_terraform_file_is_canonically_formatted(self) -> None:
        offenders = {
            path.name: formatting_violations(path.read_text(encoding="utf-8"))
            for path in TRACKED_TF
        }
        found = {name: issues for name, issues in offenders.items() if issues}
        assert found == {}, f"terraform fmt would rewrite: {found}"

    def test_the_pre_existing_files_are_the_control(self) -> None:
        """They were committed under a working `terraform fmt`; there are enough of them."""
        assert len(TRACKED_TF) >= 12
        assert QUALIFICATION_TF in TRACKED_TF

    @pytest.mark.parametrize(
        ("label", "sample", "expected"),
        [
            ("a tab", 'locals {\n\ta = "1"\n}\n', "tab"),
            ("trailing whitespace", 'locals {\n  a = "1" \n}\n', "trailing whitespace"),
            ("odd indentation", 'locals {\n   a = "1"\n}\n', "not a multiple of two"),
            ("no final newline", 'locals {\n  a = "1"\n}', "does not end with a newline"),
            ("misaligned attributes", 'locals {\n  ab = "1"\n  c = "2"\n}\n', "misaligned"),
        ],
        ids=lambda value: value if isinstance(value, str) and " " in value else "",
    )
    def test_the_formatting_checker_catches_each_defect(
        self, label: str, sample: str, expected: str
    ) -> None:
        found = formatting_violations(sample)
        assert any(expected in entry for entry in found), f"{label}: {found}"

    def test_the_formatting_checker_accepts_canonical_text(self) -> None:
        assert formatting_violations('locals {\n  ab = "1"\n  c  = "2"\n}\n') == []


# ---------------------------------------------------------------------------
# The merged foundation, as the status documents record it
# ---------------------------------------------------------------------------
#
# The Terraform above is checked by parsing it. This half checks the *claim*
# the status documents make about it, because the two can drift apart in a way
# neither the parser nor a reader notices: PR #52 put two reviewed
# `aws_iam_policy` declarations into source control, and every later gate --
# `terraform init`, plan, apply, an AWS resource, a role, a trust principal, an
# attachment, an authority -- stayed closed. A document that loses either half
# of that is wrong in a way that matters.
#
# The audit's own scanners and phrase lists are driven rather than restated. A
# test carrying its own copy of a required phrase proves nothing about the
# phrase the guard actually looks for, and every mutation below is applied to
# in-memory text: no tracked file is written, and no private material is read.


def _audit_module() -> ModuleType:
    """Load the audit by path, to *run* its guards rather than restate them.

    ``scripts`` is not an importable package. The module is registered in
    ``sys.modules`` before execution because the audit defines a ``@dataclass``,
    and ``dataclasses`` resolves the defining module through that entry.

    Importing it defines constants and functions. It runs no check, opens no
    socket and reaches no service -- ``main()`` is behind the usual guard.
    """
    spec = importlib.util.spec_from_file_location("kalpamani_phase3_docs_audit", AUDIT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GUARD = _audit_module()

REQUIRED: tuple[tuple[str, str], ...] = GUARD.QUALIFICATION_IAM_STATUS_REQUIRED
FORBIDDEN: tuple[str, ...] = GUARD.QUALIFICATION_IAM_STATUS_FORBIDDEN
PLAN_REQUIRED: tuple[tuple[str, str], ...] = GUARD.QUALIFICATION_IAM_PLAN_REQUIRED

#: The heading that ends the section in each document, read from the audit so a
#: test cannot disagree with the guard about where the boundary is.
TERMINATORS: dict[str, str] = dict(GUARD.QUALIFICATION_IAM_SECTION_TERMINATORS)


def flat(text: str) -> str:
    """Whitespace-collapsed, emphasis-stripped, lowercased -- the audit's own reading."""
    return " ".join(text.replace("**", "").split()).lower()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def missing(text: str) -> list[str]:
    """Every required clause the reading does not carry, by label."""
    return [label for label, phrase in REQUIRED if phrase not in text]


def overstated(text: str) -> list[str]:
    """Every forbidden claim the reading does carry."""
    return [claim for claim in FORBIDDEN if claim in text]


def clause(label: str) -> str:
    """The exact phrase a labelled requirement asserts, read from the audit."""
    for candidate, phrase in REQUIRED:
        if candidate == label:
            return phrase
    raise AssertionError(f"no requirement labelled {label!r}")


def split_at_section(document: Path) -> tuple[str, str, str]:
    """``(before, section, after)`` for a document's one qualification-IAM section.

    The split is made on the audit's own extractor, so a test cannot disagree
    with the guard about where the section begins and ends.
    """
    text = read(document)
    found = GUARD.scan_qualification_iam_status_sections(text)
    assert not found.defects, f"{document.name}: {found.defects}"
    assert len(found.sections) == 1, f"{document.name}: {len(found.sections)} sections"
    section = str(found.sections[0])
    before, separator, after = text.partition(section)
    assert separator == section, f"{document.name}: the section is not verbatim in the document"
    return before, section, after


def drop_inside_section(document: Path, label: str) -> tuple[str, str, str, str]:
    """Remove one required clause from the qualification-IAM section only.

    Returns ``(phrase, mutated section reading, mutated whole-document reading,
    unchanged outside reading)``.
    """
    phrase = clause(label)
    before, section, after = split_at_section(document)
    reading = flat(section)
    assert phrase in reading, f"{document.name}: absent before removal: {phrase}"
    mutated = reading.replace(phrase, "")
    assert phrase not in mutated, f"{document.name}: still present after removal: {phrase}"
    outside = flat(before) + " " + flat(after)
    whole = flat(before) + " " + mutated + " " + flat(after)
    return phrase, mutated, whole, outside


DOCUMENTS = [PROJECT_ROOT / "CLAUDE.md", PROJECT_ROOT / "README.md"]
PLAN = PROJECT_ROOT / "docs" / "phase3" / "implementation-plan.md"


class TestTheFoundationStatusIsRecorded:
    """The unmutated repository satisfies every guard. The control for the rest."""

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_each_document_carries_exactly_one_section(self, document: Path) -> None:
        found = GUARD.scan_qualification_iam_status_sections(read(document))
        assert found.defects == ()
        assert len(found.sections) == 1

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_every_required_clause_is_present_in_the_section(self, document: Path) -> None:
        _before, section, _after = split_at_section(document)
        assert missing(flat(section)) == []

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_no_forbidden_claim_is_made_anywhere_in_the_document(self, document: Path) -> None:
        assert overstated(flat(read(document))) == []

    def test_the_plan_carries_every_required_clause(self) -> None:
        reading = flat(read(PLAN))
        assert [label for label, phrase in PLAN_REQUIRED if phrase not in reading] == []

    def test_both_documents_carry_the_same_subsections_in_order(self) -> None:
        titles = {
            document.name: GUARD._section_subsection_titles(
                GUARD.scan_qualification_iam_status_sections(read(document)).sections
            )
            for document in DOCUMENTS
        }
        assert len(set(titles.values())) == 1, titles
        assert titles["CLAUDE.md"] == GUARD.QUALIFICATION_IAM_STATUS_SUBSECTIONS


class TestSectionLocalDeletionIsCaught:
    """Deleting a clause from the section is caught even when a copy survives elsewhere.

    This is the defect section scoping exists for. Most of these clauses are also
    spelled in a neighbouring status block -- "run a: not authorized / not run"
    appears in three -- so a flat whole-file scan is answered by the neighbour's
    copy and reports nothing.
    """

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    @pytest.mark.parametrize("label", [label for label, _ in REQUIRED])
    def test_removing_one_required_clause_is_reported(self, document: Path, label: str) -> None:
        phrase, mutated, _whole, _outside = drop_inside_section(document, label)
        assert label in missing(mutated), f"{document.name}: undetected removal of {phrase}"

    def test_at_least_one_deletion_would_have_escaped_a_whole_file_scan(self) -> None:
        """Section scope is doing real work, and this names how much.

        A duplicated clause deleted from the section is still present in the file,
        so the flat reading a file-wide guard uses stays green. If this ever found
        none, section scoping would be decoration.
        """
        escaped: list[tuple[str, str]] = []
        for document in DOCUMENTS:
            for label, _phrase in REQUIRED:
                phrase, mutated, whole, outside = drop_inside_section(document, label)
                assert label in missing(mutated)
                if phrase in whole:
                    assert outside.count(phrase) >= 1
                    escaped.append((document.name, label))
        assert escaped, "no required clause is duplicated outside the section"


class TestSectionStructureMutations:
    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_removing_the_whole_section_is_caught(self, document: Path) -> None:
        before, section, after = split_at_section(document)
        assert section, f"{document.name}: nothing to remove"
        found = GUARD.scan_qualification_iam_status_sections(before + after)
        assert found.sections == ()
        assert missing(flat(before + after)) != []

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_duplicating_the_section_is_caught(self, document: Path) -> None:
        before, section, after = split_at_section(document)
        found = GUARD.scan_qualification_iam_status_sections(before + section + section + after)
        assert len(found.sections) == 2, "a second copy must be visible as a second section"

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_demoting_the_heading_is_caught(self, document: Path) -> None:
        text = read(document)
        heading = f"### {GUARD.QUALIFICATION_IAM_STATUS_HEADING}"
        assert text.count(heading + "\n") == 1, f"{document.name}: heading not found once"
        demoted = text.replace(heading + "\n", f"#### {GUARD.QUALIFICATION_IAM_STATUS_HEADING}\n")
        found = GUARD.scan_qualification_iam_status_sections(demoted)
        assert found.sections == ()
        assert found.defects, "a heading at the wrong level must be reported as a defect"

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_a_foreign_subsection_is_caught(self, document: Path) -> None:
        before, section, after = split_at_section(document)
        marker = "#### Status\n"
        assert section.count(marker) == 1, f"{document.name}: no Status subsection"
        intruded = section.replace(marker, "#### Deployment evidence\n" + marker, 1)
        found = GUARD.scan_qualification_iam_status_sections(before + intruded + after)
        assert any("Deployment evidence" in defect for defect in found.defects), found.defects

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_the_real_section_ends_at_its_declared_boundary(self, document: Path) -> None:
        text = read(document)
        _before, section, _after = split_at_section(document)
        assert GUARD.qualification_iam_section_is_terminated(
            text, section, TERMINATORS[document.name]
        )

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_deleting_the_terminator_lets_the_section_swallow_its_neighbour(
        self, document: Path
    ) -> None:
        """A boundary that drifts is measuring somebody else's text, and must fail.

        The subsection guard alone does not see this. A swallowed neighbour that
        carries no headings of its own -- CLAUDE.md's, exactly -- raises no foreign
        heading, so the section silently extends to the end of the file. That is
        why the boundary is named and checked rather than inferred, and this drives
        the named check.
        """
        text = read(document)
        terminator = TERMINATORS[document.name]
        assert text.count(terminator + "\n") == 1, f"{document.name}: terminator not found once"
        widened = text.replace(terminator + "\n", "", 1)
        assert widened != text
        found = GUARD.scan_qualification_iam_status_sections(widened)
        assert len(found.sections) == 1, "the section is still extracted, and now too wide"
        assert not GUARD.qualification_iam_section_is_terminated(
            widened, str(found.sections[0]), terminator
        ), "a section running past its declared boundary must be reported"


class TestForwardDriftMutations:
    """A merged declaration read as a deployed, attached or authorized resource."""

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    @pytest.mark.parametrize(
        ("target", "replacement", "expected"),
        [
            (
                "terraform initialization for these declarations: not performed",
                "terraform initialization for these declarations: completed",
                "terraform initialization for these declarations: completed",
            ),
            (
                "terraform plan for these declarations: not authorized / not run",
                "terraform plan for these declarations: completed",
                "terraform plan for these declarations: completed",
            ),
            (
                "terraform apply for these declarations: not authorized / not run",
                "terraform apply for these declarations: completed",
                "terraform apply for these declarations: completed",
            ),
            (
                "aws managed-policy resource creation from these declarations: not performed "
                "/ not established",
                "aws managed-policy resource creation from these declarations: performed",
                "aws managed-policy resource creation from these declarations: performed",
            ),
            (
                "runtime roles: not implemented",
                "runtime roles: implemented",
                "runtime roles: implemented",
            ),
            (
                "runtime trust principals: not selected",
                "runtime trust principals: selected",
                "runtime trust principals: selected",
            ),
            (
                "policy attachments: not implemented",
                "policy attachments: implemented",
                "policy attachments: implemented",
            ),
            (
                "therefore this merge grants no principal any aws authority",
                "therefore this merge grants a principal aws authority",
                "this merge grants a principal aws authority",
            ),
            ("g1: open", "g1: closed", "g1: closed"),
            ("g2: open", "g2: closed", "g2: closed"),
            ("phase 3: not complete", "phase 3: complete", "phase 3: complete"),
            ("control: deferred", "control: published", "control: published"),
            ("live trading: hard-disabled", "live trading: enabled", "live trading: enabled"),
            ("run a: not authorized / not run", "run a: completed", "run a: completed"),
            ("run b: not authorized / not run", "run b: completed", "run b: completed"),
            (
                "combined assessment: not authorized / not run",
                "combined assessment: completed",
                "combined assessment: completed",
            ),
        ],
        ids=lambda value: value.split(":")[0] if isinstance(value, str) else "",
    )
    def test_an_overstatement_is_reported(
        self, document: Path, target: str, replacement: str, expected: str
    ) -> None:
        reading = flat(read(document))
        assert target in reading, f"{document.name}: absent before replacement: {target}"
        assert expected not in reading, f"{document.name}: already overstated: {expected}"
        mutated = reading.replace(target, replacement)
        assert mutated != reading, f"{document.name}: mutation changed nothing"
        assert expected in overstated(mutated), f"{document.name}: undetected: {expected}"

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    @pytest.mark.parametrize(
        "injected",
        [
            "aws managed policies were created",
            "aws managed policies have been created",
            "aws policies attached",
            "qualification iam policies deployed",
            "qualification iam policies applied",
            "qualification runtime role implemented",
            "qualification trust principal selected",
            "qualification infrastructure ready",
            "qualification infrastructure deployed",
            "terraform plan completed",
            "terraform apply completed",
            "aws qualification access authorized",
            "a production provider is selected",
        ],
        ids=lambda value: value.replace(" ", "-"),
    )
    def test_an_injected_claim_is_reported(self, document: Path, injected: str) -> None:
        reading = flat(read(document))
        assert injected not in reading, f"{document.name}: already present: {injected}"
        assert injected in overstated(reading + " " + injected), f"undetected: {injected}"


class TestReverseDriftMutations:
    """The pre-merge state, reasserted. PR #52 ended it, and a revert must fail."""

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    @pytest.mark.parametrize(
        "injected",
        [
            "qualification iam policy terraform declarations: absent",
            "qualification iam policy terraform declarations: not merged",
            "qualification iam policy terraform declarations: proposed",
            "qualification iam policy terraform declarations: awaiting review",
            "pr #52 is open",
            "pr #52 remains unmerged",
            "pr #52 is awaiting review",
            "pr #52: open / unmerged",
            "the offline qualification iam policy candidate is not merged",
            "no qualification terraform exists",
            "the qualification permission sets are expressed nowhere in terraform",
        ],
        ids=lambda value: value.replace(" ", "-"),
    )
    def test_a_reverted_claim_is_reported(self, document: Path, injected: str) -> None:
        reading = flat(read(document))
        assert injected not in reading, f"{document.name}: already present: {injected}"
        assert injected in overstated(reading + " " + injected), f"undetected: {injected}"

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_replacing_the_merged_status_with_the_proposed_one_is_reported(
        self, document: Path
    ) -> None:
        target = "qualification iam policy terraform declarations: merged / in main / "
        target += "offline-reviewed"
        replacement = "qualification iam policy terraform declarations: proposed"
        reading = flat(read(document))
        assert target in reading, f"{document.name}: absent before replacement: {target}"
        mutated = reading.replace(target, replacement)
        assert replacement in overstated(mutated)
        assert "records the merged declarations" in missing(
            flat(split_at_section(document)[1]).replace(target, replacement)
        )

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_removing_the_next_gate_trust_principal_requirement_is_reported(
        self, document: Path
    ) -> None:
        """The clause that keeps the next gate architectural, not operational."""
        phrase, mutated, _whole, _outside = drop_inside_section(
            document, "names the next architecture gate"
        )
        assert "the next architecture gate must choose the execution principal" in phrase
        assert "names the next architecture gate" in missing(mutated)

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_removing_the_undetermined_principal_clause_is_reported(self, document: Path) -> None:
        _phrase, mutated, _whole, _outside = drop_inside_section(
            document, "records the undetermined principal"
        )
        assert "records the undetermined principal" in missing(mutated)


class TestTheGuardsAreNotTautological:
    def test_legitimate_conditional_and_historical_wording_is_accepted(self) -> None:
        """A guard a correct document cannot satisfy is a guard somebody deletes.

        Every line here is honest prose a future editor would reasonably write,
        and none of it may be refused. The first is the load-bearing distinction
        the whole section exists to make.
        """
        honest = [
            "does not mean aws managed policies created",
            "does not mean terraform initialized, planned or applied",
            "does not mean roles, trust principals or attachments selected or implemented",
            "does not mean any principal received authority",
            "does not mean qualification infrastructure is deployable or executable",
            "if a later apply is authorized, the declarations would create two managed policies",
            "before pr #52 merged, no qualification terraform existed in main",
            "while pr #52 was open it was an unmerged implementation candidate",
            "run a: not authorized / not run",
            "terraform apply for these declarations: not authorized / not run",
            "whether any live aws policy exists is not established",
            "no live aws policy is described here as unattached",
            "the declarations are unattached by design",
        ]
        for sentence in honest:
            assert overstated(sentence) == [], f"falsely refused: {sentence}"

    def test_an_empty_document_fails_required_presence(self) -> None:
        assert GUARD.scan_qualification_iam_status_sections("").sections == ()
        assert len(missing("")) == len(REQUIRED)

    def test_an_unrelated_document_fails_required_presence(self) -> None:
        unrelated = "# Something else\n\nNothing about qualification infrastructure at all.\n"
        assert GUARD.scan_qualification_iam_status_sections(unrelated).sections == ()
        assert missing(flat(unrelated)) != []

    def test_every_required_phrase_is_distinct(self) -> None:
        phrases = [phrase for _label, phrase in REQUIRED]
        assert len(set(phrases)) == len(phrases)
        labels = [label for label, _phrase in REQUIRED]
        assert len(set(labels)) == len(labels)

    def test_no_forbidden_claim_is_a_substring_of_a_required_one(self) -> None:
        """Otherwise satisfying the guard would be impossible, in both directions."""
        offenders = [
            (claim, phrase) for claim in FORBIDDEN for _label, phrase in REQUIRED if claim in phrase
        ]
        assert offenders == []

    def test_the_scanner_holds_no_state_across_documents(self) -> None:
        """Two documents scanned in either order give the same answer."""
        claude, readme = read(DOCUMENTS[0]), read(DOCUMENTS[1])
        forward = (
            GUARD.scan_qualification_iam_status_sections(claude),
            GUARD.scan_qualification_iam_status_sections(readme),
        )
        backward = (
            GUARD.scan_qualification_iam_status_sections(readme),
            GUARD.scan_qualification_iam_status_sections(claude),
        )
        assert forward[0] == backward[1]
        assert forward[1] == backward[0]
        assert GUARD.scan_qualification_iam_status_sections("").sections == ()
        assert GUARD.scan_qualification_iam_status_sections(claude) == forward[0]

    def test_one_documents_reading_cannot_satisfy_the_others(self) -> None:
        """The guard is per file, because merged main has twice disagreed with itself."""
        claude_section = flat(split_at_section(DOCUMENTS[0])[1])
        readme_section = flat(split_at_section(DOCUMENTS[1])[1])
        assert missing(claude_section) == []
        assert missing(readme_section) == []
        label = "records the merged declarations"
        gutted = claude_section.replace(clause(label), "")
        assert label in missing(gutted)
        assert label not in missing(readme_section)


# ---------------------------------------------------------------------------
# The ADR-0021 runtime principals, parsed the same way
# ---------------------------------------------------------------------------
#
# `qualification_principals.tf` is the second OFFLINE candidate in this package. It
# names the holder PR #52 deliberately left unnamed: two Identity Center permission
# sets, one customer-managed-policy reference each, and two group-principal account
# assignments. Nothing here contacts AWS, runs Terraform or reads state.
#
# The rules below are functions over the parsed configuration, for the reason the
# policy rules above are: a substring scan cannot tell a permission set from an IAM
# role, cannot tell which policy a reference names, and reports every deliberate
# omission explained in a comment as a violation.

PRINCIPALS_TF = INFRA / "qualification_principals.tf"

#: The exact permission-set names ADR-0021 accepts, per actor label.
PERMISSION_SET_NAMES = {
    ACQUISITION: "KalpaManiQualificationAcquire",
    ASSESSMENT: "KalpaManiQualificationAssessment",
}

#: One hour, as an ISO-8601 duration. Bounded rather than raised.
SESSION_DURATION = "PT1H"

#: The three unresolved environment bindings, and nothing else. Every one must be
#: declared without a default: a default here is either wrong everywhere or is a real
#: environment value committed to a public repository.
PRINCIPAL_VARIABLES = (
    "identity_center_instance_arn",
    "qualification_operator_group_id",
    "qualification_target_account_id",
)

#: Resource types this candidate is allowed to declare. Anything else -- a role, a
#: user, an access key, an instance profile, a bucket, a KMS key -- is a violation
#: whether or not its label mentions qualification.
PERMITTED_PRINCIPAL_RESOURCES = frozenset(
    {
        "aws_ssoadmin_permission_set",
        "aws_ssoadmin_customer_managed_policy_attachment",
        "aws_ssoadmin_account_assignment",
    }
)

#: Literal shapes that would mean a live environment value was committed. The
#: twelve-digit pattern is the one most likely to arrive by accident, pasted from a
#: console URL; the rest are the values ADR-0021 keeps unresolved and unread.
PRINCIPAL_LITERAL_PATTERNS = {
    "a twelve-digit account id": re.compile(r"(?<![\d.])\d{12}(?![\d.])"),
    "an Identity Center instance id": re.compile(r"ssoins-[0-9a-zA-Z]"),
    "an identity-store or group UUID": re.compile(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    ),
    "an SSO start URL": re.compile(r"awsapps\.com"),
    "a generated role name": re.compile(r"AWSReservedSSO_"),
    "an account-bearing ARN": re.compile(r"arn:aws:[a-z0-9-]*:[a-z0-9-]*:\d{12}:"),
}


@dataclass(frozen=True)
class Principals:
    """One parsed principals document, with `local.*` references resolved."""

    blocks: tuple[Block, ...]
    locals_: dict[str, tuple[str, ...]]
    variables: dict[str, Block]
    resources: dict[tuple[str, str], Block]


def analyse_principals(text: str) -> Principals:
    """Parse the principals document and index its variables and resources."""
    blocks = tuple(parse_hcl(text))
    locals_: dict[str, tuple[str, ...]] = {}
    for block in blocks:
        if block.type != "locals":
            continue
        for name, expression in block.attributes.items():
            locals_[name] = _resolve(expression, locals_)

    variables = {block.labels[0]: block for block in blocks if block.type == "variable"}
    resources = {
        (block.labels[0], block.labels[1]): block
        for block in blocks
        if block.type == "resource" and len(block.labels) == 2
    }
    return Principals(blocks, locals_, variables, resources)


def _one(config: Principals, expression: str) -> str | None:
    """The single literal ``expression`` denotes, or ``None`` if it is not exactly one."""
    values = _resolve(expression, config.locals_)
    return values[0] if len(values) == 1 else None


def _permission_set_rules(config: Principals) -> list[str]:
    broken: list[str] = []
    for actor, expected in PERMISSION_SET_NAMES.items():
        block = config.resources.get(("aws_ssoadmin_permission_set", actor))
        if block is None:
            broken.append(f"{actor} declares no permission set")
            continue
        if _one(config, block.attributes.get("name", "")) != expected:
            broken.append(f"{actor} permission-set name is not {expected}")
        if _one(config, block.attributes.get("session_duration", "")) != SESSION_DURATION:
            broken.append(f"{actor} session duration is not {SESSION_DURATION}")
        if block.attributes.get("instance_arn") != "var.identity_center_instance_arn":
            broken.append(f"{actor} permission set does not take the unresolved instance input")
    return broken


def _policy_reference_rules(config: Principals) -> list[str]:
    broken: list[str] = []
    for actor in (ACQUISITION, ASSESSMENT):
        other = ASSESSMENT if actor == ACQUISITION else ACQUISITION
        block = config.resources.get(("aws_ssoadmin_customer_managed_policy_attachment", actor))
        if block is None:
            broken.append(f"{actor} declares no customer-managed-policy reference")
            continue
        references = block.children("customer_managed_policy_reference")
        if len(references) != 1:
            broken.append(f"{actor} declares {len(references)} policy references, not one")
            continue
        reference = references[0]
        if reference.attributes.get("name") != f"aws_iam_policy.{actor}.name":
            broken.append(f"{actor} does not reference its own merged managed policy")
        if reference.attributes.get("path") != f"aws_iam_policy.{actor}.path":
            broken.append(f"{actor} does not take the path of its own merged managed policy")
        if f"aws_iam_policy.{other}" in str(sorted(reference.attributes.values())):
            broken.append(f"{actor} references the {other} managed policy")
        if block.attributes.get("permission_set_arn") != f"aws_ssoadmin_permission_set.{actor}.arn":
            broken.append(f"{actor} attaches its policy to another permission set")
    return broken


#: A `depends_on` entry is a bare resource address, not a quoted string, so
#: :func:`string_list` reads nothing out of one. This finds the addresses instead.
_RESOURCE_ADDRESS = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)+")


def depends_on(block: Block) -> tuple[str, ...]:
    """Every resource address in ``block``'s explicit `depends_on`, in declared order."""
    return tuple(_RESOURCE_ADDRESS.findall(block.attributes.get("depends_on", "")))


def _assignment_rules(config: Principals) -> list[str]:
    broken: list[str] = []
    for actor in (ACQUISITION, ASSESSMENT):
        other = ASSESSMENT if actor == ACQUISITION else ACQUISITION
        block = config.resources.get(("aws_ssoadmin_account_assignment", actor))
        if block is None:
            broken.append(f"{actor} declares no account assignment")
            continue
        if _one(config, block.attributes.get("principal_type", "")) != "GROUP":
            broken.append(f"{actor} assignment principal is not a GROUP")
        if block.attributes.get("principal_id") != "var.qualification_operator_group_id":
            broken.append(f"{actor} assignment does not take the governed operator group input")
        if _one(config, block.attributes.get("target_type", "")) != "AWS_ACCOUNT":
            broken.append(f"{actor} assignment target type is not AWS_ACCOUNT")
        if block.attributes.get("target_id") != "var.qualification_target_account_id":
            broken.append(f"{actor} assignment does not take the unresolved account input")
        expected_set = f"aws_ssoadmin_permission_set.{actor}.arn"
        if block.attributes.get("permission_set_arn") != expected_set:
            broken.append(f"{actor} assignment names another permission set")
        # The ordering edge, and why it cannot be left implicit. An assignment and
        # its policy attachment both reference the permission set and neither
        # references the other, so Terraform sees two siblings and may create them
        # in either order. The assignment is what provisions the permission set
        # into the target account, so running it first opens a real window in which
        # the generated role exists carrying none of its intended permissions.
        # `depends_on` is the only way to say this here: an assignment consumes no
        # attribute of an attachment, so there is no reference to carry the edge.
        ordering = depends_on(block)
        own = f"aws_ssoadmin_customer_managed_policy_attachment.{actor}"
        if own not in ordering:
            broken.append(f"{actor} assignment is not ordered after its own policy attachment")
        if f"aws_ssoadmin_customer_managed_policy_attachment.{other}" in ordering:
            broken.append(f"{actor} assignment is ordered after the {other} policy attachment")
    return broken


def _shape_rules(config: Principals) -> list[str]:
    broken: list[str] = []
    for block in config.blocks:
        if block.type == "data":
            broken.append(f"declares a data source: {block.labels}")
        if block.type in ("provider", "terraform", "backend", "module"):
            broken.append(f"declares a {block.type} block")
        if block.type != "resource":
            continue
        if block.labels[0] not in PERMITTED_PRINCIPAL_RESOURCES:
            broken.append(f"declares an unpermitted resource type: {block.labels[0]}")
        elif block.labels[1] not in (ACQUISITION, ASSESSMENT):
            broken.append(f"declares a resource for an unknown actor: {block.labels[1]}")
        if "assume_role_policy" in block.attributes:
            broken.append("declares a trust policy")
        if "inline_policy" in block.attributes:
            broken.append("declares an inline permission-set policy")
    return broken


def _input_rules(config: Principals) -> list[str]:
    broken: list[str] = []
    for name in PRINCIPAL_VARIABLES:
        block = config.variables.get(name)
        if block is None:
            broken.append(f"the {name} input is not declared")
    for name, block in config.variables.items():
        if "default" in block.attributes:
            broken.append(f"the {name} input has a default")
        if not block.children("validation"):
            broken.append(f"the {name} input is unvalidated")
    return broken


def principal_violations(config: Principals) -> list[str]:
    """Every ADR-0021 rule the parsed principals document breaks."""
    return (
        _shape_rules(config)
        + _permission_set_rules(config)
        + _policy_reference_rules(config)
        + _assignment_rules(config)
        + _input_rules(config)
    )


def literal_violations(text: str) -> list[str]:
    """Every live-environment literal shape present in ``text``."""
    return [label for label, pattern in PRINCIPAL_LITERAL_PATTERNS.items() if pattern.search(text)]


def _principals_text() -> str:
    return PRINCIPALS_TF.read_text(encoding="utf-8")


@pytest.fixture
def principals() -> Principals:
    return analyse_principals(_principals_text())


class TestThePrincipalsCandidate:
    def test_the_candidate_exists(self) -> None:
        assert PRINCIPALS_TF.is_file(), "the ADR-0021 principals candidate is missing"

    def test_the_real_file_breaks_no_rule(self, principals: Principals) -> None:
        assert principal_violations(principals) == []

    def test_exactly_two_permission_sets_are_declared(self, principals: Principals) -> None:
        declared = sorted(
            label for kind, label in principals.resources if kind == "aws_ssoadmin_permission_set"
        )
        assert declared == [ACQUISITION, ASSESSMENT]

    def test_exactly_two_policy_references_are_declared(self, principals: Principals) -> None:
        declared = sorted(
            label
            for kind, label in principals.resources
            if kind == "aws_ssoadmin_customer_managed_policy_attachment"
        )
        assert declared == [ACQUISITION, ASSESSMENT]

    def test_exactly_two_group_assignments_are_declared(self, principals: Principals) -> None:
        declared = sorted(
            label
            for kind, label in principals.resources
            if kind == "aws_ssoadmin_account_assignment"
        )
        assert declared == [ACQUISITION, ASSESSMENT]

    def test_the_candidate_declares_exactly_six_resources(self, principals: Principals) -> None:
        """Two permission sets, two references, two assignments. Nothing else."""
        assert len(principals.resources) == 6

    def test_both_permission_sets_are_bounded_to_one_hour(self, principals: Principals) -> None:
        for actor in (ACQUISITION, ASSESSMENT):
            block = principals.resources[("aws_ssoadmin_permission_set", actor)]
            assert _one(principals, block.attributes["session_duration"]) == SESSION_DURATION

    def test_each_actor_references_only_its_own_merged_policy(self, principals: Principals) -> None:
        for actor, other in ((ACQUISITION, ASSESSMENT), (ASSESSMENT, ACQUISITION)):
            block = principals.resources[("aws_ssoadmin_customer_managed_policy_attachment", actor)]
            reference = block.children("customer_managed_policy_reference")[0]
            assert reference.attributes["name"] == f"aws_iam_policy.{actor}.name"
            assert other not in reference.attributes["name"]

    def test_both_assignments_target_the_same_unresolved_account_input(
        self, principals: Principals
    ) -> None:
        targets = {
            principals.resources[("aws_ssoadmin_account_assignment", actor)].attributes["target_id"]
            for actor in (ACQUISITION, ASSESSMENT)
        }
        assert targets == {"var.qualification_target_account_id"}

    def test_each_assignment_is_ordered_after_its_own_policy_attachment(
        self, principals: Principals
    ) -> None:
        """The edge the plan gate stopped for: attachment before assignment.

        Both resources reference the permission set and neither references the
        other, so without this Terraform may create the account assignment -- which
        provisions the permission set into the target account -- before the managed
        policy has been attached to it.
        """
        for actor in (ACQUISITION, ASSESSMENT):
            block = principals.resources[("aws_ssoadmin_account_assignment", actor)]
            assert depends_on(block) == (
                f"aws_ssoadmin_customer_managed_policy_attachment.{actor}",
            )

    def test_neither_assignment_is_ordered_after_the_other_actor(
        self, principals: Principals
    ) -> None:
        """An edge across the two actors would couple them at apply time."""
        for actor, other in ((ACQUISITION, ASSESSMENT), (ASSESSMENT, ACQUISITION)):
            block = principals.resources[("aws_ssoadmin_account_assignment", actor)]
            assert all(other not in address for address in depends_on(block))

    def test_the_ordering_edge_reaches_the_matching_managed_policy(
        self, principals: Principals
    ) -> None:
        """Per actor: assignment -> its own attachment -> its own IAM policy."""
        for actor in (ACQUISITION, ASSESSMENT):
            assignment = principals.resources[("aws_ssoadmin_account_assignment", actor)]
            kind, label = depends_on(assignment)[0].split(".")
            assert (kind, label) == ("aws_ssoadmin_customer_managed_policy_attachment", actor)
            reference = principals.resources[(kind, label)].children(
                "customer_managed_policy_reference"
            )[0]
            assert reference.attributes["name"] == f"aws_iam_policy.{actor}.name"
            assert reference.attributes["path"] == f"aws_iam_policy.{actor}.path"

    def test_no_live_discovery_data_source_is_declared(self, principals: Principals) -> None:
        """A data source would read the environment to write a declaration."""
        assert [block.labels for block in principals.blocks if block.type == "data"] == []

    def test_no_identity_role_user_or_key_is_declared(self, principals: Principals) -> None:
        forbidden = {
            "aws_iam_role",
            "aws_iam_role_policy",
            "aws_iam_user",
            "aws_iam_access_key",
            "aws_iam_instance_profile",
            "aws_iam_role_policy_attachment",
            "aws_ssoadmin_managed_policy_attachment",
        }
        assert {kind for kind, _ in principals.resources} & forbidden == set()

    def test_no_trust_policy_service_principal_or_assume_role_appears(self) -> None:
        hcl = GUARD.strip_hcl_comments(_principals_text())
        for token in (
            "assume_role_policy",
            "sts:AssumeRole",
            "amazonaws.com",
            "aws_iam_policy_document",
            "Principal",
        ):
            assert token not in hcl, f"the principals candidate names {token}"

    def test_the_candidate_carries_no_live_environment_literal(self) -> None:
        assert literal_violations(_principals_text()) == []

    def test_none_of_the_three_inputs_has_a_default(self, principals: Principals) -> None:
        for name in PRINCIPAL_VARIABLES:
            assert "default" not in principals.variables[name].attributes

    def test_the_account_input_is_cross_checked_against_the_provider_binding(self) -> None:
        """`allowed_account_ids` constrains the credentials, never the assignment target.

        Without this the two assignments could be created against an account the
        wrong-account guard in providers.tf never looks at.
        """
        hcl = GUARD.strip_hcl_comments(_principals_text())
        assert "contains(var.allowed_account_ids, var.qualification_target_account_id)" in hcl

    def test_the_candidate_changes_no_policy_action_matrix(self) -> None:
        """The two PR #52 documents are referenced, never restated.

        A statement, an action or a resource here would be a second matrix beside the
        reviewed one, and the two could then disagree.
        """
        hcl = GUARD.strip_hcl_comments(_principals_text())
        for token in ("actions", "resources", '"s3:', "statement", "effect"):
            assert token not in hcl, f"the principals candidate carries policy content: {token}"

    def test_the_candidate_introduces_no_wildcard(self) -> None:
        assert '"*"' not in GUARD.strip_hcl_comments(_principals_text())

    def test_the_candidate_touches_no_bucket_encryption_or_kms_resource(self) -> None:
        hcl = GUARD.strip_hcl_comments(_principals_text())
        for token in ("aws_s3_bucket", "aws_kms", "sse_algorithm", "server_side_encryption"):
            assert token not in hcl, f"the principals candidate touches {token}"


#: Each entry mutates the real principals file and names the substring the rule it
#: should trip reports.
PRINCIPAL_MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "the acquisition permission-set name is corrupted",
        'qualification_acquisition_permission_set = "KalpaManiQualificationAcquire"',
        'qualification_acquisition_permission_set = "KalpaManiQualification"',
        "permission-set name is not KalpaManiQualificationAcquire",
    ),
    (
        "the assessment permission-set name is corrupted",
        'qualification_assessment_permission_set  = "KalpaManiQualificationAssessment"',
        'qualification_assessment_permission_set  = "KalpaManiQualificationAcquire"',
        "permission-set name is not KalpaManiQualificationAssessment",
    ),
    (
        "the acquisition permission set is removed",
        'resource "aws_ssoadmin_permission_set" "qualification_acquisition" {',
        'resource "aws_ssoadmin_permission_set" "qualification_removed" {',
        "qualification_acquisition declares no permission set",
    ),
    (
        "the one-hour session bound is raised",
        'qualification_session_duration = "PT1H"',
        'qualification_session_duration = "PT12H"',
        "session duration is not PT1H",
    ),
    (
        "the acquisition managed-policy reference is removed",
        'resource "aws_ssoadmin_customer_managed_policy_attachment" "qualification_acquisition" {',
        'resource "aws_ssoadmin_customer_managed_policy_attachment" "qualification_absent" {',
        "qualification_acquisition declares no customer-managed-policy reference",
    ),
    (
        "the assessment reference names the acquisition policy",
        "name = aws_iam_policy.qualification_assessment.name",
        "name = aws_iam_policy.qualification_acquisition.name",
        "does not reference its own merged managed policy",
    ),
    (
        "the group principal becomes a user",
        'principal_type = "GROUP"',
        'principal_type = "USER"',
        "assignment principal is not a GROUP",
    ),
    (
        "the assignment target type is widened",
        'target_type = "AWS_ACCOUNT"',
        'target_type = "AWS_OU"',
        "assignment target type is not AWS_ACCOUNT",
    ),
    (
        "the account target becomes a literal instead of an input",
        "target_id   = var.qualification_target_account_id",
        'target_id   = "000000000000"',
        "assignment does not take the unresolved account input",
    ),
    (
        "a live-discovery data source is added",
        "locals {",
        'data "aws_ssoadmin_instances" "governed" {\n}\n\nlocals {',
        "declares a data source",
    ),
    (
        "a custom IAM role is added",
        'resource "aws_ssoadmin_permission_set" "qualification_acquisition" {',
        'resource "aws_iam_role" "qualification_acquisition" {',
        "declares an unpermitted resource type: aws_iam_role",
    ),
    (
        "a trust policy is added to a permission set",
        "  session_duration = local.qualification_session_duration",
        '  session_duration   = local.qualification_session_duration\n  assume_role_policy = "{}"',
        "declares a trust policy",
    ),
    (
        "an input gains a default",
        'variable "qualification_operator_group_id" {',
        'variable "qualification_operator_group_id" {\n  default = "governed-group"',
        "the qualification_operator_group_id input has a default",
    ),
    (
        "an input loses its validation",
        "  validation {\n    condition     = "
        'can(regex("^[A-Za-z0-9][A-Za-z0-9-]{0,127}$", var.qualification_operator_group_id))',
        "  validation_removed {\n    condition     = "
        'can(regex("^[A-Za-z0-9][A-Za-z0-9-]{0,127}$", var.qualification_operator_group_id))',
        "the qualification_operator_group_id input is unvalidated",
    ),
    (
        "the instance binding becomes a literal",
        "instance_arn     = var.identity_center_instance_arn",
        'instance_arn     = "arn:aws:sso:::instance/ssoins-1111222233334444"',
        "permission set does not take the unresolved instance input",
    ),
    (
        "an assignment is pointed at the other permission set",
        'resource "aws_ssoadmin_account_assignment" "qualification_assessment" {\n'
        "  instance_arn       = var.identity_center_instance_arn\n"
        "  permission_set_arn = aws_ssoadmin_permission_set.qualification_assessment.arn",
        'resource "aws_ssoadmin_account_assignment" "qualification_assessment" {\n'
        "  instance_arn       = var.identity_center_instance_arn\n"
        "  permission_set_arn = aws_ssoadmin_permission_set.qualification_acquisition.arn",
        "assignment names another permission set",
    ),
    (
        "the acquisition assignment loses its attachment ordering",
        "  depends_on = [\n"
        "    aws_ssoadmin_customer_managed_policy_attachment.qualification_acquisition,\n"
        "  ]\n",
        "",
        "qualification_acquisition assignment is not ordered after its own policy attachment",
    ),
    (
        "the assessment assignment loses its attachment ordering",
        "  depends_on = [\n"
        "    aws_ssoadmin_customer_managed_policy_attachment.qualification_assessment,\n"
        "  ]\n",
        "",
        "qualification_assessment assignment is not ordered after its own policy attachment",
    ),
    (
        "the acquisition assignment is ordered after the assessment attachment",
        "    aws_ssoadmin_customer_managed_policy_attachment.qualification_acquisition,\n",
        "    aws_ssoadmin_customer_managed_policy_attachment.qualification_assessment,\n",
        "qualification_acquisition assignment is ordered after the qualification_assessment "
        "policy attachment",
    ),
    (
        "an assignment is ordered after the permission set instead of the attachment",
        "    aws_ssoadmin_customer_managed_policy_attachment.qualification_assessment,\n",
        "    aws_ssoadmin_permission_set.qualification_assessment,\n",
        "qualification_assessment assignment is not ordered after its own policy attachment",
    ),
)


class TestPrincipalMutations:
    @pytest.mark.parametrize(
        ("label", "before", "after", "expected"),
        PRINCIPAL_MUTATIONS,
        ids=[m[0] for m in PRINCIPAL_MUTATIONS],
    )
    def test_each_mutation_is_caught(
        self, label: str, before: str, after: str, expected: str
    ) -> None:
        text = _principals_text()
        assert before in text, f"the {label!r} mutation no longer applies to the file"
        mutated = text.replace(before, after, 1)
        assert mutated != text, f"the {label!r} mutation changed nothing"
        found = principal_violations(analyse_principals(mutated))
        assert any(expected in entry for entry in found), (
            f"{label}: expected a violation containing {expected!r}, got {found}"
        )

    def test_the_unmutated_file_is_the_control(self) -> None:
        assert principal_violations(analyse_principals(_principals_text())) == []

    @pytest.mark.parametrize(
        ("label", "injected"),
        [
            ("an account id", 'locals {\n  leaked = "123456789012"\n}\n'),
            ("an instance id", 'locals {\n  leaked = "ssoins-1234567890abcdef"\n}\n'),
            ("a group UUID", 'locals {\n  leaked = "12345678-1234-1234-1234-123456789012"\n}\n'),
            ("a start URL", 'locals {\n  leaked = "https://example.awsapps.com/start"\n}\n'),
            (
                "a generated role name",
                'locals {\n  leaked = "AWSReservedSSO_KalpaManiQualificationAcquire_abc"\n}\n',
            ),
            (
                "an account-bearing ARN",
                'locals {\n  leaked = "arn:aws:iam::123456789012:policy/x"\n}\n',
            ),
        ],
        ids=lambda value: value if isinstance(value, str) and " " in value else "",
    )
    def test_an_injected_live_literal_is_caught(self, label: str, injected: str) -> None:
        text = _principals_text()
        assert literal_violations(text) == []
        assert literal_violations(text + injected), label


class TestPrincipalNegativeControls:
    """A rule set that passes on nothing is not a rule set."""

    def test_an_empty_document_fails(self) -> None:
        assert principal_violations(analyse_principals(""))

    def test_an_unrelated_document_fails(self) -> None:
        assert principal_violations(
            analyse_principals('resource "aws_s3_bucket" "x" {\n  bucket = "y"\n}\n')
        )

    def test_the_policy_candidate_is_not_a_principals_document(self) -> None:
        """The two candidates are separate files with separate rules, and stay so."""
        assert principal_violations(
            analyse_principals(QUALIFICATION_TF.read_text(encoding="utf-8"))
        )

    def test_the_literal_rule_reports_nothing_on_empty_text(self) -> None:
        assert literal_violations("") == []


class TestThePolicyCandidateIsUntouchedByTheseDeclarations:
    """ADR-0021 chose a holder. It changed neither policy it holds."""

    def test_the_policy_candidate_still_declares_exactly_the_two_managed_policies(self) -> None:
        blocks = parse_hcl(QUALIFICATION_TF.read_text(encoding="utf-8"))
        declared = [
            (block.labels[0], block.labels[1])
            for block in blocks
            if block.type == "resource" and len(block.labels) == 2
        ]
        assert declared == [
            ("aws_iam_policy", ACQUISITION),
            ("aws_iam_policy", ASSESSMENT),
        ]

    def test_the_policy_candidate_declares_no_permission_set_or_assignment(self) -> None:
        hcl = GUARD.strip_hcl_comments(QUALIFICATION_TF.read_text(encoding="utf-8"))
        assert "aws_ssoadmin" not in hcl

    def test_the_two_candidates_are_separate_files(self) -> None:
        assert QUALIFICATION_TF != PRINCIPALS_TF
        assert QUALIFICATION_TF.is_file()
        assert PRINCIPALS_TF.is_file()


# ---------------------------------------------------------------------------
# The pinned provider's own permission-set name limit -- ADR-0022
# ---------------------------------------------------------------------------
#
# ADR-0021 accepted a 33-character acquisition permission-set name and PR #56
# declared exactly that name, faithfully. The pinned `hashicorp/aws` v6.62.0
# validates `aws_ssoadmin_permission_set.name` to 1-32 characters against the
# grammar `[\w+=,.@-]+`, so the declaration was unbuildable -- and every offline
# test passed, because each compared the declared name with a constant carrying
# the same 33 characters. Two strings agreeing about a length neither measures is
# not a check.
#
# So these tests measure. They read the name out of the real declaration, follow
# the `name = local.x` reference the way Terraform would, and hand the resolved
# literal to the production rule. The mutations rewrite the declaration itself and
# assert the rule refuses it, so a rule that stopped measuring would fail here
# rather than go on agreeing with a constant.
#
# This is the length-and-grammar contract only. The generated-role suffix grammar
# is a different contract, over a different string AWS appends, and it is tested in
# `test_qualification_identity_gate.py`; neither bounds the other.

#: A synthetic 33-character name of the exact shape the provider refuses. Built by
#: repetition rather than typed, so it cannot silently become 32 or 34.
OVER_LIMIT_NAME = "K" * 33

#: The longest name the provider accepts.
BOUNDARY_NAME = "K" * 32

#: The name ADR-0022 retires. Named here once, as the value the rules must refuse.
RETIRED_ACQUISITION_NAME = "KalpaManiQualificationAcquisition"

#: The name ADR-0022 accepts, and the unchanged assessment name beside it.
ACCEPTED_ACQUISITION_NAME = "KalpaManiQualificationAcquire"
ACCEPTED_ASSESSMENT_NAME = "KalpaManiQualificationAssessment"

#: Each actor's local, by the name the declaration gives it.
PERMISSION_SET_LOCALS = (
    (ACQUISITION, "qualification_acquisition_permission_set"),
    (ASSESSMENT, "qualification_assessment_permission_set"),
)


def _declared_names(text: str) -> dict[str, str | None]:
    """The resolved permission-set names of ``text``, through the production rule."""
    names: dict[str, str | None] = GUARD.declared_permission_set_names(
        GUARD.strip_hcl_comments(text)
    )
    return names


def _rewrite_declared_name(text: str, local_name: str, replacement: str) -> str:
    """``text`` with ``local_name``'s literal replaced, refusing a no-op mutation.

    The assignment is located rather than reconstructed, because the declaration
    aligns its two ``=`` and a rebuilt line would match nothing -- a mutation that
    rewrites nothing passes every assertion made after it.
    """
    assert _declared_names(text), "the unmutated declaration must resolve before it is mutated"
    match = re.search(rf'({re.escape(local_name)}\s*=\s*)"([^"]*)"', text)
    assert match is not None, f"{local_name}: no literal assignment to mutate"
    mutated = text.replace(match.group(0), f'{match.group(1)}"{replacement}"')
    assert mutated != text, f"{local_name}: the mutation matched nothing"
    return mutated


class TestTheProviderNameLimitIsMeasuredNotDescribed:
    """The rule refuses and admits real values rather than restating a bound."""

    def test_the_rule_admits_the_accepted_acquisition_name(self) -> None:
        assert len(ACCEPTED_ACQUISITION_NAME) == 29
        assert GUARD.permission_set_name_defects(ACCEPTED_ACQUISITION_NAME) == []

    def test_the_rule_refuses_the_retired_acquisition_name(self) -> None:
        """33 characters. The value ADR-0022 retires, refused on length alone."""
        assert len(RETIRED_ACQUISITION_NAME) == 33
        defects = GUARD.permission_set_name_defects(RETIRED_ACQUISITION_NAME)
        assert defects and "33 characters" in defects[0]

    def test_the_retired_name_is_refused_only_on_length(self) -> None:
        """It satisfies the character grammar, so one character is the whole defect."""
        assert len(GUARD.permission_set_name_defects(RETIRED_ACQUISITION_NAME)) == 1

    def test_the_rule_admits_the_thirty_two_character_boundary(self) -> None:
        assert len(BOUNDARY_NAME) == 32
        assert GUARD.permission_set_name_defects(BOUNDARY_NAME) == []

    def test_the_rule_refuses_one_character_past_the_boundary(self) -> None:
        assert len(OVER_LIMIT_NAME) == 33
        assert GUARD.permission_set_name_defects(OVER_LIMIT_NAME)

    def test_the_rule_refuses_an_empty_name(self) -> None:
        assert GUARD.permission_set_name_defects("")

    @pytest.mark.parametrize(
        "name",
        ["Kalpa Mani", "Kalpa/Mani", "Kalpa:Mani", "Kalpa*Mani", "Kalpa!Mani", "Kalpa#Mani"],
    )
    def test_the_rule_refuses_a_name_outside_the_character_grammar(self, name: str) -> None:
        assert GUARD.permission_set_name_defects(name)

    def test_the_assessment_name_sits_exactly_on_the_boundary(self) -> None:
        """32 characters -- one more and ADR-0022 would have had to retire it too."""
        assert len(ACCEPTED_ASSESSMENT_NAME) == 32
        assert GUARD.permission_set_name_defects(ACCEPTED_ASSESSMENT_NAME) == []


class TestTheDeclaredNamesAreWhatIsMeasured:
    """The value checked is resolved out of the file, never copied beside it."""

    def test_both_declared_names_resolve_to_literals(self) -> None:
        assert _declared_names(_principals_text()) == {
            ACQUISITION: ACCEPTED_ACQUISITION_NAME,
            ASSESSMENT: ACCEPTED_ASSESSMENT_NAME,
        }

    def test_every_declared_name_satisfies_the_provider_rules(self) -> None:
        for label, name in _declared_names(_principals_text()).items():
            assert name is not None, label
            assert GUARD.permission_set_name_defects(name) == [], label

    def test_the_declaration_carries_no_retired_name(self) -> None:
        assert RETIRED_ACQUISITION_NAME not in _principals_text()

    def test_a_resource_rewired_to_the_wrong_local_is_seen(self) -> None:
        """Resolving through the reference is why checking the local alone is not enough."""
        mutated = _principals_text().replace(
            "  name             = local.qualification_acquisition_permission_set",
            "  name             = local.qualification_assessment_permission_set",
            1,
        )
        assert _declared_names(mutated)[ACQUISITION] == ACCEPTED_ASSESSMENT_NAME

    def test_an_unresolvable_name_reference_reads_as_unresolved(self) -> None:
        """A variable, an interpolation or a missing local must never read as valid."""
        mutated = _principals_text().replace(
            "  name             = local.qualification_acquisition_permission_set",
            "  name             = var.some_unbound_name",
            1,
        )
        assert _declared_names(mutated)[ACQUISITION] is None

    def test_a_missing_name_attribute_reads_as_unresolved(self) -> None:
        mutated = _principals_text().replace(
            "  name             = local.qualification_acquisition_permission_set\n",
            "",
            1,
        )
        assert _declared_names(mutated)[ACQUISITION] is None


class TestAnInvalidDeclaredNameIsRefused:
    """The mutations the defect itself would have needed, on the real declaration."""

    @pytest.mark.parametrize(("label", "local_name"), PERMISSION_SET_LOCALS)
    def test_a_thirty_three_character_declared_name_is_refused(
        self, label: str, local_name: str
    ) -> None:
        text = _principals_text()
        assert GUARD.permission_set_name_defects(_declared_names(text)[label] or "") == []
        declared = _declared_names(_rewrite_declared_name(text, local_name, OVER_LIMIT_NAME))[label]
        assert declared == OVER_LIMIT_NAME
        assert GUARD.permission_set_name_defects(declared)

    @pytest.mark.parametrize(("label", "local_name"), PERMISSION_SET_LOCALS)
    def test_the_retired_name_reintroduced_into_either_declaration_is_refused(
        self, label: str, local_name: str
    ) -> None:
        mutated = _rewrite_declared_name(_principals_text(), local_name, RETIRED_ACQUISITION_NAME)
        declared = _declared_names(mutated)[label]
        assert declared == RETIRED_ACQUISITION_NAME
        assert GUARD.permission_set_name_defects(declared)

    @pytest.mark.parametrize(("label", "local_name"), PERMISSION_SET_LOCALS)
    def test_an_empty_declared_name_is_refused(self, label: str, local_name: str) -> None:
        declared = _declared_names(_rewrite_declared_name(_principals_text(), local_name, ""))[
            label
        ]
        assert declared == ""
        assert GUARD.permission_set_name_defects(declared)

    @pytest.mark.parametrize(("label", "local_name"), PERMISSION_SET_LOCALS)
    def test_a_declared_name_outside_the_grammar_is_refused(
        self, label: str, local_name: str
    ) -> None:
        declared = _declared_names(
            _rewrite_declared_name(_principals_text(), local_name, "Kalpa Mani")
        )[label]
        assert declared == "Kalpa Mani"
        assert GUARD.permission_set_name_defects(declared)


class TestChangingProseAloneCannotSatisfyTheGuard:
    """The defect reached review because the prose and the constants agreed with each other."""

    def test_a_comment_naming_the_accepted_value_does_not_repair_a_bad_declaration(self) -> None:
        text = _principals_text()
        mutated = _rewrite_declared_name(
            text, "qualification_acquisition_permission_set", OVER_LIMIT_NAME
        ).replace(
            "locals {",
            f"locals {{\n  # the acquisition permission set is {ACCEPTED_ACQUISITION_NAME}, "
            "29 characters",
            1,
        )
        assert ACCEPTED_ACQUISITION_NAME in mutated
        declared = _declared_names(mutated)[ACQUISITION]
        assert declared == OVER_LIMIT_NAME
        assert GUARD.permission_set_name_defects(declared)


class TestTheGovernedVerifierNamesAreMeasuredToo:
    """The gate admits a role named after the permission set, so it is bound as well."""

    def test_the_verifier_maps_both_actors_to_the_declared_names(self) -> None:
        assert GUARD.verifier_permission_set_names(GUARD.read(GUARD.ADR_0021_VERIFIER)) == {
            "ACQUISITION": ACCEPTED_ACQUISITION_NAME,
            "ASSESSMENT": ACCEPTED_ASSESSMENT_NAME,
        }

    def test_every_verifier_name_satisfies_the_provider_rules(self) -> None:
        mapped = GUARD.verifier_permission_set_names(GUARD.read(GUARD.ADR_0021_VERIFIER))
        assert mapped
        for member, name in mapped.items():
            assert name is not None, member
            assert GUARD.permission_set_name_defects(name) == [], member

    def test_a_verifier_mapping_restored_to_the_retired_name_is_refused(self) -> None:
        source = GUARD.read(GUARD.ADR_0021_VERIFIER)
        mutated = source.replace(
            f'QualificationActor.ACQUISITION: "{ACCEPTED_ACQUISITION_NAME}"',
            f'QualificationActor.ACQUISITION: "{RETIRED_ACQUISITION_NAME}"',
        )
        assert mutated != source, "the mutation matched nothing"
        mapped = GUARD.verifier_permission_set_names(mutated)
        assert mapped["ACQUISITION"] == RETIRED_ACQUISITION_NAME
        assert GUARD.permission_set_name_defects(mapped["ACQUISITION"] or "")

    def test_an_absent_mapping_reports_nothing_rather_than_agreeing(self) -> None:
        assert GUARD.verifier_permission_set_names("") == {}


# ---------------------------------------------------------------------------
# PR #56 -- the merged offline qualification principals, as the documents claim it
# ---------------------------------------------------------------------------
#
# The Terraform above is checked by parsing it. This half checks the *claim* the
# status documents, the implementation plan and the infrastructure README make
# about the merge, because the three states this slice created can drift apart in
# a way neither the parser nor a reader notices: a merged declaration, an isolated
# offline validation of a task-owned external copy, and a live AWS object that
# still does not exist.
#
# Two drifts are now possible, and both are driven here. Forward: a merged,
# validated implementation read as a planned, applied, deployed or authorized one.
# Reverse: the merged implementation written back to the open, blocked,
# unvalidated state it came out of -- which is the drift a synchronization commit
# is most likely to reintroduce.
#
# Every guard is the audit's own, driven rather than restated, and every mutation
# is applied to in-memory text: no tracked file is written, no Terraform runs, and
# no AWS or private material is read.

PR_56_REQUIRED: tuple[tuple[str, str], ...] = GUARD.PR_56_STATUS_REQUIRED
PR_56_FORBIDDEN: tuple[str, ...] = GUARD.PR_56_STATUS_FORBIDDEN
PR_56_PLAN_REQUIRED: tuple[tuple[str, str], ...] = GUARD.PR_56_PLAN_REQUIRED
PR_56_TERMINATORS: dict[str, str] = dict(GUARD.PR_56_SECTION_TERMINATORS)

INFRA_README = INFRA / "README.md"
INFRA_REQUIRED: tuple[tuple[str, str], ...] = GUARD.INFRA_README_VALIDATION_REQUIRED
INFRA_FORBIDDEN: tuple[str, ...] = GUARD.INFRA_README_VALIDATION_FORBIDDEN


def pr_56_missing(text: str) -> list[str]:
    """Every required PR #56 clause the reading does not carry, by label."""
    return [label for label, phrase in PR_56_REQUIRED if phrase not in text]


def infra_missing(text: str) -> list[str]:
    """Every required infra-README clause the reading does not carry, by label."""
    return [label for label, phrase in INFRA_REQUIRED if phrase not in text]


def pr_56_overstated(text: str) -> list[str]:
    """Every forbidden PR #56 claim the reading does carry."""
    return [claim for claim in PR_56_FORBIDDEN if claim in text]


def pr_56_clause(label: str) -> str:
    """The exact phrase a labelled PR #56 requirement asserts, read from the audit."""
    for candidate, phrase in PR_56_REQUIRED:
        if candidate == label:
            return phrase
    raise AssertionError(f"no PR #56 requirement labelled {label!r}")


def split_at_pr_56_section(document: Path) -> tuple[str, str, str]:
    """``(before, section, after)`` for a document's one PR #56 section.

    Split on the audit's own extractor, so a test cannot disagree with the guard
    about where the section begins and ends.
    """
    text = read(document)
    found = GUARD.scan_pr_56_status_sections(text)
    assert not found.defects, f"{document.name}: {found.defects}"
    assert len(found.sections) == 1, f"{document.name}: {len(found.sections)} sections"
    section = str(found.sections[0])
    before, separator, after = text.partition(section)
    assert separator == section, f"{document.name}: the section is not verbatim in the document"
    return before, section, after


class TestThePr56MergeIsRecorded:
    """The unmutated repository satisfies every PR #56 guard. The control for the rest."""

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_each_document_carries_exactly_one_section(self, document: Path) -> None:
        found = GUARD.scan_pr_56_status_sections(read(document))
        assert found.defects == ()
        assert len(found.sections) == 1

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_every_required_clause_is_present_in_the_section(self, document: Path) -> None:
        _before, section, _after = split_at_pr_56_section(document)
        assert pr_56_missing(flat(section)) == []

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_no_forbidden_claim_is_made_anywhere_in_the_document(self, document: Path) -> None:
        assert pr_56_overstated(flat(read(document))) == []

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_the_merge_identity_is_recorded_whole(self, document: Path) -> None:
        _before, section, _after = split_at_pr_56_section(document)
        reading = flat(section)
        assert GUARD.PR_56_MERGE_COMMIT in reading
        assert GUARD.PR_56_MERGE_TIME.lower() in reading
        assert GUARD.PR_56_FIRST_PARENT in reading
        assert GUARD.PR_56_SECOND_PARENT in reading
        assert reading.index(GUARD.PR_56_FIRST_PARENT) < reading.index(GUARD.PR_56_SECOND_PARENT)

    def test_the_plan_carries_every_required_clause(self) -> None:
        reading = flat(read(PLAN))
        assert [label for label, phrase in PR_56_PLAN_REQUIRED if phrase not in reading] == []

    def test_both_documents_carry_the_same_subsections_in_order(self) -> None:
        titles = {
            document.name: GUARD._section_subsection_titles(
                GUARD.scan_pr_56_status_sections(read(document)).sections
            )
            for document in DOCUMENTS
        }
        assert len(set(titles.values())) == 1, titles
        assert titles["CLAUDE.md"] == GUARD.PR_56_STATUS_SUBSECTIONS

    def test_the_two_sections_are_byte_identical(self) -> None:
        _b, claude_section, _a = split_at_pr_56_section(PROJECT_ROOT / "CLAUDE.md")
        _b, readme_section, _a = split_at_pr_56_section(PROJECT_ROOT / "README.md")
        assert claude_section == readme_section

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_the_real_section_ends_at_its_declared_boundary(self, document: Path) -> None:
        text = read(document)
        _before, section, _after = split_at_pr_56_section(document)
        assert GUARD.qualification_iam_section_is_terminated(
            text, section, PR_56_TERMINATORS[document.name]
        )


class TestThePr56MergeFactsAreMutationProof:
    """A wrong commit, a wrong time or swapped parents describes a different history."""

    @pytest.mark.parametrize(
        ("label", "value"),
        [
            ("merge commit", GUARD.PR_56_MERGE_COMMIT),
            ("merge time", GUARD.PR_56_MERGE_TIME),
            ("first parent", GUARD.PR_56_FIRST_PARENT),
            ("second parent", GUARD.PR_56_SECOND_PARENT),
        ],
    )
    def test_replacing_one_recorded_value_is_reported(self, label: str, value: str) -> None:
        _before, section, _after = split_at_pr_56_section(PROJECT_ROOT / "CLAUDE.md")
        reading = flat(section)
        assert value.lower() in reading, label
        mutated = reading.replace(value.lower(), "0" * len(value))
        assert mutated != reading
        assert pr_56_missing(mutated) != [], label

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_swapping_the_ordered_parents_is_reported(self, document: Path) -> None:
        """Same two commits, wrong order -- a different merge, and a presence scan cannot see it.

        Drives the audit's own order guard: every phrase requirement stays
        satisfied after the swap, because both commit ids are still present.
        """
        _before, section, _after = split_at_pr_56_section(document)
        assert GUARD.pr_56_parent_order_defects(section) == []
        first, second = GUARD.PR_56_FIRST_PARENT, GUARD.PR_56_SECOND_PARENT
        swapped = section.replace(first, "<TMP>").replace(second, first).replace("<TMP>", second)
        assert swapped != section
        assert pr_56_missing(flat(swapped)) == [], "a phrase scan cannot see a swap"
        assert GUARD.pr_56_parent_order_defects(swapped) == [
            "the ordered merge parents appear in the wrong order"
        ]

    @pytest.mark.parametrize(
        ("dropped", "expected"),
        [
            (GUARD.PR_56_FIRST_PARENT, "the first ordered merge parent is absent"),
            (GUARD.PR_56_SECOND_PARENT, "the second ordered merge parent is absent"),
        ],
    )
    def test_dropping_one_ordered_parent_is_reported(self, dropped: str, expected: str) -> None:
        _before, section, _after = split_at_pr_56_section(PROJECT_ROOT / "CLAUDE.md")
        mutated = section.replace(dropped, "")
        assert mutated != section
        assert GUARD.pr_56_parent_order_defects(mutated) == [expected]

    def test_removing_the_merge_note_is_reported(self) -> None:
        phrase = pr_56_clause("records the merged pull request")
        _before, section, _after = split_at_pr_56_section(PROJECT_ROOT / "CLAUDE.md")
        mutated = flat(section).replace(phrase, "")
        assert "records the merged pull request" in pr_56_missing(mutated)

    def test_the_audit_keeps_the_cli_and_the_provider_apart(self) -> None:
        """A Terraform CLI version is not a provider version, and neither substitutes."""
        assert GUARD.PR_56_TERRAFORM_CLI not in GUARD.PR_56_LOCKED_PROVIDER
        assert GUARD.PR_56_LOCKED_PROVIDER not in GUARD.PR_56_TERRAFORM_CLI

    def test_the_recorded_merge_and_parents_are_three_commits(self) -> None:
        assert GUARD.PR_56_FIRST_PARENT != GUARD.PR_56_SECOND_PARENT
        assert GUARD.PR_56_MERGE_COMMIT not in (
            GUARD.PR_56_FIRST_PARENT,
            GUARD.PR_56_SECOND_PARENT,
        )


class TestPr56SectionLocalDeletionIsCaught:
    """Deleting a clause from the section is caught even when a copy survives elsewhere."""

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    @pytest.mark.parametrize("label", [label for label, _ in PR_56_REQUIRED])
    def test_removing_one_required_clause_is_reported(self, document: Path, label: str) -> None:
        phrase = pr_56_clause(label)
        _before, section, _after = split_at_pr_56_section(document)
        reading = flat(section)
        assert phrase in reading, f"{document.name}: absent before removal: {phrase}"
        mutated = reading.replace(phrase, "")
        assert label in pr_56_missing(mutated), f"{document.name}: undetected removal of {phrase}"

    def test_at_least_one_deletion_would_have_escaped_a_whole_file_scan(self) -> None:
        """Section scope is doing real work, and this names how much."""
        escaped: list[tuple[str, str]] = []
        for document in DOCUMENTS:
            before, _section, after = split_at_pr_56_section(document)
            outside = flat(before) + " " + flat(after)
            for label, phrase in PR_56_REQUIRED:
                if phrase in outside:
                    escaped.append((document.name, label))
        assert escaped, "no required clause is duplicated outside the section"


class TestPr56SectionStructureMutations:
    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_removing_the_whole_section_is_caught(self, document: Path) -> None:
        before, section, after = split_at_pr_56_section(document)
        assert section, f"{document.name}: nothing to remove"
        found = GUARD.scan_pr_56_status_sections(before + after)
        assert found.sections == ()
        assert pr_56_missing(flat(before + after)) != []

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_duplicating_the_section_is_caught(self, document: Path) -> None:
        before, section, after = split_at_pr_56_section(document)
        found = GUARD.scan_pr_56_status_sections(before + section + section + after)
        assert len(found.sections) == 2, "a second copy must be visible as a second section"

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_demoting_the_heading_is_caught(self, document: Path) -> None:
        text = read(document)
        heading = f"### {GUARD.PR_56_STATUS_HEADING}"
        assert text.count(heading + "\n") == 1, f"{document.name}: heading not found once"
        demoted = text.replace(heading + "\n", f"#### {GUARD.PR_56_STATUS_HEADING}\n")
        found = GUARD.scan_pr_56_status_sections(demoted)
        assert found.sections == ()
        assert found.defects, "a heading at the wrong level must be reported as a defect"

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_a_foreign_subsection_is_caught(self, document: Path) -> None:
        before, section, after = split_at_pr_56_section(document)
        marker = "#### Status\n"
        assert section.count(marker) == 1, f"{document.name}: no Status subsection"
        intruded = section.replace(marker, "#### Deployment evidence\n" + marker, 1)
        found = GUARD.scan_pr_56_status_sections(before + intruded + after)
        assert any("Deployment evidence" in defect for defect in found.defects), found.defects

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_deleting_the_terminator_lets_the_section_swallow_its_neighbour(
        self, document: Path
    ) -> None:
        text = read(document)
        terminator = PR_56_TERMINATORS[document.name]
        assert text.count(terminator + "\n") == 1, f"{document.name}: terminator not found once"
        widened = text.replace(terminator + "\n", "", 1)
        assert widened != text
        found = GUARD.scan_pr_56_status_sections(widened)
        assert len(found.sections) == 1, "the section is still extracted, and now too wide"
        assert not GUARD.qualification_iam_section_is_terminated(
            widened, str(found.sections[0]), terminator
        ), "a section running past its declared boundary must be reported"

    def test_breaking_claude_readme_parity_is_caught(self) -> None:
        _b, claude_section, _a = split_at_pr_56_section(PROJECT_ROOT / "CLAUDE.md")
        _b, readme_section, _a = split_at_pr_56_section(PROJECT_ROOT / "README.md")
        assert claude_section == readme_section
        mutated = readme_section.replace("provider selected:", "provider chosen:", 1)
        assert mutated != readme_section
        assert claude_section != mutated


class TestPr56ForwardDriftMutations:
    """A merged, validated declaration read as a planned, applied or live one."""

    @pytest.mark.parametrize(
        "claim",
        [
            "terraform has been applied",
            "terraform apply: performed",
            "terraform plan: completed",
            "terraform state: created",
            "repository .terraform/: created",
            "the repository directory was initialized",
            "live permission sets: created",
            "live assignments: created",
            "live policy attachments: established",
            "runtime roles: created",
            "runtime roles: observed",
            # "governed profiles: materialized" is retired here with the guard entry it
            # drove: both governed profiles have since been materialized and
            # independently verified, so it is no longer a claim the documents may not
            # make. The merge-day record is held by PR_56_REQUIRED instead.
            "organization-instance existence: established",
            "binding values: known",
            "authority granted: acquisition",
            "aws discovery: authorized",
            # "deployment: performed" is gone from this list, and from the guard. The
            # qualification-principal deployment has since been performed and
            # independently verified, so refusing that spelling would refuse the truth.
            # The applied-status guard refuses the reverse drift in its place.
            "qualification and binding-preflight execution: authorized",
            "run a: authorized",
            "run b: authorized",
            "combined assessment: authorized",
            "g1: closed",
            "g2: closed",
            "phase 3: complete",
            "control: published",
            "live trading: enabled",
        ],
    )
    def test_a_forward_drift_claim_is_refused(self, claim: str) -> None:
        _before, section, _after = split_at_pr_56_section(PROJECT_ROOT / "CLAUDE.md")
        assert claim not in flat(section)
        mutated = flat(section) + f" {claim} "
        assert claim in pr_56_overstated(mutated)


class TestPr56ReverseDriftMutations:
    """The merged implementation written back to the state it came out of.

    The obsolete wording is *required* to survive as history, so it cannot be a
    banned substring. It is held to its framing instead, and every spelling that
    would present the pre-merge state as the current one is refused outright.
    """

    @pytest.mark.parametrize(
        "document",
        [*DOCUMENTS, PLAN, INFRA_README],
        ids=lambda p: p.name if p.name != "README.md" else str(p.parent.name) + "/README.md",
    )
    def test_the_real_document_frames_the_pre_merge_state(self, document: Path) -> None:
        assert GUARD.pr_56_blocked_status_defects(read(document)) == []

    @pytest.mark.parametrize(
        "claim",
        [
            "PR #56: OPEN / UNMERGED / BLOCKED ON ARCHITECTURE",
            "PR #56 remains open",
            "PR #56 is unmerged",
            "PR #56 correction: NOT AUTHORIZED / NOT BEGUN",
            "PR #56 Terraform declarations: UNMERGED / UNAPPLIED",
            "the implementation is not merged",
            "no isolated `terraform validate` has been run",
        ],
    )
    def test_a_reverse_drift_claim_is_refused(self, claim: str) -> None:
        text = read(PROJECT_ROOT / "CLAUDE.md")
        assert GUARD.pr_56_blocked_status_defects(text) == []
        mutated = text + f"\n\n{claim}\n"
        defects = GUARD.pr_56_blocked_status_defects(mutated)
        assert any(
            defect.startswith("presents the pre-merge state as current:") for defect in defects
        ), claim

    def test_stripping_the_historical_framing_is_reported(self) -> None:
        """The obsolete wording kept, every framing marker deleted."""
        _before, section, _after = split_at_pr_56_section(PROJECT_ROOT / "CLAUDE.md")
        assert GUARD.pr_56_blocked_status_defects(section) == []
        mutated = flat(section)
        for mark in GUARD.PR_56_BLOCKED_FRAMINGS:
            mutated = mutated.replace(mark, "")
        assert GUARD.PR_56_BLOCKED_CLAIM in mutated
        assert GUARD.pr_56_blocked_status_defects(mutated) == [
            "names PR #56's blocked state with no historical framing"
        ]

    def test_a_text_that_never_names_the_blocked_state_is_clean(self) -> None:
        assert GUARD.pr_56_blocked_status_defects("nothing to see here") == []


class TestTheInfrastructureReadmeRecordsTheIsolatedValidation:
    """The README's obsolete no-init/no-validate sentence, and its replacement."""

    def test_every_required_clause_is_present(self) -> None:
        reading = flat(read(INFRA_README))
        assert infra_missing(reading) == []

    def test_no_forbidden_claim_is_present(self) -> None:
        reading = flat(read(INFRA_README))
        assert [claim for claim in INFRA_FORBIDDEN if claim in reading] == []

    @pytest.mark.parametrize("label", [label for label, _ in INFRA_REQUIRED])
    def test_removing_one_required_clause_is_reported(self, label: str) -> None:
        phrase = dict(INFRA_REQUIRED)[label]
        reading = flat(read(INFRA_README))
        assert phrase in reading, f"absent before removal: {phrase}"
        mutated = reading.replace(phrase, "")
        assert label in infra_missing(mutated)

    def test_reverting_to_the_obsolete_no_validation_sentence_is_refused(self) -> None:
        reading = flat(read(INFRA_README))
        reverted = (
            reading + " no `terraform plan`, `apply`, `init` or `validate` has been run "
            "against either file "
        )
        assert [claim for claim in INFRA_FORBIDDEN if claim in reverted] == [
            "no `terraform plan`, `apply`, `init` or `validate` has been run"
        ]

    @pytest.mark.parametrize(
        "claim",
        [
            # The forward-drift claims this list used to carry -- "terraform apply has
            # been run", "has been applied to aws" -- became true when the two
            # qualification files were applied and independently verified, so they are
            # retired rather than restated. What is refused now is the reverse drift,
            # which is the regression this transition can actually produce, plus the
            # forward claims the apply still did not buy.
            "never planned, never applied",
            "no plan and no apply ran",
            "qualification infrastructure remains unapplied",
            # "governed profiles are materialized" is retired here with the guard entry
            # it drove: both governed profiles exist, and this file is now required to
            # say so.
        ],
    )
    def test_a_drift_claim_is_refused(self, claim: str) -> None:
        reading = flat(read(INFRA_README))
        assert claim not in reading
        assert claim in [needle for needle in INFRA_FORBIDDEN if needle in reading + f" {claim} "]


class TestPr56GuardsAreNotTautologies:
    """Each list must be non-empty, and each guard must refuse something."""

    def test_the_requirement_lists_are_not_empty(self) -> None:
        assert PR_56_REQUIRED
        assert PR_56_PLAN_REQUIRED
        assert PR_56_FORBIDDEN
        assert INFRA_REQUIRED
        assert INFRA_FORBIDDEN

    def test_an_empty_document_fails_rather_than_passing(self) -> None:
        assert GUARD.scan_pr_56_status_sections("").sections == ()
        assert pr_56_missing("") == [label for label, _ in PR_56_REQUIRED]
        assert infra_missing("") == [label for label, _ in INFRA_REQUIRED]

    def test_no_required_clause_is_also_forbidden(self) -> None:
        required = {phrase for _label, phrase in PR_56_REQUIRED}
        assert required.isdisjoint(set(PR_56_FORBIDDEN))

    def test_the_accepted_names_still_satisfy_the_provider(self) -> None:
        for name in (ACCEPTED_ACQUISITION_NAME, ACCEPTED_ASSESSMENT_NAME):
            assert GUARD.permission_set_name_defects(name) == []
        assert GUARD.permission_set_name_defects(RETIRED_ACQUISITION_NAME)

    @pytest.mark.parametrize(
        ("name", "required"),
        [
            ("PR_56_STATUS_REQUIRED", GUARD.PR_56_STATUS_REQUIRED),
            ("PR_56_PLAN_REQUIRED", GUARD.PR_56_PLAN_REQUIRED),
            ("INFRA_README_VALIDATION_REQUIRED", GUARD.INFRA_README_VALIDATION_REQUIRED),
        ],
    )
    def test_no_label_or_phrase_is_duplicated(
        self, name: str, required: tuple[tuple[str, str], ...]
    ) -> None:
        """A duplicate label answers for the wrong clause; a duplicate phrase pads the count."""
        labels = [label for label, _phrase in required]
        phrases = [phrase for _label, phrase in required]
        assert len(set(labels)) == len(labels), name
        assert len(set(phrases)) == len(phrases), name

    def test_the_forbidden_lists_carry_no_duplicate(self) -> None:
        assert len(set(PR_56_FORBIDDEN)) == len(PR_56_FORBIDDEN)
        assert len(set(INFRA_FORBIDDEN)) == len(INFRA_FORBIDDEN)


APPLIED_REQUIRED: tuple[tuple[str, str], ...] = GUARD.APPLIED_INFRA_STATUS_REQUIRED
APPLIED_FORBIDDEN: tuple[str, ...] = GUARD.APPLIED_INFRA_STATUS_FORBIDDEN
APPLIED_REVERSE: tuple[str, ...] = GUARD.APPLIED_INFRA_REVERSE_DRIFT_FORBIDDEN
APPLIED_PLAN_REQUIRED: tuple[tuple[str, str], ...] = GUARD.APPLIED_INFRA_PLAN_REQUIRED
APPLIED_TERMINATORS: dict[str, str] = dict(GUARD.APPLIED_INFRA_SECTION_TERMINATORS)


def applied_missing(text: str) -> list[str]:
    """Every required applied-infrastructure clause the reading does not carry."""
    return [label for label, phrase in APPLIED_REQUIRED if phrase not in text]


def split_at_applied_section(document: Path) -> tuple[str, str, str]:
    """``(before, section, after)`` for a document's one applied-infrastructure section."""
    text = read(document)
    found = GUARD.scan_applied_infra_status_sections(text)
    assert not found.defects, f"{document.name}: {found.defects}"
    assert len(found.sections) == 1, f"{document.name}: {len(found.sections)} sections"
    section = str(found.sections[0])
    before, separator, after = text.partition(section)
    assert separator == section, f"{document.name}: the section is not verbatim in the document"
    return before, section, after


class TestTheAppliedInfrastructureIsRecorded:
    """The unmutated repository satisfies every applied-infrastructure guard."""

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_each_document_carries_exactly_one_section(self, document: Path) -> None:
        found = GUARD.scan_applied_infra_status_sections(read(document))
        assert found.defects == ()
        assert len(found.sections) == 1

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_the_section_ends_at_its_declared_boundary(self, document: Path) -> None:
        _before, section, _after = split_at_applied_section(document)
        assert GUARD.qualification_iam_section_is_terminated(
            read(document), section, APPLIED_TERMINATORS[document.name]
        )

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_every_required_clause_is_present(self, document: Path) -> None:
        _before, section, _after = split_at_applied_section(document)
        assert applied_missing(flat(section)) == []

    def test_both_documents_carry_the_same_section(self) -> None:
        sections = {document.name: split_at_applied_section(document)[1] for document in DOCUMENTS}
        assert len(set(sections.values())) == 1

    def test_the_plan_carries_every_required_clause(self) -> None:
        reading = flat(read(PLAN))
        assert [label for label, phrase in APPLIED_PLAN_REQUIRED if phrase not in reading] == []

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_every_superseded_block_is_framed_as_history(self, document: Path) -> None:
        assert GUARD.superseded_status_framing_defects(read(document)) == []


class TestTheAppliedInfrastructureGuardRefusesDrift:
    """The mutations. A guard that cannot fail is a guard that proves nothing."""

    @pytest.mark.parametrize("label", [label for label, _ in APPLIED_REQUIRED])
    def test_removing_one_required_clause_is_reported(self, label: str) -> None:
        phrase = dict(APPLIED_REQUIRED)[label]
        _before, section, _after = split_at_applied_section(PROJECT_ROOT / "CLAUDE.md")
        reading = flat(section)
        assert phrase in reading, f"absent before removal: {phrase}"
        assert label in applied_missing(reading.replace(phrase, ""))

    @pytest.mark.parametrize("claim", APPLIED_FORBIDDEN)
    def test_a_forward_drift_claim_is_refused(self, claim: str) -> None:
        """Everything the apply did not buy, refused anywhere in the document."""
        reading = flat(read(PROJECT_ROOT / "CLAUDE.md"))
        assert claim not in reading
        assert claim in [needle for needle in APPLIED_FORBIDDEN if needle in reading + f" {claim} "]

    @pytest.mark.parametrize("claim", APPLIED_REVERSE)
    def test_a_reverse_drift_claim_is_refused_inside_the_section(self, claim: str) -> None:
        """The pre-apply wording, refused where it would read as a claim about now.

        Section-scoped on purpose: several of these spellings are *required* to survive
        in the per-merge sections, which are the record of their own merges.
        """
        _before, section, _after = split_at_applied_section(PROJECT_ROOT / "CLAUDE.md")
        reading = flat(section)
        assert claim not in reading
        assert claim in [needle for needle in APPLIED_REVERSE if needle in reading + f" {claim} "]

    def test_an_unframed_superseded_block_is_reported(self) -> None:
        """The banner deleted from one block, and the obsolete wording left behind."""
        text = read(PROJECT_ROOT / "CLAUDE.md")
        assert GUARD.superseded_status_framing_defects(text) == []
        mutated = text.replace(
            "> **HISTORICAL — the state as of that merge, superseded by *The applied "
            "qualification\n> infrastructure*.**",
            "",
            1,
        )
        assert GUARD.superseded_status_framing_defects(mutated)

    def test_an_empty_document_fails_rather_than_passing(self) -> None:
        assert GUARD.scan_applied_infra_status_sections("").sections == ()
        assert applied_missing("") == [label for label, _ in APPLIED_REQUIRED]

    def test_the_lists_are_not_empty_and_carry_no_duplicate(self) -> None:
        assert APPLIED_REQUIRED and APPLIED_FORBIDDEN and APPLIED_REVERSE
        assert APPLIED_PLAN_REQUIRED
        assert len(set(APPLIED_FORBIDDEN)) == len(APPLIED_FORBIDDEN)
        assert len(set(APPLIED_REVERSE)) == len(APPLIED_REVERSE)
        labels = [label for label, _phrase in APPLIED_REQUIRED]
        phrases = [phrase for _label, phrase in APPLIED_REQUIRED]
        assert len(set(labels)) == len(labels)
        assert len(set(phrases)) == len(phrases)

    def test_no_required_clause_is_also_forbidden(self) -> None:
        required = {phrase for _label, phrase in APPLIED_REQUIRED}
        assert required.isdisjoint(set(APPLIED_FORBIDDEN))
        assert required.isdisjoint(set(APPLIED_REVERSE))


# ---------------------------------------------------------------------------
# The qualified operator access
# ---------------------------------------------------------------------------
#
# One owner-approved human operator was added to the governed Identity Center
# group, both governed AWS profiles were materialized, and an independent review
# confirmed each identity preflight and found no profile crossover. Three states
# are kept apart in both directions: an applied resource, a materialized access
# path, and authority to use it.
#
# The regression this transition can produce runs both ways. Forward: a
# materialized profile read as permission to run a qualification. Backward: the
# pre-membership wording -- an empty group, unmaterialized profiles, an untaken
# gate -- restored into the section that governs now, or left unframed in a
# document that has moved past it.
#
# Every guard is the audit's own, driven rather than restated, and every mutation
# is applied to in-memory text: no tracked file is written, no Terraform runs, no
# AWS is reached, and no private artifact, operator identity or account value is
# read.

ACCESS_REQUIRED: tuple[tuple[str, str], ...] = GUARD.OPERATOR_ACCESS_STATUS_REQUIRED
ACCESS_FORBIDDEN: tuple[str, ...] = GUARD.APPLIED_INFRA_MATERIALIZED_FORBIDDEN
ACCESS_REVERSE: tuple[str, ...] = GUARD.OPERATOR_ACCESS_REVERSE_DRIFT_FORBIDDEN
ACCESS_STALE: tuple[str, ...] = GUARD.OPERATOR_ACCESS_STALE_CLAIMS
ACCESS_PLAN_REQUIRED: tuple[tuple[str, str], ...] = GUARD.OPERATOR_ACCESS_PLAN_REQUIRED
ACCESS_INFRA_REQUIRED: tuple[tuple[str, str], ...] = GUARD.OPERATOR_ACCESS_INFRA_REQUIRED
ACCESS_TERMINATORS: dict[str, str] = dict(GUARD.OPERATOR_ACCESS_SECTION_TERMINATORS)


def access_missing(text: str) -> list[str]:
    """Every required operator-access clause the reading does not carry, by label."""
    return [label for label, phrase in ACCESS_REQUIRED if phrase not in text]


def split_at_access_section(document: Path) -> tuple[str, str, str]:
    """``(before, section, after)`` for a document's one operator-access section."""
    text = read(document)
    found = GUARD.scan_operator_access_status_sections(text)
    assert not found.defects, f"{document.name}: {found.defects}"
    assert len(found.sections) == 1, f"{document.name}: {len(found.sections)} sections"
    section = str(found.sections[0])
    before, separator, after = text.partition(section)
    assert separator == section, f"{document.name}: the section is not verbatim in the document"
    return before, section, after


class TestTheQualifiedOperatorAccessIsRecorded:
    """The unmutated repository satisfies every operator-access guard."""

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_each_document_carries_exactly_one_section(self, document: Path) -> None:
        found = GUARD.scan_operator_access_status_sections(read(document))
        assert found.defects == ()
        assert len(found.sections) == 1

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_the_section_ends_at_its_declared_boundary(self, document: Path) -> None:
        """It is followed by the applied-infrastructure section it supersedes."""
        _before, section, _after = split_at_access_section(document)
        assert GUARD.qualification_iam_section_is_terminated(
            read(document), section, ACCESS_TERMINATORS[document.name]
        )

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_every_required_clause_is_present(self, document: Path) -> None:
        _before, section, _after = split_at_access_section(document)
        assert access_missing(flat(section)) == []

    def test_both_documents_carry_the_same_section(self) -> None:
        sections = {document.name: split_at_access_section(document)[1] for document in DOCUMENTS}
        assert len(set(sections.values())) == 1

    def test_the_plan_carries_every_required_clause(self) -> None:
        reading = flat(read(PLAN))
        assert [label for label, phrase in ACCESS_PLAN_REQUIRED if phrase not in reading] == []

    def test_the_infra_readme_carries_every_required_clause(self) -> None:
        reading = flat(read(INFRA_README))
        assert [label for label, phrase in ACCESS_INFRA_REQUIRED if phrase not in reading] == []

    @pytest.mark.parametrize(
        "document",
        [*DOCUMENTS, PLAN, INFRA_README],
        ids=lambda p: p.name,
    )
    def test_no_pre_materialization_claim_is_left_unframed(self, document: Path) -> None:
        assert GUARD.operator_access_stale_claim_defects(read(document)) == []


class TestTheQualifiedOperatorAccessGuardRefusesDrift:
    """The mutations. A guard that cannot fail is a guard that proves nothing."""

    @pytest.mark.parametrize("label", [label for label, _ in ACCESS_REQUIRED])
    def test_removing_one_required_clause_is_reported(self, label: str) -> None:
        phrase = dict(ACCESS_REQUIRED)[label]
        _before, section, _after = split_at_access_section(PROJECT_ROOT / "CLAUDE.md")
        reading = flat(section)
        assert phrase in reading, f"absent before removal: {phrase}"
        assert label in access_missing(reading.replace(phrase, ""))

    @pytest.mark.parametrize("claim", ACCESS_FORBIDDEN)
    def test_a_forward_drift_claim_is_refused(self, claim: str) -> None:
        """Materialized access read as authority to use it, refused anywhere."""
        reading = flat(read(PROJECT_ROOT / "CLAUDE.md"))
        assert claim not in reading
        assert claim in [needle for needle in ACCESS_FORBIDDEN if needle in reading + f" {claim} "]

    @pytest.mark.parametrize("claim", ACCESS_REVERSE)
    def test_a_reverse_drift_claim_is_refused_inside_the_section(self, claim: str) -> None:
        """The pre-membership wording, refused where it would read as a claim about now.

        Section-scoped on purpose: every one of these spellings is *required* to
        survive in the applied-infrastructure block or a per-merge block below it,
        which are the record of their own dates.
        """
        _before, section, _after = split_at_access_section(PROJECT_ROOT / "CLAUDE.md")
        reading = flat(section)
        assert claim not in reading
        assert claim in [needle for needle in ACCESS_REVERSE if needle in reading + f" {claim} "]

    @pytest.mark.parametrize("claim", ACCESS_STALE)
    def test_an_unframed_pre_materialization_claim_is_reported(self, claim: str) -> None:
        """The obsolete status line written outside any framed historical block."""
        text = read(PROJECT_ROOT / "CLAUDE.md")
        assert GUARD.operator_access_stale_claim_defects(text) == []
        mutated = f"## Now\n\n{claim}\n\n{text}"
        assert GUARD.operator_access_stale_claim_defects(mutated)

    def test_a_framed_pre_materialization_claim_is_accepted(self) -> None:
        """The same wording under a superseded heading is history, not a claim."""
        framed = f"#### Verified status\n\n{ACCESS_STALE[0]}\n"
        assert GUARD.operator_access_stale_claim_defects(framed) == []

    def test_the_applied_section_carries_its_own_successor_banner(self) -> None:
        """The apply's superseded blocks name the materialization, not the apply."""
        text = read(PROJECT_ROOT / "CLAUDE.md")
        assert GUARD.superseded_status_framing_defects(text) == []
        mutated = text.replace(
            "> **HISTORICAL — the state as of that apply, superseded by *The qualified operator\n"
            "> access*.**",
            "",
            1,
        )
        assert GUARD.superseded_status_framing_defects(mutated)

    def test_a_block_framed_by_the_wrong_successor_is_reported(self) -> None:
        """A per-merge banner over the apply's own block is not framing."""
        wrong = (
            f"#### Verified status\n\n> **HISTORICAL — {GUARD.SUPERSEDED_STATUS_BANNER[13:]}**\n"
        )
        assert GUARD.superseded_status_framing_defects(wrong)

    def test_an_empty_document_fails_rather_than_passing(self) -> None:
        assert GUARD.scan_operator_access_status_sections("").sections == ()
        assert access_missing("") == [label for label, _ in ACCESS_REQUIRED]

    def test_a_second_section_is_refused(self) -> None:
        """Two answers to one question is not one answer twice."""
        _before, section, _after = split_at_access_section(PROJECT_ROOT / "CLAUDE.md")
        found = GUARD.scan_operator_access_status_sections(section + "\n" + section)
        assert len(found.sections) == 2

    def test_the_lists_are_not_empty_and_carry_no_duplicate(self) -> None:
        assert ACCESS_REQUIRED and ACCESS_FORBIDDEN and ACCESS_REVERSE and ACCESS_STALE
        assert ACCESS_PLAN_REQUIRED and ACCESS_INFRA_REQUIRED
        assert len(set(ACCESS_FORBIDDEN)) == len(ACCESS_FORBIDDEN)
        assert len(set(ACCESS_REVERSE)) == len(ACCESS_REVERSE)
        assert len(set(ACCESS_STALE)) == len(ACCESS_STALE)
        labels = [label for label, _phrase in ACCESS_REQUIRED]
        phrases = [phrase for _label, phrase in ACCESS_REQUIRED]
        assert len(set(labels)) == len(labels)
        assert len(set(phrases)) == len(phrases)

    def test_no_required_clause_is_also_forbidden(self) -> None:
        """A guard that demands what it refuses can never be satisfied."""
        for _label, phrase in ACCESS_REQUIRED:
            assert phrase not in ACCESS_FORBIDDEN
            assert phrase not in ACCESS_REVERSE
            assert phrase not in ACCESS_STALE

    def test_the_forbidden_claims_are_not_satisfied_by_an_honest_negation(self) -> None:
        """The documents say these gates are closed, and must not be refused for it."""
        reading = flat(read(PROJECT_ROOT / "CLAUDE.md"))
        assert "qualification execution: not authorized / not run" in reading
        assert "sixth private-binding preflight: not authorized / not run" in reading
        assert "provider credential retrieval: none" in reading
        assert [claim for claim in ACCESS_FORBIDDEN if claim in reading] == []


class TestMaterializedAccessIsNotAuthority:
    """The distinction the whole transition turns on, read from the documents."""

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_access_is_separated_from_every_downstream_gate(self, document: Path) -> None:
        _before, section, _after = split_at_access_section(document)
        reading = flat(section)
        assert "materialized access is not authority to use it" in reading
        for gate in (
            "sixth private-binding preflight",
            "qualification execution",
            "third adr-0017 acquisition",
            "run a",
            "run b",
            "combined assessment",
        ):
            assert f"{gate}: not authorized / not run" in reading

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_no_provider_or_object_activity_is_claimed(self, document: Path) -> None:
        _before, section, _after = split_at_access_section(document)
        reading = flat(section)
        assert "provider credential retrieval: none" in reading
        assert "s3/provider activity: none" in reading
        assert "provider selected: none" in reading
        assert "g1 / g2: open / open" in reading

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_the_operator_is_counted_and_never_named(self, document: Path) -> None:
        """The count is the record. The person is not, and neither is any identifier."""
        _before, section, _after = split_at_access_section(document)
        reading = flat(section)
        assert "operator group: exactly 1 owner-approved human member / assigned" in reading
        assert "no name, user name, email address" in reading
        for identifier in (
            "arn:aws",
            "ssoins-",
            "awsapps.com",
            "awsreservedsso_kalpamaniqualificationacquire_",
            "awsreservedsso_kalpamaniqualificationassessment_",
            "d-9",
            "@gmail.com",
        ):
            assert identifier not in reading

    @pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.name)
    def test_the_section_carries_no_twelve_digit_account_or_digest(self, document: Path) -> None:
        """No account id, and no artifact digest, reaches a tracked status surface."""
        _before, section, _after = split_at_access_section(document)
        assert re.search(r"(?<!\d)\d{12}(?!\d)", section) is None
        assert re.search(r"(?<![0-9a-f])[0-9a-f]{40,}(?![0-9a-f])", section) is None
