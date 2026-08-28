"""Sharadar provider integration -- **code only. No request has ever been sent.**

Authorized by
[ADR-0009](../../../../../docs/decisions/ADR-0009-sharadar-provider-realistic-implementation.md)
as the first provider-realistic Phase-3A slice. What that authorization covers,
and what it explicitly does not, is worth restating where the code lives:

.. code-block:: text

    authorized     provider-specific code, deterministic request construction,
                   credential-injection interfaces, redaction, pacing, retries,
                   Bronze publication mechanics, synthetic tests

    NOT authorized subscription, purchase, provider account, private credential,
                   any API call, Services Data, production ingestion, AWS mutation

``G1`` -- provider selection -- is **OPEN**. Sharadar being the implementation
target is not Sharadar being the production provider: the pre-purchase questions
Q7 (are the daily bars officially disseminated or provider-aggregated?) and Q8
(what depth does the Full History tier actually deliver, per table?) are both
still unanswered by public documentation, and both must be answered before any
purchase.

**The boundaries this package keeps.**

``credentials``
    No key value exists anywhere under ``src/`` -- not a private one, and not the
    vendor's published test token either. A credential is injected, renders as a
    placeholder, and is reachable only through ``reveal()``.
``redaction``
    Errors are assembled from closed vocabularies. A URL, a query string and a
    response body have no parameter to arrive through.
``datasets``
    Three Stage-3A tables, explicit windows, explicit pagination, and no
    constructible table-wide bulk download.
``transport``
    The only network-capable code here. Pinned by parsing to exactly one origin,
    with redirects refused, ambient proxy discovery off, and a bounded response
    body. Nothing in the repository constructs it outside its own synthetic unit
    test, and importing this package opens no socket.
``bronze``
    Translation into the vendor-neutral publisher, which owns every storage rule.

Nothing outside this package may import it. The point-in-time kernel stays
vendor-neutral, and research, strategy, risk and portfolio code may not reach the
ingest layer at all -- both enforced by static tests, not by convention.
"""

from kalpamani.data.ingest.sharadar.bronze import (
    publish_sharadar_payload,
    sharadar_retrieval_metadata,
)
from kalpamani.data.ingest.sharadar.client import (
    DEFAULT_RETRY_POLICY,
    DEFAULT_USER_AGENT,
    Pacer,
    RetryPolicy,
    SharadarClient,
)
from kalpamani.data.ingest.sharadar.credentials import (
    CREDENTIAL_ENV_VAR,
    CREDENTIAL_PLACEHOLDER,
    SharadarCredential,
    credential_from_env,
)
from kalpamani.data.ingest.sharadar.datasets import (
    API_BASE_URL,
    FORBIDDEN_QUERY_PARAMETERS,
    PROVIDER,
    QUERY_PARAMETER_ALLOWLIST,
    WINDOWED_DATASETS,
    DateWindow,
    Page,
    ResponseFormat,
    SharadarDataset,
    SharadarRequest,
    build_query_parameters,
    build_request_url,
    describe_request,
)
from kalpamani.data.ingest.sharadar.redaction import (
    RETRYABLE_CODES,
    SharadarErrorCode,
    SharadarRequestError,
    SharadarStage,
    classify_http_status,
    redact,
)
from kalpamani.data.ingest.sharadar.transport import (
    DEFAULT_MAX_RESPONSE_BYTES,
    MAX_RESPONSE_BYTES_CEILING,
    SharadarTransport,
    TransportResponse,
    TransportUnavailableError,
    UrllibTransport,
    origin_refusal,
)

__all__ = [
    "API_BASE_URL",
    "CREDENTIAL_ENV_VAR",
    "CREDENTIAL_PLACEHOLDER",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_RETRY_POLICY",
    "DEFAULT_USER_AGENT",
    "FORBIDDEN_QUERY_PARAMETERS",
    "MAX_RESPONSE_BYTES_CEILING",
    "PROVIDER",
    "QUERY_PARAMETER_ALLOWLIST",
    "RETRYABLE_CODES",
    "WINDOWED_DATASETS",
    "DateWindow",
    "Pacer",
    "Page",
    "ResponseFormat",
    "RetryPolicy",
    "SharadarClient",
    "SharadarCredential",
    "SharadarDataset",
    "SharadarErrorCode",
    "SharadarRequest",
    "SharadarRequestError",
    "SharadarStage",
    "SharadarTransport",
    "TransportResponse",
    "TransportUnavailableError",
    "UrllibTransport",
    "build_query_parameters",
    "build_request_url",
    "classify_http_status",
    "credential_from_env",
    "describe_request",
    "origin_refusal",
    "publish_sharadar_payload",
    "redact",
    "sharadar_retrieval_metadata",
]
