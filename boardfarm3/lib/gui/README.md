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

1. **Discover** your application's UI structure
2. **Generate** mapping artifacts (selectors.yaml, navigation.yaml)
3. **Enable** device-specific implementations to fulfill the standard interface

## Boardfarm Standardization Pattern

### Machine-to-Machine APIs vs GUI - Same Pattern

Boardfarm uses the **same architectural pattern** for both M2M and GUI interfaces:

| Aspect              | M2M APIs (e.g., CPE)               | GUI APIs (e.g., ACS)                  |
| ------------------- | ---------------------------------- | ------------------------------------- |
| **Template**        | `CpeTemplate` defines standard API | `AcsGuiTemplate` defines standard API |
| **Implementations** | `PrplOsCpe`, `OpenWrtCpe`          | `GenieAcsGui`, `AxirosAcsGui`         |
| **Mapping**         | Protocol adapters (TR-069, SSH)    | selectors.yaml + navigation.yaml      |
| **Test Interface**  | `cpe.reboot()`                     | `acs.gui.reboot_device()`             |
| **Discovery Tools** | Manual implementation              | **Automated** (ui_discovery.py)       |

**Key Insight:** The UI discovery tools **automatically generate the mapping artifacts** (selectors.yaml, navigation.yaml) that connect your stable test interface to the actual UI implementation.

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
│   ├── selectors.yaml              # UI element mapping (generated)
│   └── navigation.yaml             # Navigation paths (generated)
│
└── axirosacs/                        # Another implementation
    ├── axirosacs_gui.py
    ├── axirosacs_nbi.py
    ├── axirosacs_device.py
    ├── selectors.yaml              # Different UI, same interface
    └── navigation.yaml
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

## Architecture

The framework is built around a **graph-based Page Object Model (POM)**:

```
Web Application
      ↓ (Selenium crawl)
  ui_discovery.py
      ↓ (BFS traversal)
   UIGraph (NetworkX)
      ↓ (Export)
  ui_map.json (graph format)
      ↓
  ┌───────────────┴────────────────┐
  ↓                                ↓
selector_generator.py    navigation_generator.py
  ↓                                ↓
selectors.yaml              navigation.yaml
  └───────────────┬────────────────┘
                  ↓
          Device.gui configuration
                  ↓
         BDD Step Definitions
                  ↓
            Test Execution
```

### Key Components

1. **`ui_graph.py`** - NetworkX wrapper for graph representation
   
   - Nodes: Pages, Modals, Forms, Elements
   - Edges: Containment, Navigation (with query params), Dependencies
   - Algorithms: Shortest path, All paths, Connectivity checks

2. **`ui_discovery.py`** - Automated UI crawler
   
   - BFS (breadth-first search) traversal
   - Pattern-based duplicate detection
   - Interaction discovery (buttons, modals)
   - Exports to graph format

3. **`selector_generator.py`** - Selector YAML generator
   
   - Reads graph format
   - Groups elements by page/modal/form
   - Generates clean, maintainable selectors

4. **`navigation_generator.py`** - Navigation path generator
   
   - Uses graph algorithms
   - Finds optimal paths between pages
   - Generates multi-step navigation instructions

5. **`base_gui_component.py`** - Base class for GUI components
   
   - Selenium wrapper
   - Element finding and interaction
   - Navigation path execution

## Quick Start

### 1. Discover UI Structure

```bash
python ui_discovery.py \
  --url http://your-app:3000 \
  --username admin \
  --password admin \
  --discover-interactions \
  --skip-pattern-duplicates \
  --output ui_map.json
```

**Output**: `ui_map.json` - NetworkX graph with pages, elements, and navigation

### 2. Generate Selectors

```bash
python selector_generator.py \
  --input ui_map.json \
  --output selectors.yaml
```

**Output**: `selectors.yaml` - Organized element locators

### 3. Generate Navigation Paths

```bash
python navigation_generator.py \
  --input ui_map.json \
  --output navigation.yaml \
  --mode common
```

**Output**: `navigation.yaml` - Optimal navigation paths

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

To add new features:

1. **For discovery**: Extend `UIDiscoveryTool` class
2. **For selectors**: Extend `SelectorGenerator` class
3. **For navigation**: Extend `NavigationGenerator` class
4. **Add tests**: Unit tests required for all new features
5. **Update docs**: Keep this README and tool-specific docs in sync

## License

Part of the Boardfarm test framework.

## Support

For questions or issues:

- Review tool-specific READMEs
- Check NETWORKX_GRAPH_ARCHITECTURE.md for technical details
- See boardfarm-bdd/docs/UI_Testing_Guide.md for test author perspective
