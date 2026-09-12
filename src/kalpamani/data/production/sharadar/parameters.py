"""The parameter channel: one closed failure vocabulary, and the SSM adapter.

Bindings, inputs and releases travel through per-actor SSM ``SecureString``
parameters (ADR-0036 §2.5, §2.6, §2.9). Three operations exist across the two
sides -- a task **reads** one exact parameter; a human or launcher **creates**
one (never overwrites) and **deletes** it -- and each is classified into the same
closed vocabulary so a caller can tell *not yet released* from *refused* without
ever seeing the backend's message.

The adapter takes an injected SSM-shaped object and constructs the exact request
each operation needs. It has only ever been exercised against synthetic fakes:
**no AWS request has been sent through it**, and nothing here constructs a client.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Final, Protocol


class ParameterOperation(StrEnum):
    """What the channel was doing when it refused."""

    GET = "GET"
    PUT = "PUT"
    DELETE = "DELETE"


class ParameterFailure(StrEnum):
    """Why a parameter operation refused. Closed and coarse.

    ``NOT_FOUND`` is the one failure the release barrier tolerates (*not yet
    released*); ``ALREADY_EXISTS`` is the create-only conflict the stale-input and
    stale-release guards rest on. Everything else refuses at once.
    """

    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    ACCESS_DENIED = "ACCESS_DENIED"
    THROTTLED = "THROTTLED"
    TRANSIENT = "TRANSIENT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    UNKNOWN = "UNKNOWN"


class ParameterError(Exception):
    """A refusal built from two closed vocabulary members and nothing else."""

    __slots__ = ("failure", "operation")

    def __init__(self, *, operation: ParameterOperation, failure: ParameterFailure) -> None:
        """Carry an operation and a failure category. Nothing else has a home here."""
        if type(operation) is not ParameterOperation or type(failure) is not ParameterFailure:
            raise TypeError("operation and failure must be exact members")
        self.operation = operation
        self.failure = failure
        super().__init__(f"parameter {operation.value}: {failure.value}")


def _refuse(operation: ParameterOperation, failure: ParameterFailure) -> ParameterError:
    return ParameterError(operation=operation, failure=failure)


#: SSM error codes, matched exactly. Anything unrecognised is ``UNKNOWN``.
_NOT_FOUND_CODES: Final[frozenset[str]] = frozenset({"ParameterNotFound"})
_EXISTS_CODES: Final[frozenset[str]] = frozenset({"ParameterAlreadyExists"})
_DENIED_CODES: Final[frozenset[str]] = frozenset(
    {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}
)
_THROTTLED_CODES: Final[frozenset[str]] = frozenset(
    {"ThrottlingException", "Throttling", "TooManyUpdates", "TooManyRequestsException"}
)
_TRANSIENT_CODES: Final[frozenset[str]] = frozenset(
    {"InternalServerError", "ServiceUnavailable", "RequestTimeout"}
)


def _error_code(exception: BaseException) -> str:
    """The backend's error code, read structurally so no SDK import is needed."""
    try:
        response = getattr(exception, "response", None)
        if not isinstance(response, Mapping):
            return ""
        error = response.get("Error")
        if not isinstance(error, Mapping):
            return ""
        code = error.get("Code")
        return code if type(code) is str else ""
    except Exception:
        return ""


def classify_parameter_failure(exception: BaseException) -> ParameterFailure:
    """Reduce a backend exception to one closed category. Nothing survives it."""
    code = _error_code(exception)
    if code in _NOT_FOUND_CODES:
        return ParameterFailure.NOT_FOUND
    if code in _EXISTS_CODES:
        return ParameterFailure.ALREADY_EXISTS
    if code in _DENIED_CODES:
        return ParameterFailure.ACCESS_DENIED
    if code in _THROTTLED_CODES:
        return ParameterFailure.THROTTLED
    if code in _TRANSIENT_CODES:
        return ParameterFailure.TRANSIENT
    return ParameterFailure.UNKNOWN


class SsmLikeClient(Protocol):
    """The three SSM operations the channel uses. Structurally a ``boto3`` client."""

    def get_parameter(self, **kwargs: Any) -> Any:
        """Read one parameter."""
        ...

    def put_parameter(self, **kwargs: Any) -> Any:
        """Create one parameter."""
        ...

    def delete_parameter(self, **kwargs: Any) -> Any:
        """Delete one parameter."""
        ...


#: The advanced tier and the lifecycle policy shapes ADR-0036 prescribes: inputs
#: expire 24 h after materialization, releases 1 h. A lifecycle policy grants no
#: access; it is supplied in the same ``PutParameter`` call as the value.
ADVANCED_TIER: Final = "Advanced"
SECURE_STRING: Final = "SecureString"


def expiration_policy(*, expires_at_iso: str) -> str:
    """The ``Policies`` JSON for one ``Expiration`` lifecycle policy."""
    return json.dumps(
        [{"Type": "Expiration", "Version": "1.0", "Attributes": {"Timestamp": expires_at_iso}}],
        separators=(",", ":"),
    )


class SsmParameterAdapter:
    """Exact-name parameter operations over an injected SSM-shaped object.

    Counters survive a refusal, so a caller can report what was attempted.
    """

    __slots__ = ("_ssm", "delete_count", "get_count", "put_count")

    def __init__(self, *, ssm: SsmLikeClient) -> None:
        """Bind an injected client-shaped object. Nothing is constructed here."""
        for method in ("get_parameter", "put_parameter", "delete_parameter"):
            if not callable(getattr(ssm, method, None)):
                raise _refuse(ParameterOperation.GET, ParameterFailure.INVALID_CONFIGURATION)
        self._ssm = ssm
        self.get_count = 0
        self.put_count = 0
        self.delete_count = 0

    def read_parameter(self, name: str) -> bytes:
        """``GetParameter`` with decryption on exactly ``name``; the value as UTF-8 bytes.

        Raises:
            ParameterError: ``GET`` with the classified failure; ``INVALID_RESPONSE``
                for a response without a string ``Parameter.Value``.
        """
        self.get_count += 1
        try:
            response = self._ssm.get_parameter(Name=name, WithDecryption=True)
        except Exception as exception:
            raise _refuse(ParameterOperation.GET, classify_parameter_failure(exception)) from None
        parameter = response.get("Parameter") if isinstance(response, Mapping) else None
        value = parameter.get("Value") if isinstance(parameter, Mapping) else None
        if type(value) is not str:
            raise _refuse(ParameterOperation.GET, ParameterFailure.INVALID_RESPONSE) from None
        return value.encode("utf-8")

    def create_parameter(
        self, name: str, value: bytes, *, key_id: str, expires_at_iso: str
    ) -> None:
        """``PutParameter`` **without** ``Overwrite``: create only, advanced tier.

        Raises:
            ParameterError: ``PUT`` with the classified failure; ``ALREADY_EXISTS``
                is the stale-input / stale-release guard firing.
        """
        if type(value) is not bytes:
            raise _refuse(ParameterOperation.PUT, ParameterFailure.INVALID_CONFIGURATION)
        self.put_count += 1
        try:
            self._ssm.put_parameter(
                Name=name,
                Value=value.decode("utf-8"),
                Type=SECURE_STRING,
                KeyId=key_id,
                Tier=ADVANCED_TIER,
                Overwrite=False,
                Policies=expiration_policy(expires_at_iso=expires_at_iso),
            )
        except Exception as exception:
            raise _refuse(ParameterOperation.PUT, classify_parameter_failure(exception)) from None

    def delete_parameter(self, name: str) -> None:
        """``DeleteParameter`` on exactly ``name``.

        Raises:
            ParameterError: ``DELETE`` with the classified failure.
        """
        self.delete_count += 1
        try:
            self._ssm.delete_parameter(Name=name)
        except Exception as exception:
            raise _refuse(
                ParameterOperation.DELETE, classify_parameter_failure(exception)
            ) from None


__all__ = [
    "ADVANCED_TIER",
    "SECURE_STRING",
    "ParameterError",
    "ParameterFailure",
    "ParameterOperation",
    "SsmLikeClient",
    "SsmParameterAdapter",
    "classify_parameter_failure",
    "expiration_policy",
]
