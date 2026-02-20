#!/usr/bin/env python3
"""
Simple script to ingest MEMORY.md into hybrid search system
"""

import os
import sqlite3
import hashlib
import requests
import numpy as np
from datetime import datetime, timezone

# Configuration
DB_PATH = os.path.expanduser("~/.openclaw/workspace/tools/hybrid_search/data/index.db")
API_KEY = os.getenv("DASHSCOPE_API_KEY")
MEMORY_FILE = os.path.expanduser("~/.openclaw/workspace/MEMORY.md")

def init_database():
    """Initialize SQLite database"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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

def generate_doc_id(text: str, path: str, section: str = "") -> str:
    """Generate unique document ID"""
    content = f"{text}:{path}:{section}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]

def get_embedding(text: str) -> list:
    """Get embedding using DashScope API"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
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

def chunk_text_by_sections(text: str) -> list:
    """Split text by markdown headers"""
    sections = []
    current_section = ""
    current_header = "Root"
    
    for line in text.split('\n'):
        if line.startswith('## '):
            # Save previous section
            if current_section.strip():
                sections.append({
                    'header': current_header,
                    'text': current_section.strip()
                })
            # Start new section
            current_header = line[3:].strip()
            current_section = ""
        elif line.startswith('# ') or line.startswith('###'):
            # Skip main title and sub-sub sections for now
            continue
        else:
            current_section += line + "\n"
    
    # Add final section
    if current_section.strip():
        sections.append({
            'header': current_header,
            'text': current_section.strip()
        })
    
    return sections

def ingest_memory_file():
    """Ingest MEMORY.md file"""
    print("Reading MEMORY.md...")
    
    with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print("Chunking by sections...")
    sections = chunk_text_by_sections(content)
    print(f"Found {len(sections)} sections")
    
    init_database()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    for i, section in enumerate(sections):
        if len(section['text']) < 50:  # Skip very short sections
            continue
            
        doc_id = generate_doc_id(section['text'], MEMORY_FILE, section['header'])
        ts = int(os.path.getmtime(MEMORY_FILE))
        
        # Insert document - fix tags as JSON string
        tags_json = '["memory"]'
        
        cursor.execute('''
            INSERT OR REPLACE INTO docs (id, source, path, section, ts, tags, text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            doc_id, 
            'memory', 
            MEMORY_FILE, 
            section['header'], 
            ts, 
            tags_json, 
            section['text']
        ))
        
        cursor.execute('''
            INSERT OR REPLACE INTO docs_fts (rowid, content)
            VALUES (?, ?)
        ''', (doc_id, section['text']))
        
        # Generate embedding
        print(f"Generating embedding for section {i+1}/{len(sections)}: {section['header'][:30]}...")
        embedding = get_embedding(section['text'])
        if embedding:
            embedding_bytes = np.array(embedding, dtype=np.float32).tobytes()
            cursor.execute('''
                INSERT OR REPLACE INTO doc_vectors (id, embedding, model, dims)
                VALUES (?, ?, ?, ?)
            ''', (doc_id, embedding_bytes, "text-embedding-v4", len(embedding)))
        
        conn.commit()
    
    conn.close()
    print("MEMORY.md ingestion completed!")

if __name__ == "__main__":
    ingest_memory_file()