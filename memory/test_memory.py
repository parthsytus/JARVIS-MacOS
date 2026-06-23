"""Quick smoke test for the JARVIS memory system."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 50)
print("JARVIS Memory System — Smoke Test")
print("=" * 50)

# 1. ChromaDB
import chromadb
print(f"[OK] ChromaDB {chromadb.__version__}")

# 2. Sentence Transformers
from sentence_transformers import SentenceTransformer
print("[OK] sentence-transformers")

# 3. Importance Scorer
from memory.importance_scorer import ImportanceScorer
scorer = ImportanceScorer()
high = scorer.score_importance("I think I want to quit engineering", emotion_valence=-0.7)
low = scorer.score_importance("what time is it", emotion_valence=0.0)
print(f"[OK] Importance Scorer — 'quit engineering': {high:.2f}, 'what time': {low:.2f}")

# 4. Forgetting curve
import math
decayed = scorer.apply_decay(0.8, "2026-06-01T10:00:00")
print(f"[OK] Forgetting curve — 0.8 importance after ~17 days: {decayed:.2f}")

# 5. Episodic Store
from memory.episodic_store import EpisodicStore
ep = EpisodicStore(os.path.join("memory", "store", "episodic.jsonl"))
print(f"[OK] Episodic Store — {ep.count()} episodes")

# 6. Semantic Store
from memory.semantic_store import SemanticStore
sem = SemanticStore(os.path.join("memory", "store", "semantic_facts.json"))
print(f"[OK] Semantic Store — {sem.count()} facts")

# 7. Procedural Store
from memory.procedural_store import ProceduralStore
proc = ProceduralStore(os.path.join("memory", "store", "procedural_prefs.json"))
print(f"[OK] Procedural Store — {proc.get_stats()['total_sessions']} sessions")

# 8. Vector Store (this will load the embedding model on first run)
print("\nLoading embedding model (first run downloads ~90MB to models/)...")
from memory.vector_store import VectorStore
vs = VectorStore(
    persist_dir=os.path.join("memory", "store", "chroma_db"),
    model_name="all-MiniLM-L6-v2",
    model_cache_dir=os.path.join("models"),
)
# Test add + search
vs.add_memory("Parth mentioned he wants to build a game studio", metadata={"importance": 0.9})
vs.add_memory("Parth was stressed about his algorithms exam", metadata={"importance": 0.7})
vs.add_memory("Casual chat about the weather today", metadata={"importance": 0.2})

results = vs.search("game development", top_k=2)
print(f"[OK] Vector Store — {vs.count()} entries")
print(f"     Search 'game development' top result: \"{results[0]['text'][:60]}...\"")

print("\n" + "=" * 50)
print("ALL TESTS PASSED — Memory system is operational.")
print("=" * 50)
