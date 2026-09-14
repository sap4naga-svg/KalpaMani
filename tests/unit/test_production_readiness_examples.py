"""The synthetic production examples under ``docs/operations/examples/production/``.

Every committed example is parsed through the accepted contract it illustrates, so an
example that drifts from its contract fails here rather than misleading the owner; and
every example is held to be **synthetic** -- the fixtures' secret name, RFC 5737
documentation addresses, ``synthetic-`` identities, the fixtures' commit -- and free of
any account-shaped value, so nothing in the directory can be mistaken for, or quietly
become, a production input. Nothing here contacts AWS, a provider, a registry or a
container engine.
"""

from __future__ import annotations

import importlib.util
import ipaddress
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_runtime import NOW
from kalpamani.data.production.sharadar import launch_records as lr
from kalpamani.data.production.sharadar.compiled import (
    build_compiled_configuration,
    parse_build_configuration,
    parse_compiled_configuration,
)
from kalpamani.data.production.sharadar.entry import TaskEntry
from kalpamani.data.production.sharadar.inputs import parse_acquisition_input, parse_build_input
from kalpamani.data.production.sharadar.plan import bind_plan
from kalpamani.data.production.sharadar.vocabulary import ProductionActor

pytestmark = pytest.mark.unit

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
EXAMPLES: Final = REPO_ROOT / "docs" / "operations" / "examples" / "production"
GENERATOR: Final = REPO_ROOT / "scripts" / "production_compiled_configuration.py"

#: The files the directory must carry, and nothing account-bearing beside them.
EXPECTED_FILES: Final[frozenset[str]] = frozenset(
    {
        "README.md",
        "acquire-inputs.synthetic.json",
        "build-inputs.synthetic.json",
        "build-inputs.observation.synthetic.json",
        "compiled-configuration.acquire.synthetic.json",
        "compiled-configuration.build.synthetic.json",
        "acquisition-input.v2.synthetic.json",
        "build-input.v1.synthetic.json",
        "owner-ledger.synthetic.json",
        "launch-authorization.synthetic.json",
    }
)

#: A twelve-digit run outside a full digest word is an account id (the docs audit's rule).
ACCOUNT_ID: Final = re.compile(r"(?<![0-9A-Za-z])\d{12}(?![0-9A-Za-z])")
DOCUMENTATION_NET: Final = ipaddress.ip_network("192.0.2.0/24")
SYNTHETIC_COMMIT: Final = "0123456789abcdef0123456789abcdef01234567"


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location("production_compiled_configuration", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(name: str) -> Any:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_the_directory_carries_exactly_the_documented_examples() -> None:
    assert {path.name for path in EXAMPLES.iterdir()} == EXPECTED_FILES


@pytest.mark.parametrize("name", sorted(EXPECTED_FILES))
def test_no_example_carries_an_account_shaped_value(name: str) -> None:
    text = (EXAMPLES / name).read_text(encoding="utf-8")
    assert ACCOUNT_ID.search(text) is None
    assert "arn:aws" not in text
    assert "synthetic" in text.lower()


def test_the_owner_inputs_examples_are_exactly_the_generators_field_sets() -> None:
    generator = _generator()
    acquire = _load("acquire-inputs.synthetic.json")
    build = _load("build-inputs.synthetic.json")
    assert set(acquire) == set(generator.ACQUISITION_INPUT_FIELDS)
    assert set(build) == set(generator.BUILD_INPUT_FIELDS)
    assert not (set(acquire) | set(build)) & set(generator.FORBIDDEN_INPUT_FIELDS)


def test_the_owner_inputs_examples_are_synthetic_and_compile() -> None:
    acquire = _load("acquire-inputs.synthetic.json")
    build = _load("build-inputs.synthetic.json")
    assert acquire["secret_name"].startswith("synthetic/")
    assert acquire["origin_addresses"] == sorted(acquire["origin_addresses"])
    for address in acquire["origin_addresses"]:
        assert ipaddress.ip_address(address) in DOCUMENTATION_NET
    generated_at = datetime(2026, 9, 20, tzinfo=UTC)
    raw_acquire = build_compiled_configuration(
        entry=TaskEntry.ACQUISITION,
        code_commit=SYNTHETIC_COMMIT,
        code_tree="89abcdef0123456789abcdef0123456789abcdef",
        generated_at=generated_at,
        secret_name=acquire["secret_name"],
        origin_addresses=acquire["origin_addresses"],
    )
    raw_build = build_compiled_configuration(
        entry=TaskEntry.BUILD,
        code_commit=SYNTHETIC_COMMIT,
        code_tree="89abcdef0123456789abcdef0123456789abcdef",
        generated_at=generated_at,
        build_configuration=parse_build_configuration(build["build_configuration"]),
    )
    # The committed compiled examples are exactly what the committed inputs compile to.
    assert raw_acquire == (EXAMPLES / "compiled-configuration.acquire.synthetic.json").read_bytes()
    assert raw_build == (EXAMPLES / "compiled-configuration.build.synthetic.json").read_bytes()


@pytest.mark.parametrize(
    ("name", "entry"),
    [
        ("compiled-configuration.acquire.synthetic.json", TaskEntry.ACQUISITION),
        ("compiled-configuration.build.synthetic.json", TaskEntry.BUILD),
    ],
)
def test_the_compiled_examples_parse_under_the_accepted_contract(
    name: str, entry: TaskEntry
) -> None:
    configured, digest = parse_compiled_configuration((EXAMPLES / name).read_bytes())
    assert configured.entry is entry
    assert configured.compiled.code_commit == SYNTHETIC_COMMIT
    assert configured.compiled.configuration_digest == digest


def test_the_acquisition_input_example_is_admitted_and_binds_its_plan() -> None:
    document = _load("acquisition-input.v2.synthetic.json")
    assert document["run_identity"].startswith("synthetic-")
    admitted = parse_acquisition_input(document, now=NOW)
    plan = bind_plan(admitted)
    assert plan.digest == document["plan_digest"]
    assert document["spent_identities"]["spent"] == []


def test_the_build_input_example_is_admitted() -> None:
    document = _load("build-input.v1.synthetic.json")
    assert document["build_identity"].startswith("synthetic-")
    admitted = parse_build_input(document, now=NOW)
    assert admitted.build_identity == document["build_identity"]
    assert all(row["run_identity"].startswith("synthetic-") for row in document["runs"])


def test_the_observation_example_admits_nothing_and_differs_only_in_its_accepted_set() -> None:
    """Route B's observation configuration (proposed): an explicitly empty accepted set is a valid
    configuration that admits no header -- never a relaxation, never a placeholder digest."""
    observation = _load("build-inputs.observation.synthetic.json")["build_configuration"]
    producing = _load("build-inputs.synthetic.json")["build_configuration"]
    parsed = parse_build_configuration(observation)
    assert set(parsed.schemas.digests) == {"actions", "stocks", "tickers"}
    assert all(not digests for digests in parsed.schemas.digests.values())
    for dataset, digests in producing["accepted_schemas"]["digests"].items():
        for digest in digests:
            assert not parsed.schemas.admits(dataset, digest)
    differing = {key for key in producing if producing[key] != observation.get(key)}
    assert differing == {"accepted_schemas"}
    assert set(observation) == set(producing)


def test_the_owner_ledger_example_is_admitted_and_shows_every_row_kind() -> None:
    """Proposed ADR-0045: a buildable row, a verification row, two provisional rows."""
    raw = (EXAMPLES / "owner-ledger.synthetic.json").read_bytes()
    ledger = lr.parse_owner_ledger(raw)
    kinds = {(row.kind, row.evidence, row.outcome) for row in ledger.rows}
    assert (lr.LaunchKind.PRODUCTION, lr.LedgerEvidence.RECEIPT_VERIFIED, "COMPLETED") in kinds
    assert (lr.LaunchKind.VERIFICATION, lr.LedgerEvidence.RECEIPT_VERIFIED, "VERIFIED") in kinds
    assert (lr.LaunchKind.PRODUCTION, lr.LedgerEvidence.EXIT_CODE_ONLY, "COMPLETED") in kinds
    buildable = [row.identity for row in ledger.rows if row.buildable]
    assert len(buildable) == 1 and buildable[0].startswith("synthetic-")
    for row in ledger.rows:
        assert row.identity.startswith(("synthetic-", "verify-synthetic-"))
        assert (row.kind is lr.LaunchKind.VERIFICATION) == row.identity.startswith("verify-")
    # Every identity in the ledger is consumed, whatever its row says.
    for row in ledger.rows:
        with pytest.raises(lr.LaunchRecordError):
            lr.admit_identity(ledger, row.identity, kind=row.kind)


def test_the_authorization_example_names_one_launch_and_expires() -> None:
    raw = (EXAMPLES / "launch-authorization.synthetic.json").read_bytes()
    document = json.loads(raw)
    identity = document["identity"]
    assert identity.startswith("synthetic-")
    record = lr.parse_authorization(
        raw,
        actor=ProductionActor.ACQUISITION,
        kind=lr.LaunchKind.PRODUCTION,
        identity=identity,
        now=NOW,
    )
    assert record.expires_at - record.issued_at <= lr.MAX_AUTHORIZATION_VALIDITY
    with pytest.raises(lr.LaunchRecordError):
        lr.parse_authorization(
            raw,
            actor=ProductionActor.ACQUISITION,
            kind=lr.LaunchKind.VERIFICATION,
            identity=identity,
            now=NOW,
        )
