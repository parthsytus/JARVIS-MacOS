"""
Test suite for canva_agent.py - Canva API Agent
Tests the Canva API client, token management, and design builders.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import time
from unittest.mock import Mock, patch, AsyncMock, MagicMock

# Test imports
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
    CanvaAPIClient,
    CANVA_API_BASE,
    CANVA_AUTH_URL,
    MAX_REQUESTS_PER_SECOND,
    REQUEST_TIMEOUT,
)


class TestCanvaAgent:
    """Test cases for canva_agent module."""

    def test_enums(self):
        """Test enum values."""
        assert CanvaDesignType.PRESENTATION == "presentation"
        assert CanvaDesignType.SOCIAL_MEDIA == "social_media"
        assert CanvaElementType.TEXT == "text"
        assert CanvaElementType.IMAGE == "image"
        assert CanvaFontWeight.BOLD == "700"
        assert CanvaTextAlign.CENTER == "center"
        print("✓ Enum values correct")

    def test_canva_color_from_hex(self):
        """Test CanvaColor creation from hex."""
        color = CanvaColor.from_hex("#FF0000")
        assert color.r == 255
        assert color.g == 0
        assert color.b == 0
        
        # Test 3-char hex
        color2 = CanvaColor.from_hex("#F0F")
        assert color2.r == 255
        assert color2.g == 0
        assert color2.b == 255
        
        # Test to_hex
        assert color.to_hex() == "#ff0000"
        print("✓ CanvaColor from_hex/to_hex works")

    def test_canva_color_from_rgb(self):
        """Test CanvaColor creation from RGB."""
        color = CanvaColor.from_rgb(100, 150, 200, 0.5)
        assert color.r == 100
        assert color.g == 150
        assert color.b == 200
        assert color.a == 0.5
        print("✓ CanvaColor from_rgb works")

    def test_canva_color_to_canva_dict(self):
        """Test CanvaColor conversion to Canva API format."""
        color = CanvaColor(255, 128, 0, 1.0)
        canva_dict = color.to_canva_dict()
        
        assert canva_dict["r"] == 1.0
        assert canva_dict["g"] == 0.5019607843137255
        assert canva_dict["b"] == 0.0
        assert canva_dict["a"] == 1.0
        print("✓ CanvaColor to_canva_dict works")

    def test_canva_position(self):
        """Test CanvaPosition dataclass."""
        pos = CanvaPosition(100, 200, 300, 150, rotation=45)
        
        assert pos.x == 100
        assert pos.y == 200
        assert pos.width == 300
        assert pos.height == 150
        assert pos.rotation == 45
        print("✓ CanvaPosition works")

    def test_canva_text_style(self):
        """Test CanvaTextStyle dataclass."""
        style = CanvaTextStyle(
            font_family="Inter",
            font_size=24,
            font_weight=CanvaFontWeight.BOLD,
            color=CanvaColor(0, 0, 0),
            text_align=CanvaTextAlign.CENTER
        )
        
        assert style.font_family == "Inter"
        assert style.font_size == 24
        assert style.font_weight == CanvaFontWeight.BOLD
        assert style.text_align == CanvaTextAlign.CENTER
        print("✓ CanvaTextStyle works")

    def test_canva_fill(self):
        """Test CanvaFill dataclass."""
        fill = CanvaFill(
            type="solid",
            color=CanvaColor(255, 0, 0),
            opacity=0.8
        )
        
        assert fill.type == "solid"
        assert fill.color.r == 255
        assert fill.opacity == 0.8
        print("✓ CanvaFill works")

    def test_canva_stroke(self):
        """Test CanvaStroke dataclass."""
        stroke = CanvaStroke(
            color=CanvaColor(0, 0, 0),
            weight=2,
            style="dashed",
            dash_pattern=[10, 5]
        )
        
        assert stroke.color.r == 0
        assert stroke.weight == 2
        assert stroke.style == "dashed"
        assert stroke.dash_pattern == [10, 5]
        print("✓ CanvaStroke works")

    def test_canva_element_text(self):
        """Test CanvaElement for text."""
        element = CanvaElement(
            id="text1",
            type=CanvaElementType.TEXT,
            position=CanvaPosition(100, 100, 400, 50),
            name="Heading",
            text="Hello World",
            text_style=CanvaTextStyle(
                font_size=24,
                font_weight=CanvaFontWeight.BOLD,
                color=CanvaColor(0, 0, 0)
            )
        )
        
        assert element.type == CanvaElementType.TEXT
        assert element.text == "Hello World"
        assert element.text_style.font_size == 24
        
        # Test serialization
        d = element.to_canva_dict()
        assert d["type"] == "text"
        assert d["text"] == "Hello World"
        assert d["textStyle"]["fontSize"] == 24
        print("✓ CanvaElement TEXT works")

    def test_canva_element_rectangle(self):
        """Test CanvaElement for rectangle."""
        element = CanvaElement(
            type=CanvaElementType.SHAPE,
            position=CanvaPosition(0, 0, 200, 100),
            name="Rect",
            fill=CanvaFill(type="solid", color=CanvaColor(0, 122, 255)),
            corner_radius=8
        )
        
        assert element.type == CanvaElementType.SHAPE
        assert element.corner_radius == 8
        
        d = element.to_canva_dict()
        assert d["type"] == "shape"
        assert d["cornerRadius"] == 8
        assert d["fill"]["color"]["r"] == 0.0
        assert d["fill"]["color"]["b"] == 1.0
        print("✓ CanvaElement SHAPE works")

    def test_canva_element_image(self):
        """Test CanvaElement for image."""
        element = CanvaElement(
            type=CanvaElementType.IMAGE,
            position=CanvaPosition(100, 100, 300, 200),
            image_url="https://example.com/image.png",
            image_asset_id="asset_123",
            name="Photo"
        )
        
        d = element.to_canva_dict()
        assert d["type"] == "image"
        assert d["imageUrl"] == "https://example.com/image.png"
        assert d["assetId"] == "asset_123"
        print("✓ CanvaElement IMAGE works")

    def test_canva_element_frame(self):
        """Test CanvaElement for frame."""
        element = CanvaElement(
            type=CanvaElementType.FRAME,
            position=CanvaPosition(0, 0, 400, 300),
            name="Container",
            fill=CanvaFill(type="solid", color=CanvaColor(255, 255, 255))
        )
        
        d = element.to_canva_dict()
        assert d["type"] == "frame"
        print("✓ CanvaElement FRAME works")

    def test_canva_page(self):
        """Test CanvaPage dataclass."""
        page = CanvaPage(
            name="Slide 1",
            elements=[],
            background=CanvaFill(type="solid", color=CanvaColor(255, 255, 255)),
            width=1920,
            height=1080
        )
        
        assert page.name == "Slide 1"
        assert page.width == 1920
        
        d = page.to_canva_dict()
        assert d["name"] == "Slide 1"
        assert d["background"]["color"]["r"] == 1.0
        print("✓ CanvaPage works")

    def test_canva_design(self):
        """Test CanvaDesign dataclass."""
        design = CanvaDesign(
            title="Test Design",
            design_type=CanvaDesignType.PRESENTATION,
            pages=[CanvaPage()],
            tags=["test", "demo"]
        )
        
        assert design.title == "Test Design"
        assert design.design_type == CanvaDesignType.PRESENTATION
        
        d = design.to_canva_dict()
        assert d["title"] == "Test Design"
        assert d["type"] == "presentation"
        assert d["tags"] == ["test", "demo"]
        print("✓ CanvaDesign works")

    def test_token_data(self):
        """Test TokenData dataclass."""
        from integrations.canva_agent import TokenData
        
        token = TokenData(
            access_token="test_token",
            expires_in=3600,
            obtained_at=time.time()
        )
        
        assert token.access_token == "test_token"
        assert not token.is_expired
        
        # Test expired
        old_token = TokenData(
            access_token="old",
            expires_in=3600,
            obtained_at=time.time() - 4000  # 4000 seconds ago
        )
        assert old_token.is_expired
        print("✓ TokenData works")

    def test_token_manager_init(self):
        """Test TokenManager initialization."""
        tm = TokenManager(
            client_id="test_id",
            client_secret="test_secret",
            token_file=".test_token"
        )
        
        assert tm.client_id == "test_id"
        assert tm.client_secret == "test_secret"
        assert tm.token_file.name == ".test_token"
        print("✓ TokenManager init works")

    @patch('integrations.canva_agent.httpx.AsyncClient')
    async def test_token_manager_fetch_new_token(self, mock_client_class):
        """Test fetching new token via client credentials."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "new_token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "design:read design:write"
        }
        mock_response.raise_for_status = Mock()
        mock_client.post.return_value = mock_response
        
        tm = TokenManager(client_id="id", client_secret="secret")
        token = await tm.get_token()
        
        assert token == "new_token"
        mock_client.post.assert_called_once()
        print("✓ TokenManager fetch_new_token works")

    def test_canva_api_client_init(self):
        """Test CanvaAPIClient initialization."""
        tm = Mock(spec=TokenManager)
        tm.get_token = AsyncMock(return_value="test_token")
        
        client = CanvaAPIClient(tm)
        
        assert client.token_manager == tm
        assert client._rate_limiter._value == MAX_REQUESTS_PER_SECOND
        print("✓ CanvaAPIClient init works")

    @patch('integrations.canva_agent.httpx.AsyncClient')
    async def test_canva_api_client_request(self, mock_client_class):
        """Test API request with auth."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"id": "design_123"}
        mock_client.request.return_value = mock_response
        
        tm = Mock(spec=TokenManager)
        tm.get_token = AsyncMock(return_value="test_token")
        
        client = CanvaAPIClient(tm)
        client.client = mock_client
        
        response = await client._request("POST", "designs", json={"title": "Test"})
        
        assert response == mock_response
        mock_client.request.assert_called_once()
        print("✓ CanvaAPIClient _request works")

    async def test_canva_agent_context_manager(self):
        """Test CanvaAgent async context manager."""
        with patch('integrations.canva_agent.CanvaAPIClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            
            async with CanvaAgent() as agent:
                assert agent.client == mock_client
            
            mock_client.__aexit__.assert_called_once()
            print("✓ CanvaAgent context manager works")

    def test_design_builder_basics(self):
        """Test basic DesignBuilder functionality."""
        agent = Mock()
        
        builder = DesignBuilder(agent, "Test Design", 800, 600)
        
        assert builder.design.title == "Test Design"
        assert builder.design.design_type == CanvaDesignType.CUSTOM
        assert len(builder.design.pages) == 1
        assert builder.current_page.width == 800
        print("✓ DesignBuilder init works")

    def test_design_builder_add_page(self):
        """Test adding pages to design."""
        agent = Mock()
        builder = DesignBuilder(agent, "Test", 800, 600)
        
        builder.page("Page 2", 1024, 768)
        
        assert len(builder.design.pages) == 2
        assert builder.current_page.name == "Page 2"
        assert builder.current_page.width == 1024
        print("✓ DesignBuilder page works")

    def test_design_builder_background(self):
        """Test setting background."""
        agent = Mock()
        builder = DesignBuilder(agent, "Test", 800, 600)
        
        builder.background("#FF0000")
        
        assert builder.current_page.background is not None
        assert builder.current_page.background.color.r == 255
        print("✓ DesignBuilder background works")

    def test_design_builder_text(self):
        """Test adding text element."""
        agent = Mock()
        builder = DesignBuilder(agent, "Test", 800, 600)
        
        builder.text("Hello", 100, 100, 400, 50)
        
        assert len(builder.current_page.elements) == 1
        elem = builder.current_page.elements[0]
        assert elem.type == CanvaElementType.TEXT
        assert elem.text == "Hello"
        assert elem.position.x == 100
        print("✓ DesignBuilder text works")

    def test_design_builder_rectangle(self):
        """Test adding rectangle element."""
        agent = Mock()
        builder = DesignBuilder(agent, "Test", 800, 600)
        
        builder.rectangle(10, 20, 100, 50, fill="#00FF00", corner_radius=4)
        
        assert len(builder.current_page.elements) == 1
        elem = builder.current_page.elements[0]
        assert elem.type == CanvaElementType.SHAPE
        assert elem.corner_radius == 4
        assert elem.fill.color.to_hex() == "#00ff00"
        print("✓ DesignBuilder rectangle works")

    def test_design_builder_circle(self):
        """Test adding circle element."""
        agent = Mock()
        builder = DesignBuilder(agent, "Test", 800, 600)
        
        builder.circle(400, 300, 50, fill="#FF0000")
        
        elem = builder.current_page.elements[0]
        assert elem.type == CanvaElementType.SHAPE
        assert elem.position.width == 50
        assert elem.position.height == 50
        assert elem.corner_radius == 25  # diameter/2
        print("✓ DesignBuilder circle works")

    def test_design_builder_line(self):
        """Test adding line element."""
        agent = Mock()
        builder = DesignBuilder(agent, "Test", 800, 600)
        
        builder.line(0, 0, 100, 100, stroke=CanvaStroke(
            color=CanvaColor(0, 0, 0), weight=2
        ))
        
        elem = builder.current_page.elements[0]
        assert elem.type == CanvaElementType.LINE
        assert elem.position.width == 100
        assert elem.position.height == 100
        print("✓ DesignBuilder line works")

    def test_design_builder_image(self):
        """Test adding image element."""
        agent = Mock()
        builder = DesignBuilder(agent, "Test", 800, 600)
        
        builder.image(100, 100, 300, 200, image_url="https://example.com/img.png")
        
        elem = builder.current_page.elements[0]
        assert elem.type == CanvaElementType.IMAGE
        assert elem.image_url == "https://example.com/img.png"
        print("✓ DesignBuilder image works")

    def test_design_builder_frame(self):
        """Test adding frame element."""
        agent = Mock()
        builder = DesignBuilder(agent, "Test", 800, 600)
        
        builder.frame(0, 0, 400, 300, layout_mode="VERTICAL", padding=16)
        
        elem = builder.current_page.elements[0]
        assert elem.type == CanvaElementType.FRAME
        print("✓ DesignBuilder frame works")

    def test_design_builder_group(self):
        """Test grouping elements."""
        agent = Mock()
        builder = DesignBuilder(agent, "Test", 800, 600)
        
        builder.group(["elem1", "elem2"], name="My Group")
        
        elem = builder.current_page.elements[0]
        assert elem.type == CanvaElementType.GROUP
        assert json.loads(elem.text) == ["elem1", "elem2"]
        print("✓ DesignBuilder group works")

    def test_design_builder_build(self):
        """Test building final design."""
        agent = Mock()
        builder = DesignBuilder(agent, "Final", 800, 600)
        builder.text("Hello", 10, 10, 100, 20)
        
        design = builder.build()
        
        assert isinstance(design, CanvaDesign)
        assert design.title == "Final"
        assert len(design.pages) == 1
        assert len(design.pages[0].elements) == 1
        print("✓ DesignBuilder build works")

    def test_presentation_builder(self):
        """Test PresentationBuilder."""
        agent = Mock()
        builder = PresentationBuilder(agent, "Slides", 1920, 1080, theme="dark")
        
        assert builder.design.design_type == CanvaDesignType.PRESENTATION
        assert builder.theme == "dark"
        assert builder.default_text_color.r == 255  # white text for dark theme
        print("✓ PresentationBuilder init works")

    def test_presentation_builder_title_slide(self):
        """Test title slide creation."""
        agent = Mock()
        builder = PresentationBuilder(agent, "Test", 1920, 1080, theme="light")
        
        builder.title_slide("Main Title", "Subtitle here")
        
        # Title + subtitle = 2 elements
        assert len(builder.current_page.elements) == 2
        assert builder.current_page.elements[0].text == "Main Title"
        assert builder.current_page.elements[1].text == "Subtitle here"
        print("✓ PresentationBuilder title_slide works")

    def test_presentation_builder_content_slide(self):
        """Test content slide with bullets."""
        agent = Mock()
        builder = PresentationBuilder(agent, "Test", 1920, 1080, theme="light")
        
        builder.content_slide("Content Title", ["Bullet 1", "Bullet 2", "Bullet 3"])
        
        # Title + 3 bullets = 4 elements
        assert len(builder.current_page.elements) == 4
        assert builder.current_page.elements[0].text == "Content Title"
        assert "Bullet 1" in builder.current_page.elements[1].text
        assert "Bullet 2" in builder.current_page.elements[2].text
        assert "Bullet 3" in builder.current_page.elements[3].text
        print("✓ PresentationBuilder content_slide works")

    def test_social_post_builder(self):
        """Test SocialPostBuilder."""
        agent = Mock()
        
        builder = SocialPostBuilder(agent, "Insta Post", "instagram", 1080, 1080)
        
        assert builder.design.design_type == CanvaDesignType.SOCIAL_MEDIA
        assert builder.platform == "instagram"
        assert builder.design.pages[0].width == 1080
        assert builder.design.pages[0].height == 1080
        print("✓ SocialPostBuilder works")

    def test_social_post_builder_platforms(self):
        """Test various platform sizes."""
        agent = Mock()
        
        for platform, (w, h) in SocialPostBuilder.PLATFORM_SIZES.items():
            builder = SocialPostBuilder(agent, "Test", platform, w, h)
            assert builder.design.pages[0].width == w
            assert builder.design.pages[0].height == h
        
        print("✓ All platform sizes correct")

    def test_social_post_watermark(self):
        """Test adding watermark."""
        agent = Mock()
        builder = SocialPostBuilder(agent, "Test", "instagram", 1080, 1080)
        
        builder.add_brand_watermark("https://logo.png", "bottom-right")
        
        # Should add image element at bottom-right
        assert len(builder.current_page.elements) == 1
        elem = builder.current_page.elements[0]
        assert elem.type == CanvaElementType.IMAGE
        assert elem.image_url == "https://logo.png"
        print("✓ SocialPostBuilder watermark works")

    def test_infographic_builder(self):
        """Test InfographicBuilder."""
        agent = Mock()
        builder = InfographicBuilder(agent, "Stats", 800, 2000)
        
        assert builder.design.design_type == CanvaDesignType.INFOGRAPHIC
        assert builder.section_y == 100
        print("✓ InfographicBuilder init works")

    def test_infographic_header(self):
        """Test infographic header."""
        agent = Mock()
        builder = InfographicBuilder(agent, "Title", 800, 2000)
        
        builder.header("Main Title", "Subtitle")
        
        assert len(builder.current_page.elements) == 2
        assert builder.current_page.elements[0].text == "Main Title"
        assert builder.current_page.elements[1].text == "Subtitle"
        assert builder.section_y > 200
        print("✓ InfographicBuilder header works")

    def test_infographic_stat_card(self):
        """Test infographic stat card."""
        agent = Mock()
        builder = InfographicBuilder(agent, "Stats", 800, 2000)
        
        builder.stat_card("99.99%", "Uptime", 100, 250, accent_color="#00D4AA")
        
        # Should have frame + value + label = 3 elements
        assert len(builder.current_page.elements) == 3
        # Check frame
        frame = builder.current_page.elements[0]
        assert frame.type == CanvaElementType.FRAME
        assert frame.corner_radius == 16
        print("✓ InfographicBuilder stat_card works")

    def test_infographic_divider(self):
        """Test infographic section divider."""
        agent = Mock()
        builder = InfographicBuilder(agent, "Test", 800, 2000)
        
        builder.section_divider(500)
        
        divider = builder.current_page.elements[0]
        assert divider.type == CanvaElementType.LINE
        assert divider.stroke.style == "dashed"
        assert divider.position.y == 500
        assert builder.section_y == 540
        print("✓ InfographicBuilder divider works")

    def test_module_constants(self):
        """Test module-level constants."""
        assert CANVA_API_BASE == "https://api.canva.com/rest/v1/"
        assert CANVA_AUTH_URL == "https://api.canva.com/rest/v1/oauth2/token"
        assert MAX_REQUESTS_PER_SECOND == 10
        assert REQUEST_TIMEOUT == 30.0
        print("✓ Module constants correct")


def run_tests():
    """Run all tests."""
    test = TestCanvaAgent()
    
    test.test_enums()
    test.test_canva_color_from_hex()
    test.test_canva_color_from_rgb()
    test.test_canva_color_to_canva_dict()
    test.test_canva_position()
    test.test_canva_text_style()
    test.test_canva_fill()
    test.test_canva_stroke()
    test.test_canva_element_text()
    test.test_canva_element_rectangle()
    test.test_canva_element_image()
    test.test_canva_element_frame()
    test.test_canva_page()
    test.test_canva_design()
    test.test_token_data()
    test.test_token_manager_init()
    test.test_canva_api_client_init()
    test.test_design_builder_basics()
    test.test_design_builder_add_page()
    test.test_design_builder_background()
    test.test_design_builder_text()
    test.test_design_builder_rectangle()
    test.test_design_builder_circle()
    test.test_design_builder_line()
    test.test_design_builder_image()
    test.test_design_builder_frame()
    test.test_design_builder_group()
    test.test_design_builder_build()
    test.test_presentation_builder()
    test.test_presentation_builder_title_slide()
    test.test_presentation_builder_content_slide()
    test.test_social_post_builder()
    test.test_social_post_builder_platforms()
    test.test_social_post_watermark()
    test.test_infographic_builder()
    test.test_infographic_header()
    test.test_infographic_stat_card()
    test.test_infographic_divider()
    test.test_module_constants()
    
    print("\n✅ All canva_agent tests passed!")


if __name__ == "__main__":
    run_tests()