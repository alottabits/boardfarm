"""Unit tests for pattern-based URL skipping in UI Discovery."""

import pytest

from boardfarm3.lib.gui.ui_discovery import UIDiscoveryTool


class TestPatternSkipping:
    """Test suite for pattern-based URL skipping optimization."""

    def test_pattern_skipping_disabled_by_default(self):
        """Test that pattern skipping is disabled by default."""
        tool = UIDiscoveryTool(
            base_url="http://example.com",
            headless=True,
        )
        
        assert tool.skip_pattern_duplicates is False
        assert tool.pattern_sample_size == 3

    def test_get_url_structure_device_pattern(self):
        """Test URL structure extraction for device URLs."""
        tool = UIDiscoveryTool(
            base_url="http://127.0.0.1:3000",
            headless=True,
        )
        
        url1 = "http://127.0.0.1:3000/#!/devices/ABC123"
        url2 = "http://127.0.0.1:3000/#!/devices/DEF456"
        url3 = "http://127.0.0.1:3000/#!/devices/GHI789"
        
        struct1 = tool._get_url_structure(url1)
        struct2 = tool._get_url_structure(url2)
        struct3 = tool._get_url_structure(url3)
        
        # All should have the same structure
        assert struct1 == struct2 == struct3
        assert struct1 == "devices"

    def test_get_url_structure_single_segment(self):
        """Test URL structure for single-segment paths."""
        tool = UIDiscoveryTool(
            base_url="http://127.0.0.1:3000",
            headless=True,
        )
        
        url = "http://127.0.0.1:3000/#!/overview"
        struct = tool._get_url_structure(url)
        
        # Single segments return the full path
        assert struct == "/overview"

    def test_should_skip_url_when_disabled(self):
        """Test that URLs are never skipped when feature is disabled."""
        tool = UIDiscoveryTool(
            base_url="http://127.0.0.1:3000",
            headless=True,
            skip_pattern_duplicates=False,
        )
        
        # Try many URLs with same pattern
        for i in range(10):
            url = f"http://127.0.0.1:3000/#!/devices/DEVICE{i}"
            should_skip, reason = tool._should_skip_url(url)
            assert should_skip is False
            assert reason == ""

    def test_should_skip_url_after_sample_size(self):
        """Test that URLs are skipped after sampling enough instances."""
        tool = UIDiscoveryTool(
            base_url="http://127.0.0.1:3000",
            headless=True,
            skip_pattern_duplicates=True,
            pattern_sample_size=3,
        )
        
        # First 3 should not be skipped (collecting samples)
        for i in range(1, 4):
            url = f"http://127.0.0.1:3000/#!/devices/DEVICE{i}"
            should_skip, reason = tool._should_skip_url(url)
            assert should_skip is False, f"Instance {i} should not be skipped"
        
        # 4th and beyond should be skipped
        for i in range(4, 10):
            url = f"http://127.0.0.1:3000/#!/devices/DEVICE{i}"
            should_skip, reason = tool._should_skip_url(url)
            assert should_skip is True, f"Instance {i} should be skipped"
            assert "pattern" in reason.lower()

    def test_should_skip_url_different_sample_size(self):
        """Test pattern skipping with custom sample size."""
        tool = UIDiscoveryTool(
            base_url="http://127.0.0.1:3000",
            headless=True,
            skip_pattern_duplicates=True,
            pattern_sample_size=5,
        )
        
        # First 5 should not be skipped
        for i in range(1, 6):
            url = f"http://127.0.0.1:3000/#!/devices/DEVICE{i}"
            should_skip, reason = tool._should_skip_url(url)
            assert should_skip is False, f"Instance {i} should not be skipped"
        
        # 6th and beyond should be skipped
        for i in range(6, 10):
            url = f"http://127.0.0.1:3000/#!/devices/DEVICE{i}"
            should_skip, reason = tool._should_skip_url(url)
            assert should_skip is True, f"Instance {i} should be skipped"

    def test_multiple_patterns_tracked_separately(self):
        """Test that different patterns are tracked independently."""
        tool = UIDiscoveryTool(
            base_url="http://127.0.0.1:3000",
            headless=True,
            skip_pattern_duplicates=True,
            pattern_sample_size=2,
        )
        
        # Add devices pattern instances
        tool._should_skip_url("http://127.0.0.1:3000/#!/devices/DEV1")
        tool._should_skip_url("http://127.0.0.1:3000/#!/devices/DEV2")
        
        # Add users pattern instances
        tool._should_skip_url("http://127.0.0.1:3000/#!/users/USER1")
        tool._should_skip_url("http://127.0.0.1:3000/#!/users/USER2")
        
        # Third instance of each pattern should be skipped
        should_skip_dev, _ = tool._should_skip_url("http://127.0.0.1:3000/#!/devices/DEV3")
        should_skip_user, _ = tool._should_skip_url("http://127.0.0.1:3000/#!/users/USER3")
        
        assert should_skip_dev is True
        assert should_skip_user is True
        
        # Should have detected 2 patterns
        assert len(tool.detected_patterns) == 2
        assert "devices" in tool.detected_patterns
        assert "users" in tool.detected_patterns

    def test_skipped_urls_tracked(self):
        """Test that skipped URLs are tracked for stats."""
        tool = UIDiscoveryTool(
            base_url="http://127.0.0.1:3000",
            headless=True,
            skip_pattern_duplicates=True,
            pattern_sample_size=2,
        )
        
        # Sample 2 instances
        tool._should_skip_url("http://127.0.0.1:3000/#!/devices/DEV1")
        tool._should_skip_url("http://127.0.0.1:3000/#!/devices/DEV2")
        
        # Skip 3 instances
        tool._should_skip_url("http://127.0.0.1:3000/#!/devices/DEV3")
        tool._should_skip_url("http://127.0.0.1:3000/#!/devices/DEV4")
        tool._should_skip_url("http://127.0.0.1:3000/#!/devices/DEV5")
        
        # Should have tracked 3 skipped URLs
        assert len(tool.skipped_urls) == 3
        
        # Each should have URL, pattern, and reason
        for skip_record in tool.skipped_urls:
            assert "url" in skip_record
            assert "pattern" in skip_record
            assert "reason" in skip_record
            assert skip_record["pattern"] == "devices"

    def test_empty_structure_not_skipped(self):
        """Test that URLs with empty structure are never skipped."""
        tool = UIDiscoveryTool(
            base_url="http://127.0.0.1:3000",
            headless=True,
            skip_pattern_duplicates=True,
            pattern_sample_size=2,  # Changed to 2 for this test
        )
        
        # Root paths have empty or "/" structure and are skipped in the filter
        should_skip1, _ = tool._should_skip_url("http://127.0.0.1:3000/")
        should_skip2, _ = tool._should_skip_url("http://127.0.0.1:3000/#!/")
        
        assert should_skip1 is False
        assert should_skip2 is False
        
        # Overview is a single segment path - first two instances should not be skipped
        should_skip3, _ = tool._should_skip_url("http://127.0.0.1:3000/#!/overview")
        should_skip4, _ = tool._should_skip_url("http://127.0.0.1:3000/#!/overview")  # Second instance
        
        assert should_skip3 is False
        assert should_skip4 is False
        
        # Third instance should be skipped (after sample size of 2)
        should_skip5, _ = tool._should_skip_url("http://127.0.0.1:3000/#!/overview")
        assert should_skip5 is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

