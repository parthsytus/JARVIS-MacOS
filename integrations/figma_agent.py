"""
==========================================================
JARVIS — Figma Bridge (Python WebSocket Server)
==========================================================

This module provides a lightweight WebSocket server that runs in a
background thread to communicate with a Figma plugin.

Architecture:
  Python Side (this file):
    - Runs asyncio WebSocket server on localhost:8765
    - Exposes send_design_blueprint() for JARVIS to send layout commands
    - Receives selection events from Figma plugin for bi-directional context
  
  Figma Side (plugins/figma-jarvis/code.js):
    - Connects to ws://localhost:8765
    - Listens for JSON layout commands to draw vectors natively
    - Broadcasts figma.on('selectionchange') back to Python

Dependencies:
  pip install websockets

Author: JARVIS-MacOS Phase 3
"""

import asyncio
import json
import logging
import threading
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────
FIGMA_WS_HOST = "localhost"
FIGMA_WS_PORT = 8765
HEARTBEAT_INTERVAL = 30  # seconds

# ── Logging ────────────────────────────────────────────────────
logger = logging.getLogger("JARVIS.FigmaAgent")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[FIGMA_AGENT] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ── Data Classes ───────────────────────────────────────────────
@dataclass
class FigmaNode:
    """Represents a Figma canvas node."""
    id: str
    type: str  # RECTANGLE, ELLIPSE, FRAME, TEXT, COMPONENT, etc.
    name: str
    x: float
    y: float
    width: float
    height: float
    fills: List[Dict] = None
    strokes: List[Dict] = None
    characters: str = ""  # For TEXT nodes
    font_size: float = 14
    parent_id: str = ""


@dataclass
class DesignBlueprint:
    """A design layout blueprint sent from JARVIS to Figma."""
    nodes: List[Dict]  # Each node dict matches Figma's create API
    canvas_size: Dict[str, float] = None  # width, height
    metadata: Dict = None  # Any additional context


@dataclass
class SelectionEvent:
    """Selection change event from Figma plugin."""
    selected_nodes: List[FigmaNode]
    timestamp: str


# ── Figma WebSocket Server ────────────────────────────────────
class FigmaWebSocketServer:
    """
    Asyncio WebSocket server for Figma plugin communication.
    Runs in a dedicated thread with its own event loop.
    """
    
    def __init__(self, host: str = FIGMA_WS_HOST, port: int = FIGMA_WS_PORT):
        self.host = host
        self.port = port
        self._server = None
        self._loop = None
        self._thread = None
        self._running = False
        
        # Connected Figma plugin clients
        self._clients: set = set()
        
        # Callbacks
        self.on_selection_change: Optional[Callable[[SelectionEvent], None]] = None
        self.on_client_connected: Optional[Callable[[], None]] = None
        self.on_client_disconnected: Optional[Callable[[], None]] = None
        
        # Pending commands awaiting response
        self._pending_commands: Dict[str, asyncio.Future] = {}
        self._command_id_counter = 0
    
    def start(self):
        """Start the WebSocket server in a background thread."""
        if self._running:
            logger.warning("Figma WebSocket server already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        logger.info(f"Figma WebSocket server starting on ws://{self.host}:{self.port}")
    
    def stop(self):
        """Stop the WebSocket server."""
        if not self._running:
            return
        
        self._running = False
        
        # Close all client connections
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._close_all_clients(), self._loop)
        
        # Stop the event loop
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        
        if self._thread:
            self._thread.join(timeout=5)
        
        logger.info("Figma WebSocket server stopped")
    
    def _run_server(self):
        """Run the asyncio event loop with the WebSocket server."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        try:
            self._loop.run_until_complete(self._start_server())
            self._loop.run_forever()
        except Exception as e:
            logger.error(f"Figma WebSocket server error: {e}")
        finally:
            self._loop.close()
    
    async def _start_server(self):
        """Start the WebSocket server."""
        import websockets
        
        self._server = await websockets.serve(
            self._handle_client,
            self.host,
            self.port,
            ping_interval=HEARTBEAT_INTERVAL,
            ping_timeout=10
        )
        logger.info(f"Figma WebSocket server listening on ws://{self.host}:{self.port}")
    
    async def _handle_client(self, websocket, path):
        """Handle a connected Figma plugin client."""
        client_id = id(websocket)
        self._clients.add(websocket)
        logger.info(f"Figma plugin connected (clients: {len(self._clients)})")
        
        if self.on_client_connected:
            self.on_client_connected()
        
        try:
            async for message in websocket:
                await self._process_message(websocket, message)
        except Exception as e:
            logger.warning(f"Client {client_id} error: {e}")
        finally:
            self._clients.discard(websocket)
            logger.info(f"Figma plugin disconnected (clients: {len(self._clients)})")
            if self.on_client_disconnected:
                self.on_client_disconnected()
    
    async def _process_message(self, websocket, message: str):
        """Process incoming message from Figma plugin."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "selection_change":
                await self._handle_selection_change(data)
            elif msg_type == "command_response":
                await self._handle_command_response(data)
            elif msg_type == "heartbeat":
                await websocket.send(json.dumps({"type": "heartbeat_ack"}))
            else:
                logger.warning(f"Unknown message type: {msg_type}")
                
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from Figma plugin: {message[:100]}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    async def _handle_selection_change(self, data: dict):
        """Handle selection change event from Figma."""
        nodes_data = data.get("nodes", [])
        nodes = []
        
        for n in nodes_data:
            node = FigmaNode(
                id=n.get("id", ""),
                type=n.get("type", "UNKNOWN"),
                name=n.get("name", ""),
                x=n.get("x", 0),
                y=n.get("y", 0),
                width=n.get("width", 0),
                height=n.get("height", 0),
                fills=n.get("fills", []),
                strokes=n.get("strokes", []),
                characters=n.get("characters", ""),
                font_size=n.get("fontSize", 14),
                parent_id=n.get("parentId", "")
            )
            nodes.append(node)
        
        event = SelectionEvent(
            selected_nodes=nodes,
            timestamp=datetime.now().isoformat()
        )
        
        if self.on_selection_change:
            self.on_selection_change(event)
    
    async def _handle_command_response(self, data: dict):
        """Handle response to a command we sent."""
        command_id = data.get("command_id")
        if command_id in self._pending_commands:
            future = self._pending_commands.pop(command_id)
            if not future.done():
                future.set_result(data)
    
    async def _close_all_clients(self):
        """Close all connected clients."""
        for client in self._clients.copy():
            try:
                await client.close()
            except Exception:
                pass
    
    def send_blueprint(self, blueprint: DesignBlueprint) -> bool:
        """
        Send a design blueprint to all connected Figma plugins.
        
        Args:
            blueprint: DesignBlueprint with nodes to create
            
        Returns:
            True if sent to at least one client
        """
        if not self._clients:
            logger.warning("No Figma plugins connected to send blueprint")
            return False
        
        message = {
            "type": "create_design",
            "blueprint": {
                "nodes": blueprint.nodes,
                "canvas_size": blueprint.canvas_size,
                "metadata": blueprint.metadata
            },
            "timestamp": datetime.now().isoformat()
        }
        
        message_str = json.dumps(message)
        
        # Send to all connected clients
        sent_count = 0
        for client in self._clients.copy():
            try:
                asyncio.run_coroutine_threadsafe(
                    client.send(message_str), self._loop
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send to client: {e}")
        
        logger.info(f"Sent design blueprint to {sent_count} Figma plugin(s)")
        return sent_count > 0
    
    def send_blueprint_async(self, blueprint: DesignBlueprint) -> asyncio.Future:
        """
        Send a design blueprint and await confirmation from Figma.
        
        Returns:
            Future that resolves when Figma acknowledges the blueprint
        """
        if not self._clients:
            future = asyncio.Future()
            future.set_exception(RuntimeError("No Figma plugins connected"))
            return future
        
        self._command_id_counter += 1
        command_id = f"cmd_{self._command_id_counter}_{int(time.time())}"
        
        message = {
            "type": "create_design",
            "command_id": command_id,
            "blueprint": {
                "nodes": blueprint.nodes,
                "canvas_size": blueprint.canvas_size,
                "metadata": blueprint.metadata
            },
            "timestamp": datetime.now().isoformat()
        }
        
        future = asyncio.Future()
        self._pending_commands[command_id] = future
        
        message_str = json.dumps(message)
        for client in self._clients.copy():
            try:
                asyncio.run_coroutine_threadsafe(
                    client.send(message_str), self._loop
                )
            except Exception as e:
                logger.error(f"Failed to send blueprint: {e}")
        
        # Timeout after 30 seconds
        async def timeout_handler():
            await asyncio.sleep(30)
            if command_id in self._pending_commands:
                fut = self._pending_commands.pop(command_id)
                if not fut.done():
                    fut.set_exception(TimeoutError("Figma plugin did not respond in time"))
        
        asyncio.run_coroutine_threadsafe(timeout_handler(), self._loop)
        
        return future
    
    def get_connected_count(self) -> int:
        """Get number of connected Figma plugins."""
        return len(self._clients)


# ── Figma Agent (High-Level Interface) ────────────────────────
class FigmaAgent:
    """
    High-level interface for JARVIS to interact with Figma.
    Wraps the WebSocket server and provides design-specific methods.
    """
    
    def __init__(self):
        self.server = FigmaWebSocketServer()
        self._setup_callbacks()
    
    def _setup_callbacks(self):
        """Set up event callbacks."""
        self.server.on_selection_change = self._on_selection_change
        self.server.on_client_connected = self._on_client_connected
        self.server.on_client_disconnected = self._on_client_disconnected
        
        # Store latest selection for context
        self._latest_selection: Optional[SelectionEvent] = None
    
    def start(self):
        """Start the Figma agent."""
        self.server.start()
    
    def stop(self):
        """Stop the Figma agent."""
        self.server.stop()
    
    def _on_selection_change(self, event: SelectionEvent):
        """Handle selection change from Figma."""
        self._latest_selection = event
        logger.info(f"Figma selection changed: {len(event.selected_nodes)} nodes selected")
    
    def _on_client_connected(self):
        """Handle Figma plugin connection."""
        logger.info("Figma plugin connected - ready for design commands")
    
    def _on_client_disconnected(self):
        """Handle Figma plugin disconnection."""
        logger.warning("Figma plugin disconnected")
    
    def get_latest_selection(self) -> Optional[SelectionEvent]:
        """Get the most recent selection event from Figma."""
        return self._latest_selection
    
    def is_connected(self) -> bool:
        """Check if any Figma plugin is connected."""
        return self.server.get_connected_count() > 0
    
    # ── Design Creation Methods ────────────────────────────────
    
    def create_rectangle(
        self,
        x: float, y: float,
        width: float, height: float,
        fill: str = "#FF0000",
        name: str = "Rectangle",
        corner_radius: float = 0
    ) -> DesignBlueprint:
        """Create a rectangle design blueprint."""
        node = {
            "type": "RECTANGLE",
            "name": name,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "fills": [{"type": "SOLID", "color": fill}],
            "cornerRadius": corner_radius
        }
        return DesignBlueprint(nodes=[node], canvas_size={"width": 1920, "height": 1080})
    
    def create_text(
        self,
        x: float, y: float,
        text: str,
        font_size: float = 24,
        fill: str = "#000000",
        font_family: str = "Inter",
        name: str = "Text"
    ) -> DesignBlueprint:
        """Create a text node design blueprint."""
        node = {
            "type": "TEXT",
            "name": name,
            "x": x,
            "y": y,
            "characters": text,
            "fontSize": font_size,
            "fontFamily": font_family,
            "fills": [{"type": "SOLID", "color": fill}]
        }
        return DesignBlueprint(nodes=[node], canvas_size={"width": 1920, "height": 1080})
    
    def create_frame(
        self,
        x: float, y: float,
        width: float, height: float,
        fill: str = "#FFFFFF",
        name: str = "Frame"
    ) -> DesignBlueprint:
        """Create a frame (container) design blueprint."""
        node = {
            "type": "FRAME",
            "name": name,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "fills": [{"type": "SOLID", "color": fill}],
            "layoutMode": "NONE"
        }
        return DesignBlueprint(nodes=[node], canvas_size={"width": 1920, "height": 1080})
    
    def create_button(
        self,
        x: float, y: float,
        width: float, height: float,
        label: str,
        fill: str = "#007AFF",
        text_color: str = "#FFFFFF",
        font_size: float = 16,
        corner_radius: float = 8,
        name: str = "Button"
    ) -> DesignBlueprint:
        """Create a button (frame + text) design blueprint."""
        frame = {
            "type": "FRAME",
            "name": f"{name} Container",
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "fills": [{"type": "SOLID", "color": fill}],
            "cornerRadius": corner_radius,
            "layoutMode": "HORIZONTAL",
            "primaryAxisAlignItems": "CENTER",
            "counterAxisAlignItems": "CENTER",
            "paddingLeft": 16,
            "paddingRight": 16,
            "paddingTop": 8,
            "paddingBottom": 8
        }
        
        text = {
            "type": "TEXT",
            "name": f"{name} Label",
            "characters": label,
            "fontSize": font_size,
            "fontFamily": "Inter",
            "fills": [{"type": "SOLID", "color": text_color}],
            "textAlignHorizontal": "CENTER"
        }
        
        return DesignBlueprint(nodes=[frame, text], canvas_size={"width": 1920, "height": 1080})
    
    def send_blueprint(self, blueprint: DesignBlueprint) -> bool:
        """Send a design blueprint to Figma."""
        return self.server.send_blueprint(blueprint)
    
    def send_blueprint_async(self, blueprint: DesignBlueprint):
        """Send a design blueprint and return a future for the response."""
        return self.server.send_blueprint_async(blueprint)
    
    # ── Convenience Methods for Common UI Patterns ─────────────
    
    def create_login_form(
        self,
        x: float = 660, y: float = 340,
        width: float = 600, height: float = 400
    ) -> DesignBlueprint:
        """Create a login form layout."""
        nodes = [
            {
                "type": "FRAME",
                "name": "Login Form",
                "x": x, "y": y,
                "width": width, "height": height,
                "fills": [{"type": "SOLID", "color": "#FFFFFF"}],
                "cornerRadius": 16,
                "layoutMode": "VERTICAL",
                "primaryAxisAlignItems": "CENTER",
                "counterAxisAlignItems": "CENTER",
                "paddingTop": 40, "paddingBottom": 40,
                "paddingLeft": 40, "paddingRight": 40,
                "itemSpacing": 20
            },
            {
                "type": "TEXT",
                "name": "Login Title",
                "characters": "Welcome Back",
                "fontSize": 28,
                "fontWeight": 600,
                "fontFamily": "Inter",
                "fills": [{"type": "SOLID", "color": "#1A1A2E"}]
            },
            {
                "type": "FRAME",
                "name": "Email Field",
                "width": 400, "height": 48,
                "fills": [{"type": "SOLID", "color": "#F5F5F5"}],
                "cornerRadius": 8,
                "layoutMode": "HORIZONTAL",
                "paddingLeft": 16, "paddingRight": 16,
                "counterAxisAlignItems": "CENTER"
            },
            {
                "type": "TEXT",
                "name": "Email Placeholder",
                "characters": "Enter your email",
                "fontSize": 16,
                "fontFamily": "Inter",
                "fills": [{"type": "SOLID", "color": "#999999"}]
            },
            {
                "type": "FRAME",
                "name": "Password Field",
                "width": 400, "height": 48,
                "fills": [{"type": "SOLID", "color": "#F5F5F5"}],
                "cornerRadius": 8,
                "layoutMode": "HORIZONTAL",
                "paddingLeft": 16, "paddingRight": 16,
                "counterAxisAlignItems": "CENTER"
            },
            {
                "type": "TEXT",
                "name": "Password Placeholder",
                "characters": "Enter your password",
                "fontSize": 16,
                "fontFamily": "Inter",
                "fills": [{"type": "SOLID", "color": "#999999"}]
            },
            {
                "type": "FRAME",
                "name": "Login Button",
                "width": 400, "height": 48,
                "fills": [{"type": "SOLID", "color": "#007AFF"}],
                "cornerRadius": 8,
                "layoutMode": "HORIZONTAL",
                "primaryAxisAlignItems": "CENTER",
                "counterAxisAlignItems": "CENTER"
            },
            {
                "type": "TEXT",
                "name": "Login Button Label",
                "characters": "Sign In",
                "fontSize": 16,
                "fontWeight": 600,
                "fontFamily": "Inter",
                "fills": [{"type": "SOLID", "color": "#FFFFFF"}]
            }
        ]
        
        return DesignBlueprint(
            nodes=nodes,
            canvas_size={"width": 1920, "height": 1080},
            metadata={"type": "login_form", "created": datetime.now().isoformat()}
        )
    
    def create_dashboard_card(
        self,
        x: float, y: float,
        title: str,
        value: str,
        subtitle: str = "",
        icon: str = "📊",
        fill: str = "#FFFFFF"
    ) -> DesignBlueprint:
        """Create a dashboard metric card."""
        nodes = [
            {
                "type": "FRAME",
                "name": f"Card: {title}",
                "x": x, "y": y,
                "width": 280, "height": 140,
                "fills": [{"type": "SOLID", "color": fill}],
                "cornerRadius": 12,
                "layoutMode": "VERTICAL",
                "paddingTop": 20, "paddingBottom": 20,
                "paddingLeft": 24, "paddingRight": 24,
                "itemSpacing": 8
            },
            {
                "type": "TEXT",
                "name": "Card Icon",
                "characters": icon,
                "fontSize": 24
            },
            {
                "type": "TEXT",
                "name": "Card Title",
                "characters": title,
                "fontSize": 14,
                "fontWeight": 500,
                "fills": [{"type": "SOLID", "color": "#666666"}]
            },
            {
                "type": "TEXT",
                "name": "Card Value",
                "characters": value,
                "fontSize": 32,
                "fontWeight": 700,
                "fills": [{"type": "SOLID", "color": "#1A1A2E"}]
            }
        ]
        
        if subtitle:
            nodes.append({
                "type": "TEXT",
                "name": "Card Subtitle",
                "characters": subtitle,
                "fontSize": 12,
                "fills": [{"type": "SOLID", "color": "#999999"}]
            })
        
        return DesignBlueprint(nodes=nodes, canvas_size={"width": 1920, "height": 1080})


# ── Global Instance ────────────────────────────────────────────
_figma_agent = None

def get_figma_agent() -> FigmaAgent:
    """Get or create the global Figma agent."""
    global _figma_agent
    if _figma_agent is None:
        _figma_agent = FigmaAgent()
    return _figma_agent


# ── Time Import (needed for command IDs) ───────────────────────
import time


# ── Demo / Test ────────────────────────────────────────────────
if __name__ == "__main__":
    agent = get_figma_agent()
    
    print("Starting Figma Agent...")
    print("Waiting for Figma plugin to connect...")
    print(f"WebSocket server: ws://{FIGMA_WS_HOST}:{FIGMA_WS_PORT}")
    print("\nAvailable commands:")
    print("  - Press Enter to send test button")
    print("  - Type 'form' to send login form")
    print("  - Type 'dashboard' to send dashboard card")
    print("  - Type 'quit' to exit")
    
    agent.start()
    
    try:
        while True:
            cmd = input("\nCommand > ").strip().lower()
            
            if cmd == "quit":
                break
            elif cmd == "":
                # Send test button
                blueprint = agent.create_button(
                    x=500, y=300, width=200, height=50,
                    label="Test Button", fill="#007AFF"
                )
                agent.send_blueprint(blueprint)
                print("Sent test button blueprint")
            elif cmd == "form":
                blueprint = agent.create_login_form()
                agent.send_blueprint(blueprint)
                print("Sent login form blueprint")
            elif cmd == "dashboard":
                blueprint = agent.create_dashboard_card(
                    x=100, y=100,
                    title="Total Users", value="12,345",
                    subtitle="+12% from last month"
                )
                agent.send_blueprint(blueprint)
                print("Sent dashboard card blueprint")
            else:
                print("Unknown command")
    
    except KeyboardInterrupt:
        pass
    finally:
        agent.stop()
        print("\nFigma Agent stopped.")