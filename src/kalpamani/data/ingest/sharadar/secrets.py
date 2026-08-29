"""Retrieving the private Sharadar credential from an injected secrets backend.

ADR-0015. The credential has always been a parameter: every accepted slice takes
a built :class:`~kalpamani.data.ingest.sharadar.credentials.SharadarCredential`
and none of them has ever had a way to obtain one. This module is the missing
half, written the same way as every other boundary in this package -- **the
client is injected, and nothing here constructs one.**

::

    SDK import          NONE     no boto3, no botocore, in this module or any other under src/
    client construction NONE     the caller supplies one; this module builds nothing
    secret identifier   INJECTED no name, ARN, account, region or endpoint is compiled in
    operations          ONE      GetSecretValue, and nothing else is called
    secret reads        ZERO     nothing in this repository calls this against AWS
    value disclosure    NONE     the value goes straight into SharadarCredential

What "injected" buys, exactly
=============================

A ``boto3`` Secrets Manager client satisfies :class:`SecretsClient` structurally,
so the production path can hand one in without this module knowing the SDK
exists. Importing the data platform therefore pulls in no AWS code, performs no
ambient credential discovery and opens no socket -- the same property the S3
store has under ADR-0011, for the same reason.

The one operation
=================

:meth:`SecretsClient.get_secret_value` is the whole protocol. There is no
``list_secrets``, no ``describe_secret``, no ``put_secret_value``, no
``update_secret`` and no ``delete_secret`` in the shape, so this boundary could
not enumerate, create, rotate or destroy a secret even if a later edit tried to.
Reading one value is the least authority that does the job.

Fail closed, and say nothing
============================

Every refusal is a closed :class:`SecretRetrievalFailure` member raised
``from None``. A backend exception carries a secret name, an ARN and often the
account in its message; none of that has a parameter to arrive through here, and
suppressing the cause keeps it out of the traceback as well.

**``SecretString`` only.** ``SecretBinary`` is refused rather than decoded: this
credential is a printable API key, a binary payload is not one, and guessing at
an encoding is how a wrong value reaches a request. There is no JSON parsing, no
key guessing, no alias, no default and no fallback -- the secret's value *is* the
credential, and a secret holding something else is a configuration error to be
fixed at the source rather than papered over here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from kalpamani.data.contracts.errors import PointInTimeError
from kalpamani.data.ingest.sharadar.credentials import SharadarCredential


class SecretRetrievalFailure(StrEnum):
    """Every way retrieving the private credential can fail. Closed on purpose.

    Coarse, like the provider vocabulary and for the same reason: a finer
    category would have to be derived from what the backend said, and what the
    backend says is the one thing that must not travel.
    """

    # The three `SECRET_*` members trip ruff's hardcoded-password heuristic on the
    # member *name*. They are failure tokens in a closed vocabulary -- the values
    # are their own names -- and renaming them to dodge the check would make the
    # vocabulary less accurate about what failed. Suppressed per line, not by
    # disabling the rule.
    CLIENT_UNUSABLE = "CLIENT_UNUSABLE"
    SECRET_IDENTIFIER_MALFORMED = "SECRET_IDENTIFIER_MALFORMED"  # noqa: S105
    BACKEND_REFUSED = "BACKEND_REFUSED"
    RESPONSE_MALFORMED = "RESPONSE_MALFORMED"
    SECRET_BINARY_REFUSED = "SECRET_BINARY_REFUSED"  # noqa: S105
    SECRET_VALUE_UNUSABLE = "SECRET_VALUE_UNUSABLE"  # noqa: S105


class SecretRetrievalError(PointInTimeError):
    """A private credential could not be retrieved. Carries one closed member.

    Nothing else has a home here: no secret name, no ARN, no account, no region,
    no backend message and no attempted value.
    """

    __slots__ = ("failure",)

    def __init__(self, failure: SecretRetrievalFailure) -> None:
        """Carry one failure category, and render it as its token alone."""
        self.failure = (
            failure
            if type(failure) is SecretRetrievalFailure
            else SecretRetrievalFailure.RESPONSE_MALFORMED
        )
        super().__init__(f"sharadar credential retrieval refused: {self.failure.value}")


class SecretsClient(Protocol):
    """The one secrets operation this boundary uses, and nothing else.

    Structurally satisfied by a ``boto3`` Secrets Manager client. Deliberately
    narrow: no listing, no description, no write and no delete, so the least
    authority that can read one value is also the most this shape can express.
    """

    def get_secret_value(self, **kwargs: Any) -> Any:
        """Return one secret's current value."""
        ...


def _refuse(failure: SecretRetrievalFailure) -> SecretRetrievalError:
    return SecretRetrievalError(failure)


def is_usable_secret_identifier(candidate: object) -> bool:
    """Whether ``candidate`` is a secret identifier this boundary would accept.

    Exported because the operator entry point has to decide *before* it builds a
    client whether the identifier its source produced is usable at all -- and a
    second copy of this rule, written slightly differently, is how an identifier
    the caller admitted becomes an identifier the boundary refuses. One rule,
    one place, two callers.

    Accepted: an exact :class:`str`, non-blank, printable, carrying no
    whitespace of any kind. A ``str`` subclass is refused rather than rebuilt --
    the caller's object could change what it reports between the check and the
    request. Nothing about vendor or AWS naming is inferred: a name and an ARN
    are both ordinary printable strings, and guessing at a shape would refuse a
    legitimate identifier on the day it is first used.

    Whitespace is the one structural refusal, and it is not stylistic: a newline
    in an identifier is how a second parameter gets smuggled into a request.
    """
    return (
        type(candidate) is str
        and bool(candidate.strip())
        and not any(character.isspace() or not character.isprintable() for character in candidate)
    )


def sharadar_credential_from_secret(*, client: SecretsClient, secret_id: str) -> SharadarCredential:
    """The private Sharadar credential held under ``secret_id``, as a credential.

    ``client`` is injected and ``secret_id`` is supplied by the caller: no name,
    ARN, account, region or endpoint is compiled into this module, and nothing
    here constructs a client.

    The retrieved value is handed **immediately** to
    :class:`~kalpamani.data.ingest.sharadar.credentials.SharadarCredential` and is
    never bound to a local that outlives the call, never logged, never returned
    and never included in a refusal. Every rendering of the result is the
    placeholder; :meth:`SharadarCredential.reveal` is the only route to the value
    and this function does not call it.

    Raises:
        SecretRetrievalError: one closed :class:`SecretRetrievalFailure` member,
            raised ``from None``.

            ``CLIENT_UNUSABLE`` -- the injected object cannot serve the one
            operation. A ``Protocol`` annotation is a static claim; this is the
            runtime half.

            ``SECRET_IDENTIFIER_MALFORMED`` -- the identifier is not an exact,
            non-blank, printable, single-line ``str``. A newline in an identifier
            is how a second parameter gets smuggled into a request.

            ``BACKEND_REFUSED`` -- the call raised. The cause is suppressed: a
            backend exception quotes the secret name, usually the ARN and often
            the account.

            ``RESPONSE_MALFORMED`` -- the response is not a mapping, or carries
            neither a string value nor a binary one.

            ``SECRET_BINARY_REFUSED`` -- the secret holds ``SecretBinary``. Not
            decoded: an API key is printable text, and guessing at an encoding is
            how a wrong value reaches a request.

            ``SECRET_VALUE_UNUSABLE`` -- the value is present but is not a
            credential the exact-credential contract accepts. That refusal is
            converted here so a caller handles one failure type, and it never
            carries the attempted value either.
    """
    operation = getattr(client, "get_secret_value", None)
    if not callable(operation):
        raise _refuse(SecretRetrievalFailure.CLIENT_UNUSABLE) from None

    if not is_usable_secret_identifier(secret_id):
        raise _refuse(SecretRetrievalFailure.SECRET_IDENTIFIER_MALFORMED) from None

    try:
        response = operation(SecretId=secret_id)
    except Exception:
        raise _refuse(SecretRetrievalFailure.BACKEND_REFUSED) from None

    try:
        has_string = "SecretString" in response
        has_binary = "SecretBinary" in response
        value = response["SecretString"] if has_string else None
    except Exception:
        # A hostile or broken mapping raises from inside __contains__ or
        # __getitem__. Converted here rather than allowed to propagate with
        # whatever the object chose to put in its message.
        raise _refuse(SecretRetrievalFailure.RESPONSE_MALFORMED) from None

    if not has_string:
        # Binary is named separately from "no value at all", because they are
        # different configuration mistakes and want different repairs.
        raise _refuse(
            SecretRetrievalFailure.SECRET_BINARY_REFUSED
            if has_binary
            else SecretRetrievalFailure.RESPONSE_MALFORMED
        ) from None

    if type(value) is not str:
        raise _refuse(SecretRetrievalFailure.RESPONSE_MALFORMED) from None

    try:
        return SharadarCredential(value)
    except Exception:
        # The credential contract already refuses blank, oversized, whitespace-
        # bearing and non-printable values, and its refusal carries no value
        # either. Converted so a caller handles one failure type here.
        raise _refuse(SecretRetrievalFailure.SECRET_VALUE_UNUSABLE) from None


__all__ = [
    "SecretRetrievalError",
    "SecretRetrievalFailure",
    "SecretsClient",
    "is_usable_secret_identifier",
    "sharadar_credential_from_secret",
]
