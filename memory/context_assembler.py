# ==========================================================
# JARVIS — Context Assembler (Working Memory)
# Replaces the naive "last 10 turns" with intelligent context
# assembly. Selects the most RELEVANT memories, not just the
# most recent, and packs them into the LLM context window.
# ==========================================================

import time
from datetime import datetime, timedelta
from config.config import MEMORY_TOP_K


class ContextAssembler:
    """Intelligent working memory — builds optimized context for each LLM call."""

    def __init__(self, vector_store, episodic_store, semantic_store,
                 procedural_store, importance_scorer, context_budget_tokens=1500):
        """
        Args:
            vector_store: VectorStore instance for RAG search.
            episodic_store: EpisodicStore instance.
            semantic_store: SemanticStore instance.
            procedural_store: ProceduralStore instance.
            importance_scorer: ImportanceScorer instance.
            context_budget_tokens: Max approximate tokens for memory block.
        """
        self.vector = vector_store
        self.episodic = episodic_store
        self.semantic = semantic_store
        self.procedural = procedural_store
        self.scorer = importance_scorer
        self.budget = context_budget_tokens

    def build_stable_context(self):
        """Build the static memory tier (Identity + Procedural rules).
        This is computed once and baked into the system prompt to maximize KV cache reuse.
        """
        sections = []

        # ----- 1. Semantic Facts (always include — compact) -----
        semantic_block = self.semantic.build_context_block()
        if semantic_block:
            sections.append(semantic_block)

        # ----- 2. Procedural hints -----
        procedural_block = self.procedural.build_context_block()
        if procedural_block:
            sections.append(procedural_block)

        if not sections:
            return ""

        full_text = "\n".join(sections)
        header = (
            "YOUR IDENTITY & RULES (Stable Memory):"
        )
        return f"{header}\n{full_text}"

    def build_dynamic_context(self, user_query, query_embedding=None):
        """Build the dynamic memory tier (RAG + Episodic).
        Only run this on conversational turns, and attach to the tail of the prompt.
        """
        sections = []

        # ----- 1. RAG: Semantically relevant past memories -----
        rag_results = self._get_rag_memories(user_query, query_embedding=query_embedding)
        if rag_results:
            rag_lines = []
            for mem in rag_results:
                timestamp = mem.get("metadata", {}).get("timestamp")
                time_label = self._format_relative_time(timestamp)
                text = mem["text"]
                rag_lines.append(f"[{time_label}] {text}")
            sections.append("RELEVANT PAST CONVERSATIONS:\n" + "\n".join(rag_lines))

        # ----- 2. Episodic: Recent important episodes -----
        episodic_memories = self._get_episodic_memories(user_query)
        if episodic_memories:
            ep_lines = []
            for ep in episodic_memories:
                time_label = self._format_relative_time(ep.get("timestamp"))
                summary = ep.get("summary", "")
                if summary:
                    ep_lines.append(f"[{time_label}] {summary}")
            if ep_lines:
                sections.append("RECENT IMPORTANT EVENTS:\n" + "\n".join(ep_lines))

        # ----- Assemble final block -----
        if not sections:
            return ""

        # Trim to budget (rough estimate: 1 token ≈ 4 chars)
        max_chars = self.budget * 4
        full_text = "\n\n".join(sections)

        if len(full_text) > max_chars:
            full_text = full_text[:max_chars].rsplit("\n", 1)[0]  # Cut at last full line

        header = (
            "DYNAMIC MEMORY (Use naturally if relevant — do NOT announce 'I recall' unless asked):"
        )
        return f"{header}\n{full_text}"

    def _get_rag_memories(self, query, top_k=MEMORY_TOP_K, query_embedding=None):
        """Search vector store for relevant past memories.

        Uses MMR to ensure diversity (don't return 3 copies of the same thing).
        """
        if not query or self.vector.count() == 0:
            return []

        try:
            results = self.vector.search_with_mmr(
                query,
                top_k=top_k,
                candidate_k=min(15, self.vector.count()),
                diversity=0.3,
                query_embedding=query_embedding,
            )

            # Filter out low-relevance results (cosine distance > 0.65 = unrelated)
            filtered = [r for r in results if r.get("distance", 1.0) < 0.65]

            # Apply decay scoring to further rank
            for mem in filtered:
                meta = mem.get("metadata", {})
                importance = float(meta.get("importance", 0.5))
                timestamp = meta.get("timestamp")
                reinforcements = int(meta.get("reinforcement_count", 0))
                mem["_effective_score"] = self.scorer.apply_decay(
                    importance, timestamp, reinforcements
                ) if timestamp else importance

            # Sort by effective score
            filtered.sort(key=lambda x: x.get("_effective_score", 0), reverse=True)
            return filtered[:top_k]

        except Exception as e:
            print(f"[Memory] RAG search error: {e}")
            return []

    def _get_episodic_memories(self, query, max_results=3):
        """Get recent high-importance episodic memories.

        Two pools:
            1. Last 7 days, importance >= 0.5
            2. All-time importance >= 0.8 (critical memories never fade from context)
        """
        results = []
        seen_ids = set()

        try:
            # Pool 1: Recent episodes (high threshold to avoid trapping context)
            recent = self.episodic.get_recent(days=3, max_results=3)
            for ep in recent:
                # Apply decay
                decayed = self.scorer.apply_decay(
                    ep.get("importance_score", 0.5),
                    ep.get("timestamp"),
                    ep.get("reinforcement_count", 0),
                )
                # Only inject unconditionally if it's highly important (>= 0.65)
                # Ordinary chats will still be fetched by RAG if semantically relevant.
                if decayed >= 0.65 and ep["event_id"] not in seen_ids:
                    ep["_effective_score"] = decayed
                    results.append(ep)
                    seen_ids.add(ep["event_id"])

            # Pool 2: All-time critical memories
            critical = self.episodic.get_by_importance(min_importance=0.8, max_results=3)
            for ep in critical:
                if ep["event_id"] not in seen_ids:
                    ep["_effective_score"] = ep.get("importance_score", 0.8)
                    results.append(ep)
                    seen_ids.add(ep["event_id"])

            # Sort by effective score and return top N
            results.sort(key=lambda x: x.get("_effective_score", 0), reverse=True)
            return results[:max_results]

        except Exception as e:
            print(f"[Memory] Episodic search error: {e}")
            return []

    @staticmethod
    def _format_relative_time(timestamp):
        """Convert a timestamp to a human-friendly relative label.

        Examples: "Just now", "2 hours ago", "Yesterday", "3 days ago", "2 weeks ago"
        """
        if not timestamp:
            return "Past"

        try:
            if isinstance(timestamp, str):
                dt = datetime.fromisoformat(timestamp)
            elif isinstance(timestamp, (int, float)):
                dt = datetime.fromtimestamp(timestamp)
            else:
                return "Past"

            delta = datetime.now() - dt
            seconds = delta.total_seconds()

            if seconds < 3600:
                return "Earlier today"
            elif seconds < 86400:
                hours = int(seconds / 3600)
                return f"{hours} hour{'s' if hours > 1 else ''} ago"
            elif seconds < 172800:
                return "Yesterday"
            elif seconds < 604800:
                days = int(seconds / 86400)
                return f"{days} days ago"
            elif seconds < 2592000:
                weeks = int(seconds / 604800)
                return f"{weeks} week{'s' if weeks > 1 else ''} ago"
            elif seconds < 31536000:
                months = int(seconds / 2592000)
                return f"{months} month{'s' if months > 1 else ''} ago"
            else:
                years = int(seconds / 31536000)
                return f"{years} year{'s' if years > 1 else ''} ago"

        except (ValueError, TypeError):
            return "Past"
