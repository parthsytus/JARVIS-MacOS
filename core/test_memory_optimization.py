import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from core.jarvis_core import semantic_router, memory, build_live_context

def simulate_turn(text, jarvis_state):
    print(f"--- Simulating Turn: '{text}' ---")
    tools_to_pass = None
    if semantic_router:
        routing_query = text.lower()
        wake_words = ["hey jarvis", "jarvis"]
        for w in wake_words:
            if w in routing_query:
                routing_query = routing_query.replace(w, "").strip()
        if not routing_query:
            routing_query = text
        tools_to_pass = semantic_router.route(routing_query)
        
    live_context = build_live_context(jarvis_state)
    
    is_direct_command = tools_to_pass and len(tools_to_pass) == 1
    
    if memory and not is_direct_command:
        print("  -> Memory Fetched!")
        # dynamic_mem = memory.get_dynamic_context(text)
    else:
        print("  -> Memory SKIPPED!")
        
    tool_names = [t['function']['name'] for t in tools_to_pass] if tools_to_pass else "None (Conversation)"
    print(f"  -> Tools Passed: {tool_names}")
    print()

if __name__ == "__main__":
    state = {}
    simulate_turn("what is the cpu usage?", state)
    simulate_turn("tell me a story about a brave knight", state)
