"""Unit tests for URL normalization in ui_discovery.py.

Tests the enhanced URL normalization that strips query parameters
from both standard URLs and SPA fragments.
"""

import sys
from pathlib import Path

# Add boardfarm to path
boardfarm_path = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(boardfarm_path))

from boardfarm3.lib.gui.ui_discovery import UIDiscoveryTool


class TestURLNormalization:
    """Test URL normalization functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create tool instance (won't initialize browser)
        self.tool = UIDiscoveryTool.__new__(UIDiscoveryTool)
    
    def test_normalize_standard_url_with_query(self):
        """Test normalization of standard URL with query parameters."""
        url = "http://example.com/page?param1=value1&param2=value2"
        expected = "http://example.com/page"
        assert self.tool._normalize_url(url) == expected
    
    def test_normalize_spa_fragment_with_query(self):
        """Test normalization of SPA fragment with query parameters."""
        url = "http://127.0.0.1:3000/#!/devices?filter=Events.Inform%20%3E%20NOW()"
        expected = "http://127.0.0.1:3000/#!/devices"
        assert self.tool._normalize_url(url) == expected
    
    def test_normalize_spa_fragment_multiple_query_params(self):
        """Test normalization with multiple query parameters in fragment."""
        url = "http://127.0.0.1:3000/#!/devices?filter=X&sort=name&limit=10"
        expected = "http://127.0.0.1:3000/#!/devices"
        assert self.tool._normalize_url(url) == expected
    
    def test_normalize_url_without_query(self):
        """Test normalization of URL without query parameters."""
        url = "http://127.0.0.1:3000/#!/devices"
        expected = "http://127.0.0.1:3000/#!/devices"
        assert self.tool._normalize_url(url) == expected
    
    def test_normalize_url_with_trailing_slash(self):
        """Test normalization removes trailing slashes."""
        url = "http://example.com/page/"
        expected = "http://example.com/page"
        assert self.tool._normalize_url(url) == expected
    
    def test_normalize_root_url(self):
        """Test normalization of root URL."""
        url = "http://example.com/"
        expected = "http://example.com/"
        assert self.tool._normalize_url(url) == expected
    
    def test_normalize_complex_filter_expression(self):
        """Test normalization with complex filter expression."""
        url = "http://127.0.0.1:3000/#!/devices?filter=Events.Inform%20%3E%20NOW()%20-%2086700000%20AND%20Events.Inform%20%3C%20NOW()%20-%20300000"
        expected = "http://127.0.0.1:3000/#!/devices"
        assert self.tool._normalize_url(url) == expected


class TestQueryStringParsing:
    """Test query string parsing functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tool = UIDiscoveryTool.__new__(UIDiscoveryTool)
    
    def test_parse_standard_query_string(self):
        """Test parsing standard URL query parameters."""
        url = "http://example.com/page?param1=value1&param2=value2"
        params = self.tool._parse_query_string(url)
        assert params == {"param1": "value1", "param2": "value2"}
    
    def test_parse_spa_fragment_query(self):
        """Test parsing query parameters from SPA fragment."""
        url = "http://127.0.0.1:3000/#!/devices?filter=Events.Inform%20%3E%20NOW()"
        params = self.tool._parse_query_string(url)
        assert "filter" in params
        assert "Events.Inform > NOW()" in params["filter"]
    
    def test_parse_empty_query(self):
        """Test parsing URL without query parameters."""
        url = "http://example.com/page"
        params = self.tool._parse_query_string(url)
        assert params == {}
    
    def test_parse_multiple_query_params(self):
        """Test parsing multiple query parameters."""
        url = "http://127.0.0.1:3000/#!/devices?filter=X&sort=name&limit=10"
        params = self.tool._parse_query_string(url)
        assert params == {"filter": "X", "sort": "name", "limit": "10"}
    
    def test_parse_url_encoded_values(self):
        """Test parsing URL-encoded query values."""
        url = "http://example.com/page?name=John%20Doe&email=test%40example.com"
        params = self.tool._parse_query_string(url)
        assert params["name"] == "John Doe"
        assert params["email"] == "test@example.com"


class TestQueryPatternExtraction:
    """Test query pattern extraction functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tool = UIDiscoveryTool.__new__(UIDiscoveryTool)
    
    def test_extract_single_param_pattern(self):
        """Test extracting pattern from single query parameter."""
        url = "http://127.0.0.1:3000/#!/devices?filter=Events.Inform%20%3E%20NOW()"
        pattern = self.tool._extract_query_pattern(url)
        assert pattern == "?filter={filter}"
    
    def test_extract_multiple_params_pattern(self):
        """Test extracting pattern from multiple query parameters."""
        url = "http://127.0.0.1:3000/#!/devices?filter=X&sort=name&limit=10"
        pattern = self.tool._extract_query_pattern(url)
        # Should be sorted alphabetically
        assert pattern == "?filter={filter}&limit={limit}&sort={sort}"
    
    def test_extract_pattern_no_query(self):
        """Test extracting pattern from URL without query."""
        url = "http://127.0.0.1:3000/#!/devices"
        pattern = self.tool._extract_query_pattern(url)
        assert pattern is None
    
    def test_extract_pattern_consistency(self):
        """Test that different values produce same pattern."""
        url1 = "http://127.0.0.1:3000/#!/devices?filter=A"
        url2 = "http://127.0.0.1:3000/#!/devices?filter=B"
        url3 = "http://127.0.0.1:3000/#!/devices?filter=C"
        
        pattern1 = self.tool._extract_query_pattern(url1)
        pattern2 = self.tool._extract_query_pattern(url2)
        pattern3 = self.tool._extract_query_pattern(url3)
        
        assert pattern1 == pattern2 == pattern3 == "?filter={filter}"
