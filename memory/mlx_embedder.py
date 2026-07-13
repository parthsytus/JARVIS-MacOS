# ==========================================================
# JARVIS — MLX Embedder Wrapper
# Provides unified interface for MLX-based embeddings (bge-small, nomic)
# Falls back to sentence-transformers if MLX unavailable.
# ==========================================================

import os
import numpy as np


def create_embedder(model_name="bge-small-en-v1.5", model_cache_dir=None):
    """
    Create an embedder function that works with MLX models.
    
    Args:
        model_name: Model identifier (e.g., 'bge-small-en-v1.5', 'nomic-embed-text-v1.5')
        model_cache_dir: Directory to cache models
    
    Returns:
        Embedder object with .encode(texts) method returning numpy array
    """
    # Try MLX first
    try:
        from mlx_embeddings import load
        import mlx.core as mx
        
        # Resolve model path
        if model_cache_dir:
            model_path = os.path.join(model_cache_dir, model_name.replace('/', '-') + '-mlx')
        else:
            model_path = os.path.join(os.path.expanduser('~'), '.cache', 'mlx_embeddings', model_name.replace('/', '-') + '-mlx')
        
        # Check if MLX model exists locally
        if os.path.exists(model_path) and os.path.exists(os.path.join(model_path, 'model.safetensors')):
            print(f"[Memory] Loading MLX embedding model from {model_path}")
            model, tokenizer = load(model_path)
            
            class MLXEmbedder:
                def __init__(self, model, tokenizer):
                    self.model = model
                    self.tokenizer = tokenizer
                
                def encode(self, texts, normalize_embeddings=True):
                    if isinstance(texts, str):
                        texts = [texts]
                    
                    all_embeddings = []
                    for text in texts:
                        # Tokenize
                        tokens = self.tokenizer.encode(text)
                        # Add batch dim
                        tokens = mx.array([tokens])
                        
                        # Forward pass
                        outputs = self.model(tokens)
                        # outputs is BaseModelOutput with last_hidden_state
                        if hasattr(outputs, 'last_hidden_state'):
                            hidden = outputs.last_hidden_state
                        elif hasattr(outputs, 'pooler_output'):
                            hidden = outputs.pooler_output
                        else:
                            hidden = outputs[0]
                        
                        # Use CLS token (first token) as embedding
                        embedding = hidden[:, 0, :]  # shape: (1, hidden_dim)
                        # Remove batch dimension
                        embedding = embedding[0]  # shape: (hidden_dim,)
                        
                        # Normalize
                        if normalize_embeddings:
                            embedding = embedding / mx.linalg.norm(embedding)
                        
                        all_embeddings.append(embedding)
                    
                    if all_embeddings:
                        result = mx.stack(all_embeddings)  # shape: (n, hidden_dim)
                        return np.array(result)
                    return np.array([])
            
            embedder = MLXEmbedder(model, tokenizer)
            print(f"[Memory] MLX embedder ready (dim={model.config.hidden_size if hasattr(model, 'config') else 384})")
            return embedder
        
        else:
            print(f"[Memory] MLX model not found at {model_path}, will use sentence-transformers fallback")
    
    except ImportError:
        print("[Memory] mlx_embeddings not available, using sentence-transformers")
    except Exception as e:
        print(f"[Memory] MLX embedder failed: {e}, falling back to sentence-transformers")
    
    # Fallback to sentence-transformers
    from sentence_transformers import SentenceTransformer
    import torch
    
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    
    online = True
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        s.connect(("8.8.8.8", 53))
        s.close()
    except Exception:
        online = False
    
    try:
        embedder = SentenceTransformer(
            model_name,
            device=device,
            cache_folder=model_cache_dir,
            local_files_only=not online,
        )
    except Exception as e:
        if not online:
            print(f"[Memory] Offline load failed: {e}, trying online...")
            embedder = SentenceTransformer(
                model_name,
                device=device,
                cache_folder=model_cache_dir,
                local_files_only=False,
            )
        else:
            raise e
    
    print(f"[Memory] Sentence-transformers embedder ready on {device.upper()}")
    return embedder