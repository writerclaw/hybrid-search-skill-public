#!/usr/bin/env python3
"""
Hybrid search module combining FTS and vector search.
"""

import json
import os
import sqlite3
from typing import Dict, List

import faiss
import numpy as np
import yaml

try:
    from .db import HybridSearchDB
    from .embed import DashScopeEmbedder
except ImportError:
    from db import HybridSearchDB
    from embed import DashScopeEmbedder


class HybridSearcher:
    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.db = HybridSearchDB(self.config["storage"]["sqlite"])
        self.embedder = DashScopeEmbedder(
            self.config.get("embedding", {}).get("api_key"),
            self.config.get("embedding", {}).get("model", "text-embedding-v4"),
            self.config.get("embedding", {}).get("base_url"),
        )

        self.faiss_index_path = os.path.expanduser("~/.openclaw/workspace/tools/hybrid_search/data/faiss.index")
        self.id_map_path = os.path.expanduser("~/.openclaw/workspace/tools/hybrid_search/data/id_map.json")

        self.faiss_index = None
        self.id_to_doc_id: Dict[str, str] = {}
        self.doc_id_to_id: Dict[str, str] = {}

        self._load_faiss_index()

    def _load_config(self, config_path: str) -> Dict:
        with open(os.path.expanduser(config_path), "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _load_faiss_index(self):
        if os.path.exists(self.faiss_index_path) and os.path.exists(self.id_map_path):
            try:
                self.faiss_index = faiss.read_index(self.faiss_index_path)
                with open(self.id_map_path, "r", encoding="utf-8") as f:
                    self.id_to_doc_id = json.load(f)
                self.doc_id_to_id = {v: k for k, v in self.id_to_doc_id.items()}
            except Exception as e:
                print(f"Failed to load FAISS index: {e}")
                self.faiss_index = None
                self.id_to_doc_id = {}
                self.doc_id_to_id = {}

    def _save_faiss_index(self):
        if self.faiss_index is None:
            return
        os.makedirs(os.path.dirname(self.faiss_index_path), exist_ok=True)
        faiss.write_index(self.faiss_index, self.faiss_index_path)
        with open(self.id_map_path, "w", encoding="utf-8") as f:
            json.dump(self.id_to_doc_id, f, ensure_ascii=False)

    def _rrf_score(self, rank: int, k: int = 60) -> float:
        return 1.0 / (k + rank)

    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        fts_results = self.db.search_fts(query, self.config["search"].get("topk_fts", 50))
        fts_doc_ids = [doc_id for doc_id, _ in fts_results]
        fts_rank = {doc_id: i + 1 for i, doc_id in enumerate(fts_doc_ids)}

        vec_doc_ids: List[str] = []
        if self.faiss_index is not None and self.faiss_index.ntotal > 0:
            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is not None:
                query_vec = np.array(query_embedding, dtype=np.float32).reshape(1, -1)
                k = min(self.config["search"].get("topk_vec", 50), self.faiss_index.ntotal)
                _, indices = self.faiss_index.search(query_vec, k)
                for idx in indices[0]:
                    key = str(int(idx))
                    if key in self.id_to_doc_id:
                        vec_doc_ids.append(self.id_to_doc_id[key])
        vec_rank = {doc_id: i + 1 for i, doc_id in enumerate(vec_doc_ids)}

        all_doc_ids = set(fts_doc_ids) | set(vec_doc_ids)
        w_fts = float(self.config["search"].get("w_fts", 0.6))
        w_vec = float(self.config["search"].get("w_vec", 0.4))
        rrf_k = int(self.config["search"].get("rrf_k", 60))

        combined = []
        for doc_id in all_doc_ids:
            score = 0.0
            if doc_id in fts_rank:
                score += w_fts * self._rrf_score(fts_rank[doc_id], rrf_k)
            if doc_id in vec_rank:
                score += w_vec * self._rrf_score(vec_rank[doc_id], rrf_k)
            doc = self.db.get_document_by_id(doc_id)
            if doc:
                combined.append({"doc": doc, "score": score})

        combined.sort(key=lambda x: x["score"], reverse=True)
        return combined[:top_k]

    def rebuild_index(self):
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, embedding FROM doc_vectors WHERE embedding IS NOT NULL")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            print("No embeddings found to build index")
            return

        embeddings = []
        doc_ids = []
        for doc_id, blob in rows:
            vec = np.frombuffer(blob, dtype=np.float32)
            if vec.size == 0:
                continue
            embeddings.append(vec)
            doc_ids.append(doc_id)

        if not embeddings:
            print("No valid embeddings to build index")
            return

        dim = int(embeddings[0].shape[0])
        self.faiss_index = faiss.IndexFlatL2(dim)
        self.faiss_index.add(np.vstack(embeddings).astype(np.float32))

        self.id_to_doc_id = {str(i): doc_id for i, doc_id in enumerate(doc_ids)}
        self.doc_id_to_id = {v: k for k, v in self.id_to_doc_id.items()}
        self._save_faiss_index()
        print(f"Rebuilt FAISS index with {len(doc_ids)} vectors")
