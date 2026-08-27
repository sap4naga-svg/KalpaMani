"""Test-integrity audit: refuse assertions that are unconditional by construction.

A test suite is evidence only while every assertion in it can distinguish a
working system from a broken one. This scan establishes a narrower thing -- that
none of them is unconditional in a way a parser can see -- and the gap between
those two statements is the subject of the last paragraph below.

Three assertions on this branch could not distinguish anything::

    assert clean.dataset.build_identity in str(clean.context_hash()) or True
    assert manifest.quality_context_hash in manifest.manifest_hash or True
    assert not any("BOUNDED" in basis for basis in used) or bounded

The first two read as checks and neither was one: ``or True`` makes the whole
expression unconditional, so the left-hand side was never evaluated for its
truth. They would have passed against a build with no binding at all, which is
precisely the property they were written to establish. The third is ``not P or
P`` -- two spellings of one runtime predicate -- and **this scan cannot see it**.
A green suite containing any of them says less than it appears to, and nothing in
the run reports that.

Text search is not enough here. ``or True`` inside a string literal or a comment
is harmless, ``assert (x or True)``, ``assert x or (1 == 1)`` and ``assert x or
[0, 1]`` are the same defect written differently, and ``assert not False`` is a
fourth spelling. This scans the parsed tree, so it sees the structure rather than
the characters.

**What it cannot see, stated plainly.** The scan is *syntactic*. It folds
literals, comparisons between literals, literal containers, ``and``/``or`` over
those and ``not`` of those -- and nothing else, deliberately, because a scanner
that guessed at names would start refusing sound tests. It therefore cannot
detect a *semantic* tautology: ``assert not P or P`` where both halves are the
same runtime predicate reads as an ordinary assertion to any parser, and one of
those survived in the very file this audit was written to clean. Passing this
audit means no assertion is unconditional **by construction**; it does not mean
every assertion can fail. Only reading them establishes that.

Five defect classes, all of which make a test weaker than it looks:

``TAUTOLOGICAL_ASSERT``
    The assertion is statically true. It cannot fail.
``IMPOSSIBLE_ASSERT``
    The assertion is statically false. It cannot pass -- a different bug, and
    still an assertion that tests nothing about the system.
``BROAD_EXCEPTION``
    ``pytest.raises(Exception)`` or a bare/``Exception`` handler inside a test.
    The test then passes on the *wrong* failure, which is worse than not
    testing: a refusal for an unintended reason is recorded as the intended one.
``UNEXPLAINED_SKIP``
    ``xfail``/``skip``/``skipif`` with no stated reason. A skip is a decision to
    stop checking something, and a decision with no reason cannot be reviewed.
``CONSTANT_ASSERT``
    ``assert <literal>`` -- the degenerate case of the first two.

This is a guard over those five properties. It is not a proof that the
assertions which *do* vary are the right ones.

Run:  .venv/Scripts/python.exe scripts/test_integrity_audit.py
      .venv/Scripts/python.exe scripts/test_integrity_audit.py tests/unit
Exit code 0 means nothing syntactically unconditional was found; non-zero lists
what was. It is not a claim that every assertion can fail.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Exception types too broad to establish that a refusal was the intended one.
BROAD_EXCEPTIONS = frozenset({"Exception", "BaseException"})

#: Markers that stop a test from running, or from being believed when it fails.
SKIP_MARKERS = frozenset({"skip", "skipif", "xfail"})


class Finding(NamedTuple):
    """One assertion, handler or marker this scan can show is not doing its job."""

    path: Path
    line: int
    kind: str
    detail: str

    def render(self, root: Path) -> str:
        """One line, in the ``file:line`` form an editor can follow."""
        try:
            location = self.path.relative_to(root)
        except ValueError:  # pragma: no cover - only for a path outside the repo
            location = self.path
        return f"{location.as_posix()}:{self.line}  {self.kind}  {self.detail}"


def static_truth(node: ast.expr) -> bool | None:
    """Whether ``node`` is true or false without running anything.

    ``None`` means it depends on the program state, which is what an assertion
    is supposed to depend on. Only literals, ``and``/``or`` over literals, and
    ``not`` of those resolve statically -- deliberately narrow, because a
    scanner that guessed at names would start refusing sound tests.
    """
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = static_truth(node.operand)
        return None if inner is None else not inner
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        # A literal container is truthy exactly when it is non-empty, and
        # `assert x or [1]` is `assert x or True` with different punctuation.
        return bool(node.elts)
    if isinstance(node, ast.Dict):
        return bool(node.keys)
    if isinstance(node, ast.Compare):
        return _constant_comparison(node)
    if isinstance(node, ast.BoolOp):
        values = [static_truth(value) for value in node.values]
        if isinstance(node.op, ast.Or):
            # One statically-true operand short-circuits the whole expression,
            # whatever the others do. This is the `or True` case.
            if any(value is True for value in values):
                return True
            return False if all(value is False for value in values) else None
        if any(value is False for value in values):
            return False
        return True if all(value is True for value in values) else None
    return None


#: Comparisons this scanner will fold when both sides are literals. Chained
#: comparisons and identity checks are left alone: ``a is b`` between two equal
#: literals is implementation-defined, and guessing there would be worse than
#: not looking.
_FOLDABLE = {
    ast.Eq: lambda left, right: left == right,
    ast.NotEq: lambda left, right: left != right,
    ast.Lt: lambda left, right: left < right,
    ast.LtE: lambda left, right: left <= right,
    ast.Gt: lambda left, right: left > right,
    ast.GtE: lambda left, right: left >= right,
}


def _constant_comparison(node: ast.Compare) -> bool | None:
    """``1 == 1`` is ``True`` spelled to survive a text search for ``True``."""
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return None
    left, right = node.left, node.comparators[0]
    if not isinstance(left, ast.Constant) or not isinstance(right, ast.Constant):
        return None
    operator = _FOLDABLE.get(type(node.ops[0]))
    if operator is None:
        return None
    try:
        return bool(operator(left.value, right.value))
    except TypeError:
        return None


def _unparse(node: ast.expr) -> str:
    text = ast.unparse(node)
    return text if len(text) <= 80 else text[:77] + "..."


def _is_pytest_attribute(node: ast.expr, *names: str) -> bool:
    """Whether ``node`` is ``pytest.<names...>``, or the bare name it was imported as.

    ``from pytest import raises`` produces a plain ``raises(...)`` call, which a
    dotted-path matcher misses entirely -- so the guard would have reported clean
    on a file using the other import style.
    """
    if isinstance(node, ast.Name) and node.id == names[-1]:
        return True
    for name in reversed(names):
        if not isinstance(node, ast.Attribute) or node.attr != name:
            return False
        node = node.value
    return isinstance(node, ast.Name) and node.id == "pytest"


def _exception_names(node: ast.expr | None) -> list[str]:
    if node is None:
        return []
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.Tuple):
        return [name for element in node.elts for name in _exception_names(element)]
    return []


class _Scan(ast.NodeVisitor):
    """Walk one module, recording every **syntactically** unconditional assertion.

    Not every assertion that cannot fail. See :func:`static_truth` for what
    resolves statically and the module docstring for what does not.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.findings: list[Finding] = []
        self._test_depth = 0

    # -- assertions ---------------------------------------------------------

    def visit_Assert(self, node: ast.Assert) -> None:
        verdict = static_truth(node.test)
        if verdict is True:
            kind = (
                "CONSTANT_ASSERT"
                if isinstance(node.test, ast.Constant)
                else ("TAUTOLOGICAL_ASSERT")
            )
            self.findings.append(
                Finding(
                    self.path,
                    node.lineno,
                    kind,
                    f"`assert {_unparse(node.test)}` is true whatever the code does",
                )
            )
        elif verdict is False:
            self.findings.append(
                Finding(
                    self.path,
                    node.lineno,
                    "IMPOSSIBLE_ASSERT",
                    f"`assert {_unparse(node.test)}` can never pass",
                )
            )
        self.generic_visit(node)

    # -- broad exception handling, inside tests only ------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_markers(node)
        inside = node.name.startswith("test_")
        self._test_depth += int(inside)
        self.generic_visit(node)
        self._test_depth -= int(inside)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_markers(node)
        inside = node.name.startswith("test_")
        self._test_depth += int(inside)
        self.generic_visit(node)
        self._test_depth -= int(inside)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if self._test_depth:
            names = _exception_names(node.type)
            if not names:
                self.findings.append(
                    Finding(
                        self.path,
                        node.lineno,
                        "BROAD_EXCEPTION",
                        "a bare `except:` in a test passes on any failure, including the wrong one",
                    )
                )
            elif broad := sorted(set(names) & BROAD_EXCEPTIONS):
                self.findings.append(
                    Finding(
                        self.path,
                        node.lineno,
                        "BROAD_EXCEPTION",
                        f"`except {', '.join(broad)}` in a test cannot tell the intended "
                        "failure from an unintended one",
                    )
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if _is_pytest_attribute(node.func, "raises"):
            broad = sorted(
                set(_exception_names(node.args[0] if node.args else None)) & (BROAD_EXCEPTIONS)
            )
            if broad:
                self.findings.append(
                    Finding(
                        self.path,
                        node.lineno,
                        "BROAD_EXCEPTION",
                        f"`pytest.raises({', '.join(broad)})` records any failure as the "
                        "expected refusal",
                    )
                )
        if _is_pytest_attribute(node.func, "skip") or _is_pytest_attribute(node.func, "xfail"):
            has_reason = bool(node.args) or any(
                keyword.arg in {"reason", "msg"} for keyword in node.keywords
            )
            if not has_reason:
                self.findings.append(
                    Finding(
                        self.path,
                        node.lineno,
                        "UNEXPLAINED_SKIP",
                        f"`{ast.unparse(node.func)}()` states no reason",
                    )
                )
        self.generic_visit(node)

    # -- skip / xfail markers ----------------------------------------------

    def _check_markers(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            marker = next(
                (name for name in SKIP_MARKERS if _is_pytest_attribute(target, "mark", name)),
                None,
            )
            if marker is None:
                continue
            reason = isinstance(decorator, ast.Call) and any(
                keyword.arg == "reason" for keyword in decorator.keywords
            )
            if not reason:
                self.findings.append(
                    Finding(
                        self.path,
                        decorator.lineno,
                        "UNEXPLAINED_SKIP",
                        f"`@pytest.mark.{marker}` on {node.name} states no reason",
                    )
                )


def scan_source(source: str, path: Path) -> list[Finding]:
    """Every finding in one module's source. Exposed so tests can pass a string."""
    scan = _Scan(path)
    scan.visit(ast.parse(source))
    return sorted(scan.findings, key=lambda finding: (finding.line, finding.kind))


def python_files(root: Path) -> Iterator[Path]:
    """Every module under ``root``, excluding caches, in a stable order."""
    if root.is_file():
        yield root
        return
    yield from sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def audit(roots: Sequence[Path]) -> list[Finding]:
    """Scan every module under ``roots``."""
    findings: list[Finding] = []
    for root in roots:
        for path in python_files(root):
            findings.extend(scan_source(path.read_text(encoding="utf-8"), path))
    return findings


def main(argv: Sequence[str]) -> int:
    """Print the audit and return a process exit code."""
    roots = [Path(arg).resolve() for arg in argv] or [PROJECT_ROOT / "tests"]
    missing = [root for root in roots if not root.exists()]
    if missing:
        for root in missing:
            print(f"  NO SUCH PATH: {root}")
        return 2

    scanned = sum(1 for root in roots for _ in python_files(root))
    findings = audit(roots)

    print("KalpaMani test-integrity audit")
    print("=" * 70)
    for root in roots:
        print(f"  scanning: {root}")
    print(f"  {scanned} module(s) parsed")
    print()

    if not findings:
        print("AUDIT PASSED.")
        print("No syntactically unconditional assertion, broad test exception,")
        print("or unexplained skip was found.")
        print()
        print("This is a guard over the named syntactic properties,")
        print("not proof that every assertion is semantically capable of failing.")
        return 0

    print(f"AUDIT FAILED. {len(findings)} item(s) cannot do their job:")
    print()
    for finding in findings:
        print(f"  {finding.render(PROJECT_ROOT)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
