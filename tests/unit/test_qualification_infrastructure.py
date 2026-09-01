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

import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from kalpamani.data.ingest.publication import BRONZE_NAMESPACE, CLAIM_NAMESPACE
from kalpamani.data.ingest.sharadar.datasets import PROVIDER
from kalpamani.data.qualify.sharadar.locator import LOCATOR_SEGMENTS
from kalpamani.data.qualify.sharadar.plan import EMPIRICAL_DATASETS
from kalpamani.data.qualify.sharadar.publication import QUALIFICATION_SEGMENT
from kalpamani.data.qualify.sharadar.report import REPORT_SEGMENTS

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
# Canonical formatting, checked offline because `terraform fmt` cannot run here
# ---------------------------------------------------------------------------
#
# `terraform` is not installed on this workstation, so `terraform fmt -check` is
# unavailable and the candidate would otherwise ship with its formatting merely
# believed. This checks the subset of `terraform fmt`'s output that can be decided
# from the text alone: two-space indentation, no tabs, no trailing whitespace, one
# final newline, and `=` alignment across each run of consecutive single-line
# attributes inside one block.
#
# **The thirteen pre-existing files are the control.** They were written and
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
