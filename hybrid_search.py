#!/usr/bin/env python3
"""
Main entry point for Hybrid Search System
"""

import argparse
import sys
import os
import importlib.util

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ingest import Ingestor as DocumentIngestor
from db import HybridSearchDB
from embed import DashScopeEmbedder
from search import HybridSearcher
import numpy as np

def ingest_command(args):
    """Handle ingest command"""
    print(f"Ingesting sources: {args.sources}")
    
    # Load config
    config_path = os.path.expanduser("~/.openclaw/workspace/tools/hybrid_search/config.yaml")
    ingestor = DocumentIngestor(config_path)
    db = HybridSearchDB("~/.openclaw/workspace/tools/hybrid_search/data/index.db")
    embedder = DashScopeEmbedder(os.getenv("DASHSCOPE_API_KEY"), model="text-embedding-v4", base_url=os.getenv("DASHSCOPE_BASE_URL"))
    
    # Parse sources
    sources = args.sources.split(',') if args.sources else ['notes', 'sessions_summary']
    
    # Ingest documents
    documents = ingestor.ingest_sources(sources, args.since)
    print(f"Ingested {len(documents)} documents")
    
    # Generate embeddings and store in database
    for doc in documents:
        doc_id = db.insert_document(doc)
        
        # Generate embedding
        embedding = embedder.get_embedding(doc['text'])
        if embedding:
            # Convert to bytes for storage
            embedding_bytes = np.array(embedding, dtype=np.float32).tobytes()
            db.update_embedding(doc_id, embedding_bytes, "text-embedding-v4", len(embedding))
            print(f"Generated embedding for document {doc_id}")
        else:
            print(f"Failed to generate embedding for document {doc_id}")
    
    print("Ingestion completed!")

def search_command(args):
    """Handle search command"""
    print(f"Searching for: '{args.query}'")
    
    config_path = os.path.expanduser("~/.openclaw/workspace/tools/hybrid_search/config.yaml")
    searcher = HybridSearcher(config_path)
    
    results = searcher.search(args.query, args.top)
    
    print(f"\nFound {len(results)} results:\n")
    for i, result in enumerate(results, 1):
        doc = result['doc']
        print(f"{i}. Score: {result['score']:.4f}")
        print(f"   Source: {doc['source']}")
        print(f"   Path: {doc['path']}")
        print(f"   Section: {doc['section']}")
        print(f"   Text: {doc['text'][:200]}...")
        print()

def rebuild_command(args):
    """Handle rebuild command"""
    print("Rebuilding FAISS index...")
    
    config_path = os.path.expanduser("~/.openclaw/workspace/tools/hybrid_search/config.yaml")
    searcher = HybridSearcher(config_path)
    searcher.rebuild_index()
    
    print("FAISS index rebuilt successfully!")

def main():
    parser = argparse.ArgumentParser(description="Hybrid Search CLI for OpenClaw")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Ingest command
    ingest_parser = subparsers.add_parser('ingest', help='Ingest documents into the search system')
    ingest_parser.add_argument('--sources', type=str, help='Comma-separated list of sources (notes,sessions_summary,logs)')
    ingest_parser.add_argument('--since', type=int, help='Only ingest documents modified in the last N days')
    
    # Search command
    search_parser = subparsers.add_parser('search', help='Search documents using hybrid retrieval')
    search_parser.add_argument('query', type=str, help='Search query')
    search_parser.add_argument('--top', type=int, default=10, help='Number of results to return')
    
    # Rebuild command
    rebuild_parser = subparsers.add_parser('rebuild', help='Rebuild the FAISS vector index')
    
    # Parse arguments
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        if args.command == 'ingest':
            ingest_command(args)
        elif args.command == 'search':
            search_command(args)
        elif args.command == 'rebuild':
            rebuild_command(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()