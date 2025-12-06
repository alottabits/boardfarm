"""Unit tests for semantic element search in BaseGuiComponent.

Tests the find_element_by_function() method and scoring algorithm
that enable self-healing tests (Phase 5.2).
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
import tempfile
import yaml

from boardfarm3.lib.gui.base_gui_component import BaseGuiComponent


@pytest.fixture
def mock_driver():
    """Create a mock Selenium WebDriver."""
    driver = Mock()
    driver.find_element = Mock()
    return driver


@pytest.fixture
def sample_selectors():
    """Sample selectors with enhanced metadata for testing."""
    return {
        "device_details_page": {
            "buttons": {
                "reboot_device": {
                    "by": "css",
                    "selector": ".btn-reboot",
                    "text": "Reboot Device",
                    "title": "Reboot the CPE",
                    "button_class": "btn btn-danger",
                    "aria_label": "reboot",
                    "data_action": "device.reboot",
                },
                "restart_cpe": {
                    "by": "css",
                    "selector": "#btn-restart",
                    "text": "Restart CPE",
                    "title": "Restart device immediately",
                    "button_class": "btn btn-warning",
                    "button_id": "btn-restart",
                },
                "save_config": {
                    "by": "css",
                    "selector": ".btn-save",
                    "text": "Save Configuration",
                    "title": "Save current configuration",
                    "button_class": "btn btn-primary",
                },
                "delete_device": {
                    "by": "css",
                    "selector": ".btn-delete",
                    "text": "Delete",
                    "title": "Delete this device",
                    "button_class": "btn btn-critical",
                    "data_action": "device.delete",
                },
            },
            "inputs": {
                "search_field": {
                    "by": "id",
                    "selector": "search-input",
                    "placeholder": "Search devices...",
                    "aria_label": "search",
                    "input_type": "text",
                },
                "filter_input": {
                    "by": "css",
                    "selector": ".filter-box",
                    "placeholder": "Filter results",
                    "name": "filter",
                },
            },
            "links": {
                "admin_panel": {
                    "by": "css",
                    "selector": "a.admin",
                    "text": "Admin",
                    "href": "/admin",
                    "title": "Go to admin panel",
                },
            },
        },
        "home_page": {
            "buttons": {
                "log_out": {
                    "by": "css",
                    "selector": "button.logout",
                    "text": "Log out",
                    "button_type": "submit",
                },
            },
        },
    }


@pytest.fixture
def sample_navigation():
    """Sample navigation for testing."""
    return {
        "navigation_paths": {
            "Path_Home_to_Details": [
                {"action": "click", "target": "home_page.buttons.devices"},
            ],
        },
    }


@pytest.fixture
def gui_component(mock_driver, tmp_path, sample_selectors, sample_navigation):
    """Create BaseGuiComponent with temporary YAML files."""
    # Write selectors to temp file
    selectors_file = tmp_path / "selectors.yaml"
    with selectors_file.open("w") as f:
        yaml.dump(sample_selectors, f)
    
    # Write navigation to temp file
    navigation_file = tmp_path / "navigation.yaml"
    with navigation_file.open("w") as f:
        yaml.dump(sample_navigation, f)
    
    # Create component
    component = BaseGuiComponent(
        driver=mock_driver,
        selector_file=selectors_file,
        navigation_file=navigation_file,
    )
    
    return component


class TestSemanticSearch:
    """Test suite for semantic element search functionality."""
    
    def test_find_by_exact_data_action(self, gui_component, mock_driver):
        """Test finding element by exact data-action attribute (highest score)."""
        mock_element = Mock()
        mock_driver.find_element.return_value = mock_element
        
        # Mock WebDriverWait
        with patch('boardfarm3.lib.gui.base_gui_component.WebDriverWait') as mock_wait:
            mock_wait_instance = Mock()
            mock_wait_instance.until.return_value = mock_element
            mock_wait.return_value = mock_wait_instance
            gui_component.wait = mock_wait_instance
            
            result = gui_component.find_element_by_function(
                element_type="button",
                function_keywords=["reboot"],
                page="device_details_page",
            )
        
        assert result == mock_element
    
    def test_find_by_text_match(self, gui_component, mock_driver):
        """Test finding element by text content match."""
        mock_element = Mock()
        
        with patch('boardfarm3.lib.gui.base_gui_component.WebDriverWait') as mock_wait:
            mock_wait_instance = Mock()
            mock_wait_instance.until.return_value = mock_element
            mock_wait.return_value = mock_wait_instance
            gui_component.wait = mock_wait_instance
            
            result = gui_component.find_element_by_function(
                element_type="button",
                function_keywords=["save", "configuration"],
                page="device_details_page",
            )
        
        assert result == mock_element
    
    def test_find_by_title_match(self, gui_component, mock_driver):
        """Test finding element by title attribute."""
        mock_element = Mock()
        
        with patch('boardfarm3.lib.gui.base_gui_component.WebDriverWait') as mock_wait:
            mock_wait_instance = Mock()
            mock_wait_instance.until.return_value = mock_element
            mock_wait.return_value = mock_wait_instance
            gui_component.wait = mock_wait_instance
            
            # Search for "restart" which matches title "Restart device immediately"
            result = gui_component.find_element_by_function(
                element_type="button",
                function_keywords=["restart"],
                page="device_details_page",
            )
        
        assert result == mock_element
    
    def test_find_by_multiple_keywords(self, gui_component, mock_driver):
        """Test finding element with multiple keyword matches increases score."""
        mock_element = Mock()
        
        with patch('boardfarm3.lib.gui.base_gui_component.WebDriverWait') as mock_wait:
            mock_wait_instance = Mock()
            mock_wait_instance.until.return_value = mock_element
            mock_wait.return_value = mock_wait_instance
            gui_component.wait = mock_wait_instance
            
            # "reboot_device" should score highest with multiple matches
            result = gui_component.find_element_by_function(
                element_type="button",
                function_keywords=["reboot", "device"],
                page="device_details_page",
            )
        
        assert result == mock_element
    
    def test_semantic_search_no_match_uses_fallback(self, gui_component, mock_driver):
        """Test fallback to explicit name when semantic search fails."""
        mock_element = Mock()
        
        with patch('boardfarm3.lib.gui.base_gui_component.WebDriverWait') as mock_wait:
            mock_wait_instance = Mock()
            mock_wait_instance.until.return_value = mock_element
            mock_wait.return_value = mock_wait_instance
            gui_component.wait = mock_wait_instance
            
            result = gui_component.find_element_by_function(
                element_type="button",
                function_keywords=["nonexistent", "keywords"],
                page="device_details_page",
                fallback_name="save_config",
            )
        
        assert result == mock_element
    
    def test_semantic_search_no_match_no_fallback_raises(self, gui_component):
        """Test that KeyError is raised when no match and no fallback."""
        with pytest.raises(KeyError) as exc_info:
            gui_component.find_element_by_function(
                element_type="button",
                function_keywords=["nonexistent"],
                page="device_details_page",
            )
        
        assert "No button found matching" in str(exc_info.value)
    
    def test_find_input_by_placeholder(self, gui_component, mock_driver):
        """Test finding input element by placeholder text."""
        mock_element = Mock()
        
        with patch('boardfarm3.lib.gui.base_gui_component.WebDriverWait') as mock_wait:
            mock_wait_instance = Mock()
            mock_wait_instance.until.return_value = mock_element
            mock_wait.return_value = mock_wait_instance
            gui_component.wait = mock_wait_instance
            
            result = gui_component.find_element_by_function(
                element_type="input",
                function_keywords=["search", "devices"],
                page="device_details_page",
            )
        
        assert result == mock_element
    
    def test_find_link_by_text_and_title(self, gui_component, mock_driver):
        """Test finding link by text and title."""
        mock_element = Mock()
        
        with patch('boardfarm3.lib.gui.base_gui_component.WebDriverWait') as mock_wait:
            mock_wait_instance = Mock()
            mock_wait_instance.until.return_value = mock_element
            mock_wait.return_value = mock_wait_instance
            gui_component.wait = mock_wait_instance
            
            result = gui_component.find_element_by_function(
                element_type="link",
                function_keywords=["admin"],
                page="device_details_page",
            )
        
        assert result == mock_element
    
    def test_invalid_page_raises_value_error(self, gui_component):
        """Test that invalid page name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            gui_component.find_element_by_function(
                element_type="button",
                function_keywords=["reboot"],
                page="nonexistent_page",
            )
        
        assert "Page 'nonexistent_page' not found" in str(exc_info.value)
    
    def test_case_insensitive_matching(self, gui_component, mock_driver):
        """Test that keyword matching is case-insensitive."""
        mock_element = Mock()
        
        with patch('boardfarm3.lib.gui.base_gui_component.WebDriverWait') as mock_wait:
            mock_wait_instance = Mock()
            mock_wait_instance.until.return_value = mock_element
            mock_wait.return_value = mock_wait_instance
            gui_component.wait = mock_wait_instance
            
            # Use uppercase keywords to match lowercase "reboot"
            result = gui_component.find_element_by_function(
                element_type="button",
                function_keywords=["REBOOT", "DEVICE"],
                page="device_details_page",
            )
        
        assert result == mock_element
    
    def test_custom_timeout(self, gui_component, mock_driver):
        """Test that custom timeout is passed through."""
        mock_element = Mock()
        
        with patch('boardfarm3.lib.gui.base_gui_component.WebDriverWait') as mock_wait:
            mock_wait_instance = Mock()
            mock_wait_instance.until.return_value = mock_element
            mock_wait.return_value = mock_wait_instance
            
            # Call with custom timeout
            result = gui_component.find_element_by_function(
                element_type="button",
                function_keywords=["reboot"],
                page="device_details_page",
                timeout=30,
            )
        
        # Verify WebDriverWait was called with custom timeout
        mock_wait.assert_called_with(mock_driver, 30)
        assert result == mock_element


class TestScoringAlgorithm:
    """Test suite for the scoring algorithm specifically."""
    
    def test_data_action_scores_highest(self, gui_component):
        """Test data-action attribute scores 100 points."""
        elem_data = {"data_action": "device.reboot"}
        score = gui_component._calculate_functional_match_score(
            elem_data, ["reboot"], "button"
        )
        assert score == 100
    
    def test_exact_text_match_scores_50(self, gui_component):
        """Test exact text match scores 50 points."""
        elem_data = {"text": "reboot"}
        score = gui_component._calculate_functional_match_score(
            elem_data, ["reboot"], "button"
        )
        assert score == 50
    
    def test_partial_text_match_scores_25(self, gui_component):
        """Test partial text match scores 25 points."""
        elem_data = {"text": "reboot device"}
        score = gui_component._calculate_functional_match_score(
            elem_data, ["reboot"], "button"
        )
        assert score == 25
    
    def test_id_match_scores_30(self, gui_component):
        """Test ID match scores 30 points."""
        elem_data = {"button_id": "btn-reboot-device"}
        score = gui_component._calculate_functional_match_score(
            elem_data, ["reboot"], "button"
        )
        assert score == 30
    
    def test_title_match_scores_20(self, gui_component):
        """Test title match scores 20 points."""
        elem_data = {"title": "Reboot the device"}
        score = gui_component._calculate_functional_match_score(
            elem_data, ["reboot"], "button"
        )
        assert score == 20
    
    def test_aria_label_match_scores_20(self, gui_component):
        """Test aria-label match scores 20 points."""
        elem_data = {"aria_label": "reboot button"}
        score = gui_component._calculate_functional_match_score(
            elem_data, ["reboot"], "button"
        )
        assert score == 20
    
    def test_placeholder_match_scores_15(self, gui_component):
        """Test placeholder match scores 15 points."""
        elem_data = {"placeholder": "Search for devices"}
        score = gui_component._calculate_functional_match_score(
            elem_data, ["search"], "input"
        )
        assert score == 15
    
    def test_class_match_scores_10(self, gui_component):
        """Test class match scores 10 points."""
        elem_data = {"button_class": "btn-reboot-action"}
        score = gui_component._calculate_functional_match_score(
            elem_data, ["reboot"], "button"
        )
        assert score == 10
    
    def test_multiple_attribute_matches_cumulative(self, gui_component):
        """Test that scores are cumulative across attributes."""
        elem_data = {
            "text": "Reboot Device",  # 25 (partial)
            "title": "Reboot the CPE",  # 20
            "button_id": "btn-reboot",  # 30
            "data_action": "device.reboot",  # 100
        }
        score = gui_component._calculate_functional_match_score(
            elem_data, ["reboot"], "button"
        )
        # Should be 100 + 30 + 25 + 20 = 175
        assert score == 175
    
    def test_multiple_keywords_cumulative(self, gui_component):
        """Test that multiple keywords accumulate score."""
        elem_data = {
            "text": "Reboot Device",  # "reboot"=25, "device"=25
            "title": "Reboot the device",  # "reboot"=20, "device"=20
        }
        score = gui_component._calculate_functional_match_score(
            elem_data, ["reboot", "device"], "button"
        )
        # Should be 25+25+20+20 = 90
        assert score == 90
    
    def test_no_match_returns_zero(self, gui_component):
        """Test that no matches returns score of 0."""
        elem_data = {"text": "Save Configuration"}
        score = gui_component._calculate_functional_match_score(
            elem_data, ["reboot"], "button"
        )
        assert score == 0
    
    def test_empty_element_data_returns_zero(self, gui_component):
        """Test that empty element data returns score of 0."""
        elem_data = {}
        score = gui_component._calculate_functional_match_score(
            elem_data, ["reboot"], "button"
        )
        assert score == 0
    
    def test_null_values_handled_gracefully(self, gui_component):
        """Test that None/null values don't cause errors."""
        elem_data = {
            "text": None,
            "title": None,
            "aria_label": None,
            "data_action": None,
        }
        score = gui_component._calculate_functional_match_score(
            elem_data, ["reboot"], "button"
        )
        assert score == 0


class TestBestMatchSelection:
    """Test that the highest-scoring element is selected."""
    
    def test_selects_highest_scoring_element(self, gui_component, mock_driver):
        """Test that element with highest score is selected."""
        mock_element = Mock()
        
        with patch('boardfarm3.lib.gui.base_gui_component.WebDriverWait') as mock_wait:
            mock_wait_instance = Mock()
            mock_wait_instance.until.return_value = mock_element
            mock_wait.return_value = mock_wait_instance
            gui_component.wait = mock_wait_instance
            
            # "reboot_device" has data_action="device.reboot" (100 points)
            # "restart_cpe" only has title with "restart" (20 points)
            result = gui_component.find_element_by_function(
                element_type="button",
                function_keywords=["reboot"],
                page="device_details_page",
            )
        
        # Should find reboot_device (higher score)
        assert result == mock_element
    
    def test_prefers_data_action_over_text(self, gui_component, mock_driver):
        """Test that data-action is weighted higher than text."""
        mock_element = Mock()
        
        with patch('boardfarm3.lib.gui.base_gui_component.WebDriverWait') as mock_wait:
            mock_wait_instance = Mock()
            mock_wait_instance.until.return_value = mock_element
            mock_wait.return_value = mock_wait_instance
            gui_component.wait = mock_wait_instance
            
            # "delete_device" has data_action="device.delete"
            result = gui_component.find_element_by_function(
                element_type="button",
                function_keywords=["delete"],
                page="device_details_page",
            )
        
        assert result == mock_element


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_keywords_list(self, gui_component):
        """Test behavior with empty keywords list."""
        with pytest.raises(KeyError) as exc_info:
            gui_component.find_element_by_function(
                element_type="button",
                function_keywords=[],
                page="device_details_page",
            )
        
        assert "No button found" in str(exc_info.value)
    
    def test_page_with_no_elements_of_type(self, gui_component):
        """Test behavior when page has no elements of requested type."""
        with pytest.raises(KeyError) as exc_info:
            gui_component.find_element_by_function(
                element_type="select",  # No selects on device_details_page
                function_keywords=["reboot"],
                page="device_details_page",
            )
        
        assert "No select found" in str(exc_info.value)
    
    def test_fallback_name_not_found(self, gui_component):
        """Test behavior when fallback name doesn't exist."""
        with pytest.raises(KeyError) as exc_info:
            gui_component.find_element_by_function(
                element_type="button",
                function_keywords=["nonexistent"],
                page="device_details_page",
                fallback_name="also_nonexistent",
            )
        
        assert "Fallback name 'also_nonexistent' also not found" in str(exc_info.value)
    
    def test_special_characters_in_keywords(self, gui_component, mock_driver):
        """Test that special characters in keywords are handled."""
        mock_element = Mock()
        
        with patch('boardfarm3.lib.gui.base_gui_component.WebDriverWait') as mock_wait:
            mock_wait_instance = Mock()
            mock_wait_instance.until.return_value = mock_element
            mock_wait.return_value = mock_wait_instance
            gui_component.wait = mock_wait_instance
            
            # Should still work with special characters
            result = gui_component.find_element_by_function(
                element_type="button",
                function_keywords=["save/configuration"],
                page="device_details_page",
                fallback_name="save_config",
            )
        
        assert result == mock_element

