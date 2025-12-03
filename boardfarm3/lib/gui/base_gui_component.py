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
