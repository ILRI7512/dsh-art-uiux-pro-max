"""向量化适配器。

三种实现：
- ``HashingEmbedder``：纯本地特征哈希。默认实现，零依赖、确定性、离线可用。
  用词元（含中文二元组）做带符号特征哈希 + 次线性词频 + L2 归一化。
  它不是神经网络语义模型，但能提供稳定的词汇级语义召回，并且完全可测。
- ``OpenAIEmbedder``：OpenAI 兼容 ``/embeddings`` 接口，需要配置 base_url 与密钥环境变量。
- ``SentenceTransformerEmbedder``：本地模型（可选依赖，未安装时明确报错，不静默降级）。

重要：索引清单里记录 embedder id 与维度，换模型必须显式重建索引，
避免"同一集合里混着不同语义空间"的静默错误。
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np

from ..config import ConfigError, EmbeddingConfig
from ..storage.tokenizer import tokenize


class EmbeddingError(RuntimeError):
    """向量化失败。"""


class BaseEmbedder:
    """向量化接口。"""

    provider: str = "base"
    dim: int = 0
    model: str = ""

    @property
    def embedder_id(self) -> str:
        return f"{self.provider}:{self.model or 'default'}:{self.dim}"

    def embed(self, texts: Sequence[str]) -> np.ndarray:  # pragma: no cover - 抽象
        raise NotImplementedError

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    @staticmethod
    def _normalize(matrix: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms


class HashingEmbedder(BaseEmbedder):
    """带符号特征哈希向量化（确定性、离线）。"""

    provider = "hashing"

    def __init__(self, dim: int = 512, model: str = "hashed-ngram") -> None:
        if dim <= 0:
            raise EmbeddingError("向量维度必须为正")
        self.dim = int(dim)
        self.model = model

    def _hash(self, token: str) -> tuple[int, float]:
        digest = hashlib.blake2b(token.encode("utf-8", errors="replace"), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        index = value % self.dim
        sign = 1.0 if (value >> 63) & 1 else -1.0
        return index, sign

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not isinstance(texts, (list, tuple)):
            texts = [texts]  # type: ignore[list-item]
        matrix = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = tokenize(text or "")
            if not tokens:
                continue
            counts: Dict[str, int] = {}
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
            for token, count in counts.items():
                index, sign = self._hash(token)
                weight = 1.0 + math.log(count)  # 次线性词频
                matrix[row, index] += sign * weight
        return self._normalize(matrix)

    def describe(self) -> Dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "dim": self.dim,
            "note": "本地特征哈希，非神经网络语义模型；可在离线环境确定性复现",
        }


class OpenAIEmbedder(BaseEmbedder):
    """OpenAI 兼容 embeddings 接口。"""

    provider = "openai"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: str = "DSH_AL_EMBEDDING_API_KEY",
        dim: int = 0,
        timeout_s: int = 30,
        batch_size: int = 32,
    ) -> None:
        import os

        self.base_url = base_url.rstrip("/")
        self.model = model or "text-embedding-3-small"
        self.api_key_env = api_key_env
        self._api_key = os.environ.get(api_key_env, "")
        if not self._api_key:
            raise EmbeddingError(
                f"embedding.provider=openai 但环境变量 {api_key_env} 未设置（密钥不得写入配置文件）"
            )
        self.dim = int(dim)
        self.timeout_s = timeout_s
        self.batch_size = max(1, batch_size)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        import httpx

        texts = list(texts)
        if not texts:
            return np.zeros((0, self.dim or 0), dtype=np.float32)
        chunks: List[np.ndarray] = []
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=self.timeout_s) as client:
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i : i + self.batch_size]
                payload = {"model": self.model, "input": batch}
                last_error = ""
                for attempt in range(3):
                    try:
                        resp = client.post(f"{self.base_url}/embeddings", json=payload, headers=headers)
                        if resp.status_code >= 400:
                            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                            if resp.status_code in (429, 500, 502, 503, 504):
                                time.sleep(0.5 * (attempt + 1))
                                continue
                            raise EmbeddingError(last_error)
                        data = resp.json()
                        vectors = [item["embedding"] for item in data["data"]]
                        arr = np.asarray(vectors, dtype=np.float32)
                        chunks.append(arr)
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_error = str(exc)
                        if attempt == 2:
                            raise EmbeddingError(f"向量化失败: {last_error}") from exc
                        time.sleep(0.5 * (attempt + 1))
        matrix = np.vstack(chunks) if chunks else np.zeros((0, self.dim or 0), dtype=np.float32)
        if not self.dim:
            self.dim = int(matrix.shape[1])
        elif matrix.shape[1] != self.dim:
            raise EmbeddingError(
                f"向量维度与索引不一致: 返回 {matrix.shape[1]}，索引要求 {self.dim}"
            )
        return self._normalize(matrix).astype(np.float32)

    def describe(self) -> Dict[str, object]:
        return {"provider": self.provider, "model": self.model, "dim": self.dim}


class SentenceTransformerEmbedder(BaseEmbedder):
    """本地 sentence-transformers 模型（可选依赖）。"""

    provider = "sentence_transformers"

    def __init__(self, model: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:  # pragma: no cover - 依赖缺失路径
            raise EmbeddingError(
                "未安装 sentence-transformers；请先 pip install sentence-transformers，"
                "或改用 embedding.provider=hashing"
            ) from exc
        self.model = model or "paraphrase-multilingual-MiniLM-L12-v2"
        self._model = SentenceTransformer(self.model)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        vecs = self._model.encode(list(texts), normalize_embeddings=True)
        return np.asarray(vecs, dtype=np.float32)

    def describe(self) -> Dict[str, object]:
        return {"provider": self.provider, "model": self.model, "dim": self.dim}


def build_embedder(cfg: EmbeddingConfig) -> BaseEmbedder:
    """按配置构造向量化器，失败时抛出明确错误而不是静默降级。"""

    provider = cfg.provider
    if provider == "hashing":
        return HashingEmbedder(dim=cfg.dim, model=cfg.model or "hashed-ngram")
    if provider == "openai":
        if not cfg.base_url:
            raise ConfigError("embedding.provider=openai 需要 base_url")
        return OpenAIEmbedder(
            base_url=cfg.base_url,
            model=cfg.model,
            api_key_env=cfg.api_key_env,
            dim=cfg.dim,
            timeout_s=cfg.timeout_s,
            batch_size=cfg.batch_size,
        )
    if provider == "sentence_transformers":
        return SentenceTransformerEmbedder(cfg.model)
    raise ConfigError(f"未知 embedding.provider: {provider}")


__all__ = [
    "BaseEmbedder",
    "EmbeddingError",
    "HashingEmbedder",
    "OpenAIEmbedder",
    "SentenceTransformerEmbedder",
    "build_embedder",
]
