"""Synchronous Playwright driver wrapper.

This adapter provides a synchronous interface to Playwright for use with
boardfarm's FSM-based GUI testing framework.

It integrates with StateExplorer's AriaSnapshotCapture for state fingerprinting
and provides screenshot capabilities for visual regression testing.
"""

import logging
from playwright.sync_api import sync_playwright, Page, Playwright, Browser

_LOGGER = logging.getLogger(__name__)


class PlaywrightSyncAdapter:
    """Synchronous Playwright driver wrapper with StateExplorer integration."""
    
    def __init__(self, headless: bool = True, timeout: int = 30000):
        """Initialize adapter.
        
        Args:
            headless: Run browser in headless mode
            timeout: Default timeout in milliseconds (default: 30000 = 30s)
        """
        self._headless = headless
        self._timeout = timeout
        self._playwright: Playwright = None
        self._browser: Browser = None
        self._page: Page = None
        
        _LOGGER.debug(
            "PlaywrightSyncAdapter initialized (headless=%s, timeout=%dms)",
            headless, timeout
        )
    
    def start(self):
        """Launch browser and create page.
        
        This must be called before using the adapter.
        """
        _LOGGER.info("Starting Playwright browser...")
        
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self._headless)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(self._timeout)
        
        # Set consistent viewport size for screenshots
        self._page.set_viewport_size({"width": 1920, "height": 1080})
        
        _LOGGER.info(
            "Playwright browser started (headless=%s, viewport=1920x1080)",
            self._headless
        )
    
    def close(self):
        """Close browser and cleanup resources.
        
        This should be called when done with the adapter.
        """
        if self._browser:
            try:
                self._browser.close()
                _LOGGER.info("Browser closed")
            except Exception as e:
                _LOGGER.warning("Error closing browser: %s", e)
        
        if self._playwright:
            try:
                self._playwright.stop()
                _LOGGER.info("Playwright stopped")
            except Exception as e:
                _LOGGER.warning("Error stopping Playwright: %s", e)
    
    def goto(self, url: str, wait_until: str = 'load'):
        """Navigate to URL.
        
        Args:
            url: URL to navigate to
            wait_until: Wait until condition ('load', 'domcontentloaded', 'networkidle')
        """
        _LOGGER.debug("Navigating to: %s (wait_until=%s)", url, wait_until)
        self._page.goto(url, wait_until=wait_until)
        _LOGGER.info("Navigation complete: %s", url)
    
    @property
    def page(self) -> Page:
        """Get Playwright Page object.
        
        Returns:
            Playwright Page for direct manipulation
        """
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page
    
    @property
    def url(self) -> str:
        """Get current URL.
        
        Returns:
            Current page URL
        """
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page.url
    
    def capture_fingerprint(self) -> dict:
        """Capture current page fingerprint using StateFingerprinter.
        
        This creates a multi-dimensional fingerprint of the current UI state:
        - 60% accessibility tree (semantic)
        - 25% actionable elements (functional)
        - 10% URL pattern (structural)
        - 4% content (titles, headings)
        - 1% style (DOM hash)
        
        Returns:
            Dictionary with fingerprint data compatible with StateComparer
        """
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        
        _LOGGER.debug("Capturing page fingerprint...")
        
        try:
            from model_resilience_core.fingerprinting import StateFingerprinter
            from aria_state_mapper.playwright_integration import AriaSnapshotCapture
            
            # Capture ARIA snapshot using Playwright's sync API
            # Note: aria_snapshot() is available on locators
            locator = self._page.locator('body')
            aria_yaml = locator.aria_snapshot()
            
            # Parse the ARIA snapshot using StateExplorer's parser
            # AriaSnapshotCapture._parse_yaml_snapshot is a static method
            aria_tree = AriaSnapshotCapture._parse_yaml_snapshot(aria_yaml)
            
            # Get URL and title (sync methods)
            url = self._page.url
            title = self._page.title()
            
            # Get main heading (sync)
            main_heading = ""
            try:
                h1_locator = self._page.locator('h1').first
                if h1_locator.count() > 0:
                    main_heading = h1_locator.text_content() or ""
            except Exception:
                pass
            
            # Create fingerprint using StateFingerprinter
            fingerprinter = StateFingerprinter()
            fingerprint = fingerprinter.create_fingerprint(
                url=url,
                title=title,
                accessibility_tree=aria_tree,
                main_heading=main_heading
            )
            
            _LOGGER.debug("Fingerprint captured successfully")
            return fingerprint
        except Exception as e:
            _LOGGER.error("Failed to capture fingerprint: %s", e, exc_info=True)
            raise
    
    
    def capture_aria_snapshot(self) -> str:
        """Capture ARIA accessibility snapshot as YAML string.
        
        This provides the raw YAML from Playwright's aria_snapshot() API.
        
        Returns:
            YAML string with ARIA tree structure
        """
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        
        _LOGGER.debug("Capturing ARIA snapshot...")
        
        try:
            locator = self._page.locator('body')
            snapshot_yaml = locator.aria_snapshot()
            _LOGGER.debug("ARIA snapshot captured successfully")
            return snapshot_yaml
        except Exception as e:
            _LOGGER.error("Failed to capture ARIA snapshot: %s", e, exc_info=True)
            raise
    
    def take_screenshot(self, path: str, full_page: bool = True):
        """Take screenshot and save to file.
        
        Args:
            path: File path to save screenshot
            full_page: If True, capture entire page (scrolling as needed)
        """
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        
        _LOGGER.debug("Taking screenshot: %s (full_page=%s)", path, full_page)
        
        try:
            self._page.screenshot(path=path, full_page=full_page)
            _LOGGER.info("Screenshot saved: %s", path)
        except Exception as e:
            _LOGGER.error("Failed to take screenshot: %s", e, exc_info=True)
            raise
    
    def wait_for_timeout(self, timeout: int):
        """Wait for a specified amount of time.
        
        Args:
            timeout: Time to wait in milliseconds
        """
        _LOGGER.debug("Waiting for %dms", timeout)
        self._page.wait_for_timeout(timeout)
    
    def wait_for_load_state(self, state: str = 'load'):
        """Wait for a specific load state.
        
        Args:
            state: Load state to wait for ('load', 'domcontentloaded', 'networkidle')
        """
        _LOGGER.debug("Waiting for load state: %s", state)
        self._page.wait_for_load_state(state)
        _LOGGER.debug("Load state reached: %s", state)
    
    def reload(self, wait_until: str = 'load'):
        """Reload the current page.
        
        Args:
            wait_until: Wait until condition ('load', 'domcontentloaded', 'networkidle')
        """
        _LOGGER.debug("Reloading page")
        self._page.reload(wait_until=wait_until)
        _LOGGER.info("Page reloaded")
    
    def go_back(self, wait_until: str = 'load'):
        """Navigate back in browser history.
        
        Args:
            wait_until: Wait until condition ('load', 'domcontentloaded', 'networkidle')
        """
        _LOGGER.debug("Navigating back")
        self._page.go_back(wait_until=wait_until)
        _LOGGER.info("Navigated back to: %s", self.url)
    
    def go_forward(self, wait_until: str = 'load'):
        """Navigate forward in browser history.
        
        Args:
            wait_until: Wait until condition ('load', 'domcontentloaded', 'networkidle')
        """
        _LOGGER.debug("Navigating forward")
        self._page.go_forward(wait_until=wait_until)
        _LOGGER.info("Navigated forward to: %s", self.url)
    
    def evaluate(self, expression: str):
        """Evaluate JavaScript expression in the page context.
        
        Args:
            expression: JavaScript expression to evaluate
            
        Returns:
            Result of the JavaScript evaluation
        """
        _LOGGER.debug("Evaluating JavaScript: %s", expression[:100])
        return self._page.evaluate(expression)
    
    def set_viewport_size(self, width: int, height: int):
        """Set viewport size.
        
        Args:
            width: Viewport width in pixels
            height: Viewport height in pixels
        """
        _LOGGER.debug("Setting viewport size: %dx%d", width, height)
        self._page.set_viewport_size({"width": width, "height": height})
        _LOGGER.info("Viewport size set: %dx%d", width, height)
    
    def __enter__(self):
        """Context manager entry.
        
        Usage:
            with PlaywrightSyncAdapter() as driver:
                driver.goto("https://example.com")
        """
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False  # Don't suppress exceptions
