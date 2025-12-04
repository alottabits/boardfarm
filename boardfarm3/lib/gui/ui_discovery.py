"""UI Discovery Tool for automated UI mapping and crawling.

This tool crawls a web UI, discovers pages and elements, and generates
a structured JSON map (ui_map.json) that represents the UI as a graph.
This map can be used for automated navigation path generation and
change detection.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

from selenium.common.exceptions import TimeoutException
from selenium.webdriver import Firefox
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

if TYPE_CHECKING:
    from selenium.webdriver.remote.webelement import WebElement

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class URLPatternDetector:
    """Detects and groups similar URL patterns.
    
    This class analyzes a collection of URLs to identify patterns where
    URLs share the same structure but differ in specific segments (e.g., IDs).
    It generates parameterized templates that represent these patterns.
    
    Example:
        URLs: [
            "#!/devices/ABC123",
            "#!/devices/DEF456",
            "#!/devices/GHI789"
        ]
        Pattern: "#!/devices/{device_id}"
    """
    
    def __init__(self, min_pattern_count: int = 3):
        """Initialize the pattern detector.
        
        Args:
            min_pattern_count: Minimum number of URLs required to form a pattern
        """
        self.min_pattern_count = min_pattern_count
    
    def detect_patterns(self, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Detect URL patterns from a list of pages.
        
        Args:
            pages: List of page dictionaries with 'url' field
            
        Returns:
            List of detected patterns with metadata
        """
        # Group URLs by structure
        url_groups = self._group_similar_urls(pages)
        
        patterns = []
        for group_key, group_pages in url_groups.items():
            if len(group_pages) >= self.min_pattern_count:
                pattern = self._create_pattern(group_pages)
                if pattern:
                    patterns.append(pattern)
        
        return patterns
    
    def _group_similar_urls(self, pages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """Group URLs with similar structure.
        
        Args:
            pages: List of page dictionaries
            
        Returns:
            Dictionary mapping group keys to lists of pages
        """
        groups: dict[str, list[dict[str, Any]]] = {}
        
        for page in pages:
            url = page.get("url", "")
            if not url:
                continue
            
            # Parse URL to get the path structure
            parsed = urlparse(url)
            
            # For hash-based SPAs, analyze the fragment
            path = parsed.fragment if parsed.fragment else parsed.path
            
            # Strip leading ! from hash fragments (e.g., #!/devices/123 -> /devices/123)
            if path.startswith("!"):
                path = path[1:]
            
            # Split path into segments
            segments = [s for s in path.split("/") if s]
            
            # Create a group key based on structure (number of segments and static parts)
            if len(segments) >= 2:
                # Use all segments except the last one as the group key
                # This groups URLs like #!/devices/ID1, #!/devices/ID2 together
                group_key = "/".join(segments[:-1])
            else:
                # For single-segment paths, use the full path
                group_key = path
            
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(page)
        
        return groups
    
    def _create_pattern(self, pages: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Create a pattern from a group of similar pages.
        
        Args:
            pages: List of page dictionaries with similar structure
            
        Returns:
            Pattern dictionary or None if pattern cannot be created
        """
        if not pages:
            return None
        
        # Get the first URL as reference
        first_url = pages[0].get("url", "")
        parsed = urlparse(first_url)
        
        # For hash-based SPAs, work with the fragment
        path = parsed.fragment if parsed.fragment else parsed.path
        
        # Strip leading ! from hash fragments (e.g., #!/devices/123 -> /devices/123)
        if path.startswith("!"):
            path = path[1:]
        
        segments = [s for s in path.split("/") if s]
        
        if len(segments) < 2:
            return None
        
        # Extract variable segments (last segment is typically the ID)
        static_parts = segments[:-1]
        variable_segment = segments[-1]
        
        # Determine parameter name based on context
        param_name = self._infer_parameter_name(static_parts, variable_segment)
        
        # Create pattern template
        if parsed.fragment:
            # Hash-based routing - reconstruct with #!/
            pattern_template = "#!/" + "/".join(static_parts) + f"/{{{param_name}}}"
        else:
            # Path-based routing
            pattern_template = "/" + "/".join(static_parts) + f"/{{{param_name}}}"
        
        # Collect example URLs and extract common page structure
        example_urls = [p.get("url", "") for p in pages[:5]]  # Keep up to 5 examples
        
        # Analyze common page structure
        page_structure = self._extract_common_structure(pages)
        
        return {
            "pattern": pattern_template,
            "description": self._generate_description(static_parts, param_name),
            "parameter_name": param_name,
            "example_urls": example_urls,
            "count": len(pages),
            "page_structure": page_structure,
        }
    
    def _infer_parameter_name(self, static_parts: list[str], variable_segment: str) -> str:
        """Infer a descriptive parameter name from the URL context.
        
        Args:
            static_parts: Static segments of the URL
            variable_segment: The variable segment (typically an ID)
            
        Returns:
            Inferred parameter name
        """
        if not static_parts:
            return "id"
        
        # Use the last static part to infer the parameter name
        last_static = static_parts[-1].lower()
        
        # Common mappings
        if "device" in last_static:
            return "device_id"
        elif "user" in last_static:
            return "user_id"
        elif "preset" in last_static:
            return "preset_id"
        elif "provision" in last_static:
            return "provision_id"
        elif "file" in last_static:
            return "file_id"
        else:
            return f"{last_static}_id"
    
    def _generate_description(self, static_parts: list[str], param_name: str) -> str:
        """Generate a human-readable description for the pattern.
        
        Args:
            static_parts: Static segments of the URL
            param_name: Parameter name
            
        Returns:
            Description string
        """
        if not static_parts:
            return f"Page with {param_name}"
        
        last_static = static_parts[-1]
        return f"{last_static.capitalize()} detail page"
    
    def _extract_common_structure(self, pages: list[dict[str, Any]]) -> dict[str, Any]:
        """Extract common structural elements from pages.
        
        Args:
            pages: List of page dictionaries
            
        Returns:
            Dictionary with common structural elements
        """
        if not pages:
            return {}
        
        # Use the first page as reference
        first_page = pages[0]
        
        return {
            "title_pattern": first_page.get("title", ""),
            "page_type": first_page.get("page_type", "unknown"),
            "common_buttons": self._find_common_elements(pages, "buttons"),
            "common_inputs": self._find_common_elements(pages, "inputs"),
        }
    
    def _find_common_elements(self, pages: list[dict[str, Any]], element_type: str) -> list[str]:
        """Find elements that appear in all pages.
        
        Args:
            pages: List of page dictionaries
            element_type: Type of element to analyze (e.g., 'buttons', 'inputs')
            
        Returns:
            List of common element descriptions
        """
        if not pages:
            return []
        
        # Get elements from first page
        first_elements = pages[0].get(element_type, [])
        common = []
        
        for element in first_elements:
            # Check if this element appears in all pages
            element_text = element.get("text", "") or element.get("title", "")
            if element_text and all(
                any(
                    e.get("text", "") == element_text or e.get("title", "") == element_text
                    for e in page.get(element_type, [])
                )
                for page in pages
            ):
                common.append(element_text)
        
        return common[:5]  # Limit to 5 common elements


class UIDiscoveryTool:
    """A generic tool to crawl a web UI and discover its structure.
    
    This tool navigates through a web application, discovering pages,
    elements, and navigation paths. It generates a comprehensive map
    of the UI structure that can be used for:
    - Automated test generation
    - Navigation path analysis
    - UI change detection
    - Selector extraction
    
    Attributes:
        base_url: Base URL of the application
        username: Login username (optional)
        password: Login password (optional)
        driver: Selenium WebDriver instance
        wait: WebDriverWait instance
        visited_urls: Set of already visited URLs
        navigation_graph: Graph of navigation relationships
        pages: List of discovered page information
    """

    def __init__(
        self,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        headless: bool = True,
        timeout: int = 10,
        enable_pattern_detection: bool = True,
        min_pattern_count: int = 3,
        enable_interaction_discovery: bool = False,
        safe_buttons: str = "New,Add,Edit,View,Show,Cancel,Close",
        interaction_timeout: int = 2,
    ):
        """Initialize the UI Discovery Tool.
        
        Args:
            base_url: Base URL of the application to crawl
            username: Optional login username
            password: Optional login password
            headless: Run browser in headless mode
            timeout: Default timeout for element waits
            enable_pattern_detection: Enable URL pattern detection
            min_pattern_count: Minimum URLs required to form a pattern
            enable_interaction_discovery: Enable button click and modal discovery
            safe_buttons: Comma-separated list of safe button text patterns
            interaction_timeout: Seconds to wait for modals after clicking
        """
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.enable_pattern_detection = enable_pattern_detection
        self.min_pattern_count = min_pattern_count
        self.enable_interaction_discovery = enable_interaction_discovery
        self.safe_buttons = safe_buttons
        self.interaction_timeout = interaction_timeout

        # Setup Firefox driver
        options = Options()
        if headless:
            options.add_argument("--headless")
        options.add_argument("--width=1920")
        options.add_argument("--height=1080")
        
        # Set preferences similar to gui_helper.py
        options.set_preference("security.enterprise_roots.enabled", True)
        options.set_preference("browser.download.folderList", 2)
        options.set_preference("browser.download.dir", "/tmp")
        
        # Set Firefox binary path for snap installation
        # Try snap location first, fall back to auto-detection
        import os
        snap_firefox = "/snap/firefox/current/usr/lib/firefox/firefox"
        if os.path.exists(snap_firefox):
            options.binary_location = snap_firefox
            logger.debug("Using snap Firefox at %s", snap_firefox)

        try:
            # Let Selenium auto-detect Firefox (works better with snap)
            self.driver = Firefox(options=options)
            logger.info("Firefox driver initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize Firefox driver: %s", e)
            logger.info("Make sure Firefox and geckodriver are installed")
            logger.info("  - Firefox: sudo apt install firefox OR sudo snap install firefox")
            logger.info("  - geckodriver: sudo snap install geckodriver")
            raise

        self.wait = WebDriverWait(self.driver, timeout)

        # Discovery state
        self.visited_urls: set[str] = set()
        self.navigation_graph: dict[str, Any] = {}
        self.pages: list[dict[str, Any]] = []

    def login(self, login_url: str | None = None) -> None:
        """Login to the application.
        
        Args:
            login_url: Optional custom login URL. If not provided,
                      will attempt to find login page from base_url.
        
        Raises:
            TimeoutException: If login elements are not found
        """
        if not self.username or not self.password:
            logger.info("No credentials provided, skipping login")
            return

        if login_url:
            logger.info("Navigating to custom login URL: %s", login_url)
            self.driver.get(login_url)
        else:
            logger.info("Navigating to base URL: %s", self.base_url)
            self.driver.get(self.base_url)

        try:
            # Check if we need to click a login link first
            try:
                # fast check for username field
                self.wait.until(
                    EC.presence_of_element_located((By.NAME, "username"))
                )
                logger.info("Already on login page")
            except TimeoutException:
                logger.info("Username field not found, looking for 'Log in' link")
                try:
                    login_link = self.wait.until(
                        EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "Log in"))
                    )
                    login_link.click()
                    logger.info("Clicked 'Log in' link")
                except TimeoutException:
                    logger.warning("Could not find 'Log in' link, assuming we are on login page or it will load")

            # Find username field
            username_field = None
            for selector in [
                (By.NAME, "username"),
                (By.CSS_SELECTOR, "input[name='username']"),
                (By.ID, "username"),
                (By.CSS_SELECTOR, "input[type='text']"),
            ]:
                try:
                    username_field = self.wait.until(
                        EC.visibility_of_element_located(selector)
                    )
                    break
                except TimeoutException:
                    continue

            if not username_field:
                raise TimeoutException("Could not find username field")

            username_field.clear()
            username_field.send_keys(self.username)

            # Find password field
            password_field = None
            for selector in [
                (By.NAME, "password"),
                (By.CSS_SELECTOR, "input[name='password']"),
                (By.CSS_SELECTOR, "input[type='password']"),
            ]:
                try:
                    password_field = self.wait.until(
                        EC.visibility_of_element_located(selector)
                    )
                    break
                except TimeoutException:
                    continue
            
            if not password_field:
                 raise TimeoutException("Could not find password field")

            password_field.clear()
            password_field.send_keys(self.password)

            # Find and click submit button
            submit_btn = None
            for selector in [
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(text(), 'Login')]"),
                (By.CSS_SELECTOR, "button.primary"),
            ]:
                 try:
                    submit_btn = self.wait.until(
                        EC.element_to_be_clickable(selector)
                    )
                    break
                 except TimeoutException:
                    continue
            
            if not submit_btn:
                raise TimeoutException("Could not find login button")

            submit_btn.click()

            # Wait for redirect away from login page
            # This is tricky with SPAs, so we wait for the URL to change or the login form to disappear
            try:
                self.wait.until(EC.staleness_of(submit_btn))
            except TimeoutException:
                pass
            
            logger.info("Login successful")

        except Exception as e:
            logger.error("Login failed: %s", e)
            logger.error("Current URL: %s", self.driver.current_url)
            logger.error("Page Title: %s", self.driver.title)
            try:
                self.driver.save_screenshot("login_failure.png")
                logger.info("Saved screenshot to login_failure.png")
            except Exception:
                pass
            raise

    def discover_site(
        self,
        start_url: str | None = None,
        max_depth: int = 3,
        login_first: bool = True,
        login_url: str | None = None,
    ) -> dict[str, Any]:
        """Crawl the entire UI and return a structured map.
        
        Args:
            start_url: Optional starting URL. If not provided, uses base_url
            max_depth: Maximum crawl depth
            login_first: Whether to login before crawling
            login_url: Optional custom login URL
            
        Returns:
            Dictionary containing:
                - base_url: Base URL of the application
                - pages: List of discovered pages with elements
                - url_patterns: List of detected URL patterns (if enabled)
                - navigation_graph: Graph of navigation relationships
        """
        try:
            if login_first:
                self.login(login_url=login_url)
                start_url = start_url or self.driver.current_url
            else:
                start_url = start_url or self.base_url
                self.driver.get(start_url)

            logger.info("Starting discovery from %s", start_url)
            self._crawl_page(start_url, depth=0, max_depth=max_depth)

            # Detect URL patterns if enabled
            url_patterns = []
            if self.enable_pattern_detection:
                logger.info("Detecting URL patterns...")
                detector = URLPatternDetector(min_pattern_count=self.min_pattern_count)
                url_patterns = detector.detect_patterns(self.pages)
                logger.info("Detected %d URL patterns", len(url_patterns))

            return {
                "base_url": self.base_url,
                "pages": self.pages,
                "url_patterns": url_patterns,
                "navigation_graph": self.navigation_graph,
            }

        finally:
            self.close()

    def _crawl_page(self, url: str, depth: int, max_depth: int) -> None:
        """Recursively crawl pages to discover navigation paths.
        
        Args:
            url: URL to crawl
            depth: Current crawl depth
            max_depth: Maximum depth to crawl
        """
        if depth > max_depth:
            logger.debug("Max depth reached, skipping %s", url)
            return

        # Normalize URL
        normalized_url = self._normalize_url(url)

        if normalized_url in self.visited_urls:
            logger.debug("Already visited %s", normalized_url)
            return

        logger.info("Crawling: %s (depth: %d)", normalized_url, depth)
        self.visited_urls.add(normalized_url)

        try:
            self.driver.get(url)
            self.wait.until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            # Discover page elements
            page_info = self._discover_page_info(normalized_url)
            self.pages.append(page_info)

            # Find all navigation links
            links = self._find_navigation_links()

            # Store navigation graph
            self.navigation_graph[normalized_url] = {
                "title": page_info["title"],
                "page_type": page_info["page_type"],
                "links": [
                    {"href": link["href"], "text": link["text"], "selector": link["css_selector"]}
                    for link in links
                ],
            }

            # Recursively crawl linked pages
            for link in links:
                if self._is_internal_link(link["href"]):
                    self._crawl_page(link["href"], depth + 1, max_depth)

        except Exception as e:
            logger.error("Error crawling %s: %s", url, e)

    def _discover_page_info(self, url: str) -> dict[str, Any]:
        """Discover information about the current page.
        
        Args:
            url: URL of the current page
            
        Returns:
            Dictionary containing page information
        """
        page_info = {
            "url": url,
            "title": self.driver.title,
            "page_type": self._classify_page(url),
            "buttons": self._discover_buttons(),
            "inputs": self._discover_inputs(),
            "links": self._discover_links(),
            "tables": self._discover_tables(),
        }
        
        # Add interaction discovery if enabled
        if self.enable_interaction_discovery:
            page_info["interactions"] = self._discover_interactions(url)
        
        return page_info

    def _classify_page(self, url: str) -> str:
        """Classify the page type based on URL patterns.
        
        Args:
            url: URL to classify
            
        Returns:
            Page type string
        """
        path = urlparse(url).path.lower()

        # Common patterns
        if "/login" in path:
            return "login"
        if "/devices/" in path and len(path.split("/")) > 2:
            return "device_details"
        if "/devices" in path:
            return "device_list"
        if "/tasks" in path:
            return "tasks"
        if "/files" in path:
            return "files"
        if "/presets" in path:
            return "presets"
        if "/admin" in path:
            return "admin"
        if path == "/" or path == "":
            return "home"

        return "unknown"

    def _find_navigation_links(self) -> list[dict[str, str]]:
        """Find all navigation links on the current page.
        
        Returns:
            List of link dictionaries with text, href, and selector
        """
        links = []
        for link in self.driver.find_elements(By.TAG_NAME, "a"):
            href = link.get_attribute("href")
            
            # Debug logging for href type
            if href and not isinstance(href, str):
                logger.warning("Found non-string href: %s (type: %s)", href, type(href))
                continue

            if href and self._is_internal_link(href):
                links.append({
                    "text": link.text.strip() or "(no text)",
                    "href": href,
                    "css_selector": self._get_css_selector(link),
                })
        return links

    def _is_internal_link(self, href: str) -> bool:
        """Check if link is internal to the application.
        
        Args:
            href: Link href attribute
            
        Returns:
            True if internal, False otherwise
        """
        if not href:
            return False

        if not isinstance(href, str):
            logger.warning("Internal link check received non-string: %s", type(href))
            return False

        # Skip javascript: and mailto: links
        if href.startswith(("javascript:", "mailto:", "#")):
            return False

        parsed = urlparse(href)
        base_parsed = urlparse(self.base_url)

        # Same domain or relative URL
        return not parsed.netloc or parsed.netloc == base_parsed.netloc

    def _discover_buttons(self) -> list[dict[str, Any]]:
        """Discover all buttons on the page.
        
        Returns:
            List of button dictionaries
        """
        buttons = []
        for btn in self.driver.find_elements(By.TAG_NAME, "button"):
            buttons.append({
                "text": btn.text.strip(),
                "title": btn.get_attribute("title"),
                "id": btn.get_attribute("id"),
                "class": btn.get_attribute("class"),
                "css_selector": self._get_css_selector(btn),
            })
        return buttons

    def _discover_inputs(self) -> list[dict[str, Any]]:
        """Discover all input fields on the page.
        
        Returns:
            List of input dictionaries
        """
        inputs = []
        for inp in self.driver.find_elements(By.TAG_NAME, "input"):
            inputs.append({
                "type": inp.get_attribute("type"),
                "name": inp.get_attribute("name"),
                "id": inp.get_attribute("id"),
                "placeholder": inp.get_attribute("placeholder"),
                "css_selector": self._get_css_selector(inp),
            })
        return inputs

    def _discover_links(self) -> list[dict[str, Any]]:
        """Discover all links on the page.
        
        Returns:
            List of link dictionaries
        """
        links = []
        for link in self.driver.find_elements(By.TAG_NAME, "a"):
            href = link.get_attribute("href")
            if href:
                links.append({
                    "text": link.text.strip(),
                    "href": href,
                    "css_selector": self._get_css_selector(link),
                })
        return links

    def _discover_tables(self) -> list[dict[str, Any]]:
        """Discover all tables on the page.
        
        Returns:
            List of table dictionaries
        """
        tables = []
        for table in self.driver.find_elements(By.TAG_NAME, "table"):
            headers = [
                th.text.strip() for th in table.find_elements(By.TAG_NAME, "th")
            ]
            tables.append({
                "id": table.get_attribute("id"),
                "class": table.get_attribute("class"),
                "headers": headers,
                "css_selector": self._get_css_selector(table),
            })
        return tables

    def _get_css_selector(self, element: WebElement) -> str:
        """Generate CSS selector for element.
        
        Prioritizes ID, then class, then tag name.
        
        Args:
            element: WebElement to generate selector for
            
        Returns:
            CSS selector string
        """
        elem_id = element.get_attribute("id")
        if elem_id:
            return f"#{elem_id}"

        elem_class = element.get_attribute("class")
        if elem_class:
            first_class = elem_class.split()[0]
            return f".{first_class}"

        return element.tag_name

    def _normalize_url(self, url: str) -> str:
        """Normalize URL by removing query parameters but KEEPING fragments for SPAs.
        
        Args:
            url: URL to normalize
            
        Returns:
            Normalized URL
        """
        parsed = urlparse(url)
        # For SPAs, the fragment is critical. We keep scheme, netloc, path, and fragment.
        # We strip query params (?) as they often contain session IDs or filters.
        # We also ensure consistent trailing slash handling.
        
        path = parsed.path.rstrip("/")
        if not path:
            path = "/"
            
        return f"{parsed.scheme}://{parsed.netloc}{path}{'#' + parsed.fragment if parsed.fragment else ''}"

    def _discover_interactions(self, page_url: str) -> list[dict[str, Any]]:
        """Discover interactive elements by clicking buttons.
        
        Args:
            page_url: Current page URL for state recovery
            
        Returns:
            List of discovered interactions
        """
        if not self.enable_interaction_discovery:
            return []
        
        interactions = []
        buttons = self._find_safe_buttons()
        
        logger.info("Discovering interactions: found %d safe buttons to test", len(buttons))
        
        for button in buttons:
            try:
                # Record initial state
                initial_url = self.driver.current_url
                button_text = button.text.strip()
                
                logger.debug("Clicking button: %s", button_text)
                
                # Click button
                button.click()
                time.sleep(self.interaction_timeout)
                
                # Check for modal
                modal = self._detect_modal()
                if modal:
                    logger.info("Modal detected after clicking '%s'", button_text)
                    interaction = {
                        "trigger": {
                            "type": "button",
                            "text": button_text,
                            "selector": self._get_css_selector(button),
                        },
                        "result": modal,
                    }
                    interactions.append(interaction)
                    
                    # Close modal
                    self._close_modal()
                    time.sleep(0.5)
                
                # Restore state if URL changed
                if self.driver.current_url != initial_url:
                    logger.debug("URL changed, navigating back to %s", page_url)
                    self.driver.get(page_url)
                    self.wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
                    
            except Exception as e:
                logger.debug("Error clicking button '%s': %s", button.text if hasattr(button, 'text') else 'unknown', e)
                # Try to recover
                try:
                    self.driver.get(page_url)
                    self.wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
                except:
                    pass
        
        return interactions

    def _find_safe_buttons(self) -> list[WebElement]:
        """Find buttons that are safe to click.
        
        Returns:
            List of safe button WebElements
        """
        all_buttons = self.driver.find_elements(By.TAG_NAME, "button")
        safe_patterns = [p.strip().lower() for p in self.safe_buttons.split(",")]
        
        safe_buttons = []
        for button in all_buttons:
            try:
                if not button.is_displayed() or not button.is_enabled():
                    continue
                    
                button_text = button.text.strip().lower()
                button_title = (button.get_attribute("title") or "").strip().lower()
                button_aria = (button.get_attribute("aria-label") or "").strip().lower()
                
                # Check if button text/title/aria-label matches safe patterns
                if any(pattern in button_text or pattern in button_title or pattern in button_aria
                       for pattern in safe_patterns):
                    safe_buttons.append(button)
            except:
                continue
        
        return safe_buttons

    def _detect_modal(self) -> dict[str, Any] | None:
        """Detect if a modal/dialog is currently visible.
        
        Returns:
            Modal info dict if detected, None otherwise
        """
        # Common modal selectors
        modal_selectors = [
            ".modal.show",
            ".modal.in",
            ".dialog[open]",
            "[role='dialog']",
            ".overlay.visible",
            ".popup.visible",
            "div[class*='modal'][style*='display: block']",
        ]
        
        for selector in modal_selectors:
            try:
                modals = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for modal in modals:
                    if modal.is_displayed():
                        return self._capture_modal_info(modal)
            except:
                continue
        
        return None

    def _capture_modal_info(self, modal_element: WebElement) -> dict[str, Any]:
        """Capture information about a modal/dialog.
        
        Args:
            modal_element: WebElement of the modal
            
        Returns:
            Dictionary with modal information
        """
        return {
            "type": "modal",
            "title": self._get_modal_title(modal_element),
            "buttons": self._discover_buttons_in_element(modal_element),
            "inputs": self._discover_inputs_in_element(modal_element),
            "selects": self._discover_selects_in_element(modal_element),
            "css_selector": self._get_css_selector(modal_element),
        }

    def _get_modal_title(self, modal_element: WebElement) -> str:
        """Extract title from modal element.
        
        Args:
            modal_element: Modal WebElement
            
        Returns:
            Modal title or empty string
        """
        title_selectors = [
            ".modal-title",
            ".dialog-title",
            "h1", "h2", "h3",
            "[class*='title']",
        ]
        
        for selector in title_selectors:
            try:
                title_elem = modal_element.find_element(By.CSS_SELECTOR, selector)
                if title_elem.text.strip():
                    return title_elem.text.strip()
            except:
                continue
        
        return ""

    def _discover_buttons_in_element(self, element: WebElement) -> list[dict[str, Any]]:
        """Discover buttons within a specific element.
        
        Args:
            element: Parent WebElement
            
        Returns:
            List of button dictionaries
        """
        buttons = []
        for btn in element.find_elements(By.TAG_NAME, "button"):
            try:
                if btn.is_displayed():
                    buttons.append({
                        "text": btn.text.strip(),
                        "type": btn.get_attribute("type"),
                        "class": btn.get_attribute("class"),
                        "css_selector": self._get_css_selector(btn),
                    })
            except:
                continue
        return buttons

    def _discover_inputs_in_element(self, element: WebElement) -> list[dict[str, Any]]:
        """Discover input fields within a specific element.
        
        Args:
            element: Parent WebElement
            
        Returns:
            List of input dictionaries
        """
        inputs = []
        for inp in element.find_elements(By.TAG_NAME, "input"):
            try:
                if inp.is_displayed():
                    inputs.append({
                        "type": inp.get_attribute("type"),
                        "name": inp.get_attribute("name"),
                        "placeholder": inp.get_attribute("placeholder"),
                        "required": inp.get_attribute("required") is not None,
                        "css_selector": self._get_css_selector(inp),
                    })
            except:
                continue
        return inputs

    def _discover_selects_in_element(self, element: WebElement) -> list[dict[str, Any]]:
        """Discover select dropdowns within a specific element.
        
        Args:
            element: Parent WebElement
            
        Returns:
            List of select dictionaries
        """
        selects = []
        for select in element.find_elements(By.TAG_NAME, "select"):
            try:
                if select.is_displayed():
                    options = [opt.text.strip() for opt in select.find_elements(By.TAG_NAME, "option")]
                    selects.append({
                        "name": select.get_attribute("name"),
                        "options": options,
                        "css_selector": self._get_css_selector(select),
                    })
            except:
                continue
        return selects

    def _close_modal(self) -> None:
        """Attempt to close any open modal."""
        from selenium.webdriver.common.keys import Keys
        
        # Try common close methods
        close_selectors = [
            "button.close",
            "[aria-label='Close']",
            "button:contains('Cancel')",
            "button:contains('Close')",
            ".modal-close",
            ".dialog-close",
        ]
        
        for selector in close_selectors:
            try:
                close_btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                if close_btn.is_displayed():
                    close_btn.click()
                    time.sleep(0.3)
                    return
            except:
                continue
        
        # Fallback: ESC key
        try:
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            time.sleep(0.3)
        except:
            pass

    def close(self) -> None:
        """Close the browser."""
        if self.driver:
            self.driver.quit()
            logger.info("Browser closed")


def main():
    """Command-line interface for UI discovery tool."""
    parser = argparse.ArgumentParser(
        description="Discover and map UI structure for automated testing"
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Base URL of the application to crawl",
    )
    parser.add_argument(
        "--output",
        default="ui_map.json",
        help="Output file for UI map (default: ui_map.json)",
    )
    parser.add_argument(
        "--username",
        help="Login username (optional)",
    )
    parser.add_argument(
        "--password",
        help="Login password (optional)",
    )
    parser.add_argument(
        "--login-url",
        help="Custom login URL (optional)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=3,
        help="Maximum crawl depth (default: 3)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode (default: True)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_false",
        dest="headless",
        help="Run browser with GUI",
    )
    parser.add_argument(
        "--no-login",
        action="store_true",
        help="Skip login step",
    )
    parser.add_argument(
        "--disable-pattern-detection",
        action="store_true",
        help="Disable URL pattern detection (default: enabled)",
    )
    parser.add_argument(
        "--pattern-min-count",
        type=int,
        default=3,
        help="Minimum URLs required to form a pattern (default: 3)",
    )
    parser.add_argument(
        "--discover-interactions",
        action="store_true",
        help="Discover modals and dialogs by clicking buttons (default: disabled)",
    )
    parser.add_argument(
        "--safe-buttons",
        default="New,Add,Edit,View,Show,Cancel,Close",
        help="Comma-separated list of safe button text patterns to click (default: New,Add,Edit,View,Show,Cancel,Close)",
    )
    parser.add_argument(
        "--interaction-timeout",
        type=int,
        default=2,
        help="Seconds to wait for modals to appear after clicking (default: 2)",
    )

    args = parser.parse_args()

    # Create discovery tool
    tool = UIDiscoveryTool(
        base_url=args.url,
        username=args.username,
        password=args.password,
        headless=args.headless,
        enable_pattern_detection=not args.disable_pattern_detection,
        min_pattern_count=args.pattern_min_count,
        enable_interaction_discovery=args.discover_interactions,
        safe_buttons=args.safe_buttons,
        interaction_timeout=args.interaction_timeout,
    )

    # Discover site
    logger.info("Starting UI discovery for %s", args.url)
    ui_map = tool.discover_site(
        max_depth=args.max_depth,
        login_first=not args.no_login,
        login_url=args.login_url,
    )

    # Save to file
    output_path = Path(args.output)
    with output_path.open("w") as f:
        json.dump(ui_map, f, indent=2)

    logger.info("UI map saved to %s", output_path)
    logger.info("Discovered %d pages", len(ui_map["pages"]))


if __name__ == "__main__":
    main()
