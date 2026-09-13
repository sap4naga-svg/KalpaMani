"""Grammars shared by the task metadata self-check, the release and the launch tool.

Kept in a module of their own so the release contract can name the image-digest grammar
without importing the self-check, and the self-check can import the release's task-ARN
grammar without a cycle. Values only; no behaviour.
"""

from __future__ import annotations

import re
from typing import Final

#: An image digest as ECS reports it: ``sha256:`` and 64 lowercase hex.
IMAGE_DIGEST_RE: Final = re.compile(r"sha256:[0-9a-f]{64}")

#: A Git commit object name, and a SHA-256 digest: lowercase hex, fixed length.
CODE_COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}")
CONFIGURATION_DIGEST_RE: Final = re.compile(r"[0-9a-f]{64}")

__all__ = ["CODE_COMMIT_RE", "CONFIGURATION_DIGEST_RE", "IMAGE_DIGEST_RE"]
