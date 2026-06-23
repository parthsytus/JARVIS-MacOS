# ==========================================================
# JARVIS — Semantic Memory Store
# Persistent facts about Parth: identity, goals, relationships,
# preferences, and a triple-based knowledge graph.
# JARVIS learns these organically from conversations.
# ==========================================================

import os
import json
import time
from datetime import datetime


class SemanticStore:
    """JSON-backed semantic memory — structured facts about Parth."""

    DEFAULT_SCHEMA = {
        "identity": {},
        "goals": [],
        "relationships": {},
        "preferences": {},
        "facts": [],
        "_meta": {
            "created": None,
            "last_updated": None,
            "version": 1,
        }
    }

    def __init__(self, store_path):
        """
        Args:
            store_path: Path to semantic_facts.json
        """
        self.store_path = store_path
        os.makedirs(os.path.dirname(store_path), exist_ok=True)
        self._data = self._load()

    def _load(self):
        """Load facts from disk, or create empty schema."""
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                print(f"[Memory] Semantic store loaded — {self.count_from(data)} facts.")
                return data
            except (json.JSONDecodeError, IOError) as e:
                print(f"[Memory] Warning: Could not load semantic store ({e}). Starting fresh.")

        # Start with empty schema — JARVIS learns from scratch
        data = dict(self.DEFAULT_SCHEMA)
        data["_meta"]["created"] = datetime.now().isoformat()
        self._save(data)
        print("[Memory] Semantic store initialized (empty — will learn from conversations).")
        return data

    def _save(self, data=None):
        """Persist to disk."""
        if data is None:
            data = self._data
        data["_meta"]["last_updated"] = datetime.now().isoformat()
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def count_from(data):
        """Count total facts in a data dict."""
        count = 0
        count += len(data.get("identity", {}))
        count += len(data.get("goals", []))
        count += sum(len(v) if isinstance(v, list) else 1 for v in data.get("relationships", {}).values())
        count += len(data.get("preferences", {}))
        count += len(data.get("facts", []))
        return count

    # ----------------------------------------------------------
    # IDENTITY
    # ----------------------------------------------------------
    def set_identity(self, key, value):
        """Set an identity field (e.g. 'name', 'university', 'field').

        Args:
            key: Field name (e.g. 'name', 'university').
            value: Field value (e.g. 'Parth Sharma', 'DTU').
        """
        self._data.setdefault("identity", {})[key] = value
        self._save()

    def get_identity(self, key=None):
        """Get identity info. If key is None, return all."""
        if key:
            return self._data.get("identity", {}).get(key)
        return self._data.get("identity", {})

    # ----------------------------------------------------------
    # GOALS
    # ----------------------------------------------------------
    def add_goal(self, goal_text, importance=0.5):
        """Add a new goal (deduplicates by text).

        Args:
            goal_text: Description of the goal.
            importance: How important this goal seems (0.0 to 1.0).
        Returns:
            True if added, False if duplicate.
        """
        goals = self._data.setdefault("goals", [])

        # Deduplicate: check if a similar goal already exists
        for existing in goals:
            if existing["goal"].lower().strip() == goal_text.lower().strip():
                # Update importance if higher
                if importance > existing.get("importance", 0):
                    existing["importance"] = importance
                    self._save()
                return False

        goals.append({
            "goal": goal_text,
            "added": datetime.now().isoformat(),
            "importance": importance,
        })
        self._save()
        return True

    def get_goals(self):
        """Get all goals, sorted by importance."""
        goals = self._data.get("goals", [])
        return sorted(goals, key=lambda x: x.get("importance", 0), reverse=True)

    # ----------------------------------------------------------
    # RELATIONSHIPS
    # ----------------------------------------------------------
    def add_relationship(self, category, name, details=None):
        """Add a relationship entry.

        Args:
            category: Relationship category (e.g. 'friends', 'family', 'professors').
            name: Person's name.
            details: Optional details string.
        """
        relationships = self._data.setdefault("relationships", {})
        category_list = relationships.setdefault(category, [])

        # Deduplicate
        for existing in category_list:
            if isinstance(existing, dict) and existing.get("name", "").lower() == name.lower():
                if details:
                    existing["details"] = details
                self._save()
                return

        entry = {"name": name, "added": datetime.now().isoformat()}
        if details:
            entry["details"] = details
        category_list.append(entry)
        self._save()

    def get_relationships(self, category=None):
        """Get relationships. If category is None, return all."""
        if category:
            return self._data.get("relationships", {}).get(category, [])
        return self._data.get("relationships", {})

    # ----------------------------------------------------------
    # PREFERENCES
    # ----------------------------------------------------------
    def set_preference(self, key, value):
        """Set a preference (e.g. 'favorite_music': 'lo-fi hip hop').

        Args:
            key: Preference key.
            value: Preference value.
        """
        self._data.setdefault("preferences", {})[key] = value
        self._save()

    def get_preferences(self):
        """Get all preferences."""
        return self._data.get("preferences", {})

    # ----------------------------------------------------------
    # KNOWLEDGE GRAPH (Triple Store)
    # ----------------------------------------------------------
    def add_fact(self, subject, predicate, obj, confidence=1.0):
        """Add a knowledge triple (e.g. Parth → studies_at → DTU).

        Args:
            subject: The subject entity.
            predicate: The relationship/predicate.
            obj: The object entity.
            confidence: Confidence score 0.0 to 1.0.
        Returns:
            True if added, False if duplicate.
        """
        facts = self._data.setdefault("facts", [])

        # Deduplicate
        for existing in facts:
            if (existing["subject"].lower() == subject.lower() and
                existing["predicate"].lower() == predicate.lower() and
                existing["object"].lower() == obj.lower()):
                # Update confidence if higher
                if confidence > existing.get("confidence", 0):
                    existing["confidence"] = confidence
                    self._save()
                return False

        facts.append({
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "confidence": confidence,
            "added": datetime.now().isoformat(),
        })
        self._save()
        return True

    def get_facts(self, subject=None, predicate=None):
        """Query the knowledge graph.

        Args:
            subject: Filter by subject (optional).
            predicate: Filter by predicate (optional).
        Returns:
            List of matching fact triples.
        """
        facts = self._data.get("facts", [])
        results = facts

        if subject:
            results = [f for f in results if f["subject"].lower() == subject.lower()]
        if predicate:
            results = [f for f in results if f["predicate"].lower() == predicate.lower()]

        return results

    # ----------------------------------------------------------
    # BULK OPERATIONS (used by consolidator)
    # ----------------------------------------------------------
    def ingest_extracted_facts(self, extracted):
        """Ingest a batch of facts extracted by the LLM from a conversation.

        Args:
            extracted: List of dicts with keys like 'type', 'key', 'value',
                       or 'subject', 'predicate', 'object'.
        Returns:
            Number of new facts added.
        """
        added = 0
        for fact in extracted:
            fact_type = fact.get("type", "fact")

            if fact_type == "identity":
                key = fact.get("key", "")
                value = fact.get("value", "")
                if key and value:
                    self.set_identity(key, value)
                    added += 1

            elif fact_type == "goal":
                goal = fact.get("value", fact.get("goal", ""))
                if goal:
                    was_new = self.add_goal(goal, fact.get("importance", 0.5))
                    if was_new:
                        added += 1

            elif fact_type == "relationship":
                category = fact.get("category", "other")
                name = fact.get("name", fact.get("value", ""))
                if name:
                    self.add_relationship(category, name, fact.get("details"))
                    added += 1

            elif fact_type == "preference":
                key = fact.get("key", "")
                value = fact.get("value", "")
                if key and value:
                    self.set_preference(key, value)
                    added += 1

            elif fact_type == "fact":
                subj = fact.get("subject", "Parth")
                pred = fact.get("predicate", "")
                obj = fact.get("object", fact.get("value", ""))
                if pred and obj:
                    was_new = self.add_fact(subj, pred, obj, fact.get("confidence", 0.8))
                    if was_new:
                        added += 1

        return added

    # ----------------------------------------------------------
    # CONTEXT GENERATION
    # ----------------------------------------------------------
    def build_context_block(self):
        """Generate a text block for LLM context injection.

        Returns a formatted string like:
            [About Parth] Name: Parth Sharma. Studies at DTU.
            [Goals] Build a game studio (importance: 0.9).
            [Preferences] Likes lo-fi music.
        """
        lines = []

        # Identity
        identity = self.get_identity()
        if identity:
            id_parts = [f"{k}: {v}" for k, v in identity.items()]
            lines.append(f"[About Parth] {'. '.join(id_parts)}.")

        # Goals
        goals = self.get_goals()
        if goals:
            goal_parts = [g["goal"] for g in goals[:5]]  # Top 5 goals
            lines.append(f"[Goals] {'; '.join(goal_parts)}.")

        # Relationships
        relationships = self.get_relationships()
        if relationships:
            rel_parts = []
            for category, people in relationships.items():
                names = [p["name"] if isinstance(p, dict) else str(p) for p in people[:3]]
                if names:
                    rel_parts.append(f"{category}: {', '.join(names)}")
            if rel_parts:
                lines.append(f"[Relationships] {'; '.join(rel_parts)}.")

        # Preferences
        prefs = self.get_preferences()
        if prefs:
            pref_parts = [f"{k}: {v}" for k, v in list(prefs.items())[:5]]
            lines.append(f"[Preferences] {'; '.join(pref_parts)}.")

        # Key facts (top 10 by confidence)
        facts = self._data.get("facts", [])
        if facts:
            top_facts = sorted(facts, key=lambda x: x.get("confidence", 0), reverse=True)[:10]
            fact_parts = [f"{f['subject']} {f['predicate']} {f['object']}" for f in top_facts]
            lines.append(f"[Known Facts] {'; '.join(fact_parts)}.")

        return "\n".join(lines)

    # ----------------------------------------------------------
    # STATS
    # ----------------------------------------------------------
    def count(self):
        """Return total number of stored facts/entries."""
        return self.count_from(self._data)
