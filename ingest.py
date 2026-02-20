#!/usr/bin/env python3
"""
Ingest module for hybrid search system.
Supports incremental ingestion via ledger (mtime+size), with optional full scan.
"""

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Generator, List, Optional

MAX_CHARS = 2000
MIN_CHARS = 100

DEFAULT_DENY_PATTERNS = [
    r"sk-[a-zA-Z0-9]{20,}",
    r"api[_-]?key",
    r"token",
    r"AKIA[0-9A-Z]{16}",
    r"-----BEGIN",
    r"private[_-]?key",
    r"secret",
    r"password",
    r"passwd",
]


class Chunk:
    def __init__(self, text: str, source: str, path: str, section: str = ""):
        self.text = text
        self.source = source
        self.path = path
        self.section = section
        self.doc_id = self._generate_doc_id()

    def _generate_doc_id(self) -> str:
        return hashlib.sha1(f"{self.path}:{self.section}:{self.text}".encode("utf-8")).hexdigest()

    def __getitem__(self, k):
        return getattr(self, k)

    def to_dict(self) -> Dict:
        return {
            "doc_id": self.doc_id,
            "text": self.text,
            "source": self.source,
            "path": self.path,
            "section": self.section,
            "ts": int(os.path.getmtime(self.path)) if os.path.exists(self.path) else int(datetime.now().timestamp()),
        }

    @property
    def ts(self) -> int:
        return self.to_dict()["ts"]


class SecurityFilter:
    def __init__(self, patterns: Optional[List[str]] = None):
        self.compiled_patterns = [re.compile(p, re.IGNORECASE) for p in (patterns or DEFAULT_DENY_PATTERNS)]

    def filter_chunk(self, chunk: Chunk) -> Optional[Chunk]:
        for pattern in self.compiled_patterns:
            if pattern.search(chunk.text):
                return None
        return chunk


class DocumentChunker:
    def __init__(self, max_chars: int = MAX_CHARS, min_chars: int = MIN_CHARS):
        self.max_chars = max_chars
        self.min_chars = min_chars

    def chunk_by_paragraphs(self, text: str) -> List[str]:
        return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    def chunk_by_sentences(self, text: str, max_length: int) -> List[str]:
        sentences = re.split(r"(?<=[.!?。！？])\s+", text)
        chunks: List[str] = []
        buf = ""
        for s in sentences:
            if len(buf) + len(s) + 1 <= max_length:
                buf += s + " "
            else:
                if buf:
                    chunks.append(buf.strip())
                buf = s + " "
        if buf:
            chunks.append(buf.strip())
        return chunks

    def chunk_document(self, text: str, source: str, path: str, section: str = "") -> Generator[Chunk, None, None]:
        paragraphs = self.chunk_by_paragraphs(text)
        i = 0
        while i < len(paragraphs):
            paragraph = paragraphs[i]
            if self.min_chars <= len(paragraph) <= self.max_chars:
                yield Chunk(paragraph, source, path, f"{section}_para_{i}")
                i += 1
                continue

            if len(paragraph) < self.min_chars:
                merged = paragraph
                j = i + 1
                while j < len(paragraphs) and len(merged) + len(paragraphs[j]) + 2 <= self.max_chars:
                    merged += "\n\n" + paragraphs[j]
                    j += 1
                if len(merged) >= self.min_chars:
                    yield Chunk(merged, source, path, f"{section}_merged_{i}_{j-1}")
                i = j
                continue

            for j, chunk_text in enumerate(self.chunk_by_sentences(paragraph, self.max_chars)):
                if len(chunk_text) >= self.min_chars:
                    yield Chunk(chunk_text, source, path, f"{section}_sent_{i}_{j}")
            i += 1


class Ingestor:
    def __init__(self, config_path: Optional[str] = None, dry_run: bool = False):
        self.dry_run = dry_run
        self.chunker = DocumentChunker()
        self.security_filter = SecurityFilter()
        self.stats = {
            "files_scanned": 0,
            "files_changed": 0,
            "chunks_generated": 0,
            "chunks_filtered": 0,
            "chunks_accepted": 0,
        }
        self.processed_files: List[str] = []
        self.ledger_path = os.path.expanduser("~/.openclaw/workspace/tools/hybrid_search/data/ingest_ledger.json")
        self._ledger = self._load_ledger()
        self._next_ledger = dict(self._ledger)

    def _load_ledger(self) -> Dict[str, Dict[str, int]]:
        p = Path(self.ledger_path)
        if not p.exists():
            return {}
        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def _save_ledger(self):
        p = Path(self.ledger_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(self._next_ledger, f, ensure_ascii=False, indent=2)

    def _file_signature(self, file_path: str) -> Dict[str, int]:
        st = os.stat(file_path)
        return {"mtime": int(st.st_mtime), "size": int(st.st_size)}

    def should_process_file(self, file_path: str, since_days: Optional[float] = None, full_scan: bool = False) -> bool:
        if full_scan:
            return True
        if since_days is not None:
            cutoff = datetime.now() - timedelta(days=since_days)
            return datetime.fromtimestamp(os.path.getmtime(file_path)) > cutoff

        sig = self._file_signature(file_path)
        old = self._ledger.get(file_path)
        return old != sig

    def process_file(self, file_path: str, source: str) -> Generator[Chunk, None, None]:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            return

        self.stats["files_scanned"] += 1
        self.stats["files_changed"] += 1
        self.processed_files.append(file_path)
        self._next_ledger[file_path] = self._file_signature(file_path)

        section = Path(file_path).stem
        for chunk in self.chunker.chunk_document(content, source, file_path, section):
            self.stats["chunks_generated"] += 1
            filtered = self.security_filter.filter_chunk(chunk)
            if filtered is None:
                self.stats["chunks_filtered"] += 1
                continue
            self.stats["chunks_accepted"] += 1
            yield filtered

    def ingest(self, sources: List[str], since_days: Optional[float] = None, full_scan: bool = False) -> List[Chunk]:
        all_chunks: List[Chunk] = []
        source_dirs = {
            "notes": os.path.expanduser("~/.openclaw/workspace/notes/"),
            "summary": os.path.expanduser("~/.openclaw/workspace/summary/"),
            "sessions_summary": os.path.expanduser("~/.openclaw/workspace/memory/"),
            "memory": os.path.expanduser("~/.openclaw/workspace/memory/"),
            "logs": os.path.expanduser("~/.openclaw/workspace/logs/"),
        }

        seen_files = set()
        for src in sources:
            source = "summary" if src == "sessions_summary" else src
            source_dir = source_dirs.get(src) or source_dirs.get(source)
            if not source_dir:
                print(f"Unknown source: {src}")
                continue
            if not os.path.exists(source_dir):
                print(f"Source directory does not exist: {source_dir}")
                continue

            for file_path in Path(source_dir).glob("*.md"):
                f = str(file_path)
                seen_files.add(f)
                sig = self._file_signature(f)
                self._next_ledger[f] = sig

                if not self.should_process_file(f, since_days, full_scan):
                    self.stats["files_scanned"] += 1
                    continue

                if self.dry_run:
                    print(f"[DRY-RUN] Would process: {file_path}")
                    self.stats["files_scanned"] += 1
                    self.stats["files_changed"] += 1
                else:
                    all_chunks.extend(self.process_file(f, source))

        tracked_roots = [
            os.path.expanduser("~/.openclaw/workspace/notes/"),
            os.path.expanduser("~/.openclaw/workspace/summary/"),
            os.path.expanduser("~/.openclaw/workspace/memory/"),
            os.path.expanduser("~/.openclaw/workspace/logs/"),
        ]
        for p in list(self._next_ledger.keys()):
            if any(p.startswith(r) for r in tracked_roots) and p not in seen_files and not os.path.exists(p):
                self._next_ledger.pop(p, None)

        if not self.dry_run:
            self._save_ledger()

        return all_chunks

    def ingest_sources(self, sources: List[str], since_days: Optional[float] = None, full_scan: bool = False) -> List[Chunk]:
        return self.ingest(sources, since_days, full_scan)

    def print_stats(self):
        print("\n=== Ingestion Statistics ===")
        for k, v in self.stats.items():
            print(f"{k}: {v}")


def _parse_since_days(since: Optional[str]) -> Optional[float]:
    if not since:
        return None
    if since.endswith("d"):
        return float(int(since[:-1]))
    if since.endswith("h"):
        return float(int(since[:-1])) / 24
    try:
        return float(since)
    except ValueError as e:
        raise ValueError("Invalid --since format; use 7d, 24h, or days as number") from e


def main():
    parser = argparse.ArgumentParser(description="Ingest documents for hybrid search")
    parser.add_argument("--sources", nargs="+", default=["notes", "summary"], choices=["notes", "summary", "sessions_summary", "memory", "logs"])
    parser.add_argument("--since", type=str, help="Only ingest files modified since (e.g., 7d, 24h)")
    parser.add_argument("--full-scan", action="store_true", help="Force full scan regardless of ledger")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    since_days = _parse_since_days(args.since)
    ingestor = Ingestor(dry_run=args.dry_run)
    chunks = ingestor.ingest(args.sources, since_days, full_scan=args.full_scan)
    if not args.dry_run:
        print(f"\nSuccessfully ingested {len(chunks)} chunks")
    ingestor.print_stats()


if __name__ == "__main__":
    main()
