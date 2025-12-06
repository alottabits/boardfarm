# Semantic Element Search - Quick Overview

## What Is It?

A self-healing test capability that finds UI elements by their **functional purpose** rather than explicit names, making tests resilient to UI changes.

## The Problem

Traditional UI tests break when elements are renamed:

```python
# Test code
btn = self.find_element("device_details_page", "buttons", "reboot")

# selectors.yaml changes from "reboot" to "restart_device"
# ❌ Test breaks - element name "reboot" not found
```

## The Solution

Semantic search finds elements by function, using metadata:

```python
# Test code with semantic search
btn = self.find_element_by_function(
    element_type="button",
    function_keywords=["reboot", "restart", "reset"],
    page="device_details_page",
    fallback_name="reboot"
)

# selectors.yaml changes from "reboot" to "restart_device"
# ✅ Test still works - "restart" keyword matches "restart_device"
```

## How It Works

### 1. Enhanced Discovery

The `ui_discovery.py` tool captures rich functional metadata:

```yaml
# selectors.yaml with metadata
device_details_page:
  buttons:
    restart_device:
      by: "css"
      selector: "#btn-restart"
      text: "Restart CPE"              # Visible text
      aria_label: "reboot"              # Accessibility label
      data_action: "device.reboot"      # Functional attribute
      title: "Reboot the device"        # Tooltip
      class: "btn btn-warning"
```

### 2. Scoring Algorithm

`find_element_by_function()` scores each element:

| Attribute | Match Type | Score | Example |
|-----------|------------|-------|---------|
| data-action | Exact | 100 | "device.reboot" contains "reboot" |
| text | Exact | 50 | "Restart" == "restart" |
| text | Partial | 25 | "Restart Device" contains "restart" |
| id | Contains | 30 | "btn-restart" contains "restart" |
| title | Contains | 20 | "Reboot the device" contains "reboot" |
| aria-label | Contains | 20 | "reboot" contains "reboot" |
| class | Contains | 10 | "btn-reboot" contains "reboot" |

### 3. Best Match Selection

Returns element with highest score:

```python
# Search for: function_keywords=["reboot", "restart"]
# 
# Element "restart_device" scores:
#   data_action "device.reboot" → +100 (contains "reboot")
#   text "Restart CPE" → +25 (contains "restart")
#   title "Reboot the device" → +20 (contains "reboot")
#   Total: 145 points
#
# Element "save_config" scores:
#   text "Save Configuration" → 0 (no match)
#   Total: 0 points
#
# Winner: "restart_device" ✅
```

### 4. Graceful Fallback

If semantic search finds no matches, falls back to explicit name:

```python
# Semantic search returns 0 matches
# Falls back to explicit name "reboot"
# If that also fails: clear error message with guidance
```

## Benefits

| Change Type | Traditional | Semantic Search |
|-------------|-------------|-----------------|
| Element renamed | ❌ Breaks | ✅ Works (finds by keywords) |
| Text changed | ❌ Breaks | ✅ Works (matches new text) |
| ID changed | ❌ Breaks | ✅ Works (finds by function) |
| data-action added | ❌ Still breaks | ✅ Works (stronger match!) |
| Complete redesign | ❌ Breaks | ⚠️ Fallback (needs update) |

**Result:** 80%+ of UI changes handled without code updates!

## Usage Pattern

### Device Implementation (Private Helpers)

```python
class GenieAcsGUI(ACSGUI):
    """GenieACS GUI with semantic search."""
    
    # Public API (stable)
    def reboot_device_via_gui(self, cpe_id: str) -> bool:
        """Reboot device via GUI."""
        self._navigate_to_device_details(cpe_id)
        self._click_reboot_button()
        self._confirm_reboot()
        return True
    
    # Private helper (uses semantic search)
    def _click_reboot_button(self) -> None:
        """Find and click reboot button."""
        btn = self._get_reboot_button()
        btn.click()
    
    def _get_reboot_button(self):
        """Get reboot button using semantic search."""
        return self.find_element_by_function(
            element_type="button",
            function_keywords=["reboot", "restart", "reset"],
            page="device_details_page",
            fallback_name="reboot"
        )
```

### When UI Changes

**Before:** Button labeled "Reboot Device"  
**After:** Button labeled "Restart CPE"

**Impact:**
1. Regenerate selectors.yaml (automated in CI)
2. Semantic search finds new element automatically
3. **No code changes needed** ✅

## Best Practices

### 1. Choose Descriptive Keywords

✅ **Good:** Action-oriented, purposeful
```python
function_keywords=["save", "submit", "confirm"]
function_keywords=["delete", "remove", "trash"]
function_keywords=["search", "filter", "find"]
```

❌ **Bad:** Too generic or implementation-specific
```python
function_keywords=["button", "click"]  # Too generic
function_keywords=["btn-123", "primary"]  # Implementation detail
```

### 2. Provide Fallback for Critical Paths

```python
# Always include fallback for important operations
self.find_element_by_function(
    function_keywords=["delete", "remove"],
    fallback_name="delete_device"  # Explicit fallback
)
```

### 3. Use in Private Helpers Only

Keep public API simple:

```python
# ✅ Good: Public method is simple
def reboot_device_via_gui(self, cpe_id: str) -> bool:
    self._click_reboot_button()  # Implementation hidden

# ✅ Good: Complexity in private helper
def _click_reboot_button(self):
    btn = self.find_element_by_function(...)  # Semantic magic
    btn.click()

# ❌ Bad: Semantic search in public API
def reboot_device_via_gui(self, cpe_id: str) -> bool:
    btn = self.find_element_by_function(...)  # Too much detail
```

## Implementation Status

- [x] Architecture designed (Dec 6, 2024)
- [ ] Phase 5.1: Enhanced discovery metadata capture
- [ ] Phase 5.2: Semantic search implementation in BaseGuiComponent
- [ ] Phase 5.3: ACSGUI template definition
- [ ] Phase 5.4: GenieAcsGUI implementation with semantic helpers
- [ ] Phase 5.5: Documentation and migration guide

## Next Steps

1. **Enhance ui_discovery.py** to capture aria-label, data-action, onclick
2. **Update selector_generator.py** to include metadata in YAML
3. **Implement find_element_by_function()** in BaseGuiComponent
4. **Define ACSGUI template** with task-oriented methods (following NBI pattern)
5. **Implement GenieAcsGUI** with semantic helpers

## See Also

- **Discovery Tool:** `ui_discovery.py` - Enhanced metadata capture
- **Base Component:** `base_gui_component.py` - Semantic search engine
- **NBI Pattern:** `../../templates/acs/acs_nbi.py` - Task-oriented template example
- **Graph Architecture:** `NETWORKX_GRAPH_ARCHITECTURE.md` - Graph-based UI representation
- **Selector Generator:** `README_SELECTOR_GENERATOR.md` - YAML artifact generation

