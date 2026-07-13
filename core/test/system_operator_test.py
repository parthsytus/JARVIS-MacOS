"""
Test suite for system_operator.py - Computer-Using Agent
Tests screen capture, vision analysis, and UI action execution.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
from unittest.mock import Mock, patch, MagicMock

# Test imports
from core.system_operator import (
    UIElement,
    ScreenAnalysis,
    capture_screen,
    compress_image,
    image_to_base64,
    analyze_screen,
    execute_ui_action,
    find_and_click,
    find_element,
    get_screen_size,
    safe_coordinates,
    VISION_SYSTEM_PROMPT,
    MAX_SCREEN_WIDTH,
    MAX_SCREEN_HEIGHT,
)


class TestSystemOperator:
    """Test cases for system_operator module."""

    def test_ui_element_creation(self):
        """Test UIElement dataclass creation."""
        elem = UIElement(
            element_type="button",
            description="Submit button",
            x=100, y=200,
            width=80, height=40,
            confidence=0.95,
            action_hint="click"
        )
        assert elem.element_type == "button"
        assert elem.x == 100
        assert elem.y == 200
        assert elem.confidence == 0.95
        print("✓ UIElement creation works")

    def test_screen_analysis_creation(self):
        """Test ScreenAnalysis dataclass creation."""
        elements = [UIElement("button", "Test", 10, 10, 50, 30, 0.9, "click")]
        analysis = ScreenAnalysis(
            elements=elements,
            screen_width=1920,
            screen_height=1080,
            timestamp=1234567890.0,
            raw_response='[{"element_type": "button"}]'
        )
        assert len(analysis.elements) == 1
        assert analysis.screen_width == 1920
        print("✓ ScreenAnalysis creation works")

    @patch('core.system_operator.ImageGrab.grab')
    def test_capture_screen(self, mock_grab):
        """Test screen capture function."""
        mock_image = Mock()
        mock_image.size = (1920, 1080)
        mock_image.mode = "RGB"
        mock_grab.return_value = mock_image

        result = capture_screen()
        assert result == mock_image
        mock_grab.assert_called_once_with(all_screens=True)
        print("✓ capture_screen works")

    def test_compress_image(self):
        """Test image compression."""
        from PIL import Image
        # Create a test image larger than max dimensions
        img = Image.new('RGB', (2000, 1500), color='red')
        
        compressed = compress_image(img)
        assert isinstance(compressed, bytes)
        assert len(compressed) > 0
        
        # Verify dimensions are reduced
        from PIL import Image as PILImage
        import io
        compressed_img = PILImage.open(io.BytesIO(compressed))
        assert compressed_img.width <= MAX_SCREEN_WIDTH
        assert compressed_img.height <= MAX_SCREEN_HEIGHT
        print("✓ compress_image works")

    def test_image_to_base64(self):
        """Test base64 encoding."""
        test_bytes = b"test image data"
        result = image_to_base64(test_bytes)
        assert isinstance(result, str)
        # Verify it's valid base64
        import base64
        decoded = base64.b64decode(result)
        assert decoded == test_bytes
        print("✓ image_to_base64 works")

    @patch('core.system_operator.capture_screen')
    @patch('core.system_operator.compress_image')
    @patch('core.system_operator.image_to_base64')
    @patch('core.system_operator._get_groq_client')
    def test_analyze_screen(self, mock_client, mock_b64, mock_compress, mock_capture):
        """Test screen analysis with mocked Groq."""
        # Setup mocks
        mock_img = Mock()
        mock_img.size = (1920, 1080)
        mock_capture.return_value = mock_img
        mock_compress.return_value = b"compressed"
        mock_b64.return_value = "base64string"
        
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content='{"elements": [{"element_type": "button", "description": "Test button", "x": 100, "y": 200, "width": 80, "height": 40, "confidence": 0.9, "action_hint": "click"}]}'))]
        mock_client.return_value.chat.completions.create.return_value = mock_response

        result = analyze_screen(user_query="find button", context="testing")
        
        assert isinstance(result, ScreenAnalysis)
        assert len(result.elements) == 1
        assert result.elements[0].element_type == "button"
        assert result.screen_width == 1920
        print("✓ analyze_screen works with mocked Groq")

    @patch('core.system_operator.pyautogui')
    def test_execute_ui_action_click(self, mock_pyautogui):
        """Test click action execution."""
        result = execute_ui_action("click", 100, 200)
        
        assert result["success"] is True
        assert "Clicked at (100, 200)" in result["message"]
        mock_pyautogui.moveTo.assert_called_once_with(100, 200, duration=0.15)
        mock_pyautogui.click.assert_called_once_with(100, 200)
        print("✓ execute_ui_action click works")

    @patch('core.system_operator.pyautogui')
    def test_execute_ui_action_type(self, mock_pyautogui):
        """Test type action execution."""
        result = execute_ui_action("type", 100, 200, text="hello")
        
        assert result["success"] is True
        assert "Typed" in result["message"]
        mock_pyautogui.click.assert_called_once_with(100, 200)
        mock_pyautogui.write.assert_called_once_with("hello", interval=0.01)
        print("✓ execute_ui_action type works")

    @patch('core.system_operator.pyautogui')
    def test_execute_ui_action_hotkey(self, mock_pyautogui):
        """Test hotkey action execution."""
        result = execute_ui_action("hotkey", 0, 0, hotkey=["cmd", "c"])
        
        assert result["success"] is True
        assert "cmd+c" in result["message"].lower()
        mock_pyautogui.hotkey.assert_called_once_with("cmd", "c")
        print("✓ execute_ui_action hotkey works")

    @patch('core.system_operator.analyze_screen')
    @patch('core.system_operator.execute_ui_action')
    def test_find_and_click(self, mock_execute, mock_analyze):
        """Test high-level find and click."""
        mock_analyze.return_value = ScreenAnalysis(
            elements=[
                UIElement("button", "Submit button", 100, 200, 80, 40, 0.9, "click"),
                UIElement("button", "Cancel button", 200, 200, 80, 40, 0.8, "click"),
            ],
            screen_width=1920, screen_height=1080,
            timestamp=1234567890.0, raw_response="{}"
        )
        mock_execute.return_value = {"success": True, "message": "Clicked"}

        result = find_and_click("Submit", user_query="click submit")
        
        assert result["success"] is True
        mock_analyze.assert_called_once()
        mock_execute.assert_called_once_with("click", 100, 200)
        print("✓ find_and_click works")

    @patch('core.system_operator.analyze_screen')
    def test_find_element(self, mock_analyze):
        """Test element finding without clicking."""
        mock_analyze.return_value = ScreenAnalysis(
            elements=[
                UIElement("input", "Search field", 300, 100, 400, 40, 0.95, "type"),
            ],
            screen_width=1920, screen_height=1080,
            timestamp=1234567890.0, raw_response="{}"
        )

        element = find_element("search")
        
        assert element is not None
        assert element.element_type == "input"
        assert element.description == "Search field"
        print("✓ find_element works")

    def test_get_screen_size(self):
        """Test screen size retrieval."""
        with patch('core.system_operator.pyautogui.size', return_value=(1920, 1080)):
            w, h = get_screen_size()
            assert w == 1920
            assert h == 1080
        print("✓ get_screen_size works")

    def test_safe_coordinates(self):
        """Test coordinate clamping."""
        with patch('core.system_operator.get_screen_size', return_value=(1920, 1080)):
            x, y = safe_coordinates(-100, -50)
            assert x == 0
            assert y == 0
            
            x, y = safe_coordinates(2000, 1200)
            assert x == 1919
            assert y == 1079
            
            x, y = safe_coordinates(100, 200)
            assert x == 100
            assert y == 200
        print("✓ safe_coordinates works")

    def test_vision_system_prompt(self):
        """Verify vision system prompt is properly defined."""
        assert "JSON array" in VISION_SYSTEM_PROMPT
        assert "element_type" in VISION_SYSTEM_PROMPT
        assert "action_hint" in VISION_SYSTEM_PROMPT
        print("✓ VISION_SYSTEM_PROMPT is properly defined")

    def test_config_constants(self):
        """Test configuration constants."""
        assert MAX_SCREEN_WIDTH == 1024
        assert MAX_SCREEN_HEIGHT == 576
        print("✓ Config constants are correct")


def run_tests():
    """Run all tests."""
    test = TestSystemOperator()
    
    test.test_ui_element_creation()
    test.test_screen_analysis_creation()
    test.test_capture_screen()
    test.test_compress_image()
    test.test_image_to_base64()
    test.test_analyze_screen()
    test.test_execute_ui_action_click()
    test.test_execute_ui_action_type()
    test.test_execute_ui_action_hotkey()
    test.test_find_and_click()
    test.test_find_element()
    test.test_get_screen_size()
    test.test_safe_coordinates()
    test.test_vision_system_prompt()
    test.test_config_constants()
    
    print("\n✅ All system_operator tests passed!")


if __name__ == "__main__":
    run_tests()