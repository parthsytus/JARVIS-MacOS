"""
Test suite for figma_agent.py - Figma Bridge
Tests the WebSocket server, command handling, and design blueprints.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock

# Test imports
from integrations.figma_agent import (
    FigmaAgent,
    FigmaWebSocketServer,
    DesignBlueprint,
    FigmaNode,
    SelectionEvent,
    get_figma_agent,
    FIGMA_WS_HOST,
    FIGMA_WS_PORT,
    HEARTBEAT_INTERVAL,
)


class TestFigmaAgent:
    """Test cases for figma_agent module."""

    def test_figma_exports(self):
        """Test Figma exports are available."""
        assert FigmaAgent is not None
        assert FigmaWebSocketServer is not None
        assert DesignBlueprint is not None
        assert FigmaNode is not None
        assert SelectionEvent is not None
        assert get_figma_agent is not None
        print("✓ Figma exports available")

    def test_canva_exports(self):
        """Test Canva exports are available."""
        from integrations.canva_agent import (
            CanvaAgent,
            CanvaDesignType,
            CanvaElementType,
            CanvaFontWeight,
            CanvaTextAlign,
            CanvaColor,
            CanvaPosition,
            CanvaTextStyle,
            CanvaFill,
            CanvaStroke,
            CanvaElement,
            CanvaPage,
            CanvaDesign,
            DesignBuilder,
            PresentationBuilder,
            SocialPostBuilder,
            InfographicBuilder,
            TokenManager,
            CanvaAPIClient
        )
        assert CanvaAgent is not None
        assert CanvaDesignType is not None
        print("✓ Canva exports available")

    def test_figma_agent_creation(self):
        """Test FigmaAgent can be instantiated."""
        with patch('integrations.figma_agent.FigmaWebSocketServer'):
            agent = FigmaAgent()
            assert agent is not None
            assert hasattr(agent, 'server')
            assert hasattr(agent, '_latest_selection')
        print("✓ FigmaAgent instantiation works")

    def test_canva_agent_creation(self):
        """Test CanvaAgent can be instantiated."""
        with patch('integrations.canva_agent.CanvaAPIClient'):
            agent = CanvaAgent()
            assert agent is not None
            assert hasattr(agent, 'token_manager')
        print("✓ CanvaAgent instantiation works")

    def test_design_blueprint_creation(self):
        """Test DesignBlueprint creation."""
        blueprint = DesignBlueprint(
            nodes=[{"type": "RECTANGLE", "x": 100, "y": 100, "width": 200, "height": 100}],
            canvas_size={"width": 1920, "height": 1080}
        )
        
        assert len(blueprint.nodes) == 1
        assert blueprint.nodes[0]["type"] == "RECTANGLE"
        assert blueprint.canvas_size["width"] == 1920
        print("✓ DesignBlueprint creation works")

    def test_figma_node_creation(self):
        """Test FigmaNode dataclass creation."""
        node = FigmaNode(
            id="123:456",
            type="RECTANGLE",
            name="Test Rect",
            x=10, y=20,
            width=100, height=50
        )
        
        assert node.id == "123:456"
        assert node.type == "RECTANGLE"
        assert node.width == 100
        print("✓ FigmaNode creation works")

    def test_selection_event_creation(self):
        """Test SelectionEvent dataclass creation."""
        from integrations.figma_agent import SelectionEvent
        
        node = FigmaNode(id="1", type="RECTANGLE", name="Rect", x=0, y=0, width=100, height=100)
        event = SelectionEvent(
            selected_nodes=[node],
            timestamp="2024-01-01T00:00:00"
        )
        
        assert len(event.selected_nodes) == 1
        assert event.selected_nodes[0].id == "1"
        print("✓ SelectionEvent creation works")

    def test_config_constants(self):
        """Test configuration constants."""
        assert FIGMA_WS_HOST == "localhost"
        assert FIGMA_WS_PORT == 8765
        assert HEARTBEAT_INTERVAL == 30
        print("✓ Config constants are correct")

    def test_figma_websocket_server_init(self):
        """Test FigmaWebSocketServer initialization."""
        # No patch needed - websockets is imported inside _start_server method
        server = FigmaWebSocketServer(host="localhost", port=8765)
        
        assert server.host == "localhost"
        assert server.port == 8765
        assert server._running is False
        assert len(server._clients) == 0
        assert server._command_id_counter == 0
        print("✓ FigmaWebSocketServer init works")

    def test_figma_websocket_server_start(self):
        """Test server start."""
        with patch('integrations.figma_agent.FigmaWebSocketServer._start_server') as mock_start_server:
            with patch('integrations.figma_agent.threading.Thread'):
                server = FigmaWebSocketServer()
                
                mock_start_server.return_value = None
                
                server.start()
                
                assert server._running is True
        print("✓ FigmaWebSocketServer start works")

    def test_figma_agent_init(self):
        """Test FigmaAgent initialization."""
        with patch('integrations.figma_agent.FigmaWebSocketServer') as mock_server_class:
            mock_server = Mock()
            mock_server_class.return_value = mock_server
            
            agent = FigmaAgent()
            
            assert agent.server == mock_server
            assert agent._latest_selection is None
        print("✓ FigmaAgent init works")

    def test_figma_agent_callbacks(self):
        """Test FigmaAgent callback setup."""
        with patch('integrations.figma_agent.FigmaWebSocketServer') as mock_server_class:
            mock_server = Mock()
            mock_server_class.return_value = mock_server
            
            agent = FigmaAgent()
            
            # Verify callbacks are set
            assert mock_server.on_selection_change == agent._on_selection_change
            assert mock_server.on_client_connected == agent._on_client_connected
            assert mock_server.on_client_disconnected == agent._on_client_disconnected
        print("✓ FigmaAgent callbacks set correctly")

    def test_create_rectangle_blueprint(self):
        """Test rectangle creation blueprint."""
        with patch('integrations.figma_agent.FigmaWebSocketServer'):
            agent = FigmaAgent()
            
            blueprint = agent.create_rectangle(
                x=100, y=100,
                width=200, height=150,
                fill="#FF0000",
                corner_radius=8,
                name="Test Rect"
            )
            
            assert isinstance(blueprint, DesignBlueprint)
            assert len(blueprint.nodes) == 1
            node = blueprint.nodes[0]
            assert node["type"] == "RECTANGLE"
            assert node["x"] == 100
            assert node["y"] == 100
            assert node["width"] == 200
            assert node["height"] == 150
            assert node["cornerRadius"] == 8
        print("✓ create_rectangle blueprint works")

    def test_create_text_blueprint(self):
        """Test text creation blueprint."""
        with patch('integrations.figma_agent.FigmaWebSocketServer'):
            agent = FigmaAgent()
            
            blueprint = agent.create_text(
                x=100, y=200,
                text="Hello JARVIS",
                font_size=24,
                fill="#000000",
                font_family="Inter"
            )
            
            assert len(blueprint.nodes) == 1
            node = blueprint.nodes[0]
            assert node["type"] == "TEXT"
            assert node["characters"] == "Hello JARVIS"
            assert node["fontSize"] == 24
        print("✓ create_text blueprint works")

    def test_create_frame_blueprint(self):
        """Test frame creation blueprint."""
        with patch('integrations.figma_agent.FigmaWebSocketServer'):
            agent = FigmaAgent()
            
            blueprint = agent.create_frame(
                x=0, y=0,
                width=400, height=300,
                fill="#FFFFFF",
                name="Container"
            )
            
            assert len(blueprint.nodes) == 1
            node = blueprint.nodes[0]
            assert node["type"] == "FRAME"
        print("✓ create_frame blueprint works")

    def test_create_button_blueprint(self):
        """Test button creation blueprint."""
        with patch('integrations.figma_agent.FigmaWebSocketServer'):
            agent = FigmaAgent()
            
            blueprint = agent.create_button(
                x=100, y=100,
                width=160, height=48,
                label="Click Me",
                fill="#007AFF",
                text_color="#FFFFFF",
                font_size=16,
                corner_radius=8
            )
            
            # Should create a frame + text (2 nodes)
            assert len(blueprint.nodes) == 2
            frame = blueprint.nodes[0]
            text = blueprint.nodes[1]
            assert frame["type"] == "FRAME"
            assert frame["cornerRadius"] == 8
            assert text["type"] == "TEXT"
            assert text["characters"] == "Click Me"
        print("✓ create_button blueprint works")

    def test_send_blueprint(self):
        """Test sending blueprint to server."""
        with patch('integrations.figma_agent.FigmaWebSocketServer') as mock_server_class:
            mock_server = Mock()
            mock_server_class.return_value = mock_server
            mock_server.send_blueprint.return_value = True
            
            agent = FigmaAgent()
            blueprint = Mock()
            blueprint.nodes = []
            
            result = agent.send_blueprint(blueprint)
            
            assert result is True
            mock_server.send_blueprint.assert_called_once_with(blueprint)
        print("✓ send_blueprint works")

    def test_create_presentation_builder(self):
        """Test presentation builder creation."""
        with patch('integrations.figma_agent.FigmaWebSocketServer'):
            agent = FigmaAgent()
            
            builder = agent.create_presentation("Test Presentation", theme="dark")
            
            assert builder.design.design_type == "PRESENTATION"
            assert builder.theme == "dark"
        print("✓ create_presentation builder works")

    def test_presentation_builder_slides(self):
        """Test presentation builder slide methods."""
        with patch('integrations.figma_agent.FigmaWebSocketServer'):
            agent = FigmaAgent()
            builder = agent.create_presentation("Test", theme="dark")
            
            builder.title_slide("Main Title", "Subtitle")
            
            # Should have title and subtitle
            assert len(builder.current_page.elements) == 2
            assert builder.current_page.elements[0].text == "Main Title"
            assert builder.current_page.elements[1].text == "Subtitle"
            print("✓ title_slide works")
            
            builder.content_slide("Content Title", ["Bullet 1", "Bullet 2"])
            
            # Should have title + 2 bullets = 3 elements
            assert len(builder.current_page.elements) == 3
            print("✓ content_slide works")

    def test_social_post_builder(self):
        """Test social post builder."""
        with patch('integrations.figma_agent.FigmaWebSocketServer'):
            agent = FigmaAgent()
            
            builder = agent.create_social_post("Insta Post", "instagram")
            
            assert builder.design.design_type == "SOCIAL_MEDIA"
            assert builder.platform == "instagram"
            assert builder.design.pages[0].width == 1080
            assert builder.design.pages[0].height == 1080
        print("✓ SocialPostBuilder works")

    def test_infographic_builder(self):
        """Test infographic builder."""
        with patch('integrations.figma_agent.FigmaWebSocketServer'):
            agent = FigmaAgent()
            
            builder = agent.create_infographic("Stats", 800, 2000)
            
            assert builder.design.design_type == "INFORMATIONAL" or builder.design.design_type == "INFOGRAPHIC"
            assert builder.design.pages[0].width == 800
            assert builder.design.pages[0].height == 2000
        print("✓ InfographicBuilder creation works")

    def test_infographic_stat_card(self):
        """Test infographic stat card."""
        with patch('integrations.figma_agent.FigmaWebSocketServer'):
            agent = FigmaAgent()
            builder = agent.create_infographic("Stats", 800, 2000)
            
            builder.header("Title", "Subtitle")
            builder.stat_card("99.99%", "Uptime", 100, 250, accent_color="#00D4AA")
            
            # Should have header elements + stat card elements
            assert len(builder.current_page.elements) >= 5
        print("✓ infographic stat_card works")

    def test_get_figma_agent_singleton(self):
        """Test global singleton getter."""
        # Reset global
        import integrations.figma_agent as figma_module
        figma_module._figma_agent = None
        
        a1 = get_figma_agent()
        a2 = get_figma_agent()
        
        assert a1 is a2
        print("✓ get_figma_agent returns singleton")


def run_tests():
    """Run all tests."""
    test = TestFigmaAgent()
    
    test.test_figma_exports()
    test.test_config_constants()
    test.test_figma_websocket_server_init()
    test.test_figma_websocket_server_start()
    test.test_figma_agent_init()
    test.test_figma_agent_callbacks()
    test.test_create_rectangle_blueprint()
    test.test_create_text_blueprint()
    test.test_create_frame_blueprint()
    test.test_create_button_blueprint()
    test.test_send_blueprint()
    test.test_get_figma_agent_singleton()
    
    print("\n✅ All figma_agent tests passed!")


if __name__ == "__main__":
    run_tests()