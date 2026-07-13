"""
JARVIS Integrations Package
===========================
External service integrations for JARVIS.
"""

from .figma_agent import (
    FigmaAgent,
    FigmaWebSocketServer,
    FigmaNode,
    DesignBlueprint,
    SelectionEvent,
    get_figma_agent
)

from .canva_agent import (
    CanvaAgent,
    CanvaAPIClient,
    TokenManager,
    CanvaDesign,
    CanvaPage,
    CanvaElement,
    CanvaElementType,
    CanvaDesignType,
    CanvaFill,
    CanvaStroke,
    CanvaPosition,
    CanvaTextStyle,
    CanvaFontWeight,
    CanvaTextAlign,
    CanvaColor,
    PresentationBuilder,
    SocialPostBuilder,
    InfographicBuilder,
    DesignBuilder,
    CANVA_API_BASE,
    CANVA_AUTH_URL,
    MAX_REQUESTS_PER_SECOND,
    REQUEST_TIMEOUT,
)

from core.transparent_overlay import (
    draw_hologram_target,
    clear_hologram_targets,
    shutdown_hologram,
    get_hologram_controller,
    HologramController,
    HologramTarget
)

__all__ = [
    # Figma
    "FigmaAgent",
    "FigmaWebSocketServer",
    "FigmaNode",
    "DesignBlueprint",
    "SelectionEvent",
    "get_figma_agent",
    
    # Canva
    "CanvaAgent",
    "CanvaAPIClient",
    "TokenManager",
    "CanvaDesign",
    "CanvaPage",
    "CanvaElement",
    "CanvaElementType",
    "CanvaDesignType",
    "CanvaFill",
    "CanvaStroke",
    "CanvaPosition",
    "CanvaTextStyle",
    "CanvaFontWeight",
    "CanvaTextAlign",
    "CanvaColor",
    "PresentationBuilder",
    "SocialPostBuilder",
    "InfographicBuilder",
    "DesignBuilder",
    "CANVA_API_BASE",
    "CANVA_AUTH_URL",
    "MAX_REQUESTS_PER_SECOND",
    "REQUEST_TIMEOUT",
    
    # Hologram
    "draw_hologram_target",
    "clear_hologram_targets",
    "shutdown_hologram",
    "get_hologram_controller",
    "HologramController",
    "HologramTarget"
]