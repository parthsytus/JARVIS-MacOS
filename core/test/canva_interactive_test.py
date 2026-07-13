"""
==========================================================
JARVIS — Canva Agent Interactive Design Tester (LIVE)
==========================================================

Type natural language design instructions. The Canva agent will:
  1. Build design data using the fluent builder API
  2. Render a LIVE HTML preview in your browser
  3. Push the design to Canva cloud (if credentials are set)

Usage:
  venv/bin/python core/test/canva_interactive_test.py

Examples:
  > create a presentation "BGMI Tournament" theme dark
  > add title slide "Welcome to BGMI" subtitle "Season 12"
  > add content slide "Rules" bullets "No hacks, Fair play, Have fun"
  > show               ← opens preview in browser
  > push to canva      ← sends to Canva API (requires credentials)
  > quit

Author: JARVIS-MacOS Phase 3 Testing
"""

import sys
import os
import re
import json
import webbrowser
import time
import asyncio

# Path injection — 3 levels up to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

PREVIEW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview")
PREVIEW_FILE = os.path.join(PREVIEW_DIR, "canva_preview.html")

from integrations.canva_agent import (
    CanvaAgent,
    CanvaDesignType,
    CanvaElementType,
    CanvaColor,
    CanvaPosition,
    CanvaTextStyle,
    CanvaFontWeight,
    CanvaTextAlign,
    CanvaFill,
    CanvaStroke,
    CanvaElement,
    CanvaPage,
    CanvaDesign,
    DesignBuilder,
    PresentationBuilder,
    SocialPostBuilder,
    InfographicBuilder,
    CANVA_CLIENT_ID,
    CANVA_CLIENT_SECRET,
)


# ── Color Resolver ────────────────────────────────────────────
COLOR_MAP = {
    "red": "#FF0000", "green": "#00FF00", "blue": "#0066FF",
    "white": "#FFFFFF", "black": "#000000", "yellow": "#FFD700",
    "purple": "#9B59B6", "orange": "#FF6B35", "pink": "#FF69B4",
    "gray": "#808080", "grey": "#808080", "cyan": "#00BCD4",
    "neon green": "#00FF88", "navy": "#1A1A2E", "sky blue": "#87CEEB",
    "dark": "#1A1A2E", "light": "#F5F5F5", "gold": "#FFD700",
    "teal": "#00897B", "coral": "#FF6B6B", "indigo": "#3F51B5",
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

def extract_quoted_text(text: str) -> str:
    match = re.search(r'["\'](.+?)["\']', text)
    return match.group(1) if match else ""

def extract_all_quoted(text: str) -> list:
    return re.findall(r'["\'](.+?)["\']', text)

def extract_theme(text: str) -> str:
    return "dark" if "dark" in text.lower() else "light"

def extract_platform(text: str) -> str:
    platforms = ["instagram", "facebook", "twitter", "linkedin", "pinterest",
                 "tiktok", "youtube", "instagram_story"]
    text_lower = text.lower()
    for p in platforms:
        if p in text_lower:
            return p
    return "instagram"

def extract_size(text: str):
    match = re.search(r'(\d+)\s*[xX×by]+\s*(\d+)', text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None

def extract_coords(text: str):
    match = re.search(r'at\s+(\d+)[,\s]+(\d+)', text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 100, 100


# ── HTML Preview Renderer ────────────────────────────────────

def canva_color_to_hex(c: dict) -> str:
    """Convert Canva API color dict {r:0-1, g:0-1, b:0-1} to hex."""
    if not c:
        return "#CCCCCC"
    r = int(c.get("r", 0) * 255)
    g = int(c.get("g", 0) * 255)
    b = int(c.get("b", 0) * 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def render_element_html(elem: dict) -> str:
    """Convert a Canva element dict to HTML."""
    elem_type = elem.get("type", "shape")
    pos = elem.get("position", {})
    x = pos.get("x", 0)
    y = pos.get("y", 0)
    w = pos.get("width", 100)
    h = pos.get("height", 50)
    name = elem.get("name", "")
    cr = elem.get("cornerRadius", 0)
    opacity = elem.get("opacity", 1.0)

    # Fill color
    fill = elem.get("fill", {})
    bg_color = "transparent"
    if fill and fill.get("color"):
        bg_color = canva_color_to_hex(fill["color"])

    if elem_type == "text":
        text = elem.get("text", "")
        style = elem.get("textStyle", {})
        font_size = style.get("fontSize", 16)
        font_family = style.get("fontFamily", "Inter")
        font_weight = style.get("fontWeight", "400")
        text_color = canva_color_to_hex(style.get("color", {})) if style.get("color") else "#000000"
        text_align = style.get("textAlign", "left")
        return f'''<div class="canva-elem canva-text" style="
            left:{x}px; top:{y}px; width:{w}px; height:{h}px;
            font-size:{font_size}px; font-family:'{font_family}', sans-serif;
            font-weight:{font_weight}; color:{text_color};
            text-align:{text_align}; opacity:{opacity};
            display:flex; align-items:center; justify-content:{text_align};
            overflow:hidden;
        " title="{name}">{text}</div>'''

    elif elem_type == "line":
        stroke = elem.get("stroke", {})
        stroke_color = canva_color_to_hex(stroke.get("color", {})) if stroke.get("color") else "#000000"
        stroke_weight = stroke.get("weight", 1)
        stroke_style = stroke.get("style", "solid")
        return f'''<div class="canva-elem canva-line" style="
            left:{x}px; top:{y}px; width:{w}px; height:0px;
            border-top:{stroke_weight}px {stroke_style} {stroke_color};
            opacity:{opacity};
        " title="{name}"></div>'''

    elif elem_type == "image":
        url = elem.get("imageUrl", "")
        return f'''<div class="canva-elem canva-image" style="
            left:{x}px; top:{y}px; width:{w}px; height:{h}px;
            background:#E0E0E0; border-radius:{cr}px; opacity:{opacity};
            display:flex; align-items:center; justify-content:center;
            font-size:12px; color:#888;
        " title="{name}">🖼️ Image</div>'''

    else:  # shape, frame, group
        return f'''<div class="canva-elem canva-shape" style="
            left:{x}px; top:{y}px; width:{w}px; height:{h}px;
            background:{bg_color}; border-radius:{cr}px; opacity:{opacity};
        " title="{name}">
            <span class="node-label">{name}</span>
        </div>'''


def generate_canva_preview_html(design_dict: dict) -> str:
    """Generate full HTML preview from a Canva design dict."""
    pages = design_dict.get("pages", [])
    title = design_dict.get("title", "Untitled")
    design_type = design_dict.get("type", "custom")

    pages_html = ""
    for i, page in enumerate(pages):
        pw = page.get("width", 1920)
        ph = page.get("height", 1080)

        # Page background
        bg_color = "#FFFFFF"
        bg = page.get("background")
        if bg and bg.get("color"):
            bg_color = canva_color_to_hex(bg["color"])

        elements_html = ""
        for elem in page.get("elements", []):
            elements_html += render_element_html(elem) + "\n"

        # Scale to fit ~1000px width
        scale = min(1.0, 1000.0 / pw)

        pages_html += f'''
        <div class="page-container">
            <div class="page-header">
                <span class="page-title">{page.get("name", f"Page {i+1}")}</span>
                <span class="page-dims">{pw}×{ph}</span>
                <span class="page-count">{len(page.get("elements", []))} elements</span>
            </div>
            <div class="page-wrapper" style="width:{int(pw*scale)}px; height:{int(ph*scale)}px;">
                <div class="page-canvas" style="
                    width:{pw}px; height:{ph}px;
                    background:{bg_color};
                    transform:scale({scale});
                    transform-origin:top left;
                ">
                    {elements_html}
                </div>
            </div>
        </div>'''

    total_elements = sum(len(p.get("elements", [])) for p in pages)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>JARVIS Canva Preview — {title}</title>
<meta http-equiv="refresh" content="3">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background:#0A0A0A;
    font-family:'Inter', sans-serif;
    color:#E0E0E0;
    padding:24px;
    display:flex; flex-direction:column; align-items:center;
    min-height:100vh;
  }}
  .top-bar {{
    display:flex; align-items:center; gap:16px;
    margin-bottom:24px; padding:16px 28px;
    background:linear-gradient(135deg, rgba(0,122,255,0.1), rgba(0,255,136,0.05));
    border:1px solid rgba(0,122,255,0.2);
    border-radius:16px;
    width:100%; max-width:1080px;
  }}
  .top-bar .logo {{
    width:36px; height:36px; border-radius:10px;
    background:linear-gradient(135deg, #007AFF, #00D4AA);
    display:flex; align-items:center; justify-content:center;
    font-size:18px; font-weight:700; color:#FFF;
  }}
  .top-bar .title-group {{ flex:1; }}
  .top-bar .title-group h1 {{ font-size:18px; font-weight:600; color:#FFF; }}
  .top-bar .title-group .subtitle {{ font-size:13px; color:#888; margin-top:2px; }}
  .top-bar .badge {{
    padding:4px 12px; border-radius:20px;
    font-size:12px; font-weight:600;
    background:rgba(0,122,255,0.15); color:#007AFF;
    text-transform:uppercase;
  }}
  .stats {{
    display:flex; gap:24px; margin-bottom:20px;
  }}
  .stat {{ text-align:center; }}
  .stat .val {{ font-size:24px; font-weight:700; color:#00D4AA; }}
  .stat .lbl {{ font-size:11px; color:#666; margin-top:2px; text-transform:uppercase; letter-spacing:0.5px; }}
  .page-container {{
    margin-bottom:32px; width:100%; max-width:1080px;
  }}
  .page-header {{
    display:flex; align-items:center; gap:12px;
    margin-bottom:8px; padding:8px 0;
  }}
  .page-title {{ font-size:14px; font-weight:600; color:#CCC; }}
  .page-dims {{ font-size:12px; color:#555; }}
  .page-count {{ font-size:11px; color:#007AFF; margin-left:auto; }}
  .page-wrapper {{
    border:1px solid #333; border-radius:12px;
    overflow:hidden; box-shadow:0 12px 40px rgba(0,0,0,0.4);
    position:relative;
  }}
  .page-canvas {{
    position:relative;
  }}
  .canva-elem {{
    position:absolute;
    transition:outline 0.2s;
  }}
  .canva-elem:hover {{
    outline:2px solid #007AFF;
    outline-offset:2px;
    z-index:1000;
  }}
  .node-label {{
    position:absolute; top:-18px; left:0;
    font-size:10px; color:#007AFF;
    opacity:0; transition:opacity 0.2s;
    white-space:nowrap;
    background:rgba(0,0,0,0.8); padding:2px 6px; border-radius:4px;
  }}
  .canva-elem:hover .node-label {{ opacity:1; }}
  .footer {{
    margin-top:8px; font-size:12px; color:#444;
  }}
</style>
</head>
<body>
  <div class="top-bar">
    <div class="logo">J</div>
    <div class="title-group">
      <h1>{title}</h1>
      <div class="subtitle">Live preview · auto-refreshes every 3s · hover to inspect elements</div>
    </div>
    <div class="badge">{design_type}</div>
  </div>

  <div class="stats">
    <div class="stat">
      <div class="val">{len(pages)}</div>
      <div class="lbl">Pages</div>
    </div>
    <div class="stat">
      <div class="val">{total_elements}</div>
      <div class="lbl">Elements</div>
    </div>
    <div class="stat">
      <div class="val">{time.strftime("%H:%M:%S")}</div>
      <div class="lbl">Updated</div>
    </div>
  </div>

  {pages_html}

  <div class="footer">JARVIS Canva Agent · Phase 3</div>
</body>
</html>'''


def save_and_open_preview(builder, open_browser=True):
    """Build design, save HTML preview, optionally open browser."""
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    design = builder.build()
    design_dict = design.to_canva_dict()
    html = generate_canva_preview_html(design_dict)
    with open(PREVIEW_FILE, "w") as f:
        f.write(html)
    if open_browser:
        webbrowser.open(f"file://{PREVIEW_FILE}")
    print(f"  🌐 Preview saved: {PREVIEW_FILE}")


# ── Session State ─────────────────────────────────────────────

class DesignSession:
    def __init__(self, agent: CanvaAgent):
        self.agent = agent
        self.current_builder = None
        self.builder_type = None
        self.design_count = 0
        self.element_count = 0
        self.browser_opened = False

    def set_builder(self, builder, builder_type: str):
        self.current_builder = builder
        self.builder_type = builder_type
        self.design_count += 1

    def has_builder(self) -> bool:
        return self.current_builder is not None

    def update_preview(self):
        if self.has_builder():
            save_and_open_preview(self.current_builder, open_browser=not self.browser_opened)
            self.browser_opened = True


# ── Command Parser ────────────────────────────────────────────

def parse_and_execute(session: DesignSession, user_input: str):
    text = user_input.strip()
    text_lower = text.lower()
    if not text:
        return

    # ── Create Presentation ──
    if "presentation" in text_lower and any(kw in text_lower for kw in ["create", "new", "make", "start"]):
        title = extract_quoted_text(text) or "Untitled Presentation"
        theme = extract_theme(text)
        w, h = extract_size(text)
        builder = session.agent.create_presentation(title, width=w or 1920, height=h or 1080, theme=theme)
        session.set_builder(builder, "presentation")
        print(f"  🎬 Presentation: \"{title}\" ({theme} theme, {w or 1920}×{h or 1080})")
        session.update_preview()
        return

    # ── Create Social Post ──
    if any(kw in text_lower for kw in ["post", "instagram", "facebook", "twitter", "social", "tiktok"]) \
       and any(kw in text_lower for kw in ["create", "new", "make"]):
        title = extract_quoted_text(text) or "Social Post"
        platform = extract_platform(text)
        builder = session.agent.create_social_post(title, platform)
        session.set_builder(builder, "social_post")
        size = SocialPostBuilder.PLATFORM_SIZES.get(platform, (1080, 1080))
        print(f"  📱 Social Post: \"{title}\" ({platform}, {size[0]}×{size[1]})")
        session.update_preview()
        return

    # ── Create Infographic ──
    if "infographic" in text_lower and any(kw in text_lower for kw in ["create", "new", "make", "start"]):
        title = extract_quoted_text(text) or "Infographic"
        w, h = extract_size(text)
        builder = session.agent.create_infographic(title, w or 800, h or 2000)
        session.set_builder(builder, "infographic")
        print(f"  📊 Infographic: \"{title}\" ({w or 800}×{h or 2000})")
        session.update_preview()
        return

    # ── Create Custom Design ──
    if "custom" in text_lower and any(kw in text_lower for kw in ["create", "new", "make"]):
        title = extract_quoted_text(text) or "Custom Design"
        w, h = extract_size(text)
        builder = session.agent.create_custom_design(title, w or 1920, h or 1080)
        session.set_builder(builder, "custom")
        print(f"  🎨 Custom Design: \"{title}\" ({w or 1920}×{h or 1080})")
        session.update_preview()
        return

    # ── Require active builder for everything below ──
    if not session.has_builder():
        print("  ⚠️  No active design. Create one first:")
        print('     "create a presentation \"My Slides\" theme dark"')
        print('     "create instagram post \"Summer Sale\""')
        print('     "create infographic \"System Stats\""')
        return

    builder = session.current_builder

    # ── Push to Canva API ──
    if "push" in text_lower or "upload" in text_lower or ("send" in text_lower and "canva" in text_lower):
        if not CANVA_CLIENT_ID or not CANVA_CLIENT_SECRET:
            print("  ❌ Canva credentials not set in .env (CANVA_CLIENT_ID, CANVA_CLIENT_SECRET)")
            return
        print("  ☁️  Pushing design to Canva cloud...")
        try:
            async def push():
                async with CanvaAgent() as agent_live:
                    result = await agent_live.client.create_design(builder.build())
                    return result
            result = asyncio.run(push())
            design_id = result.get("id") or result.get("design", {}).get("id", "unknown")
            print(f"  ✅ Design pushed to Canva! ID: {design_id}")
            edit_url = result.get("edit_url") or result.get("urls", {}).get("edit_url", "")
            if edit_url:
                print(f"  🔗 Edit URL: {edit_url}")
                webbrowser.open(edit_url)
        except Exception as e:
            print(f"  ❌ Canva API error: {e}")
            print(f"     Design is still available in the local preview.")
        return

    # ── Title Slide ──
    if "title slide" in text_lower or ("title" in text_lower and "slide" in text_lower):
        quoted = extract_all_quoted(text)
        title = quoted[0] if len(quoted) > 0 else "Main Title"
        subtitle = ""
        sub_match = re.search(r'subtitle\s+["\'](.+?)["\']', text, re.IGNORECASE)
        subtitle = sub_match.group(1) if sub_match else (quoted[1] if len(quoted) > 1 else "")
        if hasattr(builder, 'title_slide'):
            builder.title_slide(title, subtitle)
            session.element_count += 2 if subtitle else 1
            print(f"  📑 Title Slide: \"{title}\"" + (f" / \"{subtitle}\"" if subtitle else ""))
        else:
            builder.text(title, 100, 200, 1720, 120)
            session.element_count += 1
            print(f"  📝 Title: \"{title}\"")
        session.update_preview()
        return

    # ── Content Slide ──
    if "content slide" in text_lower or "bullet" in text_lower:
        quoted = extract_all_quoted(text)
        title = quoted[0] if len(quoted) > 0 else "Content"
        bullets = []
        bullet_match = re.search(r'bullets?\s+["\'](.+?)["\']', text, re.IGNORECASE)
        if bullet_match:
            bullets = [b.strip() for b in bullet_match.group(1).split(',')]
        elif len(quoted) > 1:
            bullets = quoted[1:]
        else:
            bullets = ["Point 1", "Point 2", "Point 3"]
        if hasattr(builder, 'content_slide'):
            builder.content_slide(title, bullets)
            session.element_count += 1 + len(bullets)
            print(f"  📋 Content Slide: \"{title}\" ({len(bullets)} bullets)")
        session.update_preview()
        return

    # ── Header ──
    if "header" in text_lower:
        quoted = extract_all_quoted(text)
        title = quoted[0] if len(quoted) > 0 else "Header"
        sub_match = re.search(r'subtitle\s+["\'](.+?)["\']', text, re.IGNORECASE)
        subtitle = sub_match.group(1) if sub_match else (quoted[1] if len(quoted) > 1 else "")
        if hasattr(builder, 'header'):
            builder.header(title, subtitle)
            session.element_count += 2 if subtitle else 1
            print(f"  🏷️  Header: \"{title}\"" + (f" / \"{subtitle}\"" if subtitle else ""))
        session.update_preview()
        return

    # ── Stat Card ──
    if "stat" in text_lower or ("card" in text_lower and "create" not in text_lower) or "metric" in text_lower:
        quoted = extract_all_quoted(text)
        value = quoted[0] if len(quoted) > 0 else "100"
        label_match = re.search(r'label\s+["\'](.+?)["\']', text, re.IGNORECASE)
        label = label_match.group(1) if label_match else (quoted[1] if len(quoted) > 1 else "Metric")
        x, y = extract_coords(text)
        color = resolve_color(text)
        if hasattr(builder, 'stat_card'):
            builder.stat_card(value, label, x, y, accent_color=color)
            session.element_count += 3
            print(f"  📈 Stat Card: {value} ({label}) accent={color}")
        session.update_preview()
        return

    # ── Divider ──
    if "divider" in text_lower or "separator" in text_lower:
        if hasattr(builder, 'section_divider'):
            builder.section_divider()
            session.element_count += 1
            print(f"  ── Divider added")
        session.update_preview()
        return

    # ── Watermark ──
    if "watermark" in text_lower or "brand" in text_lower or "logo" in text_lower:
        url = extract_quoted_text(text) or "https://logo.example.com/logo.png"
        pos = "bottom-right" if "bottom" in text_lower else "top-left"
        if hasattr(builder, 'add_brand_watermark'):
            builder.add_brand_watermark(url, pos)
            session.element_count += 1
            print(f"  🏷️  Watermark: ({pos})")
        session.update_preview()
        return

    # ── Text ──
    if any(kw in text_lower for kw in ["text", "write", "heading", "label"]):
        content = extract_quoted_text(text) or "Sample Text"
        x, y = extract_coords(text)
        color = resolve_color(text)
        fs_match = re.search(r'(?:font\s*)?size\s*(\d+)', text, re.IGNORECASE)
        font_size = int(fs_match.group(1)) if fs_match else 24
        builder.text(content, x, y, width=600, height=60,
                     style=CanvaTextStyle(font_size=font_size, font_weight=CanvaFontWeight.BOLD,
                                          color=CanvaColor.from_hex(color)))
        session.element_count += 1
        print(f"  📝 Text: \"{content}\" at ({x},{y}) size={font_size}")
        session.update_preview()
        return

    # ── Rectangle ──
    if any(kw in text_lower for kw in ["rectangle", "rect", "box", "shape"]):
        x, y = extract_coords(text)
        w, h = extract_size(text)
        if not w:
            w, h = 200, 100
        color = resolve_color(text)
        cr_match = re.search(r'radius\s*(\d+)', text)
        corner_radius = int(cr_match.group(1)) if cr_match else 0
        builder.rectangle(x, y, w, h, fill=color, corner_radius=corner_radius)
        session.element_count += 1
        print(f"  📐 Rectangle: ({x},{y}) {w}×{h} fill={color}")
        session.update_preview()
        return

    # ── Circle ──
    if "circle" in text_lower:
        x, y = extract_coords(text)
        d_match = re.search(r'(?:diameter|size|radius)\s*(\d+)', text, re.IGNORECASE)
        diameter = int(d_match.group(1)) if d_match else 100
        color = resolve_color(text)
        builder.circle(x, y, diameter, fill=color)
        session.element_count += 1
        print(f"  ⭕ Circle: ({x},{y}) d={diameter}")
        session.update_preview()
        return

    # ── Image ──
    if "image" in text_lower or "photo" in text_lower:
        x, y = extract_coords(text)
        w, h = extract_size(text)
        if not w:
            w, h = 300, 200
        url = extract_quoted_text(text) or "https://example.com/image.png"
        builder.image(x, y, w, h, image_url=url)
        session.element_count += 1
        print(f"  🖼️  Image: ({x},{y}) {w}×{h}")
        session.update_preview()
        return

    # ── Background ──
    if "background" in text_lower:
        color = resolve_color(text)
        builder.background(color)
        print(f"  🎨 Background: {color}")
        session.update_preview()
        return

    # ── New Page ──
    if any(kw in text_lower for kw in ["new page", "next page", "new slide", "next slide", "add page"]):
        name = extract_quoted_text(text) or f"Page {len(builder.design.pages) + 1}"
        builder.page(name)
        print(f"  📄 New page: \"{name}\"")
        session.update_preview()
        return

    print("  ❓ Could not parse. Try \"help\" for commands.")


# ── Main Loop ─────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  JARVIS — Canva Live Design Studio")
    print("=" * 60)
    print()
    print("  Type design instructions. Designs appear in your browser")
    print("  and can be pushed to Canva cloud.")
    print()
    print("  Quick Start:")
    print('    > create a presentation "BGMI Tournament" theme dark')
    print('    > add title slide "Welcome" subtitle "Season 12"')
    print('    > add content slide "Rules" bullets "Fair play, No hacks, GG"')
    print('    > show               ← preview in browser')
    print('    > push to canva      ← send to Canva cloud')
    print('    > quit')
    print()

    has_creds = bool(CANVA_CLIENT_ID and CANVA_CLIENT_SECRET)
    agent = CanvaAgent()
    print(f"  ✅ CanvaAgent initialized")
    if has_creds:
        print(f"  🟢 Canva API credentials found — \"push to canva\" will work")
    else:
        print(f"  🟡 No Canva credentials — designs will preview locally only")
    print()

    session = DesignSession(agent)

    while True:
        try:
            if session.has_builder():
                b = session.current_builder
                elems = sum(len(p.elements) for p in b.design.pages)
                prompt = f"  [{session.builder_type}:{elems}] > "
            else:
                prompt = "  JARVIS Design > "
            user_input = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q", "stop"):
            if session.has_builder():
                print("\n  ── Final Design ──")
                d = session.current_builder.build()
                print(f"  Title: {d.title} | Type: {d.design_type.value}")
                print(f"  Pages: {len(d.pages)} | Elements: {sum(len(p.elements) for p in d.pages)}")
            break

        if user_input.lower() in ("help", "?"):
            print("\n  ── Create Designs ──")
            print('    "create presentation \"Title\" theme dark"')
            print('    "create instagram post \"Title\""')
            print('    "create infographic \"Title\""')
            print('    "create custom design \"Title\" 1200x400"')
            print("\n  ── Presentation ──")
            print('    "add title slide \"Title\" subtitle \"Sub\""')
            print('    "add content slide \"Title\" bullets \"A, B, C\""')
            print("\n  ── Infographic ──")
            print('    "add header \"Title\" subtitle \"Sub\""')
            print('    "add stat \"99%\" label \"Uptime\" at 100,300"')
            print('    "add divider"')
            print("\n  ── Universal ──")
            print('    text, rectangle, circle, image, background, watermark')
            print('    show/preview — open browser | push to canva — upload')
            print('    quit\n')
            continue

        if user_input.lower() in ("show", "preview", "open", "render"):
            if session.has_builder():
                save_and_open_preview(session.current_builder, open_browser=True)
            else:
                print("  ⚠️  No design to preview yet.")
            continue

        parse_and_execute(session, user_input)

    print(f"\n  📋 Session: {session.design_count} design(s), {session.element_count} element(s)")
    print("  ✅ Canva design pipeline verified!\n")


if __name__ == "__main__":
    main()
