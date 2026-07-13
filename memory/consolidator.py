# ==========================================================
# JARVIS — Session Consolidator (STM → LTM Pipeline)
# Runs at session end AND periodically during long sessions.
# Processes raw conversation history into structured long-term
# memory: episodic events, semantic facts, procedural patterns.
# ==========================================================

import json
import time
import re
from datetime import datetime

import requests
import threading


class SessionConsolidator:
    """Converts short-term session history into structured long-term memories."""

    # Prompt for the LLM to summarize a session and extract facts
    CONSOLIDATION_PROMPT = """You are JARVIS's memory system. Analyze this conversation between JARVIS and Parth.

CONVERSATION:
{conversation}

Respond ONLY with a valid JSON object (no markdown, no code blocks). Use this exact schema:
{{
    "session_summary": "1-2 sentence summary of what this conversation was about",
    "emotion_valence": 0.0,
    "topics": ["topic1", "topic2"],
    "extracted_facts": [
        {{"type": "identity|goal|relationship|preference|fact", "key": "field_name", "value": "field_value"}},
        {{"type": "fact", "subject": "Parth", "predicate": "relationship_verb", "object": "target"}}
    ],
    "style_observations": ["any observations about how Parth likes to communicate"],
    "importance": 0.5
}}

Rules:
- emotion_valence: -1.0 (very negative) to 1.0 (very positive). 0.0 = neutral.
- importance: 0.0 (trivial chat) to 1.0 (life-changing event). Most casual chats = 0.3-0.4.
- extracted_facts: ONLY include concrete, specific facts about Parth. Not opinions or guesses.
  - type "identity": things like name, age, university, field of study, location
  - type "goal": things Parth wants to achieve or is working toward  
  - type "relationship": people Parth mentions (friends, family, professors)
  - type "preference": things Parth likes/dislikes, preferences
  - type "fact": any other factual statement (use subject/predicate/object)
- style_observations: how Parth communicates (e.g. "prefers short answers", "uses Hindi sometimes")
- topics: 2-5 topic keywords for this conversation
- If there are no facts to extract, use an empty list [].
- If it's just casual chat with no personal info, that's fine — just summarize and set low importance.

RESPOND WITH JSON ONLY:"""

    def __init__(self, ollama_url, ollama_model, vector_store, episodic_store,
                 semantic_store, procedural_store, importance_scorer):
        """
        Args:
            ollama_url: Ollama API URL (e.g. http://localhost:11434/api/chat)
            ollama_model: Ollama model name (e.g. llama3.2)
            vector_store: VectorStore instance.
            episodic_store: EpisodicStore instance.
            semantic_store: SemanticStore instance.
            procedural_store: ProceduralStore instance.
            importance_scorer: ImportanceScorer instance.
        """
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model
        self.vector = vector_store
        self.episodic = episodic_store
        self.semantic = semantic_store
        self.procedural = procedural_store
        self.scorer = importance_scorer

    def consolidate(self, session_history, session_start_time=None):
        """Run the full STM → LTM consolidation pipeline.

        Args:
            session_history: List of {'role': 'user'|'jarvis', 'content': str} dicts.
            session_start_time: datetime of when the session started.
        Returns:
            Dict with consolidation results, or None on failure.
        """
        if not session_history or len(session_history) < 2:
            print("[Memory] Skipping consolidation — session too short.")
            return None

        print(f"[Memory] Consolidating session ({len(session_history)} turns)...")

        # Step 1: Format the conversation for the LLM
        conversation_text = self._format_conversation(session_history)

        # Step 2: Ask LLM to analyze
        analysis = self._analyze_with_llm(conversation_text)
        if not analysis:
            # Fallback: store raw conversation without LLM analysis
            print("[Memory] LLM analysis failed. Storing raw summary as fallback.")
            analysis = self._fallback_analysis(session_history)

        # Step 3: Score importance (combine LLM's score with our own)
        llm_importance = analysis.get("importance", 0.5)
        text_importance = self.scorer.score_importance(
            conversation_text,
            emotion_valence=analysis.get("emotion_valence", 0.0),
        )
        # Average the LLM's judgment with our rule-based scorer
        final_importance = (llm_importance + text_importance) / 2

        # Step 4: Store in Episodic Memory
        raw_exchange = conversation_text[:5000]  # Cap raw transcript at 5KB
        event_id = self.episodic.add_episode(
            summary=analysis.get("session_summary", "Conversation with Parth."),
            raw_exchange=raw_exchange,
            emotion_valence=analysis.get("emotion_valence", 0.0),
            importance_score=final_importance,
            tags=analysis.get("topics", []),
        )
        print(f"[Memory] Episodic entry created: {event_id} (importance: {final_importance:.2f})")

        # Step 5: Store in Vector Store (for RAG retrieval)
        summary = analysis.get("session_summary", "")
        if summary:
            self.vector.add_memory(
                text=summary,
                metadata={
                    "source": "session_consolidation",
                    "event_id": event_id,
                    "importance": final_importance,
                    "emotion_valence": analysis.get("emotion_valence", 0.0),
                    "tags": analysis.get("topics", []),
                    "timestamp": time.time(),
                },
            )

        # Also embed individual high-importance exchanges
        self._embed_key_exchanges(session_history, final_importance, event_id)

        # Step 6: Extract and store Semantic Facts
        extracted_facts = analysis.get("extracted_facts", [])
        if extracted_facts:
            new_facts = self.semantic.ingest_extracted_facts(extracted_facts)
            print(f"[Memory] {new_facts} new semantic facts learned.")

        # Step 7: Update Procedural Memory
        style_obs = analysis.get("style_observations", [])
        for obs in style_obs:
            self.procedural.add_style_observation(obs)

        session_hour = (session_start_time or datetime.now()).hour
        self.procedural.record_session(
            num_turns=len(session_history),
            session_hour=session_hour,
            topics=analysis.get("topics", []),
        )

        print("[Memory] Consolidation complete.")
        return {
            "event_id": event_id,
            "importance": final_importance,
            "facts_learned": len(extracted_facts),
            "summary": analysis.get("session_summary", ""),
        }

    def consolidate_mid_session(self, session_history, already_consolidated_count):
        """Run a lighter consolidation during a long session.

        Called every ~20 turns to prevent data loss if JARVIS crashes.
        Only processes turns that haven't been consolidated yet.

        Args:
            session_history: Full session history so far.
            already_consolidated_count: Number of turns already consolidated.
        Returns:
            Updated consolidated count, or the same if nothing was done.
        """
        new_turns = session_history[already_consolidated_count:]
        if len(new_turns) < 6:  # Need at least 3 exchanges (6 turns)
            return already_consolidated_count

        print(f"[Memory] Mid-session consolidation ({len(new_turns)} new turns)...")

        # Use a lighter analysis — just embed the key exchanges
        conversation_text = self._format_conversation(new_turns)
        importance = self.scorer.score_importance(conversation_text)

        # Store the chunk in vector store for retrieval
        summary = f"Mid-session conversation chunk ({len(new_turns)} turns)"
        self.vector.add_memory(
            text=conversation_text[:2000],  # Cap at 2KB for mid-session
            metadata={
                "source": "mid_session",
                "importance": importance,
                "timestamp": time.time(),
            },
        )

        # Try LLM analysis for fact extraction (non-blocking, best-effort)
        try:
            analysis = self._analyze_with_llm(conversation_text)
            if analysis:
                facts = analysis.get("extracted_facts", [])
                if facts:
                    new_count = self.semantic.ingest_extracted_facts(facts)
                    print(f"[Memory] Mid-session: {new_count} new facts learned.")
        except Exception as e:
            print(f"[Memory] Mid-session LLM analysis skipped: {e}")

        return len(session_history)

    def _format_conversation(self, history):
        """Format conversation history into readable text."""
        lines = []
        for turn in history:
            role = "Parth" if turn["role"] == "user" else "JARVIS"
            lines.append(f"{role}: {turn['content']}")
        return "\n".join(lines)

    def _analyze_with_llm(self, conversation_text):
        """Send conversation to Ollama for analysis and fact extraction.

        Returns parsed JSON dict, or None on failure.
        """
        prompt = self.CONSOLIDATION_PROMPT.format(conversation=conversation_text)

        try:
            response = requests.post(
                self.ollama_url,
                json={
                    "model": self.ollama_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "keep_alive": -1,
                    "format": "json",
                    "options": {
                        "num_ctx": 4096,
                        "num_predict": 500,
                        "temperature": 0.3,  # Low temp for structured output
                        "num_gpu": 99,
                    },
                },
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            content = data.get("message", {}).get("content", "")

            # Parse JSON from LLM response (handle common formatting issues)
            return self._parse_llm_json(content)

        except requests.exceptions.ConnectionError:
            print("[Memory] Ollama not available for consolidation.")
            return None
        except requests.exceptions.Timeout:
            print("[Memory] Ollama consolidation timed out.")
            return None
        except Exception as e:
            print(f"[Memory] LLM analysis error: {e}")
            return None

    def _parse_llm_json(self, text):
        """Robustly parse JSON from LLM output (handles markdown blocks, etc)."""
        # Strip markdown code blocks if present
        text = text.strip()
        if text.startswith("```"):
            # Remove ```json ... ``` wrapper
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            print(f"[Memory] Could not parse LLM JSON output: {text[:200]}...")
            return None

    def _fallback_analysis(self, session_history):
        """Generate a basic analysis without LLM (fallback)."""
        # Count words to estimate importance
        total_words = sum(len(t["content"].split()) for t in session_history)
        user_turns = [t["content"] for t in session_history if t["role"] == "user"]
        combined_user_text = " ".join(user_turns)

        importance = self.scorer.score_importance(combined_user_text)

        # Generate a basic summary from first user message
        first_msg = user_turns[0] if user_turns else "Unknown conversation"
        summary = f"Conversation about: {first_msg[:100]}"

        return {
            "session_summary": summary,
            "emotion_valence": 0.0,
            "topics": [],
            "extracted_facts": [],
            "style_observations": [],
            "importance": importance,
        }

    def _embed_key_exchanges(self, session_history, session_importance, event_id):
        """Embed individual high-value exchanges into the vector store.

        Not every turn is worth embedding — only ones where Parth says
        something substantive or personal.
        """
        batch_texts = []
        batch_metas = []

        for i in range(0, len(session_history) - 1, 2):
            user_turn = session_history[i] if session_history[i]["role"] == "user" else None
            if not user_turn:
                continue

            text = user_turn["content"]
            turn_importance = self.scorer.score_importance(text)

            # Only embed if this specific turn is notable (> 0.4)
            if turn_importance > 0.4 and len(text.split()) > 5:
                # Include JARVIS's response for context
                jarvis_response = ""
                if i + 1 < len(session_history):
                    jarvis_response = session_history[i + 1]["content"]

                exchange_text = f"Parth said: {text}"
                if jarvis_response:
                    exchange_text += f" | JARVIS replied: {jarvis_response[:200]}"

                batch_texts.append(exchange_text)
                batch_metas.append({
                    "source": "key_exchange",
                    "event_id": event_id,
                    "importance": turn_importance,
                    "timestamp": time.time(),
                })

        if batch_texts:
            self.vector.add_memories_batch(batch_texts, batch_metas)
            print(f"[Memory] Embedded {len(batch_texts)} key exchanges.")
