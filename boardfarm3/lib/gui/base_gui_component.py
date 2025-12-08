"""Base GUI Component - Graph-Based Single Source of Truth.

This component uses ONLY ui_map.json (the complete UI graph from discovery)
as its data source. It builds efficient in-memory lookup structures for:
- Element location by page
- Navigation transitions
- Dynamic pathfinding
- State tracking

This architecture uses a single-file approach that dynamically computes
everything from the UI graph, replacing the previous three-file system
(selectors.yaml, navigation.yaml, ui_map.json).

Architecture:
    ui_map.json (NetworkX graph format from discovery)
        ↓
    Parse once at initialization
        ↓
    Build in-memory structures:
        - _pages: URL → page metadata
        - _elements: element_id → element metadata
        - _elements_by_page: page_url → {element_name: element_info}
        - _transitions: (source_url, element_id) → target_url
        ↓
    Fast lookups + dynamic pathfinding + state tracking
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

_LOGGER = logging.getLogger(__name__)


class BaseGuiComponent:
    """Base GUI component using ui_map.json as single source of truth.
    
    This component uses a graph-based architecture that dynamically computes
    navigation paths and element locations from the UI graph.
    
    Attributes:
        driver: Selenium WebDriver instance
        wait: WebDriverWait instance
        _default_timeout: Default timeout for element waits
        _pages: Dictionary mapping URL → page metadata
        _elements: Dictionary mapping element_id → element metadata
        _elements_by_page: Dictionary mapping page_url → {elem_name: elem_info}
        _transitions: Dictionary mapping (source_url, elem_id) → target_url
        _page_name_to_url: Dictionary mapping friendly_name → URL
        _url_to_page_name: Dictionary mapping URL → friendly_name
        _current_state: Current page (friendly name)
        _current_url: Current page URL
        _state_history: Navigation history
    """

    # Mapping of locator types to Selenium By constants
    BY_MAPPING = {
        "id": By.ID,
        "name": By.NAME,
        "xpath": By.XPATH,
        "css": By.CSS_SELECTOR,
        "css_selector": By.CSS_SELECTOR,
        "class_name": By.CLASS_NAME,
        "tag_name": By.TAG_NAME,
        "link_text": By.LINK_TEXT,
        "partial_link_text": By.PARTIAL_LINK_TEXT,
    }

    def __init__(
        self,
        driver: WebDriver,
        ui_graph_file: str | Path,
        default_timeout: int = 20,
    ):
        """Initialize GUI component from ui_map.json.
        
        Args:
            driver: Selenium WebDriver instance
            ui_graph_file: Path to ui_map.json (complete UI graph)
            default_timeout: Default timeout in seconds for element waits
            
        Raises:
            FileNotFoundError: If ui_graph_file doesn't exist
            ValueError: If ui_map.json is malformed
        """
        self.driver = driver
        self.wait = WebDriverWait(driver, default_timeout)
        self._default_timeout = default_timeout
        
        # In-memory lookup structures (built from ui_map.json)
        self._pages: dict[str, dict] = {}                      # URL → page metadata
        self._elements: dict[str, dict] = {}                   # element_id → element metadata
        self._elements_by_page: dict[str, dict] = {}           # page_url → {elem_name: elem_info}
        self._transitions: dict[tuple[str, str], str] = {}     # (source_url, elem_id) → target_url
        self._page_name_to_url: dict[str, str] = {}            # friendly_name → URL
        self._url_to_page_name: dict[str, str] = {}            # URL → friendly_name
        
        # State tracking
        self._current_state: str | None = None                 # Current page (friendly name)
        self._current_url: str | None = None                   # Current page URL
        self._state_history: list[dict] = []                   # Navigation history
        
        # Load and parse ui_map.json
        self._load_ui_graph(ui_graph_file)
        
    def _load_ui_graph(self, graph_file: str | Path) -> None:
        """Load ui_map.json and build in-memory lookup structures.
        
        This replaces the previous approach of loading selectors.yaml and
        navigation.yaml. Everything is derived from the graph.
        
        Args:
            graph_file: Path to ui_map.json
            
        Raises:
            FileNotFoundError: If graph file doesn't exist
            ValueError: If JSON is malformed
        """
        graph_path = Path(graph_file)
        if not graph_path.exists():
            raise FileNotFoundError(f"UI graph file not found: {graph_file}")
            
        _LOGGER.info("Loading UI graph from: %s", graph_file)
        
        with graph_path.open() as f:
            ui_map = json.load(f)
            
        graph_data = ui_map.get('graph', {})
        
        if not graph_data:
            raise ValueError(f"Invalid ui_map.json: missing 'graph' key")
            
        # Step 1: Parse all nodes (pages and elements)
        for node in graph_data.get('nodes', []):
            if node.get('node_type') == 'Page':
                self._parse_page_node(node)
            elif node.get('node_type') == 'Element':
                self._parse_element_node(node)
                
        # Step 2: Parse all edges (containment and navigation)
        for edge in graph_data.get('edges', []):
            if edge.get('edge_type') == 'ON_PAGE':
                self._parse_on_page_edge(edge)
            elif edge.get('edge_type') == 'MAPS_TO':
                self._parse_maps_to_edge(edge)
                
        _LOGGER.info(
            "UI graph loaded: %d pages, %d elements, %d transitions",
            len(self._pages),
            len(self._elements),
            len(self._transitions)
        )
        
        # Log page mappings for debugging
        for name, url in self._page_name_to_url.items():
            _LOGGER.debug("Page mapping: %s → %s", name, url)
            
    def _parse_page_node(self, node: dict) -> None:
        """Parse a Page node and create friendly name mapping.
        
        Example node:
        {
            "node_type": "Page",
            "title": "Overview - GenieACS",
            "page_type": "home",
            "id": "http://127.0.0.1:3000/#!/overview"
        }
        
        Args:
            node: Page node dictionary from graph
        """
        page_url = node['id']
        self._pages[page_url] = node
        
        # Initialize element container for this page
        self._elements_by_page[page_url] = {}
        
        # Create friendly page name from URL
        # URL: http://127.0.0.1:3000/#!/overview → page_name: "home_page"
        # URL: http://127.0.0.1:3000/#!/devices → page_name: "device_list_page"
        friendly_name = self._url_to_friendly_page_name(page_url, node.get('page_type'))
        
        self._page_name_to_url[friendly_name] = page_url
        self._url_to_page_name[page_url] = friendly_name
        
    def _parse_element_node(self, node: dict) -> None:
        """Parse an Element node.
        
        Example node:
        {
            "node_type": "Element",
            "element_type": "button",
            "text": "Log out",
            "locator_type": "css",
            "locator_value": "button",
            "button_type": "submit",
            "id": "elem_button_1"
        }
        
        Args:
            node: Element node dictionary from graph
        """
        elem_id = node['id']
        self._elements[elem_id] = node
        
    def _parse_on_page_edge(self, edge: dict) -> None:
        """Parse an ON_PAGE edge (element is on page).
        
        Example edge:
        {
            "edge_type": "ON_PAGE",
            "source": "elem_button_1",
            "target": "http://127.0.0.1:3000/#!/overview"
        }
        
        Args:
            edge: Edge dictionary from graph
        """
        elem_id = edge['source']
        page_url = edge['target']
        
        if page_url not in self._elements_by_page:
            _LOGGER.warning("Page not found for ON_PAGE edge: %s", page_url)
            return
            
        if elem_id not in self._elements:
            _LOGGER.warning("Element not found for ON_PAGE edge: %s", elem_id)
            return
            
        elem_info = self._elements[elem_id]
        
        # Generate friendly name for element
        elem_name = self._generate_element_name(elem_info)
        
        # Add to page's element collection
        self._elements_by_page[page_url][elem_name] = {
            'id': elem_id,
            'name': elem_name,
            'info': elem_info
        }
        
    def _parse_maps_to_edge(self, edge: dict) -> None:
        """Parse a MAPS_TO edge (navigation transition).
        
        Example edge:
        {
            "edge_type": "MAPS_TO",
            "via_element": "elem_link_3",
            "action": "click",
            "source": "http://127.0.0.1:3000/#!/overview",
            "target": "http://127.0.0.1:3000/#!/devices"
        }
        
        Args:
            edge: Edge dictionary from graph
        """
        source_url = edge['source']
        target_url = edge['target']
        via_element = edge['via_element']
        
        # Store transition: (page, element) → target_page
        transition_key = (source_url, via_element)
        self._transitions[transition_key] = target_url
        
    def _url_to_friendly_page_name(self, url: str, page_type: str | None = None) -> str:
        """Convert URL to friendly page name.
        
        Examples:
            http://127.0.0.1:3000/#!/login → "login_page"
            http://127.0.0.1:3000/#!/overview → "home_page" (if page_type="home")
            http://127.0.0.1:3000/#!/devices → "device_list_page" (if page_type="device_list")
            http://127.0.0.1:3000/#!/devices/ABC123 → "device_details_page"
            
        Args:
            url: Full URL
            page_type: Optional page type from discovery
            
        Returns:
            Friendly page name suitable for state tracking
        """
        # Extract hash fragment
        if "#!/" in url:
            fragment = url.split("#!/")[1].split("?")[0]
        else:
            fragment = "unknown"
            
        # Special cases based on page_type from discovery
        if page_type == "home":
            return "home_page"
        elif page_type == "login":
            return "login_page"
        elif page_type == "device_list":
            return "device_list_page"
        elif page_type == "device_details":
            return "device_details_page"
        elif page_type == "faults":
            return "faults_page"
        elif page_type == "admin":
            return "admin_page"
            
        # Check for device details pattern
        if fragment.startswith("devices/") and "/" in fragment:
            return "device_details_page"
            
        # Default: convert fragment to friendly name
        # "admin/presets" → "admin_presets_page"
        friendly = fragment.replace("/", "_").replace("-", "_")
        return f"{friendly}_page"
        
    def _generate_element_name(self, elem_info: dict) -> str:
        """Generate friendly name for element.
        
        Strategy:
        1. Use text if available (e.g., "Log out" → "log_out")
        2. Use title if available (e.g., "Reboot device" → "reboot_device")
        3. Use placeholder if available (e.g., "Search" → "search")
        4. Use type + id as fallback
        
        Examples:
            {"element_type": "button", "text": "Log out"} → "log_out_button"
            {"element_type": "input", "placeholder": "Search"} → "search_input"
            {"element_type": "link", "text": "Devices"} → "devices_link"
            
        Args:
            elem_info: Element metadata dictionary
            
        Returns:
            Friendly element name
        """
        elem_type = elem_info.get('element_type', 'element')
        
        # Try to find a descriptive name (handle None values)
        text = (elem_info.get('text') or '').strip()
        title = (elem_info.get('title') or '').strip()
        placeholder = (elem_info.get('placeholder') or '').strip()
        aria_label = (elem_info.get('aria_label') or '').strip()
        name = (elem_info.get('name') or '').strip()
        
        # Priority order for naming
        name_source = text or title or placeholder or aria_label or name
        
        if name_source:
            # Clean up name: "Log out" → "log_out"
            clean_name = name_source.lower()
            clean_name = clean_name.replace(' ', '_')
            clean_name = clean_name.replace('-', '_')
            # Remove special characters
            clean_name = ''.join(c for c in clean_name if c.isalnum() or c == '_')
            return f"{clean_name}_{elem_type}"
        else:
            # Fallback: use element type + id
            elem_id = elem_info.get('id', 'unknown')
            return f"{elem_type}_{elem_id}"
            
    # ================================================================
    # STATE TRACKING
    # ================================================================
    
    def set_state(self, state: str, via_action: str | None = None) -> None:
        """Set current state (page) deterministically.
        
        Args:
            state: Page name (e.g., 'home_page', 'device_list_page')
            via_action: Optional description of how we got here
        """
        old_state = self._current_state
        self._current_state = state
        
        # Update current URL
        if state in self._page_name_to_url:
            self._current_url = self._page_name_to_url[state]
        
        # Record in history
        self._state_history.append({
            'from': old_state,
            'to': state,
            'via': via_action,
            'timestamp': time.time()
        })
        
        _LOGGER.debug("State: %s → %s (via: %s)", old_state, state, via_action)
        
    def get_state(self) -> str | None:
        """Get current state (page name).
        
        Returns:
            Current page name or None if not set
        """
        return self._current_state
        
    def get_state_history(self) -> list[dict]:
        """Get complete navigation history.
        
        Returns:
            List of state transition dictionaries
        """
        return self._state_history.copy()
        
    # ================================================================
    # ELEMENT FINDING (replaces selectors.yaml)
    # ================================================================
    
    def find_element(
        self,
        page_state: str,
        element_name: str,
        timeout: int | None = None
    ) -> WebElement:
        """Find element using ui_map.json data.
        
        This replaces the old selector_path approach from selectors.yaml.
        
        Args:
            page_state: Page name (e.g., 'home_page')
            element_name: Element name (e.g., 'log_out_button')
            timeout: Optional custom timeout
            
        Returns:
            WebElement
            
        Raises:
            KeyError: If page or element not found in graph
            TimeoutException: If element not found within timeout
            
        Example:
            >>> logout_btn = component.find_element('home_page', 'log_out_button')
        """
        # Get page URL from state name
        if page_state not in self._page_name_to_url:
            available = list(self._page_name_to_url.keys())
            raise KeyError(
                f"Page '{page_state}' not found in UI graph. "
                f"Available: {available}"
            )
            
        page_url = self._page_name_to_url[page_state]
        
        # Get element info from graph
        page_elements = self._elements_by_page.get(page_url, {})
        
        if element_name not in page_elements:
            available = list(page_elements.keys())
            raise KeyError(
                f"Element '{element_name}' not found on page '{page_state}'. "
                f"Available: {available}"
            )
            
        elem_data = page_elements[element_name]
        elem_info = elem_data['info']
        
        # Build Selenium locator
        locator_type = elem_info.get('locator_type', 'css')
        locator_value = elem_info.get('locator_value')
        
        if not locator_value:
            raise ValueError(
                f"Element '{element_name}' has no locator_value"
            )
            
        by_type = self.BY_MAPPING.get(locator_type, By.CSS_SELECTOR)
        
        # Find element with timeout
        wait = WebDriverWait(self.driver, timeout) if timeout else self.wait
        
        try:
            element = wait.until(
                EC.presence_of_element_located((by_type, locator_value))
            )
            _LOGGER.debug(
                "Found element: %s.%s (%s: %s)",
                page_state, element_name, locator_type, locator_value
            )
            return element
            
        except TimeoutException:
            _LOGGER.error(
                "Element not found: %s.%s (%s: %s) within %s seconds",
                page_state, element_name, locator_type, locator_value,
                timeout or self._default_timeout
            )
            raise
            
    def list_page_elements(self, page_state: str) -> list[str]:
        """List all available elements on a page.
        
        Useful for debugging and exploration.
        
        Args:
            page_state: Page name
            
        Returns:
            List of element names available on this page
        """
        if page_state not in self._page_name_to_url:
            return []
            
        page_url = self._page_name_to_url[page_state]
        return list(self._elements_by_page.get(page_url, {}).keys())
        
    # ================================================================
    # NAVIGATION (will be implemented in Phase 3)
    # ================================================================
    
    def verify_page(
        self,
        expected_page: str,
        timeout: int = 5,
        update_state: bool = True
    ) -> bool:
        """Verify we're on the expected page by finding an element on it.
        
        This validates that the current page matches expectations by attempting
        to find an element that should exist on that page. Useful for:
        - Validating navigation succeeded
        - Verifying state before performing actions
        - Confirming login/logout status
        - Asserting preconditions in tests
        
        Args:
            expected_page: Page name to verify (e.g., 'login_page', 'home_page')
            timeout: How long to wait for element (seconds)
            update_state: If True, update tracked state on successful verification
            
        Returns:
            True if page verified (expected element found)
            False if page not verified (element not found or page unknown)
            
        Example:
            # Verify we're on the login page
            if component.verify_page('login_page'):
                # Proceed with login
                pass
                
            # Verify and update state
            component.verify_page('home_page', update_state=True)
        """
        try:
            # Check if page exists in graph
            if expected_page not in self._page_name_to_url:
                _LOGGER.warning(
                    "Cannot verify page '%s' - not found in graph. Available: %s",
                    expected_page,
                    list(self._page_name_to_url.keys())
                )
                return False
            
            # Get elements on this page
            page_url = self._page_name_to_url[expected_page]
            page_elements = self._elements_by_page.get(page_url, {})
            
            if not page_elements:
                _LOGGER.warning(
                    "Cannot verify page '%s' - no elements in graph",
                    expected_page
                )
                return False
            
            # Try to find the first element on the page to verify we're there
            # Use a representative element (prefer buttons/inputs over generic elements)
            test_element = None
            for elem_name in page_elements.keys():
                # Prefer buttons and inputs as they're more stable indicators
                elem_data = page_elements[elem_name]
                elem_type = elem_data['info'].get('element_type', '')
                if elem_type in ['button', 'input']:
                    test_element = elem_name
                    break
            
            # If no button/input, use first available element
            if not test_element and page_elements:
                test_element = list(page_elements.keys())[0]
            
            # Try to find the element
            self.find_element(expected_page, test_element, timeout=timeout)
            
            # Success! Update state if requested
            if update_state:
                self.set_state(expected_page, via_action='verified')
            
            _LOGGER.debug("Verified page '%s' (found element '%s')", expected_page, test_element)
            return True
            
        except Exception as e:
            _LOGGER.debug("Page verification failed for '%s': %s", expected_page, e)
            return False
    
    def navigate_to_state(
        self,
        target_state: str,
        max_steps: int = 10
    ) -> bool:
        """Navigate from current state to target using shortest path.
        
        This will be implemented in Phase 3.
        Uses BFS to find shortest path in the graph.
        
        Args:
            target_state: Target page name (e.g., 'device_list_page')
            max_steps: Maximum navigation steps allowed
            
        Returns:
            True if navigation successful
            
        Raises:
            NotImplementedError: Phase 3 not yet implemented
        """
        raise NotImplementedError("Navigation will be implemented in Phase 3")
        
    def _find_shortest_path(
        self,
        source_url: str,
        target_url: str,
        max_steps: int
    ) -> list[dict] | None:
        """Find shortest path between pages using BFS.
        
        This will be implemented in Phase 3.
        
        Args:
            source_url: Source page URL
            target_url: Target page URL
            max_steps: Maximum path length
            
        Returns:
            List of edges representing the path, or None if no path
            
        Raises:
            NotImplementedError: Phase 3 not yet implemented
        """
        raise NotImplementedError("Pathfinding will be implemented in Phase 3")

