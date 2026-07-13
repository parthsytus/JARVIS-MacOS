# ==========================================================
# JARVIS — Vector Store (RAG Foundation)
# ChromaDB + MLX/sentence-transformers for semantic memory search.
# Embeds conversations, retrieves by similarity at query time.
# ==========================================================

import os
import uuid
import time
import numpy as np

import chromadb
from memory.mlx_embedder import create_embedder


def is_connected():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)  # Per-socket timeout — don't use setdefaulttimeout (affects all sockets)
        s.connect(("8.8.8.8", 53))
        s.close()
        return True
    except Exception:
        return False


class VectorStore:
    """ChromaDB-backed vector store for JARVIS long-term memory retrieval."""

    def __init__(self, persist_dir, model_name="bge-small-en-v1.5", model_cache_dir=None):
        """
        Args:
            persist_dir: Path to ChromaDB persistent storage (e.g. memory/store/chroma_db/)
            model_name: Embedding model name (default: bge-small-en-v1.5, uses MLX if available)
            model_cache_dir: Where to download/cache the model
        """
        os.makedirs(persist_dir, exist_ok=True)

        print("[Memory] Loading embedding model...")
        self.embedder = create_embedder(model_name, model_cache_dir)
        print(f"[Memory] Embedding model ready.")

        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name="jarvis_memories",
            metadata={"hnsw:space": "cosine"},
        )
        print(f"[Memory] ChromaDB ready — {self.count()} existing entries.")

    # ----------------------------------------------------------
    # WRITE
    # ----------------------------------------------------------
    def add_memory(self, text, metadata=None):
        """Embed and store a memory chunk.

        Args:
            text: The text to embed and store.
            metadata: Optional dict with keys like 'source', 'timestamp',
                      'importance', 'tags', 'emotion_valence', 'event_id'.
        Returns:
            The generated memory ID.
        """
        if not text or not text.strip():
            return None

        memory_id = f"mem_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        embedding = self.embedder.encode(text).tolist()

        # ChromaDB metadata must be str/int/float/bool — flatten complex types
        safe_metadata = {}
        if metadata:
            for k, v in metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    safe_metadata[k] = v
                elif isinstance(v, list):
                    safe_metadata[k] = ", ".join(str(x) for x in v)
                else:
                    safe_metadata[k] = str(v)

        # Always store the timestamp for decay calculations
        if "timestamp" not in safe_metadata:
            safe_metadata["timestamp"] = time.time()

        # Embedder returns (n, dim) array; for single text it's (1, dim)
        # ChromaDB expects list of embeddings, each a list of floats
        embedding = self.embedder.encode(text)
        emb_list = embedding.tolist()
        if isinstance(emb_list[0], list):
            # Already 2D: [[...], [...], ...]
            embeddings = emb_list
        else:
            # 1D: [...] -> wrap in list
            embeddings = [emb_list]

        self.collection.add(
            ids=[memory_id],
            embeddings=embeddings,
            documents=[text],
            metadatas=[safe_metadata],
        )
        return memory_id

    def add_memories_batch(self, texts, metadatas=None):
        """Batch-add multiple memories at once (more efficient)."""
        if not texts:
            return []

        ids = [f"mem_{int(time.time())}_{uuid.uuid4().hex[:8]}" for _ in texts]
        embeddings = self.embedder.encode(texts).tolist()

        safe_metadatas = []
        for i, meta in enumerate(metadatas or [{}] * len(texts)):
            safe = {}
            for k, v in meta.items():
                if isinstance(v, (str, int, float, bool)):
                    safe[k] = v
                elif isinstance(v, list):
                    safe[k] = ", ".join(str(x) for x in v)
                else:
                    safe[k] = str(v)
            if "timestamp" not in safe:
                safe["timestamp"] = time.time()
            safe_metadatas.append(safe)

        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=safe_metadatas,
        )
        return ids

    # ----------------------------------------------------------
    # READ
    # ----------------------------------------------------------
    def search(self, query, top_k=5):
        """Retrieve top-k semantically similar memories.

        Args:
            query: The search query text.
            top_k: Number of results to return.
        Returns:
            List of dicts: [{'text': ..., 'metadata': ..., 'distance': ...}, ...]
            Lower distance = more similar (cosine distance).
        """
        if self.count() == 0:
            return []

        # Don't request more results than we have
        actual_k = min(top_k, self.count())

        query_embedding = self.embedder.encode(query)
        query_emb_list = query_embedding.tolist()
        if isinstance(query_emb_list[0], list):
            # Already 2D: [[...], [...], ...]
            query_embeddings = query_emb_list
        else:
            # 1D: [...] -> wrap in list
            query_embeddings = [query_emb_list]
        results = self.collection.query(
            query_embeddings=query_embeddings,
            n_results=actual_k,
        )

        output = []
        for i in range(len(results["ids"][0])):
            output.append({
                "id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else None,
            })
        return output

    def search_with_mmr(self, query, top_k=5, candidate_k=20, diversity=0.3, query_embedding=None):
        """Maximal Marginal Relevance search — balances relevance with diversity.

        Prevents retrieving 5 memories that all say the same thing.

        Args:
            query: The search query text.
            top_k: Final number of results to return.
            candidate_k: Initial candidates to fetch before MMR reranking.
            diversity: 0.0 = pure relevance, 1.0 = pure diversity.
            query_embedding: Optional pre-computed embedding to avoid re-encoding.
        Returns:
            Same format as search().
        """
        if self.count() == 0:
            return []

        actual_candidate_k = min(candidate_k, self.count())
        actual_top_k = min(top_k, actual_candidate_k)

        if query_embedding is None:
            query_embedding = self.embedder.encode(query)
        elif not isinstance(query_embedding, np.ndarray):
            query_embedding = np.array(query_embedding)
        
        # Ensure proper format for ChromaDB
        query_emb_list = query_embedding.tolist()
        if isinstance(query_emb_list[0], list):
            query_embeddings = query_emb_list
        else:
            query_embeddings = [query_emb_list]

        # Fetch more candidates than needed
        results = self.collection.query(
            query_embeddings=query_embeddings,
            n_results=actual_candidate_k,
            include=["documents", "metadatas", "distances", "embeddings"],
        )

        if not results["ids"][0]:
            return []

        # Rebuild candidate list with embeddings
        candidates = []
        for i in range(len(results["ids"][0])):
            candidates.append({
                "id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else None,
                "embedding": np.array(results["embeddings"][0][i]) if results["embeddings"] else None,
            })

        # MMR reranking
        selected = []
        remaining = list(range(len(candidates)))

        for _ in range(actual_top_k):
            best_idx = None
            best_score = -float("inf")

            for idx in remaining:
                # Relevance: similarity to query (1 - cosine_distance)
                relevance = 1.0 - (candidates[idx]["distance"] or 0.0)

                # Diversity penalty: max similarity to already selected
                max_sim_to_selected = 0.0
                if selected and candidates[idx]["embedding"] is not None:
                    for sel_idx in selected:
                        if candidates[sel_idx]["embedding"] is not None:
                            sim = np.dot(candidates[idx]["embedding"], candidates[sel_idx]["embedding"]) / (
                                np.linalg.norm(candidates[idx]["embedding"]) * np.linalg.norm(candidates[sel_idx]["embedding"]) + 1e-8
                            )
                            max_sim_to_selected = max(max_sim_to_selected, sim)

                # MMR score
                mmr_score = (1 - diversity) * relevance - diversity * max_sim_to_selected

                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = idx

            if best_idx is not None:
                selected.append(best_idx)
                remaining.remove(best_idx)

        # Return in selected order (most relevant first)
        output = []
        for idx in selected:
            c = candidates[idx]
            output.append({
                "id": c["id"],
                "text": c["text"],
                "metadata": c["metadata"],
                "distance": c["distance"],
            })
        return output

    # ----------------------------------------------------------
    # MAINTENANCE
    # ----------------------------------------------------------
    def delete_by_ids(self, ids):
        """Delete specific memories by ID."""
        if ids:
            self.collection.delete(ids=ids)

    def delete_old(self, before_timestamp):
        """Delete all memories older than the given Unix timestamp."""
        results = self.collection.get(
            where={"timestamp": {"$lt": before_timestamp}},
        )
        if results["ids"]:
            self.collection.delete(ids=results["ids"])
            return len(results["ids"])
        return 0

    def count(self):
        """Return total number of stored memories."""
        return self.collection.count()

    def get_all_ids(self):
        """Return all memory IDs (for maintenance/debugging)."""
        results = self.collection.get()
        return results["ids"]
