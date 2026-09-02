"""The two ADR-0021 qualification actors, proved by identity rather than by profile.

**Nothing here contacts AWS.** No STS call, no client, no credential, no socket and
no profile file. Every identity in this file is a synthetic string, and the gate is
driven through its injected ``caller_identity`` callable, which is what the
parameterised design exists to make possible.

**What the gate has to be able to refuse.** The governed account already holds the
ECS task, task-execution and deletion roles, so an account-only check cannot tell the
acquisition actor from the assessment actor, or either from an unrelated principal in
the same account. The two actors are asymmetric on purpose -- one may write licensed
evidence and reach a provider credential, the other may read licensed evidence and
reach neither -- so a gate that admits either under one contract has collapsed the
compromise argument the two-actor split rests on.

**Three things this file is careful NOT to claim.**

* A **profile name is not proof.** It is local configuration text any caller can
  write. Several tests below pass the correct profile and still expect a refusal.
* The **suffix grammar proves structure, not provenance.** A string shaped like a
  generated suffix is lexically indistinguishable from one, and nothing can separate
  them. What the grammar buys is that arbitrary trailing text cannot ride along.
* A passing gate **establishes an identity and nothing else.** Every later gate --
  authorization, bucket, credential, plan, deadline -- still applies.

The mutation tests take the real committed text or the real parsed structures,
assert the mutation target exists before changing it, and then require the
production rule to catch the change. A guard that cannot fail is visible immediately
here, because the mutation that should trip it does not.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any, Final

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = PROJECT_ROOT / "scripts"
SRC = PROJECT_ROOT / "src"

VERIFY_SCRIPT = SCRIPTS / "aws_foundation_verify.py"
ACQUIRE_ENTRY = SCRIPTS / "sharadar_empirical_qualification.py"
ASSESS_ENTRY = SCRIPTS / "sharadar_qualification_assessment.py"

#: The ADR-0017 authenticated acquisition surface, and the ADR-0015 binding preflight.
#: Neither is an ADR-0021 qualification actor, and ADR-0021 preserves both unchanged.
ADR_0017_ENTRY = SCRIPTS / "sharadar_authenticated_qualification.py"
BINDING_PREFLIGHT = SCRIPTS / "sharadar_binding_preflight.py"
PUBLIC_KEY_HARNESS = SCRIPTS / "sharadar_private_qualification.py"

#: The profile every surface pinned before ADR-0021, and the one the two qualification
#: actors must no longer route through.
FOUNDATION_PROFILE: Final = "kalpamani-foundation"

#: A synthetic twelve-digit account. Not an account id: it is the shape a check needs,
#: and it names nothing. The real binding is read from a git-ignored file and is never
#: seen by this suite.
ACCOUNT: Final = "000000000000"
OTHER_ACCOUNT: Final = "999999999999"

#: A synthetic generated suffix, of the documented lowercase-hexadecimal shape.
SUFFIX: Final = "0123456789abcdef"

#: A synthetic role-session name.
SESSION: Final = "operator"

_VERIFIER_MODULE = "kalpamani_aws_foundation_verify_identity"


def _verifier() -> Any:
    """Load the verification script as a module. It is a script, not a package.

    Registered in ``sys.modules`` before execution, for the reason the other suites
    that load it record: ``@dataclass`` resolves its annotations through
    ``sys.modules[cls.__module__]``, and an unregistered module makes every dataclass
    construction fail with an unrelated-looking error.
    """
    cached = sys.modules.get(_VERIFIER_MODULE)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(_VERIFIER_MODULE, VERIFY_SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        pytest.fail("the verification script could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_VERIFIER_MODULE] = module
    spec.loader.exec_module(module)
    return module


V = _verifier()
ACQUISITION = V.QualificationActor.ACQUISITION
ASSESSMENT = V.QualificationActor.ASSESSMENT


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    """The tree with every module, class and function docstring removed.

    A comment scan is not enough and a docstring scan is not either: these files
    explain at length which AWS operation they deliberately do not perform, and a
    naive substring search reports every one of those explanations as a usage. What
    is left after this is the code that runs.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        first = body[0] if body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return tree


def executable(path: Path) -> str:
    """One module's executable source: no comments, no docstrings, one canonical form."""
    return ast.unparse(_strip_docstrings(ast.parse(read(path))))


def production_modules() -> list[Path]:
    """Every production Python module, excluding caches.

    ``tests/`` is deliberately out of scope: a suite that scans itself would report
    the synthetic identity below as a committed one.
    """
    found: list[Path] = []
    for root in (SRC, SCRIPTS):
        found.extend(p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts)
    return found


#: The two governance guards, excluded by exact filename and only these two. Each has
#: to NAME the constructs it forbids in order to forbid them, and neither constructs a
#: client, sends a request or is an operational surface.
GUARD_MODULES: Final[frozenset[str]] = frozenset(
    {"phase3_docs_audit.py", "test_integrity_audit.py"}
)


def role_name(permission_set: str, suffix: str = SUFFIX) -> str:
    return f"AWSReservedSSO_{permission_set}_{suffix}"


def sts_arn(role: str, *, account: str = ACCOUNT, session: str = SESSION) -> str:
    return f"arn:aws:sts::{account}:assumed-role/{role}/{session}"


def identity_for(actor: Any, *, account: str = ACCOUNT, suffix: str = SUFFIX) -> str:
    return sts_arn(
        role_name(V.QUALIFICATION_PERMISSION_SETS[actor], suffix),
        account=account,
    )


class Caller:
    """A synthetic ``sts:GetCallerIdentity``. Counts how often it was asked."""

    def __init__(self, *, ok: bool = True, data: Any = None, code: str = "") -> None:
        self._outcome = V.AwsOutcome(ok=ok, data=data, code=code)
        self.calls = 0

    def __call__(self) -> Any:
        self.calls += 1
        return self._outcome


def caller_for(actor: Any, *, account: str = ACCOUNT, reported: str | None = None) -> Caller:
    return Caller(
        data={"Account": reported or account, "Arn": identity_for(actor, account=account)}
    )


def refusal(
    actor: Any,
    *,
    caller: Caller,
    profile: str | None = None,
    bound: str | None = ACCOUNT,
) -> Any:
    """Drive the real gate with injected values and return its reason, or ``None``."""
    return V.qualification_identity_refusal(
        actor,
        profile=V.QUALIFICATION_PROFILES[actor] if profile is None else profile,
        bound_account=bound,
        caller_identity=caller,
    )


# ---------------------------------------------------------------------------
# The closed vocabulary, and the two mappings over it
# ---------------------------------------------------------------------------


def test_there_are_exactly_two_actors() -> None:
    """Two, and never one. ADR-0021 rejects a shared role or permission set outright."""
    assert [actor.value for actor in V.QualificationActor] == ["acquisition", "assessment"]


def test_each_actor_has_exactly_one_permission_set_and_one_profile() -> None:
    """Total mappings, so no actor can reach a lookup with no entry."""
    actors = set(V.QualificationActor)
    assert set(V.QUALIFICATION_PERMISSION_SETS) == actors
    assert set(V.QUALIFICATION_PROFILES) == actors


def test_the_permission_set_names_are_the_accepted_ones_and_are_distinct() -> None:
    assert V.QUALIFICATION_PERMISSION_SETS[ACQUISITION] == "KalpaManiQualificationAcquisition"
    assert V.QUALIFICATION_PERMISSION_SETS[ASSESSMENT] == "KalpaManiQualificationAssessment"
    assert len(set(V.QUALIFICATION_PERMISSION_SETS.values())) == 2


def test_the_profile_names_are_the_accepted_ones_and_are_distinct() -> None:
    assert V.QUALIFICATION_PROFILES[ACQUISITION] == "kalpamani-qualification-acquisition"
    assert V.QUALIFICATION_PROFILES[ASSESSMENT] == "kalpamani-qualification-assessment"
    assert len(set(V.QUALIFICATION_PROFILES.values())) == 2


def test_neither_qualification_profile_is_the_shared_foundation_profile() -> None:
    """The single pin ADR-0021 replaced. A revert to it would route both actors alike."""
    assert FOUNDATION_PROFILE not in set(V.QUALIFICATION_PROFILES.values())


def test_neither_permission_set_name_is_a_prefix_of_the_other() -> None:
    """Otherwise a prefix match would admit one actor's role for the other's gate."""
    acquisition = V.QUALIFICATION_PERMISSION_SETS[ACQUISITION]
    assessment = V.QUALIFICATION_PERMISSION_SETS[ASSESSMENT]
    assert not acquisition.startswith(assessment)
    assert not assessment.startswith(acquisition)


def test_the_entry_points_pin_the_same_profile_literals_the_verifier_declares() -> None:
    """Two spellings of one contract, asserted equal rather than assumed equal.

    The entry points restate their profile rather than importing it, deliberately --
    coupling two operator surfaces would make their failure modes depend on each
    other. This is what keeps the restatement honest.
    """
    for path, actor in ((ACQUIRE_ENTRY, ACQUISITION), (ASSESS_ENTRY, ASSESSMENT)):
        expected = V.QUALIFICATION_PROFILES[actor]
        assert f'EXPECTED_PROFILE: Final = "{expected}"' in read(path)


# ---------------------------------------------------------------------------
# The STS assumed-role ARN, parsed rather than matched
# ---------------------------------------------------------------------------


def test_the_accepted_form_parses_into_its_three_parts() -> None:
    parsed = V.parse_assumed_role_arn(identity_for(ACQUISITION))
    assert parsed is not None
    assert parsed.account == ACCOUNT
    assert parsed.role_name == role_name("KalpaManiQualificationAcquisition")
    assert parsed.session_name == SESSION


@pytest.mark.parametrize(
    ("label", "arn"),
    [
        ("an IAM role ARN", f"arn:aws:iam::{ACCOUNT}:role/{role_name('X')}"),
        (
            "the Identity Center IAM role ARN with its reserved path",
            f"arn:aws:iam::{ACCOUNT}:role/aws-reserved/sso.amazonaws.com/"
            f"us-east-1/{role_name('KalpaManiQualificationAcquisition')}",
        ),
        ("an IAM user ARN", f"arn:aws:iam::{ACCOUNT}:user/operator"),
        ("a root ARN", f"arn:aws:iam::{ACCOUNT}:root"),
        ("a federated-user ARN", f"arn:aws:sts::{ACCOUNT}:federated-user/operator"),
        (
            "an assumed-role ARN in another partition",
            f"arn:aws-us-gov:sts::{ACCOUNT}:"
            f"assumed-role/{role_name('KalpaManiQualificationAcquisition')}/{SESSION}",
        ),
        (
            "an assumed-role ARN in the China partition",
            f"arn:aws-cn:sts::{ACCOUNT}:"
            f"assumed-role/{role_name('KalpaManiQualificationAcquisition')}/{SESSION}",
        ),
        (
            "an ARN for another service",
            f"arn:aws:s3::{ACCOUNT}:"
            f"assumed-role/{role_name('KalpaManiQualificationAcquisition')}/{SESSION}",
        ),
        (
            "a region-bearing STS ARN",
            f"arn:aws:sts:us-east-1:{ACCOUNT}:"
            f"assumed-role/{role_name('KalpaManiQualificationAcquisition')}/{SESSION}",
        ),
        (
            "an eleven-digit account",
            f"arn:aws:sts::00000000000:"
            f"assumed-role/{role_name('KalpaManiQualificationAcquisition')}/{SESSION}",
        ),
        (
            "a non-numeric account",
            f"arn:aws:sts::00000000000a:"
            f"assumed-role/{role_name('KalpaManiQualificationAcquisition')}/{SESSION}",
        ),
        (
            "an extra resource path segment",
            f"arn:aws:sts::{ACCOUNT}:assumed-role/"
            f"extra/{role_name('KalpaManiQualificationAcquisition')}/{SESSION}",
        ),
        (
            "a missing session name",
            f"arn:aws:sts::{ACCOUNT}:assumed-role/{role_name('KalpaManiQualificationAcquisition')}",
        ),
        (
            "an empty session name",
            f"arn:aws:sts::{ACCOUNT}:"
            f"assumed-role/{role_name('KalpaManiQualificationAcquisition')}/",
        ),
        ("an empty role name", f"arn:aws:sts::{ACCOUNT}:assumed-role//{SESSION}"),
        (
            "a session name carrying a space",
            f"arn:aws:sts::{ACCOUNT}:"
            f"assumed-role/{role_name('KalpaManiQualificationAcquisition')}/two words",
        ),
        (
            "a session name over sixty-four characters",
            f"arn:aws:sts::{ACCOUNT}:"
            f"assumed-role/{role_name('KalpaManiQualificationAcquisition')}/{'s' * 65}",
        ),
        ("a truncated ARN", f"arn:aws:sts::{ACCOUNT}"),
        (
            "a trailing extra field",
            f"arn:aws:sts::{ACCOUNT}:"
            f"assumed-role/{role_name('KalpaManiQualificationAcquisition')}/{SESSION}:x",
        ),
        ("empty text", ""),
        ("the word arn alone", "arn"),
    ],
    ids=lambda value: value if isinstance(value, str) and " " in value else "",
)
def test_the_parser_refuses_everything_that_is_not_an_sts_assumed_role_arn(
    label: str, arn: str
) -> None:
    assert V.parse_assumed_role_arn(arn) is None, label


@pytest.mark.parametrize(
    ("label", "value"),
    [("None", None), ("bytes", b"arn:aws:sts::x"), ("an integer", 12), ("a list", ["arn"])],
    ids=lambda value: value if isinstance(value, str) and " " in value else "",
)
def test_the_parser_refuses_a_value_that_is_not_a_string(label: str, value: object) -> None:
    assert V.parse_assumed_role_arn(value) is None, label


def test_a_string_subclass_is_refused_rather_than_admitted_by_duck_typing() -> None:
    """``type(...) is not str`` rather than ``isinstance``.

    A ``str`` subclass can override every method a parser would call, so admitting
    one would mean the verdict depends on code the value brought with it.
    """

    class Sneaky(str):
        __slots__ = ()

    assert V.parse_assumed_role_arn(Sneaky(identity_for(ACQUISITION))) is None


# ---------------------------------------------------------------------------
# The role name: the exact actor prefix, and the suffix grammar
# ---------------------------------------------------------------------------


def test_each_actor_accepts_its_own_generated_role_name() -> None:
    for actor in V.QualificationActor:
        name = role_name(V.QUALIFICATION_PERMISSION_SETS[actor])
        assert V.qualification_role_suffix(actor, name) == SUFFIX


def test_each_actor_refuses_the_other_actors_generated_role_name() -> None:
    """The pairing, not merely the shape. Cross-use fails closed."""
    for actor, other in ((ACQUISITION, ASSESSMENT), (ASSESSMENT, ACQUISITION)):
        name = role_name(V.QUALIFICATION_PERMISSION_SETS[other])
        assert V.qualification_role_suffix(actor, name) is None


@pytest.mark.parametrize(
    ("label", "name"),
    [
        ("a missing suffix", "AWSReservedSSO_KalpaManiQualificationAcquisition"),
        ("an empty suffix", "AWSReservedSSO_KalpaManiQualificationAcquisition_"),
        ("an uppercase-hexadecimal suffix", "AWSReservedSSO_KalpaManiQualificationAcquisition_ABC"),
        ("a non-hexadecimal suffix", "AWSReservedSSO_KalpaManiQualificationAcquisition_zzzz"),
        ("a suffix carrying a hyphen", "AWSReservedSSO_KalpaManiQualificationAcquisition_ab-cd"),
        (
            "a suffix over the bound",
            f"AWSReservedSSO_KalpaManiQualificationAcquisition_{'a' * 33}",
        ),
        (
            "a suffix carrying a second underscore",
            "AWSReservedSSO_KalpaManiQualificationAcquisition_abc_def",
        ),
        ("an altered reserved prefix", "AWSReservedSSO2_KalpaManiQualificationAcquisition_abc"),
        ("a lowercased reserved prefix", "awsreservedsso_KalpaManiQualificationAcquisition_abc"),
        ("leading text before the prefix", "XAWSReservedSSO_KalpaManiQualificationAcquisition_abc"),
        (
            "text appended to the permission-set name",
            "AWSReservedSSO_KalpaManiQualificationAcquisitionX_abc",
        ),
        (
            "a truncated permission-set name",
            "AWSReservedSSO_KalpaManiQualificationAcquisitio_abc",
        ),
        ("no reserved prefix at all", "KalpaManiQualificationAcquisition_abc"),
        ("an unrelated role name", "kalpamani-research-task"),
        ("empty text", ""),
    ],
    ids=lambda value: value if isinstance(value, str) and " " in value else "",
)
def test_the_role_name_rule_refuses_every_near_miss(label: str, name: str) -> None:
    assert V.qualification_role_suffix(ACQUISITION, name) is None, label


def test_a_one_character_suffix_is_accepted_so_the_bound_is_a_bound_and_not_a_length() -> None:
    """The grammar requires a non-empty suffix of the documented shape, not a fixed size.

    AWS publishes no formal grammar for the generated suffix, so pinning one length
    would refuse a legitimate identity for a shape AWS never promised.
    """
    assert (
        V.qualification_role_suffix(
            ACQUISITION, role_name(V.QUALIFICATION_PERMISSION_SETS[ACQUISITION], "a")
        )
        == "a"
    )


# ---------------------------------------------------------------------------
# The gate: order first, then every refusal
# ---------------------------------------------------------------------------


def test_a_correct_identity_passes_for_each_actor() -> None:
    for actor in V.QualificationActor:
        caller = caller_for(actor)
        assert refusal(actor, caller=caller) is None
        assert caller.calls == 1


def test_each_actor_refuses_the_other_actors_identity() -> None:
    """Decision-table cases 3 and 4: the profile is right and the role is not."""
    for actor, other in ((ACQUISITION, ASSESSMENT), (ASSESSMENT, ACQUISITION)):
        caller = caller_for(other)
        reason = refusal(actor, caller=caller)
        assert reason is not None
        assert "permission-set role" in reason


def test_the_correct_profile_alone_does_not_pass_the_gate() -> None:
    """A profile name is configuration text. It selects a source and proves nothing."""
    caller = Caller(data={"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/operator"})
    assert refusal(ACQUISITION, caller=caller) is not None


def test_the_correct_account_alone_does_not_pass_the_gate() -> None:
    """The account already holds the task, task-execution and deletion roles."""
    caller = Caller(
        data={"Account": ACCOUNT, "Arn": sts_arn("kalpamani-research-task")},
    )
    assert refusal(ACQUISITION, caller=caller) is not None


def test_a_wrong_profile_refuses_before_any_identity_call_is_made() -> None:
    """Order is the security property: a wrong pin never reaches an AWS call."""
    caller = caller_for(ACQUISITION)
    reason = refusal(ACQUISITION, profile=FOUNDATION_PROFILE, caller=caller)
    assert reason is not None
    assert caller.calls == 0


def test_the_other_actors_profile_refuses_before_any_identity_call_is_made() -> None:
    caller = caller_for(ACQUISITION)
    reason = refusal(ACQUISITION, profile=V.QUALIFICATION_PROFILES[ASSESSMENT], caller=caller)
    assert reason is not None
    assert caller.calls == 0


def test_no_profile_at_all_refuses_before_any_identity_call_is_made() -> None:
    caller = caller_for(ACQUISITION)
    assert refusal(ACQUISITION, profile="", caller=caller) is not None
    assert caller.calls == 0


def test_a_missing_account_binding_refuses_before_any_identity_call_is_made() -> None:
    caller = caller_for(ACQUISITION)
    reason = refusal(ACQUISITION, caller=caller, bound=None)
    assert reason is not None
    assert caller.calls == 0


def test_an_actor_outside_the_closed_vocabulary_refuses_first_of_all() -> None:
    """A bare string equal to a member value is still not a member."""
    caller = Caller(data={})
    reason = V.qualification_identity_refusal(
        "acquisition",
        profile="kalpamani-qualification-acquisition",
        bound_account=ACCOUNT,
        caller_identity=caller,
    )
    assert reason is not None
    assert caller.calls == 0


def test_a_failed_identity_call_refuses_and_names_only_the_error_code() -> None:
    caller = Caller(ok=False, data=None, code="ExpiredToken")
    reason = refusal(ACQUISITION, caller=caller)
    assert reason is not None
    assert "ExpiredToken" in reason
    assert ACCOUNT not in reason


@pytest.mark.parametrize(
    ("label", "data"),
    [
        ("no Account field", {"Arn": identity_for(ACQUISITION)}),
        ("an empty Account", {"Account": "", "Arn": identity_for(ACQUISITION)}),
        ("a short Account", {"Account": "12345", "Arn": identity_for(ACQUISITION)}),
        ("a numeric Account", {"Account": 0, "Arn": identity_for(ACQUISITION)}),
        ("no Arn field", {"Account": ACCOUNT}),
        ("an empty Arn", {"Account": ACCOUNT, "Arn": ""}),
        ("a non-string Arn", {"Account": ACCOUNT, "Arn": None}),
        ("a response that is not a mapping", None),
    ],
    ids=lambda value: value if isinstance(value, str) and " " in value else "",
)
def test_a_malformed_identity_response_refuses(label: str, data: object) -> None:
    assert refusal(ACQUISITION, caller=Caller(data=data)) is not None, label


def test_a_wrong_account_refuses_even_with_the_right_role() -> None:
    caller = caller_for(ACQUISITION, account=OTHER_ACCOUNT)
    reason = refusal(ACQUISITION, caller=caller)
    assert reason is not None
    assert OTHER_ACCOUNT not in reason


def test_a_response_account_disagreeing_with_the_arn_account_refuses() -> None:
    """Two account fields arrive; agreeing with one of them is not enough.

    The response's ``Account`` matches the binding and the ARN's does not. A gate
    that read only the reported field would admit a role in another account.
    """
    caller = Caller(
        data={"Account": ACCOUNT, "Arn": identity_for(ACQUISITION, account=OTHER_ACCOUNT)}
    )
    reason = refusal(ACQUISITION, caller=caller)
    assert reason is not None
    assert "assumed-role account" in reason


def test_a_malformed_generated_suffix_refuses() -> None:
    caller = Caller(data={"Account": ACCOUNT, "Arn": identity_for(ACQUISITION, suffix="NOT-HEX")})
    assert refusal(ACQUISITION, caller=caller) is not None


def test_no_refusal_reason_discloses_an_identity_value() -> None:
    """Reasons are sanitized: no account, ARN, role name, session name or profile value."""
    canaries = (
        ACCOUNT,
        OTHER_ACCOUNT,
        SESSION,
        SUFFIX,
        "AWSReservedSSO",
        "arn:aws:",
        V.QUALIFICATION_PROFILES[ACQUISITION],
        V.QUALIFICATION_PROFILES[ASSESSMENT],
    )
    reasons: list[str] = []
    for actor in V.QualificationActor:
        for caller in (
            Caller(ok=False, code="AccessDenied"),
            Caller(
                data={
                    "Account": OTHER_ACCOUNT,
                    "Arn": identity_for(actor, account=OTHER_ACCOUNT),
                }
            ),
            Caller(data={"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/{SESSION}"}),
            Caller(data={"Account": ACCOUNT, "Arn": identity_for(actor, suffix="NOPE")}),
        ):
            found = refusal(actor, caller=caller)
            assert found is not None
            reasons.append(found)
        reasons.append(str(refusal(actor, profile=FOUNDATION_PROFILE, caller=Caller(data={}))))
        reasons.append(str(refusal(actor, caller=Caller(data={}), bound=None)))
    assert reasons
    for reason in reasons:
        for canary in canaries:
            assert canary not in reason, f"{canary!r} leaked into {reason!r}"


def test_the_ambient_gate_reads_the_environment_and_the_local_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wrapper wires the ambient profile and the account binding, and nothing else.

    ``_run_aws`` is replaced, so no subprocess starts and no AWS call is made. What
    this establishes is the wiring: the environment supplies the profile, the local
    binding supplies the account, and the one identity call is the existing single
    call site rather than a second one.
    """
    seen: list[tuple[str, ...]] = []

    def fake_run(args: tuple[str, ...]) -> Any:
        seen.append(args)
        return V.AwsOutcome(
            ok=True,
            data={"Account": ACCOUNT, "Arn": identity_for(ASSESSMENT)},
            code="",
        )

    monkeypatch.setattr(V, "_run_aws", fake_run)
    monkeypatch.setattr(V, "expected_account", lambda: ACCOUNT)
    monkeypatch.setenv("AWS_PROFILE", V.QUALIFICATION_PROFILES[ASSESSMENT])
    assert V.qualification_identity_gate(ASSESSMENT) is None
    assert seen == [("sts", "get-caller-identity")]


def test_the_ambient_gate_refuses_an_unpinned_environment_without_calling_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = 0

    def fake_run(args: tuple[str, ...]) -> Any:
        nonlocal called
        called += 1
        return V.AwsOutcome(ok=False, data=None, code="")

    monkeypatch.setattr(V, "_run_aws", fake_run)
    monkeypatch.setattr(V, "expected_account", lambda: ACCOUNT)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    assert V.qualification_identity_gate(ACQUISITION) is not None
    assert called == 0


# ---------------------------------------------------------------------------
# The shared account gate is unchanged, and every earlier caller keeps it
# ---------------------------------------------------------------------------


def test_the_shared_account_gate_still_exists_and_still_takes_no_actor() -> None:
    """ADR-0021 adds a gate beside the account gate rather than replacing it.

    Every earlier caller -- the ADR-0015 binding preflight, the ADR-0017 authenticated
    acquisition, the public-test-key harness -- was written against the parameterless
    contract, and a signature change would silently alter all three.
    """
    import inspect

    assert list(inspect.signature(V.identity_gate).parameters) == []
    assert V.EXPECTED_PROFILE == FOUNDATION_PROFILE


@pytest.mark.parametrize(
    "path",
    [ADR_0017_ENTRY, BINDING_PREFLIGHT, PUBLIC_KEY_HARNESS],
    ids=["adr-0017", "binding-preflight", "public-test-key-harness"],
)
def test_no_earlier_operator_surface_was_moved_onto_a_qualification_actor(path: Path) -> None:
    """ADR-0021 preserves ADR-0017, ADR-0015 and the harness unchanged.

    Each still pins the shared foundation profile, and none of them names an
    ADR-0021 actor, permission set or actor-specific profile. ADR-0021 chose who runs
    the two ADR-0018 qualification actors; it did not reach any other surface.
    """
    source = read(path)
    assert FOUNDATION_PROFILE in source
    for forbidden in (
        "QualificationActor",
        "qualification_identity_gate",
        "KalpaManiQualification",
        "kalpamani-qualification-",
    ):
        assert forbidden not in source, f"{path.name} names {forbidden}"


def test_the_adr_0021_symbols_reach_exactly_three_production_modules() -> None:
    """Containment, as a repository fact rather than a rule to remember.

    The verifier declares the contract and the two qualification entry points prove
    their own actor. A fourth module naming either symbol would be a surface nobody
    reviewed -- the shared store, the Bronze key builders and the ADR-0017 path
    included.

    The documentation audit is excluded, for the reason it is excluded everywhere
    else here: a governance guard has to name what it guards, and it constructs no
    client, sends no request and is not an operational surface.
    """
    naming = sorted(
        path.name
        for path in production_modules()
        if path.name not in GUARD_MODULES
        if any(
            symbol in read(path) for symbol in ("QualificationActor", "qualification_identity_gate")
        )
    )
    assert naming == [
        "aws_foundation_verify.py",
        "sharadar_empirical_qualification.py",
        "sharadar_qualification_assessment.py",
    ]


def test_the_containment_rule_would_catch_a_fourth_module() -> None:
    """The exclusion above must not be the reason the rule passes.

    The audit really does name one of the symbols, so the rule is shown here to
    report a module that names one -- proving the assertion is a list comparison
    that can fail rather than an exclusion that empties it.
    """
    audit = SCRIPTS / "phase3_docs_audit.py"
    assert audit.name in GUARD_MODULES
    assert "qualification_identity_gate" in read(audit)
    unfiltered = sorted(
        path.name
        for path in production_modules()
        if any(
            symbol in read(path) for symbol in ("QualificationActor", "qualification_identity_gate")
        )
    )
    assert audit.name in unfiltered
    assert len(unfiltered) == 4


# ---------------------------------------------------------------------------
# Rules over the committed source, and the mutations that must trip them
# ---------------------------------------------------------------------------
#
# Each rule below is a function over text, so the same rule can be pointed at the
# real repository (expect nothing) and at a deliberately mutated copy (expect the
# specific finding). A rule that could not fire is visible immediately.


#: Tokens that would mean an application reads or writes an AWS profile or SSO cache.
PROFILE_FILE_TOKENS: Final[tuple[str, ...]] = (
    ".aws",
    "AWS_CONFIG_FILE",
    "AWS_SHARED_CREDENTIALS_FILE",
    "aws configure",
    "sso login",
    "sso_session",
    "sso_role_name",
)

#: Tokens that would mean an application assumes a role of its own. ADR-0021 keeps
#: `sts:GetCallerIdentity` as the one runtime identity operation.
ASSUME_ROLE_TOKENS: Final[tuple[str, ...]] = ("AssumeRole", "assume_role", "sts:Assume")


def token_violations(source: str, tokens: tuple[str, ...]) -> list[str]:
    return [token for token in tokens if token in source]


def test_no_production_module_reads_or_writes_an_aws_profile_file() -> None:
    offenders = {
        path.name: token_violations(executable(path), PROFILE_FILE_TOKENS)
        for path in production_modules()
        if path.name not in GUARD_MODULES
    }
    found = {name: hits for name, hits in offenders.items() if hits}
    assert found == {}, f"an application reaches a profile or SSO cache: {found}"


def test_no_production_module_assumes_a_role() -> None:
    offenders = {
        path.name: token_violations(executable(path), ASSUME_ROLE_TOKENS)
        for path in production_modules()
        if path.name not in GUARD_MODULES
    }
    found = {name: hits for name, hits in offenders.items() if hits}
    assert found == {}, f"an application assumes a role: {found}"


@pytest.mark.parametrize("token", PROFILE_FILE_TOKENS)
def test_the_profile_file_rule_catches_an_injected_use(token: str) -> None:
    """Injected into the real verifier's executable source, not into a fixture."""
    source = executable(VERIFY_SCRIPT)
    assert token_violations(source, (token,)) == []
    assert token_violations(f'{source}\nPATH = "{token}"\n', (token,)) == [token]


@pytest.mark.parametrize("token", ASSUME_ROLE_TOKENS)
def test_the_assume_role_rule_catches_an_injected_call(token: str) -> None:
    source = executable(VERIFY_SCRIPT)
    assert token_violations(source, (token,)) == []
    assert token_violations(f'{source}\n_run_aws(("sts", "{token}"))\n', (token,)) == [token]


def test_no_production_module_pins_a_complete_generated_role_arn() -> None:
    """A pinned full ARN goes stale the moment an assignment is recreated.

    The suffix rotates, and AWS's own referencing guidance wildcards it for exactly
    that reason. What the repository may hold is the stable prefix; a literal
    containing both the reserved prefix and an `arn:` is a pin.
    """
    offenders = [
        path.name
        for path in production_modules()
        if path.name not in GUARD_MODULES
        for literal in [executable(path)]
        if "AWSReservedSSO_" in literal and "arn:aws:iam::" in literal
    ]
    assert offenders == [], f"a complete generated role ARN is pinned: {offenders}"


def test_the_pinned_arn_rule_catches_an_injected_pin() -> None:
    source = executable(VERIFY_SCRIPT)
    assert not ("AWSReservedSSO_" in source and "arn:aws:iam::" in source)
    mutated = (
        f'{source}\nPINNED = "arn:aws:iam::{ACCOUNT}:role/aws-reserved/'
        f'sso.amazonaws.com/{role_name("KalpaManiQualificationAcquisition")}"\n'
    )
    assert "AWSReservedSSO_" in mutated and "arn:aws:iam::" in mutated


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------


def test_the_token_rules_report_nothing_on_empty_text() -> None:
    """A rule that fires on everything is not a rule."""
    assert token_violations("", PROFILE_FILE_TOKENS) == []
    assert token_violations("", ASSUME_ROLE_TOKENS) == []


def test_the_docstring_stripper_removes_a_documented_prohibition() -> None:
    """The reason the scans run on executable source rather than on the file.

    These modules explain the operations they deliberately do not perform. A scan
    over raw text would report each explanation as a usage, and the honest fix is to
    scan what runs -- proved here on a module that says one of the forbidden words in
    a docstring and never performs it.
    """
    sample = 'def f() -> None:\n    """This never calls AssumeRole."""\n    return None\n'
    assert "AssumeRole" in sample
    stripped = ast.unparse(_strip_docstrings(ast.parse(sample)))
    assert "AssumeRole" not in stripped


def test_the_production_module_scan_is_not_empty() -> None:
    """Every scan above would pass vacuously against an empty file list."""
    modules = production_modules()
    assert len(modules) > 50
    assert VERIFY_SCRIPT in modules
    assert ACQUIRE_ENTRY in modules
    assert ASSESS_ENTRY in modules
