"""The production task image entrypoint (ADR-0036 §2.9, §2.12). **Never run.**

One process per task, selected by exactly one closed argument -- the task definition's
``command`` token -- and nothing else:

```text
kalpamani-production-acquire     the acquisition actor's entry
kalpamani-research-build         the build actor's entry
```

**An ordinary import does nothing observable.** No environment lookup, no client
construction, no socket, no file read. Every ``kalpamani`` import and every SDK import
sits inside a function body, and the real factories are constructed only inside the
selected entry, after the compiled checks and the credential-environment check have
passed inside :mod:`kalpamani.data.production.sharadar.entry`.

**What this file decides is exactly what ``src/`` cannot**: which real client to build.
The SDK is imported here and only here on the task path (the data platform imports
none), with the pure configuration dictionaries the platform states -- one attempt in
total, finite socket timeouts, the regional STS endpoint. **Credentials come from the
ECS container credential provider and from nothing else, by construction rather than
by exclusion**: every client is created from one fresh ``botocore`` session whose
credential resolver holds exactly one provider, the container provider over the
validated ``/v2/credentials/<id>`` relative URI, so the default chain -- environment
keys, a shared credentials file, a config file, ``credential_process``, assume-role,
web identity, SSO, the instance metadata service -- is never consulted, and
``boto3``'s cached default session is never used. The session's profile, config-file
and credentials-file variables are overridden so no ``AWS_*`` profile or file variable
is read either. A container retrieval that fails, fails closed: no other source is
tried, and no service request is issued. Credentials returned by the agent are
refreshable through the same, and only the same, provider.

**Reliance on the SDK, stated.** ``botocore.session.Session(session_vars=...)``,
``Session.register_component``, ``Session.create_client``,
``botocore.credentials.CredentialResolver``, ``botocore.credentials.ContainerProvider``
and ``botocore.utils.ContainerMetadataFetcher`` are non-underscored botocore classes and
methods; they are the SDK's own container-credential mechanism (the one the documented
default chain uses at its "container credentials" step), but the registry component
name ``credential_provider`` and the ``session_vars`` tuple layout are not part of the
documented public API. The tests cover both directly -- they build a session through
this file's real factory against synthetic files, a seeded default session and a
synthetic HTTP seam, and assert which provider answered and which were never consulted.

The metadata read is a single bounded ``urllib`` request to the URL the platform
validated, through an opener with **no proxy handler**, so an ambient proxy variable
cannot redirect a link-local read. The provider transport is the accepted origin-pinned
one at the production response ceiling.

**The compiled configuration does not exist in this repository.** The values an image
needs beyond the code -- its own digest and revision, the acquisition secret
identifier, the compiled origin address set, the build configuration -- are produced
at the image gate (ADR-0043 proposes how) and imported here from a module that is
absent until then. A missing module is ``REFUSED_CONFIGURATION`` with zero operations.

**No workstation ledger integration.** The task writes its receipt to stdout (the
allowlisted lines) and exits with the closed code; the launch tool records what it can
observe. Completing the ledger row from a task's counts is a later, separately gated
integration (ADR-0043 §5).

**This entrypoint has never been run, and running it is a separate written authorization
that has not been given.** Packaging, image publication and runtime verification are
later gates.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from typing import Any, Final

#: The one refusal exit code this file emits on its own, before any entry exists.
NO_ENTRY_EXIT_STATUS: Final = 2

#: The module the image gate generates. Absent in this repository, by design.
COMPILED_CONFIGURATION_MODULE: Final = "kalpamani_production_compiled"


def _environment_names() -> list[str]:
    """Variable **names** only; no value is read here."""
    import os

    return list(os.environ.keys())


def _environment(name: str) -> str | None:
    """One named variable's value, for the metadata URI alone."""
    import os

    return os.environ.get(name)


def _metadata_fetch(url: str, timeout_seconds: float, max_bytes: int) -> bytes:
    """One bounded GET of the validated metadata URL. No proxy, no redirect follow.

    The opener carries no proxy handler and no redirect handler, so the request goes
    to the link-local address the platform admitted and nowhere else. The body is read
    up to ``max_bytes + 1`` so an oversize response is detected rather than truncated.
    """
    import urllib.request

    opener = urllib.request.OpenerDirector()
    opener.add_handler(urllib.request.HTTPHandler())
    if not url.startswith("http://169.254.170.2/v4/"):
        raise ValueError("the metadata URL is not the validated link-local one")
    request = urllib.request.Request(url, method="GET")  # noqa: S310 - scheme and host pinned above
    with opener.open(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise RuntimeError("metadata endpoint did not answer 200")
        return bytes(response.read(max_bytes + 1))


def _resolve_origin(host: str) -> list[str]:
    """Every IPv4 address ``host`` resolves to, through the VPC resolver."""
    import socket

    return sorted({entry[4][0] for entry in socket.getaddrinfo(host, 443, family=socket.AF_INET)})


#: A path no file can have: the session's config and credentials "files". Reading them
#: raises the SDK's own not-found signal, which the session treats as no configuration.
_NO_FILE: Final = "//kalpamani-task-has-no-aws-configuration-file//"

#: The session variables overridden so that **no** environment variable and **no** file
#: can steer the session: no profile, no config file, no credentials file. The tuple is
#: botocore's ``(config_name, env_var, default, converter)``; ``None`` for the first two
#: means neither a config key nor an environment variable is consulted.
_ISOLATED_SESSION_VARS: Final[dict[str, tuple[Any, Any, Any, Any]]] = {
    "profile": (None, None, None, None),
    "config_file": (None, None, _NO_FILE, None),
    "credentials_file": (None, None, _NO_FILE, None),
}


def _isolated_session(environment: Any, *, http: Any = None, sleep: Any = None) -> Any:
    """One fresh session whose only credential source is the ECS container provider.

    ``environment`` is a mapping read for exactly one key -- the container relative
    URI -- which must already be the documented shape; ``http`` is the fetcher's HTTP
    session (the SDK's own when ``None``), ``sleep`` its retry sleeper. The container
    provider is handed a mapping holding **only** the relative URI, so it can see no
    full-URI variant and no authorization token. The retrieval is the SDK's bounded one:
    a 2-second timeout and at most three attempts against the link-local agent, and a
    failure raises the SDK's sanitized retrieval error, which the entry classifies as
    ``REFUSED_DEPENDENCY`` without trying anything else.
    """
    import time

    from botocore.credentials import ContainerProvider, CredentialResolver
    from botocore.session import Session
    from botocore.utils import ContainerMetadataFetcher

    from kalpamani.data.production.sharadar.task_clients import (
        CONTAINER_CREDENTIAL_VARIABLE,
        container_credential_source_refusal,
    )

    if container_credential_source_refusal(environment.get) is not None:
        raise ValueError("the container credential source is not the documented shape")
    relative_uri = environment[CONTAINER_CREDENTIAL_VARIABLE]
    session = Session(session_vars=dict(_ISOLATED_SESSION_VARS))
    fetcher = ContainerMetadataFetcher(session=http, sleep=time.sleep if sleep is None else sleep)
    provider = ContainerProvider(
        environ={CONTAINER_CREDENTIAL_VARIABLE: relative_uri}, fetcher=fetcher
    )
    session.register_component("credential_provider", CredentialResolver(providers=[provider]))
    return session


class _IsolatedClients:
    """Builds every task client from one isolated session, created on first use."""

    __slots__ = ("_environment", "_http", "_session", "_sleep")

    def __init__(self, environment: Any, *, http: Any = None, sleep: Any = None) -> None:
        """Bind the environment mapping; ``http`` and ``sleep`` are test seams only."""
        self._environment = environment
        self._http = http
        self._sleep = sleep
        self._session: Any = None

    def client(self, service: Any) -> Any:
        """One client from the platform's pure construction keywords and the session."""
        from botocore.config import Config

        from kalpamani.data.production.sharadar.task_clients import client_construction_kwargs

        if self._session is None:
            self._session = _isolated_session(self._environment, http=self._http, sleep=self._sleep)
        kwargs = client_construction_kwargs(service)
        config = Config(**kwargs.pop("config"))  # type: ignore[arg-type]
        return self._session.create_client(config=config, **kwargs)


def _client(service: Any, clients: _IsolatedClients) -> Any:
    """One SDK client from the isolated session. Never ``boto3.client``."""
    return clients.client(service)


def _transport() -> Any:
    """The accepted origin-pinned transport at the production response ceiling."""
    from kalpamani.data.ingest.sharadar.transport import UrllibTransport
    from kalpamani.data.production.sharadar.plan import MAX_RESPONSE_BYTES

    return UrllibTransport(max_response_bytes=MAX_RESPONSE_BYTES)


def _working_directory_cleanup(path: Any) -> Any:
    """Delete the task's working directory before exit, regardless of outcome."""
    import shutil

    def cleanup() -> None:
        shutil.rmtree(path)

    return cleanup


def _compiled_configuration(entry: Any) -> Any:
    """The image-gate module's configuration for ``entry``, or ``None`` if absent."""
    import importlib

    try:
        module = importlib.import_module(COMPILED_CONFIGURATION_MODULE)
    except ImportError:
        return None
    builder = getattr(module, "entry_configuration", None)
    if not callable(builder):
        return None
    try:
        return builder(entry)
    except Exception:
        return None


def _factories(entry: Any, working_directory: Any, *, clients: Any = None) -> Any:
    """The real factories for ``entry``. Constructs nothing; each factory is deferred.

    ``clients`` is a test seam: an :class:`_IsolatedClients` over a synthetic HTTP
    session. The image passes none and gets the real one over ``os.environ``.
    """
    import os
    import time
    from datetime import UTC, datetime

    from kalpamani.data.production.sharadar.entry import TaskEntry
    from kalpamani.data.production.sharadar.task_clients import TaskService

    def now() -> datetime:
        return datetime.now(UTC)

    if clients is None:
        clients = _IsolatedClients(os.environ)

    if entry is TaskEntry.ACQUISITION:
        from kalpamani.data.production.sharadar.acquisition_entry import AcquisitionFactories

        return AcquisitionFactories(
            environment_names=_environment_names,
            environment=_environment,
            metadata_fetch=_metadata_fetch,
            ssm=lambda: _client(TaskService.SSM, clients),
            sts=lambda: _client(TaskService.STS, clients),
            s3=lambda: _client(TaskService.S3, clients),
            secrets=lambda: _client(TaskService.SECRETS_MANAGER, clients),
            transport=_transport,
            resolve_origin=_resolve_origin,
            # The task-side spent-identity source is an owner decision not yet taken
            # (ADR-0043 §3): none is configured, and the accepted registry refuses.
            spent_identities=None,
            now=now,
            monotonic=time.monotonic,
            sleep=time.sleep,
            cleanup=_working_directory_cleanup(working_directory),
        )
    from kalpamani.data.production.sharadar.build_entry import BuildFactories

    return BuildFactories(
        environment_names=_environment_names,
        environment=_environment,
        metadata_fetch=_metadata_fetch,
        ssm=lambda: _client(TaskService.SSM, clients),
        sts=lambda: _client(TaskService.STS, clients),
        s3=lambda: _client(TaskService.S3, clients),
        now=now,
        monotonic=time.monotonic,
        sleep=time.sleep,
        cleanup=_working_directory_cleanup(working_directory),
    )


def _emit(lines: Iterable[str]) -> None:
    for line in lines:
        print(line)


def main(argv: Sequence[str] | None = None) -> int:
    """Select one closed entry, run it once, print the receipt, return its exit code.

    ``0`` means the selected actor's processing completed with every operation
    confirmed; non-zero names what refused or stopped short. **Neither is a data
    verdict.** This function has never been run.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)

    from kalpamani.data.production.sharadar.entry import (
        EXIT_STATUS,
        TaskOutcome,
        run_task_entry,
        select_entry,
        task_sentence,
    )

    entry = select_entry(arguments)
    if entry is None:
        # Nothing above this line looked anything up or constructed anything.
        print(task_sentence(TaskOutcome.REFUSED_ENTRY))
        return NO_ENTRY_EXIT_STATUS

    configuration = _compiled_configuration(entry)
    if configuration is None:
        # No compiled configuration, no working directory, no factory, no client.
        print(task_sentence(TaskOutcome.REFUSED_CONFIGURATION))
        return EXIT_STATUS[TaskOutcome.REFUSED_CONFIGURATION]

    import tempfile

    working_directory = tempfile.mkdtemp(prefix="kalpamani-task-")
    receipt = run_task_entry(
        entry=entry,
        configuration=configuration,
        factories=_factories(entry, working_directory),
    )
    _emit(receipt.render())
    return receipt.exit_code


__all__ = ["COMPILED_CONFIGURATION_MODULE", "NO_ENTRY_EXIT_STATUS", "main"]


if __name__ == "__main__":  # pragma: no cover - the image's process entry
    sys.exit(main())
