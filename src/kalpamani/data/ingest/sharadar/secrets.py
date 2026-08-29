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

import re
from enum import StrEnum
from typing import Any, Final, Protocol

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


#: The ``SecretId`` request-parameter ceiling. A longer value is refused here
#: rather than handed to a client that would reject it locally anyway -- and a
#: local parameter rejection arriving at the credential stage is exactly the
#: misclassification ADR-0016 exists to prevent.
MAX_SECRET_ID_LENGTH: Final = 2048

#: The Secrets Manager secret-name ceiling.
MAX_SECRET_NAME_LENGTH: Final = 512

#: The character set a Secrets Manager secret name may draw from: ASCII letters
#: and digits plus ``/``, ``_``, ``+``, ``=``, ``.``, ``@`` and ``-``.
#:
#: Deliberately exact rather than "printable and unspaced". Whitespace, control
#: characters, a colon and every other punctuation mark are excluded -- a colon
#: because it is the ARN field separator, and the rest because a value carrying
#: one is not a name this service will accept and must be refused *here*.
_SECRET_NAME: Final = re.compile(r"[A-Za-z0-9/_+=.@-]+")

#: The AWS partitions this deployment recognises. Closed, because an
#: unrecognised partition in an identifier is a configuration error, not a
#: forward-compatibility feature.
_AWS_PARTITIONS: Final = frozenset({"aws", "aws-cn", "aws-us-gov"})

#: A syntactically valid Region component. Shape only -- whether a Region exists
#: is not something this boundary can know, and guessing at a list would refuse
#: a legitimate Region on the day it opens.
_AWS_REGION: Final = re.compile(r"[a-z]{2}(?:-[a-z]+)+-\d{1,2}")

#: An account component: ASCII digits, and exactly twelve of them.
_AWS_ACCOUNT: Final = re.compile(r"[0-9]{12}")

#: The suffix structure Secrets Manager appends when it generates an ARN: a
#: hyphen and six alphanumeric characters.
#:
#: This is what separates a **complete** ARN from a partial one. It checks that
#: the structure is *present*; it cannot distinguish a name that happens to end
#: that way from a generated suffix, because nothing can -- the two are
#: lexically identical, and that is a property of the ARN format rather than a
#: gap in this check.
_ARN_GENERATED_SUFFIX: Final = re.compile(r".+-[A-Za-z0-9]{6}")


def _is_secret_name(candidate: str) -> bool:
    """Whether ``candidate`` is a well-formed Secrets Manager secret name."""
    return (
        1 <= len(candidate) <= MAX_SECRET_NAME_LENGTH
        and _SECRET_NAME.fullmatch(candidate) is not None
    )


def _is_complete_secret_arn(candidate: str) -> bool:
    """Whether ``candidate`` is a complete Secrets Manager secret ARN.

    Seven colon-separated fields, exactly: ``arn``, a recognised partition, the
    service, a Region, a twelve-digit account, the resource type ``secret``, and
    a name carrying the generated suffix structure. A field count other than
    seven refuses a colon-bearing name as well, which is the same defect seen
    from the other side.
    """
    fields = candidate.split(":")
    if len(fields) != 7:
        return False
    scheme, partition, service, region, account, resource_type, name = fields
    return (
        scheme == "arn"
        and partition in _AWS_PARTITIONS
        and service == "secretsmanager"
        and _AWS_REGION.fullmatch(region) is not None
        and _AWS_ACCOUNT.fullmatch(account) is not None
        and resource_type == "secret"
        and _is_secret_name(name)
        and _ARN_GENERATED_SUFFIX.fullmatch(name) is not None
    )


def is_usable_secret_identifier(candidate: object) -> bool:
    """Whether ``candidate`` is a secret identifier this boundary would accept.

    Exported because the operator entry point has to decide *before* it builds a
    client whether the identifier its source produced is usable at all -- and a
    second copy of this rule, written slightly differently, is how an identifier
    the caller admitted becomes an identifier the boundary refuses. One rule,
    one place, two callers.

    Accepted: an exact :class:`str` within the ``SecretId`` ceiling that is
    **either** a well-formed secret name **or** a complete secret ARN. A
    ``str`` subclass is refused rather than rebuilt -- the caller's object could
    change what it reports between the check and the call.

    **The earlier rule was "printable, and no whitespace", and that was too
    broad** (ADR-0016, correction round 1). It admitted identifiers no Secrets
    Manager client would accept, so a local parameter rejection happened *after*
    ``get_secret_value`` had been entered and was then reported as a credential
    failure. Refusing the shape here keeps that classification honest.

    A colon routes the decision, because a name may not contain one: anything
    carrying a colon is being offered as an ARN and is held to the ARN grammar
    rather than falling back to the looser one.

    **Nothing is transformed.** The identifier is not trimmed, normalised,
    rebuilt, lowercased, returned or rendered -- this answers a question about
    it and nothing else.
    """
    if type(candidate) is not str:
        return False
    if not 1 <= len(candidate) <= MAX_SECRET_ID_LENGTH:
        return False
    if ":" in candidate:
        return _is_complete_secret_arn(candidate)
    return _is_secret_name(candidate)


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

            ``SECRET_IDENTIFIER_MALFORMED`` -- the identifier is neither a
            well-formed secret name nor a complete secret ARN, as
            :func:`is_usable_secret_identifier` defines those. Refused **before**
            ``get_secret_value`` is entered, so a shape this service would reject
            locally can never be reported as a credential failure.

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
    "MAX_SECRET_ID_LENGTH",
    "MAX_SECRET_NAME_LENGTH",
    "SecretRetrievalError",
    "SecretRetrievalFailure",
    "SecretsClient",
    "is_usable_secret_identifier",
    "sharadar_credential_from_secret",
]
