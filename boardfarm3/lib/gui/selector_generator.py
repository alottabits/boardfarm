"""Selector YAML Generator for UI Test Artifacts.

This tool converts the UI discovery graph (NetworkX format) into a clean,
human-readable selectors.yaml file that can be used to configure a device's
GUI component (e.g., GenieAcsGui).

The input MUST be in NetworkX node-link format from ui_discovery.py.

The generated YAML follows the "Flat Name" architecture conventions:
- Pages as top-level keys
- Logical grouping of elements
- Modal/Form awareness (first-class support)
- Locators only (no behavioral information)
- Clear, descriptive naming
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

try:
    from .ui_graph import UIGraph
except ImportError:
    from boardfarm3.lib.gui.ui_graph import UIGraph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class SelectorGenerator:
    """Converts a UI discovery JSON map (NetworkX graph format) into a selectors.yaml file.
    
    This generator transforms the graph-based discovery data into a structured
    YAML format that is optimized for maintainability and human readability.
    
    The input must be in NetworkX node-link format from ui_discovery.py.
    
    Attributes:
        discovery_data: Parsed JSON data from ui_discovery.py (graph format)
        graph: UIGraph instance reconstructed from discovery data
        selectors: Dictionary to build the YAML structure
    """

    def __init__(self, discovery_file: str):
        """Initialize the selector generator.
        
        Args:
            discovery_file: Path to the UI discovery JSON file (NetworkX format)
            
        Raises:
            ValueError: If input file is not in NetworkX graph format
        """
        with open(discovery_file) as f:
            self.discovery_data = json.load(f)
        
        if "graph" not in self.discovery_data:
            raise ValueError(
                "Input file must be in NetworkX graph format. "
                "Please use ui_discovery.py to generate the graph."
            )
        
        # Load NetworkX format
        self.graph = UIGraph.from_node_link(self.discovery_data["graph"])
        page_count = len(self.graph.get_pages())
        logger.info("Loaded NetworkX graph format from %s", discovery_file)
        logger.info("Found %d pages, %d modals, %d forms", 
                   page_count, 
                   len(self.graph.get_modals()),
                   len(self.graph.get_forms()))
        
        self.selectors: dict[str, Any] = {}

    def generate(self) -> dict[str, Any]:
        """Generate the complete selectors structure from NetworkX graph.
        
        Returns:
            Dictionary representing the selectors YAML structure
        """
        logger.info("Generating selectors from discovery data...")
        
        # Process all pages
        for page_id in self.graph.get_pages():
            self._process_page_from_graph(page_id)
        
        # Process all modals (as separate sections)
        for modal_id in self.graph.get_modals():
            self._process_modal_from_graph(modal_id)
        
        # Forms are processed as part of their containers (pages or modals)
        
        logger.info("Generated selectors for %d pages", len(self.selectors))
        return self.selectors

    def _process_page_from_graph(self, page_id: str) -> None:
        """Process a page from the graph structure.
        
        Args:
            page_id: Page node ID (URL)
        """
        page_node = self.graph.G.nodes[page_id]
        
        # Generate page key
        page_key = self._generate_page_key_from_node(page_node, page_id)
        
        if page_key not in self.selectors:
            self.selectors[page_key] = {}
        
        # Get all elements on this page (returns tuples)
        page_elements = self.graph.get_container_elements(page_id)
        
        # Group elements by type
        buttons = []
        inputs = []
        links = []
        tables = []
        
        for elem_id, elem_node in page_elements:
            element_type = elem_node.get("element_type", "")
            
            if element_type == "button":
                buttons.append((elem_id, elem_node))
            elif element_type == "input":
                inputs.append((elem_id, elem_node))
            elif element_type == "link":
                links.append((elem_id, elem_node))
            elif element_type == "table":
                tables.append((elem_id, elem_node))
        
        # Process each element type
        self._process_elements_from_graph(page_key, "buttons", buttons)
        self._process_elements_from_graph(page_key, "inputs", inputs)
        self._process_elements_from_graph(page_key, "links", links, limit=10)
        self._process_elements_from_graph(page_key, "tables", tables)
        
        # Check for forms on this page
        forms_on_page = [
            form_id for form_id in self.graph.get_forms()
            if self.graph.G.has_edge(form_id, page_id)
        ]
        
        for form_id in forms_on_page:
            self._process_form_from_graph(page_key, form_id)
    
    def _process_modal_from_graph(self, modal_id: str) -> None:
        """Process a modal from the graph structure.
        
        Args:
            modal_id: Modal node ID
        """
        modal_node = self.graph.G.nodes[modal_id]
        
        # Find the parent page
        parent_page = modal_node.get("parent_page", "unknown")
        page_key = self._generate_page_key_from_url(parent_page)
        
        if page_key not in self.selectors:
            self.selectors[page_key] = {}
        
        if "modals" not in self.selectors[page_key]:
            self.selectors[page_key]["modals"] = {}
        
        # Generate modal name
        modal_title = modal_node.get("title", "")
        modal_name = self._sanitize_name(modal_title or "unnamed_modal")
        
        if modal_name not in self.selectors[page_key]["modals"]:
            self.selectors[page_key]["modals"][modal_name] = {}
        
        modal = self.selectors[page_key]["modals"][modal_name]
        
        # Add modal container selector if available
        locator_type = modal_node.get("locator_type")
        locator_value = modal_node.get("locator_value")
        if locator_type and locator_value:
            modal["container"] = {
                "by": locator_type,
                "selector": locator_value,
            }
        
        # Get all elements in this modal (returns tuples)
        modal_elements = self.graph.get_container_elements(modal_id)
        
        # Group elements by type
        buttons = []
        inputs = []
        selects = []
        
        for elem_id, elem_node in modal_elements:
            element_type = elem_node.get("element_type", "")
            
            if element_type == "button":
                buttons.append((elem_id, elem_node))
            elif element_type == "input":
                inputs.append((elem_id, elem_node))
            elif element_type == "select":
                selects.append((elem_id, elem_node))
        
        # Process each element type within modal
        if buttons:
            modal["buttons"] = {}
            for elem_id, elem_node in buttons:
                elem_name = self._generate_element_name_from_node(elem_node, "button")
                if elem_name:
                    modal["buttons"][elem_name] = self._create_selector_entry_from_node(elem_node)
        
        if inputs:
            modal["inputs"] = {}
            for elem_id, elem_node in inputs:
                elem_name = self._generate_element_name_from_node(elem_node, "input")
                if elem_name:
                    modal["inputs"][elem_name] = self._create_selector_entry_from_node(elem_node)
        
        if selects:
            modal["selects"] = {}
            for elem_id, elem_node in selects:
                elem_name = self._generate_element_name_from_node(elem_node, "select")
                if elem_name:
                    selector_entry = self._create_selector_entry_from_node(elem_node)
                    # Add options if available
                    if "options" in elem_node:
                        selector_entry["options"] = elem_node["options"]
                    modal["selects"][elem_name] = selector_entry
    
    def _process_form_from_graph(self, page_key: str, form_id: str) -> None:
        """Process a form from the graph structure.
        
        Args:
            page_key: Parent page key
            form_id: Form node ID
        """
        form_node = self.graph.G.nodes[form_id]
        form_name = self._sanitize_name(form_node.get("form_name", "unnamed_form"))
        
        if "forms" not in self.selectors[page_key]:
            self.selectors[page_key]["forms"] = {}
        
        if form_name not in self.selectors[page_key]["forms"]:
            self.selectors[page_key]["forms"][form_name] = {}
        
        form = self.selectors[page_key]["forms"][form_name]
        
        # Get all elements in this form (returns tuples)
        form_elements = self.graph.get_container_elements(form_id)
        
        # Group elements by type
        inputs = []
        buttons = []
        
        for elem_id, elem_node in form_elements:
            element_type = elem_node.get("element_type", "")
            
            if element_type == "input":
                inputs.append((elem_id, elem_node))
            elif element_type == "button":
                buttons.append((elem_id, elem_node))
        
        # Process inputs and buttons
        if inputs:
            form["inputs"] = {}
            for elem_id, elem_node in inputs:
                elem_name = self._generate_element_name_from_node(elem_node, "input")
                if elem_name:
                    form["inputs"][elem_name] = self._create_selector_entry_from_node(elem_node)
        
        if buttons:
            form["buttons"] = {}
            for elem_id, elem_node in buttons:
                elem_name = self._generate_element_name_from_node(elem_node, "button")
                if elem_name:
                    form["buttons"][elem_name] = self._create_selector_entry_from_node(elem_node)
    
    def _process_elements_from_graph(self, page_key: str, element_group: str, 
                                     elements: list[tuple[str, dict]], limit: int = None) -> None:
        """Process a list of elements from the graph.
        
        Args:
            page_key: Page key in selectors
            element_group: Element group name (buttons, inputs, links, tables)
            elements: List of (element_id, element_node) tuples
            limit: Optional limit on number of elements to process
        """
        if not elements:
            return
        
        # Apply limit if specified
        if limit:
            elements = elements[:limit]
        
        if element_group not in self.selectors[page_key]:
            self.selectors[page_key][element_group] = {}
        
        for elem_id, elem_node in elements:
            # Skip "Log out" links and empty text
            text = elem_node.get("text", "").strip()
            if element_group == "links" and (not text or text in ["", " ", "Log out"]):
                continue
            
            elem_name = self._generate_element_name_from_node(elem_node, element_group.rstrip("s"))
            if elem_name:
                selector_entry = self._create_selector_entry_from_node(elem_node)
                
                # Add special handling for tables (include headers)
                if element_group == "tables" and "headers" in elem_node:
                    selector_entry["headers"] = elem_node["headers"]
                
                self.selectors[page_key][element_group][elem_name] = selector_entry
    
    def _generate_page_key_from_node(self, page_node: dict, page_id: str) -> str:
        """Generate a clean page key from a graph node.
        
        Args:
            page_node: Page node dictionary
            page_id: Page node ID (URL)
            
        Returns:
            Clean page key (e.g., 'home_page', 'device_list_page')
        """
        # First try to use page_type
        page_type = page_node.get("page_type", "unknown")
        
        if page_type and page_type != "unknown":
            return f"{page_type}_page" if not page_type.endswith("_page") else page_type
        
        # Fall back to URL-based naming
        return self._generate_page_key_from_url(page_id)
    
    def _generate_page_key_from_url(self, url: str) -> str:
        """Generate a clean page key from a URL.
        
        Args:
            url: Page URL
            
        Returns:
            Clean page key
        """
        parsed = urlparse(url)
        
        # For hash-based routing, use the fragment
        path = parsed.fragment if parsed.fragment else parsed.path
        
        # Clean the path
        if path.startswith("!"):
            path = path[1:]
        
        # Extract meaningful name from path
        segments = [s for s in path.split("/") if s and "?" not in s]
        if segments:
            name = segments[0]
            return f"{self._sanitize_name(name)}_page"
        
        return "unknown_page"
    
    def _generate_element_name_from_node(self, elem_node: dict, default_prefix: str) -> str:
        """Generate a descriptive name for an element from graph node.
        
        Args:
            elem_node: Element node dictionary
            default_prefix: Prefix to use if no better name is found
            
        Returns:
            Generated element name
        """
        # Try different naming strategies in order of preference
        
        # 1. Use text content
        text = elem_node.get("text", "").strip()
        if text:
            return self._sanitize_name(text)
        
        # 2. Use name attribute
        name = elem_node.get("name", "").strip()
        if name:
            return self._sanitize_name(name)
        
        # 3. Use title attribute
        title = elem_node.get("title", "").strip()
        if title:
            return self._sanitize_name(title)
        
        # 4. Use placeholder
        placeholder = elem_node.get("placeholder", "").strip()
        if placeholder:
            return self._sanitize_name(placeholder)
        
        # 5. Use ID from attributes
        elem_id = elem_node.get("id", "").strip()
        if elem_id:
            return self._sanitize_name(elem_id)
        
        # 6. Use type
        elem_type = elem_node.get("type", "").strip()
        if elem_type and elem_type not in ["button", "text", "submit"]:
            return f"{elem_type}_{default_prefix}"
        
        # Fall back to default
        return default_prefix
    
    def _create_selector_entry_from_node(self, elem_node: dict) -> dict[str, str]:
        """Create a selector entry for an element from graph node.
        
        Args:
            elem_node: Element node dictionary
            
        Returns:
            Dictionary with 'by', 'selector', and enhanced metadata keys (Phase 5.1)
        """
        locator_type = elem_node.get("locator_type", "css_selector")
        locator_value = elem_node.get("locator_value", "")
        
        # Map graph locator types to selector types
        by_strategy = locator_type
        selector = locator_value
        
        # If CSS selector is an ID (starts with #), use ID strategy
        if locator_type == "css_selector" and locator_value.startswith("#"):
            by_strategy = "id"
            selector = locator_value[1:]  # Remove the #
        
        # If selector looks like XPath, use xpath strategy
        elif locator_value.startswith("//") or locator_value.startswith("(//"):
            by_strategy = "xpath"
        
        entry = {
            "by": by_strategy,
            "selector": selector,
        }
        
        # Phase 5.1: Include enhanced metadata for semantic search
        # These attributes enable find_element_by_function() to locate elements
        # by their functional purpose even when IDs/names change
        
        metadata_fields = [
            "text", "title", "aria_label", "data_action", "data_target",
            "onclick_hint", "role", "data_toggle", "data_dismiss",
            "placeholder", "value", "autocomplete",
            "button_id", "button_class", "button_type",
            "input_id", "input_type", "name",
            "select_id", "link_id", "link_class", "href"
        ]
        
        for field in metadata_fields:
            value = elem_node.get(field)
            if value:  # Only include non-None, non-empty values
                entry[field] = value
        
        return entry
    
    def _sanitize_name(self, name: str) -> str:
        """Convert a string into a valid YAML key.
        
        Args:
            name: Raw name string
            
        Returns:
            Sanitized name suitable for YAML key
        """
        # Replace special characters with underscores
        name = re.sub(r"[^\w\s-]", "", name)
        # Replace whitespace with underscores
        name = re.sub(r"[\s-]+", "_", name)
        # Convert to lowercase
        name = name.lower()
        # Remove leading/trailing underscores
        name = name.strip("_")
        
        return name or "unnamed"
    
    def save_yaml(self, output_file: str) -> None:
        """Save the selectors to a YAML file.
        
        Args:
            output_file: Path to output YAML file
        """
        output_path = Path(output_file)
        
        # Generate selectors if not already done
        if not self.selectors:
            self.generate()
        
        # Create output directory if needed
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write YAML with nice formatting
        with output_path.open("w") as f:
            # Add header comment
            f.write("# UI Element Selectors\n")
            f.write("# Auto-generated from UI discovery\n")
            f.write("# \n")
            f.write("# Structure: page_name -> element_group -> element_name -> locator\n")
            f.write("# Each locator has 'by' (strategy) and 'selector' (value)\n")
            f.write("#\n\n")
            
            yaml.dump(
                self.selectors,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                width=120,
            )
        
        logger.info("Selectors saved to %s", output_path)


def main():
    """Command-line interface for selector generator."""
    parser = argparse.ArgumentParser(
        description="Generate selectors.yaml from UI discovery JSON"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input UI discovery JSON file (from ui_discovery.py)",
    )
    parser.add_argument(
        "--output",
        default="selectors.yaml",
        help="Output selectors YAML file (default: selectors.yaml)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Generate selectors
    logger.info("Starting selector generation...")
    try:
        generator = SelectorGenerator(args.input)
        generator.generate()
        generator.save_yaml(args.output)
        
        logger.info("Selector generation complete!")
        logger.info("Generated %d page sections", len(generator.selectors))
    except ValueError as e:
        logger.error("Error: %s", e)
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())

