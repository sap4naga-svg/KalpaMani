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
:class:`SharadarCredential` overrides ``__repr__``, ``__str__`` and
``__format__`` to a fixed placeholder, so an f-string, a ``print``, a
``%``-format, a logging call, a dataclass containing one and a traceback frame
summary all render the placeholder. It is not a dataclass, so no generated
``__repr__`` exists to expose the field. Exactly one method returns the value, and
it is named :meth:`~SharadarCredential.reveal` so that every place the secret is
genuinely used is one grep away.

**And it cannot leak through the unusual ones either.** Two holes were open in an
earlier revision and both are closed here:

*The caller's object was retained.* A ``str`` subclass could reach ``reveal()``
unchanged, and the query builder would then call whatever code that subclass
wanted to run. The secret is rebuilt as an exact plain ``str`` from the character
data the value actually holds, so nothing the caller wrote survives construction.

*Subclassing was permitted.* A subclass could override ``__repr__``, ``__str__``,
``__format__`` or ``reveal`` and put a real key straight into a log line or a
request. :meth:`~SharadarCredential.__init_subclass__` refuses, and the client
additionally requires an exact :class:`SharadarCredential` so a credential-shaped
stand-in cannot be substituted either.

**No vendor alphabet is inferred.** Public documentation establishes no key
format, so guessing one would refuse a legitimate key on the day it is first
used. What *is* refused is what no key can contain and still survive a query
string intact: whitespace and non-printable characters. Legal punctuation stays
the responsibility of URL encoding.

Equality is deliberately not implemented. Comparing two credentials is not
something this system needs to do, and an ``__eq__`` would invite exactly the
"is this the right key?" branch that ends up logging the answer.
"""

from __future__ import annotations

import re
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

#: A generous finite ceiling. Not a vendor-derived length -- no public
#: documentation states one -- but a bound, because an unbounded credential is an
#: unbounded query string and an unbounded thing to hold in memory.
MAX_CREDENTIAL_LENGTH: Final = 512

#: What an environment variable name may look like. Checked so a malformed lookup
#: key fails here rather than somewhere less legible.
_ENV_VAR_NAME: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _refuse() -> SharadarRequestError:
    """The single refusal this module raises. It carries no value, ever."""
    return SharadarRequestError(stage=SharadarStage.BUILD, code=SharadarErrorCode.REQUEST_MALFORMED)


def _exact_text(value: object) -> str | None:
    """``value`` as an exact plain :class:`str` holding its real character data.

    ``None`` for anything that is not a string. A ``str`` subclass is rebuilt from
    the data it actually holds via ``str.__str__``, so an overridden ``__str__``
    cannot substitute something else -- and the lookup is guarded, because an
    object that merely *claims* to be a ``str`` through a spoofed ``__class__``
    makes ``str.__str__`` raise rather than return.
    """
    if type(value) is str:
        return value
    if not isinstance(value, str):
        return None
    try:
        return str(str.__str__(value))
    except Exception:
        return None


class SharadarCredential:
    """An injected Sharadar API key that renders as a placeholder everywhere.

    The value is reachable only through :meth:`reveal`. Every other route out --
    ``repr``, ``str``, an f-string, ``format``, a logging interpolation -- yields
    :data:`CREDENTIAL_PLACEHOLDER`.
    """

    __slots__ = ("_secret",)

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing.

        A subclass could override ``__repr__``, ``__str__``, ``__format__`` or
        ``reveal`` and put a real key into a log line or a request. The whole
        value of this class is that *every* rendering is redacted, and a subclass
        is the one way to make that untrue.
        """
        raise TypeError(
            "SharadarCredential may not be subclassed. A subclass could override a rendering "
            "method or reveal(), which is exactly the guarantee this class exists to make."
        )

    def __init__(self, secret: str) -> None:
        """Wrap ``secret`` as an exact, plain, printable string.

        Raises:
            SharadarRequestError: if ``secret`` is not a string, is empty or
                whitespace, exceeds :data:`MAX_CREDENTIAL_LENGTH`, or contains a
                whitespace or non-printable character. A blank credential would
                otherwise produce a request that looks well formed and fails for a
                reason nobody can see from the log; a control character would
                corrupt the query string it travels in.

                **The refusal never carries the attempted value.** It is built from
                a closed vocabulary, so there is no parameter for one.
        """
        exact = _exact_text(secret)
        if exact is None or not exact.strip():
            raise _refuse()
        if len(exact) > MAX_CREDENTIAL_LENGTH:
            raise _refuse()
        if any(character.isspace() or not character.isprintable() for character in exact):
            raise _refuse()
        self._secret = exact

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
        SharadarRequestError: if ``variable`` is not a plain, well-formed
            environment-variable name, if the mapping cannot be read, or if the
            value is absent, blank or not a string. A hostile or broken mapping
            raises from inside ``__getitem__``; that exception is converted here
            rather than allowed to propagate with whatever it chose to say in it.
    """
    if type(variable) is not str or not _ENV_VAR_NAME.match(variable):
        raise _refuse()
    try:
        value = env.get(variable)
    except Exception:
        raise _refuse() from None
    if value is None:
        raise _refuse()
    return SharadarCredential(value)


__all__ = [
    "CREDENTIAL_ENV_VAR",
    "CREDENTIAL_PLACEHOLDER",
    "MAX_CREDENTIAL_LENGTH",
    "SharadarCredential",
    "credential_from_env",
]
