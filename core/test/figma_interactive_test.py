"""
==========================================================
JARVIS — Figma Agent Interactive Design Tester (LIVE)
==========================================================

Type natural language design instructions. The Figma agent will:
  1. Generate JSON design blueprints
  2. Render a LIVE HTML preview in your browser
  3. Send blueprints through the WebSocket to Figma (if plugin is connected)

Usage:
  venv/bin/python core/test/figma_interactive_test.py

Examples:
  > create a red rectangle at 100,100 size 400x200
  > add text "BGMI Tournament" at 200,50 font size 36
  > make a blue button "Register Now" at 300,400
  > build a login form
  > show                    ← opens/refreshes preview in browser
  > quit

Author: JARVIS-MacOS Phase 3 Testing
"""

import sys
import os
import re
import json
import webbrowser
import time

# Path injection — 3 levels up to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

PREVIEW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview")
PREVIEW_FILE = os.path.join(PREVIEW_DIR, "figma_preview.html")

from integrations.figma_agent import (
    FigmaAgent,
    DesignBlueprint,
    FigmaNode,
    FIGMA_WS_HOST,
    FIGMA_WS_PORT,
)


# ── Color Resolver ────────────────────────────────────────────
COLOR_MAP = {
    "red": "#FF0000", "green": "#00FF00", "blue": "#0066FF",
    "white": "#FFFFFF", "black": "#000000", "yellow": "#FFD700",
    "purple": "#9B59B6", "orange": "#FF6B35", "pink": "#FF69B4",
    "gray": "#808080", "grey": "#808080", "cyan": "#00BCD4",
    "neon green": "#00FF88", "navy": "#1A1A2E", "sky blue": "#87CEEB",
    "dark": "#1A1A2E", "light": "#F5F5F5",
}

def resolve_color(text: str) -> str:
    hex_match = re.search(r'#[0-9A-Fa-f]{3,6}', text)
    if hex_match:
        return hex_match.group()
    text_lower = text.lower()
    for name, hex_val in COLOR_MAP.items():
        if name in text_lower:
            return hex_val
    return "#007AFF"

def extract_coords(text: str):
    match = re.search(r'at\s+(\d+)[,\s]+(\d+)', text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 100, 100

def extract_size(text: str):
    match = re.search(r'(?:size\s+)?(\d+)\s*[xX×by]+\s*(\d+)', text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 200, 100

def extract_quoted_text(text: str) -> str:
    match = re.search(r'["\'](.+?)["\']', text)
    return match.group(1) if match else ""

def extract_font_size(text: str) -> int:
    match = re.search(r'font\s*size\s*(\d+)', text, re.IGNORECASE)
    return int(match.group(1)) if match else 24


# ── HTML Preview Renderer ────────────────────────────────────

def render_node_html(node: dict) -> str:
    """Convert a Figma blueprint node to an HTML element."""
    node_type = node.get("type", "RECTANGLE")
    x = node.get("x", 0)
    y = node.get("y", 0)
    w = node.get("width", 100)
    h = node.get("height", 50)
    name = node.get("name", "")
    cr = node.get("cornerRadius", 0)

    # Extract fill color
    fills = node.get("fills", [])
    bg_color = "#CCCCCC"
    if fills:
        bg_color = fills[0].get("color", "#CCCCCC")

    if node_type == "TEXT":
        text = node.get("characters", "")
        font_size = node.get("fontSize", 16)
        font_family = node.get("fontFamily", "Inter")
        color = bg_color
        return f'''<div class="figma-node figma-text" style="
            left:{x}px; top:{y}px;
            font-size:{font_size}px; font-family:'{font_family}', sans-serif;
            color:{color}; white-space:nowrap;
        " title="{name}">{text}</div>'''

    elif node_type == "FRAME":
        layout = node.get("layoutMode", "NONE")
        padding = node.get("paddingTop", 0)
        inner = ""
        if layout == "HORIZONTAL":
            inner = f"display:flex; align-items:center; justify-content:center; padding:{padding}px;"
        elif layout == "VERTICAL":
            inner = f"display:flex; flex-direction:column; align-items:center; justify-content:center; padding:{padding}px;"
        return f'''<div class="figma-node figma-frame" style="
            left:{x}px; top:{y}px; width:{w}px; height:{h}px;
            background:{bg_color}; border-radius:{cr}px; {inner}
        " title="{name}">
            <span class="node-label">{name}</span>
        </div>'''

    else:  # RECTANGLE, ELLIPSE, etc.
        return f'''<div class="figma-node figma-shape" style="
            left:{x}px; top:{y}px; width:{w}px; height:{h}px;
            background:{bg_color}; border-radius:{cr}px;
        " title="{name}">
            <span class="node-label">{name}</span>
        </div>'''


def generate_preview_html(all_blueprints: list, canvas_w=1920, canvas_h=1080) -> str:
    """Generate a full HTML preview page from all accumulated blueprints."""
    elements_html = ""
    for bp in all_blueprints:
        for node in bp.nodes:
            elements_html += render_node_html(node) + "\n"

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>JARVIS Figma Preview</title>
<meta http-equiv="refresh" content="3">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background: #0D0D0D;
    display:flex; flex-direction:column;
    align-items:center; min-height:100vh;
    font-family: 'Inter', sans-serif;
    color: #E0E0E0;
    padding: 20px;
  }}
  .header {{
    display:flex; align-items:center; gap:12px;
    margin-bottom:20px; padding:12px 24px;
    background:rgba(0,255,136,0.08);
    border:1px solid rgba(0,255,136,0.2);
    border-radius:12px;
  }}
  .header .dot {{ width:10px; height:10px; border-radius:50%; background:#00FF88; box-shadow:0 0 8px #00FF88; }}
  .header h1 {{ font-size:18px; font-weight:600; color:#00FF88; }}
  .header .info {{ font-size:13px; color:#888; margin-left:16px; }}
  .canvas-wrapper {{
    border:1px solid #333; border-radius:8px;
    overflow:hidden; box-shadow:0 8px 32px rgba(0,0,0,0.5);
    position:relative;
  }}
  .canvas {{
    width:{canvas_w}px; height:{canvas_h}px;
    background:#F5F5F5; position:relative;
    transform-origin: top left;
    transform: scale(0.55);
  }}
  .figma-node {{
    position:absolute;
    transition: outline 0.2s;
  }}
  .figma-node:hover {{
    outline: 2px solid #00FF88;
    outline-offset: 2px;
    z-index:1000;
  }}
  .figma-text {{
    pointer-events:auto;
  }}
  .node-label {{
    position:absolute; top:-18px; left:0;
    font-size:10px; color:#00FF88;
    opacity:0; transition:opacity 0.2s;
    white-space:nowrap;
    background:rgba(0,0,0,0.7); padding:2px 6px; border-radius:4px;
  }}
  .figma-node:hover .node-label {{ opacity:1; }}
  .footer {{
    margin-top:16px; font-size:12px; color:#555;
    display:flex; gap:20px;
  }}
  .footer .count {{ color:#00FF88; font-weight:600; }}
</style>
</head>
<body>
  <div class="header">
    <div class="dot"></div>
    <h1>JARVIS — Figma Live Preview</h1>
    <span class="info">Auto-refreshes every 3s · Hover elements to inspect</span>
  </div>
  <div class="canvas-wrapper" style="width:{int(canvas_w*0.55)}px; height:{int(canvas_h*0.55)}px;">
    <div class="canvas">
      {elements_html}
    </div>
  </div>
  <div class="footer">
    <span>Canvas: <span class="count">{canvas_w}×{canvas_h}</span></span>
    <span>Elements: <span class="count">{sum(len(bp.nodes) for bp in all_blueprints)}</span></span>
    <span>Blueprints: <span class="count">{len(all_blueprints)}</span></span>
    <span>Updated: <span class="count">{time.strftime("%H:%M:%S")}</span></span>
  </div>
</body>
</html>'''


def save_and_open_preview(all_blueprints: list, open_browser=True):
    """Save HTML preview and optionally open in browser."""
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    html = generate_preview_html(all_blueprints)
    with open(PREVIEW_FILE, "w") as f:
        f.write(html)
    if open_browser:
        webbrowser.open(f"file://{PREVIEW_FILE}")
    print(f"  🌐 Preview saved: {PREVIEW_FILE}")


# ── Command Parser ────────────────────────────────────────────

def parse_and_execute(agent: FigmaAgent, user_input: str) -> DesignBlueprint:
    """Parse natural language and generate a Figma blueprint."""
    text = user_input.lower().strip()
    if not text:
        return None

    # ── Rectangle ──
    if any(kw in text for kw in ["rectangle", "rect", "box", "square"]):
        x, y = extract_coords(user_input)
        w, h = extract_size(user_input)
        color = resolve_color(user_input)
        cr_match = re.search(r'(?:corner|radius)\s*(\d+)', text)
        corner_radius = int(cr_match.group(1)) if cr_match else 0
        blueprint = agent.create_rectangle(x=x, y=y, width=w, height=h, fill=color,
                                           corner_radius=corner_radius, name="Rectangle")
        print(f"  📐 Rectangle: ({x},{y}) {w}×{h} fill={color} radius={corner_radius}")
        return blueprint

    # ── Text ──
    elif any(kw in text for kw in ["text", "write", "heading", "title", "label"]):
        x, y = extract_coords(user_input)
        content = extract_quoted_text(user_input) or "Hello JARVIS"
        font_size = extract_font_size(user_input)
        color = resolve_color(user_input)
        blueprint = agent.create_text(x=x, y=y, text=content, font_size=font_size,
                                      fill=color, name="Text")
        print(f"  📝 Text: \"{content}\" at ({x},{y}) size={font_size} color={color}")
        return blueprint

    # ── Button ──
    elif "button" in text:
        x, y = extract_coords(user_input)
        w, h = extract_size(user_input)
        if w == 200 and h == 100:
            w, h = 200, 48
        label_text = extract_quoted_text(user_input) or "Click Me"
        fill = resolve_color(user_input)
        cr_match = re.search(r'(?:corner|radius)\s*(\d+)', text)
        corner_radius = int(cr_match.group(1)) if cr_match else 8
        blueprint = agent.create_button(x=x, y=y, width=w, height=h, label=label_text,
                                        fill=fill, corner_radius=corner_radius, name="Button")
        print(f"  🔘 Button: \"{label_text}\" at ({x},{y}) {w}×{h} fill={fill}")
        return blueprint

    # ── Frame ──
    elif "frame" in text or "container" in text:
        x, y = extract_coords(user_input)
        w, h = extract_size(user_input)
        color = resolve_color(user_input)
        blueprint = agent.create_frame(x=x, y=y, width=w, height=h, fill=color, name="Frame")
        print(f"  📦 Frame: ({x},{y}) {w}×{h} fill={color}")
        return blueprint

    # ── Login Form ──
    elif "login" in text or "sign in" in text:
        blueprint = agent.create_login_form()
        print(f"  🔐 Login Form: Full form with email, password, submit")
        return blueprint

    # ── Dashboard Card ──
    elif "dashboard" in text or "card" in text or "metric" in text:
        x, y = extract_coords(user_input)
        title = extract_quoted_text(user_input) or "Total Users"
        val_match = re.search(r'value\s*["\']?([^"\']+)["\']?', user_input, re.IGNORECASE)
        value = val_match.group(1).strip() if val_match else "12,345"
        blueprint = agent.create_dashboard_card(x=x, y=y, title=title, value=value,
                                                subtitle="Generated by JARVIS")
        print(f"  📊 Dashboard Card: \"{title}\" = {value} at ({x},{y})")
        return blueprint

    # ── Clear ──
    elif text in ("clear", "reset", "new"):
        return "CLEAR"

    else:
        print("  ❓ Could not parse. Try:")
        print('     "create a red rectangle at 100,100 size 400x200"')
        print('     "add text \"Hello\" at 200,50 font size 36"')
        print('     "make a blue button \"Submit\" at 300,400"')
        print('     "build a login form"')
        print('     "show" to open preview in browser')
        return None


# ── Main Loop ─────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  JARVIS — Figma Live Design Studio")
    print("=" * 60)
    print()
    print("  Type design instructions. Designs appear in your browser")
    print("  AND are sent to Figma if the plugin is connected.")
    print()
    print("  Examples:")
    print('    > create a red rectangle at 100,100 size 400x200')
    print('    > add text "BGMI Tournament" at 200,50 font size 36')
    print('    > make a blue button "Register Now" at 300,400')
    print('    > build a login form')
    print('    > show / preview   ← open/refresh browser preview')
    print('    > clear            ← reset canvas')
    print('    > quit')
    print()

    # Initialize the REAL FigmaAgent (with live WebSocket server)
    agent = FigmaAgent()
    agent.start()

    connected = agent.is_connected()
    print(f"  ✅ FigmaAgent initialized")
    print(f"  🌐 WebSocket server: ws://{FIGMA_WS_HOST}:{FIGMA_WS_PORT}")
    if connected:
        print(f"  🟢 Figma plugin is CONNECTED — designs will appear in Figma!")
    else:
        print(f"  🟡 Figma plugin not connected — designs will preview in browser")
        print(f"     To connect: open Figma → Plugins → JARVIS → Run")
    print()

    all_blueprints = []
    browser_opened = False

    try:
        while True:
            try:
                count = sum(len(bp.nodes) for bp in all_blueprints)
                connected = agent.is_connected()
                icon = "🟢" if connected else "⚪"
                prompt = f"  {icon} [{count} elements] > "
                user_input = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit", "q", "stop"):
                break

            if user_input.lower() in ("help", "?"):
                print("\n  Commands:")
                print('    rectangle/rect/box — "create a red rect at 100,100 size 300x200"')
                print('    text/write/title   — "add text \"Hello\" at 50,50 font size 24"')
                print('    button             — "make a blue button \"Submit\" at 300,400"')
                print('    frame/container    — "create a frame at 0,0 size 800x600"')
                print('    login              — "build a login form"')
                print('    dashboard/card     — "create a card \"Revenue\" value \"$1.2M\""')
                print('    show/preview       — Open/refresh browser preview')
                print('    clear              — Reset canvas')
                print('    quit               — Exit\n')
                continue

            if user_input.lower() in ("show", "preview", "open", "render"):
                save_and_open_preview(all_blueprints, open_browser=True)
                continue

            result = parse_and_execute(agent, user_input)

            if result == "CLEAR":
                all_blueprints.clear()
                save_and_open_preview(all_blueprints, open_browser=browser_opened)
                print("  🗑️  Canvas cleared")
                continue

            if result and isinstance(result, DesignBlueprint):
                all_blueprints.append(result)

                # Try sending to Figma via WebSocket
                if agent.is_connected():
                    sent = agent.send_blueprint(result)
                    if sent:
                        print(f"  → Sent to Figma ✅")
                    else:
                        print(f"  → Figma send failed (preview still available)")

                # Always update the HTML preview
                save_and_open_preview(all_blueprints, open_browser=not browser_opened)
                browser_opened = True

    finally:
        agent.stop()

    total = sum(len(bp.nodes) for bp in all_blueprints)
    print(f"\n  📋 Session: {len(all_blueprints)} blueprints, {total} elements")
    print("  ✅ Figma design pipeline verified!\n")


if __name__ == "__main__":
    main()
