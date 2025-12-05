"""Unit tests for query string pattern detection in ui_discovery.py.

Tests that the pattern detection correctly identifies and groups
URLs with query string variations.
"""

import sys
from pathlib import Path

# Add boardfarm to path
boardfarm_path = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(boardfarm_path))

from boardfarm3.lib.gui.ui_discovery import UIDiscoveryTool


class TestURLStructureExtraction:
    """Test URL structure extraction for pattern matching."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tool = UIDiscoveryTool.__new__(UIDiscoveryTool)
    
    def test_structure_path_based_pattern(self):
        """Test structure extraction for path-based patterns."""
        url1 = "http://127.0.0.1:3000/#!/devices/6E9875-SN6E987540799F"
        url2 = "http://127.0.0.1:3000/#!/devices/7AB8BB-SN7AB8BBF666EB"
        url3 = "http://127.0.0.1:3000/#!/devices/CE80B3-SNCE80B324E04D"
        
        struct1 = self.tool._get_url_structure(url1)
        struct2 = self.tool._get_url_structure(url2)
        struct3 = self.tool._get_url_structure(url3)
        
        # All should have same structure (devices)
        assert struct1 == struct2 == struct3 == "devices"
    
    def test_structure_query_based_pattern(self):
        """Test structure extraction for query-based patterns."""
        url1 = "http://127.0.0.1:3000/#!/devices?filter=Events.Inform%20%3E%20NOW()%20-%20300000"
        url2 = "http://127.0.0.1:3000/#!/devices?filter=Events.Inform%20%3C%20NOW()%20-%2086700000"
        url3 = "http://127.0.0.1:3000/#!/devices?filter=Events.Inform%20%3E%20NOW()%20-%2086700000%20AND%20Events.Inform%20%3C%20NOW()%20-%20300000"
        
        struct1 = self.tool._get_url_structure(url1)
        struct2 = self.tool._get_url_structure(url2)
        struct3 = self.tool._get_url_structure(url3)
        
        # All should have same structure (devices?filter={filter})
        assert struct1 == struct2 == struct3 == "/devices?filter={filter}"
    
    def test_structure_base_page_no_query(self):
        """Test structure extraction for base page without query."""
        url = "http://127.0.0.1:3000/#!/devices"
        struct = self.tool._get_url_structure(url)
        assert struct == "/devices"
    
    def test_structure_multiple_query_params(self):
        """Test structure extraction with multiple query parameters."""
        url1 = "http://127.0.0.1:3000/#!/devices?filter=A&sort=name"
        url2 = "http://127.0.0.1:3000/#!/devices?filter=B&sort=date"
        
        struct1 = self.tool._get_url_structure(url1)
        struct2 = self.tool._get_url_structure(url2)
        
        # Should have same structure (alphabetically sorted params)
        assert struct1 == struct2 == "/devices?filter={filter}&sort={sort}"
    
    def test_structure_provisions_with_filter(self):
        """Test structure extraction for provisions with filter."""
        url1 = "http://127.0.0.1:3000/#!/admin/provisions?filter=Q(%22ID%22%2C%20%22bootstrap%22)"
        url2 = "http://127.0.0.1:3000/#!/admin/provisions?filter=Q(%22ID%22%2C%20%22default%22)"
        url3 = "http://127.0.0.1:3000/#!/admin/provisions?filter=Q(%22ID%22%2C%20%22inform%22)"
        
        struct1 = self.tool._get_url_structure(url1)
        struct2 = self.tool._get_url_structure(url2)
        struct3 = self.tool._get_url_structure(url3)
        
        # All should have same structure
        assert struct1 == struct2 == struct3 == "/admin/provisions?filter={filter}"
    
    def test_structure_different_pages_different_structures(self):
        """Test that different pages have different structures."""
        devices_url = "http://127.0.0.1:3000/#!/devices?filter=X"
        faults_url = "http://127.0.0.1:3000/#!/faults?filter=X"
        
        devices_struct = self.tool._get_url_structure(devices_url)
        faults_struct = self.tool._get_url_structure(faults_url)
        
        assert devices_struct != faults_struct
        assert devices_struct == "/devices?filter={filter}"
        assert faults_struct == "/faults?filter={filter}"


class TestPatternSkipping:
    """Test pattern-based URL skipping functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create tool with pattern skipping enabled
        self.tool = UIDiscoveryTool.__new__(UIDiscoveryTool)
        self.tool.skip_pattern_duplicates = True
        self.tool.pattern_sample_size = 2
        self.tool.pattern_tracker = {}
        self.tool.detected_patterns = set()
        self.tool.skipped_urls = []
    
    def test_skip_after_sampling(self):
        """Test that URLs are skipped after sampling N instances."""
        url1 = "http://127.0.0.1:3000/#!/devices?filter=A"
        url2 = "http://127.0.0.1:3000/#!/devices?filter=B"
        url3 = "http://127.0.0.1:3000/#!/devices?filter=C"
        
        # First URL should not be skipped
        should_skip1, reason1 = self.tool._should_skip_url(url1)
        assert not should_skip1
        
        # Track successful crawl
        self.tool._track_successful_crawl(url1)
        
        # Second URL should not be skipped (still sampling)
        should_skip2, reason2 = self.tool._should_skip_url(url2)
        assert not should_skip2
        
        # Track successful crawl
        self.tool._track_successful_crawl(url2)
        
        # Third URL SHOULD be skipped (reached sample size)
        should_skip3, reason3 = self.tool._should_skip_url(url3)
        assert should_skip3
        assert "pattern" in reason3.lower()
    
    def test_different_patterns_tracked_separately(self):
        """Test that different patterns are tracked separately."""
        devices_url1 = "http://127.0.0.1:3000/#!/devices?filter=A"
        devices_url2 = "http://127.0.0.1:3000/#!/devices?filter=B"
        faults_url1 = "http://127.0.0.1:3000/#!/faults?filter=A"
        faults_url2 = "http://127.0.0.1:3000/#!/faults?filter=B"
        
        # Track devices
        self.tool._track_successful_crawl(devices_url1)
        self.tool._track_successful_crawl(devices_url2)
        
        # Track faults
        self.tool._track_successful_crawl(faults_url1)
        
        # Devices pattern should be at limit
        should_skip_devices, _ = self.tool._should_skip_url("http://127.0.0.1:3000/#!/devices?filter=C")
        assert should_skip_devices
        
        # Faults pattern should still allow one more
        should_skip_faults, _ = self.tool._should_skip_url(faults_url2)
        assert not should_skip_faults
    
    def test_path_patterns_vs_query_patterns(self):
        """Test that path patterns and query patterns are tracked separately."""
        # Path-based pattern (device IDs)
        device_detail1 = "http://127.0.0.1:3000/#!/devices/ID1"
        device_detail2 = "http://127.0.0.1:3000/#!/devices/ID2"
        
        # Query-based pattern (filters)
        device_filter1 = "http://127.0.0.1:3000/#!/devices?filter=A"
        device_filter2 = "http://127.0.0.1:3000/#!/devices?filter=B"
        
        # Track both patterns
        self.tool._track_successful_crawl(device_detail1)
        self.tool._track_successful_crawl(device_detail2)
        self.tool._track_successful_crawl(device_filter1)
        self.tool._track_successful_crawl(device_filter2)
        
        # Both patterns should be at limit
        should_skip_detail, _ = self.tool._should_skip_url("http://127.0.0.1:3000/#!/devices/ID3")
        should_skip_filter, _ = self.tool._should_skip_url("http://127.0.0.1:3000/#!/devices?filter=C")
        
        assert should_skip_detail
        assert should_skip_filter
    
    def test_pattern_detection_logged(self):
        """Test that pattern detection is logged correctly."""
        url1 = "http://127.0.0.1:3000/#!/devices?filter=A"
        url2 = "http://127.0.0.1:3000/#!/devices?filter=B"
        url3 = "http://127.0.0.1:3000/#!/devices?filter=C"
        
        # Track samples
        self.tool._track_successful_crawl(url1)
        self.tool._track_successful_crawl(url2)
        
        # Check for pattern detection
        should_skip, _ = self.tool._should_skip_url(url3)
        
        # Pattern should be detected
        assert "/devices?filter={filter}" in self.tool.detected_patterns
