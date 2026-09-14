"""Per-dataset schema observations: evidence for owner review, never an accepted set.

**Proposed ADR-0045 (Route B) — not accepted, not in force.** A research build whose accepted
schema set admits nothing (an explicitly empty set per dataset) refuses at normalization with
zero writes; before it refuses, Silver records the header digest of every page it could parse.
That record is what this module shapes: the sorted, distinct digests per dataset, how many pages
of each dataset were parsed and how many there were, and whether the observation is
**complete** — every page of every dataset in the verified inputs parsed and observed — or
**partial**, because a page could not be parsed and its header is therefore unobserved.

**An observed digest is not an accepted one.** Nothing here writes into any accepted set, and
nothing anywhere reads an observation back into a configuration: a later configuration names a
digest only after the owner's explicit acceptance under the applicable gate. The observation
carries digests and integers only — no key, no row, no subject, no identifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.production.sharadar.documents import hex_digest

#: The datasets an observation may name, and must name (an absent dataset is zero pages).
OBSERVED_DATASETS: Final[tuple[str, ...]] = tuple(sorted(m.value for m in SharadarDataset))
#: A ceiling on distinct digests per dataset: a delivery whose headers vary more than
#: this is not one schema being observed, and the block must stay small for the receipt.
MAX_DIGESTS_PER_DATASET: Final = 8


@dataclass(frozen=True, slots=True, kw_only=True)
class DatasetObservation:
    """One dataset's observed header digests and page accounting."""

    digests: tuple[str, ...]
    pages_parsed: int
    pages_total: int

    def __post_init__(self) -> None:
        """Sorted distinct digests, bounded; parsed never exceeds total."""
        if type(self.digests) is not tuple or any(hex_digest(d) is None for d in self.digests):
            raise ValueError("digests must be a tuple of 64-hex digests")
        if list(self.digests) != sorted(set(self.digests)):
            raise ValueError("digests must be sorted and distinct")
        if len(self.digests) > MAX_DIGESTS_PER_DATASET:
            raise ValueError("too many distinct digests for one dataset")
        for name in ("pages_parsed", "pages_total"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.pages_parsed > self.pages_total:
            raise ValueError("pages_parsed cannot exceed pages_total")
        if self.pages_parsed == 0 and self.digests:
            raise ValueError("a digest was observed on a page that was parsed")
        if self.pages_parsed > 0 and not self.digests:
            raise ValueError("a parsed page has a header digest")


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaObservation:
    """The whole observation: every dataset, and whether it is complete."""

    datasets: dict[str, DatasetObservation]

    def __post_init__(self) -> None:
        """Exactly the three datasets, each an exact observation."""
        if type(self.datasets) is not dict or tuple(sorted(self.datasets)) != OBSERVED_DATASETS:
            raise ValueError("an observation names exactly the three datasets")
        if any(type(v) is not DatasetObservation for v in self.datasets.values()):
            raise TypeError("every dataset observation must be exact")

    @property
    def complete(self) -> bool:
        """Every page of every dataset was parsed. A partial observation is labelled so."""
        return all(d.pages_parsed == d.pages_total for d in self.datasets.values())

    @property
    def digest_count(self) -> int:
        """Distinct digests across datasets."""
        return sum(len(d.digests) for d in self.datasets.values())

    def document(self) -> dict[str, Any]:
        """The closed receipt block: digests and integers, in dataset order."""
        return {
            "complete": self.complete,
            "datasets": {
                name: {
                    "digests": list(self.datasets[name].digests),
                    "pages_parsed": self.datasets[name].pages_parsed,
                    "pages_total": self.datasets[name].pages_total,
                }
                for name in OBSERVED_DATASETS
            },
        }

    def __repr__(self) -> str:
        """Completeness and the count only."""
        return f"SchemaObservation(complete={self.complete}, digests={self.digest_count})"


def parse_schema_observation(raw: object) -> SchemaObservation:
    """The closed block back into an observation, or ``ValueError``/``TypeError``.

    ``complete`` is recomputed from the page accounting and must agree with the block;
    a block that claims completeness its own counts contradict is refused.
    """
    if type(raw) is not dict or set(raw) != {"complete", "datasets"}:
        raise ValueError("a schema observation carries exactly complete and datasets")
    if type(raw["complete"]) is not bool:
        raise ValueError("complete must be a bool")
    datasets = raw["datasets"]
    if type(datasets) is not dict or tuple(sorted(datasets)) != OBSERVED_DATASETS:
        raise ValueError("an observation names exactly the three datasets")
    parsed: dict[str, DatasetObservation] = {}
    for name in OBSERVED_DATASETS:
        block = datasets[name]
        if type(block) is not dict or set(block) != {"digests", "pages_parsed", "pages_total"}:
            raise ValueError("a dataset block carries exactly digests, pages_parsed, pages_total")
        digests = block["digests"]
        if type(digests) is not list or any(type(d) is not str for d in digests):
            raise ValueError("digests must be a list of strings")
        if type(block["pages_parsed"]) is not int or type(block["pages_total"]) is not int:
            raise ValueError("page counts must be integers")
        parsed[name] = DatasetObservation(
            digests=tuple(digests),
            pages_parsed=block["pages_parsed"],
            pages_total=block["pages_total"],
        )
    observation = SchemaObservation(datasets=parsed)
    if observation.complete != raw["complete"]:
        raise ValueError("the completeness claim contradicts the page accounting")
    return observation


__all__ = [
    "MAX_DIGESTS_PER_DATASET",
    "OBSERVED_DATASETS",
    "DatasetObservation",
    "SchemaObservation",
    "parse_schema_observation",
]
