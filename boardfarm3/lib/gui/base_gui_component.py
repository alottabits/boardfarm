"""Base GUI Component for scalable UI testing.

This module provides a generic, reusable UI component that executes
navigation paths defined in YAML configuration files. It implements
the "Flat Name" architecture for maintainable UI testing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

_LOGGER = logging.getLogger(__name__)


class BaseGuiComponent:
    """Generic, reusable UI component provided by the framework.
    
    This class serves as the foundation for device-specific GUI components.
    It loads UI selectors and navigation paths from YAML files and provides
    a generic engine for executing named navigation paths.
    
    The architecture decouples test intent (stable) from UI implementation
    (volatile) by externalizing selectors and navigation paths to YAML files.
    
    Attributes:
        driver: Selenium WebDriver instance
        wait: WebDriverWait instance for element waiting
        selectors: Dictionary of UI element selectors loaded from YAML
        navigation: Dictionary of navigation paths loaded from YAML
    """

    # Mapping of selector types to Selenium By constants
    BY_MAPPING = {
        "id": By.ID,
        "name": By.NAME,
        "xpath": By.XPATH,
        "css": By.CSS_SELECTOR,  # Alias for css_selector
        "css_selector": By.CSS_SELECTOR,
        "class_name": By.CLASS_NAME,
        "tag_name": By.TAG_NAME,
        "link_text": By.LINK_TEXT,
        "partial_link_text": By.PARTIAL_LINK_TEXT,
    }

    def __init__(
        self,
        driver: WebDriver,
        selector_file: str | Path,
        navigation_file: str | Path,
        default_timeout: int = 20,
    ):
        """Initialize the BaseGuiComponent.
        
        Args:
            driver: Selenium WebDriver instance
            selector_file: Path to selectors YAML file
            navigation_file: Path to navigation YAML file
            default_timeout: Default timeout in seconds for element waits
            
        Raises:
            FileNotFoundError: If selector or navigation files don't exist
            yaml.YAMLError: If YAML files are malformed
        """
        self.driver = driver
        self.wait = WebDriverWait(driver, default_timeout)
        
        # Load selectors
        selector_path = Path(selector_file)
        if not selector_path.exists():
            raise FileNotFoundError(f"Selector file not found: {selector_file}")
        
        with selector_path.open() as f:
            self.selectors = yaml.safe_load(f)
            if not self.selectors:
                raise ValueError(f"Selector file is empty: {selector_file}")
        
        # Load navigation paths
        navigation_path = Path(navigation_file)
        if not navigation_path.exists():
            raise FileNotFoundError(f"Navigation file not found: {navigation_file}")
        
        with navigation_path.open() as f:
            self.navigation = yaml.safe_load(f)
            if not self.navigation:
                raise ValueError(f"Navigation file is empty: {navigation_file}")
        
        _LOGGER.info(
            "Initialized BaseGuiComponent with selectors from %s and navigation from %s",
            selector_file,
            navigation_file,
        )

    def _get_locator(self, selector_path: str, **kwargs) -> tuple[str, str]:
        """Parse dot-notation selector path and return Selenium locator tuple.
        
        This method traverses the selectors dictionary using dot notation
        (e.g., "home_page.main_menu.devices_link") and returns the
        corresponding Selenium locator.
        
        Args:
            selector_path: Dot-notated path to selector (e.g., "page.element")
            **kwargs: Optional template variables for dynamic selectors
            
        Returns:
            Tuple of (By type, selector string)
            
        Raises:
            KeyError: If selector path is not found
            ValueError: If selector format is invalid
            
        Example:
            >>> locator = self._get_locator("home_page.main_menu.devices_link")
            >>> # Returns: (By.ID, "devices-menu-item")
        """
        # Split the path and traverse the selectors dictionary
        path_parts = selector_path.split(".")
        current = self.selectors
        
        for part in path_parts:
            if not isinstance(current, dict):
                raise ValueError(
                    f"Invalid selector path '{selector_path}': "
                    f"'{part}' is not a valid key"
                )
            if part not in current:
                raise KeyError(
                    f"Selector path '{selector_path}' not found: "
                    f"missing key '{part}'"
                )
            current = current[part]
        
        # Validate the final selector structure
        if not isinstance(current, dict):
            raise ValueError(
                f"Invalid selector at '{selector_path}': expected dict, got {type(current)}"
            )
        
        if "by" not in current or "selector" not in current:
            raise ValueError(
                f"Invalid selector at '{selector_path}': "
                f"must contain 'by' and 'selector' keys"
            )
        
        by_type = current["by"]
        selector = current["selector"]
        
        # Validate the 'by' type
        if by_type not in self.BY_MAPPING:
            raise ValueError(
                f"Invalid 'by' type '{by_type}' in selector '{selector_path}'. "
                f"Valid types: {list(self.BY_MAPPING.keys())}"
            )
        
        # Apply template variables if provided
        if kwargs:
            selector = selector.format(**kwargs)
        
        return self.BY_MAPPING[by_type], selector

    def _find_element(
        self,
        selector_path: str,
        timeout: int | None = None,
        **kwargs,
    ) -> WebElement:
        """Find a single element using the selector path.
        
        Args:
            selector_path: Dot-notated path to selector
            timeout: Optional custom timeout (uses default if None)
            **kwargs: Optional template variables for dynamic selectors
            
        Returns:
            WebElement instance
            
        Raises:
            TimeoutException: If element is not found within timeout
            KeyError: If selector path is not found
        """
        by_type, selector = self._get_locator(selector_path, **kwargs)
        wait = WebDriverWait(self.driver, timeout) if timeout else self.wait
        
        try:
            element = wait.until(
                EC.presence_of_element_located((by_type, selector))
            )
            _LOGGER.debug("Found element: %s (%s: %s)", selector_path, by_type, selector)
            return element
        except TimeoutException:
            _LOGGER.error(
                "Element not found: %s (%s: %s) within %s seconds",
                selector_path,
                by_type,
                selector,
                timeout or self.wait._timeout,
            )
            raise

    def navigate_path(self, path_name: str, **kwargs) -> None:
        """Execute a uniquely named navigation path from the navigation artifact.
        
        This is the core method that executes a sequence of UI actions defined
        in the navigation.yaml file. The path_name acts as a stable contract
        between the test intent and the volatile UI implementation.
        
        Args:
            path_name: Unique name of the navigation path (e.g., 
                      "Path_Home_to_DeviceDetails_via_Search")
            **kwargs: Template variables for dynamic values in the path
                     (e.g., cpe_id="12345")
        
        Raises:
            ValueError: If path_name is not found in navigation.yaml
            KeyError: If a selector referenced in the path is not found
            
        Example:
            >>> gui.navigate_path(
            ...     "Path_Home_to_DeviceDetails_via_Search",
            ...     cpe_id="ABC123"
            ... )
        """
        # Get the navigation path definition
        navigation_paths = self.navigation.get("navigation_paths", {})
        path_steps = navigation_paths.get(path_name)
        
        if not path_steps:
            available_paths = list(navigation_paths.keys())
            raise ValueError(
                f"Path '{path_name}' not found in navigation.yaml. "
                f"Available paths: {available_paths}"
            )
        
        _LOGGER.info("Executing navigation path: %s", path_name)
        
        # Execute each step in the path
        for step_idx, step in enumerate(path_steps, 1):
            self._execute_step(step, step_idx, path_name, **kwargs)
        
        _LOGGER.info("Completed navigation path: %s", path_name)

    def _execute_step(
        self,
        step: dict[str, Any],
        step_idx: int,
        path_name: str,
        **kwargs,
    ) -> None:
        """Execute a single navigation step.
        
        Args:
            step: Step definition from navigation.yaml
            step_idx: Step index (for logging)
            path_name: Name of the navigation path (for logging)
            **kwargs: Template variables for dynamic values
            
        Raises:
            ValueError: If action type is unknown or step is malformed
        """
        action = step.get("action")
        target = step.get("target")
        
        if not action:
            raise ValueError(
                f"Step {step_idx} in path '{path_name}' missing 'action' key"
            )
        
        if not target:
            raise ValueError(
                f"Step {step_idx} in path '{path_name}' missing 'target' key"
            )
        
        _LOGGER.debug(
            "Step %d/%s: %s on %s",
            step_idx,
            path_name,
            action,
            target,
        )
        
        # Execute the action
        if action == "click":
            element = self._find_element(target, **kwargs)
            element.click()
            
        elif action == "type":
            value = step.get("value")
            if value is None:
                raise ValueError(
                    f"Step {step_idx} in path '{path_name}': "
                    f"'type' action requires 'value' key"
                )
            # Apply template variables to the value
            if kwargs:
                value = value.format(**kwargs)
            
            element = self._find_element(target, **kwargs)
            element.clear()
            element.send_keys(value)
            
        elif action == "wait":
            # Wait for element to be present
            self._find_element(target, **kwargs)
            
        else:
            raise ValueError(
                f"Unknown action '{action}' in step {step_idx} of path '{path_name}'. "
                f"Supported actions: click, type, wait"
            )
    
    def find_element_by_function(
        self,
        element_type: str,
        function_keywords: list[str],
        page: str | None = None,
        fallback_name: str | None = None,
        timeout: int | None = None,
    ) -> WebElement:
        """Find element by functional keywords with fallback to explicit name.
        
        This method enables self-healing tests by searching element metadata
        for functional matches using scoring. Even when element IDs/names change,
        tests can find elements by their purpose.
        
        Phase 5.2: Semantic element search with scoring algorithm.
        
        Args:
            element_type: Element type ("button", "input", "link", "select")
            function_keywords: Keywords indicating function (e.g., ["reboot", "restart"])
            page: Page to search (uses current page if None)
            fallback_name: Explicit element name to use if semantic search fails
            timeout: Optional custom timeout for element location
            
        Returns:
            WebElement matching the function
            
        Raises:
            ValueError: If page not found in selectors
            KeyError: If no element matches function and no fallback provided
            
        Example:
            >>> # Search for reboot button by function
            >>> btn = gui.find_element_by_function(
            ...     element_type="button",
            ...     function_keywords=["reboot", "restart", "reset"],
            ...     page="device_details_page",
            ...     fallback_name="reboot"
            ... )
        """
        page = page or self._get_current_page()
        
        # Validate page exists
        if page not in self.selectors:
            available_pages = list(self.selectors.keys())
            raise ValueError(
                f"Page '{page}' not found in selectors. "
                f"Available pages: {available_pages}"
            )
        
        # Get all elements of this type on the page
        element_group = f"{element_type}s"  # buttons, inputs, links, selects
        elements = self.selectors[page].get(element_group, {})
        
        if not elements:
            _LOGGER.warning("No %s found on page '%s'", element_group, page)
        
        # Search for functional matches
        candidates = []
        for elem_name, elem_data in elements.items():
            score = self._calculate_functional_match_score(
                elem_data, function_keywords, element_type
            )
            if score > 0:
                candidates.append((elem_name, score, elem_data))
        
        if candidates:
            # Sort by score (highest first)
            candidates.sort(key=lambda x: x[1], reverse=True)
            best_match = candidates[0]
            _LOGGER.info(
                "Semantic search found '%s' for keywords %s (score: %d)",
                best_match[0], function_keywords, best_match[1]
            )
            
            # Build selector path and find element
            selector_path = f"{page}.{element_group}.{best_match[0]}"
            return self._find_element(selector_path, timeout=timeout)
        
        # Fallback to explicit name if semantic search fails
        if fallback_name and fallback_name in elements:
            _LOGGER.info(
                "Semantic search failed, using fallback name '%s'", 
                fallback_name
            )
            selector_path = f"{page}.{element_group}.{fallback_name}"
            return self._find_element(selector_path, timeout=timeout)
        
        # No match found
        raise KeyError(
            f"No {element_type} found matching {function_keywords} on page '{page}' "
            f"(searched {len(elements)} elements). "
            f"Fallback name '{fallback_name}' also not found." if fallback_name 
            else f"No {element_type} found matching {function_keywords} on page '{page}' "
                 f"(searched {len(elements)} elements, no fallback provided)."
        )
    
    def _calculate_functional_match_score(
        self, 
        elem_data: dict, 
        keywords: list[str],
        element_type: str
    ) -> int:
        """Calculate how well element matches functional keywords.
        
        Scoring algorithm (Phase 5.2):
        - data-action (exact): 100 points
        - text (exact): 50 points
        - text (partial): 25 points
        - id (contains): 30 points
        - title/aria-label (contains): 20 points
        - class (contains): 10 points
        
        Args:
            elem_data: Element data from selectors.yaml
            keywords: List of functional keywords
            element_type: Type of element (for context)
            
        Returns:
            Score (higher = better match, 0 = no match)
        """
        score = 0
        
        # Normalize keywords for case-insensitive matching
        keywords_lower = [kw.lower() for kw in keywords]
        
        # Extract metadata attributes (Phase 5.1 captured these)
        text = (elem_data.get("text") or "").lower()
        title = (elem_data.get("title") or "").lower()
        aria_label = (elem_data.get("aria_label") or "").lower()
        data_action = (elem_data.get("data_action") or "").lower()
        
        # Element-specific IDs
        elem_id = (
            elem_data.get("button_id") or 
            elem_data.get("input_id") or 
            elem_data.get("select_id") or 
            elem_data.get("link_id") or 
            ""
        ).lower()
        
        # Element-specific classes
        elem_class = (
            elem_data.get("button_class") or 
            elem_data.get("link_class") or 
            elem_data.get("class") or 
            ""
        ).lower()
        
        # Additional attributes
        placeholder = (elem_data.get("placeholder") or "").lower()
        name = (elem_data.get("name") or "").lower()
        href = (elem_data.get("href") or "").lower()
        onclick_hint = (elem_data.get("onclick_hint") or "").lower()
        
        # Score each keyword
        for kw in keywords_lower:
            # Highest priority: data-action (explicit functional attribute)
            if data_action and kw in data_action:
                score += 100
            
            # High priority: exact match in text
            if text:
                if kw == text:
                    score += 50
                elif kw in text:
                    score += 25
            
            # Medium-high priority: ID contains keyword
            if elem_id and kw in elem_id:
                score += 30
            
            # Medium priority: title/aria-label (descriptive)
            if title and kw in title:
                score += 20
            if aria_label and kw in aria_label:
                score += 20
            
            # Medium-low priority: placeholder (for inputs)
            if placeholder and kw in placeholder:
                score += 15
            
            # Lower priority: class name hints
            if elem_class and kw in elem_class:
                score += 10
            
            # Additional signals
            if name and kw in name:
                score += 10
            if href and kw in href:
                score += 10
            if onclick_hint and kw in onclick_hint:
                score += 5
        
        return score
    
    def _get_current_page(self) -> str:
        """Determine current page from URL or page state.
        
        This is a simple implementation that can be overridden by
        device-specific components for more sophisticated page detection.
        
        Returns:
            Page name (defaults to first page in selectors)
        """
        # Simple implementation: return first page
        # Device-specific components should override this for better page detection
        if not self.selectors:
            raise ValueError("No selectors loaded")
        
        pages = list(self.selectors.keys())
        if not pages:
            raise ValueError("No pages found in selectors")
        
        # Return first page as default
        # TODO: Enhance with URL-based page detection in device-specific components
        return pages[0]