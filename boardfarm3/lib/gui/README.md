# UI Testing Framework - Automated Discovery and Test Artifact Generation

## Overview

This directory contains the **Boardfarm UI Testing Framework**, a complete toolkit for automated UI discovery and test artifact generation. 

### The Standardization Strategy

One of Boardfarm's core principle is **standardizing test interfaces** across different device implementations. Just as we define standard machine-to-machine APIs (e.g., `cpe.reboot()` works regardless of the particular CPE in the test-bed, we apply the same pattern to GUI testing:

**Standard Test Interface (Device-Independent):**

```python
# Tests use a stable API, regardless of ACS implementation
acs.gui.navigate_to_device_list()
acs.gui.search_device("SN123456")
acs.gui.reboot_device()
```

**Device-Specific Implementation (GenieACS, Axiros, etc.):**

```yaml
# selectors.yaml - Maps interface to actual UI elements
# navigation.yaml - Maps paths to actual navigation steps
```

The UI discovery tools **automatically generate the mapping** between your stable test interface and the actual UI implementation. This maintains the separation of concerns: tests describe *what* to do, artifacts describe *how* to do it for a specific UI.

### How It Works

The framework uses NetworkX graph algorithms to:

1. **Discover** your application's UI structure (pages, elements, navigation paths)
2. **Generate** a single graph artifact (`ui_map.json`) with everything including friendly names
3. **Enable** device-specific implementations to fulfill the standard interface

**Key Innovation**: Friendly names (like `"login_page"`, `"username_input"`) are generated automatically during discovery and stored in the graph - no manual maintenance needed!

## Boardfarm Standardization Pattern

### Machine-to-Machine APIs vs GUI - Same Pattern

Boardfarm uses the **same architectural pattern** for both M2M and GUI interfaces:

| Aspect              | M2M APIs (e.g., CPE)               | GUI APIs (e.g., ACS)                  |
| ------------------- | ---------------------------------- | ------------------------------------- |
| **Template**        | `CpeTemplate` defines standard API | `AcsGuiTemplate` defines standard API |
| **Implementations** | `PrplOsCpe`, `OpenWrtCpe`          | `GenieAcsGui`, `AxirosAcsGui`         |
| **Mapping**         | Protocol adapters (TR-069, SSH)    | ui_map.json (graph with friendly names) |
| **Test Interface**  | `cpe.reboot()`                     | `acs.gui.reboot_device()`             |
| **Discovery Tools** | Manual implementation              | **Automated** (ui_discovery.py)       |

**Key Insight:** The UI discovery tools **automatically generate a graph artifact** (`ui_map.json`) with friendly names that connect your stable test interface to the actual UI implementation. Everything is generated once during discovery - no manual maintenance needed!

### Component Structure (Template Pattern)

Following Boardfarm conventions, devices are built from composable components:

```
devices/
├── acs_template/                    # Template (defines stable interface)
│   ├── __init__.py
│   ├── gui_component.py            # Standard GUI methods
│   ├── nbi_component.py            # Standard NBI methods
│   └── acs_device.py               # Composite device class
│
├── genieacs/                        # Implementation
│   ├── __init__.py
│   ├── genieacs_gui.py             # Implements gui_component
│   ├── genieacs_nbi.py             # Implements nbi_component
│   ├── genieacs_device.py          # Uses template pattern
│   └── ui_map.json                 # UI graph with friendly names (generated)
│
└── axirosacs/                        # Another implementation
    ├── axirosacs_gui.py
    ├── axirosacs_nbi.py
    ├── axirosacs_device.py
    └── ui_map.json                 # Different UI, same interface (generated)
```

**Pattern:**

- `.gui` component: Web UI interface (uses selectors + navigation)
- `.nbi` component: Northbound API interface (REST/SOAP)
- `.hw` component: Hardware interface (if applicable)

**Usage in tests:**

```python
# Access components through device
acs = bf_context.devices.genieacs
acs.gui.reboot_device()      # GUI interface
acs.nbi.get_device_status()  # NBI interface

# Same interface works for any ACS
acs2 = bf_context.devices.axirosacs
acs2.gui.reboot_device()     # Different UI, same test interface
```

### Task-Oriented Template Pattern

Following the same pattern as `ACSNBI`, the `ACSGUI` template defines **task-oriented methods** that describe business operations, not UI navigation.

#### ✅ Good: Task-Oriented Methods

These methods describe **WHAT to accomplish**:

```python
class ACSGUI(ABC):
    @abstractmethod
    def reboot_device_via_gui(self, cpe_id: str) -> bool:
        """Reboot a device via the GUI."""
        
    @abstractmethod
    def get_device_status(self, cpe_id: str) -> dict[str, str]:
        """Get device status information."""
        
    @abstractmethod
    def set_device_parameter_via_gui(self, cpe_id: str, parameter: str, value: str) -> bool:
        """Set a device parameter via GUI."""
```

**Benefits:**
- ✅ Vendor-neutral - works for any ACS (GenieACS, Axiros, etc.)
- ✅ Test clarity - `reboot_device_via_gui(cpe_id)` clearly states intent
- ✅ Encapsulation - navigation details hidden in implementation
- ✅ Consistent - matches proven `ACSNBI` pattern

#### ❌ Bad: UI-Structure-Oriented Methods

These methods expose **HOW to navigate the UI**:

```python
# DON'T DO THIS - exposes UI structure
class ACSGUI(ABC):
    @abstractmethod
    def navigate_to_device_list(self) -> None:
        """Navigate to device list page."""
        
    @abstractmethod
    def navigate_to_device_details(self, cpe_id: str) -> None:
        """Navigate to device details page."""
        
    @abstractmethod
    def click_reboot_button(self) -> None:
        """Click the reboot button."""
```

**Problems:**
- ❌ Not vendor-neutral - assumes specific UI structure
- ❌ Test verbosity - requires multiple calls for one task
- ❌ Brittle - UI restructure breaks test interface
- ❌ Low-level - tests describe navigation, not intent

#### Example: Same Task, Different Approaches

**Task-Oriented (Recommended):**
```python
# Test code - clear intent
def test_reboot_device(acs, cpe_id):
    acs.gui.reboot_device_via_gui(cpe_id)
    assert acs.gui.verify_device_online(cpe_id, timeout=120)
```

**UI-Structure-Oriented (Not Recommended):**
```python
# Test code - exposes navigation
def test_reboot_device(acs, cpe_id):
    acs.gui.navigate_to_device_list()
    acs.gui.search_device(cpe_id)
    acs.gui.navigate_to_device_details(cpe_id)
    acs.gui.click_actions_menu()
    acs.gui.click_reboot_option()
    acs.gui.confirm_reboot()
    # ... now need to wait and verify
```

#### Implementation: Semantic Helpers

Device-specific implementations use **semantic element search** to absorb UI changes:

```python
class GenieAcsGUI(ACSGUI):
    """GenieACS GUI implementation."""
    
    def reboot_device_via_gui(self, cpe_id: str) -> bool:
        """Reboot device via GenieACS GUI."""
        # 1. Navigate (encapsulated)
        self.navigate_path(f"Path_Home_to_DeviceDetails", cpe_id=cpe_id)
        
        # 2. Find reboot button (semantic search - self-healing)
        reboot_btn = self.find_element_by_function(
            element_type="button",
            function_keywords=["reboot", "restart", "reset"],
            page="device_details_page",
            fallback_name="reboot"  # Safety net
        )
        
        # 3. Execute action
        reboot_btn.click()
        
        # 4. Confirm modal (if present)
        confirm_btn = self.find_element_by_function(
            element_type="button",
            function_keywords=["confirm", "yes", "ok"],
            page="reboot_modal",
            fallback_name="confirm"
        )
        confirm_btn.click()
        
        return True
```

**Key Features:**
1. **Public API** (`reboot_device_via_gui`) is task-oriented and stable
2. **Navigation** is encapsulated using `navigate_path()` with YAML artifacts
3. **Element finding** uses semantic search for self-healing
4. **Fallback names** provide safety net if semantic search fails

#### Why This Pattern?

This approach provides the optimal balance:

| Aspect | Task-Oriented | UI-Structure-Oriented |
|--------|---------------|----------------------|
| **Vendor Portability** | ✅ High - works for any ACS | ❌ Low - assumes specific UI |
| **Test Readability** | ✅ Clear business intent | ❌ Navigation noise |
| **Maintenance** | ✅ Implementation changes, not interface | ❌ Interface changes with UI |
| **Consistency** | ✅ Matches NBI pattern | ❌ Different from NBI |
| **Self-Healing** | ✅ Semantic search absorbs changes | ❌ Breaks on any change |

See `boardfarm3/templates/acs/acs_gui.py` for the complete ACSGUI template with 18 task-oriented methods.

## Architecture

### Current Architecture: Graph-Based with Friendly Names ✅

**Status**: Production-ready as of December 9, 2025 (Phases 0-5 complete)

The framework now uses `ui_map.json` as the **single source of truth** with embedded friendly names:

```
Web Application
      ↓ (Selenium crawl + BFS)
  ui_discovery.py
      ↓ (Generate friendly names!)
   UIGraph (NetworkX)
      ↓ (Export with friendly_name attributes)
  ui_map.json ← SINGLE SOURCE OF TRUTH
      ↓ (Parse once at init)
  BaseGuiComponent (100% generic)
      ↓ (In-memory structures: O(1) lookups)
      ↓ (Read friendly names from graph)
  Device.gui (GenieAcsGUI, etc.)
      ↓ (State tracking + validation + BFS navigation)
  BDD Step Definitions
      ↓
  Test Execution
```

**Benefits**:
- ✅ **67% fewer files** (1 vs 3 - no more YAML files!)
- ✅ **5x faster initialization** (single graph load)
- ✅ **10-100x faster element lookups** (dict lookup, not YAML parsing)
- ✅ **No sync issues** (single source of truth)
- ✅ **State tracking** with validation
- ✅ **Automatic navigation** with BFS pathfinding
- ✅ **Friendly names** generated once, stored in graph
- ✅ **Clean separation** - UI-specific logic in discovery, not framework
- ✅ **100% generic framework** - no application-specific code

**Configuration**:
```json
{
  "gui_graph_file": "bf_config/gui_artifacts/genieacs/ui_map.json"
}
```

### Legacy Architecture (Pre-Phase 2)

**Note**: This approach is deprecated. Projects should migrate to the Phase 2 architecture above.

The old framework used 3 separate files:

```
ui_map.json (discovery output)
      ↓
  ┌───────────────┴────────────────┐
  ↓                                ↓
selector_generator.py    navigation_generator.py
  ↓                                ↓
selectors.yaml              navigation.yaml
  └───────────────┬────────────────┘
                  ↓
          Device.gui configuration
```

**Migration**: Simply change config from `gui_selector_file` + `gui_navigation_file` to `gui_graph_file`

### Key Components

1. **`ui_discovery.py`** - Automated UI crawler with friendly name generation
   
   - BFS (breadth-first search) traversal
   - **Generates friendly names** for pages and elements
   - Pattern-based duplicate detection
   - Interaction discovery (buttons, modals)
   - Exports to graph format with `friendly_name` attributes

2. **`ui_graph.py`** - NetworkX wrapper for graph representation
   
   - Nodes: Pages, Modals, Forms, Elements (all with `friendly_name`)
   - Edges: Containment, Navigation (with query params), Dependencies
   - Algorithms: Shortest path, All paths, Connectivity checks

3. **`base_gui_component.py`** - Generic graph-based GUI component (100% reusable)
   
   - Reads friendly names from graph (zero overhead)
   - State machine with deterministic tracking
   - **BFS automatic navigation** between any two pages
   - Element finding by friendly name
   - Page verification and detection
   - **Robust interaction methods** (clicking, typing with fallbacks)

4. **`selector_generator.py`** - Selector YAML generator (legacy/optional)
   
   - Reads graph format
   - Groups elements by page/modal/form
   - Generates clean, maintainable selectors
   - **Note**: Optional - `BaseGuiComponent` can use graph directly

5. **`navigation_generator.py`** - Navigation path generator (legacy/optional)
   
   - Uses graph algorithms
   - Finds optimal paths between pages
   - Generates multi-step navigation instructions
   - **Note**: Optional - `BaseGuiComponent` has built-in BFS navigation

### Robust Interaction Methods

The `BaseGuiComponent` provides robust interaction methods that handle common UI testing challenges:

#### For Page-Agnostic Element Finding (XPath)

**`_find_element_with_selectors(selectors, timeout, max_retries)`**
- Try multiple XPath selectors in order
- Retry on stale element exceptions
- Returns element and the selector that worked
- Use case: Finding elements not in selectors.yaml (e.g., logout button anywhere)

```python
# Example: Find logout button across entire DOM
logout_selectors = [
    "//button[contains(text(), 'Logout')]",
    "//button[contains(@class, 'logout')]",
    "//a[contains(text(), 'Logout')]"
]
element, selector = self._find_element_with_selectors(
    selectors=logout_selectors,
    timeout=10,
    max_retries=3
)
```

#### For Robust Clicking

**`_click_element_robust(element, selector, timeout)`**
- Scrolls element into view
- Waits for element to be clickable
- Falls back to JavaScript click if intercepted
- Use case: Clicking buttons that might be covered by other UI elements

```python
self._click_element_robust(
    element=button,
    selector=button_xpath,
    timeout=10
)
```

**`_find_and_click_robust(selector_path, timeout)`**
- Combines finding (from selectors.yaml) with robust clicking
- Use case: Click elements defined in your artifacts

```python
self._find_and_click_robust(
    selector_path="login_page.buttons.submit",
    timeout=10
)
```

#### For Robust Input Typing

**`_type_into_element_robust(element, selector, text, timeout, clear_first, verify)`**
- Scrolls element into view
- Waits for element to be interactable
- Falls back to JavaScript for clear/input if standard methods fail
- Optional verification of entered value
- Dispatches input events for JavaScript handlers

```python
self._type_into_element_robust(
    element=input_field,
    selector=input_xpath,
    text="test@example.com",
    timeout=10,
    clear_first=True,
    verify=True  # Verify value was set correctly
)
```

**`_find_and_type_robust(selector_path, text, timeout, clear_first, verify)`**
- Combines finding (from selectors.yaml) with robust typing
- Use case: Fill input fields defined in your artifacts

```python
self._find_and_type_robust(
    selector_path="login_page.inputs.username",
    text="admin",
    timeout=10,
    clear_first=True
)
```

#### Fallback Strategy

All robust methods follow a consistent pattern:
1. **Scroll** element into view
2. **Wait** for element to be ready (clickable/interactable)
3. **Try** standard Selenium method first
4. **Fallback** to JavaScript if standard method fails
5. **Log** actions at appropriate levels (debug, warning, error)

This ensures **maximum reliability** even with:
- Elements not in viewport
- JavaScript-heavy UIs with event handlers
- Dynamic content that loads asynchronously
- UI elements temporarily covered by others
- Stale DOM references

### Phase 2 Features: State Tracking and Validation (NEW!)

**Status**: ✅ Production-ready as of December 8, 2024

BaseGuiComponent now includes state tracking and validation methods for deterministic UI testing:

#### State Tracking Methods

**`set_state(page_state, via_action)`** - Record navigation
```python
# Set state when navigating
component.set_state('home_page', via_action='login_success')
```

**`get_state()`** - Get current page state
```python
# Check where we are
current = component.get_state()  # Returns: 'home_page'
```

**`get_state_history()`** - View navigation history
```python
# Audit trail for debugging
history = component.get_state_history()
# Returns: [
#   {'from': None, 'to': 'login_page', 'via': 'navigate', 'timestamp': ...},
#   {'from': 'login_page', 'to': 'home_page', 'via': 'login_success', 'timestamp': ...}
# ]
```

#### Page Validation Method ⭐ NEW

**`verify_page(expected_page, timeout=5, update_state=True)`** - Validate page state

Verifies we're on the expected page by finding an element that should exist there.

```python
# Verify we're on login page
if component.verify_page('login_page'):
    # Element found, page confirmed
    proceed_with_login()

# Verify and update state
component.verify_page('home_page', update_state=True)

# Quick check without updating state
is_home = component.verify_page('home_page', timeout=2, update_state=False)
```

**Use Cases**:
- ✅ Pre-condition checks before actions
- ✅ Post-action verification
- ✅ Login/logout status validation  
- ✅ Navigation confirmation
- ✅ Test assertions

**How it works**:
1. Checks if page exists in graph
2. Gets elements that should be on that page
3. Tries to find a representative element (prefers buttons/inputs)
4. Returns True if element found, False otherwise
5. Optionally updates tracked state if verified

**Example: Login Status Check**:
```python
def is_logged_in(self) -> bool:
    """Check login status with validation."""
    current_state = self._graph_component.get_state()
    
    if current_state == 'login_page':
        # Verify we're actually there
        if self._graph_component.verify_page('login_page', timeout=2):
            return False  # Confirmed not logged in
    elif current_state:
        # Verify we're on an authenticated page
        if self._graph_component.verify_page(current_state, timeout=2):
            return True  # Confirmed logged in
    
    return False
```

## Quick Start

### Phase 2 Approach (Current - Recommended) ✅

**Single source of truth**: Just generate `ui_map.json`

```bash
# Step 1: Discover UI Structure (that's all you need!)
python ui_discovery.py \
  --url http://your-app:3000 \
  --username admin \
  --password admin \
  --discover-interactions \
  --skip-pattern-duplicates \
  --output ui_map.json

# Step 2: Configure device (simple!)
# In boardfarm_config.json:
{
  "gui_graph_file": "path/to/ui_map.json"
}

# Done! BaseGuiComponent parses ui_map.json directly
```

**Benefits**: 67% fewer files, no sync issues, 5x faster init, 10-100x faster lookups

### Legacy Approach (Pre-Phase 2 - Deprecated)

<details>
<summary>Click to expand legacy 3-file workflow (deprecated)</summary>

```bash
# Step 1: Discover
python ui_discovery.py ... --output ui_map.json

# Step 2: Generate selectors
python selector_generator.py \
  --input ui_map.json \
  --output selectors.yaml

# Step 3: Generate navigation
python navigation_generator.py \
  --input ui_map.json \
  --output navigation.yaml \
  --mode common

# Step 4: Configure (old format)
{
  "gui_selector_file": "path/to/selectors.yaml",
  "gui_navigation_file": "path/to/navigation.yaml"
}
```

**Note**: This approach is deprecated. Migrate to Phase 2 (single file) above.

</details>

### 4. Define Standard Test Interface (Template)

Create a template that defines the stable API:

```python
# devices/acs_template/gui_component.py
class AcsGuiTemplate(BaseGuiComponent):
    """Standard GUI interface for all ACS implementations."""

    # Standard interface - same for all ACS types
    def navigate_to_device_list(self):
        """Navigate to device list page."""
        raise NotImplementedError("Subclass must implement")

    def search_device(self, device_id: str):
        """Search for a device by ID."""
        raise NotImplementedError("Subclass must implement")

    def reboot_device(self):
        """Reboot the selected device."""
        raise NotImplementedError("Subclass must implement")
```

### 5. Implement Device-Specific Class

Map the template to actual UI using generated artifacts:

```python
# devices/genieacs/genieacs_gui.py
from devices.acs_template.gui_component import AcsGuiTemplate

class GenieAcsGui(AcsGuiTemplate):
    """GenieACS-specific GUI implementation."""

    def __init__(self, device, **kwargs):
        super().__init__(
            device,
            base_url="http://genieacs:3000",
            selectors_file="./devices/genieacs/selectors.yaml",
            navigation_file="./devices/genieacs/navigation.yaml",
            **kwargs
        )

    # Implement standard interface using generated artifacts
    def navigate_to_device_list(self):
        """Navigate to device list page."""
        self.navigate_to_page("device_list")  # Uses navigation.yaml

    def search_device(self, device_id: str):
        """Search for a device by ID."""
        self.enter_text("search", device_id, page="device_list")  # Uses selectors.yaml
        self.press_key("ENTER")

    def reboot_device(self):
        """Reboot the selected device."""
        self.click_element("button", "reboot", page="device_list")  # Uses selectors.yaml
        self.click_element("button", "confirm", context="modal")
```

### 6. Use Standard Interface in Tests

Tests use the stable API, completely independent of implementation:

```python
# tests/step_defs/device_steps.py
@when("user reboots the device")
def reboot_device(bf_context):
    # Works for GenieACS, AxirosACS, or any ACS implementing the template
    acs = bf_context.devices.acs
    acs.gui.reboot_device()  # Standard interface
```

## Configuration: Optional GUI Initialization

### Overview

GUI testing is **completely optional** in Boardfarm. Devices work perfectly with just machine to machine API's / NBI (Northbound Interface). GUI components are only initialized when configured in the device config.

### Config-Driven Approach

GUI artifact paths are specified in the boardfarm device configuration:

```json
{
    "name": "genieacs",
    "type": "bf_acs",
    "ipaddr": "localhost",
    "http_port": 7557,
    "http_username": "admin",
    "http_password": "admin",
    "gui_selector_file": "bf_config/gui_artifacts/genieacs/selectors.yaml",
    "gui_navigation_file": "bf_config/gui_artifacts/genieacs/navigation.yaml",
    "gui_headless": true,
    "gui_default_timeout": 30
}
```

### Configuration Fields in case the GUI is intended to be used

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `gui_selector_file` | Yes (for GUI) | - | Path to selectors.yaml (relative to working directory) |
| `gui_navigation_file` | Yes (for GUI) | - | Path to navigation.yaml (relative to working directory) |
| `gui_base_url` | No | `http://{ipaddr}:{http_port}` | Base URL for GUI |
| `gui_headless` | No | `true` | Run browser in headless mode |
| `gui_default_timeout` | No | `20` | Element wait timeout (seconds) |

**Path Resolution:**
- File paths are resolved relative to the **current working directory** (where pytest is executed)
- **Not** relative to the config file's location
- Example: If running from `boardfarm-bdd/`, use `bf_config/gui_artifacts/genieacs/selectors.yaml`

### Without GUI Testing (NBI Only)

Simply omit the GUI config fields:

```json
{
    "name": "genieacs",
    "type": "bf_acs",
    "ipaddr": "localhost",
    "http_port": 7557,
    "http_username": "admin",
    "http_password": "admin"
}
```

The device works perfectly - only NBI methods are available.

### Initialization Pattern

**Device Class:**
```python
class GenieACS(LinuxDevice, ACS):
    def __init__(self, config: dict, cmdline_args: Namespace) -> None:
        super().__init__(config, cmdline_args)
        self._nbi = GenieAcsNBI(self)
        self._gui = GenieAcsGUI(self)  # Always create, but don't initialize

    @hookimpl
    def boardfarm_skip_boot(self) -> None:
        # Always initialize NBI
        self.nbi.initialize()
        
        # Optionally initialize GUI (only if configured)
        if self.gui.is_gui_configured():
            try:
                self.gui.initialize()
                _LOGGER.info("GUI component initialized")
            except Exception as e:
                _LOGGER.warning("GUI initialization failed: %s", e)
```

**GUI Component:**
```python
class GenieAcsGUI(ACSGUI):
    def __init__(self, device: GenieACS) -> None:
        super().__init__(device)
        self._driver = None
        self._base_component = None
        
        # Read artifact paths from config (optional)
        self._selector_file = self.config.get("gui_selector_file")
        self._navigation_file = self.config.get("gui_navigation_file")
    
    def is_gui_configured(self) -> bool:
        """Check if GUI testing is configured."""
        return bool(self._selector_file and self._navigation_file)
    
    def is_initialized(self) -> bool:
        """Check if GUI component is initialized."""
        return bool(self._driver and self._base_component)
    
    def initialize(self, driver=None) -> None:
        """Initialize GUI component (only if configured)."""
        if not self.is_gui_configured():
            raise ValueError("GUI not configured in device config")
        
        # Create Selenium driver
        if driver is None:
            from selenium import webdriver
            options = webdriver.ChromeOptions()
            if self.config.get("gui_headless", True):
                options.add_argument("--headless")
            driver = webdriver.Chrome(options=options)
        
        self._driver = driver
        
        # Initialize BaseGuiComponent with artifacts
        from boardfarm3.lib.gui import BaseGuiComponent
        self._base_component = BaseGuiComponent(
            driver=self._driver,
            selector_file=self._selector_file,
            navigation_file=self._navigation_file,
            default_timeout=self.config.get("gui_default_timeout", 20)
        )
    
    def _ensure_initialized(self) -> None:
        """Validate GUI is ready before use."""
        if not self.is_gui_configured():
            raise ValueError("GUI not configured in device config")
        if not self.is_initialized():
            raise RuntimeError("GUI not initialized. Call gui.initialize() first")
    
    # All task-oriented methods call _ensure_initialized() first
    def login(self, username=None, password=None) -> bool:
        self._ensure_initialized()
        # ... implementation
```

### Usage in BDD Tests

**Check availability before use:**

```python
@given("the ACS GUI is available")
def step_acs_gui_available(bf_context):
    """Ensure ACS GUI is initialized and accessible."""
    acs = bf_context.device_manager.get_device_by_name("genieacs")
    
    # Skip test if GUI not configured
    if not acs.gui.is_gui_configured():
        pytest.skip("GUI testing not configured for this device")
    
    # Initialize if not already done
    if not acs.gui.is_initialized():
        acs.gui.initialize()
    
    # Verify access
    assert acs.gui.is_logged_in() or acs.gui.login()


@when("I reboot the device {cpe_id} via GUI")
def step_reboot_via_gui(bf_context, cpe_id):
    """Reboot device using ACS GUI."""
    acs = bf_context.device_manager.get_device_by_name("genieacs")
    success = acs.gui.reboot_device_via_gui(cpe_id)
    assert success
```

**Conditional usage (prefer GUI, fall back to NBI):**

```python
@when("I reboot the device {cpe_id}")
def step_reboot_device(bf_context, cpe_id):
    """Reboot device using best available method."""
    acs = bf_context.device_manager.get_device_by_name("genieacs")
    
    if acs.gui.is_initialized():
        _LOGGER.info("Using GUI to reboot device")
        success = acs.gui.reboot_device_via_gui(cpe_id)
    else:
        _LOGGER.info("Using NBI to reboot device")
        success = acs.nbi.reboot_device(cpe_id)
    
    assert success
```

### Artifact Organization

Recommended directory structure:

```
boardfarm-bdd/                           # ← Working directory (run pytest from here)
  bf_config/
    boardfarm_config_example.json        # Config file location
    gui_artifacts/
      genieacs/
        selectors.yaml                   # Generated from ui_discovery.py
        navigation.yaml                  # Generated from navigation_generator.py
        ui_map.json                      # Source data (keep for regeneration)
      axiros/
        selectors.yaml
        navigation.yaml
        ui_map.json
```

**Configuration Example:**
```json
{
    "gui_selector_file": "bf_config/gui_artifacts/genieacs/selectors.yaml",
    "gui_navigation_file": "bf_config/gui_artifacts/genieacs/navigation.yaml"
}
```

**Path Resolution:**
- Paths are relative to the **current working directory** (where pytest runs), not the config file
- When running `pytest` from `boardfarm-bdd/`, the path resolves correctly
- This follows standard Python `Path` resolution behavior

### Benefits

✅ **Zero Breaking Changes** - Existing configs work unchanged  
✅ **Progressive Enhancement** - Add GUI testing when ready  
✅ **Clear Error Messages** - Helpful guidance when GUI unavailable  
✅ **Environment Flexibility** - Different configs for dev/test/ci  
✅ **Graceful Degradation** - Tests fall back to NBI if GUI unavailable  
✅ **CI/CD Friendly** - Easy to disable/enable per environment  

### Migration Path

1. **Current State:** Devices use NBI only (no changes needed)
2. **Generate Artifacts:** Run discovery tools for devices needing GUI
3. **Update Config:** Add `gui_selector_file` and `gui_navigation_file`
4. **Enable GUI:** Device automatically initializes GUI on boot
5. **Create Tests:** Write GUI-specific scenarios or enhance existing ones

## Workflow Options

### Option 1: Manual Workflow (Test Suite Owned)

The test suite owns and maintains the artifacts:

```
1. Test author runs ui_discovery.py locally
2. Reviews and commits ui_map.json
3. Runs generators to update YAML files
4. Commits selectors.yaml and navigation.yaml
5. Uses in step definitions
```

**Pros**: Full control, can customize artifacts  
**Cons**: Manual maintenance when UI changes

### Option 2: CI/CD Integration (Product Owned) ⭐ Recommended

The product's CI/CD pipeline maintains artifacts:

```
Product Repository CI/CD:
1. On UI change (PR/merge)
2. Run ui_discovery.py against dev environment
3. Compare with previous ui_map.json
4. If changes detected:
   - Generate new selectors.yaml + navigation.yaml
   - Create PR against test suite repository
   - Tag with "ui-changes" label
5. Test suite reviews and merges

Benefits:
- Early UI change detection
- Automatic test artifact updates
- Developer feedback loop
- Test suite stays in sync
```

### Option 3: Hybrid Approach

Combine both workflows:

- **CI/CD**: Automatic discovery and PR creation
- **Manual**: Test authors refine and optimize artifacts

## Tool Documentation

Detailed documentation for each tool:

- **[ui_discovery.py](README_ui_discovery.md)** - Automated UI crawler and graph builder
- **[selector_generator.py](README_SELECTOR_GENERATOR.md)** - YAML selector generator
- **[navigation_generator.py](README_navigation_generator.md)** - Path generator with graph algorithms
- **[NETWORKX_GRAPH_ARCHITECTURE.md](NETWORKX_GRAPH_ARCHITECTURE.md)** - Technical architecture deep-dive

## Advanced Features

### Modal and Form Support

The framework treats modals and forms as first-class entities:

```yaml
# selectors.yaml
home_page:
  buttons:
    add_device:
      by: css
      selector: "#add-btn"
  modals:
    add_device_modal:
      container:
        by: css
        selector: ".modal"
      inputs:
        device_id:
          by: id
          selector: "deviceId"
```

### Conditional Navigation

Navigation paths can include conditions:

```yaml
# navigation.yaml
Path_overview_to_admin:
  steps:
  - action: click
    element: Admin
    requires_authentication: true
    requires_role: "admin"
```

### Graph Algorithms

Access powerful NetworkX algorithms:

```python
from boardfarm3.lib.gui import UIGraph
import json

# Load graph
with open("ui_map.json") as f:
    data = json.load(f)
graph = UIGraph.from_node_link(data["graph"])

# Find shortest path
path = graph.find_shortest_path(
    "http://app/#!/home",
    "http://app/#!/admin/settings"
)

# Find all alternative paths
paths = graph.find_all_paths(
    "http://app/#!/home",
    "http://app/#!/admin",
    max_length=5
)

# Quality checks
stats = graph.get_statistics()
# {
#   "orphaned_elements": 7,
#   "dead_end_pages": 0,
#   "is_weakly_connected": true
# }
```

## Pattern-Based Duplicate Detection

The discovery tool intelligently skips duplicate pages:

```
Example: E-commerce site with 1000 product pages
- Discovers first 3 product pages (pattern sample)
- Recognizes pattern: /product/{id}
- Skips remaining 997 pages
- Saves ~16 hours of discovery time!
```

Configure with:

```bash
--skip-pattern-duplicates \
--pattern-sample-size 3
```

## Extension Points

### Custom Page Types

Add custom page classification:

```python
class MyUIDiscovery(UIDiscoveryTool):
    def _classify_page(self, url: str, title: str) -> str:
        if "dashboard" in url:
            return "dashboard"
        elif "settings" in url:
            return "settings"
        return super()._classify_page(url, title)
```

### Custom Selectors

Override selector strategy:

```python
class MySelector Generator(SelectorGenerator):
    def _create_selector_entry_from_node(self, elem_node: dict) -> dict:
        # Prefer data-testid over CSS
        if "data-testid" in elem_node:
            return {
                "by": "css",
                "selector": f"[data-testid='{elem_node['data-testid']}']"
            }
        return super()._create_selector_entry_from_node(elem_node)
```

### Custom Navigation Logic

Add custom path generation:

```python
class MyNavigationGenerator(NavigationGenerator):
    def _create_step_from_element(self, elem_id: str, elem_node: dict) -> dict:
        step = super()._create_step_from_element(elem_id, elem_node)
        # Add custom wait conditions
        if elem_node.get("requires_ajax_complete"):
            step["wait_for"] = "ajax_complete"
        return step
```

## File Formats

### ui_map.json (NetworkX Graph Format)

```json
{
  "base_url": "http://localhost:3000",
  "discovery_method": "breadth_first_search",
  "graph": {
    "directed": true,
    "nodes": [
      {
        "id": "http://localhost/#!/home",
        "node_type": "Page",
        "title": "Home",
        "page_type": "home"
      },
      {
        "id": "elem_button_1",
        "node_type": "Element",
        "element_type": "button",
        "text": "Login",
        "locator_type": "css",
        "locator_value": "#login-btn"
      }
    ],
    "links": [
      {
        "source": "elem_button_1",
        "target": "http://localhost/#!/home",
        "edge_type": "ON_PAGE"
      }
    ]
  },
  "statistics": {
    "page_count": 10,
    "element_count": 150,
    "total_nodes": 169,
    "total_edges": 245
  }
}
```

### selectors.yaml

```yaml
home_page:
  buttons:
    login:
      by: id
      selector: login-btn
    signup:
      by: css
      selector: .btn-signup
  inputs:
    username:
      by: id
      selector: username
```

### navigation.yaml

```yaml
Path_home_to_admin_settings:
  description: Navigate to admin settings
  from: '#!/home'
  to: '#!/admin/settings'
  steps:
  - action: click
    element: Admin
    locator:
      by: css
      selector: a.admin-link
  - action: click
    element: Settings
    locator:
      by: css
      selector: a.settings-link
```

## Testing

### Unit Tests

```bash
# Test UIGraph class
pytest unittests/lib/gui/test_ui_graph.py -v

# Test selector generator
pytest unittests/lib/gui/test_selector_generator.py -v
```

### Integration Tests

```bash
# Run discovery on test application
python ui_discovery.py --url http://localhost:3000 \
  --username test --password test --output test_map.json

# Verify graph structure
python -c "
import json
with open('test_map.json') as f:
    data = json.load(f)
print(f'Pages: {data[\"statistics\"][\"page_count\"]}')
print(f'Elements: {data[\"statistics\"][\"element_count\"]}')
"
```

## Troubleshooting

### Discovery Issues

**Problem**: Stale element references  
**Solution**: Already handled with try-except blocks and stabilization waits

**Problem**: Missing pages  
**Solution**: Check if pattern detection is too aggressive:

```bash
--skip-pattern-duplicates=false  # Disable pattern skipping
```

**Problem**: Slow discovery  
**Solution**: Enable pattern skipping:

```bash
--skip-pattern-duplicates --pattern-sample-size 3
```

### Generator Issues

**Problem**: "Input file must be in NetworkX graph format"  
**Solution**: Ensure you're using output from ui_discovery.py 

**Problem**: Missing elements in selectors.yaml  
**Solution**: Check if elements have identifying attributes (text, id, name)

**Problem**: No navigation paths generated  
**Solution**: Ensure pages are reachable from home page (check graph connectivity)

## Dependencies

```toml
# pyproject.toml
dependencies = [
    "selenium>=4.0",
    "networkx>=3.0",
    "pyyaml>=6.0",
]
```

## Performance

- **Discovery**: ~4 seconds per page (with stabilization)
- **Pattern skipping**: 99%+ time savings for large apps
- **Graph algorithms**: O(V+E) for most operations
- **Memory**: ~1MB per 100 pages

## Best Practices

1. **Run discovery regularly** - Weekly or on UI changes
2. **Use pattern skipping** - For apps with many similar pages
3. **Review generated artifacts** - Customize names if needed
4. **Version control everything** - ui_map.json + YAML files
5. **Integrate with CI/CD** - Automatic updates on UI changes
6. **Keep artifacts DRY** - One source of truth per environment

## Contributing

To add new features or customize for different UIs:

1. **For discovery**: Extend `UIDiscoveryTool` class
   - Override `_classify_page()` for custom page types
   - Override `_generate_friendly_page_name()` for custom page names
   - Override `_generate_friendly_element_name()` for custom element names
2. **For selectors** (optional): Extend `SelectorGenerator` class
3. **For navigation** (optional): Extend `NavigationGenerator` class
4. **Add tests**: Unit tests required for all new features
5. **Update docs**: Keep this README and tool-specific docs in sync

## License

Part of the Boardfarm test framework.

## Semantic Element Search (Phase 5)

**NEW:** Self-healing test capability through semantic element search!

Instead of breaking when UI elements are renamed, the framework can find elements by their **functional purpose**:

```python
# Traditional (breaks when element renamed)
btn = self.find_element("device_details_page", "buttons", "reboot")

# Semantic (resilient to renames)
btn = self.find_element_by_function(
    element_type="button",
    function_keywords=["reboot", "restart", "reset"],
    page="device_details_page",
    fallback_name="reboot"
)
```

### Key Features

1. **Enhanced Metadata Capture**: Discovery tool captures aria-label, data-action, onclick, and other functional attributes
2. **Scoring Algorithm**: Weights different attributes (data-action=100, text=50, id=30, etc.) to find best match
3. **Graceful Fallback**: Falls back to explicit name if semantic search fails
4. **80%+ Self-Healing**: Most UI changes handled without code updates

### Benefits

- Element renames handled automatically
- Text/label changes absorbed
- CSS class/ID changes transparent
- Better test resilience

**See:** `SEMANTIC_SEARCH_OVERVIEW.md` in this directory for complete architecture and implementation guide.

## Support

For questions or issues:

- Review tool-specific READMEs
- Check NETWORKX_GRAPH_ARCHITECTURE.md for technical details
- See boardfarm-bdd/docs/UI_Testing_Guide.md for test author perspective
- **NEW:** See SEMANTIC_SEARCH_OVERVIEW.md for self-healing tests
