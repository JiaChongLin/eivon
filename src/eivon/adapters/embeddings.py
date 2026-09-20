"""Bounded embedding providers used by the workspace knowledge index."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

import httpx

from eivon.core.contracts import EmbeddingSpec

from .network import check_destination


class EmbeddingUnavailable(RuntimeError):
    """The configured embedding provider could not produce a safe response."""


def local_embedding(value: str, dimensions: int = 96) -> list[float]:
    """Stable feature hashing baseline for offline and deterministic installations."""
    vector = [0.0] * dimensions
    tokens = re.findall(r"[\w\u4e00-\u9fff]{2,}", value.lower())
    features = tokens + [value.lower()[i : i + 3] for i in range(max(0, len(value) - 2))]
    for feature in features:
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vector[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(item * item for item in vector)) or 1.0
    return [round(item / norm, 8) for item in vector]


def _validate_vector(value: Any, dimensions: int) -> list[float]:
    if not isinstance(value, list) or len(value) != dimensions:
        raise EmbeddingUnavailable("Embedding provider returned an unexpected vector dimension")
    if any(not isinstance(item, (int, float)) or not math.isfinite(item) for item in value):
        raise EmbeddingUnavailable("Embedding provider returned a non-finite vector")
    return [float(item) for item in value]


def embed(
    spec: EmbeddingSpec,
    credential: str | None,
    allowed_hosts: tuple[str, ...],
    texts: list[str],
) -> list[list[float]]:
    if not texts or len(texts) > 500:
        raise EmbeddingUnavailable("Embedding batches must contain 1 to 500 texts")
    if spec.provider == "local":
        return [local_embedding(text, spec.dimensions) for text in texts]
    url = check_destination(spec.base_url.rstrip("/") + "/embeddings", allowed_hosts)
    headers = {"Content-Type": "application/json"}
    if credential:
        headers["Authorization"] = "Bearer " + credential
    try:
        with httpx.Client(timeout=spec.timeout_seconds, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                url,
                headers=headers,
                json={"model": spec.model, "input": texts, "encoding_format": "float"},
            )
            response.raise_for_status()
            if len(response.content) > 8_000_000:
                raise EmbeddingUnavailable("Embedding response exceeds 8 MB")
            payload = response.json()
    except EmbeddingUnavailable:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise EmbeddingUnavailable("Embedding provider request failed") from exc
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != len(texts):
        raise EmbeddingUnavailable("Embedding provider returned an invalid data array")
    try:
        rows = sorted(rows, key=lambda row: int(row["index"]))
        return [_validate_vector(row["embedding"], spec.dimensions) for row in rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise EmbeddingUnavailable("Embedding provider returned invalid vectors") from exc
