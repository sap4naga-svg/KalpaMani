"""Task-side client boundaries: identity, capabilities, configuration and environment.

Everything a task entrypoint needs *around* a real SDK client, stated here without an
SDK: the module names no ``boto3`` and constructs nothing. The image entrypoint
constructs the clients from the pure configuration dictionaries below and hands them
in; the tests hand in fakes. Four concerns, each one small on purpose:

**Identity.** :class:`StsCallerIdentityAdapter` is the accepted identity gate's
``caller_identity`` callable over an STS-shaped client: it issues one
``GetCallerIdentity``, reduces the response to its three documented fields, and raises
a value-free error for anything else. The gate compares; this adapter only fetches.

**Capabilities.** :class:`PutOnlyS3Client` exposes ``put_object`` and nothing else;
:class:`ReadWriteS3Client` exposes ``get_object`` and ``put_object`` and nothing else.
The acquisition entrypoint wraps its client in the first before any processing module
sees it, so even a client that *carries* a read method offers none to the writer side
(ADR-0019, ADR-0036 §2.2); the build entrypoint wraps in the second (§2.3).

**Configuration.** The SDK must not be able to add attempts the accounting never
counted or hold a socket open past the deadline's per-operation ceiling. Every task
client therefore takes the qualification path's explicit settings -- one attempt in
total, both socket timeouts finite -- expressed as plain dictionaries a test can assert
without importing an SDK. The S3 dictionary is the accepted one, imported rather than
restated. STS is pinned to the **regional** endpoint, because the interface endpoint
serves ``sts.<region>.amazonaws.com`` and not the global name (ADR-0036 §2.8).

**Environment and credential source.** A task's credentials come from the ECS agent's
container credential provider and from nothing else. Two checks, in order. By variable
**name** the task refuses an environment that carries a static key, a profile, a shared
credentials or config file, a web-identity role, the full-URI container variant or a
container authorization token, and requires the Fargate relative-URI variable to be
present. By **value** -- the one credential-related value the task reads -- the relative
URI must be exactly the documented ``/v2/credentials/<id>`` shape, which is served from
the link-local agent address and is **not** the task metadata endpoint's ``/v4/`` path.
Both refusals happen before any client exists (ADR-0036 §2.5: a default chain refuses
before any operation). The names-only refusal is necessary but not sufficient: the
image entrypoint additionally constructs every client from a session whose credential
resolver holds **only** the container provider, so no default chain is ever consulted.

**Origin.** The acquisition runner resolves the pinned provider host at start and
refuses if any resolved address falls outside the compiled set the Terraform gate
materialized (ADR-0036 §2.8). The resolver is injected; an empty compiled set refuses
every address, so an unconfigured image fails closed.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import Any, Final, Protocol

from kalpamani.data.ingest.sharadar.transport import ALLOWED_HOST
from kalpamani.data.production.sharadar.vocabulary import EXPECTED_REGION
from kalpamani.data.qualify.sharadar.plan import (
    S3_CONNECT_TIMEOUT_SECONDS,
    S3_READ_TIMEOUT_SECONDS,
    S3_RETRY_MODE,
    S3_TOTAL_MAX_ATTEMPTS,
    s3_client_config_kwargs,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class StsLikeClient(Protocol):
    """The one STS operation the task uses. Structurally a ``boto3`` STS client."""

    def get_caller_identity(self) -> Any:
        """The authenticated identity."""
        ...


class IdentityUnavailableError(Exception):
    """The identity call raised or answered outside its documented shape. **No text.**"""

    __slots__ = ()

    def __init__(self) -> None:
        """Carry the fixed sentence."""
        super().__init__("the authenticated identity could not be obtained")


#: The documented ``GetCallerIdentity`` response fields, and the only ones passed on.
CALLER_IDENTITY_FIELDS: Final[frozenset[str]] = frozenset({"UserId", "Account", "Arn"})


class StsCallerIdentityAdapter:
    """One ``GetCallerIdentity`` per call, reduced to documented fields, counted."""

    __slots__ = ("_sts", "calls")

    def __init__(self, *, sts: StsLikeClient) -> None:
        """Bind an injected STS-shaped object. Nothing is constructed here."""
        if not callable(getattr(sts, "get_caller_identity", None)):
            raise TypeError("an STS client must provide a callable get_caller_identity")
        self._sts = sts
        self.calls = 0

    def __repr__(self) -> str:
        """The count only."""
        return f"StsCallerIdentityAdapter(calls={self.calls})"

    def __call__(self) -> dict[str, str]:
        """The three documented fields as strings, or raise value-free."""
        self.calls += 1
        try:
            response = self._sts.get_caller_identity()
        except Exception:
            raise IdentityUnavailableError() from None
        if not isinstance(response, dict):
            raise IdentityUnavailableError()
        reduced: dict[str, str] = {}
        for name in sorted(CALLER_IDENTITY_FIELDS):
            value = response.get(name)
            if type(value) is not str or not value:
                raise IdentityUnavailableError()
            reduced[name] = value
        return reduced


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


class PutOnlyS3Client:
    """``put_object`` and nothing else, over an injected client. The writer's whole shape."""

    __slots__ = ("_client",)

    def __init__(self, client: Any) -> None:
        """Require the one method; carry nothing else forward."""
        if not callable(getattr(client, "put_object", None)):
            raise TypeError("a put-only client must provide a callable put_object")
        self._client = client

    def __repr__(self) -> str:
        """A fixed token."""
        return "PutOnlyS3Client()"

    def put_object(self, **kwargs: Any) -> Any:
        """Forward one conditional write unchanged."""
        return self._client.put_object(**kwargs)


class ReadWriteS3Client:
    """``get_object`` and ``put_object`` and nothing else. The build actor's whole shape."""

    __slots__ = ("_client",)

    def __init__(self, client: Any) -> None:
        """Require both methods; carry nothing else forward."""
        for method in ("get_object", "put_object"):
            if not callable(getattr(client, method, None)):
                raise TypeError(f"a read-write client must provide a callable {method}")
        self._client = client

    def __repr__(self) -> str:
        """A fixed token."""
        return "ReadWriteS3Client()"

    def get_object(self, **kwargs: Any) -> Any:
        """Forward one exact read unchanged."""
        return self._client.get_object(**kwargs)

    def put_object(self, **kwargs: Any) -> Any:
        """Forward one conditional write unchanged."""
        return self._client.put_object(**kwargs)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TaskService(StrEnum):
    """The services a task client may be built for. Closed."""

    S3 = "s3"
    SSM = "ssm"
    STS = "sts"
    SECRETS_MANAGER = "secretsmanager"


def client_config_kwargs(service: TaskService) -> dict[str, object]:
    """The botocore ``Config`` arguments for one task client. Pure; imports no SDK.

    S3 takes the accepted qualification dictionary unchanged. The other three take the
    same finite socket timeouts and the same **one attempt in total** in ``standard``
    mode: a hidden SDK retry on the release barrier would be a parameter read the
    barrier's ceiling never counted, on STS a second identity call, and on Secrets
    Manager a second retrieval.
    """
    if type(service) is not TaskService:
        raise TypeError("service must be an exact TaskService member")
    if service is TaskService.S3:
        return s3_client_config_kwargs()
    return {
        "connect_timeout": S3_CONNECT_TIMEOUT_SECONDS,
        "read_timeout": S3_READ_TIMEOUT_SECONDS,
        "retries": {"total_max_attempts": S3_TOTAL_MAX_ATTEMPTS, "mode": S3_RETRY_MODE},
    }


def sts_endpoint_url(region: str = EXPECTED_REGION) -> str:
    """The regional STS endpoint the interface endpoint serves. Never the global name."""
    if type(region) is not str or region != EXPECTED_REGION:
        raise ValueError("the governed region is the only region")
    return f"https://sts.{region}.amazonaws.com"


def client_construction_kwargs(service: TaskService) -> dict[str, object]:
    """Every keyword the image entrypoint passes to ``boto3.client`` for ``service``.

    Region pinned; STS additionally pinned to its regional endpoint; the ``config``
    entry is the dictionary above, left for the caller to wrap in ``Config`` because
    this module imports no SDK.
    """
    kwargs: dict[str, object] = {
        "service_name": service.value,
        "region_name": EXPECTED_REGION,
        "config": client_config_kwargs(service),
    }
    if service is TaskService.STS:
        kwargs["endpoint_url"] = sts_endpoint_url()
    return kwargs


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

#: The ECS container credential provider's documented Fargate variable: a relative
#: URI the agent serves from its link-local address. The only accepted source.
CONTAINER_CREDENTIAL_VARIABLE: Final = "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"
#: The variables that mean *container*: only the relative one.
CONTAINER_CREDENTIAL_VARIABLES: Final[frozenset[str]] = frozenset({CONTAINER_CREDENTIAL_VARIABLE})

#: Variables whose presence means a credential source other than the Fargate
#: container provider could be consulted, or the provider could be redirected.
#: Refused by name; no value is ever read for these.
WORKSTATION_CREDENTIAL_VARIABLES: Final[frozenset[str]] = frozenset(
    {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_SHARED_CREDENTIALS_FILE",
        "AWS_CONFIG_FILE",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_ROLE_ARN",
        "AWS_EC2_METADATA_DISABLED",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
    }
)

#: The link-local address the ECS agent serves container credentials from, and the
#: documented shape of the relative URI it places in the environment. The host is the
#: metadata endpoint's; the path family is not, and the two are never confused.
CONTAINER_CREDENTIAL_HOST: Final = "169.254.170.2"
CONTAINER_CREDENTIAL_PATH_RE: Final = re.compile(r"/v2/credentials/[A-Za-z0-9-]{1,64}")


def task_credential_environment_refusal(variable_names: Iterable[str]) -> str | None:
    """Why the task's credential environment is refused, or ``None``.

    Names only. A workstation, ambient, full-URI or token variable refuses; the Fargate
    relative-URI variable must be present. Value-free reasons.
    """
    present = {name for name in variable_names if type(name) is str}
    if present & WORKSTATION_CREDENTIAL_VARIABLES:
        return "a non-container AWS credential source is present in the task environment"
    if CONTAINER_CREDENTIAL_VARIABLE not in present:
        return "the container credential provider is not present in the task environment"
    return None


def container_credential_source_refusal(environment: Callable[[str], object]) -> str | None:
    """Why the container credential source is refused, or ``None``.

    Reads exactly one value: the relative URI. It must be a string of the documented
    ``/v2/credentials/<id>`` shape -- no scheme, host, userinfo, query or fragment, and
    never the metadata endpoint's ``/v4/`` path. Value-free reasons.
    """
    try:
        value = environment(CONTAINER_CREDENTIAL_VARIABLE)
    except Exception:
        return "the container credential relative URI could not be read"
    if type(value) is not str or not value:
        return "the container credential relative URI is absent"
    if not CONTAINER_CREDENTIAL_PATH_RE.fullmatch(value):
        return "the container credential relative URI is not the documented shape"
    return None


def container_credentials_url(relative_uri: str) -> str:
    """The full container-credential URL for an admitted relative URI, and only one."""
    if not CONTAINER_CREDENTIAL_PATH_RE.fullmatch(relative_uri):
        raise ValueError("the relative URI is not the documented container credential shape")
    return f"http://{CONTAINER_CREDENTIAL_HOST}{relative_uri}"


# ---------------------------------------------------------------------------
# Origin
# ---------------------------------------------------------------------------

#: The pinned provider host the transport talks to, imported so the two cannot drift.
PROVIDER_ORIGIN_HOST: Final = ALLOWED_HOST


def compiled_origin_addresses(candidates: Iterable[object]) -> frozenset[str]:
    """A compiled address set: distinct IPv4 literals in canonical form, or refuse."""
    addresses: set[str] = set()
    for candidate in candidates:
        if type(candidate) is not str:
            raise ValueError("a compiled origin address must be a string")
        try:
            parsed = ipaddress.IPv4Address(candidate)
        except ValueError:
            raise ValueError("a compiled origin address must be an IPv4 literal") from None
        addresses.add(str(parsed))
    return frozenset(addresses)


def origin_address_refusal(
    *, compiled: frozenset[str], resolve: Callable[[str], Iterable[object]]
) -> str | None:
    """Why the resolved provider origin is refused, or ``None``.

    The resolver is called once with the pinned host. Every resolved IPv4 address must
    be in the compiled set; an empty compiled set, a resolver that raises, a resolver
    that returns nothing, and any non-IPv4 answer each refuse. Value-free reasons.
    """
    if not compiled:
        return "no compiled origin address set exists in this image"
    try:
        resolved = list(resolve(PROVIDER_ORIGIN_HOST))
    except Exception:
        return "the provider origin could not be resolved"
    if not resolved:
        return "the provider origin resolved to no address"
    for candidate in resolved:
        if type(candidate) is not str:
            return "the provider origin resolved to a non-string answer"
        try:
            parsed = ipaddress.IPv4Address(candidate)
        except ValueError:
            return "the provider origin resolved to a non-IPv4 address"
        if str(parsed) not in compiled:
            return "the provider origin resolved outside the compiled address set"
    return None


__all__ = [
    "CALLER_IDENTITY_FIELDS",
    "CONTAINER_CREDENTIAL_HOST",
    "CONTAINER_CREDENTIAL_PATH_RE",
    "CONTAINER_CREDENTIAL_VARIABLE",
    "CONTAINER_CREDENTIAL_VARIABLES",
    "PROVIDER_ORIGIN_HOST",
    "WORKSTATION_CREDENTIAL_VARIABLES",
    "IdentityUnavailableError",
    "PutOnlyS3Client",
    "ReadWriteS3Client",
    "StsCallerIdentityAdapter",
    "StsLikeClient",
    "TaskService",
    "client_config_kwargs",
    "client_construction_kwargs",
    "compiled_origin_addresses",
    "container_credential_source_refusal",
    "container_credentials_url",
    "origin_address_refusal",
    "sts_endpoint_url",
    "task_credential_environment_refusal",
]
