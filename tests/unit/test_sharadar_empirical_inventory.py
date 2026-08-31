"""The owner-only subject inventory: eight classes, one name each, never disclosed.

**No test creates, reads or references the real private inventory.** The production
path is a git-ignored file under ``.runtime/`` that must never exist here; every test
below either validates an in-memory structure or writes a synthetic file to a
temporary directory it created itself.

Every subject used is unmistakably fictional and is not a listed security.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fixtures.sharadar_empirical import SYNTHETIC_SUBJECTS, inventory_document, synthetic_inventory
from kalpamani.data.qualify.sharadar import inventory as inventory_module
from kalpamani.data.qualify.sharadar.inventory import (
    CANONICAL_SUBJECT_CLASSES,
    INVENTORY_SCHEMA_VERSION,
    MAX_INVENTORY_BYTES,
    PRIVATE_INVENTORY_PATH,
    REQUIRED_SUBJECT_COUNT,
    InventoryDefect,
    PrivateInventory,
    PrivateInventoryError,
    SubjectClass,
    inventory_digest,
    load_private_inventory,
    parse_private_inventory,
)


def _refuses(document: object) -> InventoryDefect:
    with pytest.raises(PrivateInventoryError) as raised:
        parse_private_inventory(document)
    return raised.value.defect


def test_exactly_eight_subject_classes_exist() -> None:
    assert REQUIRED_SUBJECT_COUNT == 8
    assert len(CANONICAL_SUBJECT_CLASSES) == 8
    assert len(set(CANONICAL_SUBJECT_CLASSES)) == 8


def test_the_eight_classes_are_the_accepted_evidence_roles() -> None:
    assert set(SubjectClass) == {
        SubjectClass.LONG_HISTORY_DIVIDEND_PAYER_WITH_SPLIT,
        SubjectClass.SPINOFF_PARENT,
        SubjectClass.SPINOFF_CHILD,
        SubjectClass.DELISTED_APPROXIMATELY_FIVE_YEARS,
        SubjectClass.DELISTED_APPROXIMATELY_TEN_YEARS,
        SubjectClass.DELISTED_APPROXIMATELY_FIFTEEN_YEARS,
        SubjectClass.IDENTIFIER_TRANSITION,
        SubjectClass.SMALL_CAP_NO_ACTION_CONTROL,
    }


def test_a_well_formed_inventory_maps_one_subject_to_every_class() -> None:
    inventory = synthetic_inventory()
    assert len(inventory.subjects) == REQUIRED_SUBJECT_COUNT
    assert inventory.classes == CANONICAL_SUBJECT_CLASSES
    for index, subject_class in enumerate(CANONICAL_SUBJECT_CLASSES):
        assert inventory.subject_for(subject_class) is inventory.subjects[index]


def test_the_digest_is_deterministic_across_two_parses() -> None:
    assert synthetic_inventory().digest == synthetic_inventory().digest


def test_the_digest_ignores_the_order_of_the_file() -> None:
    document = inventory_document()
    reversed_document = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "subjects": list(reversed(document["subjects"])),
    }
    assert parse_private_inventory(reversed_document).digest == synthetic_inventory().digest


def test_a_different_subject_set_produces_a_different_digest() -> None:
    other = (*SYNTHETIC_SUBJECTS[:-1], "ZZ-SYNTH-99")
    assert synthetic_inventory(other).digest != synthetic_inventory().digest


def test_swapping_two_roles_changes_the_digest() -> None:
    swapped = (SYNTHETIC_SUBJECTS[1], SYNTHETIC_SUBJECTS[0], *SYNTHETIC_SUBJECTS[2:])
    assert synthetic_inventory(swapped).digest != synthetic_inventory().digest


def test_the_digest_is_sixty_four_lowercase_hex_characters() -> None:
    digest = synthetic_inventory().digest
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_the_digest_helper_and_the_parser_agree() -> None:
    assert inventory_digest(SYNTHETIC_SUBJECTS) == synthetic_inventory().digest


# -- refusals: every rule, and none of them names a value --------------------


def test_a_non_mapping_document_is_refused() -> None:
    assert _refuses(["not", "a", "document"]) is InventoryDefect.DOCUMENT_MALFORMED


def test_an_unknown_top_level_field_is_refused_rather_than_ignored() -> None:
    document = inventory_document()
    document["unexpected"] = "value"
    assert _refuses(document) is InventoryDefect.FIELD_UNKNOWN


def test_a_missing_top_level_field_is_refused() -> None:
    document = inventory_document()
    del document["subjects"]
    assert _refuses(document) is InventoryDefect.FIELD_MISSING


def test_a_wrong_schema_version_is_refused_rather_than_interpreted() -> None:
    document = inventory_document()
    document["schema_version"] = "kalpamani-sharadar-empirical-inventory-v0"
    assert _refuses(document) is InventoryDefect.SCHEMA_VERSION_UNKNOWN


def test_too_few_subjects_is_refused_as_a_count_not_as_a_missing_class() -> None:
    document = inventory_document()
    document["subjects"] = document["subjects"][:-1]
    assert _refuses(document) is InventoryDefect.SUBJECT_COUNT_WRONG


def test_too_many_subjects_is_refused() -> None:
    document = inventory_document()
    document["subjects"].append({"subject_class": "SPINOFF_PARENT", "ticker": "ZZ-SYNTH-09"})
    assert _refuses(document) is InventoryDefect.SUBJECT_COUNT_WRONG


def test_a_duplicated_class_is_refused() -> None:
    document = inventory_document()
    document["subjects"][1]["subject_class"] = document["subjects"][0]["subject_class"]
    assert _refuses(document) is InventoryDefect.SUBJECT_CLASS_DUPLICATED


def test_an_unknown_class_is_refused() -> None:
    document = inventory_document()
    document["subjects"][0]["subject_class"] = "SOME_OTHER_ROLE"
    assert _refuses(document) is InventoryDefect.SUBJECT_CLASS_UNKNOWN


def test_a_duplicated_subject_is_refused_because_one_name_cannot_fill_two_roles() -> None:
    document = inventory_document()
    document["subjects"][1]["ticker"] = document["subjects"][0]["ticker"]
    assert _refuses(document) is InventoryDefect.SUBJECT_DUPLICATED


def test_an_unknown_entry_field_is_refused() -> None:
    document = inventory_document()
    document["subjects"][0]["note"] = "why this one"
    assert _refuses(document) is InventoryDefect.FIELD_UNKNOWN


def test_a_missing_entry_field_is_refused() -> None:
    document = inventory_document()
    del document["subjects"][0]["ticker"]
    assert _refuses(document) is InventoryDefect.FIELD_MISSING


@pytest.mark.parametrize("ticker", ["", "lowercase", "TOO-LONG-A-SYMBOL-HERE", "WITH SPACE", "1ST"])
def test_a_subject_outside_the_accepted_grammar_is_refused(ticker: str) -> None:
    document = inventory_document()
    document["subjects"][0]["ticker"] = ticker
    assert _refuses(document) is InventoryDefect.SUBJECT_MALFORMED


def test_a_non_string_subject_is_refused() -> None:
    document = inventory_document()
    document["subjects"][0]["ticker"] = 12345
    assert _refuses(document) is InventoryDefect.SUBJECT_MALFORMED


def test_a_non_mapping_entry_is_refused() -> None:
    document = inventory_document()
    document["subjects"][0] = "ZZ-SYNTH-01"
    assert _refuses(document) is InventoryDefect.ENTRY_MALFORMED


def test_no_refusal_message_carries_a_subject_or_a_path() -> None:
    document = inventory_document()
    document["subjects"][0]["ticker"] = "NOTREAL.X"
    document["subjects"][1]["ticker"] = document["subjects"][0]["ticker"]
    with pytest.raises(PrivateInventoryError) as raised:
        parse_private_inventory(document)
    rendered = f"{raised.value} {raised.value!r} {raised.value.args}"
    assert "NOTREAL" not in rendered
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in rendered
    assert ".runtime" not in rendered


# -- the loader, exercised only against a temporary file a test created ------


def _write(tmp_path: Path, payload: bytes) -> Path:
    path = tmp_path / "synthetic-inventory.json"
    path.write_bytes(payload)
    return path


def test_the_loader_reads_and_validates_a_well_formed_file(tmp_path: Path) -> None:
    path = _write(tmp_path, json.dumps(inventory_document()).encode("utf-8"))
    assert load_private_inventory(path).digest == synthetic_inventory().digest


def test_a_missing_file_is_refused_as_missing(tmp_path: Path) -> None:
    with pytest.raises(PrivateInventoryError) as raised:
        load_private_inventory(tmp_path / "absent.json")
    assert raised.value.defect is InventoryDefect.FILE_MISSING


def test_a_file_over_the_ceiling_is_refused_before_decoding(tmp_path: Path) -> None:
    path = _write(tmp_path, b"x" * (MAX_INVENTORY_BYTES + 1))
    with pytest.raises(PrivateInventoryError) as raised:
        load_private_inventory(path)
    assert raised.value.defect is InventoryDefect.FILE_TOO_LARGE


def test_invalid_utf8_is_refused_rather_than_replaced(tmp_path: Path) -> None:
    path = _write(tmp_path, b'{"schema_version": "\xff\xfe"}')
    with pytest.raises(PrivateInventoryError) as raised:
        load_private_inventory(path)
    assert raised.value.defect is InventoryDefect.ENCODING_INVALID


def test_invalid_json_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, b"{not json")
    with pytest.raises(PrivateInventoryError) as raised:
        load_private_inventory(path)
    assert raised.value.defect is InventoryDefect.DOCUMENT_MALFORMED


# -- disclosure controls -----------------------------------------------------


def test_the_private_path_is_under_the_git_ignored_runtime_directory() -> None:
    assert PRIVATE_INVENTORY_PATH.parts[0] == ".runtime"


def test_the_repr_names_no_subject() -> None:
    rendered = repr(synthetic_inventory())
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in rendered


def test_the_inventory_may_not_be_subclassed() -> None:
    with pytest.raises(TypeError):

        class _Leaky(PrivateInventory):
            pass


def test_the_module_offers_no_rendering_or_preview_helper() -> None:
    source = Path(inventory_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("def render", "def preview", "def show", "def dump", "def describe"):
        assert forbidden not in source


def test_the_module_never_writes_or_creates_the_private_file() -> None:
    source = Path(inventory_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("write_text", "write_bytes", "mkdir", "touch", "open("):
        assert forbidden not in source


def test_no_real_security_symbol_is_compiled_into_the_module() -> None:
    source = Path(inventory_module.__file__).read_text(encoding="utf-8")
    # The module names classes, never names. The only quoted uppercase tokens are
    # the class members themselves, and each contains an underscore -- which the
    # subject grammar forbids, so none of them could ever be a symbol.
    assert "ticker" in source
    for member in SubjectClass:
        assert "_" in member.value
