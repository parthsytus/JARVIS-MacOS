"""
JARVIS Integrations Package
===========================
External service integrations for JARVIS.
"""

from core.transparent_overlay import (
    draw_hologram_target,
    clear_hologram_targets,
    shutdown_hologram,
    get_hologram_controller,
    HologramController,
    HologramTarget
)

__all__ = [
    # Hologram
    "draw_hologram_target",
    "clear_hologram_targets",
    "shutdown_hologram",
    "get_hologram_controller",
    "HologramController",
    "HologramTarget"
]