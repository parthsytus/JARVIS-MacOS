"""
==========================================================
JARVIS — Canva API Agent (Cloud Design Integration)
==========================================================

This module provides a scaffolded interface to the Canva REST API
for generating graphics programmatically.

Architecture:
  - CanvaAgent: High-level interface for JARVIS to create designs
  - CanvaAPIClient: Low-level HTTP client with auth & rate limiting
  - DesignBuilder: Fluent API for constructing design JSON

Authentication:
  - Uses Canva OAuth 2.0 (client credentials flow for server-to-server)
  - Requires CANVA_CLIENT_ID and CANVA_CLIENT_SECRET in .env
  - Access tokens cached and auto-refreshed

API Endpoints (Canva Connect API):
  - POST /v1/designs - Create new design
  - GET /v1/designs/{id} - Get design details
  - PATCH /v1/designs/{id} - Update design
  - POST /v1/designs/{id}/export - Export design
  - POST /v1/assets/upload - Upload media

Dependencies:
  pip install httpx tenacity python-dotenv

Author: JARVIS-MacOS Phase 3
"""

import os
import json
import time
import logging
import asyncio
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from urllib.parse import urljoin

try:
    import httpx
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
except ImportError:
    # Allow import without deps for syntax checking
    httpx = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Configuration ──────────────────────────────────────────────
CANVA_API_BASE = "https://api.canva.com/rest/v1/"
CANVA_AUTH_URL = "https://api.canva.com/rest/v1/oauth2/token"

CANVA_CLIENT_ID = os.getenv("CANVA_CLIENT_ID", "")
CANVA_CLIENT_SECRET = os.getenv("CANVA_CLIENT_SECRET", "")
CANVA_ACCESS_TOKEN = os.getenv("CANVA_ACCESS_TOKEN", "")  # Optional: pre-existing token

# Rate limiting
MAX_REQUESTS_PER_SECOND = 10
REQUEST_TIMEOUT = 30.0

# Logging
logger = logging.getLogger("JARVIS.CanvaAgent")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[CANVA_AGENT] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ── Enums & Data Classes ───────────────────────────────────────

class CanvaDesignType(str, Enum):
    """Supported Canva design types (subset)."""
    PRESENTATION = "presentation"
    SOCIAL_MEDIA = "social_media"
    POSTER = "poster"
    FLYER = "flyer"
    LOGO = "logo"
    INFOGRAPHIC = "infographic"
    VIDEO = "video"
    WHITEBOARD = "whiteboard"
    DOCUMENT = "document"
    CUSTOM = "custom"


class CanvaElementType(str, Enum):
    """Canva element types for design building."""
    TEXT = "text"
    IMAGE = "image"
    SHAPE = "shape"
    LINE = "line"
    FRAME = "frame"
    GROUP = "group"
    EMBED = "embed"
    CHART = "chart"
    TABLE = "table"


class CanvaFontWeight(str, Enum):
    THIN = "100"
    EXTRA_LIGHT = "200"
    LIGHT = "300"
    REGULAR = "400"
    MEDIUM = "500"
    SEMI_BOLD = "600"
    BOLD = "700"
    EXTRA_BOLD = "800"
    BLACK = "900"


class CanvaTextAlign(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


@dataclass
class CanvaColor:
    """Color representation for Canva."""
    r: int
    g: int
    b: int
    a: float = 1.0

    def to_hex(self) -> str:
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    @classmethod
    def from_hex(cls, hex_str: str) -> "CanvaColor":
        hex_str = hex_str.lstrip("#")
        if len(hex_str) == 3:
            hex_str = "".join(c * 2 for c in hex_str)
        r = int(hex_str[0:2], 16)
        g = int(hex_str[2:4], 16)
        b = int(hex_str[4:6], 16)
        return cls(r, g, b)

    @classmethod
    def from_rgb(cls, r: int, g: int, b: int, a: float = 1.0) -> "CanvaColor":
        return cls(r, g, b, a)

    def to_canva_dict(self) -> Dict:
        """Convert to Canva API color format."""
        return {
            "r": self.r / 255.0,
            "g": self.g / 255.0,
            "b": self.b / 255.0,
            "a": self.a
        }


@dataclass
class CanvaPosition:
    """Position and size on canvas."""
    x: float
    y: float
    width: float
    height: float
    rotation: float = 0.0


@dataclass
class CanvaTextStyle:
    """Text styling options."""
    font_family: str = "Inter"
    font_size: float = 16
    font_weight: CanvaFontWeight = CanvaFontWeight.REGULAR
    color: CanvaColor = field(default_factory=lambda: CanvaColor(0, 0, 0))
    line_height: float = 1.2
    letter_spacing: float = 0
    text_align: CanvaTextAlign = CanvaTextAlign.LEFT
    text_transform: str = "none"  # none, uppercase, lowercase, capitalize
    text_decoration: str = "none"  # none, underline, strikethrough


@dataclass
class CanvaFill:
    """Fill configuration for shapes."""
    type: str = "solid"  # solid, gradient, pattern
    color: Optional[CanvaColor] = None
    gradient: Optional[Dict] = None
    opacity: float = 1.0

    def to_canva_dict(self) -> Dict:
        """Convert to Canva API format."""
        result = {"type": self.type, "opacity": self.opacity}
        if self.color:
            result["color"] = self.color.to_canva_dict()
        if self.gradient:
            result["gradient"] = self.gradient
        return result


@dataclass
class CanvaStroke:
    """Stroke/border configuration."""
    color: CanvaColor = field(default_factory=lambda: CanvaColor(0, 0, 0))
    weight: float = 1
    style: str = "solid"  # solid, dashed, dotted
    dash_pattern: Optional[List[float]] = None


@dataclass
class CanvaElement:
    """Base element for Canva designs."""
    id: str = field(default_factory=lambda: f"elem_{int(time.time() * 1000)}")
    type: CanvaElementType = CanvaElementType.SHAPE
    position: CanvaPosition = field(default_factory=lambda: CanvaPosition(0, 0, 100, 100))
    name: str = ""
    visible: bool = True
    locked: bool = False
    opacity: float = 1.0
    rotation: float = 0.0
    fill: Optional[CanvaFill] = None
    stroke: Optional[CanvaStroke] = None
    corner_radius: float = 0

    # Type-specific fields
    text: str = ""
    text_style: Optional[CanvaTextStyle] = None
    image_url: str = ""
    image_asset_id: str = ""

    def to_canva_dict(self) -> Dict:
        """Convert to Canva API element format."""
        base = {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "position": {
                "x": self.position.x,
                "y": self.position.y,
                "width": self.position.width,
                "height": self.position.height
            },
            "rotation": self.rotation,
            "visible": self.visible,
            "locked": self.locked,
            "opacity": self.opacity
        }

        if self.fill:
            base["fill"] = self.fill.to_canva_dict() if hasattr(self.fill, 'to_canva_dict') else self.fill

        if self.stroke:
            base["stroke"] = {
                "color": self.stroke.color.to_canva_dict(),
                "weight": self.stroke.weight,
                "style": self.stroke.style
            }
            if self.stroke.dash_pattern:
                base["stroke"]["dashPattern"] = self.stroke.dash_pattern

        if self.corner_radius > 0:
            base["cornerRadius"] = self.corner_radius

        # Type-specific
        if self.type == CanvaElementType.TEXT:
            base["text"] = self.text
            if self.text_style:
                base["textStyle"] = {
                    "fontFamily": self.text_style.font_family,
                    "fontSize": self.text_style.font_size,
                    "fontWeight": self.text_style.font_weight.value,
                    "color": self.text_style.color.to_canva_dict(),
                    "lineHeight": self.text_style.line_height,
                    "letterSpacing": self.text_style.letter_spacing,
                    "textAlign": self.text_style.text_align.value,
                    "textTransform": self.text_style.text_transform,
                    "textDecoration": self.text_style.text_decoration
                }

        if self.type == CanvaElementType.IMAGE:
            base["imageUrl"] = self.image_url
            if self.image_asset_id:
                base["assetId"] = self.image_asset_id

        return base


@dataclass
class CanvaPage:
    """A page/slide in a Canva design."""
    id: str = field(default_factory=lambda: f"page_{int(time.time() * 1000)}")
    name: str = "Page"
    elements: List[CanvaElement] = field(default_factory=list)
    background: Optional[CanvaFill] = None
    width: float = 1920
    height: float = 1080

    def to_canva_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "background": self.background.to_canva_dict() if self.background else None,
            "elements": [e.to_canva_dict() for e in self.elements]
        }


@dataclass
class CanvaDesign:
    """Complete Canva design."""
    id: str = ""
    title: str = "Untitled Design"
    design_type: CanvaDesignType = CanvaDesignType.CUSTOM
    pages: List[CanvaPage] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    tags: List[str] = field(default_factory=list)
    folders: List[str] = field(default_factory=list)

    def to_canva_dict(self) -> Dict:
        return {
            "title": self.title,
            "type": self.design_type.value,
            "pages": [p.to_canva_dict() for p in self.pages],
            "tags": self.tags,
            "folders": self.folders
        }


# ── Token Management ───────────────────────────────────────────

@dataclass
class TokenData:
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: str = ""
    scope: str = ""
    obtained_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        return time.time() - self.obtained_at > (self.expires_in - 60)  # 60s buffer

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "TokenData":
        return cls(**data)


class TokenManager:
    """Manages Canva OAuth tokens with auto-refresh."""

    def __init__(self, client_id: str = "", client_secret: str = "", token_file: str = ".canva_token"):
        self.client_id = client_id or CANVA_CLIENT_ID
        self.client_secret = client_secret or CANVA_CLIENT_SECRET
        self.token_file = Path(token_file)
        self._token: Optional[TokenData] = None
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Get valid access token, refreshing if needed."""
        async with self._lock:
            if self._token is None:
                await self._load_token()

            if self._token is None or self._token.is_expired:
                if self._token and self._token.refresh_token:
                    await self._refresh_token()
                else:
                    await self._fetch_new_token()

            return self._token.access_token

    async def _load_token(self):
        """Load token from file."""
        if self.token_file.exists():
            try:
                data = json.loads(self.token_file.read_text())
                self._token = TokenData.from_dict(data)
                logger.info("Loaded Canva token from cache")
            except Exception as e:
                logger.warning(f"Failed to load token: {e}")

    async def _save_token(self):
        """Save token to file."""
        if self._token:
            try:
                self.token_file.write_text(json.dumps(self._token.to_dict()))
            except Exception as e:
                logger.error(f"Failed to save token: {e}")

    async def _fetch_new_token(self):
        """Fetch new token via client credentials flow."""
        if not self.client_id or not self.client_secret:
            raise ValueError("CANVA_CLIENT_ID and CANVA_CLIENT_SECRET required")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                CANVA_AUTH_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            response.raise_for_status()
            data = response.json()

            self._token = TokenData(
                access_token=data["access_token"],
                token_type=data.get("token_type", "Bearer"),
                expires_in=data.get("expires_in", 3600),
                scope=data.get("scope", "")
            )
            await self._save_token()
            logger.info("Obtained new Canva access token")

    async def _refresh_token(self):
        """Refresh access token using refresh token."""
        if not self._token or not self._token.refresh_token:
            await self._fetch_new_token()
            return

        async with httpx.AsyncClient() as client:
            response = await client.post(
                CANVA_AUTH_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._token.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            response.raise_for_status()
            data = response.json()

            self._token = TokenData(
                access_token=data["access_token"],
                token_type=data.get("token_type", "Bearer"),
                expires_in=data.get("expires_in", 3600),
                refresh_token=data.get("refresh_token", self._token.refresh_token),
                scope=data.get("scope", self._token.scope)
            )
            await self._save_token()
            logger.info("Refreshed Canva access token")


# ── Canva API Client ───────────────────────────────────────────

class CanvaAPIClient:
    """Low-level HTTP client for Canva API."""

    def __init__(self, token_manager: TokenManager):
        self.token_manager = token_manager
        self.client: Optional[httpx.AsyncClient] = None
        self._rate_limiter = asyncio.Semaphore(MAX_REQUESTS_PER_SECOND)
        self._last_request = 0

    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            base_url=CANVA_API_BASE,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "JARVIS-CanvaAgent/1.0"}
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> httpx.Response:
        """Make authenticated request with rate limiting."""
        token = await self.token_manager.get_token()

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"

        # Rate limiting
        async with self._rate_limiter:
            now = time.time()
            if now - self._last_request < 1.0 / MAX_REQUESTS_PER_SECOND:
                await asyncio.sleep(1.0 / MAX_REQUESTS_PER_SECOND - (now - self._last_request))
            self._last_request = time.time()

            response = await self.client.request(
                method,
                endpoint,
                headers=headers,
                **kwargs
            )

            # Handle token expiry
            if response.status_code == 401:
                logger.warning("Token expired, refreshing...")
                self.token_manager._token = None  # Force refresh
                token = await self.token_manager.get_token()
                headers["Authorization"] = f"Bearer {token}"
                response = await self.client.request(
                    method, endpoint, headers=headers, **kwargs
                )

            return response

    # ── Design Operations ──────────────────────────────────────

    async def create_design(self, design: CanvaDesign) -> Dict:
        """Create a new design."""
        response = await self._request(
            "POST",
            "designs",
            json=design.to_canva_dict()
        )
        response.raise_for_status()
        return response.json()

    async def get_design(self, design_id: str) -> Dict:
        """Get design details."""
        response = await self._request("GET", f"designs/{design_id}")
        response.raise_for_status()
        return response.json()

    async def update_design(self, design_id: str, design: CanvaDesign) -> Dict:
        """Update an existing design."""
        response = await self._request(
            "PATCH",
            f"designs/{design_id}",
            json=design.to_canva_dict()
        )
        response.raise_for_status()
        return response.json()

    async def delete_design(self, design_id: str) -> bool:
        """Delete a design."""
        response = await self._request("DELETE", f"designs/{design_id}")
        return response.status_code == 204

    async def list_designs(
        self,
        limit: int = 50,
        offset: int = 0,
        design_type: Optional[str] = None
    ) -> Dict:
        """List designs with pagination."""
        params = {"limit": limit, "offset": offset}
        if design_type:
            params["type"] = design_type

        response = await self._request("GET", "designs", params=params)
        response.raise_for_status()
        return response.json()

    # ── Export Operations ──────────────────────────────────────

    async def export_design(
        self,
        design_id: str,
        format: str = "pdf",  # pdf, png, jpg, pptx, mp4
        pages: Optional[List[int]] = None,
        quality: str = "high"  # low, medium, high
    ) -> Dict:
        """Export design to file."""
        payload = {"format": format, "quality": quality}
        if pages:
            payload["pages"] = pages

        response = await self._request(
            "POST",
            f"designs/{design_id}/export",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def download_export(self, export_url: str, dest_path: str) -> bool:
        """Download exported file from URL."""
        async with httpx.AsyncClient() as client:
            response = await client.get(export_url, timeout=60.0)
            response.raise_for_status()
            Path(dest_path).write_bytes(response.content)
            return True

    # ── Asset Operations ───────────────────────────────────────

    async def upload_asset(
        self,
        file_path: str,
        parent_folder: str = ""
    ) -> Dict:
        """Upload an asset (image, font, etc.)."""
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(file_path)

        with file_path.open("rb") as f:
            files = {"file": (file_path.name, f, "application/octet-stream")}
            data = {"parent_folder": parent_folder} if parent_folder else {}

            response = await self._request(
                "POST",
                "assets/upload",
                files=files,
                data=data
            )
            response.raise_for_status()
            return response.json()

    async def list_assets(
        self,
        asset_type: Optional[str] = None,
        folder: str = "",
        limit: int = 50
    ) -> Dict:
        """List uploaded assets."""
        params = {"limit": limit}
        if asset_type:
            params["type"] = asset_type
        if folder:
            params["folder"] = folder

        response = await self._request("GET", "assets", params=params)
        response.raise_for_status()
        return response.json()

    # ── Brand Kit Operations ──────────────────────────────────

    async def get_brand_kits(self) -> Dict:
        """Get available brand kits."""
        response = await self._request("GET", "brand-kits")
        response.raise_for_status()
        return response.json()

    async def get_brand_kit(self, kit_id: str) -> Dict:
        """Get brand kit details (colors, fonts, logos)."""
        response = await self._request("GET", f"brand-kits/{kit_id}")
        response.raise_for_status()
        return response.json()


# ── High-Level Agent ──────────────────────────────────────────

class CanvaAgent:
    """
    High-level agent for JARVIS to create Canva designs.
    Provides fluent builders for common design patterns.
    """

    def __init__(self):
        self.token_manager = TokenManager()
        self._client: Optional[CanvaAPIClient] = None

    async def __aenter__(self):
        self._client = CanvaAPIClient(self.token_manager)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)

    @property
    def client(self) -> CanvaAPIClient:
        if not self._client:
            raise RuntimeError("CanvaAgent not initialized. Use 'async with CanvaAgent() as agent:'")
        return self._client

    # ── Design Builders ────────────────────────────────────────

    def create_presentation(
        self,
        title: str,
        width: float = 1920,
        height: float = 1080,
        theme: str = "light"
    ) -> "PresentationBuilder":
        """Create a presentation builder."""
        return PresentationBuilder(self, title, width, height, theme)

    def create_social_post(
        self,
        title: str,
        platform: str = "instagram",
        width: float = 1080,
        height: float = 1080
    ) -> "SocialPostBuilder":
        """Create a social media post builder."""
        return SocialPostBuilder(self, title, platform, width, height)

    def create_infographic(
        self,
        title: str,
        width: float = 800,
        height: float = 2000
    ) -> "InfographicBuilder":
        """Create an infographic builder."""
        return InfographicBuilder(self, title, width, height)

    def create_custom_design(
        self,
        title: str,
        width: float = 1920,
        height: float = 1080
    ) -> "DesignBuilder":
        """Create a generic design builder."""
        return DesignBuilder(self, title, width, height)


# ── Fluent Design Builders ────────────────────────────────────

class DesignBuilder:
    """Fluent API for building Canva designs."""

    def __init__(self, agent: CanvaAgent, title: str, width: float, height: float):
        self.agent = agent
        self.design = CanvaDesign(
            title=title,
            design_type=CanvaDesignType.CUSTOM
        )
        self.current_page = CanvaPage(width=width, height=height)
        self.design.pages.append(self.current_page)

    def page(self, name: str = "Page", width: float = None, height: float = None) -> "DesignBuilder":
        """Add a new page and make it current."""
        self.design.pages.append(self.current_page)
        self.current_page = CanvaPage(
            name=name,
            width=width or self.current_page.width,
            height=height or self.current_page.height
        )
        return self

    def background(self, color: Union[str, CanvaColor]) -> "DesignBuilder":
        """Set page background."""
        if isinstance(color, str):
            color = CanvaColor.from_hex(color)
        self.current_page.background = CanvaFill(type="solid", color=color)
        return self

    def add_element(self, element: CanvaElement) -> "DesignBuilder":
        """Add an element to current page."""
        self.current_page.elements.append(element)
        return self

    # ── Convenience Element Methods ───────────────────────────

    def text(
        self,
        text: str,
        x: float, y: float,
        width: float = 400, height: float = 50,
        style: CanvaTextStyle = None,
        name: str = "Text"
    ) -> "DesignBuilder":
        """Add text element."""
        if style is None:
            style = CanvaTextStyle()
        element = CanvaElement(
            type=CanvaElementType.TEXT,
            position=CanvaPosition(x, y, width, height),
            name=name,
            text=text,
            text_style=style
        )
        self.current_page.elements.append(element)
        return self

    def rectangle(
        self,
        x: float, y: float,
        width: float, height: float,
        fill: Union[str, CanvaColor] = "#007AFF",
        corner_radius: float = 0,
        stroke: CanvaStroke = None,
        name: str = "Rectangle"
    ) -> "DesignBuilder":
        """Add rectangle shape."""
        if isinstance(fill, str):
            fill = CanvaColor.from_hex(fill)
        element = CanvaElement(
            type=CanvaElementType.SHAPE,
            position=CanvaPosition(x, y, width, height),
            name=name,
            fill=CanvaFill(type="solid", color=fill),
            stroke=stroke,
            corner_radius=corner_radius
        )
        self.current_page.elements.append(element)
        return self

    def circle(
        self,
        x: float, y: float,
        diameter: float,
        fill: Union[str, CanvaColor] = "#FF6B6B",
        name: str = "Circle"
    ) -> "DesignBuilder":
        """Add circle (ellipse with equal width/height)."""
        if isinstance(fill, str):
            fill = CanvaColor.from_hex(fill)
        element = CanvaElement(
            type=CanvaElementType.SHAPE,  # Use ellipse type
            position=CanvaPosition(x, y, diameter, diameter),
            name=name,
            fill=CanvaFill(type="solid", color=fill),
            corner_radius=diameter / 2  # Full circle
        )
        self.current_page.elements.append(element)
        return self

    def line(
        self,
        x1: float, y1: float,
        x2: float, y2: float,
        stroke: CanvaStroke = None,
        name: str = "Line"
    ) -> "DesignBuilder":
        """Add line."""
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        x = min(x1, x2)
        y = min(y1, y2)

        if stroke is None:
            stroke = CanvaStroke(color=CanvaColor(0, 0, 0), weight=2)

        element = CanvaElement(
            type=CanvaElementType.LINE,
            position=CanvaPosition(x, y, width, height),
            name=name,
            stroke=stroke
        )
        self.current_page.elements.append(element)
        return self

    def image(
        self,
        x: float, y: float,
        width: float, height: float,
        image_url: str = "",
        asset_id: str = "",
        name: str = "Image"
    ) -> "DesignBuilder":
        """Add image element."""
        element = CanvaElement(
            type=CanvaElementType.IMAGE,
            position=CanvaPosition(x, y, width, height),
            name=name,
            image_url=image_url,
            image_asset_id=asset_id
        )
        self.current_page.elements.append(element)
        return self

    def frame(
        self,
        x: float, y: float,
        width: float, height: float,
        fill: Union[str, CanvaColor] = "#FFFFFF",
        layout_mode: str = "NONE",
        padding: float = 0,
        item_spacing: float = 0,
        name: str = "Frame"
    ) -> "DesignBuilder":
        """Add frame container."""
        if isinstance(fill, str):
            fill = CanvaColor.from_hex(fill)
        element = CanvaElement(
            type=CanvaElementType.FRAME,
            position=CanvaPosition(x, y, width, height),
            name=name,
            fill=CanvaFill(type="solid", color=fill)
        )
        self.current_page.elements.append(element)
        return self

    def group(self, element_ids: List[str], name: str = "Group") -> "DesignBuilder":
        """Group elements (creates a group element referencing others)."""
        # Canva handles grouping at the API level
        group = CanvaElement(
            type=CanvaElementType.GROUP,
            position=CanvaPosition(0, 0, 1, 1),
            name=name
        )
        group.text = json.dumps(element_ids)  # Store referenced IDs in text field
        self.current_page.elements.append(group)
        return self

    # ── Finalization ──────────────────────────────────────────

    def build(self) -> CanvaDesign:
        """Finalize and return the design."""
        if self.current_page not in self.design.pages:
            self.design.pages.append(self.current_page)
        return self.design

    async def create(self) -> Dict:
        """Create design in Canva."""
        design = self.build()
        return await self.agent.client.create_design(design)

    async def create_and_export(
        self,
        format: str = "pdf",
        quality: str = "high"
    ) -> Dict:
        """Create design and export immediately."""
        result = await self.create()
        design_id = result.get("id") or result.get("design", {}).get("id")
        if design_id:
            return await self.agent.client.export_design(design_id, format=format)
        return result


class PresentationBuilder(DesignBuilder):
    """Builder for presentation slides."""

    def __init__(self, agent: CanvaAgent, title: str, width: float, height: float, theme: str):
        super().__init__(agent, title, width, height)
        self.design.design_type = CanvaDesignType.PRESENTATION
        self.theme = theme
        self._apply_theme(theme)

    def _apply_theme(self, theme: str):
        """Apply theme colors."""
        if theme == "dark":
            self.background("#1A1A2E")
            self.default_text_color = CanvaColor(255, 255, 255)
            self.accent_color = CanvaColor(0, 122, 255)
        else:
            self.background("#FFFFFF")
            self.default_text_color = CanvaColor(26, 26, 46)
            self.accent_color = CanvaColor(0, 122, 255)

    def slide(self, title: str = "", layout: str = "blank") -> "PresentationBuilder":
        """Add a new slide."""
        self.page(name=title or f"Slide {len(self.design.pages) + 1}")
        return self

    def title_slide(
        self,
        title: str,
        subtitle: str = "",
        x: float = 100, y: float = 200
    ) -> "PresentationBuilder":
        """Add title slide layout."""
        self.text(
            title, x, y, width=1720, height=120,
            style=CanvaTextStyle(
                font_size=64,
                font_weight=CanvaFontWeight.BOLD,
                color=self.default_text_color
            ),
            name="Title"
        )
        if subtitle:
            self.text(
                subtitle, x, y + 140, width=1720, height=60,
                style=CanvaTextStyle(
                    font_size=28,
                    font_weight=CanvaFontWeight.REGULAR,
                    color=CanvaColor(128, 128, 128)
                ),
                name="Subtitle"
            )
        return self

    def content_slide(
        self,
        title: str,
        bullets: List[str],
        x: float = 100, y: float = 150
    ) -> "PresentationBuilder":
        """Add content slide with bullet points."""
        self.text(
            title, x, y, width=1720, height=80,
            style=CanvaTextStyle(
                font_size=40,
                font_weight=CanvaFontWeight.BOLD,
                color=self.default_text_color
            ),
            name="Slide Title"
        )

        y_pos = y + 120
        for i, bullet in enumerate(bullets):
            self.text(
                f"• {bullet}", x + 40, y_pos + i * 60, width=1600, height=50,
                style=CanvaTextStyle(
                    font_size=24,
                    font_weight=CanvaFontWeight.REGULAR,
                    color=self.default_text_color
                ),
                name=f"Bullet {i + 1}"
            )
        return self


class SocialPostBuilder(DesignBuilder):
    """Builder for social media posts."""

    PLATFORM_SIZES = {
        "instagram": (1080, 1080),
        "instagram_story": (1080, 1920),
        "facebook": (1200, 630),
        "twitter": (1200, 675),
        "linkedin": (1200, 627),
        "pinterest": (1000, 1500),
        "tiktok": (1080, 1920),
        "youtube_thumbnail": (1280, 720)
    }

    def __init__(self, agent: CanvaAgent, title: str, platform: str, width: float, height: float):
        super().__init__(agent, title, width, height)
        self.design.design_type = CanvaDesignType.SOCIAL_MEDIA
        self.platform = platform.lower()
        if platform in self.PLATFORM_SIZES:
            w, h = self.PLATFORM_SIZES[platform]
            self.design.pages[0].width = w
            self.design.pages[0].height = h
            self.current_page.width = w
            self.current_page.height = h

    def add_brand_watermark(self, logo_url: str, position: str = "bottom-right"):
        """Add brand watermark."""
        if self.current_page.width and self.current_page.height:
            if position == "bottom-right":
                x = self.current_page.width - 120
                y = self.current_page.height - 120
            elif position == "top-left":
                x, y = 20, 20
            else:
                x, y = 20, 20
            self.image(x, y, 100, 100, image_url=logo_url, name="Watermark")


class InfographicBuilder(DesignBuilder):
    """Builder for infographics."""

    def __init__(self, agent: CanvaAgent, title: str, width: float, height: float):
        super().__init__(agent, title, width, height)
        self.design.design_type = CanvaDesignType.INFOGRAPHIC
        self.section_y = 100

    def header(self, title: str, subtitle: str = "") -> "InfographicBuilder":
        """Add infographic header."""
        self.text(
            title, 100, 50, width=self.current_page.width - 200, height=80,
            style=CanvaTextStyle(
                font_size=48,
                font_weight=CanvaFontWeight.BOLD,
                color=CanvaColor(26, 26, 46),
                text_align=CanvaTextAlign.CENTER
            ),
            name="Infographic Title"
        )
        if subtitle:
            self.text(
                subtitle, 100, 140, width=self.current_page.width - 200, height=40,
                style=CanvaTextStyle(
                    font_size=20,
                    font_weight=CanvaFontWeight.REGULAR,
                    color=CanvaColor(100, 100, 100),
                    text_align=CanvaTextAlign.CENTER
                ),
                name="Infographic Subtitle"
            )
        self.section_y = 220
        return self

    def stat_card(
        self,
        value: str,
        label: str,
        x: float, y: float,
        width: float = 300, height: float = 200,
        icon: str = "",
        accent_color: str = "#007AFF"
    ) -> "InfographicBuilder":
        """Add a statistic card."""
        card = CanvaElement(
            type=CanvaElementType.FRAME,
            position=CanvaPosition(x, y, width, height),
            name=f"Stat Card: {label}",
            fill=CanvaFill(type="solid", color=CanvaColor(255, 255, 255)),
            corner_radius=16
        )
        self.current_page.elements.append(card)

        # Value
        self.text(
            value, x + 24, y + 40, width=width - 48, height=80,
            style=CanvaTextStyle(
                font_size=48,
                font_weight=CanvaFontWeight.BOLD,
                color=CanvaColor.from_hex(accent_color),
                text_align=CanvaTextAlign.CENTER
            ),
            name=f"Stat Value: {label}"
        )

        # Label
        self.text(
            label, x + 24, y + 130, width=width - 48, height=40,
            style=CanvaTextStyle(
                font_size=18,
                font_weight=CanvaFontWeight.MEDIUM,
                color=CanvaColor(100, 100, 100),
                text_align=CanvaTextAlign.CENTER
            ),
            name=f"Stat Label: {label}"
        )

        return self

    def section_divider(self, y: float = None) -> "InfographicBuilder":
        """Add horizontal divider line."""
        y = y or self.section_y
        self.line(
            100, y, self.current_page.width - 100, y,
            stroke=CanvaStroke(
                color=CanvaColor(200, 200, 200),
                weight=1,
                style="dashed",
                dash_pattern=[10, 10]
            ),
            name="Section Divider"
        )
        self.section_y = y + 40
        return self


# ── Module Exports ─────────────────────────────────────────────

__all__ = [
    # Enums
    "CanvaDesignType",
    "CanvaElementType",
    "CanvaFontWeight",
    "CanvaTextAlign",
    # Data Classes
    "CanvaColor",
    "CanvaPosition",
    "CanvaTextStyle",
    "CanvaFill",
    "CanvaStroke",
    "CanvaElement",
    "CanvaPage",
    "CanvaDesign",
    # Core Classes
    "TokenManager",
    "CanvaAPIClient",
    "CanvaAgent",
    # Builders
    "DesignBuilder",
    "PresentationBuilder",
    "SocialPostBuilder",
    "InfographicBuilder",
]

# ── Demo / Test ────────────────────────────────────────────────

async def demo():
    """Demo creating a simple design."""
    async with CanvaAgent() as agent:
        # Create a presentation
        builder = agent.create_presentation("JARVIS Quarterly Report", theme="dark")
        
        builder.title_slide(
            "JARVIS Quarterly Report",
            "Q3 2026 Performance Metrics"
        )
        
        builder.content_slide(
            "Key Achievements",
            [
                "Revenue up 23% YoY",
                "User retention at 94%",
                "Launched 3 new integrations",
                "Zero critical incidents"
            ]
        )
        
        # Create infographic
        infographic = agent.create_infographic("System Metrics")
        infographic.header("System Health Overview", "Real-time monitoring dashboard")
        
        infographic.stat_card("99.99%", "Uptime", 100, 250, accent_color="#00D4AA")
        infographic.stat_card("12ms", "Avg Latency", 450, 250, accent_color="#007AFF")
        infographic.stat_card("2.4M", "Requests/min", 800, 250, accent_color="#FF6B6B")
        infographic.stat_card("0", "Critical Errors", 1150, 250, accent_color="#FFD700")
        
        infographic.section_divider()
        
        # Build and create
        design = infographic.build()
        print(f"Created design: {design.title}")
        print(f"Pages: {len(design.pages)}")
        print(f"Elements: {sum(len(p.elements) for p in design.pages)}")

if __name__ == "__main__":
    asyncio.run(demo())