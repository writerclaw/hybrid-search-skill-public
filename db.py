#!/usr/bin/env python3
"""
Hybrid Search Database Module
SQLite with FTS5 + vector table.
"""

import hashlib
import json
import os
import sqlite3
from typing import Dict, List, Optional, Tuple


class HybridSearchDB:
    def __init__(self, db_path: str):
        self.db_path = os.path.expanduser(db_path)
        self._ensure_data_dir()
        self._init_database()

    def _ensure_data_dir(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def _init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS docs (
                id TEXT PRIMARY KEY,
                source TEXT,
                path TEXT,
                section TEXT,
                ts INTEGER,
                tags TEXT,
                text TEXT
            )
            """
        )

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='docs_fts'")
        exists = cursor.fetchone() is not None
        if exists:
            cols = [r[1] for r in cursor.execute("PRAGMA table_info(docs_fts)").fetchall()]
            if "doc_id" not in cols:
                cursor.execute("DROP TABLE docs_fts")
                exists = False

        if not exists:
            cursor.execute(
                """
                CREATE VIRTUAL TABLE docs_fts
                USING fts5(doc_id UNINDEXED, content, tokenize='unicode61')
                """
            )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS doc_vectors (
                id TEXT PRIMARY KEY,
                embedding BLOB,
                model TEXT,
                dims INTEGER,
                FOREIGN KEY (id) REFERENCES docs (id)
            )
            """
        )

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_docs_ts ON docs(ts)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_docs_source ON docs(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_docs_path ON docs(path)")

        conn.commit()
        conn.close()

    def generate_doc_id(self, text: str, path: str, section: str = "") -> str:
        content = f"{text}:{path}:{section}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def insert_document(self, doc: Dict) -> str:
        doc_id = self.generate_doc_id(doc["text"], doc["path"], doc.get("section", ""))
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO docs (id, source, path, section, ts, tags, text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id,
                doc["source"],
                doc["path"],
                doc.get("section", ""),
                doc["ts"],
                json.dumps(doc.get("tags", []), ensure_ascii=False),
                doc["text"],
            ),
        )

        cursor.execute("DELETE FROM docs_fts WHERE doc_id = ?", (doc_id,))
        cursor.execute("INSERT INTO docs_fts (doc_id, content) VALUES (?, ?)", (doc_id, doc["text"]))

        conn.commit()
        conn.close()
        return doc_id

    def update_embedding(self, doc_id: str, embedding: bytes, model: str, dims: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO doc_vectors (id, embedding, model, dims)
            VALUES (?, ?, ?, ?)
            """,
            (doc_id, embedding, model, dims),
        )
        conn.commit()
        conn.close()

    def delete_documents_by_paths(self, paths: List[str]) -> int:
        if not paths:
            return 0
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        q = ",".join(["?"] * len(paths))
        cursor.execute(f"SELECT id FROM docs WHERE path IN ({q})", paths)
        doc_ids = [r[0] for r in cursor.fetchall()]
        if not doc_ids:
            conn.close()
            return 0

        q2 = ",".join(["?"] * len(doc_ids))
        cursor.execute(f"DELETE FROM doc_vectors WHERE id IN ({q2})", doc_ids)
        cursor.execute(f"DELETE FROM docs_fts WHERE doc_id IN ({q2})", doc_ids)
        cursor.execute(f"DELETE FROM docs WHERE id IN ({q2})", doc_ids)
        conn.commit()
        conn.close()
        return len(doc_ids)

    def vacuum_analyze(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("VACUUM")
        cursor.execute("ANALYZE")
        conn.close()

    def search_fts(self, query: str, limit: int = 50) -> List[Tuple[str, float]]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT doc_id, bm25(docs_fts) AS score
            FROM docs_fts
            WHERE docs_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (query, limit),
        )
        rows = [(r[0], float(r[1])) for r in cursor.fetchall()]
        conn.close()
        return rows

    def get_document_by_id(self, doc_id: str) -> Optional[Dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, source, path, section, ts, tags, text
            FROM docs
            WHERE id = ?
            """,
            (doc_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0],
            "source": row[1],
            "path": row[2],
            "section": row[3],
            "ts": row[4],
            "tags": json.loads(row[5]) if row[5] else [],
            "text": row[6],
        }
