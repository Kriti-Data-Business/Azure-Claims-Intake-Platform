"""Vector retrieval over a pack's knowledge base (the RAG step).

`VectorIndex` is a small in-memory cosine index behind an Embedder interface:
- HashingEmbedder: offline and deterministic (hashed word and character n-grams). It matches
  wording, not meaning, so it is for tests and local runs.
- AzureOpenAIEmbedder: real semantic embeddings from an Azure OpenAI embedding deployment.
Not built: Azure AI Search or another managed index. The interface is what such an adapter
would implement; today the index lives in process memory and is rebuilt from the pack on start.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Callable, Protocol

from engine.llm import JsonHttp, LLMError
from engine.pack import Pack


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class HashingEmbedder:
    def __init__(self, dim: int = 512):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            words = re.findall(r"[a-z0-9]+", t.lower())
            feats = words + [w[i:i + 4] for w in words if len(w) > 4 for i in range(len(w) - 3)]
            for f in feats:
                h = int(hashlib.md5(f.encode()).hexdigest(), 16)
                v[h % self.dim] += 1.0
            out.append(_norm(v))
        return out


class AzureOpenAIEmbedder:
    def __init__(self, endpoint: str, deployment: str, api_key: str, api_version: str = "2024-02-01",
                 http: JsonHttp | None = None):
        self.url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/embeddings?api-version={api_version}"
        self.api_key, self.http = api_key, http or JsonHttp()

    def embed(self, texts: list[str]) -> list[list[float]]:
        data = self.http.post(self.url, {"api-key": self.api_key}, {"input": texts})
        try:
            rows = sorted(data["data"], key=lambda r: r["index"])
            if len(rows) != len(texts):
                raise LLMError("embedding count mismatch")
            return [_norm(r["embedding"]) for r in rows]
        except (KeyError, TypeError) as e:
            raise LLMError("unusable embeddings response") from e


class VectorIndex:
    def __init__(self, embedder: Embedder):
        self.embedder, self.docs, self.vecs = embedder, [], []

    def add(self, docs: list[str]) -> None:
        self.vecs += self.embedder.embed(docs)
        self.docs += docs

    def search(self, query: str, k: int = 2, min_score: float = 0.15) -> list[tuple[float, str]]:
        q = self.embedder.embed([query])[0]
        scored = sorted(((sum(a * b for a, b in zip(q, v)), d) for v, d in zip(self.vecs, self.docs)), reverse=True)
        return [(round(s, 3), d) for s, d in scored[:k] if s >= min_score]


def vector_retriever(embedder: Embedder, k: int = 2, min_score: float = 0.15) -> Callable[[str, Pack], list[str]]:
    """Returns a retriever(text, pack) -> list[str] for engine.pipeline.run. Indexes each pack once."""
    cache: dict[str, VectorIndex] = {}

    def retrieve(text: str, pack: Pack) -> list[str]:
        if pack.domain not in cache:
            idx = VectorIndex(embedder)
            idx.add(pack.knowledge)
            cache[pack.domain] = idx
        return [d for _, d in cache[pack.domain].search(text, k, min_score)]

    return retrieve
