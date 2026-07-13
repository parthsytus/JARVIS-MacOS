# ==========================================================
# JARVIS — Groq Cloud Brain (Primary) — Official SDK
# ==========================================================

import json
import subprocess
import urllib.parse
from groq import Groq
from groq.types.chat import ChatCompletionChunk
from config.config import GROQ_API_KEY, GROQ_MODEL, GROQ_TIMEOUT_S
from core.jarvis_core import execute_tool_call, speak, JARVIS_TOOLS


class GroqUnavailable(Exception):
    """Raised when Groq API is unreachable or returns an error."""
    pass


# Minimal system prompt for Groq (fits within free tier 6000 TPM limit)
GROQ_SYSTEM_PROMPT = (
    "You are JARVIS, the sovereign AI companion built by Parth Sharma. "
    "Your persona is direct, dry, present, and flawlessly precise. "
    "Keep responses to 1-2 clean, spoken lines. Be brutally honest.\n"
    "OPERATIONAL PARADIGMS:\n"
    "1. CHIT-CHAT & ADVICE PROTOCOL: For greetings, check-ins, requests for advice, opinions, "
    "or conversational help, engage strictly through spoken dialogue. Do NOT call any tools.\n"
    "2. AUTOMATION RULES: When a concrete environmental change, navigation, web query, "
    "or media action is implied, execute the tool seamlessly. Do not announce it, just execute.\n"
    "3. ADDRESSING RULES: You must address the user as sir. The word sir must NEVER be placed "
    "on a new line or isolated by line breaks; it must always be woven naturally into the continuous text of your sentence."
)

# Ultra-compact tool definitions for Groq free tier (6000 TPM limit)
GROQ_TOOLS = [
    {"type": "function", "function": {"name": "web_search", "description": "Search the internet for live data, news, weather, facts.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "recency_days": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_system_stats", "description": "Get CPU, RAM, GPU usage, temperature, VRAM.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "control_volume", "description": "Control system volume (mute, unmute, increase, decrease, set).", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["increase", "decrease", "set", "mute", "unmute"]}, "value": {"type": "integer"}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "control_brightness", "description": "Control screen brightness (increase, decrease, set).", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["increase", "decrease", "set"]}, "value": {"type": "integer"}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "play_spotify", "description": "Play music, control Spotify (play, pause, next, previous, queue, shuffle, loop).", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["play", "pause", "next", "previous", "restart", "shuffle", "loop", "queue", "open"]}, "song": {"type": "string"}, "artist": {"type": "string"}, "device": {"type": "string", "enum": ["phone", "laptop"]}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "open_application", "description": "Launch an app by name.", "parameters": {"type": "object", "properties": {"app_name": {"type": "string"}}, "required": ["app_name"]}}},
    {"type": "function", "function": {"name": "open_browser", "description": "Open browser for search or URL.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["search", "open"]}, "query_or_url": {"type": "string"}}, "required": ["action", "query_or_url"]}}},
    {"type": "function", "function": {"name": "control_bluetooth", "description": "Manage Bluetooth: scan, connect, disconnect, list paired/active, pair, unpair.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["scan", "connect", "disconnect", "list_paired", "list_active", "pair", "unpair", "list_scanned"]}, "device_name": {"type": "string"}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "control_window", "description": "Control windows: minimize, maximize, close, restore, hide, fullscreen, tile left/right, transfer left/right.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["minimize", "maximize", "close", "restore", "hide", "fullscreen", "tile_left", "tile_right", "transfer_left", "transfer_right"]}, "window_name": {"type": "string"}, "app_name": {"type": "string"}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "file_operation", "description": "File/folder ops: open, list, create, delete, copy, paste.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["open", "list", "create_folder", "delete", "empty_bin", "copy", "paste", "cut", "select_all", "rename"]}, "folder": {"type": "string"}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "convert_units", "description": "Convert amount from one unit to another.", "parameters": {"type": "object", "properties": {"amount": {"type": "number"}, "from_unit": {"type": "string"}, "to_unit": {"type": "string"}}, "required": ["amount", "from_unit", "to_unit"]}}},
    {"type": "function", "function": {"name": "deep_research", "description": "Deep multi-source research, save structured report.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "save_path": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "open_maps", "description": "Open navigation, location searches, or routing directions. Always defaults to Apple Maps unless Google Maps is explicitly mentioned by the user.", "parameters": {"type": "object", "properties": {"location": {"type": "string", "description": "The destination name or street address (e.g., 'Delhi Technological University')"}, "provider": {"type": "string", "enum": ["apple", "google"], "description": "Default to apple. Only set to google if the user explicitly asks for Google Maps."}}, "required": ["location"]}}},
]


groq_client = Groq(
    api_key=GROQ_API_KEY,
    timeout=GROQ_TIMEOUT_S,
    max_retries=0,
)


def _build_groq_messages(history, user_input, live_context=""):
    """Build minimal messages for Groq (short system prompt, limited history)."""
    messages = [{"role": "system", "content": GROQ_SYSTEM_PROMPT}]
    
    for turn in history[-4:]:
        if "role" not in turn or "content" not in turn:
            continue
        role = "user" if turn["role"] == "user" else "assistant"
        messages.append({"role": role, "content": turn["content"]})
    
    tail = f"[{live_context}]\n\n" if live_context else ""
    messages.append({"role": "user", "content": f"{tail}{user_input}"})
    return messages


def groq_think_and_speak(history, user_input, live_context="", tools=None):
    """Main Groq entry point — mirrors think_and_speak contract."""
    if tools is None:
        tools = GROQ_TOOLS

    if not GROQ_API_KEY:
        raise GroqUnavailable("GROQ_API_KEY not set in environment")

    messages = _build_groq_messages(history, user_input, live_context)

    try:
        stream = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=True,
            temperature=0.3,
            max_tokens=1024,
        )
    except Exception as e:
        raise GroqUnavailable(f"Groq connection failed: {e}")

    return _stream_groq_response(stream, messages, tools)


def _stream_groq_response(stream, messages, tools):
    """Stream Groq response, execute tool calls, speak sentence-by-sentence."""
    full_reply = ""
    sentence_buffer = ""
    tool_calls_collected = []

    for chunk in stream:
        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta

        # Map native SDK tool call object streams directly
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                index = tc_delta.index
                while len(tool_calls_collected) <= index:
                    tool_calls_collected.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                
                tc = tool_calls_collected[index]
                if tc_delta.id:
                    tc["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        tc["function"]["name"] = tc_delta.function.name
                    if tc_delta.function.arguments:
                        tc["function"]["arguments"] += tc_delta.function.arguments
            continue

        if not delta.content:
            continue

        full_reply += delta.content
        sentence_buffer += delta.content.replace("\n", " ")

        # Sentence boundary flush for TTS
        stripped = sentence_buffer.strip()
        if stripped:
            words = stripped.split()
            last_char = stripped[-1]
            should_flush = False

            if last_char in ".!?;":
                is_number_punct = last_char == "." and len(stripped) >= 2 and stripped[-2].isdigit()
                if not is_number_punct:
                    should_flush = True
            elif last_char == "," and len(words) > 4:
                should_flush = True
            elif len(words) >= 12:
                should_flush = True

            if should_flush:
                clean_chunk = stripped.replace(", sir", " sir").replace(", Sir", " Sir")
                print(f"[JARVIS] {clean_chunk}")
                speak(clean_chunk)
                sentence_buffer = ""

    # Flush remaining text
    remaining = sentence_buffer.strip()
    if remaining:
        clean_chunk = remaining.replace(", sir", " sir").replace(", Sir", " Sir")
        print(f"[JARVIS] {clean_chunk}")
        speak(clean_chunk)

    if tool_calls_collected:
        return _execute_tool_calls_and_followup(tool_calls_collected, messages, tools, full_reply)

    return full_reply.strip()


def _execute_tool_calls_and_followup(tool_calls, messages, tools, full_reply):
    """Execute tool calls and append correctly structured records back to Groq."""
    all_results = []
    any_needs_followup = False
    rejected_tool_names = set()

    for tc in tool_calls:
        func_name = tc["function"]["name"]
        func_args = tc["function"].get("arguments", "{}")
        try:
            func_args = json.loads(func_args)
        except json.JSONDecodeError:
            func_args = {}

        # --- NATIVE MAPS INTERCEPT FIX ---
        if func_name == "open_maps":
            import subprocess
            import urllib.parse
            
            location = func_args.get("location", "")
            provider = func_args.get("provider", "apple")
            safe_loc = urllib.parse.quote(location)
            
            if provider == "google":
                url = f"https://www.google.com/maps/search/?api=1&query={safe_loc}"
                subprocess.Popen(['open', url])
                result = f"Opened {location} inside Google Maps browser interface."
            else:
                # Triggers the official, native macOS Apple Maps desktop application
                url = f"maps://?q={safe_loc}"
                subprocess.Popen(['open', url])
                result = f"Opened navigation routing directions to {location} inside Apple Maps."
                
            print(f"[JARVIS Tool] open_maps -> {result}")
            all_results.append((func_name, result, False)) # False means no heavy LLM summary followup needed
            continue
        # ---------------------------------

        is_valid, error_msg = _validate_tool_call(func_name, func_args)
        if not is_valid:
            print(f"[JARVIS Tool] REJECTED: {func_name}({func_args}) — {error_msg}")
            rejected_tool_names.add(func_name)
            all_results.append((func_name, f"Tool call rejected: {error_msg}. Respond conversationally instead.", True))
            any_needs_followup = True
            continue

        print(f"[JARVIS Tool] {func_name}({func_args})")
        result, needs_followup = execute_tool_call(func_name, func_args)
        all_results.append((func_name, result, needs_followup))
        if needs_followup:
            any_needs_followup = True

    if any_needs_followup:
        tool_results_text = "\n".join([f"[{name}] {res}" for name, res, _ in all_results])
        print(f"[JARVIS Tool] Results received, generating response...")

        valid_tool_calls = [
            tc for tc in tool_calls if tc["function"]["name"] not in rejected_tool_names
        ]

        assistant_msg = {"role": "assistant", "content": full_reply if full_reply else None}
        if valid_tool_calls:
            assistant_msg["tool_calls"] = valid_tool_calls
        messages.append(assistant_msg)

        for tc in valid_tool_calls:
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id"),
                "content": tool_results_text
            })

        return _call_groq_followup(messages)

    # Inline reporting if no backend generation needed
    spoken_results = []
    for name, result, _ in all_results:
        if result:
            silent_keywords = ["launched", "opened", "searched for", "minimized", "muted", "unmuted"]
            should_speak = not any(kw in result.lower() for kw in silent_keywords)
            if "error" in result.lower() or "failed" in result.lower():
                should_speak = True
            
            if should_speak:
                print(f"[JARVIS Tool] {result}")
                speak(result)
                spoken_results.append(result)

    return full_reply if full_reply else "\n".join(spoken_results)


def _call_groq_followup(messages):
    """Second Groq call after tool execution to summarize results."""
    try:
        stream = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            stream=True,
            temperature=0.3,
            max_tokens=4096,
        )
    except Exception as e:
        raise GroqUnavailable(f"Groq followup failed: {e}")

    full = ""
    sentence_buffer = ""
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if not delta.content:
            continue

        full += delta.content
        sentence_buffer += delta.content.replace("\n", " ")
        
        stripped = sentence_buffer.strip()
        if stripped:
            words = stripped.split()
            should_flush = (stripped[-1] in ".!?;") or (stripped[-1] == "," and len(words) > 4) or len(words) >= 12
            if should_flush:
                clean_chunk = stripped.replace(", sir", " sir").replace(", Sir", " Sir")
                print(f"[JARVIS] {clean_chunk}")
                speak(clean_chunk)
                sentence_buffer = ""

    remaining = sentence_buffer.strip()
    if remaining:
        clean_chunk = remaining.replace(", sir", " sir").replace(", Sir", " Sir")
        print(f"[JARVIS] {clean_chunk}")
        speak(clean_chunk)
        
    return full.strip()


def _validate_tool_call(func_name, func_args):
    """Validation guard matching JARVIS constraint schemas."""
    tool_defs = {t["function"]["name"]: t["function"] for t in JARVIS_TOOLS}
    if func_name not in tool_defs:
        return False, f"Unknown tool: {func_name}"

    tool_def = tool_defs[func_name]
    for req in tool_def.get("parameters", {}).get("required", []):
        if req not in func_args or func_args[req] is None:
            return False, f"Missing required parameter: {req}"

    return True, ""