#!/usr/bin/env python3
"""
Quick test for DashScope embedding API
"""

import requests
import json

API_KEY = os.getenv("DASHSCOPE_API_KEY")

def test_embedding():
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "text-embedding-v4",
        "input": {"texts": ["This is a test sentence for embedding."]}
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
        embedding = result['output']['embeddings'][0]['embedding']
        print(f"✅ Embedding generated successfully! Dimension: {len(embedding)}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    test_embedding()