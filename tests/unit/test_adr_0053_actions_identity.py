"""ADR-0053 §12: the canonical full-row actions event identity, as an executable specification.

The reference implementation below lives in this test module only. It is not a runtime module, it
activates no runtime path, and the runtime identity module the amendment calls for is a later,
separately authorized code cycle. What is proved here is the contract's *properties*: the seven
governed fields are derived from the accepted schema digest, every field participates in identity,
object and delivery ordering are irrelevant, normalization is deterministic and lossless, exact
duplicates and digest collisions are refused, the coarse key fails the mutation control, and the
D-20 tickers group may be reused only under an exact binding.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

import pytest

from kalpamani.data.contracts.canonical import canonical_bytes
from kalpamani.data.qualify.sharadar.parser import schema_digest_of

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
ADR: Final = (
    REPO_ROOT
    / "docs"
    / "decisions"
    / "ADR-0053-pagination-v2-single-data-page-and-completion-probe.md"
)
ADR_TEXT: Final = ADR.read_text(encoding="utf-8")

#: The governed actions schema: the accepted Route-A digest (observed by D-20) is the parser's
#: order-sensitive digest of exactly these seven columns, in this order (ADR-0053 §12.3).
ACTIONS_FIELDS: Final = ("date", "action", "ticker", "name", "value", "contraticker", "contraname")
ACCEPTED_ACTIONS_SCHEMA: Final = "f2de54a58d32d33efb87647b1b62e6768175cb720bad6e7a2991fbba23a1fa72"
CONTRACT: Final = "sharadar-actions-event-identity/v1"


class ActionsIdentityRefusalError(Exception):
    """A closed refusal; the message is the member token, never a row."""


def normalize_field(name: str, value: str | None) -> str | None:
    """The typed normalization of §12.3: date, decimal literal, exact strings, null."""
    if value is None:
        if name in ("date", "action", "ticker"):
            raise ActionsIdentityRefusalError("ACTIONS_REQUIRED_FIELD_NULL")
        return None
    if name == "date":
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            raise ActionsIdentityRefusalError("ACTIONS_DATE_MALFORMED") from None
    if name == "value":
        try:
            Decimal(value)
        except InvalidOperation:
            raise ActionsIdentityRefusalError("ACTIONS_VALUE_NOT_DECIMAL") from None
        return value  # the exact delivered literal; no rescaling, no float
    return value  # exact delivered text; no trimming, folding or Unicode normalization


def canonical_row(row: dict[str, str | None], *, schema_digest: str) -> bytes:
    """§12.4(1): a list of pairs in accepted order, bound to the schema digest."""
    if schema_digest != ACCEPTED_ACTIONS_SCHEMA or set(row) != set(ACTIONS_FIELDS):
        raise ActionsIdentityRefusalError("ACTIONS_SCHEMA_NOT_GOVERNED")
    fields = [[name, normalize_field(name, row[name])] for name in ACTIONS_FIELDS]
    return canonical_bytes({"contract": CONTRACT, "schema": schema_digest, "fields": fields})


def event_identity(row: dict[str, str | None], *, schema_digest: str) -> str:
    """§12.4(2): SHA-256 of the canonical row."""
    return hashlib.sha256(canonical_row(row, schema_digest=schema_digest)).hexdigest()


def admit_events(
    rows: list[dict[str, str | None]],
    *,
    schema_digest: str,
    digest: Callable[..., str] = event_identity,
) -> tuple[tuple[str, bytes], ...]:
    """§12.4(4)-(7): refuse exact duplicates and collisions; order by canonical bytes."""
    seen: dict[str, bytes] = {}
    for row in rows:
        canonical = canonical_row(row, schema_digest=schema_digest)
        identity = digest(row, schema_digest=schema_digest)
        if identity in seen:
            if seen[identity] == canonical:
                raise ActionsIdentityRefusalError("ACTIONS_DUPLICATE_EVENT")
            raise ActionsIdentityRefusalError("ACTIONS_IDENTITY_COLLISION")
        seen[identity] = canonical
    return tuple(sorted(seen.items(), key=lambda item: item[1]))


def coarse_identity(row: dict[str, str | None], *, schema_digest: str) -> str:
    """The superseded coarse key, kept only as the mutation control."""
    return hashlib.sha256(canonical_bytes([row["ticker"], row["date"], row["action"]])).hexdigest()


#: §12.5: every binding field of the reused D-20 tickers group, as recorded.
TICKERS_REUSE_BINDING: Final = {
    "predicate": "table=stocks",
    "window": "SNAPSHOT",
    "shape_digest": "b66e69ed479829e0ed9625662551549fea883c12a2817d7cd4bab134d4c2ee3c",
    "schema_digest": "1162197271c19a530482df5e6accf7e1fe22b14e14b668c29b978b4daae5d824",
    "identity_rule": "permaticker",
    "verdict": "COMPLETE_SHAPED_SHORT_PAGE",
    "probe_required": False,
    "bytes": 8196857,
    "rows": 20976,
    "sha256": "ccdd104acc30a67eb04b8bba2bb45c147b854d86d7ca028bbcbeb3f6ca3d787f",
}


def admit_tickers_reuse(candidate: dict[str, Any]) -> bool:
    """§12.5: reuse only when every binding field matches and the verdict is complete."""
    return (
        candidate == TICKERS_REUSE_BINDING and candidate["verdict"] == "COMPLETE_SHAPED_SHORT_PAGE"
    )


def _row(**overrides: str | None) -> dict[str, str | None]:
    base: dict[str, str | None] = {
        "date": "2025-03-14",
        "action": "dividend",
        "ticker": "XYZ",
        "name": "Example Corp",
        "value": "0.25",
        "contraticker": None,
        "contraname": None,
    }
    base.update(overrides)
    return base


def test_the_seven_fields_are_derived_from_the_accepted_schema_digest() -> None:
    assert schema_digest_of(ACTIONS_FIELDS) == ACCEPTED_ACTIONS_SCHEMA
    assert schema_digest_of(
        ("ticker", "date", "action", "name", "value", "contraticker", "contraname")
    ) != (ACCEPTED_ACTIONS_SCHEMA)
    for name in ACTIONS_FIELDS:
        assert f"`{name}`" in ADR_TEXT.split("### 12.3", 1)[1].split("### 12.4", 1)[0]


def test_rows_sharing_the_coarse_key_but_differing_elsewhere_are_distinct_events() -> None:
    a = _row(value="0.25")
    b = _row(value="0.30")
    assert coarse_identity(a, schema_digest=ACCEPTED_ACTIONS_SCHEMA) == coarse_identity(
        b, schema_digest=ACCEPTED_ACTIONS_SCHEMA
    )
    assert event_identity(a, schema_digest=ACCEPTED_ACTIONS_SCHEMA) != event_identity(
        b, schema_digest=ACCEPTED_ACTIONS_SCHEMA
    )
    assert len(admit_events([a, b], schema_digest=ACCEPTED_ACTIONS_SCHEMA)) == 2


@pytest.mark.parametrize("field", ACTIONS_FIELDS)
def test_changing_each_field_independently_changes_the_identity(field: str) -> None:
    base = _row(contraticker="ABC", contraname="Other Corp")
    changed = dict(base)
    changed[field] = {"date": "2025-03-15", "value": "0.26"}.get(field, str(base[field]) + "x")
    assert event_identity(base, schema_digest=ACCEPTED_ACTIONS_SCHEMA) != event_identity(
        changed, schema_digest=ACCEPTED_ACTIONS_SCHEMA
    )


def test_source_object_ordering_does_not_change_the_identity() -> None:
    forward = _row()
    reversed_order = {name: forward[name] for name in reversed(ACTIONS_FIELDS)}
    assert list(reversed_order) != list(forward)
    assert event_identity(forward, schema_digest=ACCEPTED_ACTIONS_SCHEMA) == event_identity(
        reversed_order, schema_digest=ACCEPTED_ACTIONS_SCHEMA
    )
    assert canonical_row(forward, schema_digest=ACCEPTED_ACTIONS_SCHEMA) == canonical_row(
        reversed_order, schema_digest=ACCEPTED_ACTIONS_SCHEMA
    )


def test_provider_row_ordering_does_not_change_the_canonical_event_set() -> None:
    rows = [_row(value="0.25"), _row(value="0.30"), _row(ticker="ABC"), _row(date="2025-03-15")]
    assert admit_events(rows, schema_digest=ACCEPTED_ACTIONS_SCHEMA) == admit_events(
        list(reversed(rows)), schema_digest=ACCEPTED_ACTIONS_SCHEMA
    )


def test_normalization_is_deterministic_and_lossless() -> None:
    a = event_identity(_row(name=None), schema_digest=ACCEPTED_ACTIONS_SCHEMA)
    assert a == event_identity(_row(name=None), schema_digest=ACCEPTED_ACTIONS_SCHEMA)
    # null is not the empty string, not zero, not a default
    assert a != event_identity(_row(name=""), schema_digest=ACCEPTED_ACTIONS_SCHEMA)
    assert event_identity(
        _row(value=None), schema_digest=ACCEPTED_ACTIONS_SCHEMA
    ) != event_identity(_row(value="0"), schema_digest=ACCEPTED_ACTIONS_SCHEMA)
    # the decimal literal is kept exactly: 0.25 and 0.250 are different deliveries
    assert event_identity(
        _row(value="0.25"), schema_digest=ACCEPTED_ACTIONS_SCHEMA
    ) != event_identity(_row(value="0.250"), schema_digest=ACCEPTED_ACTIONS_SCHEMA)
    # dates are validated calendar dates rendered YYYY-MM-DD, never instants
    assert b'["date","2025-03-14"]' in canonical_row(_row(), schema_digest=ACCEPTED_ACTIONS_SCHEMA)
    with pytest.raises(ActionsIdentityRefusalError, match="ACTIONS_DATE_MALFORMED"):
        event_identity(_row(date="2025-3-14"), schema_digest=ACCEPTED_ACTIONS_SCHEMA)
    with pytest.raises(ActionsIdentityRefusalError, match="ACTIONS_VALUE_NOT_DECIMAL"):
        event_identity(_row(value="1,5"), schema_digest=ACCEPTED_ACTIONS_SCHEMA)
    with pytest.raises(ActionsIdentityRefusalError, match="ACTIONS_SCHEMA_NOT_GOVERNED"):
        event_identity(_row(), schema_digest="0" * 64)


def test_exact_duplicate_canonical_rows_are_refused_not_deduplicated() -> None:
    with pytest.raises(ActionsIdentityRefusalError, match="ACTIONS_DUPLICATE_EVENT"):
        admit_events([_row(), _row()], schema_digest=ACCEPTED_ACTIONS_SCHEMA)


def test_a_digest_collision_with_differing_canonical_bytes_is_refused() -> None:
    def colliding(row: dict[str, str | None], *, schema_digest: str) -> str:
        return "collision"

    with pytest.raises(ActionsIdentityRefusalError, match="ACTIONS_IDENTITY_COLLISION"):
        admit_events(
            [_row(value="0.25"), _row(value="0.30")],
            schema_digest=ACCEPTED_ACTIONS_SCHEMA,
            digest=colliding,
        )


def test_the_coarse_key_fails_the_mutation_control() -> None:
    # Under the superseded key two legitimate distinct events read as one identity, which is
    # exactly the conflict D-20 measured 44 times in one window.
    rows = [_row(value="0.25"), _row(value="0.30")]
    with pytest.raises(ActionsIdentityRefusalError, match="ACTIONS_IDENTITY_COLLISION"):
        admit_events(rows, schema_digest=ACCEPTED_ACTIONS_SCHEMA, digest=coarse_identity)


def test_tickers_evidence_reuse_is_admitted_only_under_the_exact_binding() -> None:
    assert admit_tickers_reuse(dict(TICKERS_REUSE_BINDING))
    for field, altered in (
        ("predicate", "table=fundamentals"),
        ("schema_digest", "0" * 64),
        ("shape_digest", "1" * 64),
        ("identity_rule", "(permaticker, table)"),
        ("verdict", "NOT_COMPLETE"),
        ("rows", 20975),
        ("sha256", "2" * 64),
    ):
        candidate = dict(TICKERS_REUSE_BINDING)
        candidate[field] = altered
        assert not admit_tickers_reuse(candidate), field


def test_the_adr_states_the_contract_and_preserves_the_verdicts() -> None:
    plain = " ".join(line.removeprefix("> ") for line in ADR_TEXT.splitlines())
    plain = " ".join(plain.split()).replace("**", "").replace("`", "")
    for phrase in (
        "I accept a schema-bound canonical full-row identity for each delivered Sharadar actions",
        "D-20 remains failed overall",
        "Exact duplicate canonical rows are refused",
        "identity collision and is refused",
        "No rows are silently combined",
        "requires an explicit identity-contract review",
        "independent of provider delivery order",
        "L = 100000 remains unqualified until D-21 succeeds",
        "never conceals an incomplete or failed group",
        "D-21 requalifies both actions windows",
        CONTRACT,
        ACCEPTED_ACTIONS_SCHEMA,
    ):
        assert phrase in plain, phrase
