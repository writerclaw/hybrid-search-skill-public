#!/usr/bin/env python3
"""
Simple Hybrid Search Implementation - Single file for easy deployment
"""

import os
import re
import json
import yaml
import sqlite3
import hashlib
import requests
import numpy as np
import faiss
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple, Generator

# Configuration
CONFIG = {
    'embedding': {
        'provider': 'dashscope',
        'model': 'text-embedding-v4',
        'api_key': 'os.getenv("DASHSCOPE_API_KEY")'
    },
    'storage': {
        'sqlite': '~/.openclaw/workspace/tools/hybrid_search/data/index.db'
    },
    'search': {
        'topk_fts': 50,
        'topk_vec': 50,
        'w_fts': 0.6,
        'w_vec': 0.4
    },
    'ingest': {
        'sources': {
            'notes': '~/.openclaw/workspace/notes/',
            'sessions_summary': '~/.openclaw/workspace/memory/',
            'logs': '~/.openclaw/workspace/logs/'
        },
        'deny_patterns': ['api_key', 'password', 'token', 'secret', 'auth'],
        'max_chunk_tokens': 800,
        'min_chunk_tokens': 300
    },
    'security': {
        'allowed_paths': [
            '~/.openclaw/workspace/notes/',
            '~/.openclaw/workspace/memory/', 
            '~/.openclaw/workspace/logs/'
        ],
        'denied_paths': [
            '~/.openclaw/agents/main/agent/auth-profiles.json',
            '~/.openclaw/workspace/credentials/',
            '~/.npm-global/'
        ]
    }
}

class SimpleHybridSearch:
    def __init__(self):
        self.db_path = os.path.expanduser(CONFIG['storage']['sqlite'])
        self.api_key = CONFIG['embedding']['api_key']
        self.faiss_index_path = os.path.expanduser("~/.openclaw/workspace/tools/hybrid_search/data/faiss.index")
        self.id_map_path = os.path.expanduser("~/.openclaw/workspace/tools/hybrid_search/data/id_map.json")
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS docs (
                id TEXT PRIMARY KEY,
                source TEXT,
                path TEXT,
                section TEXT,
                ts INTEGER,
                tags TEXT,
                text TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts 
            USING fts5(content, tokenize='unicode61')
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS doc_vectors (
                id TEXT PRIMARY KEY,
                embedding BLOB,
                model TEXT,
                dims INTEGER,
                FOREIGN KEY (id) REFERENCES docs (id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def generate_doc_id(self, text: str, path: str, section: str = "") -> str:
        """Generate unique document ID"""
        content = f"{text}:{path}:{section}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding using DashScope API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "text-embedding-v4",
            "input": {"texts": [text]}
        }
        
        try:
            response = requests.post(
                "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding",
                headers=headers, 
                json=payload, 
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            return result['output']['embeddings'][0]['embedding']
        except Exception as e:
            print(f"Error generating embedding: {e}")
            return None
    
    def ingest_document(self, source: str, path: str, text: str, section: str = "", ts: int = None):
        """Ingest a single document"""
        if ts is None:
            ts = int(datetime.now(timezone.utc).timestamp())
        
        doc_id = self.generate_doc_id(text, path, section)
        
        # Insert into database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO docs (id, source, path, section, ts, tags, text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (doc_id, source, path, section, ts, json.dumps([source]), text))
        
        cursor.execute('''
            INSERT OR REPLACE INTO docs_fts (rowid, content)
            VALUES (?, ?)
        ''', (doc_id, text))
        
        conn.commit()
        conn.close()
        
        # Generate and store embedding
        embedding = self.get_embedding(text)
        if embedding:
            embedding_bytes = np.array(embedding, dtype=np.float32).tobytes()
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO doc_vectors (id, embedding, model, dims)
                VALUES (?, ?, ?, ?)
            ''', (doc_id, embedding_bytes, "text-embedding-v4", len(embedding)))
            conn.commit()
            conn.close()
            print(f"Ingested document {doc_id} with embedding")
        else:
            print(f"Ingested document {doc_id} without embedding")
    
    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        """Simple search combining FTS and vector search"""
        results = []
        
        # FTS search
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT rowid, bm25(docs_fts) as score
            FROM docs_fts
            WHERE docs_fts MATCH ?
            ORDER BY score
            LIMIT ?
        ''', (query, CONFIG['search']['topk_fts']))
        
        fts_results = [(row[0], float(row[1])) for row in cursor.fetchall()]
        conn.close()
        
        # Get full documents for FTS results
        for doc_id, fts_score in fts_results:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT source, path, section, text FROM docs WHERE id = ?', (doc_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                results.append({
                    'doc_id': doc_id,
                    'source': row[0],
                    'path': row[1],
                    'section': row[2],
                    'text': row[3],
                    'score': 1.0 - fts_score,  # Invert BM25 score
                    'type': 'fts'
                })
        
        return results[:top_k]

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Simple Hybrid Search")
    parser.add_argument('command', choices=['ingest', 'search'], help='Command to run')
    parser.add_argument('--source', help='Source type for ingestion')
    parser.add_argument('--path', help='File path for ingestion')
    parser.add_argument('--query', help='Search query')
    parser.add_argument('--top', type=int, default=10, help='Number of results')
    
    args = parser.parse_args()
    
    searcher = SimpleHybridSearch()
    
    if args.command == 'ingest':
        if not args.source or not args.path:
            print("Error: --source and --path required for ingest")
            return
        
        with open(args.path, 'r') as f:
            text = f.read()
        
        searcher.ingest_document(args.source, args.path, text)
        print("Ingestion completed!")
    
    elif args.command == 'search':
        if not args.query:
            print("Error: --query required for search")
            return
        
        results = searcher.search(args.query, args.top)
        print(f"Found {len(results)} results:")
        for result in results:
            print(f"Score: {result['score']:.4f}, Source: {result['source']}")
            print(f"Text: {result['text'][:100]}...")

if __name__ == "__main__":
    main()