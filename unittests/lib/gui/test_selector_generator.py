"""Unit tests for SelectorGenerator.

Tests the conversion of UI discovery JSON to selectors.yaml format.
"""

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from boardfarm3.lib.gui.selector_generator import SelectorGenerator


@pytest.fixture
def sample_discovery_data():
    """Sample UI discovery data for testing."""
    return {
        "base_url": "http://127.0.0.1:3000",
        "pages": [
            {
                "url": "http://127.0.0.1:3000/#!/overview",
                "title": "Overview - GenieACS",
                "page_type": "home",
                "buttons": [
                    {
                        "text": "Log out",
                        "title": "Log out",
                        "id": "logout-btn",
                        "class": "btn btn-link",
                        "css_selector": "#logout-btn",
                    },
                    {
                        "text": "Refresh",
                        "title": "Refresh page",
                        "id": "",
                        "class": "btn btn-primary",
                        "css_selector": "button.btn-primary",
                    },
                ],
                "inputs": [
                    {
                        "type": "text",
                        "name": "search",
                        "id": "search-input",
                        "placeholder": "Search...",
                        "css_selector": "#search-input",
                    }
                ],
                "links": [
                    {
                        "text": "Devices",
                        "href": "http://127.0.0.1:3000/#!/devices",
                        "css_selector": "a[href='#!/devices']",
                    },
                    {
                        "text": "Presets",
                        "href": "http://127.0.0.1:3000/#!/admin/presets",
                        "css_selector": "a[href='#!/admin/presets']",
                    },
                ],
                "tables": [
                    {
                        "id": "device-table",
                        "class": "table",
                        "headers": ["ID", "Serial", "Status"],
                        "css_selector": "#device-table",
                    }
                ],
            },
            {
                "url": "http://127.0.0.1:3000/#!/devices",
                "title": "Devices - GenieACS",
                "page_type": "device_list",
                "buttons": [
                    {
                        "text": "Add Device",
                        "title": "",
                        "id": "add-device-btn",
                        "class": "btn btn-success",
                        "css_selector": "#add-device-btn",
                    }
                ],
                "inputs": [
                    {
                        "type": "text",
                        "name": "filter",
                        "id": "device-filter",
                        "placeholder": "Filter devices",
                        "css_selector": "#device-filter",
                    }
                ],
                "links": [],
                "tables": [],
                "interactions": [
                    {
                        "trigger": {
                            "type": "button",
                            "text": "New",
                            "selector": "button.primary",
                        },
                        "result": {
                            "type": "modal",
                            "title": "New Device",
                            "css_selector": ".modal",
                            "buttons": [
                                {
                                    "text": "Save",
                                    "type": "submit",
                                    "class": "btn btn-primary",
                                    "css_selector": "button[type='submit']",
                                },
                                {
                                    "text": "Cancel",
                                    "type": "button",
                                    "class": "btn btn-secondary",
                                    "css_selector": "button.cancel",
                                },
                            ],
                            "inputs": [
                                {
                                    "type": "text",
                                    "name": "serial",
                                    "placeholder": "Device serial number",
                                    "required": True,
                                    "css_selector": "input[name='serial']",
                                }
                            ],
                            "selects": [
                                {
                                    "name": "model",
                                    "options": ["Model A", "Model B", "Model C"],
                                    "css_selector": "select[name='model']",
                                }
                            ],
                        },
                    }
                ],
            },
        ],
        "url_patterns": [],
        "navigation_graph": {},
    }


@pytest.fixture
def temp_discovery_file(sample_discovery_data):
    """Create a temporary discovery JSON file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sample_discovery_data, f)
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    Path(temp_path).unlink(missing_ok=True)


class TestSelectorGenerator:
    """Test suite for SelectorGenerator."""

    def test_initialization(self, temp_discovery_file):
        """Test generator initialization."""
        generator = SelectorGenerator(temp_discovery_file)
        
        assert generator.discovery_data is not None
        assert len(generator.discovery_data["pages"]) == 2
        assert generator.selectors == {}

    def test_generate_page_key_from_page_type(self, temp_discovery_file):
        """Test page key generation from page_type."""
        generator = SelectorGenerator(temp_discovery_file)
        
        page = {"page_type": "home", "url": "http://example.com"}
        page_key = generator._generate_page_key(page)
        
        assert page_key == "home_page"

    def test_generate_page_key_from_url(self, temp_discovery_file):
        """Test page key generation from URL when page_type is unknown."""
        generator = SelectorGenerator(temp_discovery_file)
        
        page = {
            "page_type": "unknown",
            "url": "http://127.0.0.1:3000/#!/admin/settings",
        }
        page_key = generator._generate_page_key(page)
        
        assert page_key == "admin_page"

    def test_sanitize_name(self, temp_discovery_file):
        """Test name sanitization."""
        generator = SelectorGenerator(temp_discovery_file)
        
        assert generator._sanitize_name("Log Out") == "log_out"
        assert generator._sanitize_name("Device List") == "device_list"
        assert generator._sanitize_name("Add/Edit") == "addedit"
        assert generator._sanitize_name("Save & Close") == "save_close"
        assert generator._sanitize_name("  spaces  ") == "spaces"

    def test_generate_element_name_from_text(self, temp_discovery_file):
        """Test element name generation from text."""
        generator = SelectorGenerator(temp_discovery_file)
        
        element = {"text": "Log out", "css_selector": "#logout"}
        name = generator._generate_element_name(element, "button")
        
        assert name == "log_out"

    def test_generate_element_name_from_name_attribute(self, temp_discovery_file):
        """Test element name generation from name attribute."""
        generator = SelectorGenerator(temp_discovery_file)
        
        element = {"name": "username", "type": "text", "css_selector": "input[name='username']"}
        name = generator._generate_element_name(element, "input")
        
        assert name == "username"

    def test_generate_element_name_fallback(self, temp_discovery_file):
        """Test element name generation fallback to default."""
        generator = SelectorGenerator(temp_discovery_file)
        
        element = {"css_selector": ".btn"}
        name = generator._generate_element_name(element, "button")
        
        assert name == "button"

    def test_create_selector_entry_with_id(self, temp_discovery_file):
        """Test selector entry creation for ID-based selector."""
        generator = SelectorGenerator(temp_discovery_file)
        
        element = {"css_selector": "#login-button"}
        entry = generator._create_selector_entry(element)
        
        assert entry["by"] == "id"
        assert entry["selector"] == "login-button"

    def test_create_selector_entry_with_css(self, temp_discovery_file):
        """Test selector entry creation for CSS selector."""
        generator = SelectorGenerator(temp_discovery_file)
        
        element = {"css_selector": "button.primary"}
        entry = generator._create_selector_entry(element)
        
        assert entry["by"] == "css_selector"
        assert entry["selector"] == "button.primary"

    def test_create_selector_entry_with_xpath(self, temp_discovery_file):
        """Test selector entry creation for XPath selector."""
        generator = SelectorGenerator(temp_discovery_file)
        
        element = {"css_selector": "//button[@type='submit']"}
        entry = generator._create_selector_entry(element)
        
        assert entry["by"] == "xpath"
        assert entry["selector"] == "//button[@type='submit']"

    def test_process_buttons(self, temp_discovery_file):
        """Test button processing."""
        generator = SelectorGenerator(temp_discovery_file)
        generator.generate()
        
        # Check home page buttons
        assert "home_page" in generator.selectors
        assert "buttons" in generator.selectors["home_page"]
        
        buttons = generator.selectors["home_page"]["buttons"]
        assert "log_out" in buttons
        assert buttons["log_out"]["by"] == "id"
        assert buttons["log_out"]["selector"] == "logout-btn"

    def test_process_inputs(self, temp_discovery_file):
        """Test input field processing."""
        generator = SelectorGenerator(temp_discovery_file)
        generator.generate()
        
        # Check home page inputs
        assert "inputs" in generator.selectors["home_page"]
        
        inputs = generator.selectors["home_page"]["inputs"]
        assert "search" in inputs
        assert inputs["search"]["by"] == "id"
        assert inputs["search"]["selector"] == "search-input"

    def test_process_links(self, temp_discovery_file):
        """Test link processing."""
        generator = SelectorGenerator(temp_discovery_file)
        generator.generate()
        
        # Check home page links
        assert "links" in generator.selectors["home_page"]
        
        links = generator.selectors["home_page"]["links"]
        assert "devices" in links
        assert "presets" in links

    def test_process_tables(self, temp_discovery_file):
        """Test table processing."""
        generator = SelectorGenerator(temp_discovery_file)
        generator.generate()
        
        # Check home page tables
        assert "tables" in generator.selectors["home_page"]
        
        tables = generator.selectors["home_page"]["tables"]
        assert "device_table" in tables
        assert tables["device_table"]["by"] == "id"
        assert tables["device_table"]["headers"] == ["ID", "Serial", "Status"]

    def test_process_interactions(self, temp_discovery_file):
        """Test modal/interaction processing."""
        generator = SelectorGenerator(temp_discovery_file)
        generator.generate()
        
        # Check device_list page modals
        assert "device_list_page" in generator.selectors
        assert "modals" in generator.selectors["device_list_page"]
        
        modals = generator.selectors["device_list_page"]["modals"]
        assert "new_device" in modals
        
        modal = modals["new_device"]
        assert "container" in modal
        assert "buttons" in modal
        assert "inputs" in modal
        assert "selects" in modal
        
        # Check modal buttons
        assert "save" in modal["buttons"]
        assert "cancel" in modal["buttons"]
        
        # Check modal inputs
        assert "serial" in modal["inputs"]
        
        # Check modal selects with options
        assert "model" in modal["selects"]
        assert modal["selects"]["model"]["options"] == ["Model A", "Model B", "Model C"]

    def test_generate_creates_all_pages(self, temp_discovery_file):
        """Test that generate processes all pages."""
        generator = SelectorGenerator(temp_discovery_file)
        result = generator.generate()
        
        assert len(result) == 2
        assert "home_page" in result
        assert "device_list_page" in result

    def test_save_yaml(self, temp_discovery_file):
        """Test YAML file saving."""
        generator = SelectorGenerator(temp_discovery_file)
        generator.generate()
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            output_path = f.name
        
        try:
            generator.save_yaml(output_path)
            
            # Verify file exists
            assert Path(output_path).exists()
            
            # Verify file can be loaded as YAML
            with open(output_path) as f:
                loaded_data = yaml.safe_load(f)
            
            assert "home_page" in loaded_data
            assert "device_list_page" in loaded_data
            
            # Verify structure
            assert "buttons" in loaded_data["home_page"]
            assert "modals" in loaded_data["device_list_page"]
            
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_empty_page_handling(self, temp_discovery_file):
        """Test handling of pages with no elements."""
        generator = SelectorGenerator(temp_discovery_file)
        
        # Add a page with no elements
        empty_page = {
            "url": "http://127.0.0.1:3000/#!/empty",
            "title": "Empty Page",
            "page_type": "empty",
            "buttons": [],
            "inputs": [],
            "links": [],
            "tables": [],
        }
        generator.discovery_data["pages"].append(empty_page)
        
        generator.generate()
        
        # Empty page should still be in selectors but with no element groups
        assert "empty_page" in generator.selectors
        # But it should be an empty dict (or only have metadata)
        assert generator.selectors["empty_page"] == {}

    def test_duplicate_element_names(self, temp_discovery_file):
        """Test handling of elements with duplicate names."""
        generator = SelectorGenerator(temp_discovery_file)
        
        # Add a page with duplicate button texts
        page_with_dupes = {
            "url": "http://127.0.0.1:3000/#!/test",
            "title": "Test Page",
            "page_type": "test",
            "buttons": [
                {"text": "Submit", "css_selector": "#submit1"},
                {"text": "Submit", "css_selector": "#submit2"},
            ],
            "inputs": [],
            "links": [],
            "tables": [],
        }
        generator.discovery_data["pages"].append(page_with_dupes)
        
        generator.generate()
        
        # Both buttons should be processed (last one wins for now)
        assert "test_page" in generator.selectors
        assert "buttons" in generator.selectors["test_page"]
        assert "submit" in generator.selectors["test_page"]["buttons"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

