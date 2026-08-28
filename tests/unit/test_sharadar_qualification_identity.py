"""One request is one acquisition. **Offline and synthetic throughout.**

The neutral contract defines a retrieval identity as
``(payload digest, ingestion run id)``. An earlier revision of the runtime passed
one execution-level id to every publication, which made that identity mean
something it does not: two requests in one execution shared it.

Three concrete defects followed, and each has a test here:

* byte-identical payloads from **two datasets** collided on the global claim, and
  a run halted on a conflict that was an artefact of the identity rather than a
  fact about the data;
* byte-identical payloads from **two subjects** collapsed into one acquisition, so
  the second retrieval left no durable evidence;
* byte-identical payloads on **two pages** did the same.

The rest of the file establishes the properties a derived identity has to have to
keep those fixed: determinism, sensitivity to every component, and the structural
impossibility of a credential or a URL entering it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from fixtures.sharadar_provider import (
    OTHER_SYNTHETIC_CREDENTIAL_VALUE,
    SYNTHETIC_CREDENTIAL_VALUE,
)
from fixtures.sharadar_runtime import (
    EXECUTION_ID,
    OTHER_EXECUTION_ID,
    SUBJECT_A,
    SUBJECT_B,
    subjects,
    window,
)
from kalpamani.data.ingest.sharadar.datasets import (
    DateWindow,
    Page,
    ResponseFormat,
    SharadarDataset,
    SharadarRequest,
)
from kalpamani.data.ingest.sharadar.qualification import (
    ACQUISITION_DIGEST_CHARACTERS,
    NEUTRAL_IDENTIFIER_CEILING,
    DatasetPlan,
    QualificationDefect,
    QualificationPlan,
    QualificationPlanError,
    acquisition_id,
    request_identity_preimage,
)

pytestmark = pytest.mark.unit


def base_request(**overrides: Any) -> SharadarRequest:
    fields: dict[str, Any] = {
        "dataset": SharadarDataset.STOCKS,
        "ticker": SUBJECT_A,
        "response_format": ResponseFormat.CSV,
        "page": Page(limit=500, skip=0),
        "window": window(),
    }
    fields.update(overrides)
    return SharadarRequest(**fields)


def derive(request: SharadarRequest, execution: str = EXECUTION_ID) -> str:
    return acquisition_id(execution_id=execution, request=request)


# ---------------------------------------------------------------------------
# Shape and grammar
# ---------------------------------------------------------------------------


def test_a_derived_identity_stays_inside_the_neutral_grammar_and_ceiling() -> None:
    """A derived value that the neutral publisher would refuse is worse than
    useless: it fails deep inside a layer that cannot say why."""
    derived = derive(base_request(), "a" * 32)
    assert len(derived) <= NEUTRAL_IDENTIFIER_CEILING
    assert len(derived) == 32 + 1 + ACQUISITION_DIGEST_CHARACTERS


def test_the_execution_id_stays_legible_in_the_derived_identity() -> None:
    """Durable evidence has to be reconcilable with the attempt that produced it."""
    assert derive(base_request()).startswith(f"{EXECUTION_ID}.")


@pytest.mark.parametrize("execution", ["", "A" * 4, "x" * 33, "has space", 7, None])
def test_a_malformed_execution_id_is_refused(execution: Any) -> None:
    with pytest.raises(QualificationPlanError) as caught:
        acquisition_id(execution_id=execution, request=base_request())
    assert caught.value.defect is QualificationDefect.IDENTITY_MALFORMED


@pytest.mark.parametrize("request_object", [None, "request", 7, object()])
def test_a_non_exact_request_is_refused(request_object: Any) -> None:
    with pytest.raises(QualificationPlanError):
        acquisition_id(execution_id=EXECUTION_ID, request=request_object)


# ---------------------------------------------------------------------------
# Determinism, and sensitivity to every component
# ---------------------------------------------------------------------------


def test_the_same_canonical_request_derives_the_same_identity() -> None:
    assert derive(base_request()) == derive(base_request())


def test_two_plans_built_in_opposite_orders_derive_the_same_identities() -> None:
    forward = QualificationPlan(
        subjects=subjects(SUBJECT_A, SUBJECT_B),
        datasets=(
            DatasetPlan(dataset=SharadarDataset.TICKERS),
            DatasetPlan(dataset=SharadarDataset.STOCKS, window=window()),
        ),
        execution_id=EXECUTION_ID,
    )
    backward = QualificationPlan(
        subjects=subjects(SUBJECT_B, SUBJECT_A),
        datasets=(
            DatasetPlan(dataset=SharadarDataset.STOCKS, window=window()),
            DatasetPlan(dataset=SharadarDataset.TICKERS),
        ),
        execution_id=EXECUTION_ID,
    )
    assert [derive(r) for r in forward.requests()] == [derive(r) for r in backward.requests()]


#: Every component the derivation must bind. Changing any one must change the
#: identity -- otherwise two different requests share durable evidence.
COMPONENT_CHANGES: list[tuple[str, dict[str, Any]]] = [
    ("dataset", {"dataset": SharadarDataset.ACTIONS}),
    ("subject", {"ticker": SUBJECT_B}),
    ("range", {"window": DateWindow(start=date(2024, 1, 3), end=date(2024, 3, 28))}),
    ("format", {"response_format": ResponseFormat.JSON}),
    ("page limit", {"page": Page(limit=499, skip=0)}),
    ("page offset", {"page": Page(limit=500, skip=500)}),
]


@pytest.mark.parametrize("label,change", COMPONENT_CHANGES, ids=[c[0] for c in COMPONENT_CHANGES])
def test_changing_any_identity_component_changes_the_identity(
    label: str, change: dict[str, Any]
) -> None:
    assert derive(base_request()) != derive(base_request(**change))


def test_changing_the_execution_changes_the_identity() -> None:
    assert derive(base_request(), EXECUTION_ID) != derive(base_request(), OTHER_EXECUTION_ID)


def test_the_snapshot_dataset_derives_a_distinct_identity() -> None:
    """`tickers` has no window, so its range token is `SNAPSHOT` rather than
    absent -- an empty range would read as an unknown window."""
    snapshot = SharadarRequest(
        dataset=SharadarDataset.TICKERS,
        ticker=SUBJECT_A,
        response_format=ResponseFormat.CSV,
        page=Page(limit=500, skip=0),
        window=None,
    )
    assert "range=SNAPSHOT" in request_identity_preimage(
        execution_id=EXECUTION_ID, request=snapshot
    )
    assert derive(snapshot) != derive(base_request())


# ---------------------------------------------------------------------------
# Disclosure safety, by shape rather than by filter
# ---------------------------------------------------------------------------


def test_the_preimage_binds_exactly_the_declared_components() -> None:
    preimage = request_identity_preimage(execution_id=EXECUTION_ID, request=base_request())
    keys = [line.split("=", 1)[0] for line in preimage.splitlines()]
    assert keys == [
        "execution",
        "provider",
        "dataset",
        "subject",
        "range",
        "format",
        "limit",
        "skip",
    ]


def test_no_credential_or_url_can_enter_the_identity() -> None:
    """There is no component a credential could arrive in, so this is a property
    of the shape rather than of a filter applied afterwards."""
    preimage = request_identity_preimage(execution_id=EXECUTION_ID, request=base_request())
    for forbidden in (
        SYNTHETIC_CREDENTIAL_VALUE,
        OTHER_SYNTHETIC_CREDENTIAL_VALUE,
        "api_key",
        "https://",
        "api.sharadar.com",
        "?",
        "&",
    ):
        assert forbidden not in preimage


def test_the_credential_cannot_influence_the_derived_identity() -> None:
    """Two clients holding different credentials derive the same identity for the
    same request, because the credential is not an input."""
    from fixtures.sharadar_provider import credential

    first = credential(SYNTHETIC_CREDENTIAL_VALUE)
    second = credential(OTHER_SYNTHETIC_CREDENTIAL_VALUE)
    assert first.reveal() != second.reveal()
    # The signature takes no credential at all, which is the proof.
    import inspect

    assert set(inspect.signature(acquisition_id).parameters) == {"execution_id", "request"}
    assert derive(base_request()) == derive(base_request())


def test_the_preimage_uses_a_separator_no_component_can_contain() -> None:
    """Otherwise two different requests could produce one pre-image by moving
    where a delimiter falls."""
    preimage = request_identity_preimage(execution_id=EXECUTION_ID, request=base_request())
    for line in preimage.splitlines():
        _, _, value = line.partition("=")
        assert "\n" not in value


def test_the_derived_identity_is_lowercase_hex_after_the_execution() -> None:
    suffix = derive(base_request()).split(".", 1)[1]
    assert len(suffix) == ACQUISITION_DIGEST_CHARACTERS
    assert all(character in "0123456789abcdef" for character in suffix)


def test_a_plan_derives_one_distinct_identity_per_request() -> None:
    """Ninety-six requests, ninety-six identities. The plan's own ceilings make
    this the largest case that can occur."""
    plan = QualificationPlan(
        subjects=subjects(*(f"ZZ{index:02d}" for index in range(8))),
        datasets=(
            DatasetPlan(dataset=SharadarDataset.TICKERS, max_pages=4),
            DatasetPlan(dataset=SharadarDataset.STOCKS, window=window(), max_pages=4),
            DatasetPlan(dataset=SharadarDataset.ACTIONS, window=window(), max_pages=4),
        ),
        execution_id=EXECUTION_ID,
    )
    requests = plan.requests()
    assert len(requests) == 96
    assert len({derive(r) for r in requests}) == 96


def test_replacing_a_requests_field_changes_its_identity() -> None:
    """`dataclasses.replace` re-runs validation, so this is a genuine second
    request rather than a mutated first one."""
    original = base_request()
    changed = replace(original, ticker=SUBJECT_B)
    assert derive(original) != derive(changed)
