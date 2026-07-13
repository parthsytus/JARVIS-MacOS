# ============================================================
# JARVIS — Intelligent Intent Classifier
# Model-driven intent classification, zero hardcoded keywords
# ============================================================

import json
import requests
from config.config import OLLAMA_URL, FAST_MODEL, FAST_NUM_CTX, FAST_NUM_PREDICT, FAST_KEEP_ALIVE

# Actual tool names from JARVIS_TOOLS — classifier must use these exact names
JARVIS_TOOL_NAMES = [
    "web_search", "get_system_stats", "control_volume", "control_brightness",
    "play_spotify", "open_application", "open_browser", "control_bluetooth",
    "control_window", "file_operation", "convert_units", "deep_research"
]

INTENT_CLASSIFIER_PROMPT = """You are an intent classifier for JARVIS. Analyze the user's input and classify it into exactly ONE category.

Categories:
1. TOOL_ACTION - User wants to perform a concrete action that requires calling a tool (play music, open app, change brightness/volume, bluetooth, file ops, window control, search web, etc.). Includes indirect phrasing like "volume too loud" → lower volume, "screen too bright" → lower brightness, "check activity monitor" → open app.
2. DEEP_RESEARCH - User wants deep research: multi-source search, analysis, pros/cons, save structured file. Phrases like "research X", "deep search X", "investigate X and save". Complex, multi-step, needs large model.
3. KNOWLEDGE_QUERY - User asks a factual question needing web search (current prices, specs, news, technical info). Single search sufficient. Not deep research.
4. CONVERSATION - Chat, opinions, venting, thinking out loud, general discussion. No tool needed. Includes statements about ambient environment/weather: "today the day is too bright", "the sun is bright", "it's a sunny day", "day is bright", "weather is nice".
5. MODE_SWITCH - User explicitly wants to switch models: "use complex mode", "use think mode", "switch to large model", etc.
6. FOLLOWUP_SUGGESTION - User mentions future intent that suggests a proactive action: "gym at 6pm" → suggest alarm, "meeting at 3" → suggest reminder.

CRITICAL DISTINCTIONS:
- "too much brightness" / "screen too bright" / "brightness too high" → TOOL_ACTION (screen brightness control)
- "today the day is too bright" / "sun is bright" / "it's a bright day" / "weather is bright" → CONVERSATION (ambient description, NOT a command)

Available tools (use EXACT names in suggested_tools):
- web_search: Search internet for live data, weather, factual questions
- get_system_stats: Get CPU, RAM, GPU usage, temperature, VRAM
- control_volume: Mute, unmute, increase, decrease, set system volume
- control_brightness: Increase, decrease, set screen brightness
- play_spotify: Play, pause, next, previous, queue, shuffle, loop Spotify
- open_application: Launch an app by name (Chrome, Discord, Calculator, etc.)
- open_browser: Open browser tab/window - search or open URL
- control_bluetooth: Scan, connect, disconnect, list paired/active, pair, unpair
- control_window: Minimize, maximize, close, restore, hide, fullscreen, tile left/right, transfer left/right
- file_operation: Open, list, create, delete, copy, paste files/folders
- convert_units: Convert amount from one unit to another (e.g., km to miles, celsius to fahrenheit)
- deep_research: Conduct deep multi-source research and save structured report

Output ONLY valid JSON:
{
  "category": "TOOL_ACTION|DEEP_RESEARCH|KNOWLEDGE_QUERY|CONVERSATION|MODE_SWITCH|FOLLOWUP_SUGGESTION",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation",
  "suggested_tools": ["tool1", "tool2"] or [],
  "needs_complex_model": true/false,
  "followup_suggestion": "proactive suggestion text or null"
}"""

def classify_intent(user_input, history=None):
    """
    Classify user intent using the fast model.
    Returns dict with category, confidence, reasoning, suggested_tools, needs_complex_model, followup_suggestion.
    """
    # Build messages for classification
    messages = [
        {"role": "system", "content": INTENT_CLASSIFIER_PROMPT}
    ]
    
    if history:
        # Include last 3 turns for context
        for turn in history[-6:]:
            role = "user" if turn.get("role") == "user" else "assistant"
            messages.append({"role": role, "content": turn.get("content", "")})
    
    messages.append({"role": "user", "content": user_input})
    
    payload = {
        "model": FAST_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": "json",
        "keep_alive": FAST_KEEP_ALIVE,
        "options": {
            "num_ctx": FAST_NUM_CTX,
            "num_predict": FAST_NUM_PREDICT,
            "num_gpu": 99,
            "temperature": 0.1  # Low temp for consistent classification
        }
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        content = result.get("message", {}).get("content", "").strip()
        
        # Parse JSON from response
        # Handle potential markdown code blocks
        if content.startswith("```"):
            lines = content.split('\n')
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()
        
        # Try to parse JSON, handle malformed responses
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from text
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                except:
                    raise
            else:
                raise
        
        # Validate required fields
        required = ["category", "confidence", "reasoning", "suggested_tools", "needs_complex_model", "followup_suggestion"]
        for field in required:
            if field not in parsed:
                parsed[field] = [] if field == "suggested_tools" else (False if field == "needs_complex_model" else None)
        
        # Validate suggested_tools against known tool names — filter out hallucinated names
        if isinstance(parsed.get("suggested_tools"), list):
            parsed["suggested_tools"] = [t for t in parsed["suggested_tools"] if t in JARVIS_TOOL_NAMES]
        
        return parsed
        
    except Exception as e:
        print(f"[Intent Classifier] Error: {e}")
        # Fallback: assume conversation
        return {
            "category": "CONVERSATION",
            "confidence": 0.5,
            "reasoning": "Classification failed, defaulting to conversation",
            "suggested_tools": [],
            "needs_complex_model": False,
            "followup_suggestion": None
        }

def should_escalate_to_complex(classification, user_input):
    """
    Determine if task should escalate to complex model.
    """
    if classification.get("needs_complex_model"):
        return True
    if classification.get("category") == "DEEP_RESEARCH":
        return True
    if classification.get("category") == "MODE_SWITCH":
        return True
    return False

def get_routing_decision(classification):
    """
    Convert classification to routing action.
    Returns: ("fast_tool", tools_list) | ("complex", reason) | ("conversation", None) | ("ask_escalate", reason)
    """
    cat = classification.get("category")
    needs_complex = classification.get("needs_complex_model", False)
    
    if cat == "TOOL_ACTION":
        return ("fast_tool", classification.get("suggested_tools", []))
    elif cat == "DEEP_RESEARCH":
        return ("complex", "deep research task")
    elif cat == "KNOWLEDGE_QUERY":
        return ("fast_tool", ["web_search"])
    elif cat == "MODE_SWITCH":
        return ("complex", "user requested complex mode")
    elif cat == "FOLLOWUP_SUGGESTION":
        return ("fast_tool", classification.get("suggested_tools", []))
    elif needs_complex:
        return ("ask_escalate", classification.get("reasoning", "task may need complex model"))
    else:
        return ("conversation", None)