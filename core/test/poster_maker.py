"""
==========================================================
JARVIS — Poster Maker (PNG Output)
==========================================================

Type natural language instructions to build a poster.
Output is a real PNG image file — no HTML, no browser.

Usage:
  venv/bin/python core/test/poster_maker.py

Examples:
  > size 1080x1920
  > background navy
  > text "BGMI TOURNAMENT" at 540,200 size 60 white bold center
  > text "Season 12" at 540,300 size 30 gold center
  > line at 100,400 to 980,400 gold width 3
  > box at 200,800 size 680x100 blue radius 20
  > text "REGISTER NOW" at 540,835 size 28 white bold center
  > circle at 540,600 size 150 orange
  > save                ← saves poster.png
  > save "tournament"   ← saves tournament.png
  > quit

Author: JARVIS-MacOS
"""

import sys
import os
import re
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from PIL import Image, ImageDraw, ImageFont

# ── Output directory ──────────────────────────────────────────
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "posters")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── Color Resolver ────────────────────────────────────────────
COLOR_MAP = {
    "red": "#FF3B30", "green": "#34C759", "blue": "#007AFF",
    "white": "#FFFFFF", "black": "#000000", "yellow": "#FFD700",
    "purple": "#AF52DE", "orange": "#FF9500", "pink": "#FF2D55",
    "gray": "#8E8E93", "grey": "#8E8E93", "cyan": "#00BCD4",
    "neon green": "#00FF88", "neon": "#00FF88",
    "navy": "#1A1A2E", "sky blue": "#87CEEB",
    "dark": "#1A1A2E", "light": "#F5F5F5", "gold": "#FFD700",
    "teal": "#00897B", "coral": "#FF6B6B", "indigo": "#3F51B5",
    "maroon": "#800000", "lime": "#32CD32", "magenta": "#FF00FF",
    "brown": "#8B4513", "beige": "#F5F5DC", "crimson": "#DC143C",
    "turquoise": "#40E0D0", "salmon": "#FA8072", "olive": "#808000",
    "violet": "#8A2BE2", "mint": "#98FF98", "lavender": "#E6E6FA",
    "charcoal": "#36454F", "slate": "#708090",
}


def resolve_color(text: str) -> str:
    """Resolve a color name or hex code from text."""
    hex_match = re.search(r'#[0-9A-Fa-f]{6}', text)
    if hex_match:
        return hex_match.group()
    hex_match = re.search(r'#[0-9A-Fa-f]{3}\b', text)
    if hex_match:
        h = hex_match.group()
        return f"#{h[1]*2}{h[2]*2}{h[3]*2}"
    text_lower = text.lower()
    # Check multi-word names first
    for name in sorted(COLOR_MAP.keys(), key=len, reverse=True):
        if name in text_lower:
            return COLOR_MAP[name]
    return None


def hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color to RGB tuple."""
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple:
    """Convert hex color to RGBA tuple."""
    r, g, b = hex_to_rgb(hex_color)
    return (r, g, b, alpha)


# ── Font Loader ───────────────────────────────────────────────
FONT_PATHS = {
    "bold": "/System/Library/Fonts/HelveticaNeue.ttc",
    "regular": "/System/Library/Fonts/Helvetica.ttc",
    "light": "/System/Library/Fonts/HelveticaNeue.ttc",
    "avenir": "/System/Library/Fonts/Avenir Next.ttc",
}

_font_cache = {}


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Get a font at the given size."""
    key = (size, bold)
    if key not in _font_cache:
        path = FONT_PATHS["bold"] if bold else FONT_PATHS["regular"]
        try:
            # For .ttc files, index 0 is usually regular, higher indices are bold variants
            font_index = 1 if bold else 0
            _font_cache[key] = ImageFont.truetype(path, size, index=font_index)
        except Exception:
            try:
                _font_cache[key] = ImageFont.truetype(path, size)
            except Exception:
                _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


# ── Poster Canvas ─────────────────────────────────────────────

class Poster:
    """A poster canvas that renders to PNG."""

    def __init__(self, width: int = 1080, height: int = 1920):
        self.width = width
        self.height = height
        self.bg_color = "#1A1A2E"
        self.elements = []  # list of (type, kwargs) tuples
        self._rebuild()

    def _rebuild(self):
        """Rebuild the image from all elements."""
        self.img = Image.new("RGBA", (self.width, self.height), hex_to_rgba(self.bg_color))
        self.draw = ImageDraw.Draw(self.img)
        for elem_type, kwargs in self.elements:
            if elem_type == "text":
                self._draw_text(**kwargs)
            elif elem_type == "box":
                self._draw_box(**kwargs)
            elif elem_type == "circle":
                self._draw_circle(**kwargs)
            elif elem_type == "line":
                self._draw_line(**kwargs)
            elif elem_type == "gradient_box":
                self._draw_gradient_box(**kwargs)

    def set_size(self, width: int, height: int):
        self.width = width
        self.height = height
        self._rebuild()

    def set_background(self, color: str):
        self.bg_color = color
        self._rebuild()

    def add_text(self, text: str, x: int, y: int, size: int = 24,
                 color: str = "#FFFFFF", bold: bool = False, center: bool = False):
        self.elements.append(("text", {
            "text": text, "x": x, "y": y, "size": size,
            "color": color, "bold": bold, "center": center
        }))
        self._draw_text(text, x, y, size, color, bold, center)

    def _draw_text(self, text: str, x: int, y: int, size: int,
                   color: str, bold: bool, center: bool):
        font = get_font(size, bold)
        fill = hex_to_rgb(color)
        if center:
            bbox = font.getbbox(text)
            text_w = bbox[2] - bbox[0]
            x = x - text_w // 2
        self.draw.text((x, y), text, font=font, fill=fill)

    def add_box(self, x: int, y: int, w: int, h: int,
                color: str = "#007AFF", radius: int = 0,
                outline: str = None, outline_width: int = 2,
                opacity: int = 255):
        self.elements.append(("box", {
            "x": x, "y": y, "w": w, "h": h, "color": color,
            "radius": radius, "outline": outline,
            "outline_width": outline_width, "opacity": opacity
        }))
        self._draw_box(x, y, w, h, color, radius, outline, outline_width, opacity)

    def _draw_box(self, x: int, y: int, w: int, h: int,
                  color: str, radius: int, outline: str,
                  outline_width: int, opacity: int):
        fill = hex_to_rgba(color, opacity)
        # Draw on a temp layer for opacity support
        if opacity < 255:
            layer = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
            layer_draw = ImageDraw.Draw(layer)
            layer_draw.rounded_rectangle(
                [x, y, x + w, y + h], radius=radius, fill=fill,
                outline=hex_to_rgb(outline) if outline else None,
                width=outline_width if outline else 0
            )
            self.img = Image.alpha_composite(self.img, layer)
            self.draw = ImageDraw.Draw(self.img)
        else:
            self.draw.rounded_rectangle(
                [x, y, x + w, y + h], radius=radius, fill=fill,
                outline=hex_to_rgb(outline) if outline else None,
                width=outline_width if outline else 0
            )

    def add_circle(self, cx: int, cy: int, diameter: int,
                   color: str = "#FF9500", outline: str = None,
                   outline_width: int = 2):
        self.elements.append(("circle", {
            "cx": cx, "cy": cy, "diameter": diameter, "color": color,
            "outline": outline, "outline_width": outline_width
        }))
        self._draw_circle(cx, cy, diameter, color, outline, outline_width)

    def _draw_circle(self, cx: int, cy: int, diameter: int,
                     color: str, outline: str, outline_width: int):
        r = diameter // 2
        self.draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=hex_to_rgb(color),
            outline=hex_to_rgb(outline) if outline else None,
            width=outline_width if outline else 0
        )

    def add_line(self, x1: int, y1: int, x2: int, y2: int,
                 color: str = "#FFFFFF", width: int = 2):
        self.elements.append(("line", {
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "color": color, "width": width
        }))
        self._draw_line(x1, y1, x2, y2, color, width)

    def _draw_line(self, x1: int, y1: int, x2: int, y2: int,
                   color: str, width: int):
        self.draw.line([x1, y1, x2, y2], fill=hex_to_rgb(color), width=width)

    def add_gradient_box(self, x: int, y: int, w: int, h: int,
                         color1: str, color2: str, radius: int = 0,
                         direction: str = "vertical"):
        self.elements.append(("gradient_box", {
            "x": x, "y": y, "w": w, "h": h,
            "color1": color1, "color2": color2,
            "radius": radius, "direction": direction
        }))
        self._draw_gradient_box(x, y, w, h, color1, color2, radius, direction)

    def _draw_gradient_box(self, x: int, y: int, w: int, h: int,
                           color1: str, color2: str, radius: int,
                           direction: str):
        r1, g1, b1 = hex_to_rgb(color1)
        r2, g2, b2 = hex_to_rgb(color2)
        gradient = Image.new("RGBA", (w, h))
        for i in range(h if direction == "vertical" else w):
            steps = h if direction == "vertical" else w
            ratio = i / max(steps - 1, 1)
            r = int(r1 + (r2 - r1) * ratio)
            g = int(g1 + (g2 - g1) * ratio)
            b = int(b1 + (b2 - b1) * ratio)
            if direction == "vertical":
                ImageDraw.Draw(gradient).line([(0, i), (w, i)], fill=(r, g, b, 255))
            else:
                ImageDraw.Draw(gradient).line([(i, 0), (i, h)], fill=(r, g, b, 255))
        # Apply rounded corners via mask
        if radius > 0:
            mask = Image.new("L", (w, h), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, w, h], radius=radius, fill=255)
            gradient.putalpha(mask)
        self.img.paste(gradient, (x, y), gradient)
        self.draw = ImageDraw.Draw(self.img)

    def undo(self):
        """Remove the last element."""
        if self.elements:
            self.elements.pop()
            self._rebuild()
            return True
        return False

    def clear(self):
        """Clear all elements."""
        self.elements.clear()
        self._rebuild()

    def save(self, name: str = "poster") -> str:
        """Save the poster as PNG. Returns the file path."""
        if not name.endswith(".png"):
            name = f"{name}.png"
        path = os.path.join(OUTPUT_DIR, name)
        # Flatten RGBA to RGB for final PNG (smaller file)
        final = Image.new("RGB", self.img.size, (255, 255, 255))
        final.paste(self.img, mask=self.img.split()[3])
        final.save(path, "PNG", quality=95)
        return path


# ── Command Parser ────────────────────────────────────────────

def extract_quoted(text: str) -> str:
    match = re.search(r'["\'](.+?)["\']', text)
    return match.group(1) if match else ""

def extract_at(text: str):
    match = re.search(r'at\s+(\d+)\s*[,\s]+\s*(\d+)', text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None

def extract_to(text: str):
    match = re.search(r'to\s+(\d+)\s*[,\s]+\s*(\d+)', text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None

def extract_size_val(text: str):
    match = re.search(r'size\s+(\d+)\s*[xX×]\s*(\d+)', text)
    if match:
        return int(match.group(1)), int(match.group(2))
    # single number for font size or circle diameter
    match = re.search(r'size\s+(\d+)', text)
    if match:
        return int(match.group(1)), None
    return None, None

def extract_font_size(text: str) -> int:
    match = re.search(r'(?:font\s*)?size\s+(\d+)', text, re.IGNORECASE)
    return int(match.group(1)) if match else 24

def extract_radius(text: str) -> int:
    match = re.search(r'radius\s+(\d+)', text, re.IGNORECASE)
    return int(match.group(1)) if match else 0

def extract_width(text: str) -> int:
    match = re.search(r'width\s+(\d+)', text, re.IGNORECASE)
    return int(match.group(1)) if match else 2

def extract_opacity(text: str) -> int:
    match = re.search(r'opacity\s+(\d+)', text, re.IGNORECASE)
    if match:
        val = int(match.group(1))
        if val <= 100:
            return int(val * 2.55)
        return min(val, 255)
    return 255


def parse_and_execute(poster: Poster, user_input: str) -> str:
    """Parse user input and execute the command. Returns status message."""
    text = user_input.strip()
    text_lower = text.lower()

    if not text:
        return None

    # ── Size ──
    if text_lower.startswith("size"):
        match = re.search(r'(\d+)\s*[xX×]\s*(\d+)', text)
        if match:
            w, h = int(match.group(1)), int(match.group(2))
            poster.set_size(w, h)
            return f"📐 Canvas: {w}×{h}"
        return "❌ Usage: size 1080x1920"

    # ── Background ──
    if text_lower.startswith("background") or text_lower.startswith("bg"):
        color = resolve_color(text)
        if color:
            poster.set_background(color)
            return f"🎨 Background: {color}"
        return "❌ Could not parse color. Use a name (navy, red) or hex (#1A1A2E)"

    # ── Text ──
    if any(text_lower.startswith(kw) for kw in ["text ", "add text", "write "]):
        content = extract_quoted(text) or "Hello"
        x, y = extract_at(text)
        if x is None:
            x, y = poster.width // 2, poster.height // 2
        font_size = extract_font_size(text)
        bold = "bold" in text_lower
        center = "center" in text_lower
        color = resolve_color(text) or "#FFFFFF"
        poster.add_text(content, x, y, font_size, color, bold, center)
        pos = f"centered at ({x},{y})" if center else f"at ({x},{y})"
        return f'📝 Text: "{content}" {pos} size={font_size} {"bold " if bold else ""}color={color}'

    # ── Box / Rectangle ──
    if any(kw in text_lower for kw in ["box", "rect", "rectangle"]):
        x, y = extract_at(text)
        if x is None:
            x, y = 100, 100
        sw, sh = extract_size_val(text)
        if sw and sh:
            w, h = sw, sh
        elif sw:
            w, h = sw, sw
        else:
            w, h = 200, 100
        color = resolve_color(text) or "#007AFF"
        radius = extract_radius(text)
        opacity = extract_opacity(text)
        outline_color = None
        if "outline" in text_lower or "border" in text_lower:
            # Try to find a second color for outline
            outline_color = "#FFFFFF"
        poster.add_box(x, y, w, h, color, radius, outline_color, opacity=opacity)
        return f"📦 Box: ({x},{y}) {w}×{h} fill={color} radius={radius}"

    # ── Circle ──
    if "circle" in text_lower:
        x, y = extract_at(text)
        if x is None:
            x, y = poster.width // 2, poster.height // 2
        sw, _ = extract_size_val(text)
        diameter = sw or 100
        color = resolve_color(text) or "#FF9500"
        poster.add_circle(x, y, diameter, color)
        return f"⭕ Circle: center=({x},{y}) diameter={diameter} fill={color}"

    # ── Line ──
    if text_lower.startswith("line") or "add line" in text_lower:
        x1, y1 = extract_at(text)
        x2, y2 = extract_to(text)
        if x1 is None:
            x1, y1 = 100, poster.height // 2
        if x2 is None:
            x2, y2 = poster.width - 100, y1
        color = resolve_color(text) or "#FFFFFF"
        width = extract_width(text)
        poster.add_line(x1, y1, x2, y2, color, width)
        return f"📏 Line: ({x1},{y1}) → ({x2},{y2}) color={color} width={width}"

    # ── Gradient Box ──
    if "gradient" in text_lower:
        x, y = extract_at(text)
        if x is None:
            x, y = 0, 0
        sw, sh = extract_size_val(text)
        if sw and sh:
            w, h = sw, sh
        else:
            w, h = poster.width, poster.height
        colors = re.findall(r'#[0-9A-Fa-f]{6}', text)
        if len(colors) < 2:
            named = [v for k, v in COLOR_MAP.items() if k in text_lower]
            colors = (colors + named + ["#007AFF", "#00D4AA"])[:2]
        radius = extract_radius(text)
        direction = "horizontal" if "horizontal" in text_lower else "vertical"
        poster.add_gradient_box(x, y, w, h, colors[0], colors[1], radius, direction)
        return f"🌈 Gradient: ({x},{y}) {w}×{h} {colors[0]}→{colors[1]} {direction}"

    # ── Undo ──
    if text_lower in ("undo", "remove", "delete last"):
        if poster.undo():
            return "↩️  Undid last element"
        return "❌ Nothing to undo"

    # ── Clear ──
    if text_lower in ("clear", "reset"):
        poster.clear()
        return "🗑️  Cleared all elements"

    # ── Save ──
    if text_lower.startswith("save"):
        name = extract_quoted(text) or "poster"
        path = poster.save(name)
        return f"SAVE:{path}"

    # ── Info ──
    if text_lower in ("info", "status"):
        return f"ℹ️  Canvas: {poster.width}×{poster.height} | Background: {poster.bg_color} | Elements: {len(poster.elements)}"

    return None


# ── Main Loop ─────────────────────────────────────────────────

def main():
    print("=" * 56)
    print("  JARVIS — Poster Maker")
    print("  Output: Real PNG images")
    print("=" * 56)
    print()
    print("  Commands:")
    print("    size 1080x1920          ← set canvas size")
    print("    background navy         ← set background color")
    print('    text "HELLO" at 540,200 size 60 white bold center')
    print("    box at 100,800 size 880x120 blue radius 16")
    print("    circle at 540,600 size 200 orange")
    print("    line at 100,500 to 980,500 gold width 3")
    print("    gradient at 0,0 size 1080x400 #007AFF #00D4AA")
    print("    undo / clear            ← undo last or clear all")
    print('    save "my_poster"        ← saves to data/posters/')
    print("    quit")
    print()
    print(f"  📁 Output: {OUTPUT_DIR}/")
    print()

    poster = Poster(1080, 1920)
    save_count = 0

    while True:
        try:
            elems = len(poster.elements)
            prompt = f"  [{poster.width}×{poster.height} · {elems} items] > "
            user_input = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            if poster.elements:
                path = poster.save("poster_final")
                print(f"\n  💾 Auto-saved: {path}")
            break

        if user_input.lower() in ("help", "?"):
            print()
            print("  ── Canvas ──")
            print("    size 1080x1920")
            print("    background navy / background #1A1A2E")
            print()
            print("  ── Elements ──")
            print('    text "YOUR TEXT" at X,Y size 36 white bold center')
            print("    box at X,Y size WxH blue radius 12")
            print("    circle at X,Y size 150 orange")
            print("    line at X1,Y1 to X2,Y2 gold width 3")
            print("    gradient at X,Y size WxH #color1 #color2 radius 8")
            print()
            print("  ── Actions ──")
            print("    undo          ← remove last element")
            print("    clear         ← remove everything")
            print('    save "name"   ← save as data/posters/name.png')
            print("    info          ← show canvas info")
            print("    quit          ← exit (auto-saves)")
            print()
            print("  ── Colors ──")
            print("    red, blue, green, white, black, yellow, gold,")
            print("    purple, orange, pink, cyan, navy, teal, coral,")
            print("    neon green, crimson, violet, salmon, mint,")
            print("    lavender, charcoal, slate, or any #HEX code")
            print()
            continue

        result = parse_and_execute(poster, user_input)

        if result is None:
            print("  ❓ Could not parse. Type 'help' for commands.")
        elif result.startswith("SAVE:"):
            path = result[5:]
            save_count += 1
            print(f"  ✅ Saved: {path}")
            # Open in Preview app on macOS
            try:
                subprocess.Popen(["open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"  👁️  Opened in Preview")
            except Exception:
                pass
        else:
            print(f"  {result}")

    print(f"\n  📋 Session: {len(poster.elements)} elements, {save_count} save(s)")
    print("  ✅ Done!\n")


if __name__ == "__main__":
    main()
