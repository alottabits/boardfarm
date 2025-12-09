"""Unit tests for BaseGuiComponent with ui_map.json."""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock
from boardfarm3.lib.gui.base_gui_component import BaseGuiComponent


@pytest.fixture
def sample_ui_graph(tmp_path):
    """Create a sample ui_map.json for testing."""
    graph = {
        "base_url": "http://test.com",
        "discovery_method": "breadth_first_search",
        "graph": {
            "directed": True,
            "multigraph": False,
            "nodes": [
                {
                    "node_type": "Page",
                    "page_type": "home",
                    "title": "Home",
                    "friendly_name": "home_page",
                    "id": "http://test.com/#!/home"
                },
                {
                    "node_type": "Page",
                    "page_type": "login",
                    "title": "Login",
                    "friendly_name": "login_page",
                    "id": "http://test.com/#!/login"
                },
                {
                    "node_type": "Page",
                    "page_type": "device_list",
                    "title": "Devices",
                    "friendly_name": "device_list_page",
                    "id": "http://test.com/#!/devices"
                },
                {
                    "node_type": "Element",
                    "element_type": "button",
                    "text": "Log out",
                    "locator_type": "css",
                    "locator_value": "button.logout",
                    "button_type": "button",
                    "friendly_name": "log_out_button",
                    "id": "elem_btn_1"
                },
                {
                    "node_type": "Element",
                    "element_type": "input",
                    "name": "username",
                    "input_type": "text",
                    "locator_type": "css",
                    "locator_value": "input[name='username']",
                    "friendly_name": "username_input",
                    "id": "elem_input_1"
                },
                {
                    "node_type": "Element",
                    "element_type": "input",
                    "name": "password",
                    "input_type": "password",
                    "locator_type": "css",
                    "locator_value": "input[name='password']",
                    "friendly_name": "password_input",
                    "id": "elem_input_2"
                },
                {
                    "node_type": "Element",
                    "element_type": "link",
                    "text": "Devices",
                    "locator_type": "css",
                    "locator_value": "a.devices",
                    "friendly_name": "devices_link",
                    "id": "elem_link_1"
                }
            ],
            "edges": [
                {
                    "edge_type": "ON_PAGE",
                    "source": "elem_btn_1",
                    "target": "http://test.com/#!/home"
                },
                {
                    "edge_type": "ON_PAGE",
                    "source": "elem_link_1",
                    "target": "http://test.com/#!/home"
                },
                {
                    "edge_type": "ON_PAGE",
                    "source": "elem_input_1",
                    "target": "http://test.com/#!/login"
                },
                {
                    "edge_type": "ON_PAGE",
                    "source": "elem_input_2",
                    "target": "http://test.com/#!/login"
                },
                {
                    "edge_type": "MAPS_TO",
                    "source": "http://test.com/#!/home",
                    "target": "http://test.com/#!/devices",
                    "via_element": "elem_link_1",
                    "action": "click"
                }
            ]
        }
    }
    
    graph_file = tmp_path / "ui_map.json"
    with graph_file.open('w') as f:
        json.dump(graph, f)
        
    return graph_file


def test_load_ui_graph(sample_ui_graph):
    """Test loading and parsing ui_map.json."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Verify pages loaded
    assert len(component._pages) == 3
    assert len(component._page_name_to_url) == 3
    assert 'home_page' in component._page_name_to_url
    assert 'login_page' in component._page_name_to_url
    assert 'device_list_page' in component._page_name_to_url
    
    # Verify elements loaded
    assert len(component._elements) == 4
    
    # Verify transitions loaded
    assert len(component._transitions) == 1
    
    # Verify element containment
    home_url = component._page_name_to_url['home_page']
    home_elements = component._elements_by_page[home_url]
    assert 'log_out_button' in home_elements
    assert 'devices_link' in home_elements


def test_page_name_mapping(sample_ui_graph):
    """Test URL to friendly page name mapping."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Check bi-directional mapping
    assert component._page_name_to_url['home_page'] == "http://test.com/#!/home"
    assert component._url_to_page_name["http://test.com/#!/home"] == 'home_page'
    
    assert component._page_name_to_url['login_page'] == "http://test.com/#!/login"
    assert component._url_to_page_name["http://test.com/#!/login"] == 'login_page'


def test_element_name_generation(sample_ui_graph):
    """Test element friendly name generation."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    home_url = component._page_name_to_url['home_page']
    home_elements = component._elements_by_page[home_url]
    
    # Button with text "Log out" → "log_out_button"
    assert 'log_out_button' in home_elements
    
    # Link with text "Devices" → "devices_link"
    assert 'devices_link' in home_elements


def test_state_tracking(sample_ui_graph):
    """Test state tracking functionality."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Initial state
    assert component.get_state() is None
    
    # Set state
    component.set_state('home_page', via_action='initialize')
    assert component.get_state() == 'home_page'
    assert component._current_url == "http://test.com/#!/home"
    
    # Transition
    component.set_state('device_list_page', via_action='click_link')
    assert component.get_state() == 'device_list_page'
    
    # Check history
    history = component.get_state_history()
    assert len(history) == 2
    assert history[0]['to'] == 'home_page'
    assert history[0]['via'] == 'initialize'
    assert history[1]['to'] == 'device_list_page'
    assert history[1]['via'] == 'click_link'


def test_list_page_elements(sample_ui_graph):
    """Test listing elements on a page."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Home page elements
    home_elements = component.list_page_elements('home_page')
    assert 'log_out_button' in home_elements
    assert 'devices_link' in home_elements
    assert len(home_elements) == 2
    
    # Login page elements
    login_elements = component.list_page_elements('login_page')
    assert 'username_input' in login_elements
    assert 'password_input' in login_elements
    assert len(login_elements) == 2


def test_find_element(sample_ui_graph):
    """Test finding element by page state and name."""
    # Create mock driver and element
    driver = Mock()
    mock_element = Mock()
    
    # Mock WebDriverWait behavior
    driver.find_element.return_value = mock_element
    
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Mock the wait.until to return our mock element
    component.wait = Mock()
    component.wait.until = Mock(return_value=mock_element)
    
    # Find element
    element = component.find_element('home_page', 'log_out_button')
    
    # Verify element was found
    assert element == mock_element
    component.wait.until.assert_called_once()


def test_find_element_not_found_page(sample_ui_graph):
    """Test finding element on non-existent page raises KeyError."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    with pytest.raises(KeyError) as excinfo:
        component.find_element('nonexistent_page', 'some_button')
    
    assert "Page 'nonexistent_page' not found" in str(excinfo.value)


def test_find_element_not_found_element(sample_ui_graph):
    """Test finding non-existent element on page raises KeyError."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    with pytest.raises(KeyError) as excinfo:
        component.find_element('home_page', 'nonexistent_button')
    
    assert "Element 'nonexistent_button' not found" in str(excinfo.value)


def test_missing_graph_file():
    """Test that missing graph file raises FileNotFoundError."""
    driver = Mock()
    
    with pytest.raises(FileNotFoundError) as excinfo:
        BaseGuiComponent(driver, "/nonexistent/path/ui_map.json")
    
    assert "UI graph file not found" in str(excinfo.value)


def test_malformed_graph(tmp_path):
    """Test that malformed graph raises ValueError."""
    # Create malformed JSON (missing 'graph' key)
    bad_graph = {"base_url": "http://test.com"}
    
    graph_file = tmp_path / "bad_ui_map.json"
    with graph_file.open('w') as f:
        json.dump(bad_graph, f)
    
    driver = Mock()
    
    with pytest.raises(ValueError) as excinfo:
        BaseGuiComponent(driver, graph_file)
    
    assert "missing 'graph' key" in str(excinfo.value)


def test_transitions_parsed(sample_ui_graph):
    """Test that navigation transitions are parsed correctly."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Check transition exists
    home_url = "http://test.com/#!/home"
    devices_url = "http://test.com/#!/devices"
    elem_id = "elem_link_1"
    
    transition_key = (home_url, elem_id)
    assert transition_key in component._transitions
    assert component._transitions[transition_key] == devices_url


def test_url_to_friendly_name_special_cases():
    """Test URL to friendly name conversion for special cases."""
    driver = Mock()
    
    # Create minimal graph for testing
    graph = {
        "graph": {
            "nodes": [
                {"node_type": "Page", "page_type": "device_details", "friendly_name": "device_details_page", "id": "http://test.com/#!/devices/ABC123"},
                {"node_type": "Page", "page_type": "admin", "friendly_name": "admin_page", "id": "http://test.com/#!/admin/presets"}
            ],
            "edges": []
        }
    }
    
    # Create temp file
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(graph, f)
        temp_path = f.name
    
    try:
        component = BaseGuiComponent(driver, temp_path)
        
        # Device details
        assert 'device_details_page' in component._page_name_to_url
        
        # Admin page
        assert 'admin_page' in component._page_name_to_url
        
    finally:
        Path(temp_path).unlink()


def test_element_name_fallback():
    """Test element uses friendly_name from graph (no fallback needed)."""
    driver = Mock()
    
    # Create element with friendly_name from UI discovery
    graph = {
        "graph": {
            "nodes": [
                {"node_type": "Page", "page_type": "home", "friendly_name": "home_page", "id": "http://test.com/#!/home"},
                {
                    "node_type": "Element",
                    "element_type": "div",
                    "locator_type": "css",
                    "locator_value": "div.container",
                    "friendly_name": "div_999",
                    "id": "elem_div_999"
                }
            ],
            "edges": [
                {
                    "edge_type": "ON_PAGE",
                    "source": "elem_div_999",
                    "target": "http://test.com/#!/home"
                }
            ]
        }
    }
    
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(graph, f)
        temp_path = f.name
    
    try:
        component = BaseGuiComponent(driver, temp_path)
        
        home_elements = component.list_page_elements('home_page')
        
        # Should use friendly_name from graph (generated by ui_discovery.py)
        assert 'div_999' in home_elements
        
    finally:
        Path(temp_path).unlink()


# ================================================================
# Phase 3: Navigation Tests
# ================================================================

def test_find_shortest_path(sample_ui_graph):
    """Test BFS shortest path algorithm."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Find path from home to devices
    home_url = "http://test.com/#!/home"
    devices_url = "http://test.com/#!/devices"
    
    path = component._find_shortest_path(home_url, devices_url, max_steps=10)
    
    # Should find a path
    assert path is not None
    assert len(path) == 1
    assert path[0]['source'] == home_url
    assert path[0]['target'] == devices_url
    assert path[0]['element_id'] == 'elem_link_1'
    assert path[0]['action'] == 'click'


def test_find_shortest_path_same_page(sample_ui_graph):
    """Test path finding when already at target."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    home_url = "http://test.com/#!/home"
    path = component._find_shortest_path(home_url, home_url, max_steps=10)
    
    # Should return empty path
    assert path == []


def test_find_shortest_path_no_path(sample_ui_graph):
    """Test path finding when no path exists."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # No path from devices back to home (no reverse transition)
    devices_url = "http://test.com/#!/devices"
    home_url = "http://test.com/#!/home"
    
    path = component._find_shortest_path(devices_url, home_url, max_steps=10)
    
    # Should return None
    assert path is None


def test_find_shortest_path_max_steps(sample_ui_graph):
    """Test path finding respects max_steps."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    home_url = "http://test.com/#!/home"
    devices_url = "http://test.com/#!/devices"
    
    # Set max_steps to 0 - should find no path
    path = component._find_shortest_path(home_url, devices_url, max_steps=0)
    assert path is None


def test_get_available_actions(sample_ui_graph):
    """Test listing available navigation actions from a page."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Get actions from home page
    actions = component.get_available_actions('home_page')
    
    # Should have one action (to devices)
    assert len(actions) == 1
    assert actions[0]['target_page'] == 'device_list_page'
    assert actions[0]['element_name'] == 'devices_link'
    assert actions[0]['element_type'] == 'link'


def test_get_available_actions_no_transitions(sample_ui_graph):
    """Test available actions from page with no transitions."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Device list page has no outgoing transitions
    actions = component.get_available_actions('device_list_page')
    
    assert actions == []


def test_get_available_actions_current_state(sample_ui_graph):
    """Test available actions uses current state if not specified."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Set current state
    component.set_state('home_page')
    
    # Get actions without specifying page
    actions = component.get_available_actions()
    
    assert len(actions) == 1
    assert actions[0]['target_page'] == 'device_list_page'


def test_find_path_to_page(sample_ui_graph):
    """Test finding path without executing navigation."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Find path from home to devices
    path = component.find_path_to_page('device_list_page', 'home_page')
    
    assert path is not None
    assert len(path) == 1
    assert path[0]['from'] == 'home_page'
    assert path[0]['to'] == 'device_list_page'
    assert path[0]['via_element'] == 'devices_link'
    assert path[0]['element_id'] == 'elem_link_1'


def test_find_path_to_page_no_path(sample_ui_graph):
    """Test finding path when no path exists."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # No path from devices back to home
    path = component.find_path_to_page('home_page', 'device_list_page')
    
    assert path is None


def test_find_path_to_page_current_state(sample_ui_graph):
    """Test finding path from current state."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Set current state
    component.set_state('home_page')
    
    # Find path without specifying from_state
    path = component.find_path_to_page('device_list_page')
    
    assert path is not None
    assert len(path) == 1


def test_get_page_metadata(sample_ui_graph):
    """Test getting page metadata."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Get home page metadata
    metadata = component.get_page_metadata('home_page')
    
    assert metadata is not None
    assert metadata['name'] == 'home_page'
    assert metadata['url'] == "http://test.com/#!/home"
    assert metadata['title'] == 'Home'
    assert metadata['page_type'] == 'home'
    assert metadata['element_count'] == 2
    assert 'log_out_button' in metadata['elements']
    assert 'devices_link' in metadata['elements']
    assert metadata['outgoing_transitions'] == 1
    assert 'device_list_page' in metadata['can_navigate_to']


def test_get_page_metadata_not_found(sample_ui_graph):
    """Test getting metadata for non-existent page."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    metadata = component.get_page_metadata('nonexistent_page')
    
    assert metadata is None


def test_get_element_metadata(sample_ui_graph):
    """Test getting element metadata."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Get logout button metadata
    metadata = component.get_element_metadata('home_page', 'log_out_button')
    
    assert metadata is not None
    assert metadata['name'] == 'log_out_button'
    assert metadata['id'] == 'elem_btn_1'
    assert metadata['element_type'] == 'button'
    assert metadata['text'] == 'Log out'
    assert metadata['locator_type'] == 'css'
    assert metadata['locator_value'] == 'button.logout'


def test_get_element_metadata_not_found(sample_ui_graph):
    """Test getting metadata for non-existent element."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    metadata = component.get_element_metadata('home_page', 'nonexistent_button')
    
    assert metadata is None


def test_detect_current_page(sample_ui_graph):
    """Test detecting current page from URL."""
    driver = Mock()
    driver.current_url = "http://test.com/#!/home"
    
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Mock verify_page to return True and also update state (side effect)
    def mock_verify(page, timeout=5, update_state=True):
        if update_state:
            component.set_state(page, via_action='verified')
        return True
    
    component.verify_page = Mock(side_effect=mock_verify)
    
    # Detect current page
    page = component.detect_current_page(update_state=True)
    
    assert page == 'home_page'
    assert component.get_state() == 'home_page'


def test_detect_current_page_unknown_url(sample_ui_graph):
    """Test detecting current page with unknown URL."""
    driver = Mock()
    driver.current_url = "http://test.com/#!/unknown"
    
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Detect should fail
    page = component.detect_current_page()
    
    assert page is None


def test_navigate_to_state_success(sample_ui_graph):
    """Test successful navigation."""
    from unittest.mock import patch
    from selenium.webdriver.support.ui import WebDriverWait
    
    driver = Mock()
    driver.current_url = "http://test.com/#!/home"
    
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Set initial state
    component.set_state('home_page')
    
    # Mock element that will be clicked
    mock_element = Mock()
    
    # Mock WebDriverWait to return clickable element
    with patch.object(WebDriverWait, '__init__', return_value=None):
        with patch.object(WebDriverWait, 'until', return_value=mock_element):
            # Mock verify_page to return True (final verification)
            component.verify_page = Mock(return_value=True)
            
            # Navigate
            success = component.navigate_to_state('device_list_page')
    
    assert success is True
    assert component.get_state() == 'device_list_page'
    mock_element.click.assert_called_once()


def test_navigate_to_state_already_there(sample_ui_graph):
    """Test navigation when already at target."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Set state to target
    component.set_state('device_list_page')
    
    # Navigate to same page
    success = component.navigate_to_state('device_list_page')
    
    assert success is True


def test_navigate_to_state_no_path(sample_ui_graph):
    """Test navigation when no path exists."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Set state to device list (no path back to home)
    component.set_state('device_list_page')
    
    # Try to navigate to home
    success = component.navigate_to_state('home_page')
    
    assert success is False


def test_navigate_to_state_no_current_state(sample_ui_graph):
    """Test navigation without current state."""
    from unittest.mock import patch
    from selenium.webdriver.support.ui import WebDriverWait
    
    driver = Mock()
    driver.current_url = "http://test.com/#!/home"
    
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Mock detect_current_page to set state as side effect
    def mock_detect(update_state=True):
        if update_state:
            component.set_state('home_page', via_action='detected')
        return 'home_page'
    
    component.detect_current_page = Mock(side_effect=mock_detect)
    
    # Mock navigation element
    mock_element = Mock()
    
    # Mock WebDriverWait
    with patch.object(WebDriverWait, '__init__', return_value=None):
        with patch.object(WebDriverWait, 'until', return_value=mock_element):
            # Mock verify_page for final verification
            component.verify_page = Mock(return_value=True)
            
            # Navigate
            success = component.navigate_to_state('device_list_page')
    
    # Should detect current page first
    component.detect_current_page.assert_called_once()
    assert success is True


def test_navigate_to_state_invalid_target(sample_ui_graph):
    """Test navigation to non-existent page."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    component.set_state('home_page')
    
    # Try to navigate to invalid page
    with pytest.raises(KeyError) as excinfo:
        component.navigate_to_state('nonexistent_page')
    
    assert "Target page 'nonexistent_page' not found" in str(excinfo.value)

