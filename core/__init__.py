"""
JARVIS Core Package
====================
Core modules for JARVIS voice assistant.
"""

from .system_operator import (
    UIElement,
    ScreenAnalysis,
    analyze_screen,
    execute_ui_action,
    find_and_click,
    find_element,
    get_screen_size,
    safe_coordinates,
    request_permission
)

from .transparent_overlay import (
    HologramController,
    HologramTarget,
    get_hologram_controller,
    draw_hologram_target,
    clear_hologram_targets,
    shutdown_hologram
)

__all__ = [
    # System Operator
    "UIElement",
    "ScreenAnalysis",
    "analyze_screen",
    "execute_ui_action",
    "find_and_click",
    "find_element",
    "get_screen_size",
    "safe_coordinates",
    "request_permission",
    
    # Transparent Overlay
    "HologramController",
    "HologramTarget",
    "get_hologram_controller",
    "draw_hologram_target",
    "clear_hologram_targets",
    "shutdown_hologram"
]