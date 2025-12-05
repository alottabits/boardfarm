"""Unit tests for page type classification in ui_discovery.py.

Tests that page classification correctly handles query parameters
and classifies filtered URLs with the same page type as unfiltered ones.
"""

import sys
from pathlib import Path

# Add boardfarm to path
boardfarm_path = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(boardfarm_path))

from boardfarm3.lib.gui.ui_discovery import UIDiscoveryTool


class TestPageClassification:
    """Test page type classification functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tool = UIDiscoveryTool.__new__(UIDiscoveryTool)
    
    def test_classify_device_list_without_filter(self):
        """Test classification of device list page without filter."""
        url = "http://127.0.0.1:3000/#!/devices"
        page_type = self.tool._classify_page(url)
        assert page_type == "device_list"
    
    def test_classify_device_list_with_filter(self):
        """Test classification of device list page WITH filter - should still be device_list."""
        url = "http://127.0.0.1:3000/#!/devices?filter=Events.Inform%20%3E%20NOW()%20-%20300000"
        page_type = self.tool._classify_page(url)
        assert page_type == "device_list", "Filtered device list should be classified as device_list, not device_details"
    
    def test_classify_device_list_with_complex_filter(self):
        """Test classification with complex filter expression."""
        url = "http://127.0.0.1:3000/#!/devices?filter=Events.Inform%20%3E%20NOW()%20-%2086700000%20AND%20Events.Inform%20%3C%20NOW()%20-%20300000"
        page_type = self.tool._classify_page(url)
        assert page_type == "device_list"
    
    def test_classify_device_details_without_query(self):
        """Test classification of device details page."""
        url = "http://127.0.0.1:3000/#!/devices/6E9875-SN6E987540799F"
        page_type = self.tool._classify_page(url)
        assert page_type == "device_details"
    
    def test_classify_device_details_with_query(self):
        """Test classification of device details page with query params."""
        url = "http://127.0.0.1:3000/#!/devices/6E9875-SN6E987540799F?tab=info"
        page_type = self.tool._classify_page(url)
        assert page_type == "device_details"
    
    def test_classify_faults_page(self):
        """Test classification of faults page."""
        url = "http://127.0.0.1:3000/#!/faults"
        page_type = self.tool._classify_page(url)
        assert page_type == "faults"
    
    def test_classify_faults_with_filter(self):
        """Test classification of faults page with filter."""
        url = "http://127.0.0.1:3000/#!/faults?filter=severity%3Dhigh"
        page_type = self.tool._classify_page(url)
        assert page_type == "faults"
    
    def test_classify_admin_page(self):
        """Test classification of admin page."""
        url = "http://127.0.0.1:3000/#!/admin"
        page_type = self.tool._classify_page(url)
        assert page_type == "admin"
    
    def test_classify_admin_presets(self):
        """Test classification of admin presets sub-page."""
        url = "http://127.0.0.1:3000/#!/admin/presets"
        page_type = self.tool._classify_page(url)
        assert page_type == "presets"
    
    def test_classify_admin_provisions_with_filter(self):
        """Test classification of provisions page with filter."""
        url = "http://127.0.0.1:3000/#!/admin/provisions?filter=Q(%22ID%22%2C%20%22bootstrap%22)"
        page_type = self.tool._classify_page(url)
        assert page_type == "provisions"
    
    def test_classify_home_page(self):
        """Test classification of home/overview page."""
        url = "http://127.0.0.1:3000/#!/overview"
        page_type = self.tool._classify_page(url)
        assert page_type == "home"
    
    def test_classify_login_page(self):
        """Test classification of login page."""
        url = "http://127.0.0.1:3000/login"
        page_type = self.tool._classify_page(url)
        assert page_type == "login"
    
    def test_classify_unknown_page(self):
        """Test classification of unknown page."""
        url = "http://127.0.0.1:3000/#!/unknown-page"
        page_type = self.tool._classify_page(url)
        assert page_type == "unknown"
    
    def test_consistency_filtered_vs_unfiltered(self):
        """Test that filtered and unfiltered versions have same page type."""
        base_url = "http://127.0.0.1:3000/#!/devices"
        filtered_url1 = "http://127.0.0.1:3000/#!/devices?filter=A"
        filtered_url2 = "http://127.0.0.1:3000/#!/devices?filter=B&sort=name"
        
        base_type = self.tool._classify_page(base_url)
        filtered_type1 = self.tool._classify_page(filtered_url1)
        filtered_type2 = self.tool._classify_page(filtered_url2)
        
        assert base_type == filtered_type1 == filtered_type2 == "device_list"
