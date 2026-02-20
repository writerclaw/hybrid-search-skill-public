#!/usr/bin/env python3
"""CLI for Hybrid Search System."""

import argparse
import os
import sys

import numpy as np
import yaml

from db import HybridSearchDB
from embed import DashScopeEmbedder
from ingest import Ingestor
from search import HybridSearcher

CONFIG_PATH = os.path.expanduser("~/.openclaw/workspace/tools/hybrid_search/config.yaml")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_since_days(since):
    if not since:
        return None
    if since.endswith("d"):
        return float(int(since[:-1]))
    if since.endswith("h"):
        return float(int(since[:-1])) / 24
    try:
        return float(since)
    except ValueError as e:
        raise ValueError("Invalid --since format; use 7d, 24h, or numeric days") from e


def ingest_command(args):
    mode = "FULL" if args.full_scan else "INCREMENTAL"
    print("Ingestion mode: {}".format(mode))
    print("Ingesting sources: {}".format(args.sources))

    cfg = load_config()
    ingestor = Ingestor(CONFIG_PATH)
    db = HybridSearchDB(cfg["storage"]["sqlite"])

    # 优先从环境变量读取向量模型的 API Key
    api_key = os.getenv("DASHSCOPE_EMBEDDING_API_KEY")
    
    # 如果环境变量未设置，尝试从配置文件读取（但应该为空）
    if not api_key:
        config_api_key = cfg.get("embedding", {}).get("api_key", "")
        if config_api_key and not config_api_key.startswith("$"):
            # 警告：发现配置文件中有硬编码的 API Key！
            print("⚠️ WARNING: Hardcoded API Key found in config.yaml! This is a security risk.")
            api_key = config_api_key
    embedder = DashScopeEmbedder(
        api_key,
        cfg.get("embedding", {}).get("model", "text-embedding-v4"),
        os.getenv("DASHSCOPE_BASE_URL") or cfg.get("embedding", {}).get("base_url"),
    )

    sources = args.sources.split(",") if args.sources else ["notes", "summary", "logs", "memory"]
    since_days = parse_since_days(args.since)
    documents = ingestor.ingest_sources(sources, since_days, full_scan=args.full_scan)

    if ingestor.processed_files:
        removed = db.delete_documents_by_paths(ingestor.processed_files)
        print("Removed stale chunks: {}".format(removed))

    print("Ingested chunks: {}".format(len(documents)))

    ok_embed = 0
    for chunk in documents:
        doc = chunk.to_dict()
        doc_id = db.insert_document(doc)
        embedding = embedder.get_embedding(doc["text"])
        if embedding is None:
            print("Skipped embedding for {} (no key or API error)".format(doc_id))
            continue
        embedding_bytes = np.array(embedding, dtype=np.float32).tobytes()
        db.update_embedding(
            doc_id,
            embedding_bytes,
            cfg.get("embedding", {}).get("model", "text-embedding-v4"),
            len(embedding),
        )
        ok_embed += 1

    print("Embedding updated: {}".format(ok_embed))
    print("Ingestion completed!")


def search_command(args):
    print("Searching for: {}".format(args.query))
    searcher = HybridSearcher(CONFIG_PATH)
    results = searcher.search(args.query, args.top)
    print("\nFound {} results:\n".format(len(results)))
    for i, result in enumerate(results, 1):
        doc = result["doc"]
        print("{}. Score: {:.4f}".format(i, result["score"]))
        print("   Source: {}".format(doc["source"]))
        print("   Path: {}".format(doc["path"]))
        print("   Section: {}".format(doc["section"]))
        print("   Text: {}...".format(doc["text"][:200]))
        print()


def rebuild_command(_args):
    print("Rebuilding FAISS index...")
    searcher = HybridSearcher(CONFIG_PATH)
    searcher.rebuild_index()
    print("FAISS index rebuilt successfully!")


def main():
    parser = argparse.ArgumentParser(description="Hybrid Search CLI for OpenClaw")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    ingest_parser = subparsers.add_parser("ingest", help="Ingest documents into the search system")
    ingest_parser.add_argument("--sources", type=str, help="Comma-separated list (notes,summary,memory,logs)")
    ingest_parser.add_argument("--since", type=str, help="Only ingest files modified since (e.g., 24h, 7d)")
    ingest_parser.add_argument("--full-scan", action="store_true", help="Force full scan regardless of ledger")

    search_parser = subparsers.add_parser("search", help="Search documents using hybrid retrieval")
    search_parser.add_argument("query", type=str)
    search_parser.add_argument("--top", type=int, default=10)

    subparsers.add_parser("rebuild", help="Rebuild the FAISS vector index")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "ingest":
            ingest_command(args)
        elif args.command == "search":
            search_command(args)
        elif args.command == "rebuild":
            rebuild_command(args)
    except Exception as e:
        print("Error: {}".format(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
