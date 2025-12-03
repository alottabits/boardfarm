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
    ):
        """Initialize the UI Discovery Tool.
        
        Args:
            base_url: Base URL of the application to crawl
            username: Optional login username
            password: Optional login password
            headless: Run browser in headless mode
            timeout: Default timeout for element waits
        """
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password

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
                      uses base_url + '/login'
        
        Raises:
            TimeoutException: If login elements are not found
        """
        if not self.username or not self.password:
            logger.info("No credentials provided, skipping login")
            return

        url = login_url or f"{self.base_url}/login"
        logger.info("Logging in to %s", url)
        self.driver.get(url)

        try:
            # Try common username field selectors
            username_field = None
            for selector in [
                (By.NAME, "username"),
                (By.ID, "username"),
                (By.CSS_SELECTOR, "input[type='text']"),
            ]:
                try:
                    username_field = self.wait.until(
                        EC.presence_of_element_located(selector)
                    )
                    break
                except TimeoutException:
                    continue

            if not username_field:
                raise TimeoutException("Could not find username field")

            username_field.send_keys(self.username)

            # Find password field
            password_field = self.driver.find_element(
                By.CSS_SELECTOR, "input[type='password']"
            )
            password_field.send_keys(self.password)

            # Find and click submit button
            submit_btn = self.driver.find_element(
                By.CSS_SELECTOR, "button[type='submit']"
            )
            submit_btn.click()

            # Wait for redirect away from login page
            self.wait.until(lambda d: "/login" not in d.current_url)
            logger.info("Login successful")

        except Exception as e:
            logger.error("Login failed: %s", e)
            raise

    def discover_site(
        self,
        start_url: str | None = None,
        max_depth: int = 3,
        login_first: bool = True,
    ) -> dict[str, Any]:
        """Crawl the entire UI and return a structured map.
        
        Args:
            start_url: Optional starting URL. If not provided, uses base_url
            max_depth: Maximum crawl depth
            login_first: Whether to login before crawling
            
        Returns:
            Dictionary containing:
                - base_url: Base URL of the application
                - pages: List of discovered pages with elements
                - navigation_graph: Graph of navigation relationships
        """
        try:
            if login_first:
                self.login()
                start_url = start_url or self.driver.current_url
            else:
                start_url = start_url or self.base_url
                self.driver.get(start_url)

            logger.info("Starting discovery from %s", start_url)
            self._crawl_page(start_url, depth=0, max_depth=max_depth)

            return {
                "base_url": self.base_url,
                "pages": self.pages,
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
        return {
            "url": url,
            "title": self.driver.title,
            "page_type": self._classify_page(url),
            "buttons": self._discover_buttons(),
            "inputs": self._discover_inputs(),
            "links": self._discover_links(),
            "tables": self._discover_tables(),
        }

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
        """Normalize URL by removing query parameters and fragments.
        
        Args:
            url: URL to normalize
            
        Returns:
            Normalized URL
        """
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

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

    args = parser.parse_args()

    # Create discovery tool
    tool = UIDiscoveryTool(
        base_url=args.url,
        username=args.username,
        password=args.password,
        headless=args.headless,
    )

    # Discover site
    logger.info("Starting UI discovery for %s", args.url)
    ui_map = tool.discover_site(
        max_depth=args.max_depth,
        login_first=not args.no_login,
    )

    # Save to file
    output_path = Path(args.output)
    with output_path.open("w") as f:
        json.dump(ui_map, f, indent=2)

    logger.info("UI map saved to %s", output_path)
    logger.info("Discovered %d pages", len(ui_map["pages"]))


if __name__ == "__main__":
    main()
