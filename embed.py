#!/usr/bin/env python3
"""
Embedding generation module (DashScope compatible-mode / OpenAI-compatible API).
"""

import hashlib
import json
import math
import os
import time
from typing import Dict, List, Optional

import requests


class DashScopeEmbedder:
    def __init__(
        self,
        api_key: Optional[str],
        model: str = "text-embedding-v4",
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("DASHSCOPE_EMBEDDING_API_KEY")
        self.model = model
        self.base_url = (
            base_url
            or os.getenv("DASHSCOPE_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/")
        self.endpoint = f"{self.base_url}/embeddings"

        self.cache_file = os.path.expanduser(
            "~/.openclaw/workspace/tools/hybrid_search/data/embedding_cache.json"
        )
        self.cache = self._load_cache()
        self._dirty = 0

        # Fallback controls: API first, local model after retries exhausted.
        self.enable_local_fallback = (
            os.getenv("HYBRID_EMBED_LOCAL_FALLBACK", "1") != "0"
        )
        self.local_model_name = os.getenv(
            "HYBRID_LOCAL_EMBED_MODEL", "all-MiniLM-L6-v2"
        )
        self._local_embedder = None

        # Degrade mode: if API+local both fail, optionally return deterministic vector.
        self.enable_degrade_vector = (
            os.getenv("HYBRID_EMBED_DEGRADE_VECTOR", "1") != "0"
        )
        self.degrade_dims = int(os.getenv("HYBRID_EMBED_DEGRADE_DIMS", "1024"))

    def _load_cache(self) -> Dict[str, List[float]]:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load embedding cache: {e}")
        return {}

    def _save_cache(self, force: bool = False):
        if not force and self._dirty < 20:
            return
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self.cache, f)
        self._dirty = 0

    def _get_text_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _load_local_embedder(self):
        if self._local_embedder is False:
            return None
        if self._local_embedder is not None:
            return self._local_embedder
        try:
            from embed_local import LocalEmbedder

            self._local_embedder = LocalEmbedder(model_name=self.local_model_name)
            print(f"Local embedder enabled: {self.local_model_name}")
            return self._local_embedder
        except Exception as e:
            print(f"Local embedder unavailable: {e}")
            self._local_embedder = False
            return None

    def _get_local_embedding(self, text: str, text_hash: str) -> Optional[List[float]]:
        embedder = self._load_local_embedder()
        if embedder is None:
            return None
        try:
            embedding = embedder.get_embedding(text)
            if embedding:
                self.cache[text_hash] = embedding
                self._dirty += 1
                self._save_cache()
                return embedding
            return None
        except Exception as e:
            print(f"Local embedding failed: {e}")
            return None

    def _make_degrade_embedding(self, text_hash: str) -> Optional[List[float]]:
        if not self.enable_degrade_vector:
            return None

        dims = max(8, self.degrade_dims)
        raw = hashlib.sha256(text_hash.encode("utf-8")).digest()
        vals: List[float] = []
        i = 0
        while len(vals) < dims:
            b = raw[i % len(raw)]
            vals.append((b / 255.0) * 2.0 - 1.0)
            i += 1
        norm = math.sqrt(sum(v * v for v in vals)) or 1.0
        emb = [v / norm for v in vals]
        print(f"Embedding degrade mode: deterministic vector dims={dims}")
        return emb

    def _cache_embedding(self, text_hash: str, embedding: List[float]) -> List[float]:
        self.cache[text_hash] = embedding
        self._dirty += 1
        self._save_cache()
        return embedding

    def get_embedding(self, text: str) -> Optional[List[float]]:
        text_hash = self._get_text_hash(text)
        if text_hash in self.cache:
            return self.cache[text_hash]

        if not self.api_key:
            print("Error: Missing DASHSCOPE_API_KEY (or embedding.api_key in config)")
            if self.enable_local_fallback:
                local_embedding = self._get_local_embedding(text, text_hash)
                if local_embedding is not None:
                    return local_embedding
            degrade = self._make_degrade_embedding(text_hash)
            if degrade is not None:
                return self._cache_embedding(text_hash, degrade)
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": text,
            "encoding_format": "float",
        }

        timeout_s = int(os.getenv("HYBRID_EMBED_TIMEOUT", "45"))
        max_retries = int(os.getenv("HYBRID_EMBED_RETRIES", "3"))
        backoff_base = float(os.getenv("HYBRID_EMBED_BACKOFF", "1.5"))

        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(
                    self.endpoint, headers=headers, json=payload, timeout=timeout_s
                )
                resp.raise_for_status()
                result = resp.json()
                embedding = result["data"][0]["embedding"]
                return self._cache_embedding(text_hash, embedding)
            except Exception as e:
                if attempt >= max_retries:
                    print(f"Error generating embedding after {max_retries} attempts: {e}")
                    if self.enable_local_fallback:
                        local_embedding = self._get_local_embedding(text, text_hash)
                        if local_embedding is not None:
                            print("Embedding fallback: using local model")
                            return local_embedding
                    degrade = self._make_degrade_embedding(text_hash)
                    if degrade is not None:
                        return self._cache_embedding(text_hash, degrade)
                    return None
                sleep_s = backoff_base ** (attempt - 1)
                print(
                    f"Embedding request failed (attempt {attempt}/{max_retries}): {e}; "
                    f"retrying in {sleep_s:.1f}s"
                )
                time.sleep(sleep_s)

    def get_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        out: List[Optional[List[float]]] = []
        for text in texts:
            out.append(self.get_embedding(text))
            time.sleep(0.05)
        self._save_cache(force=True)
        return out
