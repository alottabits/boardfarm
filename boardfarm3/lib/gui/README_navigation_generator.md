# Navigation Generator - Automated Path Generation Using Graph Algorithms

## Overview

The `navigation_generator.py` tool uses NetworkX graph algorithms to automatically generate optimal navigation paths between pages in your web application. It reads the graph output from `ui_discovery.py` and creates a `navigation.yaml` file with multi-step navigation instructions.

## Features

- **Graph Algorithm-Based**: Uses NetworkX shortest path and all paths algorithms
- **Multi-Step Journeys**: Automatically discovers complex navigation sequences
- **Three Generation Modes**: Common paths, specific paths, or all alternative routes
- **Modal Awareness**: Includes modal opening in navigation steps
- **Conditional Support**: Tracks authentication, role, and input requirements

## Installation

The navigation generator is part of the boardfarm UI testing framework:

```bash
# Ensure dependencies are installed
pip install networkx>=3.0 pyyaml>=6.0
```

## Usage

### Mode 1: Common Paths (Recommended)

Automatically detect the home page and generate paths to all major pages:

```bash
python navigation_generator.py \
  --input ui_map.json \
  --output navigation.yaml \
  --mode common
```

**Output Example**:
```yaml
Path_overview_to_admin_presets:
  description: Navigate from home to admin_presets
  from: '#!/overview'
  to: '#!/admin/presets'
  steps:
  - action: click
    element: Admin
    locator:
      by: css
      value: a
  - action: click
    element: Presets
    locator:
      by: css
      value: a
```

### Mode 2: Specific Path

Generate a single path between two pages:

```bash
python navigation_generator.py \
  --input ui_map.json \
  --output navigation_specific.yaml \
  --mode specific \
  --from-page "#!/overview" \
  --to-page "#!/admin/settings"
```

### Mode 3: All Paths

Find all possible paths (alternative routes):

```bash
python navigation_generator.py \
  --input ui_map.json \
  --output navigation_all.yaml \
  --mode all \
  --from-page "#!/home" \
  --to-page "#!/admin" \
  --max-paths 5 \
  --max-length 10
```

## Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--input` | Input ui_map.json file (required) | - |
| `--output` | Output navigation.yaml file | `navigation.yaml` |
| `--mode` | Generation mode: common, specific, all | `common` |
| `--from-page` | Starting page (for specific/all modes) | - |
| `--to-page` | Destination page (for specific/all modes) | - |
| `--max-paths` | Max alternative paths (all mode) | 5 |
| `--max-length` | Max path length in steps (all mode) | 10 |
| `--verbose` | Enable debug logging | false |

## How It Works

### 1. Graph Loading

```python
from boardfarm3.lib.gui import NavigationGenerator

generator = NavigationGenerator("ui_map.json")
# Loads NetworkX graph from ui_discovery.py output
```

### 2. Path Finding

Uses NetworkX algorithms to find optimal routes:

```python
# Shortest path
path_nodes = graph.find_shortest_path(from_url, to_url)
# Example: ['http://app/#!/home', 'http://app/#!/admin', 'http://app/#!/admin/settings']
```

### 3. Element Resolution

For each page transition, finds the navigation element:

```python
# Between page1 and page2, find the link/button that connects them
nav_element = find_navigation_element(page1, page2)
# Returns: ('elem_link_5', {element data})
```

### 4. Step Generation

Converts graph path to actionable steps:

```python
steps = [
    {
        "action": "click",
        "element": "Admin",
        "locator": {"by": "css", "value": "a.admin-link"}
    },
    {
        "action": "click",
        "element": "Settings",
        "locator": {"by": "css", "value": "a.settings-link"}
    }
]
```

## Output Format

### Basic Navigation Path

```yaml
Path_home_to_settings:
  description: Navigate from home to settings
  from: '#!/home'
  to: '#!/settings'
  steps:
  - action: click
    element: Settings Menu
    locator:
      by: id
      selector: settings-link
```

### Multi-Step Path

```yaml
Path_home_to_admin_users:
  description: Navigate from home to admin_users
  from: '#!/home'
  to: '#!/admin/users'
  steps:
  - action: click        # Step 1: Go to Admin section
    element: Admin
    locator:
      by: css
      selector: a[href='#!/admin']
  - action: click        # Step 2: Go to Users page
    element: Users
    locator:
      by: css
      selector: a[href='#!/admin/users']
```

### Path with Modal

```yaml
Path_dashboard_add_device:
  description: Navigate to add device modal
  from: '#!/dashboard'
  to: 'modal_add_device'
  steps:
  - action: open_modal
    element: Add Device
    modal: Add Device Modal
    locator:
      by: id
      selector: add-device-btn
```

### Path with Conditions

```yaml
Path_home_to_admin:
  description: Navigate to admin (requires authentication)
  from: '#!/home'
  to: '#!/admin'
  steps:
  - action: click
    element: Admin
    locator:
      by: css
      selector: a.admin-link
    requires_authentication: true
    requires_role: admin
```

## Python API

### Basic Usage

```python
from boardfarm3.lib.gui import NavigationGenerator

# Initialize
generator = NavigationGenerator("ui_map.json")

# Generate common paths
common_paths = generator.generate_common_paths()

# Save to YAML
generator.save_yaml("navigation.yaml", common_paths)
```

### Generate Specific Path

```python
# Single path
path = generator.generate_path(
    from_page="#!/home",
    to_page="#!/admin/settings"
)

print(f"Path name: {path['name']}")
print(f"Steps: {path['hops']}")
for step in path['steps']:
    print(f"  - {step['action']} {step['element']}")
```

### Find All Paths

```python
# Find alternative routes
all_paths = generator.generate_all_paths(
    from_page="#!/home",
    to_page="#!/admin",
    max_paths=5,
    max_length=10
)

print(f"Found {len(all_paths)} alternative paths:")
for path in all_paths:
    print(f"  - {path['name']}: {path['hops']} steps")
```

### Custom Path Name

```python
path = generator.generate_path(
    from_page="#!/home",
    to_page="#!/settings",
    path_name="CustomPath_HomeToSettings"
)
```

## Integration with BaseGuiComponent

Use generated navigation paths in your GUI component:

```python
class MyAppGui(BaseGuiComponent):
    def __init__(self, device, **kwargs):
        super().__init__(
            device,
            navigation_file="navigation.yaml",
            **kwargs
        )
    
    def go_to_settings(self):
        """Navigate to settings page using generated path."""
        self.navigate_path("Path_home_to_settings")
```

## Use Cases

### 1. Test Prerequisite Navigation

```python
# In step definition
@given("user is on the admin settings page")
def step_impl(bf_context):
    device = bf_context.devices.genieacs
    device.gui.navigate_path("Path_home_to_admin_settings")
```

### 2. Find Optimal Path

```python
# What's the fastest way to reach page X?
path = generator.generate_path("#!/home", "#!/admin/advanced/logs")
print(f"Shortest route: {path['hops']} steps")
```

### 3. Find Alternative Routes

```python
# If primary navigation fails, try backup route
all_paths = generator.generate_all_paths("#!/home", "#!/admin", max_paths=3)

for i, path in enumerate(all_paths):
    try:
        device.gui.execute_path(path)
        break
    except Exception as e:
        logger.warning(f"Route {i+1} failed: {e}")
        continue
```

### 4. Test Coverage Analysis

```python
# Which pages are reachable from home?
common_paths = generator.generate_common_paths()
reachable_pages = set(path['to'] for path in common_paths.values())
print(f"Reachable from home: {len(reachable_pages)} pages")
```

## Algorithm Details

### Shortest Path

Uses Dijkstra's algorithm via NetworkX:

```python
# All edges have weight=1 (each click is equal cost)
path = nx.shortest_path(graph, source=from_page, target=to_page)
```

### All Simple Paths

Uses depth-first search to find all non-repeating paths:

```python
# Find all paths without revisiting nodes
paths = nx.all_simple_paths(graph, source=from_page, target=to_page, cutoff=max_length)
```

### Home Page Detection

Automatically finds the home page using heuristics:

1. Look for "overview", "home", "index" in URL
2. Fall back to first discovered page

## Performance

- **Path finding**: O(V+E) for shortest path
- **All paths**: Exponential worst-case, but limited by `max_length`
- **Generation time**: ~0.01s per path for typical graphs
- **Memory**: Minimal (graph already loaded)

## Troubleshooting

### No Path Found

**Problem**: `ValueError: No path found between X and Y`

**Solutions**:
1. Check if both pages exist in ui_map.json
2. Verify pages are connected (not isolated)
3. Use graph.get_pages() to list available pages

```python
from boardfarm3.lib.gui import UIGraph
import json

with open("ui_map.json") as f:
    data = json.load(f)
graph = UIGraph.from_node_link(data["graph"])

# Check connectivity
pages = graph.get_pages()
print(f"Total pages: {len(pages)}")

# Try finding path
try:
    path = graph.find_shortest_path(pages[0], pages[1])
    print(f"Path exists: {len(path)} nodes")
except:
    print("No path found - pages may be disconnected")
```

### Missing Elements in Steps

**Problem**: Steps show element IDs instead of readable names

**Cause**: Elements don't have text/name attributes

**Solution**: Elements are shown with best available identifier:
1. Text content (preferred)
2. Name attribute
3. Title attribute
4. ID attribute
5. Element ID (fallback)

### Paths Too Long

**Problem**: Generated paths have too many steps

**Solution**: Use `--max-length` to limit path depth:

```bash
python navigation_generator.py \
  --input ui_map.json \
  --mode all \
  --from-page "#!/home" \
  --to-page "#!/admin" \
  --max-length 3  # Limit to 3 steps
```

## Advanced Usage

### Filter Paths by Condition

```python
# Only generate paths that don't require authentication
def generate_public_paths(generator):
    common = generator.generate_common_paths()
    public = {}
    
    for name, path in common.items():
        # Check if any step requires auth
        requires_auth = any(
            step.get('requires_authentication') 
            for step in path['steps']
        )
        if not requires_auth:
            public[name] = path
    
    return public
```

### Custom Step Processing

```python
class CustomNavigationGenerator(NavigationGenerator):
    def _create_step_from_element(self, elem_id, elem_node):
        step = super()._create_step_from_element(elem_id, elem_node)
        
        # Add custom wait logic
        if "ajax" in elem_node.get("class", ""):
            step["wait_for"] = "ajax_complete"
        
        # Add retry logic for flaky elements
        if elem_node.get("visibility_observed") == "sometimes_hidden":
            step["retry"] = 3
        
        return step
```

### Merge Multiple Navigation Files

```python
import yaml

# Load multiple navigation files
with open("nav_app1.yaml") as f:
    nav1 = yaml.safe_load(f)

with open("nav_app2.yaml") as f:
    nav2 = yaml.safe_load(f)

# Merge
merged = {**nav1, **nav2}

# Save
with open("navigation_merged.yaml", "w") as f:
    yaml.dump(merged, f)
```

## Best Practices

1. **Use common mode first** - Generates useful paths automatically
2. **Customize path names** - Make them descriptive for test readability
3. **Version control** - Commit navigation.yaml to track changes
4. **Regenerate regularly** - When UI structure changes
5. **Validate paths** - Test generated paths before deploying
6. **Keep DRY** - One navigation.yaml per environment/application

## Comparison with Manual Definition

### Manual (Old Way)

```yaml
# navigation.yaml - manually created
Path_home_to_admin:
  steps:
  - action: click
    element: Admin Menu
    locator:
      by: id
      selector: admin-menu
  # Missing intermediate steps?
  # Did we find the shortest path?
  # Is this still valid after UI changes?
```

### Generated (New Way)

```bash
# Automatically discovers optimal path
python navigation_generator.py --input ui_map.json --output navigation.yaml --mode common
```

**Benefits**:
- Finds actual shortest path
- Includes all necessary steps
- Auto-updates when UI changes
- Validated against real UI structure

## Examples

See the [main README](README.md) for complete workflow examples.

## Related Documentation

- [ui_discovery.py](README_UI_DISCOVERY.md) - Generate the input graph
- [selector_generator.py](README_SELECTOR_GENERATOR.md) - Generate selectors
- [NETWORKX_GRAPH_ARCHITECTURE.md](NETWORKX_GRAPH_ARCHITECTURE.md) - Technical architecture
- [boardfarm-bdd/docs/UI_Testing_Guide.md](../../boardfarm-bdd/docs/UI_Testing_Guide.md) - Test author guide

