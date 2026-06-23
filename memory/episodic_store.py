# ==========================================================
# JARVIS — Episodic Memory Store
# Stores specific events/conversations with timestamps,
# emotional valence, importance scores, and topic tags.
# Format: JSONL (append-only, one JSON object per line)
# ==========================================================

import os
import json
import time
import uuid
from datetime import datetime, timedelta


class EpisodicStore:
    """Append-only episodic memory store backed by a JSONL file."""

    def __init__(self, store_path):
        """
        Args:
            store_path: Path to the .jsonl file (e.g. memory/store/episodic.jsonl)
        """
        self.store_path = store_path
        os.makedirs(os.path.dirname(store_path), exist_ok=True)

        # In-memory index for fast lookups (loaded from disk at startup)
        self._index = []  # List of {event_id, timestamp, importance, tags, summary}
        self._load_index()

    def _load_index(self):
        """Load lightweight index from the JSONL file into memory."""
        self._index = []
        if not os.path.exists(self.store_path):
            return

        with open(self.store_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    self._index.append({
                        "event_id": entry["event_id"],
                        "timestamp": entry["timestamp"],
                        "importance_score": entry.get("importance_score", 0.5),
                        "tags": entry.get("tags", []),
                        "summary": entry.get("summary", ""),
                        "emotion_valence": entry.get("emotion_valence", 0.0),
                        "reinforcement_count": entry.get("reinforcement_count", 0),
                        "_line_num": line_num,
                    })
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"[Memory] Warning: Skipping malformed episodic entry line {line_num}: {e}")

        print(f"[Memory] Episodic store loaded — {len(self._index)} episodes.")

    # ----------------------------------------------------------
    # WRITE
    # ----------------------------------------------------------
    def add_episode(self, summary, raw_exchange="", emotion_valence=0.0,
                    importance_score=0.5, tags=None):
        """Store a new episodic memory entry.

        Args:
            summary: Short summary of what happened (1-2 sentences).
            raw_exchange: Full raw transcript of the exchange.
            emotion_valence: Float -1.0 (very negative) to 1.0 (very positive).
            importance_score: Float 0.0 to 1.0.
            tags: List of topic tags (e.g. ["burnout", "engineering"]).
        Returns:
            The event_id of the new episode.
        """
        event_id = f"ep_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"

        entry = {
            "event_id": event_id,
            "timestamp": datetime.now().isoformat(),
            "summary": summary,
            "raw_exchange": raw_exchange,
            "emotion_valence": float(emotion_valence),
            "importance_score": float(importance_score),
            "tags": tags or [],
            "reinforcement_count": 0,
        }

        # Append to JSONL file
        with open(self.store_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Update in-memory index
        self._index.append({
            "event_id": event_id,
            "timestamp": entry["timestamp"],
            "importance_score": entry["importance_score"],
            "tags": entry["tags"],
            "summary": entry["summary"],
            "emotion_valence": entry["emotion_valence"],
            "reinforcement_count": 0,
            "_line_num": len(self._index) + 1,
        })

        return event_id

    # ----------------------------------------------------------
    # READ
    # ----------------------------------------------------------
    def get_recent(self, days=7, max_results=10):
        """Get recent episodes from the last N days.

        Args:
            days: How far back to look.
            max_results: Maximum episodes to return.
        Returns:
            List of index entries (summary, tags, importance, etc.)
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        recent = [
            ep for ep in self._index
            if ep["timestamp"] >= cutoff
        ]
        # Sort by importance (highest first), then by recency
        recent.sort(key=lambda x: (x["importance_score"], x["timestamp"]), reverse=True)
        return recent[:max_results]

    def get_by_importance(self, min_importance=0.7, max_results=10):
        """Get the most important episodes regardless of recency.

        Args:
            min_importance: Minimum importance score threshold.
            max_results: Maximum episodes to return.
        Returns:
            List of index entries.
        """
        important = [
            ep for ep in self._index
            if ep["importance_score"] >= min_importance
        ]
        important.sort(key=lambda x: x["importance_score"], reverse=True)
        return important[:max_results]

    def search_by_tags(self, tags, max_results=10):
        """Find episodes matching any of the given tags.

        Args:
            tags: List of tag strings to match.
            max_results: Maximum episodes to return.
        Returns:
            List of index entries.
        """
        tags_lower = [t.lower() for t in tags]
        matches = [
            ep for ep in self._index
            if any(t.lower() in tags_lower for t in ep.get("tags", []))
        ]
        matches.sort(key=lambda x: x["importance_score"], reverse=True)
        return matches[:max_results]

    def get_full_episode(self, event_id):
        """Read the full episode entry (including raw_exchange) from disk.

        Args:
            event_id: The event_id to look up.
        Returns:
            Full dict entry, or None if not found.
        """
        if not os.path.exists(self.store_path):
            return None

        with open(self.store_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("event_id") == event_id:
                        return entry
                except json.JSONDecodeError:
                    continue
        return None

    def reinforce(self, event_id):
        """Bump the reinforcement count for an episode (it was re-referenced).

        This resets the forgetting curve decay for this memory.
        """
        # Update in-memory index
        for ep in self._index:
            if ep["event_id"] == event_id:
                ep["reinforcement_count"] = ep.get("reinforcement_count", 0) + 1
                break

        # Update on disk (rewrite the specific line)
        # For simplicity, we rewrite the whole file — episodic files are small
        self._rewrite_entry(event_id, {"reinforcement_count": lambda x: x.get("reinforcement_count", 0) + 1})

    def _rewrite_entry(self, event_id, updates):
        """Rewrite a single entry in the JSONL file with updated fields.

        Args:
            event_id: The event_id to update.
            updates: Dict of {field: new_value_or_callable}. If callable, it receives the entry.
        """
        if not os.path.exists(self.store_path):
            return

        lines = []
        with open(self.store_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        with open(self.store_path, "w", encoding="utf-8") as f:
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    f.write(line)
                    continue
                try:
                    entry = json.loads(stripped)
                    if entry.get("event_id") == event_id:
                        for field, value in updates.items():
                            if callable(value):
                                entry[field] = value(entry)
                            else:
                                entry[field] = value
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                except json.JSONDecodeError:
                    f.write(line)

    # ----------------------------------------------------------
    # STATS
    # ----------------------------------------------------------
    def count(self):
        """Return total number of stored episodes."""
        return len(self._index)

    def get_stats(self):
        """Return summary statistics about the episodic memory."""
        if not self._index:
            return {"total": 0, "avg_importance": 0.0, "date_range": None}

        importances = [ep["importance_score"] for ep in self._index]
        timestamps = [ep["timestamp"] for ep in self._index]
        return {
            "total": len(self._index),
            "avg_importance": sum(importances) / len(importances),
            "date_range": (min(timestamps), max(timestamps)),
            "high_importance_count": sum(1 for i in importances if i >= 0.7),
        }
