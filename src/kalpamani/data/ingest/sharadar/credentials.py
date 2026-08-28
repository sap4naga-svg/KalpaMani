"""The Sharadar credential boundary.

**This module contains no API key value, and neither does anything else under
``src/``.** Not a private one, and not the vendor's published test token either.
The published token legitimately lives in the already-approved private
qualification harness under ``scripts/``, and it stays there: a value that is
harmless in a manual, owner-run probe becomes a habit if production code carries
one, and the habit is what eventually commits a real key.

A credential arrives by **injection** -- constructed by a future authorized runner
from an environment variable or an external secret manager and handed to the
client. This slice creates no secret and reads none: :func:`credential_from_env`
takes an explicit mapping, and this module never touches the process environment
itself, so "no real secret is read here" is a property of the code rather than a
promise about how it is called.

**The value cannot leak through the ordinary accidents.**
:class:`SharadarCredential` overrides ``__repr__``, ``__str__`` and ``__format__``
to a fixed placeholder, so an f-string, a ``print``, a ``%``-format, a logging
call, a dataclass containing one and a traceback frame summary all render the
placeholder. It is not a dataclass, so no generated ``__repr__`` exists to expose
the field. Exactly one method returns the value, and it is named
:meth:`~SharadarCredential.reveal` so that every place the secret is genuinely
used is one grep away.

Equality is deliberately not implemented. Comparing two credentials is not
something this system needs to do, and an ``__eq__`` would invite exactly the
"is this the right key?" branch that ends up logging the answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from kalpamani.data.ingest.sharadar.redaction import (
    SharadarErrorCode,
    SharadarRequestError,
    SharadarStage,
)

#: What every rendering of a credential shows instead of the value.
CREDENTIAL_PLACEHOLDER: Final = "<sharadar-credential:redacted>"

#: The environment variable a future authorized runner is expected to read from.
#: Named here so the name is reviewable; **nothing in this slice reads it**.
CREDENTIAL_ENV_VAR: Final = "KALPAMANI_SHARADAR_API_KEY"


class SharadarCredential:
    """An injected Sharadar API key that renders as a placeholder everywhere.

    The value is reachable only through :meth:`reveal`. Every other route out --
    ``repr``, ``str``, an f-string, ``format``, a logging interpolation -- yields
    :data:`CREDENTIAL_PLACEHOLDER`.
    """

    __slots__ = ("_secret",)

    def __init__(self, secret: str) -> None:
        """Wrap ``secret``.

        Raises:
            SharadarRequestError: if ``secret`` is empty or whitespace, or carries
                a character that cannot appear in a query parameter. A blank
                credential would otherwise produce a request that looks
                well-formed and fails for a reason nobody can see from the log.
        """
        if not secret or not secret.strip():
            raise SharadarRequestError(
                stage=SharadarStage.BUILD, code=SharadarErrorCode.REQUEST_MALFORMED
            )
        if any(character.isspace() for character in secret):
            raise SharadarRequestError(
                stage=SharadarStage.BUILD, code=SharadarErrorCode.REQUEST_MALFORMED
            )
        self._secret = secret

    def reveal(self) -> str:
        """The credential value. **The only route to it, and named to be greppable.**"""
        return self._secret

    def __repr__(self) -> str:
        """The placeholder. Never the value."""
        return CREDENTIAL_PLACEHOLDER

    def __str__(self) -> str:
        """The placeholder. Never the value."""
        return CREDENTIAL_PLACEHOLDER

    def __format__(self, format_spec: str) -> str:
        """The placeholder, whatever the format spec asks for."""
        return CREDENTIAL_PLACEHOLDER


def credential_from_env(
    env: Mapping[str, str], *, variable: str = CREDENTIAL_ENV_VAR
) -> SharadarCredential:
    """Build a credential from an **explicitly supplied** mapping.

    The mapping is a parameter rather than ``os.environ``, so this module has no
    route to the real process environment and a test cannot accidentally pick up a
    developer's key. A future authorized runner passes ``os.environ`` in at the
    one place that is allowed to.

    Raises:
        SharadarRequestError: if ``variable`` is absent or empty.
    """
    value = env.get(variable, "")
    if not value:
        raise SharadarRequestError(
            stage=SharadarStage.BUILD, code=SharadarErrorCode.REQUEST_MALFORMED
        )
    return SharadarCredential(value)


__all__ = [
    "CREDENTIAL_ENV_VAR",
    "CREDENTIAL_PLACEHOLDER",
    "SharadarCredential",
    "credential_from_env",
]
