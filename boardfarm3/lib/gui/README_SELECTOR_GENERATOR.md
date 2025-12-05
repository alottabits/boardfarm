# Selector Generator

Converts UI discovery JSON output into clean, maintainable `selectors.yaml` files.

## Purpose

The `selector_generator.py` tool transforms the detailed JSON output from `ui_discovery.py` into a structured YAML format that follows the "Flat Name" architecture conventions. The generated YAML file can be used to configure a device's GUI component (e.g., `GenieAcsGui`).

## Features

- **Automatic Page Organization**: Groups elements by page type
- **Intelligent Naming**: Generates descriptive names from element text, attributes, or IDs
- **Locator Strategy Detection**: Automatically chooses the best locator strategy (ID, CSS, XPath)
- **Modal Support**: Captures interactions (modals/dialogs) with their buttons, inputs, and selects
- **Human-Readable Output**: Clean YAML format with comments

## Usage

### Basic Usage

```bash
# Generate selectors from discovery JSON
python boardfarm/boardfarm3/lib/gui/selector_generator.py \
  --input ui_map.json \
  --output selectors.yaml
```

### Complete Workflow

```bash
# Step 1: Discover the UI (with interaction discovery)
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
```

### With Verbose Logging

```bash
python boardfarm/boardfarm3/lib/gui/selector_generator.py \
  --input ui_map.json \
  --output selectors.yaml \
  --verbose
```

## Input Format

Expects JSON from `ui_discovery.py` with this structure:

```json
{
  "base_url": "http://127.0.0.1:3000",
  "pages": [
    {
      "url": "http://127.0.0.1:3000/#!/overview",
      "title": "Overview - GenieACS",
      "page_type": "home",
      "buttons": [...],
      "inputs": [...],
      "links": [...],
      "tables": [...],
      "interactions": [...]
    }
  ]
}
```

## Output Format

Generates YAML with this structure:

```yaml
# UI Element Selectors
# Auto-generated from UI discovery

home_page:
  buttons:
    log_out:
      by: id
      selector: logout-btn
    refresh:
      by: css_selector
      selector: button.btn-primary
  inputs:
    search:
      by: id
      selector: search-input
  links:
    devices:
      by: css_selector
      selector: a[href='#!/devices']

device_list_page:
  buttons:
    add_device:
      by: id
      selector: add-device-btn
  modals:
    new_device:
      container:
        by: css_selector
        selector: .modal
      buttons:
        save:
          by: css_selector
          selector: button[type='submit']
        cancel:
          by: css_selector
          selector: button.cancel
      inputs:
        serial:
          by: css_selector
          selector: input[name='serial']
      selects:
        model:
          by: css_selector
          selector: select[name='model']
          options:
            - Model A
            - Model B
            - Model C
```

## Structure Conventions

1. **Top-level keys**: Page names (e.g., `home_page`, `device_list_page`)
2. **Element groups**: `buttons`, `inputs`, `links`, `tables`, `modals`
3. **Element names**: Derived from text, name attribute, title, or placeholder
4. **Locator format**: Each element has `by` (strategy) and `selector` (value)

### Locator Strategies

- **`id`**: When element has a unique ID (most reliable)
- **`css_selector`**: For class-based or attribute selectors
- **`xpath`**: When selector starts with `//` (least preferred)

## Modal/Interaction Handling

When `--discover-interactions` is used with `ui_discovery.py`, modals are captured:

```yaml
modals:
  new_preset:
    container:
      by: css_selector
      selector: .modal
    buttons:
      save:
        by: css_selector
        selector: button[type='submit']
    inputs:
      name:
        by: css_selector
        selector: input[name='name']
```

## Element Naming Logic

The generator tries these strategies in order:

1. **Text content**: Button text, link text (e.g., "Log Out" → `log_out`)
2. **Name attribute**: Input name (e.g., `name="username"` → `username`)
3. **Title attribute**: Button/element title
4. **Placeholder**: Input placeholder text
5. **ID attribute**: Element ID
6. **Type + prefix**: As fallback (e.g., `text_input`)

## Page Naming Logic

Pages are named based on:

1. **page_type**: From discovery data (e.g., `home`, `device_list`)
2. **URL path**: First segment of URL path (e.g., `/admin` → `admin_page`)
3. **Fallback**: `unknown_page`

## Testing

Run unit tests to verify functionality:

```bash
cd /home/rjvisser/projects/req-tst/boardfarm
source ../boardfarm-bdd/.venv-3.12/bin/activate
python -m pytest unittests/lib/gui/test_selector_generator.py -v
```

**Test Coverage:**
- ✅ Page key generation
- ✅ Element name sanitization
- ✅ Locator strategy detection
- ✅ Button, input, link, table processing
- ✅ Modal/interaction processing
- ✅ YAML file generation
- ✅ Empty page handling
- ✅ Duplicate element names

All 19 tests passing.

## Integration with BaseGuiComponent

The generated `selectors.yaml` is designed to work with `BaseGuiComponent`:

```python
# In your device implementation
from boardfarm3.lib.gui.base_gui_component import BaseGuiComponent

class GenieAcsGui(BaseGuiComponent):
    def __init__(self, driver, selector_file, navigation_file):
        super().__init__(driver, selector_file, navigation_file)
    
    def click_logout(self):
        # Uses dot notation to reference: home_page.buttons.log_out
        locator = self._get_locator("home_page.buttons.log_out")
        element = self.wait.until(EC.element_to_be_clickable(locator))
        element.click()
```

## Best Practices

1. **Review Generated Output**: Always review the generated YAML before using in production
2. **Customize Names**: Edit element names to be more descriptive if needed
3. **Remove Unused Elements**: Delete selectors for elements you won't use
4. **Version Control**: Commit the YAML file alongside your tests
5. **Update Regularly**: Regenerate when the UI changes significantly

## Limitations

1. **Duplicate Names**: If multiple elements have the same text/name, the last one wins
2. **No Context**: Elements are grouped by page only, not by semantic sections
3. **Selector Quality**: Quality depends on the HTML structure (IDs are best)

## Future Enhancements

- Semantic grouping within pages (e.g., `main_menu`, `sidebar`)
- Conflict resolution for duplicate names
- Selector optimization (prefer stable selectors)
- Integration with change detection to update only changed selectors

