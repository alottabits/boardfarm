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
        
        # Read friendly page name from graph (generated during UI discovery)
        # This provides a stable, readable name for tests to reference
        # URL: http://127.0.0.1:3000/#!/overview → page_name: "home_page"
        # URL: http://127.0.0.1:3000/#!/devices → page_name: "device_list_page"
        friendly_name = node.get('friendly_name')
        if not friendly_name:
            raise ValueError(f"Page node missing 'friendly_name': {page_url}")
        
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
        
        # Read friendly name from graph (generated during UI discovery)
        # This provides a stable, readable name for tests to reference
        elem_name = elem_info.get('friendly_name')
        if not elem_name:
            raise ValueError(f"Element node missing 'friendly_name': {elem_id}")
        
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
    # PAGE VERIFICATION
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
    
    # ================================================================
    # GRAPH-BASED NAVIGATION (Phase 3)
    # ================================================================
    
    def navigate_to_state(
        self,
        target_state: str,
        max_steps: int = 10
    ) -> bool:
        """Navigate from current state to target using shortest path.
        
        Uses BFS algorithm to find the shortest path through the UI graph
        and executes the navigation by clicking elements in sequence.
        
        Args:
            target_state: Target page name (e.g., 'device_list_page')
            max_steps: Maximum navigation steps allowed (default: 10)
            
        Returns:
            True if navigation successful, False otherwise
            
        Raises:
            KeyError: If target_state not found in graph
            ValueError: If current state is unknown
            
        Example:
            >>> # Navigate from home to device details
            >>> component.set_state('home_page')
            >>> component.navigate_to_state('device_list_page')
            True
            >>> component.navigate_to_state('device_details_page')
            True
        """
        # Validate target exists
        if target_state not in self._page_name_to_url:
            available = list(self._page_name_to_url.keys())
            raise KeyError(
                f"Target page '{target_state}' not found in UI graph. "
                f"Available: {available}"
            )
        
        target_url = self._page_name_to_url[target_state]
        
        # Get or detect current state
        current_state = self._current_state
        if not current_state:
            _LOGGER.warning("Current state unknown, attempting to detect...")
            current_state = self.detect_current_page(update_state=True)
            if not current_state:
                raise ValueError(
                    "Cannot navigate: current state is unknown and could not be detected. "
                    "Call set_state() or navigate to a known page first."
                )
        
        current_url = self._page_name_to_url[current_state]
        
        # Already at target?
        if current_url == target_url:
            _LOGGER.info("Already at target page '%s'", target_state)
            return True
        
        _LOGGER.info(
            "Navigating: %s → %s (max %d steps)",
            current_state, target_state, max_steps
        )
        
        # Find shortest path using BFS
        path = self._find_shortest_path(current_url, target_url, max_steps)
        
        if not path:
            _LOGGER.error(
                "No path found from '%s' to '%s' within %d steps",
                current_state, target_state, max_steps
            )
            return False
        
        _LOGGER.info("Found path with %d steps", len(path))
        
        # Execute navigation path
        for i, step in enumerate(path, 1):
            source_url = step['source']
            target_url = step['target']
            element_id = step['element_id']
            action = step.get('action', 'click')
            
            # Get friendly names for logging
            source_name = self._url_to_page_name.get(source_url, source_url)
            target_name = self._url_to_page_name.get(target_url, target_url)
            
            _LOGGER.debug(
                "Step %d/%d: %s → %s (via %s)",
                i, len(path), source_name, target_name, element_id
            )
            
            # Find the element to click
            try:
                # Get element info
                if element_id not in self._elements:
                    _LOGGER.error("Element '%s' not found in graph", element_id)
                    return False
                
                elem_info = self._elements[element_id]
                
                # Build locator
                locator_type = elem_info.get('locator_type', 'css')
                locator_value = elem_info.get('locator_value')
                
                if not locator_value:
                    _LOGGER.error("Element '%s' has no locator_value", element_id)
                    return False
                
                by_type = self.BY_MAPPING.get(locator_type, By.CSS_SELECTOR)
                
                # Find and click element
                wait = WebDriverWait(self.driver, self._default_timeout)
                element = wait.until(
                    EC.element_to_be_clickable((by_type, locator_value))
                )
                element.click()
                
                _LOGGER.debug("Clicked element: %s", element_id)
                
                # Update state
                self.set_state(target_name, via_action=f'navigate_step_{i}')
                
                # Wait briefly for page transition
                time.sleep(0.3)
                
            except Exception as e:
                _LOGGER.error(
                    "Navigation failed at step %d/%d: %s",
                    i, len(path), e
                )
                return False
        
        # Verify we arrived at target
        if self.verify_page(target_state, timeout=5, update_state=True):
            _LOGGER.info("Navigation successful: arrived at '%s'", target_state)
            return True
        else:
            _LOGGER.warning(
                "Navigation completed but verification failed for '%s'",
                target_state
            )
            return False
    
    def _find_shortest_path(
        self,
        source_url: str,
        target_url: str,
        max_steps: int
    ) -> list[dict] | None:
        """Find shortest path between pages using BFS algorithm.
        
        Uses breadth-first search to find the shortest sequence of clicks
        needed to navigate from source page to target page.
        
        Args:
            source_url: Source page URL
            target_url: Target page URL
            max_steps: Maximum path length to search
            
        Returns:
            List of navigation steps, where each step is:
            {
                'source': source_url,
                'target': target_url,
                'element_id': element_id,
                'action': 'click'
            }
            Returns None if no path found within max_steps
            
        Algorithm:
            1. Initialize queue with source page
            2. Track visited pages to avoid cycles
            3. For each page, explore all outgoing MAPS_TO transitions
            4. Record parent for path reconstruction
            5. Return path when target found
            6. Return None if queue exhausted or max_steps exceeded
            
        Complexity:
            Time: O(V + E) where V = pages, E = transitions
            Space: O(V) for visited and parent tracking
        """
        if source_url == target_url:
            return []
        
        # BFS initialization
        queue = deque([(source_url, 0)])  # (page_url, depth)
        visited = {source_url}
        parent = {}  # page_url → (parent_url, element_id, action)
        
        while queue:
            current_url, depth = queue.popleft()
            
            # Check depth limit
            if depth >= max_steps:
                continue
            
            # Explore all transitions from current page
            for (page_url, element_id), next_url in self._transitions.items():
                if page_url != current_url:
                    continue
                
                # Skip if already visited
                if next_url in visited:
                    continue
                
                # Mark as visited and record parent
                visited.add(next_url)
                parent[next_url] = (current_url, element_id, 'click')
                
                # Found target?
                if next_url == target_url:
                    return self._reconstruct_path(parent, source_url, target_url)
                
                # Add to queue for further exploration
                queue.append((next_url, depth + 1))
        
        # No path found
        return None
    
    def _reconstruct_path(
        self,
        parent: dict[str, tuple[str, str, str]],
        source_url: str,
        target_url: str
    ) -> list[dict]:
        """Reconstruct path from parent tracking dictionary.
        
        Args:
            parent: Dictionary mapping page_url → (parent_url, element_id, action)
            source_url: Starting page URL
            target_url: Target page URL
            
        Returns:
            List of navigation steps in forward order
        """
        path = []
        current = target_url
        
        # Walk backwards from target to source
        while current != source_url:
            parent_url, element_id, action = parent[current]
            path.append({
                'source': parent_url,
                'target': current,
                'element_id': element_id,
                'action': action
            })
            current = parent_url
        
        # Reverse to get forward order
        path.reverse()
        return path
    
    # ================================================================
    # HELPER METHODS FOR UI EXPLORATION
    # ================================================================
    
    def detect_current_page(self, update_state: bool = True) -> str | None:
        """Detect which page we're currently on based on URL and verification.
        
        Attempts to determine current page by:
        1. Matching browser URL against known page URLs
        2. Verifying the match by finding an element on that page
        
        Args:
            update_state: If True, update tracked state on successful detection
            
        Returns:
            Page name (friendly name) or None if unknown
            
        Example:
            >>> # After manual navigation or session recovery
            >>> current = component.detect_current_page()
            >>> print(f"Currently on: {current}")
            Currently on: home_page
        """
        try:
            current_url = self.driver.current_url
            _LOGGER.debug("Detecting current page from URL: %s", current_url)
            
            # Try exact URL match first
            if current_url in self._url_to_page_name:
                page_name = self._url_to_page_name[current_url]
                
                # Verify by finding an element
                if self.verify_page(page_name, timeout=2, update_state=update_state):
                    _LOGGER.info("Detected current page: %s", page_name)
                    return page_name
            
            # Try partial URL matching (for parameterized URLs)
            # Extract base URL without query parameters
            base_url = current_url.split('?')[0]
            
            for known_url, page_name in self._url_to_page_name.items():
                # Check if current URL starts with known base
                if base_url.startswith(known_url.split('?')[0]):
                    # Verify by finding an element
                    if self.verify_page(page_name, timeout=2, update_state=update_state):
                        _LOGGER.info("Detected current page (partial match): %s", page_name)
                        return page_name
            
            _LOGGER.warning("Could not detect current page from URL: %s", current_url)
            return None
            
        except Exception as e:
            _LOGGER.error("Error detecting current page: %s", e)
            return None
    
    def get_available_actions(self, page_state: str | None = None) -> list[dict]:
        """List all navigation actions available from a page.
        
        Args:
            page_state: Page name (uses current state if None)
            
        Returns:
            List of available actions:
            [
                {
                    'element_id': 'elem_link_1',
                    'element_name': 'devices_link',
                    'target_page': 'device_list_page',
                    'target_url': 'http://...'
                },
                ...
            ]
            
        Example:
            >>> # See where we can navigate from home page
            >>> actions = component.get_available_actions('home_page')
            >>> for action in actions:
            ...     print(f"Can go to {action['target_page']} via {action['element_name']}")
            Can go to device_list_page via devices_link
            Can go to admin_page via admin_link
        """
        # Use current state if not specified
        if page_state is None:
            page_state = self._current_state
            if not page_state:
                _LOGGER.warning("No page state specified and current state is unknown")
                return []
        
        # Get page URL
        if page_state not in self._page_name_to_url:
            _LOGGER.warning("Page '%s' not found in graph", page_state)
            return []
        
        page_url = self._page_name_to_url[page_state]
        
        # Find all transitions from this page
        actions = []
        for (source_url, element_id), target_url in self._transitions.items():
            if source_url != page_url:
                continue
            
            # Get element info
            elem_info = self._elements.get(element_id, {})
            elem_name = elem_info.get('friendly_name', element_id)  # Read from graph
            
            # Get target page name
            target_page = self._url_to_page_name.get(target_url, target_url)
            
            actions.append({
                'element_id': element_id,
                'element_name': elem_name,
                'target_page': target_page,
                'target_url': target_url,
                'element_type': elem_info.get('element_type', 'unknown')
            })
        
        _LOGGER.debug(
            "Found %d available actions from page '%s'",
            len(actions), page_state
        )
        
        return actions
    
    def find_path_to_page(
        self,
        target_state: str,
        from_state: str | None = None,
        max_steps: int = 10
    ) -> list[dict] | None:
        """Find navigation path without executing it.
        
        Useful for:
        - Planning navigation
        - Testing path existence
        - Generating navigation documentation
        
        Args:
            target_state: Target page name
            from_state: Starting page (uses current state if None)
            max_steps: Maximum path length
            
        Returns:
            List of navigation steps with friendly names:
            [
                {
                    'from': 'home_page',
                    'to': 'device_list_page',
                    'via_element': 'devices_link',
                    'element_id': 'elem_link_1'
                },
                ...
            ]
            Returns None if no path found
            
        Example:
            >>> # Plan navigation from home to device details
            >>> path = component.find_path_to_page('device_details_page', 'home_page')
            >>> for step in path:
            ...     print(f"{step['from']} → {step['to']} (click {step['via_element']})")
            home_page → device_list_page (click devices_link)
            device_list_page → device_details_page (click device_row_1)
        """
        # Use current state if not specified
        if from_state is None:
            from_state = self._current_state
            if not from_state:
                _LOGGER.warning("No starting state specified and current state is unknown")
                return None
        
        # Validate pages exist
        if from_state not in self._page_name_to_url:
            _LOGGER.error("Source page '%s' not found", from_state)
            return None
        
        if target_state not in self._page_name_to_url:
            _LOGGER.error("Target page '%s' not found", target_state)
            return None
        
        source_url = self._page_name_to_url[from_state]
        target_url = self._page_name_to_url[target_state]
        
        # Find path using BFS
        raw_path = self._find_shortest_path(source_url, target_url, max_steps)
        
        if not raw_path:
            return None
        
        # Convert to friendly format
        friendly_path = []
        for step in raw_path:
            source_name = self._url_to_page_name.get(step['source'], step['source'])
            target_name = self._url_to_page_name.get(step['target'], step['target'])
            
            # Get element name
            elem_info = self._elements.get(step['element_id'], {})
            elem_name = elem_info.get('friendly_name', step['element_id'])  # Read from graph
            
            friendly_path.append({
                'from': source_name,
                'to': target_name,
                'via_element': elem_name,
                'element_id': step['element_id'],
                'action': step.get('action', 'click')
            })
        
        return friendly_path
    
    def get_page_metadata(self, page_state: str) -> dict | None:
        """Get complete metadata about a page.
        
        Args:
            page_state: Page name
            
        Returns:
            Dictionary with page metadata:
            {
                'name': 'home_page',
                'url': 'http://...',
                'title': 'Overview - GenieACS',
                'page_type': 'home',
                'element_count': 15,
                'elements': ['log_out_button', 'devices_link', ...],
                'outgoing_transitions': 5,
                'can_navigate_to': ['device_list_page', 'admin_page', ...]
            }
            Returns None if page not found
            
        Example:
            >>> # Inspect page structure
            >>> metadata = component.get_page_metadata('home_page')
            >>> print(f"Page has {metadata['element_count']} elements")
            >>> print(f"Can navigate to: {metadata['can_navigate_to']}")
        """
        if page_state not in self._page_name_to_url:
            _LOGGER.warning("Page '%s' not found", page_state)
            return None
        
        page_url = self._page_name_to_url[page_state]
        page_info = self._pages.get(page_url, {})
        page_elements = self._elements_by_page.get(page_url, {})
        
        # Find outgoing transitions
        targets = set()
        transition_count = 0
        for (source_url, _), target_url in self._transitions.items():
            if source_url == page_url:
                transition_count += 1
                target_name = self._url_to_page_name.get(target_url, target_url)
                targets.add(target_name)
        
        return {
            'name': page_state,
            'url': page_url,
            'title': page_info.get('title', ''),
            'page_type': page_info.get('page_type', 'unknown'),
            'element_count': len(page_elements),
            'elements': list(page_elements.keys()),
            'outgoing_transitions': transition_count,
            'can_navigate_to': sorted(targets)
        }
    
    def get_element_metadata(
        self,
        page_state: str,
        element_name: str
    ) -> dict | None:
        """Get complete metadata about an element.
        
        Args:
            page_state: Page name
            element_name: Element name
            
        Returns:
            Dictionary with element metadata:
            {
                'id': 'elem_button_1',
                'name': 'log_out_button',
                'element_type': 'button',
                'text': 'Log out',
                'locator_type': 'css',
                'locator_value': 'button',
                'aria_label': 'Logout',
                ...
            }
            Returns None if element not found
            
        Example:
            >>> # Inspect element details
            >>> metadata = component.get_element_metadata('home_page', 'log_out_button')
            >>> print(f"Element type: {metadata['element_type']}")
            >>> print(f"Locator: {metadata['locator_type']}={metadata['locator_value']}")
        """
        if page_state not in self._page_name_to_url:
            _LOGGER.warning("Page '%s' not found", page_state)
            return None
        
        page_url = self._page_name_to_url[page_state]
        page_elements = self._elements_by_page.get(page_url, {})
        
        if element_name not in page_elements:
            _LOGGER.warning(
                "Element '%s' not found on page '%s'",
                element_name, page_state
            )
            return None
        
        elem_data = page_elements[element_name]
        elem_info = elem_data['info'].copy()
        elem_info['name'] = element_name
        
        return elem_info

