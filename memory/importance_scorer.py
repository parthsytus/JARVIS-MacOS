# ==========================================================
# JARVIS — Memory Importance Scorer
# Two mechanisms:
#   1. Salience Detection — score new memories at creation time
#   2. Forgetting Curve — decay old memories at retrieval time
# ==========================================================

import re
import math
import time
from datetime import datetime


class ImportanceScorer:
    """Scores memory importance and applies Ebbinghaus-style forgetting curves."""

    # Patterns that indicate high-importance statements
    HIGH_IMPORTANCE_PATTERNS = [
        # Life events / decisions
        (r'\b(quit|leave|break\s*up|die|dying|kill|fail|drop\s*out|fired|expelled)\b', 0.2),
        (r'\b(graduate|married|engaged|pregnant|born|passed\s*away|promoted)\b', 0.2),
        # Strong feelings / values
        (r'\b(love|hate|dream|goal|plan|decide|decided|scared|afraid|depressed|anxious)\b', 0.15),
        (r'\b(happy|excited|thrilled|proud|devastated|miserable|lonely)\b', 0.15),
        # Absolute / emphatic statements
        (r'\b(never|always|forever|promise|swear|worst|best|biggest|first\s*time)\b', 0.1),
        # Personal identity
        (r'\b(i\s+am|i\'m|my\s+name|i\s+believe|i\s+think|i\s+feel|i\s+want)\b', 0.1),
        # Future plans
        (r'\b(tomorrow|next\s+week|next\s+month|next\s+year|planning\s+to|going\s+to)\b', 0.05),
        # Relationships
        (r'\b(friend|girlfriend|boyfriend|mom|dad|brother|sister|family|professor)\b', 0.1),
    ]

    # Patterns that indicate LOW-importance (routine/trivial)
    LOW_IMPORTANCE_PATTERNS = [
        r'\b(what\s+time|what\s+day|weather|temperature|volume|brightness|play\s+music)\b',
        r'\b(open\s+chrome|open\s+spotify|set\s+timer|convert|calculate|search\s+for)\b',
        r'\b(hi|hello|hey|bye|goodbye|good\s+morning|good\s+night|thanks|thank\s+you|ok|okay)\b',
    ]

    def __init__(self, decay_tau_days=30):
        """
        Args:
            decay_tau_days: Forgetting curve time constant in days.
                           After tau days, a memory decays to ~37% of original importance.
        """
        self.tau_days = decay_tau_days
        # Pre-compile patterns
        self._high_patterns = [
            (re.compile(pattern, re.IGNORECASE), boost) 
            for pattern, boost in self.HIGH_IMPORTANCE_PATTERNS
        ]
        self._low_patterns = [
            re.compile(pattern, re.IGNORECASE) 
            for pattern in self.LOW_IMPORTANCE_PATTERNS
        ]

    # ----------------------------------------------------------
    # SALIENCE DETECTION (at memory creation time)
    # ----------------------------------------------------------
    def score_importance(self, text, emotion_valence=0.0, is_repeated=False):
        """Score the importance of a new memory.

        Args:
            text: The memory text to evaluate.
            emotion_valence: Float -1.0 to 1.0 indicating emotional intensity.
            is_repeated: Whether this topic has been mentioned before.
        Returns:
            Float 0.0 to 1.0 indicating importance.
        """
        if not text:
            return 0.1

        score = 0.3  # Baseline — every memory has some value

        # 1. Emotional intensity (|valence| → more important)
        score += abs(emotion_valence) * 0.25

        # 2. High-importance keyword patterns
        for pattern, boost in self._high_patterns:
            if pattern.search(text):
                score += boost

        # 3. Low-importance suppression
        low_matches = sum(1 for p in self._low_patterns if p.search(text))
        if low_matches >= 2:
            score *= 0.5  # Reduce if it's clearly routine
        elif low_matches == 1:
            score *= 0.75

        # 4. Repetition bonus (user keeps mentioning → important to them)
        if is_repeated:
            score += 0.15

        # 5. Text length heuristic (longer = likely more substantial)
        word_count = len(text.split())
        if word_count > 50:
            score += 0.1
        elif word_count < 10:
            score -= 0.05

        # 6. Question vs statement (questions about self are important)
        if re.search(r'\b(should\s+I|do\s+you\s+think|what\s+do\s+I|am\s+I)\b', text, re.IGNORECASE):
            score += 0.1

        return max(0.05, min(score, 1.0))  # Clamp to [0.05, 1.0]

    # ----------------------------------------------------------
    # FORGETTING CURVE (at retrieval time)
    # ----------------------------------------------------------
    def apply_decay(self, importance, timestamp, reinforcement_count=0):
        """Apply Ebbinghaus forgetting curve decay to a memory's importance.

        Formula: I(t) = I₀ × e^(-t/τ)

        Reinforcement (re-referencing a memory) extends its effective lifespan.

        Args:
            importance: Original importance score (I₀).
            timestamp: When the memory was created (ISO string or Unix timestamp).
            reinforcement_count: How many times this memory was re-referenced.
        Returns:
            Decayed importance score.
        """
        # Parse timestamp
        if isinstance(timestamp, str):
            try:
                dt = datetime.fromisoformat(timestamp)
                age_seconds = (datetime.now() - dt).total_seconds()
            except ValueError:
                age_seconds = 0.0
        elif isinstance(timestamp, (int, float)):
            age_seconds = time.time() - timestamp
        else:
            age_seconds = 0.0

        age_days = max(age_seconds / 86400, 0)

        # Reinforcement extends effective tau
        # Each reinforcement adds 50% to the time constant
        effective_tau = self.tau_days * (1 + 0.5 * reinforcement_count)

        # Ebbinghaus decay
        decayed = importance * math.exp(-age_days / effective_tau)

        # Floor: high-importance memories never fully vanish
        if importance >= 0.8:
            floor = importance * 0.15  # 15% floor for critical memories
        elif importance >= 0.5:
            floor = importance * 0.05  # 5% floor for moderate memories
        else:
            floor = 0.0  # Trivial memories can fully decay

        return max(decayed, floor)

    def rank_memories(self, memories, query_relevance_scores=None):
        """Rank a list of memories by combined importance (decay + relevance).

        Args:
            memories: List of dicts with 'importance_score', 'timestamp',
                      'reinforcement_count' fields.
            query_relevance_scores: Optional list of float (0-1) relevance
                                    scores aligned with memories list.
        Returns:
            List of (index, combined_score) tuples, sorted descending.
        """
        scored = []
        for i, mem in enumerate(memories):
            importance = mem.get("importance_score", 0.5)
            timestamp = mem.get("timestamp", datetime.now().isoformat())
            reinforcements = mem.get("reinforcement_count", 0)

            # Apply decay
            decayed_importance = self.apply_decay(importance, timestamp, reinforcements)

            # Combine with query relevance if provided
            if query_relevance_scores and i < len(query_relevance_scores):
                relevance = query_relevance_scores[i]
                # Weighted combination: 40% importance, 60% relevance
                combined = 0.4 * decayed_importance + 0.6 * relevance
            else:
                combined = decayed_importance

            scored.append((i, combined))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
