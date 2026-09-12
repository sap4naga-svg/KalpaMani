"""The production identity shapes and the identity gate (ADR-0036 §2.5).

**Unchanged in kind, extended in shape.** The qualification gate binds an exact
account plus an exact permission-set role-name prefix and a validated generated
suffix; the same three clauses hold for a production human and for a launcher.
A task adds the third shape ADR-0036 names --
``arn:<partition>:sts::<account>:assumed-role/<task-role-name>/<task-id>`` with
the **exact** compiled task-role name -- and nothing here relaxes the first two to
admit it: each :class:`~kalpamani.data.production.sharadar.vocabulary.IdentityPath`
is matched by its own rule, and a credential resolving to another path, the other
actor, a qualification actor, the foundation role or any default chain refuses.

**The binding is input, the constants are proof.** The authenticated account is
compared to the binding's ``target_account_id`` and the authenticated role name to
the actor's *compiled* role name or permission set. A binding can therefore make
the comparison fail; it cannot make it pass against the wrong principal.

**Every reason is value-free.** No account, ARN, role name, session name, task id
or AWS error text is returned. The one runtime identity operation is
``sts:GetCallerIdentity``, injected as a callable so no SDK is named here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from kalpamani.data.production.sharadar.bindings import ProductionRuntimeBinding
from kalpamani.data.production.sharadar.vocabulary import (
    EXPECTED_PARTITION,
    GENERATED_ROLE_PREFIX,
    IdentityPath,
    ProductionActor,
    constants_for,
)

#: A twelve-digit AWS account number.
_ACCOUNT_ID: Final = re.compile(r"[0-9]{12}")

#: The generated suffix Identity Center appends to a role it creates: non-empty
#: lowercase hexadecimal, bounded. The qualification gate's grammar, unchanged.
GENERATED_SUFFIX_RE: Final = re.compile(r"[0-9a-f]{1,32}")

#: An STS role-session name. Non-empty, no ``/``.
SESSION_NAME_RE: Final = re.compile(r"[A-Za-z0-9+=,.@_-]{1,64}")

#: An ECS task id, which is what the task-role session is named after: thirty-two
#: lowercase hexadecimal characters.
TASK_ID_RE: Final = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True, slots=True, kw_only=True)
class AssumedRoleIdentity:
    """One parsed ``sts:GetCallerIdentity`` assumed-role ARN.

    The STS form -- role **name**, no IAM path -- which is what the call returns.
    """

    account: str
    role_name: str
    session_name: str

    def __repr__(self) -> str:
        """A fixed token. **None of the three fields is ever rendered.**"""
        return "AssumedRoleIdentity(<redacted>)"


def parse_assumed_role_arn(arn: object) -> AssumedRoleIdentity | None:
    """The parsed STS assumed-role identity, or ``None`` if this is not one.

    Fails closed on an IAM role ARN, an IAM user, a root ARN, a federated user,
    another partition, another service, a malformed account, an extra resource
    segment, or a value that is not a string. Nothing is trimmed or rebuilt.
    """
    if type(arn) is not str:
        return None
    fields = arn.split(":")
    if len(fields) != 6:
        return None
    scheme, partition, service, region, account, resource = fields
    if scheme != "arn" or partition != EXPECTED_PARTITION or service != "sts" or region != "":
        return None
    if not _ACCOUNT_ID.fullmatch(account):
        return None
    parts = resource.split("/")
    if len(parts) != 3:
        return None
    kind, role_name, session_name = parts
    if kind != "assumed-role" or not role_name:
        return None
    if not SESSION_NAME_RE.fullmatch(session_name):
        return None
    return AssumedRoleIdentity(account=account, role_name=role_name, session_name=session_name)


def generated_role_suffix(permission_set: str, role_name: str) -> str | None:
    """The generated suffix, if ``role_name`` is exactly ``permission_set``'s role.

    Anchored at both ends: the exact prefix, then a remainder that must satisfy the
    suffix grammar, which admits no underscore and no uppercase.
    """
    expected = f"{GENERATED_ROLE_PREFIX}{permission_set}_"
    if not role_name.startswith(expected):
        return None
    suffix = role_name[len(expected) :]
    return suffix if GENERATED_SUFFIX_RE.fullmatch(suffix) else None


def role_matches_path(actor: ProductionActor, path: IdentityPath, role_name: str) -> bool:
    """Whether ``role_name`` is exactly ``actor``'s role under ``path``. Nothing else.

    ``HUMAN`` and ``LAUNCHER`` are generated Identity Center roles, matched by exact
    prefix plus suffix grammar; ``TASK`` is a declared role, matched by exact name.
    """
    constants = constants_for(actor)
    if path is IdentityPath.HUMAN:
        return generated_role_suffix(constants.permission_set, role_name) is not None
    if path is IdentityPath.LAUNCHER:
        return generated_role_suffix(constants.launcher_permission_set, role_name) is not None
    # Exhaustive: the three members above are the whole vocabulary, and a caller
    # holding a non-member has not been through it.
    if type(path) is not IdentityPath:
        return False
    return role_name == constants.task_role_name


@dataclass(frozen=True, slots=True, kw_only=True)
class ProvenIdentity:
    """What the gate hands on when every clause holds. The task id, for a task."""

    actor: ProductionActor
    path: IdentityPath
    task_id: str | None

    def __repr__(self) -> str:
        """Actor and path. **Never the task id.**"""
        return f"ProvenIdentity(actor={self.actor.value!r}, path={self.path.value!r})"


def production_identity_refusal(
    actor: ProductionActor,
    *,
    path: IdentityPath,
    binding: ProductionRuntimeBinding,
    caller_identity: Callable[[], object],
) -> str | ProvenIdentity:
    """Why this principal may not proceed as ``actor`` under ``path``, or the proof.

    The order is the security property: the actor and the binding are checked
    before ``caller_identity`` is invoked, so an identity call is never made under
    a binding nobody validated. Every reason returned is value-free.

    Returns:
        A :class:`str` reason on refusal; a :class:`ProvenIdentity` when the
        authenticated account equals the binding's account, the role name is
        exactly this actor's role under this path, and -- for a task -- the session
        name is a well-formed task id.
    """
    if type(actor) is not ProductionActor:
        return "the production actor is not a member of the closed vocabulary"
    if type(path) is not IdentityPath:
        return "the identity path is not a member of the closed vocabulary"
    if type(binding) is not ProductionRuntimeBinding or binding.actor is not actor:
        return "no validated runtime binding for this actor was supplied"

    try:
        data = caller_identity()
    except Exception:
        return "could not resolve an authenticated AWS identity"
    if not isinstance(data, dict):
        return "the authenticated identity returned no usable response"
    payload: dict[str, Any] = data
    reported = payload.get("Account")
    if type(reported) is not str or not _ACCOUNT_ID.fullmatch(reported):
        return "the authenticated identity returned no usable account"
    if reported != binding.target_account_id:
        return "the authenticated account does not match the runtime binding"

    identity = parse_assumed_role_arn(payload.get("Arn"))
    if identity is None:
        return "the authenticated identity is not a usable STS assumed-role identity"
    if identity.account != reported:
        return "the assumed-role account does not match the authenticated account"
    if not role_matches_path(actor, path, identity.role_name):
        return f"the authenticated identity is not the governed {actor.value} {path.value} role"

    task_id: str | None = None
    if path is IdentityPath.TASK:
        if not TASK_ID_RE.fullmatch(identity.session_name):
            return "the task-role session is not named by a well-formed task id"
        task_id = identity.session_name
    return ProvenIdentity(actor=actor, path=path, task_id=task_id)


__all__ = [
    "GENERATED_SUFFIX_RE",
    "SESSION_NAME_RE",
    "TASK_ID_RE",
    "AssumedRoleIdentity",
    "ProvenIdentity",
    "generated_role_suffix",
    "parse_assumed_role_arn",
    "production_identity_refusal",
    "role_matches_path",
]
