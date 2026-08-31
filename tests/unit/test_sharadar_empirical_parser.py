"""The strict private parser: refusals fail closed, and nothing is silently repaired.

Every payload here is invented. The column names are the ones the vendor documents in
prose, because the parser's contract is written against them; every value is
hand-authored, because a value is a vendor row and a vendor row may not be in this
repository.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from fixtures.sharadar_empirical import ACTIONS_CSV, STOCKS_CSV, TICKERS_CSV
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.qualify.sharadar.parser import (
    MAX_FIELD_LENGTH,
    MAX_PARSE_BYTES,
    MAX_ROWS_PER_PAGE,
    REQUIRED_FIELDS,
    PagePair,
    ParseDefect,
    ParseError,
    date_field,
    decimal_field,
    parse_payload,
    schema_digest_of,
)


def _refuses(payload: bytes, dataset: SharadarDataset = SharadarDataset.STOCKS) -> ParseDefect:
    with pytest.raises(ParseError) as raised:
        parse_payload(payload, dataset=dataset)
    return raised.value.defect


# -- encoding ----------------------------------------------------------------


def test_strict_utf8_is_required_and_nothing_is_replaced() -> None:
    assert _refuses(b"ticker,date,close\n\xff\xfe,1998-01-05,1\n") is ParseDefect.ENCODING_INVALID


def test_a_byte_order_mark_is_refused_rather_than_stripped() -> None:
    # Stripping would change the observed header, and the schema digest has to
    # describe what was actually delivered.
    assert _refuses(b"\xef\xbb\xbf" + STOCKS_CSV) is ParseDefect.BYTE_ORDER_MARK


def test_a_payload_over_the_ceiling_is_refused_before_decoding() -> None:
    assert _refuses(b"x" * (MAX_PARSE_BYTES + 1)) is ParseDefect.PAYLOAD_TOO_LARGE


def test_a_non_bytes_payload_is_refused() -> None:
    assert _refuses("a string") is ParseDefect.PAYLOAD_MALFORMED  # type: ignore[arg-type]


# -- headers -----------------------------------------------------------------


def test_an_empty_body_is_refused_because_it_has_no_header() -> None:
    assert _refuses(b"") is ParseDefect.HEADER_MISSING


def test_a_duplicated_header_field_is_refused() -> None:
    assert _refuses(b"ticker,date,close,close\nZ,1998-01-05,1,2\n") is (
        ParseDefect.HEADER_DUPLICATED
    )


def test_a_blank_header_field_is_refused() -> None:
    assert _refuses(b"ticker,date,close, \nZ,1998-01-05,1,2\n") is ParseDefect.HEADER_BLANK


def test_a_missing_required_field_is_refused_per_dataset() -> None:
    assert _refuses(b"ticker,date\nZ,1998-01-05\n") is ParseDefect.REQUIRED_FIELD_MISSING


def test_every_dataset_declares_a_required_subset_not_an_exhaustive_header() -> None:
    # The vendor publishes no complete column list for any of these tables, so an
    # exact-header contract would be this package inventing a vendor fact.
    assert set(REQUIRED_FIELDS) == set(SharadarDataset)
    for required in REQUIRED_FIELDS.values():
        assert 0 < len(required) <= 3


def test_observed_extras_are_recorded_rather_than_discarded() -> None:
    page = parse_payload(STOCKS_CSV, dataset=SharadarDataset.STOCKS)
    assert "closeadj" in page.observed_extras
    assert "lastupdated" in page.observed_extras
    assert set(page.header) == set(REQUIRED_FIELDS[SharadarDataset.STOCKS]) | set(
        page.observed_extras
    )


# -- rows --------------------------------------------------------------------


def test_a_ragged_row_is_refused_rather_than_padded_or_truncated() -> None:
    assert _refuses(b"ticker,date,close\nZ,1998-01-05\n") is ParseDefect.ROW_RAGGED
    assert _refuses(b"ticker,date,close\nZ,1998-01-05,1,2\n") is ParseDefect.ROW_RAGGED


def test_a_page_over_the_row_ceiling_is_refused() -> None:
    body = b"ticker,date,close\n" + b"Z,1998-01-05,1\n" * (MAX_ROWS_PER_PAGE + 1)
    assert _refuses(body) is ParseDefect.ROW_COUNT_EXCEEDED


def test_an_over_long_field_is_refused() -> None:
    body = b"ticker,date,close\nZ,1998-01-05," + b"9" * (MAX_FIELD_LENGTH + 1) + b"\n"
    assert _refuses(body) is ParseDefect.FIELD_TOO_LONG


def test_delivered_order_is_preserved_and_never_sorted() -> None:
    body = b"ticker,date,close\nZB,1998-01-06,2\nZA,1998-01-05,1\n"
    page = parse_payload(body, dataset=SharadarDataset.STOCKS)
    assert page.column("ticker") == ("ZB", "ZA")


def test_duplicate_rows_are_detected_and_reported_never_collapsed() -> None:
    body = b"ticker,date,close\nZ,1998-01-05,1\nZ,1998-01-05,1\n"
    page = parse_payload(body, dataset=SharadarDataset.STOCKS)
    assert page.row_count == 2
    assert page.duplicate_row_count == 1


def test_a_missing_value_stays_distinct_from_zero() -> None:
    body = b"ticker,date,close\nZ,1998-01-05,\nZ,1998-01-06,0\n"
    page = parse_payload(body, dataset=SharadarDataset.STOCKS)
    closes = page.column("close")
    assert closes == (None, "0")
    assert decimal_field(closes[0]) is None
    assert decimal_field(closes[1]) == Decimal("0")


def test_a_header_only_page_is_valid_and_is_not_a_fault() -> None:
    page = parse_payload(b"ticker,date,close\n", dataset=SharadarDataset.STOCKS)
    assert page.row_count == 0
    assert page.is_header_only is True


def test_rfc4180_quoting_is_handled() -> None:
    body = b'ticker,date,close\n"Z,A",1998-01-05,"1.50"\n'
    page = parse_payload(body, dataset=SharadarDataset.STOCKS)
    assert page.column("ticker") == ("Z,A",)
    assert page.column("close") == ("1.50",)


def test_an_absent_column_answers_empty_and_is_distinguishable_from_blank_values() -> None:
    page = parse_payload(b"ticker,date,close\nZ,1998-01-05,\n", dataset=SharadarDataset.STOCKS)
    assert page.column("closeadj") == ()
    assert page.has_column("closeadj") is False
    assert page.column("close") == (None,)
    assert page.has_column("close") is True


# -- typed accessors ---------------------------------------------------------


def test_numerics_are_decimal_and_never_binary_float() -> None:
    value = decimal_field("0.1")
    assert isinstance(value, Decimal)
    assert value == Decimal("0.1")
    # The comparison a float would fail.
    assert decimal_field("0.1") + decimal_field("0.2") == Decimal("0.3")  # type: ignore[operator]


@pytest.mark.parametrize("value", [None, "", "not a number", "NaN", "Infinity"])
def test_an_unusable_numeric_is_absent_rather_than_zero(value: str | None) -> None:
    assert decimal_field(value) is None


def test_dates_are_real_calendar_dates_and_never_instants() -> None:
    parsed = date_field("1998-01-05")
    assert parsed == date(1998, 1, 5)
    assert type(parsed) is date


@pytest.mark.parametrize("value", [None, "", "2026-13-45", "1998-02-30", "05/01/1998"])
def test_an_impossible_date_is_absent_rather_than_repaired(value: str | None) -> None:
    assert date_field(value) is None


def test_a_date_only_value_is_not_coerced_into_an_instant() -> None:
    assert date_field("1998-01-05T00:00:00+00:00") is None


# -- schema digests ----------------------------------------------------------


def test_the_schema_digest_is_deterministic() -> None:
    first = parse_payload(STOCKS_CSV, dataset=SharadarDataset.STOCKS)
    second = parse_payload(STOCKS_CSV, dataset=SharadarDataset.STOCKS)
    assert first.schema_digest == second.schema_digest


def test_the_schema_digest_is_order_sensitive() -> None:
    assert schema_digest_of(("a", "b")) != schema_digest_of(("b", "a"))


def test_an_added_column_changes_the_schema_digest() -> None:
    baseline = parse_payload(b"ticker,date,close\n", dataset=SharadarDataset.STOCKS)
    widened = parse_payload(b"ticker,date,close,extra\n", dataset=SharadarDataset.STOCKS)
    assert baseline.schema_digest != widened.schema_digest


# -- page pairs and the completeness probe ------------------------------------


def _pair(second: bytes) -> PagePair:
    return PagePair(
        dataset=SharadarDataset.STOCKS,
        first=parse_payload(STOCKS_CSV, dataset=SharadarDataset.STOCKS),
        second=parse_payload(second, dataset=SharadarDataset.STOCKS),
    )


def test_an_empty_second_page_proves_the_first_was_complete() -> None:
    pair = _pair(b"ticker,date,open,high,low,close,closeadj,closeunadj,volume,lastupdated\n")
    assert pair.truncated is False
    assert pair.schema_stable is True
    assert pair.row_count_usable is True


def test_a_non_empty_second_page_establishes_truncation() -> None:
    pair = _pair(STOCKS_CSV)
    assert pair.truncated is True
    assert pair.row_count_usable is False


def test_a_schema_that_changed_between_pages_makes_row_counts_unusable() -> None:
    pair = _pair(b"ticker,date,close\n")
    assert pair.schema_stable is False
    assert pair.row_count_usable is False


# -- disclosure ---------------------------------------------------------------


def test_no_refusal_carries_a_row_or_a_field_value() -> None:
    ragged = b"ticker,date,close\nSECRETVALUE,1998-01-05\n"
    with pytest.raises(ParseError) as raised:
        parse_payload(ragged, dataset=SharadarDataset.STOCKS)
    rendered = f"{raised.value} {raised.value!r} {raised.value.args}"
    assert "SECRETVALUE" not in rendered


def test_the_parsed_page_repr_carries_no_row() -> None:
    page = parse_payload(TICKERS_CSV, dataset=SharadarDataset.TICKERS)
    rendered = repr(page)
    assert "ZZ-SYNTH-01" not in rendered
    assert "900001" not in rendered


def test_the_page_pair_repr_carries_no_row() -> None:
    rendered = repr(_pair(b"ticker,date,close\n"))
    assert "ZZ-SYNTH-01" not in rendered


def test_the_three_datasets_all_parse() -> None:
    for dataset, body in (
        (SharadarDataset.TICKERS, TICKERS_CSV),
        (SharadarDataset.STOCKS, STOCKS_CSV),
        (SharadarDataset.ACTIONS, ACTIONS_CSV),
    ):
        page = parse_payload(body, dataset=dataset)
        assert page.dataset is dataset
        assert page.row_count > 0


def test_no_action_code_vocabulary_is_compiled_into_the_parser() -> None:
    # The vendor does not publish its action-code set, which the source register
    # records explicitly. A compiled list here would be this package inventing one.
    from pathlib import Path

    from kalpamani.data.qualify.sharadar import parser as parser_module

    source = Path(parser_module.__file__).read_text(encoding="utf-8")
    for invented in ("ACTION_CODES", '"split"', '"dividend"', '"spinoff"'):
        assert invented not in source
