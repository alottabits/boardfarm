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
                    "id": "http://test.com/#!/home"
                },
                {
                    "node_type": "Page",
                    "page_type": "login",
                    "title": "Login",
                    "id": "http://test.com/#!/login"
                },
                {
                    "node_type": "Page",
                    "page_type": "device_list",
                    "title": "Devices",
                    "id": "http://test.com/#!/devices"
                },
                {
                    "node_type": "Element",
                    "element_type": "button",
                    "text": "Log out",
                    "locator_type": "css",
                    "locator_value": "button.logout",
                    "button_type": "button",
                    "id": "elem_btn_1"
                },
                {
                    "node_type": "Element",
                    "element_type": "input",
                    "name": "username",
                    "input_type": "text",
                    "locator_type": "css",
                    "locator_value": "input[name='username']",
                    "id": "elem_input_1"
                },
                {
                    "node_type": "Element",
                    "element_type": "input",
                    "name": "password",
                    "input_type": "password",
                    "locator_type": "css",
                    "locator_value": "input[name='password']",
                    "id": "elem_input_2"
                },
                {
                    "node_type": "Element",
                    "element_type": "link",
                    "text": "Devices",
                    "locator_type": "css",
                    "locator_value": "a.devices",
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
                {"node_type": "Page", "page_type": "device_details", "id": "http://test.com/#!/devices/ABC123"},
                {"node_type": "Page", "page_type": "admin", "id": "http://test.com/#!/admin/presets"}
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
    """Test element name generation with fallback to ID."""
    driver = Mock()
    
    # Create element with no text/title/placeholder
    graph = {
        "graph": {
            "nodes": [
                {"node_type": "Page", "page_type": "home", "id": "http://test.com/#!/home"},
                {
                    "node_type": "Element",
                    "element_type": "div",
                    "locator_type": "css",
                    "locator_value": "div.container",
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
        
        # Should use fallback: element_type + id
        assert 'div_elem_div_999' in home_elements
        
    finally:
        Path(temp_path).unlink()


def test_navigation_not_implemented(sample_ui_graph):
    """Test that navigation methods raise NotImplementedError (Phase 3)."""
    driver = Mock()
    component = BaseGuiComponent(driver, sample_ui_graph)
    
    # Set state first
    component.set_state('home_page')
    
    # Navigation should raise NotImplementedError
    with pytest.raises(NotImplementedError):
        component.navigate_to_state('device_list_page')
    
    # Pathfinding should raise NotImplementedError
    with pytest.raises(NotImplementedError):
        component._find_shortest_path(
            "http://test.com/#!/home",
            "http://test.com/#!/devices",
            10
        )

