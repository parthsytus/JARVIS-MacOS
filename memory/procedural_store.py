# ==========================================================
# JARVIS — Procedural Memory Store
# Learned patterns of how Parth likes things done:
# response style, command preferences, interaction rhythm.
# Updated by the consolidator analyzing patterns over time.
# ==========================================================

import os
import json
from datetime import datetime


class ProceduralStore:
    """JSON-backed procedural memory — learned interaction patterns and preferences."""

    DEFAULT_SCHEMA = {
        "response_style": {
            "observed_patterns": [],
        },
        "interaction_patterns": {
            "session_times": [],
            "common_topics": [],
            "avg_session_turns": 0,
            "total_sessions": 0,
        },
        "command_preferences": {},
        "_meta": {
            "created": None,
            "last_updated": None,
        }
    }

    def __init__(self, store_path):
        """
        Args:
            store_path: Path to procedural_prefs.json
        """
        self.store_path = store_path
        os.makedirs(os.path.dirname(store_path), exist_ok=True)
        self._data = self._load()

    def _load(self):
        """Load from disk or create empty schema."""
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                print(f"[Memory] Procedural store loaded — {data.get('interaction_patterns', {}).get('total_sessions', 0)} sessions tracked.")
                return data
            except (json.JSONDecodeError, IOError) as e:
                print(f"[Memory] Warning: Could not load procedural store ({e}). Starting fresh.")

        data = dict(self.DEFAULT_SCHEMA)
        data["_meta"]["created"] = datetime.now().isoformat()
        self._save(data)
        print("[Memory] Procedural store initialized (empty).")
        return data

    def _save(self, data=None):
        """Persist to disk."""
        if data is None:
            data = self._data
        data["_meta"]["last_updated"] = datetime.now().isoformat()
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ----------------------------------------------------------
    # RESPONSE STYLE
    # ----------------------------------------------------------
    def add_style_observation(self, observation):
        """Record an observed interaction style preference.

        Args:
            observation: String describing the pattern (e.g. "Prefers bullet points for task lists")
        """
        patterns = self._data.setdefault("response_style", {}).setdefault("observed_patterns", [])

        # Deduplicate (case-insensitive)
        if not any(p.lower() == observation.lower() for p in patterns):
            patterns.append(observation)
            # Keep only the most recent 50 patterns
            if len(patterns) > 50:
                self._data["response_style"]["observed_patterns"] = patterns[-50:]
            self._save()

    def get_style_patterns(self):
        """Get all observed style patterns."""
        return self._data.get("response_style", {}).get("observed_patterns", [])

    # ----------------------------------------------------------
    # INTERACTION PATTERNS
    # ----------------------------------------------------------
    def record_session(self, num_turns, session_hour, topics=None):
        """Record metadata about a completed session.

        Args:
            num_turns: Number of conversational turns in the session.
            session_hour: Hour of day (0-23) when session started.
            topics: List of topic strings detected in the session.
        """
        patterns = self._data.setdefault("interaction_patterns", {})

        # Session times (keep last 100 for pattern analysis)
        session_times = patterns.setdefault("session_times", [])
        session_times.append(session_hour)
        if len(session_times) > 100:
            patterns["session_times"] = session_times[-100:]

        # Running average of session length
        total = patterns.get("total_sessions", 0)
        avg = patterns.get("avg_session_turns", 0)
        new_total = total + 1
        patterns["avg_session_turns"] = round(((avg * total) + num_turns) / new_total, 1)
        patterns["total_sessions"] = new_total

        # Common topics (accumulate with counts)
        if topics:
            common = patterns.setdefault("common_topics", [])
            # Store as list of {topic, count} dicts
            topic_dict = {t["topic"]: t["count"] for t in common if isinstance(t, dict)}
            for topic in topics:
                topic_lower = topic.lower().strip()
                if topic_lower:
                    topic_dict[topic_lower] = topic_dict.get(topic_lower, 0) + 1
            # Convert back, keep top 30
            sorted_topics = sorted(topic_dict.items(), key=lambda x: x[1], reverse=True)[:30]
            patterns["common_topics"] = [{"topic": t, "count": c} for t, c in sorted_topics]

        self._save()

    def get_peak_hours(self):
        """Analyze session times to find peak usage hours.

        Returns:
            List of (hour, count) tuples, sorted by frequency.
        """
        times = self._data.get("interaction_patterns", {}).get("session_times", [])
        if not times:
            return []

        hour_counts = {}
        for h in times:
            hour_counts[h] = hour_counts.get(h, 0) + 1

        return sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)

    def get_common_topics(self, top_n=10):
        """Get the most common conversation topics.

        Returns:
            List of {topic, count} dicts.
        """
        topics = self._data.get("interaction_patterns", {}).get("common_topics", [])
        return topics[:top_n]

    # ----------------------------------------------------------
    # COMMAND PREFERENCES
    # ----------------------------------------------------------
    def set_command_preference(self, key, value):
        """Set a command/tool preference.

        Args:
            key: Preference key (e.g. 'music_service', 'default_browser').
            value: Preference value (e.g. 'spotify', 'chrome').
        """
        self._data.setdefault("command_preferences", {})[key] = value
        self._save()

    def get_command_preferences(self):
        """Get all command preferences."""
        return self._data.get("command_preferences", {})

    # ----------------------------------------------------------
    # CONTEXT GENERATION
    # ----------------------------------------------------------
    def build_context_block(self):
        """Generate a text block for LLM context injection.

        Returns a formatted string with procedural memory insights.
        """
        lines = []

        # Style patterns
        patterns = self.get_style_patterns()
        if patterns:
            lines.append(f"[Interaction Style] {'; '.join(patterns[-5:])}.")

        # Peak hours
        peak = self.get_peak_hours()
        if peak:
            top_hours = [f"{h}:00" for h, _ in peak[:3]]
            lines.append(f"[Typical Hours] Most active around {', '.join(top_hours)}.")

        # Common topics
        topics = self.get_common_topics(5)
        if topics:
            topic_names = [t["topic"] for t in topics]
            lines.append(f"[Common Topics] {', '.join(topic_names)}.")

        # Session stats
        stats = self._data.get("interaction_patterns", {})
        total = stats.get("total_sessions", 0)
        if total > 0:
            avg = stats.get("avg_session_turns", 0)
            lines.append(f"[Sessions] {total} total sessions, avg {avg} turns each.")

        return "\n".join(lines)

    # ----------------------------------------------------------
    # STATS
    # ----------------------------------------------------------
    def get_stats(self):
        """Return summary statistics."""
        return {
            "total_sessions": self._data.get("interaction_patterns", {}).get("total_sessions", 0),
            "style_patterns": len(self.get_style_patterns()),
            "common_topics": len(self.get_common_topics()),
            "command_prefs": len(self.get_command_preferences()),
        }
