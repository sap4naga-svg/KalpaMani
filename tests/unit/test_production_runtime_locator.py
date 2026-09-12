"""Behavioural tests: the ADR-0037 key builders, namespace separation, and the run locator.

The namespace-separation tests build every earlier package's keys with the
**merged** builders on the same synthetic inputs and prove the production
namespaces pairwise disjoint from them -- and that the earlier builders still
produce exactly what they produced before this cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import pytest

from fixtures.production_runtime import (
    BUCKET,
    CANARIES,
    OTHER_RUN_ID,
    PAYLOADS,
    RECORDS,
    RUN_ID,
    FakeS3Get,
    digest_of,
    encode,
    ledger_row_document,
    locator_document,
    locator_entry,
    slice_document,
)
from kalpamani.data.contracts.errors import UnsafePathComponentError
from kalpamani.data.contracts.paths import RESERVED_SEGMENTS, path_segment
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.ingest.bronze import RetrievalMetadata
from kalpamani.data.ingest.publication import (
    acquisition_claim_key,
    bronze_acquisition_key,
    bronze_payload_key,
)
from kalpamani.data.production.sharadar import keys as pk
from kalpamani.data.production.sharadar import locator as pl
from kalpamani.data.production.sharadar.inputs import LedgerRow, parse_slice
from kalpamani.data.qualify.sharadar.locator import locator_key_segments
from kalpamani.data.qualify.sharadar.publication import qualification_payload_key
from kalpamani.data.qualify.sharadar.read import LicensedReadError, ReadFailure
from kalpamani.data.qualify.sharadar.report import report_key_segments

PAYLOAD: Final = PAYLOADS[0]
DIGEST: Final = digest_of(PAYLOAD)
RETRIEVED_AT: Final = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)


def _retrieval(dataset: str = "actions") -> RetrievalMetadata:
    return RetrievalMetadata(
        provider="sharadar",
        dataset=dataset,
        retrieved_at=RETRIEVED_AT,
        source_schema_version="synthetic-schema-v0",
        ingestion_run_id=RUN_ID,
        acquisition_mode=AcquisitionMode.QUALIFICATION,
        requested_range="1998-01-01/2026-09-09",
    )


# ---------------------------------------------------------------------------
# The reserved segments and the production builders
# ---------------------------------------------------------------------------


class TestReservedSegments:
    def test_the_two_production_namespaces_are_reserved_and_the_earlier_one_kept(self) -> None:
        assert RESERVED_SEGMENTS == frozenset(
            {"_acquisition_claims", "_indexes", "_production_claims"}
        )
        for segment in RESERVED_SEGMENTS:
            assert path_segment(segment, kind="test") == segment

    def test_an_external_identifier_still_cannot_spell_a_reserved_segment(self) -> None:
        for spelling in ("_indexes", "_production_claims", "_other"):
            with pytest.raises(UnsafePathComponentError):
                path_segment(spelling + "x", kind="run id")


class TestProductionBuilders:
    def test_the_four_layouts_are_the_adr_0037_ones(self) -> None:
        payload = pk.production_payload_key(dataset="actions", payload=PAYLOAD)
        record = pk.production_acquisition_key(
            dataset="actions", payload_digest=DIGEST, run_id=RUN_ID, ordinal=3, record=RECORDS[0]
        )
        claim = pk.production_claim_key(
            payload_digest=DIGEST, run_id=RUN_ID, ordinal=3, claim=b"{}"
        )
        locator = pk.run_locator_key(run_id=RUN_ID, payload=b"{}")
        assert (
            payload.logical_key
            == f"licensed/bronze/sharadar/actions/production/objects/sha256/{DIGEST}"
        )
        assert record.logical_key == (
            f"licensed/bronze/sharadar/actions/production/acquisitions/{DIGEST}/{RUN_ID}.03.json"
        )
        assert claim.logical_key == f"licensed/bronze/_production_claims/{DIGEST}/{RUN_ID}.03.json"
        assert locator.logical_key == f"licensed/bronze/sharadar/_indexes/{RUN_ID}.json"
        assert pk.run_locator_logical_key(RUN_ID) == locator.logical_key

    @pytest.mark.parametrize("dataset", ["fundamentals", "SF1", "", "objects", "_indexes"])
    def test_a_dataset_outside_the_vocabulary_is_refused_value_free(self, dataset: str) -> None:
        with pytest.raises(pk.ProductionKeyError) as info:
            pk.production_payload_key(dataset=dataset, payload=PAYLOAD)
        assert dataset not in str(info.value) or dataset == ""

    @pytest.mark.parametrize("run_id", ["", "_indexes", "../x", "a/b", "x" * 65, 5])
    def test_a_run_identity_outside_the_grammar_is_refused(self, run_id: object) -> None:
        with pytest.raises(pk.ProductionKeyError):
            pk.run_locator_key_segments(run_id)  # type: ignore[arg-type]
        with pytest.raises(pk.ProductionKeyError):
            pk.production_claim_key(payload_digest=DIGEST, run_id=run_id, ordinal=0, claim=b"{}")  # type: ignore[arg-type]

    def test_a_digest_outside_the_grammar_is_refused(self) -> None:
        for digest in ("ABC", "0" * 63, "g" * 64):
            with pytest.raises(pk.ProductionKeyError):
                pk.production_payload_key_for_digest(dataset="actions", content_sha256=digest)

    def test_a_non_bytes_payload_is_refused(self) -> None:
        with pytest.raises(pk.ProductionKeyError):
            pk.production_payload_key(dataset="actions", payload="text")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Namespace separation, with the real builders on both sides
# ---------------------------------------------------------------------------


PRODUCTION_PREFIXES: Final = (
    "licensed/bronze/sharadar/actions/production/",
    "licensed/bronze/sharadar/tickers/production/",
    "licensed/bronze/sharadar/stocks/production/",
    "licensed/bronze/sharadar/_indexes/",
    "licensed/bronze/_production_claims/",
)


def _earlier_keys() -> dict[str, str]:
    retrieval = _retrieval()
    return {
        "general payload": bronze_payload_key(retrieval=retrieval, payload=PAYLOAD).logical_key,
        "general record": bronze_acquisition_key(
            retrieval=retrieval, payload_digest=DIGEST, record=RECORDS[0]
        ).logical_key,
        "general claim": acquisition_claim_key(
            payload_digest=DIGEST, run_id=RUN_ID, claim=b"{}"
        ).logical_key,
        "qualification payload": qualification_payload_key(
            dataset="actions",
            execution_id="synthetic-exec-0001",
            request_ordinal=3,
            content_sha256=DIGEST,
        ).logical_key,
        "qualification locator": "licensed/"
        + "/".join(locator_key_segments("synthetic-exec-0001")),
        "qualification report": "licensed/"
        + "/".join(
            report_key_segments(
                run_a_execution_id="synthetic-exec-0001",
                run_b_execution_id="synthetic-exec-0002",
                assessment_id="synthetic-assess-0001",
            )
        ),
    }


def _production_keys() -> dict[str, str]:
    return {
        "production payload": pk.production_payload_key(
            dataset="actions", payload=PAYLOAD
        ).logical_key,
        "production record": pk.production_acquisition_key(
            dataset="actions", payload_digest=DIGEST, run_id=RUN_ID, ordinal=0, record=RECORDS[0]
        ).logical_key,
        "production claim": pk.production_claim_key(
            payload_digest=DIGEST, run_id=RUN_ID, ordinal=0, claim=b"{}"
        ).logical_key,
        "production locator": pk.run_locator_logical_key(RUN_ID),
    }


class TestNamespaceSeparation:
    def test_no_earlier_key_lies_under_a_production_prefix(self) -> None:
        for name, key in _earlier_keys().items():
            assert not any(key.startswith(prefix) for prefix in PRODUCTION_PREFIXES), name

    def test_every_production_key_lies_under_exactly_one_production_prefix(self) -> None:
        for name, key in _production_keys().items():
            assert sum(key.startswith(prefix) for prefix in PRODUCTION_PREFIXES) == 1, name

    def test_no_production_key_lies_under_an_earlier_prefix(self) -> None:
        earlier_prefixes = (
            "licensed/bronze/sharadar/actions/objects/",
            "licensed/bronze/sharadar/actions/acquisitions/",
            "licensed/bronze/_acquisition_claims/",
            "licensed/bronze/sharadar/actions/qualification/",
            "licensed/qualification/",
        )
        for name, key in _production_keys().items():
            assert not any(key.startswith(prefix) for prefix in earlier_prefixes), name

    def test_the_earlier_builders_are_byte_for_byte_unchanged(self) -> None:
        """Pinned literals: the general and qualification layouts this cycle did not touch."""
        keys = _earlier_keys()
        assert (
            keys["general payload"] == f"licensed/bronze/sharadar/actions/objects/sha256/{DIGEST}"
        )
        assert (
            keys["general record"]
            == f"licensed/bronze/sharadar/actions/acquisitions/{DIGEST}/{RUN_ID}.json"
        )
        assert (
            keys["general claim"] == f"licensed/bronze/_acquisition_claims/{DIGEST}/{RUN_ID}.json"
        )
        assert keys["qualification payload"] == (
            f"licensed/bronze/sharadar/actions/qualification/synthetic-exec-0001/requests/03/sha256/{DIGEST}"
        )
        assert (
            keys["qualification locator"]
            == "licensed/qualification/sharadar/locators/synthetic-exec-0001.json"
        )
        assert keys["qualification report"] == (
            "licensed/qualification/sharadar/reports/synthetic-exec-0001/synthetic-exec-0002/synthetic-assess-0001.json"
        )

    def test_same_bytes_and_identity_land_on_different_names_across_packages(self) -> None:
        earlier, production = _earlier_keys(), _production_keys()
        assert len(set(earlier.values()) | set(production.values())) == len(earlier) + len(
            production
        )


# ---------------------------------------------------------------------------
# The run locator: decoding, the four clauses, and the reader
# ---------------------------------------------------------------------------


def _row(run_id: str = RUN_ID, **overrides: Any) -> LedgerRow:
    document = ledger_row_document(run_id, **overrides)
    return LedgerRow(
        run_identity=document["run_identity"],
        slice=parse_slice(document["slice"]),
        plan_digest=document["plan_digest"],
        outcome=document["outcome"],
        launched_at=datetime.fromisoformat(document["launched_at"]),
        completed_at=datetime.fromisoformat(document["completed_at"]),
    )


def _validate(
    document: object, *, run_id: str = RUN_ID, row: LedgerRow | None = None
) -> pl.ValidatedRunLocator:
    return pl.validate_run_locator(
        document, run_id=run_id, ledger_row=_row() if row is None else row
    )


def _refused(document: object, **kwargs: Any) -> pl.RunLocatorDefect:
    with pytest.raises(pl.RunLocatorError) as info:
        _validate(document, **kwargs)
    for canary in CANARIES:
        assert canary not in str(info.value)
    return info.value.defect


class TestLocatorDecoding:
    def test_size_is_checked_before_decoding(self) -> None:
        raw = b"{" + b" " * pl.MAX_LOCATOR_BYTES + b"}"
        with pytest.raises(pl.RunLocatorError) as info:
            pl.decode_run_locator(raw)
        assert info.value.defect is pl.RunLocatorDefect.TOO_LARGE

    @pytest.mark.parametrize(
        ("raw", "defect"),
        [
            (b"", pl.RunLocatorDefect.EMPTY),
            (b"\xef\xbb\xbf{}", pl.RunLocatorDefect.ENCODING_INVALID),
            (b"\xff", pl.RunLocatorDefect.ENCODING_INVALID),
            (b"[]", pl.RunLocatorDefect.DOCUMENT_MALFORMED),
            (b"{", pl.RunLocatorDefect.DOCUMENT_MALFORMED),
            (b'{"a":1,"a":1}', pl.RunLocatorDefect.DUPLICATE_KEY),
        ],
    )
    def test_integrity_defects_refuse_before_any_clause(
        self, raw: bytes, defect: pl.RunLocatorDefect
    ) -> None:
        with pytest.raises(pl.RunLocatorError) as info:
            pl.decode_run_locator(raw)
        assert info.value.defect is defect

    def test_the_document_defect_mapping_is_total(self) -> None:
        from kalpamani.data.production.sharadar.documents import DocumentDefect

        assert set(pl._DOCUMENT_DEFECTS) == set(DocumentDefect)


class TestLocatorClauses:
    def test_a_valid_locator_is_admitted_in_ordinal_order(self) -> None:
        document = locator_document()
        document["entries"].reverse()
        locator = _validate(document)
        assert [entry.ordinal for entry in locator.entries] == [0, 1, 2, 3, 4, 5]
        assert locator.object_count == 12
        assert len(locator.exact_references()) == 12
        # Identical bytes across distinct requests of one dataset (tickers pages 0 and 2):
        # one payload name, distinct record names.
        assert locator.entries[2].payload.logical_key == locator.entries[4].payload.logical_key
        assert locator.entries[2].record.logical_key != locator.entries[4].record.logical_key
        for canary in CANARIES:
            assert canary not in repr(locator)

    # Clause 1: identity binding.
    def test_a_run_id_that_did_not_derive_the_key_is_refused(self) -> None:
        assert (
            _refused(locator_document(run_id=OTHER_RUN_ID)) is pl.RunLocatorDefect.IDENTITY_MISMATCH
        )

    def test_a_plan_digest_not_in_the_ledger_row_is_refused(self) -> None:
        assert (
            _refused(locator_document(plan_digest="0" * 64))
            is pl.RunLocatorDefect.PLAN_DIGEST_MISMATCH
        )

    def test_a_slice_not_in_the_ledger_row_is_refused(self) -> None:
        document = locator_document()
        document["slice"]["max_response_bytes"] = 1024
        assert _refused(document) is pl.RunLocatorDefect.SLICE_MISMATCH

    def test_no_ledger_row_refuses_before_any_clause(self) -> None:
        with pytest.raises(pl.RunLocatorError) as info:
            pl.validate_run_locator(locator_document(), run_id=RUN_ID, ledger_row=None)
        assert info.value.defect is pl.RunLocatorDefect.NO_LEDGER_ROW
        assert (
            _refused(locator_document(), row=_row(OTHER_RUN_ID))
            is pl.RunLocatorDefect.NO_LEDGER_ROW
        )

    # Clause 2: the prefix allowlist -- every escape route, each by name.
    @pytest.mark.parametrize(
        "escape",
        [
            f"licensed/bronze/sharadar/actions/objects/sha256/{DIGEST}",
            f"licensed/bronze/_acquisition_claims/{DIGEST}/{RUN_ID}.json",
            f"licensed/bronze/_production_claims/{DIGEST}/{RUN_ID}.00.json",
            f"licensed/bronze/sharadar/_indexes/{RUN_ID}.json",
            f"licensed/bronze/sharadar/actions/qualification/x/requests/00/sha256/{DIGEST}",
            f"licensed/qualification/sharadar/locators/{RUN_ID}.json",
            f"licensed/silver/x/{DIGEST}",
            f"licensed/gold/x/{DIGEST}",
            f"licensed/manifests/x/{DIGEST}",
            f"licensed/bronze/otherprovider/actions/production/objects/sha256/{DIGEST}",
            f"control/bronze/sharadar/actions/production/objects/sha256/{DIGEST}",
            f"licensed/bronze/sharadar/stocks/production/objects/sha256/{DIGEST}",
        ],
    )
    def test_a_payload_key_outside_the_allowlist_is_refused(self, escape: str) -> None:
        document = locator_document()
        document["entries"][0]["payload_key"] = escape
        assert _refused(document) in {
            pl.RunLocatorDefect.PREFIX_NOT_ALLOWED,
            pl.RunLocatorDefect.DATASET_NOT_IN_SLICE,
        }

    def test_a_record_key_naming_another_run_is_refused(self) -> None:
        document = locator_document()
        entry = document["entries"][0]
        entry["record_key"] = entry["record_key"].replace(
            f"/{RUN_ID}.00.json", f"/{OTHER_RUN_ID}.00.json"
        )
        assert _refused(document) is pl.RunLocatorDefect.PREFIX_NOT_ALLOWED

    def test_a_record_key_carrying_another_requests_ordinal_is_refused(self) -> None:
        """The record leaf binds this entry's ordinal, so two requests cannot share a record."""
        document = locator_document()
        entry = document["entries"][0]
        entry["record_key"] = entry["record_key"].replace(
            f"/{RUN_ID}.00.json", f"/{RUN_ID}.02.json"
        )
        assert _refused(document) is pl.RunLocatorDefect.PREFIX_NOT_ALLOWED

    def test_a_dataset_the_slice_does_not_declare_is_refused(self) -> None:
        document = locator_document()
        document["entries"][0] = locator_entry(0, "stocks", PAYLOADS[0], RECORDS[0])
        assert _refused(document) is pl.RunLocatorDefect.DATASET_NOT_IN_SLICE

    # Clause 3: request scope.
    def test_a_key_whose_digest_disagrees_with_the_recorded_digest_is_refused(self) -> None:
        document = locator_document()
        document["entries"][0]["payload_sha256"] = digest_of(b"other")
        assert _refused(document) is pl.RunLocatorDefect.KEY_DIGEST_MISMATCH

    def test_a_record_digest_is_not_in_the_key_and_is_verified_at_read_time(self) -> None:
        """A record is named by ``(payload digest, run id)``; ``read_exact`` proves its digest."""
        document = locator_document()
        document["entries"][0]["record_sha256"] = digest_of(b"other")
        locator = _validate(document)
        assert locator.entries[0].record.expected_sha256 == digest_of(b"other")

    def test_a_byte_count_over_the_slice_ceiling_is_refused(self) -> None:
        document = locator_document()
        document["entries"][0]["payload_bytes"] = 4 * 1024 * 1024 + 1
        assert _refused(document) is pl.RunLocatorDefect.BYTES_OVER_CEILING

    def test_a_missing_or_duplicated_ordinal_is_refused(self) -> None:
        document = locator_document()
        # Entry 2 restated as ordinal 0 with the tickers coordinates: its coordinates are
        # not the compiled request at ordinal 0, which is the first clause to fire.
        document["entries"][2] = locator_entry(0, "tickers", PAYLOADS[0], RECORDS[0])
        assert _refused(document) is pl.RunLocatorDefect.REQUEST_COORDINATES_MISMATCH
        # Two entries that both are ordinal 0, coordinates and all: a duplicated request.
        document = locator_document()
        document["entries"][2] = dict(document["entries"][0])
        assert _refused(document) is pl.RunLocatorDefect.REQUEST_DUPLICATED
        # An ordinal outside the compiled plan.
        document = locator_document()
        document["entries"][5] = locator_entry(
            6, "tickers", PAYLOADS[1], RECORDS[1], page_offset=30000
        )
        assert _refused(document) is pl.RunLocatorDefect.ORDINAL_INCONSISTENT

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda e: e["request"].__setitem__("window", "2025-01-01/2025-06-30"),
            lambda e: e["request"].__setitem__("page_offset", 555),
            lambda e: e["request"].__setitem__("page_limit", 9999),
            lambda e: e["request"].__setitem__("window", "SNAPSHOT"),
        ],
        ids=["window", "offset", "limit", "snapshot-for-windowed"],
    )
    def test_an_entry_whose_coordinates_are_not_the_compiled_requests_is_refused(
        self, mutate: Any
    ) -> None:
        """Containment in the slice's date range is not enough: the entry must equal the
        compiled request at its ordinal exactly."""
        document = locator_document()
        mutate(document["entries"][0])
        assert _refused(document) is pl.RunLocatorDefect.REQUEST_COORDINATES_MISMATCH

    def test_a_dataset_swapped_between_entries_is_refused(self) -> None:
        document = locator_document()
        # Ordinal 0 is an actions request; restate it as a tickers request with keys
        # consistent for tickers -- the coordinates no longer match the compiled plan.
        document["entries"][0] = locator_entry(0, "tickers", PAYLOADS[0], RECORDS[0])
        assert _refused(document) is pl.RunLocatorDefect.REQUEST_COORDINATES_MISMATCH

    def test_a_ledger_row_whose_slice_the_plan_cannot_compile_is_refused(self) -> None:
        row = _row()
        broken = LedgerRow(
            run_identity=row.run_identity,
            slice=parse_slice(slice_document(request_count=5)),
            plan_digest=row.plan_digest,
            outcome=row.outcome,
            launched_at=row.launched_at,
            completed_at=row.completed_at,
        )
        document = locator_document()
        document["slice"] = slice_document(request_count=5)
        document["planned_requests"] = 5
        document["completed_requests"] = 5
        document["entries"] = document["entries"][:5]
        assert _refused(document, row=broken) is pl.RunLocatorDefect.PLAN_NOT_COMPILABLE

    def test_a_request_count_disagreeing_with_the_slice_is_refused(self) -> None:
        document = locator_document()
        document["entries"].pop()
        document["completed_requests"] = 1
        document["planned_requests"] = 1
        assert _refused(document) is pl.RunLocatorDefect.REQUEST_COUNT_MISMATCH

    def test_a_window_disagreeing_with_the_compiled_request_is_refused(self) -> None:
        document = locator_document()
        document["entries"][0]["request"]["window"] = "1999-01-01/2026-09-11"
        assert _refused(document) is pl.RunLocatorDefect.REQUEST_COORDINATES_MISMATCH

    # Clause 4: completeness.
    def test_a_partial_locator_grants_no_build(self) -> None:
        assert _refused(locator_document(completeness="PARTIAL")) is pl.RunLocatorDefect.INCOMPLETE

    def test_an_unknown_publication_state_is_refused(self) -> None:
        assert (
            _refused(locator_document(publication_state_unknown=True))
            is pl.RunLocatorDefect.PUBLICATION_STATE_UNKNOWN
        )

    def test_an_unknown_schema_version_is_refused(self) -> None:
        assert (
            _refused(locator_document(schema_version="v0"))
            is pl.RunLocatorDefect.SCHEMA_VERSION_UNKNOWN
        )

    def test_a_qualification_mode_is_refused(self) -> None:
        assert (
            _refused(locator_document(acquisition_mode="QUALIFICATION"))
            is pl.RunLocatorDefect.MODE_UNEXPECTED
        )

    @pytest.mark.parametrize("field", sorted(pl.LOCATOR_FIELDS))
    def test_every_missing_field_is_refused(self, field: str) -> None:
        document = locator_document()
        del document[field]
        assert _refused(document) is pl.RunLocatorDefect.FIELD_MISSING

    def test_an_unknown_field_is_refused(self) -> None:
        assert _refused(locator_document(notes="free text")) is pl.RunLocatorDefect.FIELD_UNKNOWN

    def test_a_malformed_entry_is_refused(self) -> None:
        document = locator_document()
        document["entries"][0]["extra"] = 1
        assert _refused(document) is pl.RunLocatorDefect.ENTRY_MALFORMED


class TestTheReader:
    def _store(self) -> tuple[FakeS3Get, pl.ProductionLocatorReader]:
        document = locator_document()
        objects = {f"bronze/sharadar/_indexes/{RUN_ID}.json": encode(document)}
        for index, entry in enumerate(document["entries"]):
            objects[entry["payload_key"][len("licensed/") :]] = PAYLOADS[index % 2]
            objects[entry["record_key"][len("licensed/") :]] = RECORDS[index % 2]
        s3 = FakeS3Get(objects=objects)
        return s3, pl.ProductionLocatorReader(client=s3, licensed_bucket=BUCKET)

    def test_the_locator_is_read_by_name_and_every_object_by_exact_reference(self) -> None:
        s3, reader = self._store()
        locator = reader.read_run_locator(run_id=RUN_ID, ledger_row=_row())
        objects = list(reader.iter_locator_objects(locator))
        assert [entry.ordinal for entry, _, _ in objects] == [0, 1, 2, 3, 4, 5]
        assert [payload for _, payload, _ in objects] == [PAYLOADS[i % 2] for i in range(6)]
        assert [record for _, _, record in objects] == [RECORDS[i % 2] for i in range(6)]
        # One by-name read plus two per entry: the count the ADR requires.
        assert reader.get_object_count == 1 + locator.object_count == len(s3.calls)
        assert all(call["Bucket"] == BUCKET for call in s3.calls)

    def test_a_tampered_object_is_refused_before_it_is_returned(self) -> None:
        s3, reader = self._store()
        locator = reader.read_run_locator(run_id=RUN_ID, ledger_row=_row())
        key = locator.entries[0].payload.logical_key[len("licensed/") :]
        # Same length, different bytes: only the digest can tell, and it does.
        s3.objects[key] = PAYLOADS[0][:-1] + b"X"
        with pytest.raises(LicensedReadError) as info:
            list(reader.iter_locator_objects(locator))
        assert info.value.failure is ReadFailure.INTEGRITY_MISMATCH
        # Longer bytes are abandoned while reading, before any digest.
        s3.objects[key] = PAYLOADS[0] + b"x"
        with pytest.raises(LicensedReadError) as info:
            list(reader.iter_locator_objects(locator))
        assert info.value.failure is ReadFailure.TOO_LARGE

    def test_a_missing_locator_reads_nothing_further(self) -> None:
        s3, reader = self._store()
        with pytest.raises(LicensedReadError) as info:
            reader.read_run_locator(run_id=OTHER_RUN_ID, ledger_row=_row(OTHER_RUN_ID))
        assert info.value.failure is ReadFailure.NOT_FOUND
        assert len(s3.calls) == 1

    def test_an_oversize_locator_is_abandoned_while_reading(self) -> None:
        s3, reader = self._store()
        s3.objects[f"bronze/sharadar/_indexes/{RUN_ID}.json"] = b"{" + b" " * pl.MAX_LOCATOR_BYTES
        with pytest.raises(LicensedReadError) as info:
            reader.read_run_locator(run_id=RUN_ID, ledger_row=_row())
        assert info.value.failure is ReadFailure.TOO_LARGE

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d["entries"][0]["request"].__setitem__("page_offset", 555),
            lambda d: d["entries"][0]["request"].__setitem__("window", "2025-01-01/2025-06-30"),
            lambda d: d["entries"].__setitem__(2, dict(d["entries"][0])),
            lambda d: (d["entries"].pop(), d.__setitem__("completed_requests", 5)),
        ],
        ids=["offset", "window", "duplicate", "missing-request"],
    )
    def test_the_reader_refuses_before_reading_any_referenced_object(self, mutate: Any) -> None:
        s3, reader = self._store()
        document = locator_document()
        mutate(document)
        s3.objects[f"bronze/sharadar/_indexes/{RUN_ID}.json"] = encode(document)
        with pytest.raises(pl.RunLocatorError):
            reader.read_run_locator(run_id=RUN_ID, ledger_row=_row())
        assert len(s3.calls) == 1  # the by-name locator read, and nothing it names

    def test_a_refused_locator_reads_no_object(self) -> None:
        s3, reader = self._store()
        s3.objects[f"bronze/sharadar/_indexes/{RUN_ID}.json"] = encode(
            locator_document(completeness="PARTIAL")
        )
        with pytest.raises(pl.RunLocatorError):
            reader.read_run_locator(run_id=RUN_ID, ledger_row=_row())
        assert len(s3.calls) == 1

    def test_the_reader_cannot_write_or_head(self) -> None:
        _, reader = self._store()
        assert not hasattr(reader, "publish_report")
        assert not hasattr(reader, "put_object") and not hasattr(reader, "head_object")
        view = reader._reader._client
        with pytest.raises(LicensedReadError):
            view.put_object(Bucket=BUCKET, Key="x")
        with pytest.raises(LicensedReadError):
            view.head_object(Bucket=BUCKET, Key="x")

    def test_an_identity_outside_the_grammar_never_reaches_the_client(self) -> None:
        s3, reader = self._store()
        with pytest.raises(LicensedReadError) as info:
            reader.read_run_locator_bytes("../escape")
        assert info.value.failure is ReadFailure.INVALID_KEY and s3.calls == []

    def test_iterating_a_non_validated_locator_is_refused(self) -> None:
        _, reader = self._store()
        with pytest.raises(LicensedReadError):
            list(reader.iter_locator_objects(locator_document()))  # type: ignore[arg-type]
