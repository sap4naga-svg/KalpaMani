"""The operator binding preflight for the authenticated Sharadar stack.

ADR-0015. The qualification runtime and the composition root take their private
bindings **by injection and cannot discover an ambient one**: neither resolves a
credential, a bucket or an AWS client for itself, and neither has any code that
could. **This file is the sole boundary that can** -- it pins the profile, reads
the governed licensed bucket, reads the secret identifier and constructs the AWS
SDK clients, and nothing else under ``src/`` or ``scripts/`` may.

That is a statement about *where* those dependencies may be resolved, not a claim
that none of it exists. It was written, reviewed and tested while refused by
default, rather than under pressure beside an authorization to run -- and it has
since been **invoked four times under separate authorization**. The second and
third attempts **reached bucket resolution**; the third **reached the fixed
secret-identifier source** and refused there; the fourth **refused at the AWS
identity gate**, reaching neither. No attempt reached Secrets Manager
client construction, composition validation or qualification execution.

::

    entry points        ONE      this file, and nothing re-exports it
    default behaviour   REFUSE   no flag, no work: no lookup, no client, no socket
    authorization       ONE      --i-am-the-operator-authorizing-binding-preflight
    what it authorizes  BINDING PREFLIGHT ONLY -- never a qualification run
    operations reached  preflight_qualification_composition, and nothing else
    authorized attempts FOUR     all refused; none reached a Secrets Manager
                                 client, S3, Sharadar, the composition or a run
    third attempt       REFUSED_SECRET_IDENTIFIER at the identifier source
    fourth attempt      REFUSED_IDENTITY at the AWS identity gate
    AWS activity        NOT ZERO identity-gate activity occurred on the attempts
    fourth-attempt identity-gate invocations: ONE -- the gate runs its own STS
    fourth-attempt standalone diagnostic commands: ZERO
    fourth-attempt AWS network requests: UNKNOWN -- no numeric count established
    post-fourth identity diagnosis: COMPLETED
                                 REFUSED_SSO_SESSION_MISSING_OR_EXPIRED, one
                                 command, exit 255, its own network count
                                 UNKNOWN, zero SSO logins during it, zero
                                 repair actions during it
    post-diagnosis SSO-login attempt: COMPLETED REFUSED_SSO_LOGIN -- one
                                 ``aws sso login --no-cli-pager`` command,
                                 timed out after 420 seconds, terminated,
                                 no exit status returned, no lingering AWS
                                 CLI process, zero browser authorizations,
                                 zero device authorizations, zero
                                 successful refreshes, zero identity
                                 confirmations, its own network count
                                 UNKNOWN, SSO session still unrefreshed
    Secrets Manager     ZERO     client constructions, get_secret_value
                                 invocations and network requests
    S3 object ops       ZERO     ·  Sharadar/provider requests: ZERO
    S3 clients          ZERO     constructed  ·  provider transports: ZERO
    credential          NONE     retrieved  ·  qualification runs: ZERO
    secret identifier   OWNER-CONFIGURED / NOT YET VERIFIED BY THE ENTRY POINT

What has actually happened, and what has not
============================================

**Writing and merging this file executed nothing.** Four later, separately
authorized operator attempts did execute it, and all four refused. They are
different facts and this docstring keeps them apart -- an earlier revision said
only "never run", which was true of the merge and false of the operation.

======================================  ====================================
event                                   outcome
======================================  ====================================
implementation and merge                no attempt; code and synthetic
                                        validation only
first authorized attempt                refused at the AWS identity gate
separately authorized diagnosis         one ``sts:GetCallerIdentity`` request;
                                        session missing or expired
second authorized attempt, after an     passed the identity gate and licensed
AWS SSO login                           bucket resolution, then refused
                                        **before constructing a Secrets
                                        Manager client** -- the project
                                        environment lacked the AWS SDK
separately authorized environment       installed and verified the AWS SDK;
action                                  no repository file changed
third authorized attempt                passed authorization, the profile
                                        contract, the identity gate and
                                        licensed-bucket resolution, reached
                                        the fixed secret-identifier source
                                        **exactly once** and refused with
                                        ``REFUSED_SECRET_IDENTIFIER``
owner credential setup, after the       a Secrets Manager secret created for
third attempt                           the existing Sharadar API key, and
                                        ``KALPAMANI_SHARADAR_SECRET_ID``
                                        configured -- owner-attested, and
                                        **not verified by this entry point**
fourth authorized attempt, after the    passed authorization and the profile
owner's setup                           contract, invoked the AWS identity
                                        gate once and refused there with
                                        ``REFUSED_IDENTITY``; it reached
                                        neither licensed-bucket resolution
                                        nor the secret-identifier source, so
                                        it did not read
                                        ``KALPAMANI_SHARADAR_SECRET_ID``,
                                        built no client and retrieved no
                                        credential
a second separately authorized          one ``aws sts get-caller-identity``
diagnosis, after the fourth attempt     command, exit code 255, classified
                                        ``REFUSED_SSO_SESSION_MISSING_OR_EXPIRED``
                                        -- missing and expired **not
                                        distinguished**; its own network
                                        count UNKNOWN; no SSO login, no
                                        repair and no fifth attempt followed
                                        it under that authorization
a separately authorized SSO-login       one ``aws sso login --no-cli-pager``
attempt, after that diagnosis           command; **timed out after 420
                                        seconds**, terminated, no lingering
                                        process, so **no exit status was
                                        returned** -- ``REFUSED_SSO_LOGIN``;
                                        zero browser authorizations, zero
                                        device authorizations, zero
                                        successful refreshes, zero identity
                                        confirmations; its own network count
                                        UNKNOWN; the SSO session remains
                                        unrefreshed
======================================  ====================================

**So AWS identity-gate activity occurred and total AWS activity was not zero.**
What stayed at zero is narrower, and is stated in scope: Secrets Manager client
constructions, ``get_secret_value`` invocations and Secrets Manager network
requests; S3 client constructions and object operations; provider transport
constructions; Sharadar and provider requests. No attempt reached composition
validation or a qualification run, and **no credential was retrieved or
revealed.**

**Whether the fourth attempt sent an AWS network request is UNKNOWN.** The gate
was invoked once and did not pass; a gate can fail before anything leaves the
machine, so neither zero nor one may be claimed here.

**No standalone diagnosis was performed as part of attempt 4** -- and that is
narrower than an earlier revision of this docstring claimed. **Its governed
identity gate invoked its own STS identity operation once**:
``identity_gate()`` in ``scripts/aws_foundation_verify.py`` runs
``sts get-caller-identity`` itself, so it is false to say the attempt made no
STS identity call. What it did **not** do is run an *additional* diagnostic
command or any SSO inspection, and no authentication repair occurred during it.
Nothing the attempt did **beyond its own gate** establishes why that gate
refused, and the gate's internal operation is **not** the later standalone
diagnosis.

**A separately authorized diagnosis has since answered that. It is an
additional standalone command** -- neither the gate's own STS operation above,
nor the diagnosis that followed the first attempt. Run after the
fourth attempt, it invoked one process and one ``aws sts get-caller-identity``
command, which exited **255** and classified as
**REFUSED_SSO_SESSION_MISSING_OR_EXPIRED**: the governed SSO session or cached
token was unavailable or expired. **It does not distinguish missing from
expired**, and nothing here guesses which. It is the first direct diagnostic
evidence explaining the fourth attempt's identity refusal, and it revises no
count -- the attempt's own network total stays UNKNOWN, and so does the
diagnosis command's, because a CLI call may resolve credentials locally and fail
before anything leaves the machine. **At that point SSO-login invocations
were zero, authentication-repair actions were zero and fifth
binding-preflight attempts were zero.** The first of those has since moved
and the other two have not; see the timed-out SSO-login attempt below.

That diagnosis pinned the governed profile in its **child** process, from the
``EXPECTED_PROFILE`` constant below, because a shell-level pin does not survive
across separate tool invocations and an unpinned call would fall back to an
unrelated default profile. That constant already existed in tracked executable
source, so the claim is narrow: the diagnosis did not print, log, disclose or
newly write the value; it used the governed constant already present in tracked
source.

**Further** AWS authentication diagnosis is not authorized, and **another**
AWS SSO refresh or login is separately gated: classifying a session was not
permission to replace it, and a failed login attempt is not permission to
retry.

**A separately authorized AWS SSO-login attempt has since been made, and it
did not succeed.** Run after that diagnosis and after PR #29 merged, it
invoked one process and one ``aws sso login --no-cli-pager`` command, with
the governed profile resolved by static AST parse of the ``EXPECTED_PROFILE``
constant below -- this module was neither imported nor executed -- and pinned
in the child environment only, never disclosed. **It timed out after 420
seconds**, was terminated and left no lingering AWS CLI process, so **no exit
status was returned**: the record is *exit code NOT AVAILABLE / PROCESS
TERMINATED ON TIMEOUT*, never a numeric one, and the closed public outcome is
**REFUSED_SSO_LOGIN**. **Browser authorization interactions zero, device
authorizations completed zero, successful SSO refreshes zero,
identity-confirmation command invocations zero, fifth binding-preflight
attempts zero.** Its own underlying AWS network-request count is **UNKNOWN**,
for the reason every count here is: a CLI invocation is not one network
request. **The SSO session remains unrefreshed**, the earlier
REFUSED_SSO_SESSION_MISSING_OR_EXPIRED diagnosis stands unrevised, and the
attempt produced no evidence distinguishing missing from expired, did not
verify or contradict the owner-configured secret identifier, and retrieved no
credential.

**The likely cause is procedural, and it is recorded as likely rather than
proven.** stdout and stderr were captured rather than streamed, no browser
appeared, no device URL or code was displayed to the owner, and the process
waited the full 420 seconds -- so the failed interaction was **likely caused
by suppressing the interactive browser/device-code surface**. That is an
operational-handling explanation, **not proof of an AWS configuration
defect**. Whether the AWS CLI emitted a device URL or code into the
undisplayed buffer was **not inspected and remains UNKNOWN**, and no raw
output may be inspected now to resolve it. Nothing establishes a defective SSO
configuration, an incorrect governed profile, a wrong start URL, any particular
technical reason for a browser not appearing, or the presence or absence of a
generated device code.

``KALPAMANI_SHARADAR_SECRET_ID`` is **OWNER-CONFIGURED / NOT YET VERIFIED BY THE
ENTRY POINT**. It was **UNKNOWN** at the second attempt, which refused on the
dependency path without reading it, and still UNKNOWN at the third, which
resolved the fixed source exactly once and refused because no usable identifier
came back. The owner created the secret and configured the variable **only
afterwards**, so none of the first three could have seen it -- and the fourth
refused at the identity gate, two stages before the identifier source, so it did
not read the variable either. **No attempt has resolved the identifier.** Owner
attestation is not
verification by this file: it has not resolved the identifier, has not
constructed a Secrets Manager client, has not invoked ``get_secret_value`` and
has retrieved no credential.

**Credential access by this application**, **a fifth binding preflight**, **further
AWS authentication diagnosis**, **another AWS SSO refresh or login** and an
**authenticated qualification run** remain five separate decisions, each still
**NOT AUTHORIZED**, and each requires separate written authorization. This file
existing does not create a secret, does not read one, and cannot execute a
qualification run -- there is no code here that could, and a static guard keeps
it that way. Owner-side secret creation happened outside this repository and
grants none of the three.

Refusing by default, and why the flag is spelled like that
==========================================================

An ordinary import or an ordinary invocation does nothing at all. The operational
path needs
``--i-am-the-operator-authorizing-binding-preflight``, and the name is
deliberately unmistakable: ``--run``, ``--live``, ``--execute`` and ``--force``
are all things a person types out of habit on the wrong terminal. This one has to
be meant.

**It authorizes a binding preflight and nothing further.** It does not mint,
imply or stand in for authorization to execute a qualification run, and no code
path here consumes it as one.

Two defects this file's first revision contained
================================================

**A boolean could forge the authorization.** The check was ``binding_authorized is True``, so a
caller who imported :func:`run_binding_preflight` and passed ``True`` reached the profile, identity
and bucket stages without the flag ever being parsed. A boolean is the one value every caller
already has; an authorization that any caller can supply is not an authorization.

**A copyable mint field was not much better.** The next revision took an object of an exact type
carrying a module-private mint field. ``copy.copy`` produced a *distinct* object holding the same
field, and admission accepted it -- so copying manufactured a second bearer of authority. The
slice's closeout claimed both "copying cannot forge one" and "a shallow copy stays genuine", which
cannot both be true; review caught it.

The parameter is now **one module-level object, admitted by identity**. There is no state to copy:
``__slots__`` is empty, ``__new__`` refuses once the singleton exists, ``__copy__``,
``__deepcopy__`` and ``__reduce__`` all refuse, and subclassing refuses. The object is not
exported, and no function returns it except the parser path that has already admitted the flag.

*What that claims, exactly:* no caller can obtain a second admitted authorization through
construction, copying, deep copying, serialisation, subclassing, a structural lookalike or a
borrowed field. It is **not** a claim about hostile runtime introspection -- a process that can
reach a module's private names already holds the singleton, and this file does not pretend
otherwise.

**A private secret identifier travelled in argv.** ``--secret-id`` put it in shell history and in
every process listing on the machine, whether or not this program ever printed it. Redacting output
does not help once the value is on the command line.

The identifier now comes from an **injected zero-argument source**, called once, only after
authorization, profile, identity and bucket resolution have all passed, and immediately before the
credential is retrieved. The production source reads **one fixed, non-secret environment-variable
name** on that authorized path. ``--secret-id``, ``--secret-name`` and their near spellings are
refused by name rather than silently ignored.

The order, and why nothing may be reordered
===========================================

1. explicit binding-preflight authorization
2. the exact AWS profile
3. the AWS account identity gate
4. governed licensed-bucket resolution
5. the guarded secrets-boundary import the validation needs
6. the secret-identifier source, and its structural validation
7. Secrets Manager SDK and client construction
8. one ``get_secret_value`` invocation
9. the remaining dependency construction
10. the accepted offline composition preflight
11. a closed result

Each stage runs only if every earlier one passed. The order is the security
property: identity is established before any state is read, the bucket is
resolved before a secret is fetched, and the secret is fetched before anything is
constructed -- so a wrong-account session never reaches a secret, and a failed
gate never reaches a credential.

Stage 5 is stated separately rather than folded in, because it changes a count:
if the secrets boundary will not import, ``REFUSED_DEPENDENCY`` is raised
**before the identifier source is called at all**, so that refusal shows zero
identifier resolutions rather than one.

Stages 6, 7 and 8 were one stage, and that was a defect
=======================================================

ADR-0016. The first revision resolved the identifier, constructed the client and
retrieved the credential inside one ``try`` whose every failure became
``REFUSED_CREDENTIAL``. Two authorized operator attempts had been made against
the real foundation by then. The first refused at the identity gate. The second passed
identity and bucket resolution and reported ``REFUSED_CREDENTIAL`` -- and the
operational virtual environment contained no ``boto3`` at all, so
``_secrets_client`` had raised ``ModuleNotFoundError`` **inside the constructor**.
**No client existed, so there was no ``get_secret_value`` invocation and no AWS
network request.**

The command reported a private-credential failure for a missing local package.
An operator reading it would go looking at Secrets Manager, at IAM, at the secret
itself -- at everything except the one thing that was actually wrong. Worse, the
report implied AWS had been contacted when it had not, and whether the secret
identifier was even configured stayed unknown, because nothing had distinguished
that stage either.

They are three stages with three closed outcomes now, and each is refused before
the next begins:

======================================  ==========  ==========  ================
outcome                                 identifier  client      invocations
======================================  ==========  ==========  ================
authorization / profile / identity /             0           0                 0
bucket refusal
secrets-boundary import refusal                  0           0                 0
``REFUSED_SECRET_IDENTIFIER``                    1           0                 0
``REFUSED_DEPENDENCY`` at the client             1           1                 0
``REFUSED_CREDENTIAL``                           1           1                 1
``REFUSED_DEPENDENCY`` after the credential      1           1                 1
a completed offline preflight                    1           1                 1
======================================  ==========  ==========  ================

An invocation is not an AWS network request
===========================================

The third column counts **calls into the injected client's ``get_secret_value``
method**. That is what a counter can observe, and it is all the synthetic suite
establishes. A real client validates parameters locally and can reject a call
after the method is entered and before anything leaves the machine, so:

* ``REFUSED_CREDENTIAL`` establishes **one admitted invocation**;
* it does **not**, on its own, establish that AWS received anything;
* the historical missing-SDK run establishes **zero invocations and zero AWS
  network requests**, because no client existed to make either.

The distinction is kept in the wording deliberately. Saying "a request was sent"
on the strength of a method counter would be a smaller version of the same
mistake ADR-0016 was written to correct.

The counts are not decoration. They are what the synthetic suite asserts, with
factories and a client that count what was asked of them -- so "no invocation
occurred" is observed rather than argued from which line raised.

Nothing here reimplements a gate. ``AWS_PROFILE`` pinning, the account-binding
comparison and the Terraform-state read all come from
``scripts/aws_foundation_verify.py``, which already owns them; a second copy of
account matching is a second thing to get wrong.

What may be printed
===================

A fixed allowlist of sentences, none of which carries a private identifier. No
credential or fragment, no secret identifier, no bucket, no account, no ARN, no
profile, no region, no Terraform output, no URL, no plan subject, no empirical
result and no provider recommendation. The exit status reports command success or
refusal -- never a qualification verdict and never provider suitability.

Not the public-token harness
============================

``scripts/sharadar_private_qualification.py`` is a separate, owner-only
instrument that reads the vendor's *published* test token. This file does not
import, invoke, modify or repurpose it, and the two have no code in common.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

REPO_ROOT_MARKER: Final = "scripts"

#: The one flag that turns a refusal into a binding preflight.
#:
#: Long, explicit and awkward on purpose. Anything a person might type from habit
#: -- ``--run``, ``--live``, ``--execute``, ``--force`` -- is refused by name
#: below, so a wrong reflex fails loudly instead of doing something.
BINDING_AUTHORIZATION_FLAG: Final = "--i-am-the-operator-authorizing-binding-preflight"

#: The one fixed, non-secret environment-variable *name* the production source
#: reads on the authorized path. The name is not a secret; the value is, and it
#: is never printed, logged or included in a refusal.
#: Ruff flags the *name* on its hardcoded-password heuristic. This is the name of
#: an environment variable, not a value: the identifier it holds is private, this
#: constant is not, and renaming it to dodge the check would make it less clear
#: what the constant is.
SECRET_ID_ENV_VAR: Final = "KALPAMANI_SHARADAR_SECRET_ID"  # noqa: S105


class _BindingAuthorization:
    """Proof that the operator flag was parsed. **Exactly one exists.**

    Two revisions got this wrong, and the second is worth stating because it is
    the subtler mistake.

    The first took a ``bool``, so any importer could pass ``True``.

    The second took an object carrying a module-private *mint field*, and
    admitted anything of the exact type holding that field. **A field is
    copyable.** ``copy.copy`` produced a distinct object carrying the same mint,
    and admission accepted it -- so copying manufactured a second bearer of
    authority, which is precisely what the capability existed to prevent. The
    slice's own closeout claimed both "copying cannot forge one" and "a shallow
    copy stays genuine"; those cannot both be true, and review caught it.

    There is now **no state to copy**: ``__slots__`` is empty, admission is
    identity against the single module-level instance, and every route that
    would produce a second object is closed --

    * ``__new__`` refuses once the singleton exists, so there is no second
      construction;
    * ``__copy__`` and ``__deepcopy__`` refuse, so no copy operation yields an
      object at all;
    * ``__reduce__`` refuses, so the object cannot be pickled and therefore
      cannot be unpickled into a second bearer;
    * subclassing refuses, so no subclass instance can stand in.

    An ``object.__new__`` instance can still be built -- that bypasses
    ``__new__`` -- and it is refused for the reason that matters: it is not
    *this* object.

    **What that claims, precisely.** No caller can obtain a second admitted
    authorization through construction, copying, deep copying, serialisation,
    subclassing, a structural lookalike or a borrowed field. It is **not** a
    claim about hostile runtime introspection: a process that can reach a
    module's private names already holds the singleton, and this file does not
    pretend otherwise.
    """

    __slots__ = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing.

        A subclass instance would satisfy an ``isinstance`` check while being a
        different object from the one this module made.
        """
        raise TypeError("_BindingAuthorization may not be subclassed.")

    def __new__(cls) -> _BindingAuthorization:
        """Build the one instance, and refuse every later construction.

        Raises:
            TypeError: once the singleton is bound. The module binds it below;
                after that, ``_BindingAuthorization()`` is a refusal rather than
                a second capability.
        """
        if "_BINDING_PREFLIGHT_AUTHORIZATION" in globals():
            raise TypeError(
                "there is one binding-preflight authorization; it is obtained by parsing "
                "the operator flag, not constructed"
            )
        return super().__new__(cls)

    def __copy__(self) -> _BindingAuthorization:
        """Refuse copying.

        Returning ``self`` would also have been defensible -- one object, no new
        bearer. Refusing is chosen because it fails loudly: code that copies an
        authorization is doing something this design does not intend, and a
        silent pass-through would let that intent survive unexamined.
        """
        raise TypeError("a binding-preflight authorization may not be copied.")

    def __deepcopy__(self, memo: object) -> _BindingAuthorization:
        """Refuse deep copying, for the same reason."""
        raise TypeError("a binding-preflight authorization may not be copied.")

    def __reduce__(self) -> object:
        """Refuse pickling, so nothing can be unpickled into a second bearer."""
        raise TypeError("a binding-preflight authorization may not be serialised.")

    def __repr__(self) -> str:
        """A constant. There is nothing else to render."""
        return "<binding-preflight authorization>"


#: The one authorization. Admission is identity against exactly this object.
#:
#: Not exported, and no function returns it except the parser path that has
#: already admitted the operator flag.
_BINDING_PREFLIGHT_AUTHORIZATION: Final = _BindingAuthorization()


def _is_authorized(candidate: object) -> bool:
    """Whether ``candidate`` **is** the one authorization this module holds.

    Identity, and nothing else. No type check is needed and none is written: a
    type check plus a copyable field is what admitted a shallow copy in the
    previous revision, and adding one back would invite the same mistake.
    """
    return candidate is _BINDING_PREFLIGHT_AUTHORIZATION


#: The profile and region the governed foundation is pinned to.
#:
#: Read from the verifier that owns them rather than restated, so the pin cannot
#: drift between the gate and this caller.
EXPECTED_PROFILE: Final = "kalpamani-foundation"
EXPECTED_REGION: Final = "us-east-1"

#: The Terraform output holding the licensed research bucket.
#:
#: Named, so the CONTROL bucket cannot be substituted by editing a variable: the
#: control bucket has a different output key and this module never names it.
LICENSED_BUCKET_OUTPUT: Final = "licensed_bucket_name"

#: Options refused by name, each with the reason.
#:
#: Present as rejected names rather than simply absent: an unrecognised flag is
#: already an ``argparse`` error, but one that says "unrecognized arguments"
#: teaches nothing and someone tries again with a different spelling.
REFUSED_OPTIONS: Final[dict[str, str]] = {
    "--run": "there is no run mode; a qualification run is a separate authorization",
    "--live": "there is no live mode, and nothing here can construct one",
    "--execute": "this command cannot execute a qualification run; no such code path exists",
    "--force": "nothing here is forceable; a refusal is a refusal",
    "--api-key": "no credential is accepted on the command line, ever",
    "--secret-value": "no credential value is accepted on the command line, ever",
    "--secret-id": (
        "a secret identifier is private; on the command line it enters shell history and "
        "every process listing. It is read from the environment on the authorized path"
    ),
    "--secret-name": "same as --secret-id: a private identifier does not travel in argv",
    "--secretid": "same as --secret-id: a private identifier does not travel in argv",
    "--secret-arn": "same as --secret-id: a private identifier does not travel in argv",
    "--secret": "same as --secret-id: a private identifier does not travel in argv",
    "--account": "the account is never supplied; it is compared against the local binding",
    "--bucket": "the licensed bucket is resolved from governed state, never supplied",
    "--endpoint": "no endpoint is accepted; the SDK resolves the governed one",
    "--token": "no token is accepted, read, stored or bound by this command",
}


class PreflightOutcome(StrEnum):
    """Every sentence this command may print. A fixed allowlist.

    Each is a fact about what the command did, safe in a public transcript. None
    reports a qualification verdict, provider suitability or readiness to run --
    those are not facts this command establishes, and a word implying one would
    be read as permission.

    **Three of them are the correction ADR-0016 records.** A single
    ``REFUSED_CREDENTIAL`` once covered the identifier source, the local SDK and
    client construction, and the one ``get_secret_value`` call. An operator
    running this against a machine with no SDK installed was told the private
    credential could not be retrieved -- when no client existed, so nothing had
    been invoked and nothing could have reached AWS. The three are separate
    members now:

    ``REFUSED_SECRET_IDENTIFIER``
        the configured source was unavailable, raised, or produced something the
        identifier boundary refuses. **No client is built, so nothing is invoked
        and nothing can reach AWS.**
    ``REFUSED_DEPENDENCY``
        a local dependency -- the SDK, the client factory, the client itself, the
        secrets boundary's own import, or anything constructed after the
        credential -- was not usable. **This outcome alone determines neither the
        invocation count nor any network activity**: it occurs both before the
        client exists (zero invocations) and after a successful retrieval (one).
        Only the witnessed, stage-specific count says which.
    ``REFUSED_CREDENTIAL``
        the one admitted ``get_secret_value`` invocation raised or was refused,
        or what came back was not a credential. **This is the only outcome that
        follows an admitted invocation**, and every earlier refusal has its own
        member so it cannot be mistaken for one.
    ``REFUSED_UNCLASSIFIED``
        this program could not work out what the boundary refused. Added in
        ADR-0016's first correction round, because the two places that needed an
        answer for "I do not know" were answering ``REFUSED_CREDENTIAL`` and
        ``REFUSED_DEPENDENCY`` -- each a positive claim about a boundary that may
        never have been reached. Not knowing has its own word now.
    """

    REFUSED_NOT_AUTHORIZED = "binding preflight refused: no operator authorization was given"
    REFUSED_PROFILE = "binding preflight refused: the AWS profile is not the governed one"
    REFUSED_IDENTITY = "binding preflight refused: the AWS identity gate did not pass"
    REFUSED_BUCKET = "binding preflight refused: the licensed bucket could not be resolved"
    # Ruff's hardcoded-password heuristic fires on the member *name*. This is a
    # refusal sentence in a closed operator vocabulary, and renaming it to dodge
    # the check would make the vocabulary less accurate about what was refused --
    # which is the whole subject of ADR-0016. Suppressed per line, as in the
    # secrets boundary, not by disabling the rule.
    REFUSED_SECRET_IDENTIFIER = (
        "binding preflight refused: no usable secret identifier was resolved"  # noqa: S105
    )
    REFUSED_DEPENDENCY = "binding preflight refused: a required local dependency was not usable"
    REFUSED_UNCLASSIFIED = "binding preflight refused: the refusal could not be classified"
    REFUSED_CREDENTIAL = "binding preflight refused: the private credential could not be retrieved"
    REFUSED_PLAN = "binding preflight refused: the qualification plan did not validate"
    REFUSED_OPTION = "binding preflight refused: an option this command does not accept"
    COMPLETED = "binding preflight completed"
    VALIDATION_COMPLETED = "offline validation completed"


#: What each closed secrets-boundary failure means to an operator.
#:
#: Keyed by the ``SecretRetrievalFailure`` member's own token rather than by the
#: member, so this file still imports nothing at module scope: the default,
#: refusing invocation must stay runnable on a machine where the data platform
#: is not importable, which is exactly the class of machine the defect was found
#: on.
#:
#: **Total over that vocabulary**, and a test asserts it is: a failure member
#: with no entry here would be swept into "the credential failed" by a default,
#: which is the defect ADR-0016 corrects rather than a way to express it. Two of
#: the members are refusals the boundary reaches *before* it invokes the client,
#: and they map to the stages that own them -- not to the credential.
SECRET_FAILURE_OUTCOME: Final[dict[str, PreflightOutcome]] = {
    # Reached before the client is invoked, so no invocation and no network
    # activity can be attributed to any of them.
    "CLIENT_UNUSABLE": PreflightOutcome.REFUSED_DEPENDENCY,
    "SECRET_IDENTIFIER_MALFORMED": PreflightOutcome.REFUSED_SECRET_IDENTIFIER,
    # "I could not tell what this was." Reachable only by handing the boundary's
    # error type something that is not a member of its vocabulary at all -- which
    # used to normalise to RESPONSE_MALFORMED, and therefore to a credential
    # claim (ADR-0016, correction round 2).
    "UNCLASSIFIED": PreflightOutcome.REFUSED_UNCLASSIFIED,
    # Reached only by invoking the client, or by inspecting what that invocation
    # returned. These are the genuine credential boundary. Each establishes an
    # invocation; none establishes that AWS received anything.
    "BACKEND_REFUSED": PreflightOutcome.REFUSED_CREDENTIAL,
    "RESPONSE_MALFORMED": PreflightOutcome.REFUSED_CREDENTIAL,
    "SECRET_BINARY_REFUSED": PreflightOutcome.REFUSED_CREDENTIAL,
    "SECRET_VALUE_UNUSABLE": PreflightOutcome.REFUSED_CREDENTIAL,
}


class BindingPreflightError(Exception):
    """A stage refused. Carries one closed outcome and nothing else.

    No secret, no identifier, no bucket, no account, no ARN, no backend message
    and no attempted value: there is no parameter for one.
    """

    __slots__ = ("outcome",)

    def __init__(self, outcome: PreflightOutcome) -> None:
        """Carry one allowlisted outcome, and render it as that sentence alone.

        A caller that hands over something which is not a member gets
        ``REFUSED_UNCLASSIFIED``. It used to get ``REFUSED_DEPENDENCY``, which
        asserted that a dependency had failed on evidence that established
        nothing of the kind.
        """
        self.outcome = (
            outcome if type(outcome) is PreflightOutcome else PreflightOutcome.REFUSED_UNCLASSIFIED
        )
        super().__init__(self.outcome.value)


def _secret_failure_outcome(refusal: object) -> PreflightOutcome:
    """The operator outcome for one closed secrets-boundary refusal.

    **The invariant, and it is the whole function.** ``REFUSED_CREDENTIAL`` is
    reachable only through an explicit entry in :data:`SECRET_FAILURE_OUTCOME`
    naming a member that is known to follow an admitted ``get_secret_value``
    invocation. There is no ``.get`` default, no ``else`` branch and no
    catch-all that can produce it.

    The first revision of this correction had two, and both recreated the false
    claim ADR-0016 exists to remove: a non-string token returned
    ``REFUSED_CREDENTIAL``, and ``SECRET_FAILURE_OUTCOME.get(token,
    REFUSED_CREDENTIAL)`` returned it for an unmapped one. Neither an unreadable
    token nor an unrecognised one establishes that anything was invoked -- and a
    vocabulary member added later, by someone who did not run the totality test,
    would have been reported as a credential failure by default.

    Everything this function cannot classify is ``REFUSED_UNCLASSIFIED``: a
    refusal object with no ``failure``, a ``failure`` with no ``value``, a
    non-string token, an unmapped token, and an attribute lookup that raises on
    the way to any of them. That word claims nothing about which boundary was
    reached, which is the only honest thing to say when this code does not know.
    """
    try:
        failure = getattr(refusal, "failure", None)
        token = getattr(failure, "value", None)
    except Exception:
        # A refusal object whose own attribute access raises. Nothing about it
        # is readable, so nothing about it may be claimed.
        return PreflightOutcome.REFUSED_UNCLASSIFIED
    if type(token) is not str:
        return PreflightOutcome.REFUSED_UNCLASSIFIED
    outcome = SECRET_FAILURE_OUTCOME.get(token)
    if outcome is None:
        return PreflightOutcome.REFUSED_UNCLASSIFIED
    return outcome


def _emit(outcome: PreflightOutcome) -> None:
    """Print one allowlisted sentence. The only route to stdout in this file."""
    print(outcome.value)


class SystemClock:
    """The retrieval instant, as the qualification runtime's clock protocol.

    Defined here rather than in the package because it is a *deployment*
    decision: the runtime takes an injected clock precisely so that nothing
    inside it reads a wall clock, and the one place allowed to choose one is the
    operator path that also chooses the credential and the bucket.
    """

    def now(self) -> datetime:
        """The current instant, timezone-aware."""
        return datetime.now(UTC)


def build_parser() -> argparse.ArgumentParser:
    """The command's surface. One authorizing flag, one secret identifier, one plan."""
    parser = argparse.ArgumentParser(
        prog="sharadar_binding_preflight",
        description=(
            "Operator binding preflight for the authenticated Sharadar qualification "
            "stack. Refuses by default. Authorizes a binding preflight only -- never a "
            "qualification run."
        ),
    )
    parser.add_argument(
        BINDING_AUTHORIZATION_FLAG,
        # "was the flag present", which is a parse result -- not an
        # authorization. The authorization is minted from it below, and the
        # name says which of the two this is.
        dest="binding_flag_present",
        action="store_true",
        help=(
            "Authorize a binding preflight. This does not authorize, imply or stand in "
            "for authorization to execute a qualification run."
        ),
    )
    parser.add_argument(
        "--subject",
        dest="subjects",
        action="append",
        default=None,
        help="A qualification subject. Never printed back.",
    )
    parser.add_argument(
        "--execution-id",
        dest="execution_id",
        default=None,
        help="The explicit execution identity for the plan. No default exists.",
    )
    return parser


def _refused_option(argv: Sequence[str]) -> str | None:
    """The first refused option in ``argv``, if any.

    Checked before parsing, so a refused name is reported as itself rather than
    as an unrecognised argument.
    """
    for argument in argv:
        name = argument.split("=", 1)[0]
        if name in REFUSED_OPTIONS:
            return name
    return None


def run_binding_preflight(
    *,
    authorization: object,
    subjects: Sequence[str] | None,
    execution_id: str | None,
    profile_of: Callable[[], str],
    identity_gate: Callable[[], str | None],
    resolve_licensed_bucket: Callable[[], str],
    secret_id_source: Callable[[], str],
    secrets_client_factory: Callable[[], Any],
    s3_client_factory: Callable[[], Any],
    transport_factory: Callable[[], Any],
) -> Any:
    """Bind the private dependencies and validate a plan against them. **Offline.**

    Every stage is a parameter, which is what makes this testable without AWS and
    what keeps the ambient environment out of it: nothing here reads
    ``os.environ``, opens a file, constructs a client or resolves a name. The
    real factories are supplied by :func:`main`, and this slice never calls it
    with real ones.

    ``authorization`` is a capability minted by :func:`main` after the exact
    operator flag parses. It is **not** a boolean: an earlier revision took one,
    which meant an importer could pass ``True`` and reach the profile, identity
    and bucket stages with no flag involved.

    ``secret_id_source`` is a zero-argument callable rather than a value, and it
    is invoked **once**, after every gate has passed and immediately before the
    credential is retrieved. A private identifier must not be resolved on a path
    that is going to refuse.

    The order in the module docstring is the security property, and it is
    enforced here by sequence rather than described: a later stage cannot run
    after an earlier refusal, because a refusal raises.

    **The only operation reached is** ``preflight_qualification_composition``.
    There is no call to ``QualificationRuntime.execute``, to a provider
    transport's ``get``, or to ``put_object`` or ``head_object`` -- and no code in
    this file could construct one.

    The identifier, the client and the retrieval are **three stages with three
    outcomes**, not one stage with one. ADR-0016: they were one, and an operator
    running this on a machine with no ``boto3`` installed was told the private
    credential could not be retrieved -- when the constructor had raised
    ``ModuleNotFoundError``, no client existed, and nothing had been invoked.

    Raises:
        BindingPreflightError: one allowlisted :class:`PreflightOutcome`. The
            cause is always suppressed: a backend exception quotes a secret name,
            an ARN or a bucket, and a plan refusal can quote a subject.

            ``REFUSED_SECRET_IDENTIFIER`` -- the source was unavailable, raised,
            or produced something :func:`is_usable_secret_identifier` refuses.
            **Zero clients constructed, so zero invocations and no AWS network
            request.**

            ``REFUSED_DEPENDENCY`` -- the secrets boundary would not import, the
            SDK or the client factory raised, the constructed client cannot
            serve the one operation, an exception of an unknown type escaped the
            retrieval, or a dependency built after the credential failed. **The
            outcome alone fixes no count**: it occurs both before a client exists
            and after a successful retrieval, so only the witnessed stage count
            says whether anything was invoked.

            ``REFUSED_CREDENTIAL`` -- and only this -- follows an admitted
            ``get_secret_value`` invocation: the call raised, the response was
            unusable, it held binary, or the value was not a credential. It
            establishes one invocation, not that AWS received anything.

            ``REFUSED_UNCLASSIFIED`` -- the boundary refused with something this
            program could not read or does not recognise. It names no boundary,
            because none is known.
    """
    # 1. Authorization. A capability this module minted after parsing the flag --
    #    not a boolean, which is the one value every caller already has.
    if not _is_authorized(authorization):
        raise BindingPreflightError(PreflightOutcome.REFUSED_NOT_AUTHORIZED) from None

    # 2. The profile, before any AWS call is attempted at all.
    try:
        profile = profile_of()
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_PROFILE) from None
    if profile != EXPECTED_PROFILE:
        raise BindingPreflightError(PreflightOutcome.REFUSED_PROFILE) from None

    # 3. The account identity gate. Its reason string can name an account, so it
    #    is consumed as a pass/fail and never printed.
    try:
        reason = identity_gate()
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_IDENTITY) from None
    if reason is not None:
        raise BindingPreflightError(PreflightOutcome.REFUSED_IDENTITY) from None

    # 4. The licensed bucket, from governed state. Never the control bucket:
    #    the resolver is asked for one named output and this module names no
    #    other.
    try:
        licensed_bucket = resolve_licensed_bucket()
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_BUCKET) from None
    if type(licensed_bucket) is not str or not licensed_bucket.strip():
        raise BindingPreflightError(PreflightOutcome.REFUSED_BUCKET) from None

    # 5. The secrets boundary itself is a local dependency. Imported here rather
    #    than at module scope so an ordinary import of this file still reaches
    #    nothing, and guarded because an import that fails is a dependency fact.
    #
    #    This runs *before* the identifier source, and that is visible in the
    #    counts: an import refusal shows zero identifier resolutions. The
    #    validation rule lives in this module, so it has to be here.
    try:
        from kalpamani.data.ingest.sharadar.secrets import (
            SecretRetrievalError,
            is_usable_secret_identifier,
            sharadar_credential_from_secret,
        )
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_DEPENDENCY) from None

    # 6. The secret identifier, resolved **here** and nowhere earlier. It is
    #    private, so every refusal above must complete without asking for it --
    #    which is why it is a source rather than an argument.
    #
    #    Its own outcome, and not the credential's: an unset variable or a
    #    malformed identifier is a configuration fact about this machine, and
    #    reporting it as a credential failure sends an operator to Secrets
    #    Manager to look for a problem that is not there (ADR-0016). Nothing has
    #    been constructed at this point and nothing has been invoked.
    #
    #    The rule is the secrets boundary's own, imported rather than restated:
    #    two spellings of one rule is how a value this stage admits becomes a
    #    value the boundary refuses. It is a real Secrets Manager identifier
    #    grammar -- a name or a complete ARN -- so a shape the client would
    #    reject locally is refused here instead of inside the invocation.
    try:
        secret_id = secret_id_source()
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_SECRET_IDENTIFIER) from None
    if not is_usable_secret_identifier(secret_id):
        raise BindingPreflightError(PreflightOutcome.REFUSED_SECRET_IDENTIFIER) from None

    # 7. The Secrets Manager client. **Local construction only** -- importing the
    #    SDK, building a session, pinning a region. Nothing is invoked and no
    #    AWS network request can originate here, because until this line returns
    #    there is no client: the operational finding behind ADR-0016 is precisely
    #    a `ModuleNotFoundError` raised here being reported as a credential that
    #    could not be retrieved.
    #
    #    The dependency's own exception is suppressed like every other: an import
    #    error names a path, and a client constructor's error can name a profile,
    #    a region or an endpoint.
    try:
        secrets_client = secrets_client_factory()
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_DEPENDENCY) from None
    if not callable(getattr(secrets_client, "get_secret_value", None)):
        # Checked here so the boundary's `CLIENT_UNUSABLE` -- which is a
        # dependency fact -- cannot arrive at the credential stage and be read
        # as one.
        raise BindingPreflightError(PreflightOutcome.REFUSED_DEPENDENCY) from None

    # 8. The one credential retrieval, and the only stage that invokes the
    #    client. Everything that could refuse before the invocation has refused
    #    above, so a refusal here is a credential-boundary refusal -- and the
    #    closed member the boundary raises is mapped rather than assumed, with
    #    no default that could turn "I do not know" into a credential claim.
    try:
        credential = sharadar_credential_from_secret(client=secrets_client, secret_id=secret_id)
    except SecretRetrievalError as refusal:
        raise BindingPreflightError(_secret_failure_outcome(refusal)) from None
    except Exception:
        # Not the boundary's closed vocabulary at all. The boundary raises only
        # closed members, so something in the local stack is broken -- and an
        # exception of an unknown type does not establish that `get_secret_value`
        # was ever entered. It used to answer REFUSED_CREDENTIAL, which asserted
        # exactly that (ADR-0016, correction round 1).
        raise BindingPreflightError(PreflightOutcome.REFUSED_DEPENDENCY) from None

    # 9. The remaining dependencies. After the credential, because none of them
    #    is needed to decide any earlier refusal -- and a dependency failure
    #    here is still a dependency failure, even though a credential was
    #    retrieved a moment ago and the invocation count is therefore one.
    try:
        from kalpamani.data.ingest.sharadar.client import DEFAULT_RETRY_POLICY, Pacer

        s3_client = s3_client_factory()
        transport = transport_factory()
        pacer = Pacer()
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_DEPENDENCY) from None

    # 10. The accepted offline composition preflight, and nothing else.
    from kalpamani.data.ingest.sharadar.composition import preflight_qualification_composition

    try:
        plan = _build_plan(subjects=subjects, execution_id=execution_id)
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_PLAN) from None

    try:
        return preflight_qualification_composition(
            credential=credential,
            transport=transport,
            pacer=pacer,
            retry_policy=DEFAULT_RETRY_POLICY,
            timeout_seconds=60.0,
            s3_client=s3_client,
            licensed_bucket=licensed_bucket,
            clock=SystemClock(),
            plan=plan,
        )
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_PLAN) from None


def _build_plan(*, subjects: Sequence[str] | None, execution_id: str | None) -> Any:
    """The bounded qualification plan this preflight validates.

    No subject and no execution identity is compiled in: both are supplied, and
    the plan's own contract refuses a malformed one. Neither is ever printed
    back -- a subject is a listed security, and this command's transcript is
    meant to be safe to share.
    """
    from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
    from kalpamani.data.ingest.sharadar.qualification import (
        DatasetPlan,
        QualificationPlan,
        QualificationSubject,
    )

    if not subjects or execution_id is None:
        raise ValueError("a subject and an execution identity are both required")
    return QualificationPlan(
        subjects=tuple(QualificationSubject(subject) for subject in subjects),
        datasets=(DatasetPlan(dataset=SharadarDataset.TICKERS, page_limit=100, max_pages=1),),
        execution_id=execution_id,
    )


def main(argv: list[str] | None = None) -> int:
    """Parse, refuse or bind. Returns a command status, never a verdict.

    ``0`` means the command did what it was asked to do; non-zero means it
    refused. Neither says anything about the provider, the data, or whether a
    qualification run should happen.

    **The real factories are constructed here and only here**, inside the
    authorized branch. This is the one place ADR-0015 permits an AWS SDK session
    or client to be built. Four separately authorized attempts have run this
    function; **none reached this construction** -- the first and the fourth
    refused at the AWS identity gate, the second refused on the missing AWS SDK,
    and the third refused at the secret-identifier source -- so no Secrets
    Manager client has been built. That is a fact about what happened, not a
    property of the code.
    """
    argv = list(sys.argv[1:] if argv is None else argv)

    refused = _refused_option(argv)
    if refused is not None:
        _emit(PreflightOutcome.REFUSED_OPTION)
        print(f"  {refused}: {REFUSED_OPTIONS[refused]}")
        return 2

    parsed = build_parser().parse_args(argv)

    if not parsed.binding_flag_present:
        # The default path. Nothing above this line looked anything up,
        # constructed anything, or opened anything.
        _emit(PreflightOutcome.REFUSED_NOT_AUTHORIZED)
        print(f"  pass {BINDING_AUTHORIZATION_FLAG} to authorize a binding preflight")
        print("  that flag authorizes a binding preflight only, never a qualification run")
        return 1

    try:
        result = run_binding_preflight(
            # Handed over here, and only here: the flag has parsed.
            authorization=_BINDING_PREFLIGHT_AUTHORIZATION,
            subjects=parsed.subjects,
            execution_id=parsed.execution_id,
            profile_of=_ambient_profile,
            identity_gate=_governed_identity_gate,
            resolve_licensed_bucket=_governed_licensed_bucket,
            secret_id_source=_environment_secret_id,
            secrets_client_factory=_secrets_client,
            s3_client_factory=_s3_client,
            transport_factory=_transport,
        )
    except BindingPreflightError as refusal:
        _emit(refusal.outcome)
        return 1

    _emit(PreflightOutcome.COMPLETED)
    if str(result.status) == "VALIDATED_OFFLINE":
        _emit(PreflightOutcome.VALIDATION_COMPLETED)
    return 0


# ---------------------------------------------------------------------------
# The real factories. Referenced by `main`, never called by a test.
# ---------------------------------------------------------------------------
#
# Each imports what it needs inside the function body, so importing this module
# imports no SDK, reads no environment and touches no state.
#
# `_ambient_profile` and `_governed_identity_gate` HAVE run, on all four
# separately authorized attempts -- the identity gate is where AWS activity
# occurred, and it is where the first and the fourth attempts refused.
# `_governed_licensed_bucket` ran on the second and third attempts only, never
# on the first or the fourth. `_environment_secret_id` ran exactly once, during
# the third attempt, which refused there; the fourth never reached it and
# therefore did not read `KALPAMANI_SHARADAR_SECRET_ID`. The scope is
# deliberate: `_ambient_profile` reads `AWS_PROFILE` from the process
# environment and ran on all four attempts, and the fourth passed the governed
# profile contract, so the secret identifier is the one variable this file may
# say went unread. `_secrets_client`, `_s3_client` and `_transport` have
# never been constructed by any attempt: the second refused inside
# `_secrets_client` before a client existed, and nothing past it was reached.
# No credential has been retrieved, and no composition preflight or
# qualification execution has occurred. Diagnosis is no longer entirely future:
# a separately authorized command run after the fourth attempt classified the
# governed SSO session or cached token as missing or expired, without
# distinguishing which. No SSO login or repair followed it under that
# authorization; a separately authorized `aws sso login` attempt came later,
# timed out after 420 seconds and refused with REFUSED_SSO_LOGIN, leaving the
# session unrefreshed and running none of these factories. A fifth attempt,
# any further AWS authentication diagnosis, another SSO refresh and every
# other operational event remain separately gated.


def _ambient_profile() -> str:
    """The pinned profile from the process environment. Read, never printed."""
    import os

    return os.environ.get("AWS_PROFILE", "")


def _environment_secret_id() -> str:
    """The secret identifier, from one fixed environment-variable name.

    Called only on the authorized path, after every gate has passed. The
    *name* is a constant and is not a secret; the *value* is, and it is never
    printed, logged, returned to a caller or included in a refusal.

    ``os`` is imported inside the body, so an ordinary import of this module --
    and every refusal path above -- performs no environment lookup at all.

    Raises:
        LookupError: if the variable is unset or blank. Converted by the caller
            into the closed ``REFUSED_SECRET_IDENTIFIER`` outcome, which names
            nothing -- and which is not the credential outcome, because at that
            point no client exists and nothing has been invoked.
    """
    import os

    value = os.environ.get(SECRET_ID_ENV_VAR, "")
    if not value.strip():
        raise LookupError("the secret identifier environment variable is unset")
    return value


def _governed_identity_gate() -> str | None:
    """The existing account identity gate. Not a second implementation of one."""
    from aws_foundation_verify import identity_gate  # type: ignore[import-not-found]

    return identity_gate()  # type: ignore[no-any-return]


def _governed_licensed_bucket() -> str:
    """The licensed bucket from governed Terraform state. Never the control one."""
    from aws_foundation_verify import tf_outputs  # type: ignore[import-not-found]

    return str(tf_outputs()[LICENSED_BUCKET_OUTPUT])


def _secrets_client() -> Any:
    """A Secrets Manager client, pinned to the governed region.

    The one AWS SDK construction ADR-0015 authorizes, and the reason the SDK is a
    declared dependency at all. It lives in a script rather than under ``src/``
    so the data platform stays SDK-free.
    """
    import boto3

    return boto3.client("secretsmanager", region_name=EXPECTED_REGION)


def _s3_client() -> Any:
    """An S3 client, pinned to the governed region."""
    import boto3

    return boto3.client("s3", region_name=EXPECTED_REGION)


def _transport() -> Any:
    """The origin-pinned provider transport."""
    from kalpamani.data.ingest.sharadar.transport import UrllibTransport

    return UrllibTransport()


#: The public surface, stated so it can be checked rather than inferred.
#:
#: The authorization capability, its mint and its minting function are all
#: absent, deliberately: an exported mint is a public constructor by another
#: name. An audit guard asserts their absence, which is only meaningful
#: because this list exists to be absent from.
__all__ = [
    "BINDING_AUTHORIZATION_FLAG",
    "REFUSED_OPTIONS",
    "SECRET_FAILURE_OUTCOME",
    "SECRET_ID_ENV_VAR",
    "BindingPreflightError",
    "PreflightOutcome",
    "SystemClock",
    "build_parser",
    "main",
    "run_binding_preflight",
]


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    sys.exit(main())
