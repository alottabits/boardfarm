"""Unit tests for stale element handling in ui_discovery.py

These tests verify that the UI discovery tool gracefully handles
StaleElementReferenceException errors that commonly occur in SPAs.
"""

import pytest
from unittest.mock import Mock, MagicMock, PropertyMock, patch
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.remote.webelement import WebElement

from boardfarm3.lib.gui.ui_discovery import UIDiscoveryTool


class TestStaleElementHandling:
    """Test stale element reference exception handling."""
    
    @patch('boardfarm3.lib.gui.ui_discovery.Firefox')
    def setup_method(self, method, mock_firefox):
        """Set up test fixtures."""
        
        # Create a mock driver
        self.mock_driver = Mock()
        mock_firefox.return_value = self.mock_driver
        
        # Create tool instance
        self.tool = UIDiscoveryTool(
            base_url="http://test.local",
            username="test",
            password="test",
            headless=True
        )
        self.tool.driver = self.mock_driver
        
    def test_find_navigation_links_with_stale_element(self):
        """Test that _find_navigation_links handles stale elements gracefully."""
        # Create mock link elements
        good_link = Mock(spec=WebElement)
        good_link.get_attribute.return_value = "http://test.local/page1"
        good_link.text = "Page 1"
        
        stale_link = Mock(spec=WebElement)
        stale_link.get_attribute.side_effect = StaleElementReferenceException("Element is stale")
        
        another_good_link = Mock(spec=WebElement)
        another_good_link.get_attribute.return_value = "http://test.local/page2"
        another_good_link.text = "Page 2"
        
        # Mock driver to return mix of good and stale elements
        self.mock_driver.find_elements.return_value = [
            good_link,
            stale_link,
            another_good_link
        ]
        
        # Call method
        links = self.tool._find_navigation_links()
        
        # Should return 2 links, skipping the stale one
        assert len(links) == 2
        assert links[0]["text"] == "Page 1"
        assert links[0]["href"] == "http://test.local/page1"
        assert links[1]["text"] == "Page 2"
        assert links[1]["href"] == "http://test.local/page2"
        
    def test_discover_buttons_with_stale_element(self):
        """Test that _discover_buttons handles stale elements gracefully."""
        # Create mock button elements
        good_button = Mock(spec=WebElement)
        good_button.text = "Save"
        good_button.get_attribute.return_value = "btn-save"
        
        stale_button = Mock(spec=WebElement)
        # Use PropertyMock to make accessing .text raise StaleElementReferenceException
        type(stale_button).text = PropertyMock(side_effect=StaleElementReferenceException("Element is stale"))
        
        another_good_button = Mock(spec=WebElement)
        another_good_button.text = "Cancel"
        another_good_button.get_attribute.return_value = "btn-cancel"
        
        # Mock driver
        self.mock_driver.find_elements.return_value = [
            good_button,
            stale_button,
            another_good_button
        ]
        
        # Call method
        buttons = self.tool._discover_buttons()
        
        # Should return 2 buttons, skipping the stale one
        assert len(buttons) == 2
        assert buttons[0]["text"] == "Save"
        assert buttons[1]["text"] == "Cancel"
        
    def test_discover_inputs_with_stale_element(self):
        """Test that _discover_inputs handles stale elements gracefully."""
        # Create mock input elements
        good_input = Mock(spec=WebElement)
        good_input.get_attribute.side_effect = lambda attr: {
            "type": "text",
            "name": "username",
            "id": "input-username",
            "placeholder": "Enter username"
        }.get(attr)
        
        stale_input = Mock(spec=WebElement)
        stale_input.get_attribute.side_effect = StaleElementReferenceException("Element is stale")
        
        another_good_input = Mock(spec=WebElement)
        another_good_input.get_attribute.side_effect = lambda attr: {
            "type": "password",
            "name": "password",
            "id": "input-password",
            "placeholder": "Enter password"
        }.get(attr)
        
        # Mock driver
        self.mock_driver.find_elements.return_value = [
            good_input,
            stale_input,
            another_good_input
        ]
        
        # Call method
        inputs = self.tool._discover_inputs()
        
        # Should return 2 inputs, skipping the stale one
        assert len(inputs) == 2
        assert inputs[0]["name"] == "username"
        assert inputs[1]["name"] == "password"
        
    def test_discover_links_with_stale_element(self):
        """Test that _discover_links handles stale elements gracefully."""
        # Create mock link elements
        good_link = Mock(spec=WebElement)
        good_link.get_attribute.return_value = "http://test.local/about"
        good_link.text = "About"
        
        stale_link = Mock(spec=WebElement)
        stale_link.get_attribute.side_effect = StaleElementReferenceException("Element is stale")
        
        another_good_link = Mock(spec=WebElement)
        another_good_link.get_attribute.return_value = "http://test.local/contact"
        another_good_link.text = "Contact"
        
        # Mock driver
        self.mock_driver.find_elements.return_value = [
            good_link,
            stale_link,
            another_good_link
        ]
        
        # Call method
        links = self.tool._discover_links()
        
        # Should return 2 links, skipping the stale one
        assert len(links) == 2
        assert links[0]["text"] == "About"
        assert links[0]["href"] == "http://test.local/about"
        assert links[1]["text"] == "Contact"
        assert links[1]["href"] == "http://test.local/contact"
        
    def test_all_elements_stale(self):
        """Test behavior when all elements are stale."""
        # All elements raise StaleElementReferenceException
        stale_element = Mock(spec=WebElement)
        stale_element.get_attribute.side_effect = StaleElementReferenceException("Element is stale")
        
        self.mock_driver.find_elements.return_value = [
            stale_element,
            stale_element,
            stale_element
        ]
        
        # Should return empty list, not raise exception
        links = self.tool._find_navigation_links()
        assert links == []
        
        buttons = self.tool._discover_buttons()
        assert buttons == []
        
        inputs = self.tool._discover_inputs()
        assert inputs == []
        
    def test_no_elements(self):
        """Test behavior when no elements are found."""
        self.mock_driver.find_elements.return_value = []
        
        # Should return empty lists without error
        assert self.tool._find_navigation_links() == []
        assert self.tool._discover_buttons() == []
        assert self.tool._discover_inputs() == []
        assert self.tool._discover_links() == []
        
    def test_mixed_errors(self):
        """Test handling of both stale elements and other exceptions."""
        good_link = Mock(spec=WebElement)
        good_link.get_attribute.return_value = "http://test.local/page1"
        good_link.text = "Page 1"
        
        stale_link = Mock(spec=WebElement)
        stale_link.get_attribute.side_effect = StaleElementReferenceException("Stale")
        
        error_link = Mock(spec=WebElement)
        error_link.get_attribute.side_effect = RuntimeError("Some other error")
        
        another_good_link = Mock(spec=WebElement)
        another_good_link.get_attribute.return_value = "http://test.local/page2"
        another_good_link.text = "Page 2"
        
        self.mock_driver.find_elements.return_value = [
            good_link,
            stale_link,
            error_link,
            another_good_link
        ]
        
        # Should skip both error elements and return the 2 good ones
        links = self.tool._find_navigation_links()
        assert len(links) == 2
        assert links[0]["text"] == "Page 1"
        assert links[1]["text"] == "Page 2"


class TestSPAStabilizationWait:
    """Test the SPA stabilization wait after navigation."""
    
    @patch('boardfarm3.lib.gui.ui_discovery.time.sleep')
    @patch('boardfarm3.lib.gui.ui_discovery.Firefox')
    def test_spa_wait_after_navigation(self, mock_firefox, mock_sleep):
        """Test that a stabilization wait occurs after page navigation."""
        # Create mock driver
        mock_driver = Mock()
        mock_driver.execute_script.return_value = "complete"
        mock_firefox.return_value = mock_driver
        
        # Create tool
        tool = UIDiscoveryTool(
            base_url="http://test.local",
            username="test",
            password="test",
            headless=True
        )
        tool.driver = mock_driver
        tool.wait = Mock()
        tool.wait.until = Mock()
        
        # Mock the methods that would be called during crawl
        tool._discover_page_info = Mock(return_value={
            "url": "http://test.local/page1",
            "title": "Page 1",
            "page_type": "home",
            "buttons": [],
            "inputs": [],
            "links": [],
            "tables": []
        })
        tool._find_navigation_links = Mock(return_value=[])
        
        # Call _crawl_page
        tool._crawl_page("http://test.local/page1", depth=0, max_depth=1)
        
        # Verify sleep was called (for SPA stabilization)
        # Note: sleep might be called multiple times in the method
        assert mock_sleep.called
        # Check that 0.5 was one of the sleep durations
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        assert 0.5 in sleep_calls


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

