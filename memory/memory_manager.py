# ==========================================================
# JARVIS — Memory Manager (Central Orchestrator)
# Single entry point for all memory operations.
# The core loop talks ONLY to this class.
# ==========================================================

import os
import time
from datetime import datetime


class MemoryManager:
    """Central memory orchestrator — the bridge between JARVIS core and the memory subsystem."""

    def __init__(self, jarvis_root, ollama_url, ollama_model,
                 embedding_model="all-MiniLM-L6-v2", decay_tau_days=30,
                 context_budget_tokens=1500):
        """
        Initialize all memory subsystems.

        Args:
            jarvis_root: Path to JARVIS project root (e.g. D:/JARVIS)
            ollama_url: Ollama API endpoint.
            ollama_model: Ollama model name for consolidation analysis.
            embedding_model: Sentence-transformers model name for embeddings.
            decay_tau_days: Forgetting curve time constant.
            context_budget_tokens: Max tokens for memory context block.
        """
        from memory.vector_store import VectorStore
        from memory.episodic_store import EpisodicStore
        from memory.semantic_store import SemanticStore
        from memory.procedural_store import ProceduralStore
        from memory.importance_scorer import ImportanceScorer
        from memory.context_assembler import ContextAssembler
        from memory.consolidator import SessionConsolidator

        # Paths
        store_dir = os.path.join(jarvis_root, "memory", "store")
        chroma_dir = os.path.join(store_dir, "chroma_db")
        episodic_path = os.path.join(store_dir, "episodic.jsonl")
        semantic_path = os.path.join(store_dir, "semantic_facts.json")
        procedural_path = os.path.join(store_dir, "procedural_prefs.json")
        model_cache_dir = os.path.join(jarvis_root, "models")

        os.makedirs(store_dir, exist_ok=True)

        print("[Memory] ========== MEMORY SYSTEM INIT ==========")

        # Initialize stores
        self.vector_store = VectorStore(
            persist_dir=chroma_dir,
            model_name=embedding_model,
            model_cache_dir=model_cache_dir,
        )
        self.episodic = EpisodicStore(episodic_path)
        self.semantic = SemanticStore(semantic_path)
        self.procedural = ProceduralStore(procedural_path)

        # Initialize intelligence layer
        self.scorer = ImportanceScorer(decay_tau_days=decay_tau_days)
        self.assembler = ContextAssembler(
            vector_store=self.vector_store,
            episodic_store=self.episodic,
            semantic_store=self.semantic,
            procedural_store=self.procedural,
            importance_scorer=self.scorer,
            context_budget_tokens=context_budget_tokens,
        )
        self.consolidator = SessionConsolidator(
            ollama_url=ollama_url,
            ollama_model=ollama_model,
            vector_store=self.vector_store,
            episodic_store=self.episodic,
            semantic_store=self.semantic,
            procedural_store=self.procedural,
            importance_scorer=self.scorer,
        )

        # Mid-session consolidation tracking
        self._consolidated_turn_count = 0

        stats = self.get_stats()
        print(f"[Memory] Ready — {stats['total_episodes']} episodes, "
              f"{stats['total_facts']} facts, "
              f"{stats['vector_entries']} vector entries, "
              f"{stats['total_sessions']} past sessions.")
        print("[Memory] ==========================================")

    # ----------------------------------------------------------
    # QUERY-TIME: Called before every LLM call
    # ----------------------------------------------------------
    def get_stable_context(self):
        """Build the static memory context (Identity & Rules)."""
        try:
            return self.assembler.build_stable_context()
        except Exception as e:
            print(f"[Memory] Stable context assembly error: {e}")
            return ""

    def get_dynamic_context(self, user_query, query_embedding=None):
        """Build the dynamic memory context (RAG + Episodic)."""
        try:
            return self.assembler.build_dynamic_context(user_query, query_embedding=query_embedding)
        except Exception as e:
            print(f"[Memory] Dynamic context assembly error: {e}")
            return ""

    # ----------------------------------------------------------
    # SESSION END: Called at shutdown
    # ----------------------------------------------------------
    def on_session_end(self, full_session_history, session_start_time=None):
        """Consolidate the full session into long-term memory.

        Called at shutdown (KeyboardInterrupt). Processes the entire
        session history into episodic, semantic, and procedural memory.

        Args:
            full_session_history: Complete list of all turns this session.
            session_start_time: datetime when the session started.
        Returns:
            Consolidation results dict, or None.
        """
        try:
            result = self.consolidator.consolidate(
                full_session_history,
                session_start_time=session_start_time,
            )
            if result:
                print(f"[Memory] Session saved: \"{result['summary'][:80]}...\" "
                      f"(importance: {result['importance']:.2f}, "
                      f"facts learned: {result['facts_learned']})")
            return result
        except Exception as e:
            print(f"[Memory] Session consolidation error: {e}")
            return None

    # ----------------------------------------------------------
    # MID-SESSION: Called periodically during long sessions
    # ----------------------------------------------------------
    def check_mid_session_consolidation(self, full_session_history, turn_interval=20):
        """Check if mid-session consolidation should run.

        Called after each turn. Triggers consolidation every `turn_interval` turns
        to prevent data loss if JARVIS crashes.

        Args:
            full_session_history: Complete session history so far.
            turn_interval: How often to consolidate (in turns).
        """
        import threading
        
        current_turns = len(full_session_history)
        turns_since_last = current_turns - self._consolidated_turn_count

        if turns_since_last >= turn_interval:
            # Prevent multiple overlapping consolidation threads
            if getattr(self, "_is_consolidating", False):
                return
            
            self._is_consolidating = True
            
            # Create a snapshot to prevent race conditions while the thread runs
            history_snapshot = list(full_session_history)
            target_turn_count = self._consolidated_turn_count
            
            def _bg_consolidate():
                try:
                    new_count = self.consolidator.consolidate_mid_session(
                        history_snapshot,
                        target_turn_count,
                    )
                    self._consolidated_turn_count = new_count
                except Exception as e:
                    print(f"[Memory] Mid-session consolidation error: {e}")
                finally:
                    self._is_consolidating = False
                    
            # Fire and forget in a daemon thread so it doesn't block JARVIS shutdown
            threading.Thread(target=_bg_consolidate, daemon=True).start()

    # ----------------------------------------------------------
    # STATS & DIAGNOSTICS
    # ----------------------------------------------------------
    def get_stats(self):
        """Get memory system statistics.

        Returns:
            Dict with counts and storage info.
        """
        return {
            "total_episodes": self.episodic.count(),
            "total_facts": self.semantic.count(),
            "vector_entries": self.vector_store.count(),
            "total_sessions": self.procedural.get_stats().get("total_sessions", 0),
            "episodic_stats": self.episodic.get_stats(),
            "procedural_stats": self.procedural.get_stats(),
        }

    def get_disk_usage(self):
        """Calculate total disk usage of the memory store.

        Returns:
            Dict with size_bytes and size_human.
        """
        store_dir = os.path.dirname(self.episodic.store_path)
        total = 0
        for dirpath, dirnames, filenames in os.walk(store_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass

        # Human-readable
        if total < 1024:
            human = f"{total} bytes"
        elif total < 1024 * 1024:
            human = f"{total / 1024:.1f} KB"
        elif total < 1024 * 1024 * 1024:
            human = f"{total / (1024 * 1024):.1f} MB"
        else:
            human = f"{total / (1024 * 1024 * 1024):.2f} GB"

        return {"size_bytes": total, "size_human": human}
