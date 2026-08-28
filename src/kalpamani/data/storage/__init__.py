"""Storage backends: the local analytical store, and the licensed S3 object store.

Two backends with deliberately different jobs, and the split is what keeps the
AWS SDK out of everything that does not need it.

``local``
    The Silver/Gold analytical store from the A1 kernel -- newline-delimited
    canonical JSON on a filesystem, atomic publication by directory rename. It
    is re-exported here unchanged, so ``from kalpamani.data.storage import
    LocalTableStore`` means exactly what it always did.
``s3``
    :class:`~kalpamani.data.storage.s3.S3ResearchObjectStore`, the LICENSED-only
    implementation of :class:`~kalpamani.data.objectstore.ResearchObjectStore`.

**``s3`` is deliberately not re-exported here.** Importing
``kalpamani.data.storage`` must not drag in the AWS SDK, and the neutral Bronze
publisher and every provider adapter depend on the ``ResearchObjectStore``
*protocol* rather than on any backend. A caller that genuinely needs the S3
implementation names it: ``from kalpamani.data.storage.s3 import
S3ResearchObjectStore``. That import is a decision, and it should read like one.

**Nothing here opens a socket, reads a file or contacts a cloud at import time**,
and a static test proves that only ``s3`` may name the AWS SDK at all.
"""

from kalpamani.data.storage.local import (
    DEFAULT_DATA_ROOT,
    STAGING_PREFIX,
    LocalTableStore,
    Row,
    TableArtifact,
)

__all__ = [
    "DEFAULT_DATA_ROOT",
    "STAGING_PREFIX",
    "LocalTableStore",
    "Row",
    "TableArtifact",
]
