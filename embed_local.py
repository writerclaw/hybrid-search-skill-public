#!/usr/bin/env python3
"""
Local embedding generation module using sentence-transformers.
Falls back to CPU if CUDA is not available.
"""

import hashlib
import json
import os
from typing import Dict, List, Optional

import numpy as np

# Global cache for the model
_model = None
_model_name = None


class LocalEmbedder:
    """Local embedding model using sentence-transformers."""
    
    # Lightweight model good for semantic search
    DEFAULT_MODEL = "all-MiniLM-L6-v2"
    
    # Alternative models (uncomment to use):
    # DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"  # Multilingual
    # DEFAULT_MODEL = "nomic-ai/nomic-embed-text-v1"  # Better quality, larger
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        cache_dir: Optional[str] = None,
    ):
        self.model_name = model_name or self.DEFAULT_MODEL
        self.cache_dir = cache_dir or os.path.expanduser(
            "~/.openclaw/workspace/tools/hybrid_search/models"
        )
        
        # Initialize embedding cache
        self.cache_file = os.path.expanduser(
            "~/.openclaw/workspace/tools/hybrid_search/data/embedding_cache_local.json"
        )
        self.cache: Dict[str, List[float]] = self._load_cache()
        self._dirty = 0
        
        # Load model (lazy loading)
        self._model = None
        
    def _load_cache(self) -> Dict[str, List[float]]:
        """Load embedding cache from disk."""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load embedding cache: {e}")
        return {}
    
    def _save_cache(self, force: bool = False):
        """Save embedding cache to disk."""
        if not force and self._dirty < 20:
            return
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self.cache, f)
        self._dirty = 0
    
    def _get_text_hash(self, text: str) -> str:
        """Generate hash for text content."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    
    def _load_model(self):
        """Lazy load the sentence-transformers model."""
        if self._model is not None:
            return
        
        try:
            from sentence_transformers import SentenceTransformer
            
            print(f"Loading embedding model: {self.model_name}")
            print(f"Cache directory: {self.cache_dir}")
            
            # Create cache directory
            os.makedirs(self.cache_dir, exist_ok=True)
            
            # Load model
            self._model = SentenceTransformer(
                self.model_name,
                cache_folder=self.cache_dir,
                device="cpu",  # Use CPU for compatibility
            )
            
            print(f"Model loaded successfully!")
            print(f"Embedding dimension: {self._model.get_sentence_embedding_dimension()}")
            
        except ImportError:
            print("Error: sentence-transformers not installed.")
            print("Please run: pip install sentence-transformers")
            raise
        except Exception as e:
            print(f"Error loading model: {e}")
            raise
    
    def get_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text using local model."""
        # Check cache first
        text_hash = self._get_text_hash(text)
        if text_hash in self.cache:
            return self.cache[text_hash]
        
        # Load model if needed
        self._load_model()
        
        try:
            # Generate embedding
            embedding = self._model.encode(text, convert_to_numpy=True, show_progress_bar=False)
            embedding_list = embedding.tolist()
            
            # Cache the result
            self.cache[text_hash] = embedding_list
            self._dirty += 1
            self._save_cache()
            
            return embedding_list
            
        except Exception as e:
            print(f"Error generating embedding: {e}")
            return None
    
    def get_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Generate embeddings for multiple texts."""
        results = []
        for text in texts:
            results.append(self.get_embedding(text))
        return results


def create_embedder(config_path: Optional[str] = None) -> LocalEmbedder:
    """Factory function to create embedder from config."""
    import yaml
    
    if config_path is None:
        config_path = os.path.expanduser(
            "~/.openclaw/workspace/tools/hybrid_search/config.yaml"
        )
    
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
        
        embed_cfg = cfg.get("embedding", {})
        model_name = embed_cfg.get("model", "all-MiniLM-L6-v2")
        cache_dir = embed_cfg.get("cache_dir")
        
        return LocalEmbedder(model_name=model_name, cache_dir=cache_dir)
    
    # Fallback to default
    return LocalEmbedder()


if __name__ == "__main__":
    # Quick test
    embedder = LocalEmbedder()
    test_text = "This is a test sentence."
    embedding = embedder.get_embedding(test_text)
    if embedding:
        print(f"Test successful! Embedding dimension: {len(embedding)}")
    else:
        print("Test failed!")
