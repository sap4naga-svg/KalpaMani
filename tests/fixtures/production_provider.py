"""A coordinate-answering scripted transport for the production provider adapter.

The transport answers each GET by **decoding the URL the adapter built** -- dataset
from the path, ``from``/``to``/``skip``/``limit``/``format`` from the query -- so a test
that receives the right bytes has proved the adapter encoded the compiled coordinates,
not merely that a fake was handed them. Every call is recorded (URL, headers, timeout);
failures are scripted per coordinate. It holds no host, opens no socket and resolves
no name.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

from kalpamani.data.ingest.sharadar.datasets import API_BASE_URL
from kalpamani.data.ingest.sharadar.transport import (
    DEFAULT_MAX_RESPONSE_BYTES,
    TransportResponse,
    TransportUnavailableError,
)

Coordinate = tuple[str, str, int]


def coordinate_of(url: str) -> tuple[Coordinate, dict[str, list[str]]]:
    """``(dataset, window, skip)`` and the full query of one adapter-built URL."""
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}".startswith(API_BASE_URL + "/")
    dataset = parts.path.rsplit("/", 1)[1]
    query = parse_qs(parts.query, keep_blank_values=True)
    if "from" in query or "to" in query:
        window = f"{query['from'][0]}/{query['to'][0]}"
    else:
        window = "SNAPSHOT"
    return (dataset, window, int(query["skip"][0])), query


@dataclass
class CoordinateTransport:
    """Answers by decoded coordinate; records every invocation; scripts failures."""

    responses: dict[Coordinate, bytes]
    failures: dict[Coordinate, TransportUnavailableError | TransportResponse | Any] = field(
        default_factory=dict
    )
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    urls: list[str] = field(default_factory=list)
    headers: list[Mapping[str, str]] = field(default_factory=list)
    timeouts: list[float] = field(default_factory=list)
    coordinates: list[Coordinate] = field(default_factory=list)
    queries: list[dict[str, list[str]]] = field(default_factory=list)

    @property
    def call_count(self) -> int:
        return len(self.urls)

    def get(self, *, url: str, headers: Mapping[str, str], timeout_seconds: float) -> Any:
        self.urls.append(url)
        self.headers.append(dict(headers))
        self.timeouts.append(timeout_seconds)
        coordinate, query = coordinate_of(url)
        self.coordinates.append(coordinate)
        self.queries.append(query)
        if coordinate in self.failures:
            outcome = self.failures[coordinate]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return TransportResponse(status=200, body=self.responses[coordinate])


__all__ = ["CoordinateTransport", "coordinate_of"]
