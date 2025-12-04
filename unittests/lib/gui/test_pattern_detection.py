"""Unit tests for UI Discovery Tool pattern detection.

Tests the URLPatternDetector class to ensure it correctly identifies
and groups similar URLs into patterns.
"""

import pytest
from boardfarm3.lib.gui.ui_discovery import URLPatternDetector


class TestURLPatternDetector:
    """Test suite for URLPatternDetector."""

    def test_detect_simple_device_pattern(self):
        """Test detection of simple device ID pattern."""
        pages = [
            {"url": "http://example.com/#!/devices/ABC123"},
            {"url": "http://example.com/#!/devices/DEF456"},
            {"url": "http://example.com/#!/devices/GHI789"},
            {"url": "http://example.com/#!/overview"},
        ]

        detector = URLPatternDetector(min_pattern_count=3)
        patterns = detector.detect_patterns(pages)

        assert len(patterns) == 1
        assert patterns[0]["pattern"] == "#!/devices/{device_id}"
        assert patterns[0]["count"] == 3
        assert patterns[0]["parameter_name"] == "device_id"

    def test_no_pattern_below_threshold(self):
        """Test that patterns below min_count threshold are not detected."""
        pages = [
            {"url": "http://example.com/#!/devices/ABC123"},
            {"url": "http://example.com/#!/devices/DEF456"},
            {"url": "http://example.com/#!/overview"},
        ]

        detector = URLPatternDetector(min_pattern_count=3)
        patterns = detector.detect_patterns(pages)

        assert len(patterns) == 0

    def test_multiple_patterns(self):
        """Test detection of multiple different patterns."""
        pages = [
            {"url": "http://example.com/#!/devices/ABC123"},
            {"url": "http://example.com/#!/devices/DEF456"},
            {"url": "http://example.com/#!/devices/GHI789"},
            {"url": "http://example.com/#!/users/user1"},
            {"url": "http://example.com/#!/users/user2"},
            {"url": "http://example.com/#!/users/user3"},
            {"url": "http://example.com/#!/overview"},
        ]

        detector = URLPatternDetector(min_pattern_count=3)
        patterns = detector.detect_patterns(pages)

        assert len(patterns) == 2
        pattern_templates = [p["pattern"] for p in patterns]
        assert "#!/devices/{device_id}" in pattern_templates
        assert "#!/users/{user_id}" in pattern_templates

    def test_genieacs_device_pattern(self):
        """Test detection of GenieACS-style device patterns."""
        pages = [
            {
                "url": "http://127.0.0.1:3000/#!/devices/06E1AF-SN06E1AFE199B4",
                "title": "Overview - GenieACS",
                "page_type": "device_details",
            },
            {
                "url": "http://127.0.0.1:3000/#!/devices/0A08B3-SN0A08B3DA2A1D",
                "title": "Overview - GenieACS",
                "page_type": "device_details",
            },
            {
                "url": "http://127.0.0.1:3000/#!/devices/0A4250-SN0A4250DF0848",
                "title": "Overview - GenieACS",
                "page_type": "device_details",
            },
        ]

        detector = URLPatternDetector(min_pattern_count=3)
        patterns = detector.detect_patterns(pages)

        assert len(patterns) == 1
        assert patterns[0]["pattern"] == "#!/devices/{device_id}"
        assert patterns[0]["count"] == 3
        assert patterns[0]["description"] == "Devices detail page"
        assert len(patterns[0]["example_urls"]) == 3

    def test_pattern_with_page_structure(self):
        """Test that pattern includes common page structure."""
        pages = [
            {
                "url": "http://example.com/#!/devices/ABC123",
                "title": "Device Details",
                "page_type": "device_details",
                "buttons": [{"text": "Reboot"}, {"text": "Delete"}],
                "inputs": [{"type": "text"}],
            },
            {
                "url": "http://example.com/#!/devices/DEF456",
                "title": "Device Details",
                "page_type": "device_details",
                "buttons": [{"text": "Reboot"}, {"text": "Delete"}],
                "inputs": [{"type": "text"}],
            },
            {
                "url": "http://example.com/#!/devices/GHI789",
                "title": "Device Details",
                "page_type": "device_details",
                "buttons": [{"text": "Reboot"}, {"text": "Delete"}],
                "inputs": [{"type": "text"}],
            },
        ]

        detector = URLPatternDetector(min_pattern_count=3)
        patterns = detector.detect_patterns(pages)

        assert len(patterns) == 1
        page_structure = patterns[0]["page_structure"]
        assert page_structure["title_pattern"] == "Device Details"
        assert page_structure["page_type"] == "device_details"
        assert "Reboot" in page_structure["common_buttons"]
        assert "Delete" in page_structure["common_buttons"]

    def test_path_based_routing(self):
        """Test pattern detection for path-based (non-hash) routing."""
        pages = [
            {"url": "http://example.com/devices/ABC123"},
            {"url": "http://example.com/devices/DEF456"},
            {"url": "http://example.com/devices/GHI789"},
        ]

        detector = URLPatternDetector(min_pattern_count=3)
        patterns = detector.detect_patterns(pages)

        assert len(patterns) == 1
        assert patterns[0]["pattern"] == "/devices/{device_id}"

    def test_custom_min_pattern_count(self):
        """Test custom minimum pattern count."""
        pages = [
            {"url": "http://example.com/#!/devices/ABC123"},
            {"url": "http://example.com/#!/devices/DEF456"},
        ]

        # With min_count=2, should detect pattern
        detector = URLPatternDetector(min_pattern_count=2)
        patterns = detector.detect_patterns(pages)
        assert len(patterns) == 1

        # With min_count=3, should not detect pattern
        detector = URLPatternDetector(min_pattern_count=3)
        patterns = detector.detect_patterns(pages)
        assert len(patterns) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
