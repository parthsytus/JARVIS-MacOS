"""
Test suite for integrations package.
Tests the integration modules work together.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from unittest.mock import Mock, patch, AsyncMock

# Test imports
from integrations import (
    FigmaAgent,
    FigmaWebSocketServer,
    DesignBlueprint,
    FigmaNode,
    SelectionEvent,
    get_figma_agent,
    draw_hologram_target,
    clear_hologram_targets,
    shutdown_hologram,
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
    CanvaAPIClient,
    CANVA_API_BASE,
    CANVA_AUTH_URL,
    MAX_REQUESTS_PER_SECOND,
    REQUEST_TIMEOUT,
)


class TestIntegrations:
    """Test cases for integrations package."""

    def test_figma_exports(self):
        """Test Figma exports are available."""
        assert FigmaAgent is not None
        assert FigmaWebSocketServer is not None
        assert DesignBlueprint is not None
        assert FigmaNode is not None
        assert SelectionEvent is not None
        assert get_figma_agent is not None
        assert draw_hologram_target is not None
        assert clear_hologram_targets is not None
        assert shutdown_hologram is not None
        print("✓ Figma exports available")

    def test_canva_exports(self):
        """Test Canva exports are available."""
        assert CanvaAgent is not None
        assert CanvaDesignType is not None
        assert CanvaElementType is not None
        assert CanvaFontWeight is not None
        assert CanvaTextAlign is not None
        assert CanvaColor is not None
        assert CanvaPosition is not None
        assert CanvaTextStyle is not None
        assert CanvaFill is not None
        assert CanvaStroke is not None
        assert CanvaElement is not None
        assert CanvaPage is not None
        assert CanvaDesign is not None
        assert DesignBuilder is not None
        assert PresentationBuilder is not None
        assert SocialPostBuilder is not None
        assert InfographicBuilder is not None
        assert TokenManager is not None
        assert CanvaAPIClient is not None
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
        """Test FigmaNode dataclass."""
        node = FigmaNode(
            id="123",
            type="RECTANGLE",
            name="Test Rect",
            x=10, y=20,
            width=100, height=50
        )
        
        assert node.id == "123"
        assert node.type == "RECTANGLE"
        assert node.width == 100
        print("✓ FigmaNode creation works")

    def test_selection_event_creation(self):
        """Test SelectionEvent dataclass."""
        from integrations.figma_agent import SelectionEvent
        
        event = SelectionEvent(
            selected_nodes=[FigmaNode(id="1", type="RECTANGLE", name="Rect", x=0, y=0, width=100, height=100)],
            timestamp="2024-01-01T00:00:00"
        )
        
        assert len(event.selected_nodes) == 1
        assert event.selected_nodes[0].id == "1"
        print("✓ SelectionEvent creation works")

    def test_canva_color_operations(self):
        """Test CanvaColor operations."""
        # From hex
        c1 = CanvaColor.from_hex("#FF0000")
        assert c1.r == 255
        
        # From RGB
        c2 = CanvaColor.from_rgb(0, 255, 0, 0.5)
        assert c2.g == 255
        assert c2.a == 0.5
        
        # To hex
        assert c1.to_hex() == "#ff0000"
        
        # To Canva dict
        canva_dict = c1.to_canva_dict()
        assert canva_dict["r"] == 1.0
        assert canva_dict["g"] == 0.0
        assert canva_dict["b"] == 0.0
        print("✓ CanvaColor operations work")

    def test_canva_design_type_enum(self):
        """Test CanvaDesignType enum values."""
        assert CanvaDesignType.PRESENTATION == "presentation"
        assert CanvaDesignType.SOCIAL_MEDIA == "social_media"
        assert CanvaDesignType.INFOGRAPHIC == "infographic"
        assert CanvaDesignType.CUSTOM == "custom"
        print("✓ CanvaDesignType enum works")

    def test_canva_element_type_enum(self):
        """Test CanvaElementType enum values."""
        assert CanvaElementType.TEXT == "text"
        assert CanvaElementType.IMAGE == "image"
        assert CanvaElementType.SHAPE == "shape"
        assert CanvaElementType.FRAME == "frame"
        assert CanvaElementType.GROUP == "group"
        print("✓ CanvaElementType enum works")

    def test_canva_font_weight_enum(self):
        """Test CanvaFontWeight enum values."""
        assert CanvaFontWeight.REGULAR == "400"
        assert CanvaFontWeight.BOLD == "700"
        assert CanvaFontWeight.BLACK == "900"
        print("✓ CanvaFontWeight enum works")

    def test_canva_text_align_enum(self):
        """Test CanvaTextAlign enum values."""
        assert CanvaTextAlign.LEFT == "left"
        assert CanvaTextAlign.CENTER == "center"
        assert CanvaTextAlign.RIGHT == "right"
        assert CanvaTextAlign.JUSTIFY == "justify"
        print("✓ CanvaTextAlign enum works")

    def test_canva_text_style(self):
        """Test CanvaTextStyle dataclass."""
        style = CanvaTextStyle(
            font_family="Inter",
            font_size=24,
            font_weight=CanvaFontWeight.BOLD,
            color=CanvaColor.from_hex("#000000"),
            line_height=1.2,
            letter_spacing=0,
            text_align=CanvaTextAlign.CENTER,
            text_transform="uppercase",
            text_decoration="underline"
        )
        
        assert style.font_family == "Inter"
        assert style.font_size == 24
        assert style.font_weight == CanvaFontWeight.BOLD
        assert style.text_align == CanvaTextAlign.CENTER
        assert style.text_transform == "uppercase"
        assert style.text_decoration == "underline"
        print("✓ CanvaTextStyle works")

    def test_canva_fill(self):
        """Test CanvaFill dataclass."""
        fill = CanvaFill(
            type="solid",
            color=CanvaColor.from_hex("#FF0000"),
            opacity=0.8
        )
        
        assert fill.type == "solid"
        assert fill.color.r == 255
        assert fill.opacity == 0.8
        print("✓ CanvaFill works")

    def test_canva_stroke(self):
        """Test CanvaStroke dataclass."""
        stroke = CanvaStroke(
            color=CanvaColor.from_hex("#000000"),
            weight=2,
            style="dashed",
            dash_pattern=[10, 5]
        )
        
        assert stroke.weight == 2
        assert stroke.style == "dashed"
        assert stroke.dash_pattern == [10, 5]
        print("✓ CanvaStroke works")

    def test_canva_element_serialization(self):
        """Test CanvaElement to_canva_dict."""
        element = CanvaElement(
            id="test1",
            type=CanvaElementType.TEXT,
            position=CanvaPosition(10, 20, 100, 50),
            name="Test Text",
            text="Hello World",
            text_style=CanvaTextStyle(
                font_family="Arial",
                font_size=16,
                font_weight=CanvaFontWeight.REGULAR,
                color=CanvaColor.from_hex("#000000")
            )
        )
        
        d = element.to_canva_dict()
        
        assert d["id"] == "test1"
        assert d["type"] == "text"
        assert d["text"] == "Hello World"
        assert d["textStyle"]["fontFamily"] == "Arial"
        assert d["textStyle"]["fontSize"] == 16
        assert d["textStyle"]["fontWeight"] == "400"
        print("✓ CanvaElement serialization works")

    def test_canva_page_serialization(self):
        """Test CanvaPage to_canva_dict."""
        page = CanvaPage(
            name="Test Page",
            elements=[],
            background=CanvaFill(
                type="solid",
                color=CanvaColor.from_hex("#FFFFFF")
            ),
            width=1920,
            height=1080
        )
        
        d = page.to_canva_dict()
        
        assert d["name"] == "Test Page"
        assert d["width"] == 1920
        assert d["height"] == 1080
        assert d["background"]["color"]["r"] == 1.0
        print("✓ CanvaPage serialization works")

    def test_canva_design_serialization(self):
        """Test CanvaDesign to_canva_dict."""
        design = CanvaDesign(
            title="Test Design",
            design_type=CanvaDesignType.PRESENTATION,
            pages=[CanvaPage()],
            tags=["test", "presentation"]
        )
        
        d = design.to_canva_dict()
        
        assert d["title"] == "Test Design"
        assert d["type"] == "presentation"
        assert d["tags"] == ["test", "presentation"]
        print("✓ CanvaDesign serialization works")

    def test_canva_agent_builders(self):
        """Test CanvaAgent builder creation."""
        with patch('integrations.canva_agent.CanvaAPIClient'):
            agent = CanvaAgent()
            
            # Test all builder types
            pres = agent.create_presentation("Test Pres")
            assert isinstance(pres, PresentationBuilder)
            
            social = agent.create_social_post("Insta", "instagram")
            assert isinstance(social, SocialPostBuilder)
            
            info = agent.create_infographic("Stats")
            assert isinstance(info, InfographicBuilder)
            
            custom = agent.create_custom_design("Custom")
            assert isinstance(custom, DesignBuilder)
            
        print("✓ CanvaAgent builder creation works")

    def test_figma_singleton(self):
        """Test Figma agent singleton behavior."""
        import integrations.figma_agent as figma_module
        
        # Reset
        figma_module._figma_agent = None
        
        a1 = get_figma_agent()
        a2 = get_figma_agent()
        
        assert a1 is a2
        print("✓ Figma agent singleton works")

    def test_config_constants(self):
        """Test configuration constants."""
        assert CANVA_API_BASE == "https://api.canva.com/rest/v1/"
        assert CANVA_AUTH_URL == "https://api.canva.com/rest/v1/oauth2/token"
        assert MAX_REQUESTS_PER_SECOND == 10
        assert REQUEST_TIMEOUT == 30.0
        print("✓ Config constants correct")


def run_tests():
    """Run all tests."""
    test = TestIntegrations()
    
    test.test_figma_exports()
    test.test_canva_exports()
    test.test_figma_agent_creation()
    test.test_canva_agent_creation()
    test.test_design_blueprint_creation()
    test.test_figma_node_creation()
    test.test_selection_event_creation()
    test.test_canva_color_operations()
    test.test_canva_design_type_enum()
    test.test_canva_element_type_enum()
    test.test_canva_font_weight_enum()
    test.test_canva_text_align_enum()
    test.test_canva_text_style()
    test.test_canva_fill()
    test.test_canva_stroke()
    test.test_canva_element_serialization()
    test.test_canva_page_serialization()
    test.test_canva_design_serialization()
    test.test_canva_agent_builders()
    test.test_figma_singleton()
    test.test_config_constants()
    
    print("\n✅ All integrations tests passed!")


if __name__ == "__main__":
    run_tests()