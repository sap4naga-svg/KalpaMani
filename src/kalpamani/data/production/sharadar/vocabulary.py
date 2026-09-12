"""The two production actors and every constant compiled for each (ADR-0036 §2.1).

**Compiled, never read from a binding, an input, a release or the environment.**
ADR-0036 §2.5 makes the expected task-role name "a constant in the image, not a
field of the binding", so a forged binding fails a comparison rather than steering
one. The same holds for every value here: a document may *match* one of these, and
none of them may be *supplied* by a document.

The literals are the ones the merged Terraform declaration compiles
(``infra/aws/research-data-plane/production_*.tf``); a test holds the two spellings
together so they cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class ProductionActor(StrEnum):
    """The two ADR-0036 actors. A closed vocabulary of exactly two."""

    ACQUISITION = "acquisition"
    BUILD = "build"


class IdentityPath(StrEnum):
    """Which principal shape a run proves its identity under (ADR-0036 §2.5).

    ``HUMAN`` is the actor's Identity Center permission-set role, ``LAUNCHER`` the
    actor's launcher permission-set role, and ``TASK`` the actor's ECS task role.
    Each is a different generated or declared role, so the same actor may never be
    admitted under the wrong one.
    """

    HUMAN = "human"
    LAUNCHER = "launcher"
    TASK = "task"


@dataclass(frozen=True, slots=True, kw_only=True)
class ActorConstants:
    """Everything ADR-0036 compiles for one actor. Every field is a constant."""

    actor: ProductionActor
    permission_set: str
    launcher_permission_set: str
    task_role_name: str
    task_family: str
    profile: str
    profile_field: str
    binding_kind: str
    binding_contract_id: str
    binding_env_var: str
    binding_parameter: str
    input_contract_id: str
    input_parameter: str
    release_parameter: str
    identity_field: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a constant that can be overridden is not one."""
        raise TypeError("ActorConstants may not be subclassed")


#: The governed partition and region, restated here and compared rather than
#: accepted from a document (the qualification loader does the same).
EXPECTED_PARTITION: Final = "aws"
EXPECTED_REGION: Final = "us-east-1"

#: The fixed name prefix IAM Identity Center gives every role it generates.
GENERATED_ROLE_PREFIX: Final = "AWSReservedSSO_"

#: The placement-release contract, shared by both actors; the actor field differs.
RELEASE_CONTRACT_ID: Final = "kalpamani-placement-release/v1"

#: SSM parameter tiers and their value ceilings, from the Parameter Store limits:
#: standard tier 4 KiB, advanced tier 8 KiB. A binding is standard tier; inputs and
#: releases are advanced tier. Refused above the ceiling **before parsing**.
MAX_BINDING_PARAMETER_BYTES: Final = 4 * 1024
MAX_ADVANCED_PARAMETER_BYTES: Final = 8 * 1024

#: The whole of what either actor compiles, keyed by actor. Two entries, no more.
ACTORS: Final[dict[ProductionActor, ActorConstants]] = {
    ProductionActor.ACQUISITION: ActorConstants(
        actor=ProductionActor.ACQUISITION,
        permission_set="KalpaManiProductionAcquire",
        launcher_permission_set="KalpaManiAcquireLauncher",
        task_role_name="kalpamani-production-acquire-task",
        task_family="kalpamani-production-acquire",
        profile="kalpamani-production-acquisition",
        profile_field="acquisition_profile",
        binding_kind="kalpamani-production-acquisition-runtime",
        binding_contract_id="kalpamani-production-acquisition-runtime-binding/v1",
        binding_env_var="KALPAMANI_PRODUCTION_ACQUISITION_RUNTIME_BINDING_FILE",
        binding_parameter="/kalpamani/production/acquisition/runtime-binding",
        input_contract_id="kalpamani-production-acquisition-input/v1",
        input_parameter="/kalpamani/production/acquisition/input",
        release_parameter="/kalpamani/production/acquisition/release",
        identity_field="run_identity",
    ),
    ProductionActor.BUILD: ActorConstants(
        actor=ProductionActor.BUILD,
        permission_set="KalpaManiResearchBuild",
        launcher_permission_set="KalpaManiBuildLauncher",
        task_role_name="kalpamani-research-build-task",
        task_family="kalpamani-research-build",
        profile="kalpamani-research-build",
        profile_field="build_profile",
        binding_kind="kalpamani-research-build-runtime",
        binding_contract_id="kalpamani-research-build-runtime-binding/v1",
        binding_env_var="KALPAMANI_RESEARCH_BUILD_RUNTIME_BINDING_FILE",
        binding_parameter="/kalpamani/production/research-build/runtime-binding",
        input_contract_id="kalpamani-research-build-input/v1",
        input_parameter="/kalpamani/production/research-build/input",
        release_parameter="/kalpamani/production/research-build/release",
        identity_field="build_identity",
    ),
}


def constants_for(actor: object) -> ActorConstants:
    """The compiled constants of one actor. An exact member, or a refusal.

    Raises:
        TypeError: for anything but an exact :class:`ProductionActor` member. A
            string that merely equals one is refused: the vocabulary is closed, and
            a caller holding a bare string has not been through it.
    """
    if type(actor) is not ProductionActor:
        raise TypeError("actor must be an exact ProductionActor member")
    return ACTORS[actor]


__all__ = [
    "ACTORS",
    "EXPECTED_PARTITION",
    "EXPECTED_REGION",
    "GENERATED_ROLE_PREFIX",
    "MAX_ADVANCED_PARAMETER_BYTES",
    "MAX_BINDING_PARAMETER_BYTES",
    "RELEASE_CONTRACT_ID",
    "ActorConstants",
    "IdentityPath",
    "ProductionActor",
    "constants_for",
]
