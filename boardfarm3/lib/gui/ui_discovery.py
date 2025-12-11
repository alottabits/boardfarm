"""UI Discovery Tool for automated UI mapping and crawling (Playwright Version).

This tool crawls a web UI, discovers pages and elements, and generates
a structured JSON map (ui_map.json) that represents the UI as a graph.
This map can be used for automated navigation path generation and
change detection.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse, parse_qs

from playwright.async_api import async_playwright, Page, Locator, TimeoutError as PlaywrightTimeoutError, BrowserContext

from boardfarm3.lib.gui.ui_graph import UIGraph

if TYPE_CHECKING:
    pass

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
    """Web UI crawler with NetworkX graph representation and BFS traversal (Playwright Version).
    
    Attributes:
        base_url: Base URL of the application
        username: Login username (optional)
        password: Login password (optional)
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
        """Initialize the UI Discovery Tool."""
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.headless = headless
        self.timeout = timeout * 1000  # Convert to ms
        self.enable_pattern_detection = enable_pattern_detection
        self.min_pattern_count = min_pattern_count
        self.enable_interaction_discovery = enable_interaction_discovery
        self.safe_buttons = safe_buttons
        self.interaction_timeout = interaction_timeout
        self.skip_pattern_duplicates = skip_pattern_duplicates
        self.pattern_sample_size = pattern_sample_size

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
        
        # Browser state
        self.browser = None
        self.context = None
        self.page = None

    async def _init_browser(self):
        """Initialize Playwright browser."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.firefox.launch(
            headless=self.headless,
            args=["--width=1920", "--height=1080"]
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            ignore_https_errors=True
        )
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.timeout)

    async def login(self, login_url: str | None = None) -> None:
        """Login to the application."""
        if not self.username or not self.password:
            logger.info("No credentials provided, skipping login")
            return

        if login_url:
            logger.info("Navigating to custom login URL: %s", login_url)
            await self.page.goto(login_url)
        else:
            current_url = self.page.url
            if '/login' not in current_url.lower():
                logger.info("Not on login page, navigating to base URL: %s", self.base_url)
                await self.page.goto(self.base_url)

        try:
            # Check if we need to click a login link first
            try:
                # fast check - explicit timeout shorter than component timeout
                await self.page.wait_for_selector("input[name='username']", timeout=2000)
                logger.info("Already on login page")
            except PlaywrightTimeoutError:
                logger.info("Username field not found, looking for 'Log in' link")
                try:
                    await self.page.click("text=Log in")
                    logger.info("Clicked 'Log in' link")
                except Exception:
                     logger.warning("Could not find 'Log in' link, assuming we are on login page or it will load")

            # Fill username
            await self.page.fill("input[name='username']", self.username)
            
            # Fill password
            await self.page.fill("input[name='password']", self.password)
            
            # Click submit
            # Try multiple selectors
            for selector in ["button[type='submit']", "button:has-text('Login')", ".primary"]:
                if await self.page.locator(selector).is_visible():
                    await self.page.click(selector)
                    break
            
            # Wait for navigation
            try:
                await self.page.wait_for_url(lambda u: "/login" not in u and "login" not in u.split("?")[0], timeout=5000)
            except Exception:
                logger.warning("Timed out waiting for URL to change from login page")

            logger.info("Login successful, current URL: %s", self.page.url)

        except Exception as e:
            logger.error("Login failed: %s", e)
            await self.page.screenshot(path="login_failure.png")
            raise

    async def discover_site(
        self,
        start_url: str | None = None,
        login_first: bool = True,
        login_url: str | None = None,
        discover_login_page: bool = True,
    ) -> dict[str, Any]:
        """Crawl the UI using breadth-first search with leaf tracking (Async)."""
        await self._init_browser()
        
        try:
            if login_first and discover_login_page:
                target_url = login_url or self.base_url
                logger.info("Navigating to initial URL: %s", target_url)
                await self.page.goto(target_url)
                await self.page.wait_for_load_state("networkidle")
                await asyncio.sleep(0.5)
                
                login_page_url = self.page.url
                logger.info("Discovering login page: %s", login_page_url)
                
                normalized_login_url = self._normalize_url(login_page_url)
                
                page_type = self._classify_page(normalized_login_url)
                friendly_name = self._generate_friendly_page_name(normalized_login_url, page_type)
                
                self.graph.add_page(
                    url=normalized_login_url,
                    title=await self.page.title(),
                    page_type=page_type,
                    friendly_name=friendly_name
                )
                
                await self._discover_elements(normalized_login_url)
                self.visited_urls.add(normalized_login_url)
                
                logger.info("Login page discovered successfully")
                
                await self.login(login_url=None)
                
                # If start_url not provided, use current URL.
                # If current URL is still login page (despite wait), fall back to base_url
                current_url = self.page.url
                if "/login" in current_url.lower():
                     logger.warning("Still on login page, forcing navigation to base URL")
                     await self.page.goto(self.base_url)
                     await self.page.wait_for_load_state("networkidle")
                     current_url = self.page.url
                
                start_url = start_url or current_url
                
            elif login_first:
                await self.login(login_url=login_url)
                start_url = start_url or self.page.url
            else:
                start_url = start_url or self.base_url
                await self.page.goto(start_url)
                await self.page.wait_for_load_state("networkidle")

            logger.info("Starting BFS discovery from %s", start_url)
            self.frontier.append(start_url)
            
            while self.frontier and len(self.visited_urls) < self.max_pages:
                level_size = len(self.frontier)
                logger.info("Level %d: Processing %d pages", self.current_level, level_size)
                
                new_leaves = []
                
                for _ in range(level_size):
                    if not self.frontier:
                        break
                    
                    url = self.frontier.popleft()
                    normalized_url = self._normalize_url(url)
                    
                    if normalized_url in self.visited_urls:
                        continue
                    
                    leaves = await self._discover_page(normalized_url)
                    new_leaves.extend(leaves)
                
                self.frontier.extend(new_leaves)
                self.current_level += 1
            
            return {
                "base_url": self.base_url,
                "discovery_method": "breadth_first_search_async",
                "levels_explored": self.current_level,
                "graph": self.graph.export_node_link(),
                "statistics": self.graph.get_statistics(),
            }
            
        finally:
            await self.close()

    async def _discover_page(self, url: str) -> list[str]:
        """Discover a single page and return new leaves."""
        should_skip, skip_reason = self._should_skip_url(url)
        if should_skip:
            logger.info("Skipping %s: %s", url, skip_reason)
            return []

        logger.info("Discovering: %s", url)

        try:
            await self.page.goto(url)
            await self.page.wait_for_load_state("networkidle")
            await asyncio.sleep(0.5)

            page_type = self._classify_page(url)
            friendly_name = self._generate_friendly_page_name(url, page_type)
            
            self.graph.add_page(
                url=url,
                title=await self.page.title(),
                page_type=page_type,
                friendly_name=friendly_name
            )
            
            await self._discover_elements(url)
            
            if self.enable_interaction_discovery:
                await self._discover_interactions(url)
                await asyncio.sleep(1.0)
            
            leaves = await self._find_links(url)
            self.visited_urls.add(url)
            self._track_successful_crawl(url)
            
            return leaves
            
        except Exception as e:
            logger.error("Error discovering %s: %s", url, e)
            return []

    async def _discover_elements(self, page_url: str):
        """Discover elements on the page."""
        # Buttons
        buttons = await self.page.locator("button").all()
        for i, btn in enumerate(buttons):
            try:
                if not await btn.is_visible(): continue
                
                # Get CSS selector via JS evaluation
                css_selector = await self._get_selector_js(btn)
                
                text = (await btn.text_content() or "").strip()
                btn_id = await btn.get_attribute("id") or ""
                btn_class = await btn.get_attribute("class") or ""
                
                friendly_name = self._generate_friendly_element_name(
                    {"text": text, "name": btn_id, "title": await btn.get_attribute("title")}, 
                    "button"
                )
                
                self.graph.add_element(
                    page_url, "button", "css", css_selector,
                    text=text, button_id=btn_id, button_class=btn_class,
                    visibility_observed="visible", friendly_name=friendly_name
                )
            except Exception as e:
                logger.debug("Error button %d: %s", i, e)

        # Inputs
        inputs = await self.page.locator("input").all()
        for i, inp in enumerate(inputs):
            try:
                if not await inp.is_visible(): continue
                
                css_selector = await self._get_selector_js(inp)
                name = await inp.get_attribute("name") or ""
                
                friendly_name = self._generate_friendly_element_name(
                    {"name": name, "placeholder": await inp.get_attribute("placeholder")}, 
                    "input"
                )
                
                self.graph.add_element(
                    page_url, "input", "css", css_selector,
                    name=name, visibility_observed="visible", friendly_name=friendly_name
                )
            except Exception: pass

        # Links (for content, not navigation) - Handled mostly in _find_links but elements added here too?
        # The legacy tool discovers elements by type independently.
        # But _find_links adds them too. Duplicate?
        # Legacy _discover_elements does NOT discover 'a' tags. _find_links does.
        # So we stop here.

    async def _find_links(self, current_page_url: str) -> list[str]:
        """Find navigation links."""
        leaves = []
        links = await self.page.locator("a").all()
        
        for i, link in enumerate(links):
            try:
                if not await link.is_visible(): continue
                
                href = await link.get_attribute("href")
                text = (await link.text_content() or "").strip() or "(no text)"
                css_selector = await self._get_selector_js(link)
                
                is_svg_link = False
                # Handle SVG href logic if needed - Playwright handles explicit attributes well
                # but SVG href might be xlink:href or href.
                
                if href and self._is_internal_link(href):
                    normalized_href = self._normalize_url(href)
                    
                    friendly_name = self._generate_friendly_element_name(
                        {"text": text, "title": await link.get_attribute("title")}, 
                        "link"
                    )
                    
                    link_elem_id = self.graph.add_element(
                        current_page_url, "link", "css", css_selector,
                        text=text, href=normalized_href, visibility_observed="visible",
                        friendly_name=friendly_name
                    )
                    
                    self.graph.add_navigation_link(
                        from_page=current_page_url,
                        to_page=normalized_href,
                        via_element=link_elem_id,
                        action="click"
                    )
                    
                    if normalized_href not in self.visited_urls:
                        leaves.append(normalized_href)
            except Exception: pass
            
        return leaves

    async def _get_selector_js(self, element: Locator) -> str:
        """Generate CSS selector using JS evaluation."""
        return await element.evaluate("""(el) => {
            if (el.id) return '#' + el.id;
            if (el.className && typeof el.className === 'string' && el.className.trim()) {
                return '.' + el.className.trim().split(' ')[0];
            }
            return el.tagName.toLowerCase();
        }""")

    # --- Helper methods ported from legacy ---

    def _normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            base_parsed = urlparse(self.base_url)
            scheme = parsed.scheme or base_parsed.scheme
            netloc = parsed.netloc or base_parsed.netloc
        else:
            scheme = parsed.scheme
            netloc = parsed.netloc
        
        fragment = parsed.fragment
        if fragment and '?' in fragment:
            fragment = fragment.split('?')[0]
        
        path = parsed.path.rstrip("/")
        if not path:
            path = "/"
        elif not path.startswith("/"):
            path = "/" + path
            
        return f"{scheme}://{netloc}{path}{'#' + fragment if fragment else ''}"

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

    def _is_internal_link(self, href: str) -> bool:
        if not href or href.startswith(("javascript:", "mailto:")): return False
        if href.startswith("#") and "/" not in href: return False
        if any(href.endswith(ext) for ext in [".csv", ".json", ".xml", ".pdf", ".zip"]): return False
        
        parsed = urlparse(href)
        base_parsed = urlparse(self.base_url)
        return not parsed.netloc or parsed.netloc == base_parsed.netloc

    def _classify_page(self, url: str) -> str:
        # Same logic as legacy
        parsed = urlparse(url)
        path = (parsed.fragment if parsed.fragment else parsed.path).lower()
        if '?' in path: path = path.split('?')[0]
        if path.startswith("!"): path = path[1:]

        if "/login" in path: return "login"
        if "/devices/" in path and len(path.split("/")) > 2: return "device_details"
        if "/devices" in path: return "device_list"
        if "/tasks" in path: return "tasks"
        if "/files" in path: return "files"
        if "/faults" in path: return "faults"
        if "/presets" in path: return "presets"
        if "/provisions" in path: return "provisions"
        if "/config" in path: return "config"
        if "/users" in path: return "users"
        if "/admin" in path: return "admin"
        if path == "/" or "/overview" in path: return "home"
        return "unknown"

    def _generate_friendly_page_name(self, url: str, page_type: str) -> str:
        return f"{page_type}_page"

    def _generate_friendly_element_name(self, elem_info: dict, element_type: str) -> str:
        # Simplified for brevity but functionally equivalent
        name_source = (elem_info.get('text') or elem_info.get('title') or 
                      elem_info.get('placeholder') or elem_info.get('name') or '').strip()
        
        if name_source:
            clean_name = "".join(c for c in name_source.lower().replace(' ', '_').replace('-', '_') 
                               if c.isalnum() or c == '_')
            return f"{clean_name}_{element_type}"
        return f"{element_type}_unknown"

    # Pattern detection helpers (minimal port for pattern detection support)
    def _should_skip_url(self, url: str) -> tuple[bool, str]:
        if not self.skip_pattern_duplicates: return False, ""
        structure = self._get_url_structure(url)
        if not structure or structure == "/": return False, ""
        
        if structure not in self.pattern_tracker:
            self.pattern_tracker[structure] = []
            
        if len(self.pattern_tracker[structure]) >= self.pattern_sample_size:
            if structure not in self.detected_patterns:
                self.detected_patterns.add(structure)
            return True, f"Pattern match {structure}"
        return False, ""

    def _track_successful_crawl(self, url: str):
        if not self.skip_pattern_duplicates: return
        structure = self._get_url_structure(url)
        if not structure: return
        if structure not in self.pattern_tracker: self.pattern_tracker[structure] = []
        if url not in self.pattern_tracker[structure]:
            self.pattern_tracker[structure].append(url)

    def _get_url_structure(self, url: str) -> str:
        parsed = urlparse(url)
        path = parsed.fragment if parsed.fragment else parsed.path
        if path.startswith("!"): path = path[1:]
        if '?' in path: return path.split('?')[0] + "?" # logic simplified
        segments = [s for s in path.split("/") if s]
        if len(segments) >= 2: return "/".join(segments[:-1])
        return path

    async def _discover_interactions(self, url: str):
        pass # To be implemented if needed for parity, but keeping simple for initial port

    async def close(self):
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()


def main():
    asyncio.run(main_async())

async def main_async():
    parser = argparse.ArgumentParser(
        description="Discover and map UI structure for automated testing (Playwright)"
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
    # Headless toggle logic to match legacy
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
        "--skip-login-discovery",
        action="store_true",
        help="Skip discovering login page elements (default: discover login page)",
    )
    parser.add_argument(
        "--disable-pattern-detection",
        action="store_true",
        help="Disable URL pattern detection (default: enabled)",
    )
    parser.add_argument(
        "--discover-interactions",
        action="store_true",
        help="Discover modals and dialogs by clicking buttons (default: disabled)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1000,
        help="Maximum number of pages to crawl (default: 1000)",
    )

    args = parser.parse_args()

    # Create discovery tool
    tool = UIDiscoveryTool(
        base_url=args.url,
        username=args.username,
        password=args.password,
        headless=args.headless,
        enable_pattern_detection=not args.disable_pattern_detection,
        enable_interaction_discovery=args.discover_interactions,
    )
    tool.max_pages = args.max_pages

    # Discover site
    logger.info("Starting UI discovery for %s", args.url)
    ui_map = await tool.discover_site(
        login_first=not args.no_login,
        login_url=args.login_url,
        discover_login_page=not args.skip_login_discovery,
    )

    # Save to file
    output_path = Path(args.output)
    with output_path.open("w") as f:
        json.dump(ui_map, f, indent=2)

    logger.info("UI map saved to %s", output_path)
    
    # Log statistics
    graph_stats = ui_map.get("statistics", {})
    logger.info("Graph statistics:")
    logger.info("  - Pages: %d", graph_stats.get("page_count", 0))
    logger.info("  - Total nodes: %d", graph_stats.get("total_nodes", 0))


if __name__ == "__main__":
    main()
