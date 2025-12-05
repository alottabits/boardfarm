"""Unit tests for SVG link handling in ui_discovery.py.

Tests that SVG links with dict-type href attributes are properly
extracted and identified with element_type='svg_link'.
"""

import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# Add boardfarm to path
boardfarm_path = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(boardfarm_path))

from boardfarm3.lib.gui.ui_discovery import UIDiscoveryTool


class TestSVGLinkHandling:
    """Test SVG link extraction and identification."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tool = UIDiscoveryTool.__new__(UIDiscoveryTool)
        self.tool.visited_urls = set()
        
        # Mock the graph
        self.tool.graph = Mock()
        self.tool.graph.add_element = Mock(return_value="elem_link_1")
        self.tool.graph.add_navigation_link = Mock()
        
        # Mock the driver
        self.tool.driver = Mock()
    
    @patch('boardfarm3.lib.gui.ui_discovery.logger')
    def test_svg_link_extraction_baseVal(self, mock_logger):
        """Test extraction of href from SVG element with baseVal."""
        # Create mock SVG link element
        svg_link = Mock()
        svg_link.get_attribute.return_value = {
            'baseVal': '#!/devices?filter=X',
            'animVal': '#!/devices?filter=X'
        }
        svg_link.text.strip.return_value = "Filtered Devices"
        svg_link.is_displayed.return_value = True
        
        # Mock driver to return our SVG link
        self.tool.driver.find_elements.return_value = [svg_link]
        
        # Mock helper methods
        self.tool._get_css_selector = Mock(return_value="a.svg-link")
        self.tool._is_internal_link = Mock(return_value=True)
        self.tool._normalize_url = Mock(return_value="http://127.0.0.1:3000/#!/devices")
        
        # Execute
        leaves = self.tool._find_links("http://127.0.0.1:3000/#!/overview")
        
        # Verify href was extracted
        assert len(leaves) == 1
        assert leaves[0] == "http://127.0.0.1:3000/#!/devices"
        
        # Verify element was added with svg_link type
        self.tool.graph.add_element.assert_called_once()
        call_args = self.tool.graph.add_element.call_args
        assert call_args[0][1] == "svg_link"  # element_type
        
        # Verify debug log was called
        mock_logger.debug.assert_called()
    
    @patch('boardfarm3.lib.gui.ui_discovery.logger')
    def test_html_link_remains_link_type(self, mock_logger):
        """Test that HTML links are still identified as 'link' type."""
        # Create mock HTML link element
        html_link = Mock()
        html_link.get_attribute.return_value = "#!/devices"  # String, not dict
        html_link.text.strip.return_value = "Devices"
        html_link.is_displayed.return_value = True
        
        # Mock driver to return our HTML link
        self.tool.driver.find_elements.return_value = [html_link]
        
        # Mock helper methods
        self.tool._get_css_selector = Mock(return_value="a.nav-link")
        self.tool._is_internal_link = Mock(return_value=True)
        self.tool._normalize_url = Mock(return_value="http://127.0.0.1:3000/#!/devices")
        
        # Execute
        leaves = self.tool._find_links("http://127.0.0.1:3000/#!/overview")
        
        # Verify element was added with link type (not svg_link)
        self.tool.graph.add_element.assert_called_once()
        call_args = self.tool.graph.add_element.call_args
        assert call_args[0][1] == "link"  # element_type
    
    @patch('boardfarm3.lib.gui.ui_discovery.logger')
    def test_svg_link_with_animVal_only(self, mock_logger):
        """Test extraction when only animVal is present."""
        # Create mock SVG link with only animVal
        svg_link = Mock()
        svg_link.get_attribute.return_value = {
            'animVal': '#!/faults'
        }
        svg_link.text.strip.return_value = "Faults"
        svg_link.is_displayed.return_value = True
        
        # Mock driver
        self.tool.driver.find_elements.return_value = [svg_link]
        
        # Mock helpers
        self.tool._get_css_selector = Mock(return_value="a.svg-icon")
        self.tool._is_internal_link = Mock(return_value=True)
        self.tool._normalize_url = Mock(return_value="http://127.0.0.1:3000/#!/faults")
        
        # Execute
        leaves = self.tool._find_links("http://127.0.0.1:3000/#!/overview")
        
        # Verify href was extracted from animVal
        assert len(leaves) == 1
        assert leaves[0] == "http://127.0.0.1:3000/#!/faults"
        
        # Verify svg_link type
        call_args = self.tool.graph.add_element.call_args
        assert call_args[0][1] == "svg_link"
    
    @patch('boardfarm3.lib.gui.ui_discovery.logger')
    def test_mixed_html_and_svg_links(self, mock_logger):
        """Test page with both HTML and SVG links."""
        # Create mock HTML link
        html_link = Mock()
        html_link.get_attribute.return_value = "#!/devices"
        html_link.text.strip.return_value = "Devices"
        html_link.is_displayed.return_value = True
        
        # Create mock SVG link
        svg_link = Mock()
        svg_link.get_attribute.return_value = {
            'baseVal': '#!/faults',
            'animVal': '#!/faults'
        }
        svg_link.text.strip.return_value = "Faults"
        svg_link.is_displayed.return_value = True
        
        # Mock driver to return both
        self.tool.driver.find_elements.return_value = [html_link, svg_link]
        
        # Mock helpers
        self.tool._get_css_selector = Mock(side_effect=["a.nav-link", "a.svg-icon"])
        self.tool._is_internal_link = Mock(return_value=True)
        self.tool._normalize_url = Mock(side_effect=[
            "http://127.0.0.1:3000/#!/devices",
            "http://127.0.0.1:3000/#!/faults"
        ])
        
        # Execute
        leaves = self.tool._find_links("http://127.0.0.1:3000/#!/overview")
        
        # Verify both links discovered
        assert len(leaves) == 2
        
        # Verify element types
        calls = self.tool.graph.add_element.call_args_list
        assert calls[0][0][1] == "link"      # First call: HTML link
        assert calls[1][0][1] == "svg_link"  # Second call: SVG link
    
    @patch('boardfarm3.lib.gui.ui_discovery.logger')
    def test_invalid_svg_href_skipped(self, mock_logger):
        """Test that invalid SVG href (non-dict, non-string) is skipped."""
        # Create mock element with invalid href
        invalid_link = Mock()
        invalid_link.get_attribute.return_value = 12345  # Invalid type
        invalid_link.text.strip.return_value = "Invalid"
        invalid_link.is_displayed.return_value = True
        
        # Mock driver
        self.tool.driver.find_elements.return_value = [invalid_link]
        
        # Execute
        leaves = self.tool._find_links("http://127.0.0.1:3000/#!/overview")
        
        # Verify link was skipped
        assert len(leaves) == 0
        self.tool.graph.add_element.assert_not_called()
        
        # Verify warning was logged
        mock_logger.warning.assert_called()
