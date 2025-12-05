# UI Discovery Tool

Automated web UI crawler and mapper for generating comprehensive UI structure documentation.

## Purpose

The `ui_discovery.py` tool crawls a web application to discover its structure, including pages, elements, navigation paths, and interactive components. It generates a detailed JSON map that can be used for:

- Automated test artifact generation (`selectors.yaml`, `navigation.yaml`)
- UI change detection and monitoring
- Navigation path analysis
- Documentation generation
- Test maintenance automation

## Features

### Core Features

- **🔍 Automatic UI Crawling**: Discovers all reachable pages using Breadth-First Search (BFS)
- **🔗 NetworkX Graph**: Builds a graph representation with pages, modals, forms, and elements as nodes
- **📊 Element Discovery**: Captures buttons, inputs, links, tables on each page
- **🏷️ Page Classification**: Automatically classifies page types (home, device_list, etc.)
- **🔐 Authentication**: Handles login flows for protected applications

### Advanced Features

- **🎯 URL Pattern Recognition**: Detects and generalizes repetitive URL structures (e.g., `#!/devices/{device_id}`)
- **🚀 Pattern-Based Skipping**: Intelligently skips duplicate URLs after sampling, reducing crawl time by 99%+ for production systems
- **🎭 Interaction Discovery**: Clicks safe buttons to discover modals, dialogs, and dynamic content
- **🔄 State Recovery**: Safely restores page state after interactions
- **⚡ Hash-based Routing**: Full support for Single Page Applications (SPAs)

## Installation Requirements

```bash
pip install selenium pyyaml
```

**Browser Requirements:**
- Firefox browser installed
- geckodriver installed (via snap or package manager)

```bash
# Install Firefox (if not already installed)
sudo snap install firefox

# Install geckodriver
sudo snap install geckodriver
```

## Usage

### Basic Usage

```bash
# Minimal crawl without authentication
python boardfarm/boardfarm3/lib/gui/ui_discovery.py \
  --url http://127.0.0.1:3000 \
  --no-login \
  --output ui_map.json
```

### With Authentication

```bash
# Crawl with login
python boardfarm/boardfarm3/lib/gui/ui_discovery.py \
  --url http://127.0.0.1:3000 \
  --username admin \
  --password admin \
  --output ui_map.json
```

### Full-Featured Discovery

```bash
# Complete discovery with all features enabled
python boardfarm/boardfarm3/lib/gui/ui_discovery.py \
  --url http://127.0.0.1:3000 \
  --username admin \
  --password admin \
  --discover-interactions \
  --skip-pattern-duplicates \
  --pattern-sample-size 3 \
  --output ui_map_complete.json \
  --headless
```

### Debugging Mode

```bash
# Run with visible browser for debugging
python boardfarm/boardfarm3/lib/gui/ui_discovery.py \
  --url http://127.0.0.1:3000 \
  --username admin \
  --password admin \
  --no-headless \
  --output ui_map.json
```

## Command-Line Options

### Required Options

| Option | Type | Description |
|--------|------|-------------|
| `--url` | string | Base URL of the application to crawl |

### Authentication Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--username` | string | None | Login username (optional) |
| `--password` | string | None | Login password (optional) |
| `--login-url` | string | None | Custom login URL (defaults to base URL) |
| `--no-login` | flag | False | Skip login step entirely |

### Crawl Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--headless` | flag | True | Run browser in headless mode |
| `--no-headless` | flag | - | Run browser with GUI (for debugging) |
| `--output` | string | `ui_map.json` | Output file path |

**Note:** The tool uses **Breadth-First Search (BFS)** to crawl all reachable pages automatically. There is no depth limit - crawling continues until all discoverable pages are visited.

### Pattern Detection Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--disable-pattern-detection` | flag | False | Disable URL pattern recognition |
| `--pattern-min-count` | int | 3 | Minimum URLs required to form a pattern |
| `--skip-pattern-duplicates` | flag | False | Skip URLs matching patterns after sampling (huge time savings!) |
| `--pattern-sample-size` | int | 3 | Number of pattern instances to crawl before skipping |

### Interaction Discovery Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--discover-interactions` | flag | False | Enable button click and modal discovery |
| `--safe-buttons` | string | `New,Add,Edit,View,Show,Cancel,Close` | Comma-separated safe button text patterns |
| `--interaction-timeout` | int | 2 | Seconds to wait for modals after clicking |

## URL Pattern Recognition

The tool automatically detects repetitive URL patterns where multiple pages share the same structure but differ in specific segments (typically IDs).

### How It Works

1. Groups URLs by structure (same path segments except last)
2. Identifies variable segments (usually IDs or identifiers)
3. Generates parameterized templates
4. Extracts common page structure from instances

### Example

**Input URLs:**
```
http://127.0.0.1:3000/#!/devices/ABC123
http://127.0.0.1:3000/#!/devices/DEF456
http://127.0.0.1:3000/#!/devices/GHI789
```

**Detected Pattern:**
```json
{
  "pattern": "#!/devices/{device_id}",
  "description": "Devices detail page",
  "parameter_name": "device_id",
  "count": 15,
  "example_urls": ["...", "...", "..."],
  "page_structure": {
    "common_buttons": ["Reboot", "Reset", "Delete"],
    "common_inputs": []
  }
}
```

### Benefits

- **Reduces redundancy** in UI maps (15 device pages → 1 pattern)
- **Identifies parameterized routes** for dynamic testing
- **Preserves examples** for reference (up to 5 URLs)
- **Extracts common structure** for template generation

### Configuration

```bash
# Require at least 5 similar URLs to form a pattern
python boardfarm/boardfarm3/lib/gui/ui_discovery.py \
  --url http://127.0.0.1:3000 \
  --username admin \
  --password admin \
  --pattern-min-count 5 \
  --output ui_map.json

# Disable pattern detection entirely
python boardfarm/boardfarm3/lib/gui/ui_discovery.py \
  --url http://127.0.0.1:3000 \
  --username admin \
  --password admin \
  --disable-pattern-detection \
  --output ui_map_full.json
```

## Interaction Discovery

Discovers modal dialogs, forms, and dynamic content by clicking "safe" buttons on each page.

### How It Works

1. **Button Identification**: Finds buttons matching safe patterns
2. **Click & Wait**: Clicks button and waits for modals to appear
3. **Modal Capture**: Records modal title, buttons, inputs, selects
4. **Safe Closure**: Closes modal using standard close methods
5. **State Recovery**: Navigates back to original page URL

### Safety Controls

**Default Safe Patterns:**
- `New`, `Add`, `Edit`, `View`, `Show` - Creation/viewing actions
- `Cancel`, `Close` - Dismissal actions

**Excluded Patterns (Never Clicked):**
- `Delete`, `Remove` - Destructive operations
- `Reset`, `Reboot` - State-changing operations
- `Submit`, `Save` - May commit unwanted changes

**Recovery Mechanisms:**
- Timeout protection (configurable, default 2 seconds)
- Automatic page reload on errors
- Multiple modal close strategies (button, ESC key)

### Example Output

```json
{
  "interactions": [
    {
      "trigger": {
        "type": "button",
        "text": "New",
        "selector": "button.primary"
      },
      "result": {
        "type": "modal",
        "title": "New Preset",
        "css_selector": ".modal",
        "buttons": [
          {
            "text": "Save",
            "type": "submit",
            "css_selector": "button[type='submit']"
          },
          {
            "text": "Cancel",
            "css_selector": "button.cancel"
          }
        ],
        "inputs": [
          {
            "type": "text",
            "name": "name",
            "placeholder": "Preset name",
            "required": true,
            "css_selector": "input[name='name']"
          }
        ],
        "selects": [
          {
            "name": "provision",
            "options": ["bootstrap", "default", "inform"],
            "css_selector": "select[name='provision']"
          }
        ]
      }
    }
  ]
}
```

### Custom Configuration

```bash
# Customize safe button patterns
python boardfarm/boardfarm3/lib/gui/ui_discovery.py \
  --url http://127.0.0.1:3000 \
  --username admin \
  --password admin \
  --discover-interactions \
  --safe-buttons "New,Add,Create,Edit,View,Details,Configure" \
  --interaction-timeout 3 \
  --output ui_map.json
```

## Output Format

The tool generates a **NetworkX graph in node-link JSON format**, which can be loaded by downstream tools (selector_generator.py, navigation_generator.py) or visualized with graph tools.

### Legacy Format Reference

For reference, the previous flat JSON structure looked like this:

### Current Format (NetworkX Graph)

The tool now outputs a **NetworkX node-link format**:

```json
{
  "directed": true,
  "multigraph": false,
  "graph": {},
  "nodes": [
    {
      "id": "http://127.0.0.1:3000/#!/overview",
      "node_type": "Page",
      "title": "Overview - GenieACS",
      "page_type": "home"
    },
    {
      "id": "elem_button_1",
      "node_type": "Element",
      "element_type": "button",
      "text": "Log out",
      "locator_type": "id",
      "locator_value": "logout-btn"
    }
  ],
  "links": [
    {
      "source": "elem_button_1",
      "target": "http://127.0.0.1:3000/#!/overview",
      "edge_type": "ON_PAGE"
    }
  ]
}
```

**Benefits of Graph Format:**
- Enables graph algorithms (shortest path, reachability analysis)
- Supports complex relationships (modals, forms, conditional navigation)
- Compatible with NetworkX for further analysis
- Can be exported to GraphML/GEXF for visualization

### Legacy Flat Format (Deprecated)

The old flat structure (no longer generated):

```json
{
  "base_url": "http://127.0.0.1:3000",
  "pages": [
    {
      "url": "http://127.0.0.1:3000/#!/overview",
      "title": "Overview - GenieACS",
      "page_type": "home",
      "buttons": [
        {
          "text": "Log out",
          "title": "Log out",
          "id": "logout-btn",
          "class": "btn btn-link",
          "css_selector": "#logout-btn"
        }
      ],
      "inputs": [
        {
          "type": "text",
          "name": "search",
          "id": "search-input",
          "placeholder": "Search...",
          "css_selector": "#search-input"
        }
      ],
      "links": [
        {
          "text": "Devices",
          "href": "http://127.0.0.1:3000/#!/devices",
          "css_selector": "a[href='#!/devices']"
        }
      ],
      "tables": [
        {
          "id": "device-table",
          "class": "table",
          "headers": ["ID", "Serial", "Status"],
          "css_selector": "#device-table"
        }
      ],
      "interactions": [
        {
          "trigger": {...},
          "result": {...}
        }
      ]
    }
  ],
  "url_patterns": [
    {
      "pattern": "#!/devices/{device_id}",
      "description": "Devices detail page",
      "parameter_name": "device_id",
      "example_urls": [...],
      "count": 15,
      "page_structure": {...}
    }
  ],
  "navigation_graph": {
    "http://127.0.0.1:3000/#!/overview": {
      "title": "Overview - GenieACS",
      "page_type": "home",
      "links": [
        {
          "href": "http://127.0.0.1:3000/#!/devices",
          "text": "Devices",
          "selector": "a[href='#!/devices']"
        }
      ]
    }
  }
}
```

## Analyzing Discovery Results

### View Basic Statistics

**Using Python and UIGraph:**
```python
from boardfarm3.lib.gui.ui_graph import UIGraph

# Load the graph
graph = UIGraph.from_node_link("ui_map.json")

# Get statistics
stats = graph.get_statistics()
print(f"Pages: {stats['page_count']}")
print(f"Modals: {stats['modal_count']}")
print(f"Elements: {stats['element_count']}")
print(f"Navigation links: {stats['navigation_count']}")

# List all pages
for page_id, attrs in graph.get_pages():
    print(f"{attrs['page_type']}: {page_id}")
```

**Using jq (for node-link format):**
```bash
# Count total pages
cat ui_map.json | jq '[.nodes[] | select(.node_type == "Page")] | length'

# List all page types
cat ui_map.json | jq '[.nodes[] | select(.node_type == "Page").page_type] | unique'

# Count elements by type
cat ui_map.json | jq '[.nodes[] | select(.node_type == "Element").element_type] | group_by(.) | map({type: .[0], count: length})'
```

### Analyze Modals and Forms

**Using Python and UIGraph:**
```python
# Count modals
modals = list(graph.get_modals())
print(f"Total modals: {len(modals)}")

# List modals by page
for page_id, _ in graph.get_pages():
    page_modals = list(graph.get_page_modals(page_id))
    if page_modals:
        print(f"{page_id}: {len(page_modals)} modals")
```

**Using jq:**
```bash
# Count modals
cat ui_map.json | jq '[.nodes[] | select(.node_type == "Modal")] | length'

# List all modals with their parent pages
cat ui_map.json | jq '[.nodes[] | select(.node_type == "Modal") | {title: .title, parent: .parent_page}]'

# Count forms
cat ui_map.json | jq '[.nodes[] | select(.node_type == "Form")] | length'
```

### Analyze Navigation Paths

**Using Python and UIGraph:**
```python
# Find shortest path between pages
path = graph.find_shortest_path(
    "http://127.0.0.1:3000/#!/overview",
    "http://127.0.0.1:3000/#!/devices/ABC123"
)
print(f"Path length: {len(path)} steps")

# Find all paths (up to 5)
all_paths = graph.find_all_paths(
    "http://127.0.0.1:3000/#!/overview",
    "http://127.0.0.1:3000/#!/admin/users",
    cutoff=5
)
print(f"Alternative paths: {len(all_paths)}")
```

**Using jq:**
```bash
# Count navigation links
cat ui_map.json | jq '[.links[] | select(.edge_type == "NAVIGATES_TO")] | length'

# List pages by connectivity (incoming/outgoing edges)
cat ui_map.json | jq '[.links[] | .target] | group_by(.) | map({page: .[0], incoming: length}) | sort_by(.incoming) | reverse | .[0:5]'
```

## Testing

### Unit Tests

Run the pattern detection unit tests:

```bash
cd /home/rjvisser/projects/req-tst/boardfarm
source ../boardfarm-bdd/.venv-3.12/bin/activate
python -m pytest unittests/lib/gui/test_pattern_detection.py -v
```

**Test Coverage:**
- ✅ Simple pattern detection (basic ID patterns)
- ✅ Threshold filtering (minimum count enforcement)
- ✅ Multiple pattern types simultaneously
- ✅ GenieACS device serial number patterns
- ✅ Page structure extraction
- ✅ Hash-based and path-based routing
- ✅ Custom threshold configuration

All 7 tests passing.

### Integration Testing

Test with a real application:

```bash
# GenieACS example (comprehensive test)
python ../boardfarm/boardfarm3/lib/gui/ui_discovery.py \
  --url http://127.0.0.1:3000 \
  --username admin \
  --password admin \
  --discover-interactions \
  --skip-pattern-duplicates \
  --pattern-sample-size 3 \
  --output ui_map_genieacs.json

# Verify output
cat ui_map_genieacs.json | jq '.pages | length'
cat ui_map_genieacs.json | jq '.url_patterns | length'
cat ui_map_genieacs.json | jq '[.pages[] | select(.interactions)] | length'
```

**Expected Results for GenieACS:**
- All reachable pages discovered automatically (BFS traversal)
- 1 URL pattern detected: `#!/devices/{device_id}` (with 3 samples if using `--skip-pattern-duplicates`)
- 4-6 pages with interactions (Presets, Provisions, Files, Virtual Parameters)
- Common buttons: `["Log out", "Reboot", "Reset", "Push file", "Delete"]`
- Admin sub-pages: users, permissions, config, presets, provisions, virtualparameters

**How BFS Works:**
The tool starts from the home page and systematically:
1. Discovers all links on the current page level
2. Visits each discovered page
3. Repeats until no new pages are found
4. Automatically stops when the entire UI is mapped

## Page Classification

The tool automatically classifies pages based on URL patterns:

| Pattern | Classification |
|---------|----------------|
| `/login` | `login` |
| `/devices/ID` | `device_details` |
| `/devices` | `device_list` |
| `/tasks` | `tasks` |
| `/files` | `files` |
| `/presets` | `presets` |
| `/admin` | `admin` |
| `/` or empty | `home` |
| Other | `unknown` |

## Integration Workflow

### Complete UI Testing Workflow

```bash
# Step 1: Discover UI structure
python boardfarm/boardfarm3/lib/gui/ui_discovery.py \
  --url http://127.0.0.1:3000 \
  --username admin \
  --password admin \
  --discover-interactions \
  --output ui_map.json

# Step 2: Generate selectors YAML
python boardfarm/boardfarm3/lib/gui/selector_generator.py \
  --input ui_map.json \
  --output tests/ui_helpers/acs_selectors.yaml

# Step 3: Generate navigation YAML
python boardfarm/boardfarm3/lib/gui/navigation_generator.py \
  --input ui_map.json \
  --output tests/ui_helpers/acs_navigation.yaml \
  --mode common

# Step 4: Use artifacts in tests
# The YAML files configure GenieAcsGui component
```

### Change Detection Workflow

```bash
# Step 1: Create baseline
python boardfarm/boardfarm3/lib/gui/ui_discovery.py \
  --url http://127.0.0.1:3000 \
  --username admin \
  --password admin \
  --output baseline_ui_map.json

# Step 2: After UI changes, scan again
python boardfarm/boardfarm3/lib/gui/ui_discovery.py \
  --url http://127.0.0.1:3000 \
  --username admin \
  --password admin \
  --output current_ui_map.json

# Step 3: Compare graphs (using NetworkX)
python -c "
from boardfarm3.lib.gui.ui_graph import UIGraph
baseline = UIGraph.from_node_link('baseline_ui_map.json')
current = UIGraph.from_node_link('current_ui_map.json')

baseline_stats = baseline.get_statistics()
current_stats = current.get_statistics()

print('Page count change:', current_stats['page_count'] - baseline_stats['page_count'])
print('Element count change:', current_stats['element_count'] - baseline_stats['element_count'])
"
```

## Performance Considerations

### Crawl Time Factors

| Factor | Impact | Typical Time |
|--------|--------|--------------|
| **Page Count** | Linear | ~2-5s per page (headless) |
| **Pattern Skipping** | Massive reduction | 99%+ time savings |
| **Interaction Discovery** | 1.5-2x multiplier | +5-10s per page with buttons |
| **Application Size** | Variable | Small: 1-2 min, Medium: 3-5 min, Large: 10+ min (without pattern skipping) |

### BFS Traversal Characteristics

- **Systematic**: Discovers all reachable pages level-by-level
- **Complete**: Automatically finds all linked pages
- **Natural termination**: Stops when no new pages are found
- **Predictable**: Page count depends on application structure, not arbitrary depth limits

### Optimization Tips

1. **Use pattern skipping** for production systems: `--skip-pattern-duplicates --pattern-sample-size 3` (reduces crawl time by 99%+)
2. **Skip interaction discovery** for basic structure mapping (save for periodic comprehensive scans)
3. **Use headless mode** (default) for faster execution
4. **Increase timeout** for slow-loading pages: `--interaction-timeout 3`
5. **Adjust pattern threshold** for your needs: `--pattern-min-count 5` (higher = fewer patterns detected)

## Troubleshooting

### Common Issues

**Firefox/geckodriver not found:**
```bash
sudo snap install firefox
sudo snap install geckodriver
```

**Login fails:**
- Check credentials
- Use `--no-headless` to watch the login process
- Provide custom `--login-url` if needed
- Check for CAPTCHA or 2FA requirements

**Pattern not detected:**
- Check `--pattern-min-count` (default: 3 URLs required)
- Use `--disable-pattern-detection` to see all pages
- Verify URLs share common structure

**Modal not captured:**
- Check button text matches `--safe-buttons` patterns
- Increase `--interaction-timeout` for slow-loading modals
- Use `--no-headless` to debug modal appearance

**Missing pages:**
- BFS automatically discovers all reachable pages - if a page is missing, it's not linked
- Check if pages require specific navigation sequence (e.g., form submission)
- Verify links are standard `<a>` tags (not JavaScript handlers without href)
- Confirm pages aren't behind permission checks or conditional UI

**Stale Element Reference Exceptions:**
- These are common in Single Page Applications (SPAs) where the DOM updates dynamically
- The tool now handles these gracefully by:
  - Extracting element attributes immediately upon discovery
  - Using try-except blocks to skip stale elements
  - Adding a 0.5s stabilization wait after navigation
- Most stale element errors are logged at DEBUG level and don't affect the crawl
- If you see frequent stale element errors, your SPA may need longer to stabilize:
  - Use `--skip-pattern-duplicates` to limit crawling of similar pages
  - Consider running discovery during periods of low server activity
  - Check that the application is not continuously polling/updating

**Admin sub-pages not discovered:**
- Some SPAs redirect from entry pages (e.g., `/#!/admin` → `/#!/admin/presets`)
- The tool discovers all links on each page, so sub-pages should be found
- If sub-pages are missing, they may be behind:
  - JavaScript-only navigation (not `<a>` tags)
  - Permission checks that require specific user roles
  - Client-side routing without href attributes

### Debug Mode

```bash
# Run with visible browser and verbose logging
python boardfarm/boardfarm3/lib/gui/ui_discovery.py \
  --url http://127.0.0.1:3000 \
  --username admin \
  --password admin \
  --no-headless \
  --output ui_map.json 2>&1 | tee discovery_debug.log
```

## Best Practices

1. **Test login first**: Use `--no-headless` to verify authentication works before full crawl
2. **Use pattern skipping for production**: Enable `--skip-pattern-duplicates --pattern-sample-size 3` to avoid crawling thousands of similar pages
3. **Periodic full scans**: Run comprehensive scans weekly or on major releases
4. **Version control outputs**: Commit UI maps for change tracking (use NetworkX node-link format)
5. **Review patterns**: Verify detected patterns make sense for your app structure
6. **Customize safe buttons**: Add application-specific safe button patterns for interaction discovery
7. **Optimize interaction discovery**: Run without `--discover-interactions` for quick structural scans, enable for comprehensive periodic scans
8. **SPAs require special handling**: For Single Page Applications:
   - The tool automatically waits 0.5s for DOM stabilization after navigation
   - Stale element exceptions are handled gracefully (logged at DEBUG level)
   - Use `--skip-pattern-duplicates` to avoid crawling thousands of similar pages
   - Test with `--no-headless` first to understand the application's behavior
9. **Clean test data**: Remove offline devices or test entries before discovery to avoid:
   - Unnecessary crawling of error/empty pages
   - Long timeouts on non-responsive entities
   - Skewed pattern detection
10. **Let BFS complete**: The BFS algorithm naturally discovers all reachable pages - don't interrupt unless crawl time is excessive

## Limitations

1. **JavaScript navigation**: Only follows standard `<a>` href links
2. **Dynamic content**: May miss content loaded after page load (unless using `--discover-interactions`)
3. **Authentication**: Only supports form-based login
4. **Single domain**: Does not crawl external links
5. **Rate limiting**: No built-in rate limiting for sites with protections

## Future Enhancements

- Configurable wait strategies for dynamic content
- Support for OAuth/SSO authentication
- Parallel crawling for faster execution
- Custom page classification rules
- Screenshot capture for visual regression
- Integration with accessibility auditing
- API endpoint discovery from network traffic

## Related Documentation

- **[Stale Element Fixes](../../../boardfarm-bdd/docs/ui_discovery_stale_element_fixes.md)**: Deep dive into handling stale element exceptions in SPAs
- **[Pattern Skipping](PATTERN_SKIPPING.md)**: Smart URL pattern detection and duplicate skipping
- **[Automated UI Maintenance Strategy](../../../boardfarm-bdd/docs/automated_ui_maintenance_strategy.md)**: Complete CI/CD integration guide
- **[Selector Generator](README_SELECTOR_GENERATOR.md)**: Converting UI maps to selectors.yaml

## Pattern-Based Skipping (NEW!)

**Massive time savings for production systems!**

When your system has hundreds of similar pages (devices, users, products), the tool can now:
- Sample N instances of each pattern (default: 3)
- Skip remaining duplicate URLs
- Reduce crawl time by 99%+

See [PATTERN_SKIPPING.md](./PATTERN_SKIPPING.md) for complete documentation.

**Quick Example:**
```bash
# Before: 47 devices × 30 sec = 23 minutes
# After: 3 devices × 30 sec = 90 seconds (15x faster!)

python ui_discovery.py \
  --url http://127.0.0.1:3000 \
  --username admin \
  --password admin \
  --skip-pattern-duplicates \
  --pattern-sample-size 3
```

## Related Tools

- **selector_generator.py**: Converts NetworkX graph to `selectors.yaml` ✅ Implemented
- **navigation_generator.py**: Converts NetworkX graph to `navigation.yaml` ✅ Implemented
- **ui_graph.py**: NetworkX wrapper for graph operations ✅ Implemented
- **BaseGuiComponent**: Consumes generated YAML artifacts in device implementations

## Support

For issues or questions:
1. Check this README for configuration options
2. Run tests to verify installation: `pytest unittests/lib/gui/test_pattern_detection.py -v`
3. Use debug mode: `--no-headless` to visually inspect crawl behavior
4. Review logs for error messages

