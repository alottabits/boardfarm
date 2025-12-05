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
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver import Firefox
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from boardfarm3.lib.gui.ui_graph import UIGraph

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
    """Web UI crawler with NetworkX graph representation and BFS traversal.
    
    This tool navigates through a web application using breadth-first search,
    discovering pages, modals, forms, and elements. It builds a NetworkX
    graph that can be used for:
    - Automated test generation
    - Navigation path analysis (shortest path, all paths)
    - UI change detection
    - Selector extraction
    - Quality checks (orphaned elements, dead-end pages)
    
    Attributes:
        base_url: Base URL of the application
        username: Login username (optional)
        password: Login password (optional)
        driver: Selenium WebDriver instance
        wait: WebDriverWait instance
        graph: UIGraph instance (NetworkX-based)
        visited_urls: Set of already visited URLs
        frontier: BFS queue of URLs to visit
        current_level: Current BFS level
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
        skip_pattern_duplicates: bool = False,
        pattern_sample_size: int = 3,
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
            skip_pattern_duplicates: Skip URLs matching detected patterns after sampling
            pattern_sample_size: Number of pattern instances to crawl before skipping
        """
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.enable_pattern_detection = enable_pattern_detection
        self.min_pattern_count = min_pattern_count
        self.enable_interaction_discovery = enable_interaction_discovery
        self.safe_buttons = safe_buttons
        self.interaction_timeout = interaction_timeout
        self.skip_pattern_duplicates = skip_pattern_duplicates
        self.pattern_sample_size = pattern_sample_size

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

        # NetworkX graph for UI structure
        self.graph = UIGraph()
        
        # BFS crawl state
        self.visited_urls: set[str] = set()
        self.frontier: deque[str] = deque()  # BFS queue
        self.current_level: int = 0
        self.max_pages: int = 1000  # Safety limit
        
        # Pattern-based skipping state
        self.pattern_tracker: dict[str, list[str]] = {}  # structure -> [urls]
        self.detected_patterns: set[str] = set()  # Patterns we're skipping
        self.skipped_urls: list[dict[str, str]] = []  # Track skipped URLs for stats

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
        login_first: bool = True,
        login_url: str | None = None,
    ) -> dict[str, Any]:
        """Crawl the UI using breadth-first search with leaf tracking.
        
        Uses BFS to systematically discover all reachable pages level by level.
        Natural stopping condition: no new leaves found.
        
        Args:
            start_url: Optional starting URL. If not provided, uses base_url
            login_first: Whether to login before crawling
            login_url: Optional custom login URL
            
        Returns:
            Dictionary containing:
                - base_url: Base URL of the application
                - discovery_method: "breadth_first_search"
                - levels_explored: Number of BFS levels
                - graph: NetworkX graph in node-link format
                - statistics: Graph statistics
                - discovery_stats: Crawl statistics
        """
        try:
            # Login if needed
            if login_first:
                self.login(login_url=login_url)
                start_url = start_url or self.driver.current_url
            else:
                start_url = start_url or self.base_url
                self.driver.get(start_url)

            logger.info("Starting BFS discovery from %s", start_url)
            
            # Initialize frontier with start URL
            self.frontier.append(start_url)
            
            # BFS crawl with leaf tracking
            while self.frontier and len(self.visited_urls) < self.max_pages:
                # Process entire level
                level_size = len(self.frontier)
                logger.info(
                    "Level %d: Processing %d pages", 
                    self.current_level, 
                    level_size
                )
                
                new_leaves = []
                
                for _ in range(level_size):
                    if not self.frontier:
                        break
                    
                    url = self.frontier.popleft()
                    
                    # Skip if already visited
                    normalized_url = self._normalize_url(url)
                    if normalized_url in self.visited_urls:
                        continue
                    
                    # Crawl the page and get new leaves
                    leaves = self._discover_page(normalized_url)
                    new_leaves.extend(leaves)
                
                # Add new leaves to frontier for next level
                self.frontier.extend(new_leaves)
                self.current_level += 1
                
                logger.info(
                    "Level %d complete: Discovered %d new pages", 
                    self.current_level - 1,
                    len(new_leaves)
                )
            
            # Check if we hit the safety limit
            if len(self.visited_urls) >= self.max_pages:
                logger.warning(
                    "Reached max_pages limit (%d). Discovery may be incomplete.",
                    self.max_pages
                )
            
            logger.info(
                "BFS discovery complete: %d pages discovered across %d levels",
                len(self.visited_urls),
                self.current_level
            )

            # Compile discovery statistics
            discovery_stats = {
                "pages_crawled": len(self.visited_urls),
                "pages_skipped": len(self.skipped_urls),
                "patterns_detected_during_crawl": len(self.detected_patterns),
                "pattern_skipping_enabled": self.skip_pattern_duplicates,
                "pattern_sample_size": self.pattern_sample_size if self.skip_pattern_duplicates else None,
                "levels_explored": self.current_level,
            }
            
            # Add skipped URLs details if any
            if self.skipped_urls:
                discovery_stats["skipped_urls"] = self.skipped_urls

            # Export graph data
            return {
                "base_url": self.base_url,
                "discovery_method": "breadth_first_search",
                "levels_explored": self.current_level,
                "graph": self.graph.export_node_link(),
                "statistics": self.graph.get_statistics(),
                "discovery_stats": discovery_stats,
            }

        finally:
            self.close()

    def _discover_page(self, url: str) -> list[str]:
        """Discover a single page and return new leaves.
        
        Populates the graph with page, elements, and navigation edges.
        Returns list of newly discovered URLs (leaves) for BFS.
        
        Args:
            url: URL to discover (already normalized)
            
        Returns:
            List of new URLs to add to frontier (leaves)
        """
        # Check if we should skip this URL based on pattern matching
        should_skip, skip_reason = self._should_skip_url(url)
        if should_skip:
            logger.info("Skipping %s: %s", url, skip_reason)
            return []

        logger.info("Discovering: %s", url)

        try:
            # Navigate to page
            self.driver.get(url)
            self.wait.until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            # Additional wait for SPAs to settle after navigation
            time.sleep(0.5)

            # Add page to graph
            page_type = self._classify_page(url)
            self.graph.add_page(
                url=url,
                title=self.driver.title,
                page_type=page_type
            )
            
            # Discover elements and add to graph
            self._discover_elements(url)
            
            # Discover interactions if enabled (creates modal nodes)
            if self.enable_interaction_discovery:
                self._discover_interactions(url)
                # Extra stabilization after interactions
                time.sleep(1.0)
            
            # Find all navigation links and add to graph
            leaves = self._find_links(url)
            
            # Mark as visited only after successful discovery
            self.visited_urls.add(url)
            
            # Track this successful crawl for pattern detection
            self._track_successful_crawl(url)
            
            return leaves
            
        except Exception as e:
            logger.error("Error discovering %s: %s", url, e)
            logger.debug("Failed page will not be marked as visited, allowing potential retry")
            # Don't add to visited_urls so it can be retried if encountered again
            return []

    def _discover_elements(self, page_url: str):
        """Discover and add all elements on current page to graph.
        
        Discovers buttons, inputs, and tables, adding them to the graph
        with visibility tracking.
        
        Args:
            page_url: URL of the current page
        """
        # Discover buttons
        button_elements = self.driver.find_elements(By.TAG_NAME, "button")
        for i, btn in enumerate(button_elements):
            try:
                # Extract attributes immediately to avoid stale element issues
                text = btn.text.strip()
                title = btn.get_attribute("title")
                btn_id = btn.get_attribute("id")
                btn_class = btn.get_attribute("class")
                btn_type = btn.get_attribute("type")
                css_selector = self._get_css_selector(btn)
                is_visible = btn.is_displayed()
                
                self.graph.add_element(
                    page_url,
                    "button",
                    "css",
                    css_selector,
                    text=text,
                    title=title,
                    button_id=btn_id,
                    button_class=btn_class,
                    button_type=btn_type,
                    visibility_observed="visible" if is_visible else "hidden"
                )
            except StaleElementReferenceException:
                logger.debug("Skipping stale button element %d", i)
                continue
            except Exception as e:
                logger.debug("Error processing button element %d: %s", i, e)
                continue
        
        # Discover inputs
        input_elements = self.driver.find_elements(By.TAG_NAME, "input")
        for i, inp in enumerate(input_elements):
            try:
                # Extract attributes immediately to avoid stale element issues
                input_type = inp.get_attribute("type")
                name = inp.get_attribute("name")
                inp_id = inp.get_attribute("id")
                placeholder = inp.get_attribute("placeholder")
                css_selector = self._get_css_selector(inp)
                is_visible = inp.is_displayed()
                
                self.graph.add_element(
                    page_url,
                    "input",
                    "css",
                    css_selector,
                    input_type=input_type,
                    name=name,
                    input_id=inp_id,
                    placeholder=placeholder,
                    visibility_observed="visible" if is_visible else "hidden"
                )
            except StaleElementReferenceException:
                logger.debug("Skipping stale input element %d", i)
                continue
            except Exception as e:
                logger.debug("Error processing input element %d: %s", i, e)
                continue
        
        # Discover select elements
        select_elements = self.driver.find_elements(By.TAG_NAME, "select")
        for i, sel in enumerate(select_elements):
            try:
                name = sel.get_attribute("name")
                sel_id = sel.get_attribute("id")
                css_selector = self._get_css_selector(sel)
                is_visible = sel.is_displayed()
                
                self.graph.add_element(
                    page_url,
                    "select",
                    "css",
                    css_selector,
                    name=name,
                    select_id=sel_id,
                    visibility_observed="visible" if is_visible else "hidden"
                )
            except StaleElementReferenceException:
                logger.debug("Skipping stale select element %d", i)
                continue
            except Exception as e:
                logger.debug("Error processing select element %d: %s", i, e)
                continue

    def _classify_page(self, url: str) -> str:
        """Classify the page type based on URL patterns.
        
        Strips query parameters before classification to ensure consistent
        page types (e.g., #!/devices?filter=X -> device_list, not device_details).
        
        Args:
            url: URL to classify
            
        Returns:
            Page type string
        """
        parsed = urlparse(url)
        # For hash-based SPAs, use the fragment; otherwise use path
        path = (parsed.fragment if parsed.fragment else parsed.path).lower()
        
        # Strip query parameters from path/fragment before classification
        if '?' in path:
            path = path.split('?')[0]
        
        # Strip leading ! from hash fragments (e.g., #!/devices -> /devices)
        if path.startswith("!"):
            path = path[1:]

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
        if "/faults" in path:
            return "faults"
        if "/presets" in path:
            return "presets"
        if "/provisions" in path:
            return "provisions"
        if "/virtualparameters" in path:
            return "virtual_parameters"
        if "/config" in path:
            return "config"
        if "/permissions" in path:
            return "permissions"
        if "/users" in path:
            return "users"
        if "/admin" in path:
            return "admin"
        if path == "/" or path == "#!/overview" or "/overview" in path:
            return "home"

        return "unknown"

    def _find_links(self, current_page_url: str) -> list[str]:
        """Find all internal navigation links on current page.
        
        Adds link elements to graph, creates navigation edges, and returns
        list of new URLs to explore (leaves). Handles both HTML and SVG links.
        
        Args:
            current_page_url: Current page URL
            
        Returns:
            List of new URLs to add to frontier (leaves)
        """
        leaves = []
        link_elements = self.driver.find_elements(By.TAG_NAME, "a")
        
        for i, link in enumerate(link_elements):
            try:
                # Extract attributes immediately to avoid stale element issues
                href = link.get_attribute("href")
                text = link.text.strip() or "(no text)"
                css_selector = self._get_css_selector(link)
                is_visible = link.is_displayed()
                
                # Handle SVG href (returns dict with baseVal/animVal)
                is_svg_link = False
                if href and isinstance(href, dict):
                    # SVG elements return href as {'baseVal': '...', 'animVal': '...'}
                    href = href.get('baseVal') or href.get('animVal')
                    is_svg_link = True
                    logger.info("Extracted href from SVG element: %s", href)
                
                # Validate href is now a string
                if href and not isinstance(href, str):
                    logger.warning("Found non-string href after extraction: %s (type: %s)", href, type(href))
                    continue

                if href and self._is_internal_link(href):
                    normalized_href = self._normalize_url(href)
                    
                    # Determine element type (svg_link for SVG elements, link for HTML)
                    element_type = "svg_link" if is_svg_link else "link"
                    
                    # Add link element to graph
                    link_elem_id = self.graph.add_element(
                        current_page_url,
                        element_type,
                        "css",
                        css_selector,
                        text=text,
                        href=normalized_href,
                        visibility_observed="visible" if is_visible else "hidden"
                    )
                    
                    # Add navigation relationship
                    self.graph.add_navigation_link(
                        from_page=current_page_url,
                        to_page=normalized_href,
                        via_element=link_elem_id,
                        action="click"
                    )
                    
                    # Add to leaves if not yet visited
                    if normalized_href not in self.visited_urls:
                        leaves.append(normalized_href)
                        
            except StaleElementReferenceException:
                # Element became stale (DOM changed), skip it
                logger.debug("Skipping stale link element %d", i)
                continue
            except Exception as e:
                logger.debug("Error processing link element %d: %s", i, e)
                continue
                
        return leaves

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

        # Skip API endpoints and download files
        if any(href.endswith(ext) for ext in [".csv", ".json", ".xml", ".pdf", ".zip", ".tar", ".gz"]):
            logger.debug("Skipping API/download endpoint: %s", href)
            return False
        
        if "/api/" in href.lower():
            logger.debug("Skipping API endpoint: %s", href)
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
        button_elements = self.driver.find_elements(By.TAG_NAME, "button")
        
        for i, btn in enumerate(button_elements):
            try:
                # Extract attributes immediately to avoid stale element issues
                buttons.append({
                    "text": btn.text.strip(),
                    "title": btn.get_attribute("title"),
                    "id": btn.get_attribute("id"),
                    "class": btn.get_attribute("class"),
                    "css_selector": self._get_css_selector(btn),
                })
            except StaleElementReferenceException:
                logger.debug("Skipping stale button element %d", i)
                continue
            except Exception as e:
                logger.debug("Error processing button element %d: %s", i, e)
                continue
                
        return buttons

    def _discover_inputs(self) -> list[dict[str, Any]]:
        """Discover all input fields on the page.
        
        Returns:
            List of input dictionaries
        """
        inputs = []
        input_elements = self.driver.find_elements(By.TAG_NAME, "input")
        
        for i, inp in enumerate(input_elements):
            try:
                # Extract attributes immediately to avoid stale element issues
                inputs.append({
                    "type": inp.get_attribute("type"),
                    "name": inp.get_attribute("name"),
                    "id": inp.get_attribute("id"),
                    "placeholder": inp.get_attribute("placeholder"),
                    "css_selector": self._get_css_selector(inp),
                })
            except StaleElementReferenceException:
                logger.debug("Skipping stale input element %d", i)
                continue
            except Exception as e:
                logger.debug("Error processing input element %d: %s", i, e)
                continue
                
        return inputs

    def _discover_links(self) -> list[dict[str, Any]]:
        """Discover all links on the page.
        
        Returns:
            List of link dictionaries
        """
        links = []
        link_elements = self.driver.find_elements(By.TAG_NAME, "a")
        
        for i, link in enumerate(link_elements):
            try:
                # Extract attributes immediately to avoid stale element issues
                href = link.get_attribute("href")
                if href:
                    links.append({
                        "text": link.text.strip(),
                        "href": href,
                        "css_selector": self._get_css_selector(link),
                    })
            except StaleElementReferenceException:
                logger.debug("Skipping stale link element %d", i)
                continue
            except Exception as e:
                logger.debug("Error processing link element %d: %s", i, e)
                continue
                
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
        
        Query parameters are stripped from both the main URL and the fragment
        to ensure consistent page identity (e.g., #!/devices?filter=X -> #!/devices).
        
        Args:
            url: URL to normalize
            
        Returns:
            Normalized URL without query parameters
        """
        parsed = urlparse(url)
        
        # For SPAs, the fragment is critical. We need to handle query params in fragments.
        fragment = parsed.fragment
        if fragment and '?' in fragment:
            # Strip query params from fragment (e.g., #!/devices?filter=X -> #!/devices)
            fragment = fragment.split('?')[0]
        
        # Strip query params from path and ensure consistent trailing slash handling
        path = parsed.path.rstrip("/")
        if not path:
            path = "/"
            
        return f"{parsed.scheme}://{parsed.netloc}{path}{'#' + fragment if fragment else ''}"
    
    def _parse_query_string(self, url: str) -> dict[str, str]:
        """Parse query parameters from URL.
        
        Handles query params in both standard URLs and SPA fragments.
        
        Args:
            url: URL to parse
            
        Returns:
            Dictionary of query parameters
        """
        from urllib.parse import parse_qs
        
        parsed = urlparse(url)
        query_params = {}
        
        # Check for query params in standard URL
        if parsed.query:
            params = parse_qs(parsed.query)
            # Flatten single-value lists
            query_params.update({k: v[0] if len(v) == 1 else v for k, v in params.items()})
        
        # Check for query params in fragment (for SPAs)
        if parsed.fragment and '?' in parsed.fragment:
            fragment_query = parsed.fragment.split('?', 1)[1]
            params = parse_qs(fragment_query)
            # Flatten single-value lists
            query_params.update({k: v[0] if len(v) == 1 else v for k, v in params.items()})
        
        return query_params
    
    def _extract_query_pattern(self, url: str) -> str | None:
        """Extract query string pattern from URL.
        
        Identifies patterns like ?filter={variable} or ?tab={variable}.
        
        Args:
            url: URL to analyze
            
        Returns:
            Query pattern string or None if no query params
        """
        query_params = self._parse_query_string(url)
        
        if not query_params:
            return None
        
        # Create pattern by replacing values with {key} placeholders
        # e.g., {"filter": "Events.Inform > NOW()"} -> "filter={filter}"
        pattern_parts = [f"{key}={{{key}}}" for key in sorted(query_params.keys())]
        return "?" + "&".join(pattern_parts)

    def _get_url_structure(self, url: str) -> str:
        """Extract URL structure for pattern matching.
        
        Handles both path-based patterns (e.g., #!/devices/{id}) and
        query-based patterns (e.g., #!/devices?filter={filter}).
        
        Args:
            url: URL to analyze
            
        Returns:
            URL structure string
        """
        parsed = urlparse(url)
        
        # For hash-based SPAs, work with the fragment
        path = parsed.fragment if parsed.fragment else parsed.path
        
        # Strip leading ! from hash fragments
        if path.startswith("!"):
            path = path[1:]
        
        # Check for query parameters in the path/fragment
        if '?' in path:
            # Split base path and query
            base_path = path.split('?')[0]
            # Get query pattern
            query_pattern = self._extract_query_pattern(url)
            
            # Return combined pattern: base_path + query_pattern
            if query_pattern:
                return base_path + query_pattern
            return base_path
        
        # Split path into segments for path-based patterns
        segments = [s for s in path.split("/") if s]
        
        # If we have multiple segments, the last one might be a variable ID
        if len(segments) >= 2:
            # Use all segments except the last one as the structure
            # This groups URLs like #!/devices/ID1, #!/devices/ID2 together
            structure = "/".join(segments[:-1])
            return structure
        
        # For single-segment or no-segment paths, use the full path
        return path

    def _should_skip_url(self, url: str) -> tuple[bool, str]:
        """Check if URL matches a pattern we've already sampled enough.
        
        Args:
            url: URL to check
            
        Returns:
            Tuple of (should_skip, reason)
        """
        if not self.skip_pattern_duplicates:
            return False, ""
        
        # Extract URL structure
        structure = self._get_url_structure(url)
        
        # Skip empty structures
        if not structure or structure == "/":
            return False, ""
        
        # Initialize tracking for this structure if needed
        if structure not in self.pattern_tracker:
            self.pattern_tracker[structure] = []
        
        # Check if we've already sampled enough of this pattern
        current_count = len(self.pattern_tracker[structure])
        
        if current_count >= self.pattern_sample_size:
            # Mark as detected pattern (first time we skip)
            if structure not in self.detected_patterns:
                self.detected_patterns.add(structure)
                logger.info(
                    "Pattern detected: '%s' (sampled %d instances, skipping future instances)",
                    structure,
                    self.pattern_sample_size
                )
            
            # Record this skip for stats
            self.skipped_urls.append({
                "url": url,
                "pattern": structure,
                "reason": f"Matches pattern (already sampled {self.pattern_sample_size} instances)"
            })
            
            return True, f"Matches pattern '{structure}' (already sampled {self.pattern_sample_size} instances)"
        
        # Still collecting samples - don't add to tracker yet, wait for successful crawl
        logger.debug(
            "Pattern candidate '%s': %d/%d samples collected (will track if crawl succeeds)",
            structure,
            current_count,
            self.pattern_sample_size
        )
        
        return False, ""
    
    def _track_successful_crawl(self, url: str) -> None:
        """Track a URL after successful crawl for pattern detection.
        
        Only successfully crawled URLs should count toward pattern sampling.
        
        Args:
            url: URL that was successfully crawled
        """
        if not self.skip_pattern_duplicates:
            return
        
        # Extract URL structure
        structure = self._get_url_structure(url)
        
        # Skip empty structures
        if not structure or structure == "/":
            return
        
        # Initialize tracking for this structure if needed
        if structure not in self.pattern_tracker:
            self.pattern_tracker[structure] = []
        
        # Add this URL to the pattern tracker
        if url not in self.pattern_tracker[structure]:
            self.pattern_tracker[structure].append(url)
            logger.debug(
                "Tracked successful crawl for pattern '%s': %d/%d samples",
                structure,
                len(self.pattern_tracker[structure]),
                self.pattern_sample_size
            )

    def _discover_interactions(self, page_url: str):
        """Discover modals by clicking safe buttons.
        
        Creates modal nodes in the graph when modals are detected, along with
        their elements and OPENS_MODAL edges from trigger buttons.
        
        Args:
            page_url: Current page URL for state recovery
        """
        if not self.enable_interaction_discovery:
            return
        
        buttons = self._find_safe_buttons()
        
        logger.info("Discovering interactions: found %d safe buttons to test", len(buttons))
        
        for i, button in enumerate(buttons):
            try:
                # Record initial state and extract button info before clicking
                initial_url = self.driver.current_url
                button_text = button.text.strip()
                button_selector = self._get_css_selector(button)
                
                logger.debug("Clicking button %d/%d: %s", i + 1, len(buttons), button_text)
                
                # Click button
                button.click()
                time.sleep(self.interaction_timeout)
                
                # Check for modal
                modal_info = self._detect_modal()
                if modal_info:
                    logger.info("Modal detected after clicking '%s'", button_text)
                    
                    # Create modal node
                    modal_id = self.graph.add_modal(
                        parent_page=page_url,
                        title=modal_info.get("title", ""),
                        modal_type="dialog",
                        css_selector=modal_info.get("css_selector", "")
                    )
                    
                    # Find trigger button in graph and create OPENS_MODAL edge
                    # Search for button with matching selector
                    for elem_id in self.graph.get_container_elements(page_url):
                        elem_data = self.graph.graph.G.nodes.get(elem_id[0], {})
                        if (elem_data.get("element_type") == "button" and
                            elem_data.get("text") == button_text):
                            self.graph.add_modal_trigger(elem_id[0], modal_id, action="click")
                            break
                    
                    # Add modal's elements to graph
                    for btn_info in modal_info.get("buttons", []):
                        self.graph.add_element(
                            modal_id,
                            "button",
                            "css",
                            btn_info.get("css_selector", ""),
                            text=btn_info.get("text", ""),
                            button_type=btn_info.get("type", ""),
                            button_class=btn_info.get("class", ""),
                            visibility_observed="visible"
                        )
                    
                    for input_info in modal_info.get("inputs", []):
                        self.graph.add_element(
                            modal_id,
                            "input",
                            "css",
                            input_info.get("css_selector", ""),
                            input_type=input_info.get("type", ""),
                            name=input_info.get("name", ""),
                            placeholder=input_info.get("placeholder", ""),
                            required=input_info.get("required", False),
                            visibility_observed="visible"
                        )
                    
                    for select_info in modal_info.get("selects", []):
                        self.graph.add_element(
                            modal_id,
                            "select",
                            "css",
                            select_info.get("css_selector", ""),
                            name=select_info.get("name", ""),
                            visibility_observed="visible"
                        )
                    
                    # Close modal
                    self._close_modal()
                    time.sleep(0.5)
                
                # Restore state if URL changed
                if self.driver.current_url != initial_url:
                    logger.debug("URL changed, navigating back to %s", page_url)
                    self.driver.get(page_url)
                    self.wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
                    
            except StaleElementReferenceException:
                # Button became stale (common after page navigation)
                logger.debug("Button %d/%d became stale, skipping", i + 1, len(buttons))
                # Try to recover page state
                try:
                    self.driver.get(page_url)
                    self.wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
                    time.sleep(0.5)
                except:
                    pass
            except Exception as e:
                # Extract button text safely
                try:
                    btn_text = button_text if 'button_text' in locals() else 'unknown'
                except:
                    btn_text = 'unknown'
                logger.debug("Error with button %d/%d (%s): %s", i + 1, len(buttons), btn_text, e)
                # Try to recover page state
                try:
                    self.driver.get(page_url)
                    self.wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
                    time.sleep(0.5)
                except:
                    pass

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
        "--skip-pattern-duplicates",
        action="store_true",
        help="Skip URLs matching detected patterns after sampling enough instances (default: disabled)",
    )
    parser.add_argument(
        "--pattern-sample-size",
        type=int,
        default=3,
        help="Number of pattern instances to crawl before skipping duplicates (default: 3)",
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
        skip_pattern_duplicates=args.skip_pattern_duplicates,
        pattern_sample_size=args.pattern_sample_size,
    )

    # Discover site
    logger.info("Starting UI discovery for %s", args.url)
    ui_map = tool.discover_site(
        login_first=not args.no_login,
        login_url=args.login_url,
    )

    # Save to file
    output_path = Path(args.output)
    with output_path.open("w") as f:
        json.dump(ui_map, f, indent=2)

    logger.info("UI map saved to %s", output_path)
    
    # Log graph statistics
    graph_stats = ui_map.get("statistics", {})
    logger.info("Graph statistics:")
    logger.info("  - Pages: %d", graph_stats.get("page_count", 0))
    logger.info("  - Modals: %d", graph_stats.get("modal_count", 0))
    logger.info("  - Forms: %d", graph_stats.get("form_count", 0))
    logger.info("  - Elements: %d", graph_stats.get("element_count", 0))
    logger.info("  - Total nodes: %d", graph_stats.get("total_nodes", 0))
    logger.info("  - Total edges: %d", graph_stats.get("total_edges", 0))
    
    # Log discovery statistics
    discovery_stats = ui_map.get("discovery_stats", {})
    logger.info("Discovery method: %s", ui_map.get("discovery_method", "unknown"))
    logger.info("Levels explored: %d", ui_map.get("levels_explored", 0))
    
    if discovery_stats.get("pattern_skipping_enabled"):
        logger.info("Pattern-based skipping: ENABLED")
        logger.info("  - Pages crawled: %d", discovery_stats.get("pages_crawled", 0))
        logger.info("  - Pages skipped: %d", discovery_stats.get("pages_skipped", 0))
        logger.info("  - Patterns detected during crawl: %d", discovery_stats.get("patterns_detected_during_crawl", 0))
        logger.info("  - Sample size per pattern: %d", discovery_stats.get("pattern_sample_size", 0))
        if discovery_stats.get("pages_skipped", 0) > 0:
            time_saved = discovery_stats.get("pages_skipped", 0) * 30  # Rough estimate: 30 sec/page
            logger.info("  - Estimated time saved: ~%d minutes", time_saved // 60)


if __name__ == "__main__":
    main()
