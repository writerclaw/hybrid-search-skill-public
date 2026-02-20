#!/bin/bash
# Test ingestion script for hybrid search

echo "=== Hybrid Search System Test ==="

# Create test directories if they don't exist
mkdir -p ~/.openclaw/workspace/notes
mkdir -p ~/.openclaw/workspace/logs

# Create a test note
cat > ~/.openclaw/workspace/notes/test_memory.md << EOF
# Test Memory Note

This is a test document for the hybrid search system.

## Key Information
- Memory system uses DashScope text-embedding-v4
- Hybrid retrieval combines FTS and vector search
- FAISS is used for vector indexing
- SQLite stores documents and metadata

## Implementation Details
The system ingests documents from notes, memory logs, and session summaries.
It generates embeddings using the DashScope API and stores them in a FAISS index.
Search queries are processed through both full-text search and vector similarity.
Results are combined using a weighted scoring system (0.6 FTS + 0.4 vector).

## Security Considerations
Sensitive information like API keys and passwords are filtered out during ingestion.
Only allowed directories are processed to prevent accidental data exposure.
EOF

echo "Created test note"

# Activate virtual environment and run ingestion
source venv/bin/activate
python3 hybrid_search.py ingest --sources notes --since 1

echo "=== Test completed ==="