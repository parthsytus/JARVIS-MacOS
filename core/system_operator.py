"""
==========================================================
JARVIS — Universal System Operator (Computer-Using Agent)
==========================================================

This module provides universal fallback navigation for ANY application
using Computer Vision (Groq Llama-4-Scout) + PyAutoGUI.

Architecture:
  1. Eyes: analyze_screen() — captures screen, compresses to max 1024x576,
     sends to Groq vision model to extract UI element coordinates
  2. Hands: execute_ui_action() — wraps pyautogui for zero-latency execution

Permission Protocol:
  - JARVIS MUST verbally ask user for permission before calling
    analyze_screen or execute_ui_action
  - This is enforced at the tool-calling layer in groq_brain.py

Dependencies:
  pip install pillow pyautogui groq python-dotenv

Author: JARVIS-MacOS Phase 3
"""

import os
import base64
import io
import time
import logging
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
import json
from PIL import Image, ImageGrab
import pyautogui
from groq import Groq
from config.config import GROQ_API_KEY, GROQ_TIMEOUT_S

# ── Configuration ──────────────────────────────────────────────
# Zero-latency PyAutoGUI
pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = True  # Keep failsafe for safety (corner to abort)

# Screen capture settings
MAX_SCREEN_WIDTH = 1024
MAX_SCREEN_HEIGHT = 576
JPEG_QUALITY = 75  # Balance between size and clarity for vision model

# Groq Vision Model
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Logging
logger = logging.getLogger("JARVIS.SystemOperator")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[SYSTEM_OPERATOR] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ── Data Classes ───────────────────────────────────────────────
@dataclass
class UIElement:
    """Represents a detected UI element on screen."""
    element_type: str      # button, input, link, menu, icon, text, unknown
    description: str       # Human-readable description (e.g., "Submit button", "Search field")
    x: int                 # Center X coordinate (screen space)
    y: int                 # Center Y coordinate (screen space)
    width: int             # Element width
    height: int            # Element height
    confidence: float      # Model confidence 0.0-1.0
    action_hint: str       # Suggested action: click, type, hover, scroll


@dataclass
class ScreenAnalysis:
    """Result of screen analysis."""
    elements: List[UIElement]
    screen_width: int
    screen_height: int
    timestamp: float
    raw_response: str      # Raw model response for debugging


# ── Groq Client ────────────────────────────────────────────────
_groq_client = None

def _get_groq_client() -> Groq:
    """Lazy-initialize Groq client."""
    global _groq_client
    if _groq_client is None:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY not set in config")
        _groq_client = Groq(
            api_key=GROQ_API_KEY,
            timeout=GROQ_TIMEOUT_S,
            max_retries=1
        )
    return _groq_client


# ── Screen Capture ─────────────────────────────────────────────
def capture_screen() -> Image.Image:
    """
    Capture the full screen using PIL.ImageGrab.
    Returns PIL Image in RGB mode.
    """
    try:
        screenshot = ImageGrab.grab(all_screens=True)
        if screenshot.mode != "RGB":
            screenshot = screenshot.convert("RGB")
        return screenshot
    except Exception as e:
        logger.error(f"Screen capture failed: {e}")
        raise


def compress_image(image: Image.Image, max_width: int = MAX_SCREEN_WIDTH, 
                   max_height: int = MAX_SCREEN_HEIGHT, quality: int = JPEG_QUALITY) -> bytes:
    """
    Compress image to fit within max dimensions while maintaining aspect ratio.
    Returns JPEG bytes.
    """
    # Calculate scaling factor
    scale_w = max_width / image.width
    scale_h = max_height / image.height
    scale = min(scale_w, scale_h, 1.0)  # Never upscale
    
    if scale < 1.0:
        new_width = int(image.width * scale)
        new_height = int(image.height * scale)
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # Save to bytes
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def image_to_base64(image_bytes: bytes) -> str:
    """Convert image bytes to base64 string."""
    return base64.b64encode(image_bytes).decode("utf-8")


# ── Vision Analysis ────────────────────────────────────────────
VISION_SYSTEM_PROMPT = """You are JARVIS's vision system. Analyze the provided screenshot and identify ALL interactive UI elements.

Return a JSON array of objects, each with:
- "element_type": "button" | "input" | "link" | "menu" | "icon" | "text" | "checkbox" | "dropdown" | "slider" | "tab" | "unknown"
- "description": Brief human-readable label (e.g., "Submit button", "Search field", "Close icon")
- "x": Center X coordinate in pixels (0 = left edge)
- "y": Center Y coordinate in pixels (0 = top edge)
- "width": Element width in pixels
- "height": Element height in pixels
- "confidence": 0.0 to 1.0
- "action_hint": "click" | "type" | "hover" | "scroll" | "drag" | "right_click"

Rules:
1. Only return elements a user would actually interact with
2. Ignore decorative elements, background images, static text blocks
3. Coordinates are in the ORIGINAL screenshot coordinate space
4. Be precise — center point must land on the clickable area
5. If unsure, set confidence lower and note in description
6. Return empty array [] if no interactive elements found

Example output:
[
  {"element_type": "button", "description": "Blue Submit button at bottom right", "x": 950, "y": 520, "width": 120, "height": 40, "confidence": 0.95, "action_hint": "click"},
  {"element_type": "input", "description": "Search field top center", "x": 480, "y": 80, "width": 400, "height": 36, "confidence": 0.9, "action_hint": "type"}
]"""


def analyze_screen(user_query: str = "", context: str = "") -> ScreenAnalysis:
    """
    Capture screen, send to Groq vision model, parse UI elements.
    
    Args:
        user_query: What the user is trying to do (helps model focus)
        context: Additional context from conversation history
    
    Returns:
        ScreenAnalysis with list of UIElement objects
    
    Permission: MUST be called only after user grants explicit permission.
    """
    logger.info("Capturing screen for analysis...")
    
    # 1. Capture & compress
    screenshot = capture_screen()
    original_width, original_height = screenshot.size
    logger.info(f"Screen captured: {original_width}x{original_height}")
    
    compressed_bytes = compress_image(screenshot)
    logger.info(f"Compressed to {len(compressed_bytes)/1024:.1f} KB")
    
    # 2. Encode to base64
    b64_image = image_to_base64(compressed_bytes)
    
    # 3. Build prompt with user context
    user_prompt = f"""Analyze this screenshot for interactive UI elements.

User's intent: {user_query or "General navigation"}
Context: {context or "None"}

Return JSON array of interactive elements only."""
    
    # 4. Call Groq Vision API
    client = _get_groq_client()
    
    try:
        response = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}
                        }
                    ]
                }
            ],
            temperature=0.1,  # Low temp for consistent coordinate extraction
            max_tokens=2048,
            response_format={"type": "json_object"}  # Force JSON output
        )
        
        raw_content = response.choices[0].message.content
        logger.debug(f"Raw vision response: {raw_content[:500]}...")
        
    except Exception as e:
        logger.error(f"Groq vision API error: {e}")
        raise RuntimeError(f"Vision analysis failed: {e}")
    
    # 5. Parse JSON response
    try:
        # Groq may return object with "elements" key or direct array
        parsed = json.loads(raw_content)
        if isinstance(parsed, dict) and "elements" in parsed:
            elements_data = parsed["elements"]
        elif isinstance(parsed, list):
            elements_data = parsed
        else:
            elements_data = []
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse vision response as JSON: {e}")
        logger.error(f"Raw response: {raw_content}")
        elements_data = []
    
    # 6. Convert to UIElement objects
    elements = []
    for item in elements_data:
        try:
            elem = UIElement(
                element_type=item.get("element_type", "unknown"),
                description=item.get("description", ""),
                x=int(item.get("x", 0)),
                y=int(item.get("y", 0)),
                width=int(item.get("width", 0)),
                height=int(item.get("height", 0)),
                confidence=float(item.get("confidence", 0.0)),
                action_hint=item.get("action_hint", "click")
            )
            # Validate coordinates are within screen bounds
            if 0 <= elem.x <= original_width and 0 <= elem.y <= original_height:
                elements.append(elem)
            else:
                logger.warning(f"Element {elem.description} has out-of-bounds coordinates ({elem.x}, {elem.y})")
        except (ValueError, TypeError) as e:
            logger.warning(f"Skipping malformed element: {item} — {e}")
    
    logger.info(f"Detected {len(elements)} interactive elements")
    
    return ScreenAnalysis(
        elements=elements,
        screen_width=original_width,
        screen_height=original_height,
        timestamp=time.time(),
        raw_response=raw_content
    )


# ── Action Execution ───────────────────────────────────────────
def execute_ui_action(
    action: str,
    x: int,
    y: int,
    text: str = "",
    hotkey: Optional[Union[str, List[str]]] = None,
    duration: float = 0.15
) -> Dict[str, Any]:
    """
    Execute a UI action at the given coordinates.
    
    Args:
        action: "click" | "double_click" | "right_click" | "type" | "hover" | "scroll" | "drag" | "hotkey"
        x: Target X coordinate (screen space)
        y: Target Y coordinate (screen space)
        text: Text to type (for action="type")
        hotkey: Key or list of keys for hotkey combos (e.g., ["cmd", "c"] or "enter")
        duration: Mouse movement duration in seconds
    
    Returns:
        Dict with success status and message
    
    Permission: MUST be called only after user grants explicit permission.
    """
    logger.info(f"Executing UI action: {action} at ({x}, {y})")
    
    try:
        # Move to position first (except for hotkey-only actions)
        if action != "hotkey" and hotkey is None:
            pyautogui.moveTo(x, y, duration=duration)
            time.sleep(0.05)  # Brief settle
        
        # Execute action
        if action == "click":
            pyautogui.click(x, y)
            msg = f"Clicked at ({x}, {y})"
            
        elif action == "double_click":
            pyautogui.doubleClick(x, y)
            msg = f"Double-clicked at ({x}, {y})"
            
        elif action == "right_click":
            pyautogui.rightClick(x, y)
            msg = f"Right-clicked at ({x}, {y})"
            
        elif action == "type":
            pyautogui.click(x, y)  # Focus first
            time.sleep(0.05)
            pyautogui.write(text, interval=0.01)
            msg = f"Typed '{text[:50]}...' at ({x}, {y})"
            
        elif action == "hover":
            pyautogui.moveTo(x, y, duration=duration)
            msg = f"Hovered at ({x}, {y})"
            
        elif action == "scroll":
            # Positive = up, negative = down
            pyautogui.scroll(int(text) if text else 0, x=x, y=y)
            direction = "up" if (text and int(text) > 0) else "down"
            msg = f"Scrolled {direction} at ({x}, {y})"
            
        elif action == "drag":
            # Expect text to be "target_x,target_y"
            try:
                tx, ty = map(int, text.split(","))
                pyautogui.dragTo(tx, ty, duration=duration)
                msg = f"Dragged from ({x}, {y}) to ({tx}, {ty})"
            except ValueError:
                return {"success": False, "error": "Drag requires 'target_x,target_y' in text param"}
                
        elif action == "hotkey":
            keys = hotkey if isinstance(hotkey, list) else [hotkey]
            pyautogui.hotkey(*keys)
            msg = f"Pressed hotkey: {'+'.join(keys)}"
            
        else:
            return {"success": False, "error": f"Unknown action: {action}"}
        
        logger.info(f"Action complete: {msg}")
        return {"success": True, "message": msg, "action": action, "x": x, "y": y}
    
    except pyautogui.FailSafeException:
        logger.error("PyAutoGUI failsafe triggered (mouse in corner)")
        return {"success": False, "error": "Failsafe triggered — mouse moved to screen corner"}
    
    except Exception as e:
        logger.error(f"Action execution failed: {e}")
        return {"success": False, "error": str(e)}


# ── High-Level Helpers ─────────────────────────────────────────
def find_and_click(description: str, user_query: str = "", context: str = "") -> Dict[str, Any]:
    """
    High-level: Analyze screen, find element matching description, click it.
    
    Returns result dict with success status.
    """
    analysis = analyze_screen(user_query=user_query, context=context)
    
    # Find best match by description similarity (simple contains for now)
    matches = [e for e in analysis.elements if description.lower() in e.description.lower()]
    
    if not matches:
        return {"success": False, "error": f"No element found matching '{description}'"} 
    
    # Pick highest confidence match
    target = max(matches, key=lambda e: e.confidence)
    
    return execute_ui_action(target.action_hint, target.x, target.y)


def find_element(description: str, user_query: str = "", context: str = "") -> Optional[UIElement]:
    """
    Find a UI element by description without clicking.
    Returns the element or None.
    """
    analysis = analyze_screen(user_query=user_query, context=context)
    matches = [e for e in analysis.elements if description.lower() in e.description.lower()]
    return max(matches, key=lambda e: e.confidence) if matches else None


# ── Safety & Utilities ─────────────────────────────────────────
def get_screen_size() -> Tuple[int, int]:
    """Return (width, height) of primary screen."""
    return pyautogui.size()


def safe_coordinates(x: int, y: int) -> Tuple[int, int]:
    """Clamp coordinates to screen bounds."""
    w, h = get_screen_size()
    return (max(0, min(x, w - 1)), max(0, min(y, h - 1)))


# ── Permission Wrapper (for tool registry) ─────────────────────
def request_permission(action_description: str) -> bool:
    """
    Placeholder for permission request.
    Actual implementation in groq_brain.py tool calling layer.
    Returns True if granted (simulated here for standalone testing).
    """
    # In production, this is handled by the voice layer
    logger.warning(f"PERMISSION REQUESTED: {action_description}")
    return True  # Standalone mode assumes granted


# ── Module Exports ─────────────────────────────────────────────
__all__ = [
    "UIElement",
    "ScreenAnalysis", 
    "analyze_screen",
    "execute_ui_action",
    "find_and_click",
    "find_element",
    "get_screen_size",
    "safe_coordinates",
    "request_permission",
    "capture_screen",
    "compress_image",
]