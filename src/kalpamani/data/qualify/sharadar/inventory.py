"""The owner-only private subject inventory, and the digest that binds it.

**Which securities the owner chose to evaluate is evaluation information.** The
Sharadar Personal Use License bars disclosing fitness conclusions (ADR-0008), and
a subject list is one: it says what the owner thought worth testing. Decision 9 of
the accepted architecture therefore keeps concrete names out of Git, documentation,
command arguments and public output entirely, and this module is the boundary that
makes that structural.

**Eight classes, one name each, supplied out of band.** The classes are compiled
in -- they are the design, derived from what P1-P9 need -- and the *names* arrive
from a deterministic, git-ignored path the application fixes. The path is not a
command-line argument: an argument would put a private path in shell history and
in every process listing, which is the same defect that keeps the secret
identifier out of ``argv``.

**Nothing here prints, previews, enumerates or summarises the inventory.** There
is no rendering function, no ``__repr__`` carrying tickers and no "show what was
loaded" option, because a diagnostic that exists is a diagnostic somebody runs.
What leaves this module is a validated in-memory structure and a digest.

**The digest binds without disclosing.** It is the SHA-256 of the canonical
rendering of the *validated, normalised* inventory, so a report can prove which
inventory produced it, two runs can be shown to have used the same one, and
neither the report nor the locator has to carry a name. The digest is LICENSED
material like everything else derived from the inventory: it may enter the
private locator and the private report, and it may never enter public output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.ingest.sharadar.qualification import QualificationSubject


class SubjectClass(StrEnum):
    """The eight evidence roles the accepted design requires, as classes not names.

    Each exists because a specific P-test needs it, and the set is closed: a ninth
    class would be a ninth subject, and eight is the compiled subject ceiling the
    plan model already enforces.

    The parent and child spinoff classes exist as a pair because the published
    spinoff ratio needs the spun-off entity's own opening price -- a single subject
    can never reach that limb. The three delisting cohorts are one name each, which
    is exactly why P2 ceilings at existence rather than at a population claim.
    """

    LONG_HISTORY_DIVIDEND_PAYER_WITH_SPLIT = "LONG_HISTORY_DIVIDEND_PAYER_WITH_SPLIT"
    SPINOFF_PARENT = "SPINOFF_PARENT"
    SPINOFF_CHILD = "SPINOFF_CHILD"
    DELISTED_APPROXIMATELY_FIVE_YEARS = "DELISTED_APPROXIMATELY_FIVE_YEARS"
    DELISTED_APPROXIMATELY_TEN_YEARS = "DELISTED_APPROXIMATELY_TEN_YEARS"
    DELISTED_APPROXIMATELY_FIFTEEN_YEARS = "DELISTED_APPROXIMATELY_FIFTEEN_YEARS"
    IDENTIFIER_TRANSITION = "IDENTIFIER_TRANSITION"
    SMALL_CAP_NO_ACTION_CONTROL = "SMALL_CAP_NO_ACTION_CONTROL"


#: The eight classes in one fixed order. Canonical, so two loads of one file
#: normalise identically and produce the same digest regardless of file order.
CANONICAL_SUBJECT_CLASSES: Final[tuple[SubjectClass, ...]] = tuple(SubjectClass)

#: Exactly eight. Stated as a constant so the arithmetic that produces 48 requests
#: reads from one place rather than from a literal in three modules.
REQUIRED_SUBJECT_COUNT: Final = len(CANONICAL_SUBJECT_CLASSES)

#: The deterministic, application-fixed location of the owner-only input.
#:
#: Under ``.runtime/``, which is git-ignored in its entirety and holds every
#: sensitive operational artifact. **This module never creates it**, never creates
#: its parents and never writes to it -- it is the owner's file, and a tool that
#: would helpfully scaffold one is a tool that invites a placeholder to be mistaken
#: for a decision.
PRIVATE_INVENTORY_PATH: Final = (
    Path(".runtime") / "phase3" / "sharadar" / "empirical-inventory.json"
)

#: The one schema version this loader accepts. An exact match, not a minimum: a
#: file written for a different shape is refused rather than interpreted.
INVENTORY_SCHEMA_VERSION: Final = "kalpamani-sharadar-empirical-inventory-v1"

#: Largest private input this loader will read, in bytes. An inventory of eight
#: short records is on the order of a kilobyte; the ceiling exists so a wrong path
#: cannot make the loader read something enormous before refusing it.
MAX_INVENTORY_BYTES: Final = 64 * 1024


class InventoryDefect(StrEnum):
    """Why a private inventory was refused. A closed, structural vocabulary.

    **No member can carry a value**, which is the point: a refusal that quoted the
    offending entry would print a ticker, and the whole reason this file is private
    is that its contents must not be printed. Every member names a rule, and the
    owner reads their own file to see which entry broke it.
    """

    FILE_MISSING = "FILE_MISSING"
    FILE_UNREADABLE = "FILE_UNREADABLE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    ENCODING_INVALID = "ENCODING_INVALID"
    DOCUMENT_MALFORMED = "DOCUMENT_MALFORMED"
    SCHEMA_VERSION_UNKNOWN = "SCHEMA_VERSION_UNKNOWN"
    FIELD_UNKNOWN = "FIELD_UNKNOWN"
    FIELD_MISSING = "FIELD_MISSING"
    ENTRY_MALFORMED = "ENTRY_MALFORMED"
    SUBJECT_CLASS_UNKNOWN = "SUBJECT_CLASS_UNKNOWN"
    SUBJECT_CLASS_DUPLICATED = "SUBJECT_CLASS_DUPLICATED"
    SUBJECT_CLASS_MISSING = "SUBJECT_CLASS_MISSING"
    SUBJECT_COUNT_WRONG = "SUBJECT_COUNT_WRONG"
    SUBJECT_MALFORMED = "SUBJECT_MALFORMED"
    SUBJECT_DUPLICATED = "SUBJECT_DUPLICATED"


class PrivateInventoryError(Exception):
    """A refusal carrying exactly one :class:`InventoryDefect` and nothing else.

    Raised ``from None`` everywhere. A JSON decoder quotes the offending line, a
    filesystem error quotes the path, and a subject grammar refusal can quote the
    subject -- none of which may reach a traceback somebody pastes into a chat.
    """

    __slots__ = ("defect",)

    def __init__(self, defect: InventoryDefect) -> None:
        """Bind the defect. The message is the member's token, nothing more."""
        if type(defect) is not InventoryDefect:  # pragma: no cover - type guard
            raise TypeError("a defect must be an exact InventoryDefect member")
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: InventoryDefect) -> PrivateInventoryError:
    return PrivateInventoryError(defect)


#: The exact top-level field set. An allowlist: a field nobody anticipated is
#: refused rather than ignored, because an ignored field is a decision that
#: silently did not happen.
_DOCUMENT_FIELDS: Final[frozenset[str]] = frozenset({"schema_version", "subjects"})

#: The exact per-entry field set, same rule.
_ENTRY_FIELDS: Final[frozenset[str]] = frozenset({"subject_class", "ticker"})


@dataclass(frozen=True, slots=True, kw_only=True)
class PrivateInventory:
    """Eight validated subjects, one per class, and the digest that binds them.

    **This object holds private names and is never rendered.** ``__repr__`` is
    overridden to a constant so no logging call, no assertion failure and no
    debugger echo can spill it, and there is no method that returns the names as
    text. The tickers are reachable only as typed
    :class:`~kalpamani.data.ingest.sharadar.qualification.QualificationSubject`
    values, for the plan builder that needs them.
    """

    subjects: tuple[QualificationSubject, ...]
    classes: tuple[SubjectClass, ...]
    digest: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass could give the names a ``__repr__``."""
        raise TypeError("PrivateInventory may not be subclassed")

    def __repr__(self) -> str:
        """A count and a digest prefix. **Never a subject.**

        Safe to log without anyone having to think about it, which is the only kind
        of safe that survives a late-night debugging session.
        """
        return f"PrivateInventory(subjects={len(self.subjects)}, digest={self.digest[:8]}...)"

    def subject_for(self, subject_class: SubjectClass) -> QualificationSubject:
        """The subject filling one class. For the plan builder, not for display."""
        return self.subjects[self.classes.index(subject_class)]


def _entry(raw: object) -> tuple[SubjectClass, str]:
    """One validated ``(class, ticker)`` pair, or a refusal naming only the rule."""
    if type(raw) is not dict:
        raise _refuse(InventoryDefect.ENTRY_MALFORMED) from None
    names = set(raw)
    if names - _ENTRY_FIELDS:
        raise _refuse(InventoryDefect.FIELD_UNKNOWN) from None
    if _ENTRY_FIELDS - names:
        raise _refuse(InventoryDefect.FIELD_MISSING) from None

    raw_class = raw["subject_class"]
    if type(raw_class) is not str:
        raise _refuse(InventoryDefect.ENTRY_MALFORMED) from None
    try:
        subject_class = SubjectClass(raw_class)
    except ValueError:
        raise _refuse(InventoryDefect.SUBJECT_CLASS_UNKNOWN) from None

    ticker = raw["ticker"]
    if type(ticker) is not str:
        raise _refuse(InventoryDefect.SUBJECT_MALFORMED) from None
    try:
        # Validated by the *plan model's own grammar*, imported rather than
        # restated. Two spellings of one rule is how a value this loader admits
        # becomes a value the plan refuses, three stages later and after the
        # identity gate has already passed.
        QualificationSubject(ticker)
    except Exception:
        raise _refuse(InventoryDefect.SUBJECT_MALFORMED) from None
    return subject_class, ticker


def inventory_digest(tickers: tuple[str, ...] | list[str]) -> str:
    """The deterministic digest binding one validated inventory.

    Taken over the canonical rendering of the **class-to-subject mapping in
    canonical class order**, so the digest is a function of the decisions and not
    of how the owner happened to order their file. Two runs eight days apart bind
    to the same value if and only if they evaluated the same eight securities in
    the same eight roles.
    """
    payload: dict[str, Any] = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "subjects": [
            {"subject_class": name.value, "ticker": ticker}
            for name, ticker in zip(CANONICAL_SUBJECT_CLASSES, tickers, strict=True)
        ],
    }
    return sha256_hex(canonical_bytes(payload))


def parse_private_inventory(document: object) -> PrivateInventory:
    """Validate an already-decoded inventory document. **Reads no file.**

    Separated from :func:`load_private_inventory` so every rule below is testable
    with synthetic structures and no filesystem at all -- which is the only way
    this can be tested, since the real file must never exist in a test.

    Raises:
        PrivateInventoryError: for a malformed document, an unknown or missing
            field, a wrong schema version, a wrong entry count, an unknown,
            duplicated or missing class, or a malformed or duplicated subject.
            **The refusal names the rule and never the value.**
    """
    if type(document) is not dict:
        raise _refuse(InventoryDefect.DOCUMENT_MALFORMED) from None
    names = set(document)
    if names - _DOCUMENT_FIELDS:
        raise _refuse(InventoryDefect.FIELD_UNKNOWN) from None
    if _DOCUMENT_FIELDS - names:
        raise _refuse(InventoryDefect.FIELD_MISSING) from None
    if document["schema_version"] != INVENTORY_SCHEMA_VERSION:
        raise _refuse(InventoryDefect.SCHEMA_VERSION_UNKNOWN) from None

    entries = document["subjects"]
    if type(entries) is not list:
        raise _refuse(InventoryDefect.DOCUMENT_MALFORMED) from None
    if len(entries) != REQUIRED_SUBJECT_COUNT:
        # Checked before the per-class accounting so a short or long file says
        # "wrong count" rather than "a class is missing", which would send the
        # owner to look at the wrong thing.
        raise _refuse(InventoryDefect.SUBJECT_COUNT_WRONG) from None

    by_class: dict[SubjectClass, str] = {}
    for raw in entries:
        subject_class, ticker = _entry(raw)
        if subject_class in by_class:
            raise _refuse(InventoryDefect.SUBJECT_CLASS_DUPLICATED) from None
        by_class[subject_class] = ticker

    if [name for name in CANONICAL_SUBJECT_CLASSES if name not in by_class]:
        raise _refuse(InventoryDefect.SUBJECT_CLASS_MISSING) from None

    tickers = [by_class[name] for name in CANONICAL_SUBJECT_CLASSES]
    if len(set(tickers)) != len(tickers):
        # One security cannot fill two evidence roles: the spinoff parent and
        # child limb needs two distinct entities, and a repeated name would make
        # the plan refuse for duplicate subjects several stages later.
        raise _refuse(InventoryDefect.SUBJECT_DUPLICATED) from None

    return PrivateInventory(
        subjects=tuple(QualificationSubject(ticker) for ticker in tickers),
        classes=CANONICAL_SUBJECT_CLASSES,
        digest=inventory_digest(tickers),
    )


def load_private_inventory(path: Path = PRIVATE_INVENTORY_PATH) -> PrivateInventory:
    """Read and validate the owner-only inventory from the fixed private path.

    ``path`` is a parameter **for tests only**, and the production callers pass
    nothing: the default is the application-fixed location, and no entry point
    exposes an option that could supply a different one.

    **Strict UTF-8, and a size ceiling checked before decoding.** A replacement
    character in a private input is silent corruption of the thing every later
    digest is taken over.

    Raises:
        PrivateInventoryError: if the file is missing, unreadable, over the
            ceiling, not valid UTF-8, not valid JSON, or refused by
            :func:`parse_private_inventory`. **No refusal names the path, the
            offending line or any subject.**
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise _refuse(InventoryDefect.FILE_MISSING) from None
    except OSError:
        raise _refuse(InventoryDefect.FILE_UNREADABLE) from None
    if len(raw) > MAX_INVENTORY_BYTES:
        raise _refuse(InventoryDefect.FILE_TOO_LARGE) from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse(InventoryDefect.ENCODING_INVALID) from None
    try:
        document = json.loads(text)
    except Exception:
        raise _refuse(InventoryDefect.DOCUMENT_MALFORMED) from None
    return parse_private_inventory(document)


__all__ = [
    "CANONICAL_SUBJECT_CLASSES",
    "INVENTORY_SCHEMA_VERSION",
    "MAX_INVENTORY_BYTES",
    "PRIVATE_INVENTORY_PATH",
    "REQUIRED_SUBJECT_COUNT",
    "InventoryDefect",
    "PrivateInventory",
    "PrivateInventoryError",
    "SubjectClass",
    "inventory_digest",
    "load_private_inventory",
    "parse_private_inventory",
]
