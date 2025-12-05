"""Navigation Path Generator for UI Test Artifacts.

This tool uses the NetworkX graph representation from ui_discovery.py to
generate optimal navigation paths between pages. It leverages graph algorithms
to find the shortest paths, alternative routes, and can respect conditional
navigation requirements.

The generated YAML follows the "Flat Name" architecture conventions:
- Named paths as top-level keys
- Step-by-step instructions
- Element references
- Clear, descriptive naming

Example usage:
    python navigation_generator.py \\
        --input ui_map.json \\
        --output navigation.yaml \\
        --from-page "#!/overview" \\
        --to-page "#!/admin/presets"
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


class NavigationGenerator:
    """Generates navigation.yaml from a UI discovery graph.
    
    Uses NetworkX graph algorithms to find optimal paths between pages,
    including support for modals, forms, and conditional navigation.
    
    Attributes:
        discovery_data: Parsed JSON data from ui_discovery.py
        graph: UIGraph instance reconstructed from discovery data
        navigation_paths: Dictionary to build the YAML structure
    """

    def __init__(self, discovery_file: str):
        """Initialize the navigation generator.
        
        Args:
            discovery_file: Path to the UI discovery JSON file (NetworkX format)
        """
        with open(discovery_file) as f:
            self.discovery_data = json.load(f)
        
        if "graph" not in self.discovery_data:
            raise ValueError("Input file must be in NetworkX graph format")
        
        self.graph = UIGraph.from_node_link(self.discovery_data["graph"])
        self.base_url = self.discovery_data.get("base_url", "")
        self.navigation_paths: dict[str, Any] = {}
        
        logger.info("Loaded NetworkX graph format from %s", discovery_file)
        logger.info("Found %d pages, %d modals", 
                   len(self.graph.get_pages()),
                   len(self.graph.get_modals()))
    
    def generate_path(self, from_page: str, to_page: str, 
                      path_name: str = None) -> dict[str, Any]:
        """Generate a navigation path between two pages.
        
        Args:
            from_page: Starting page URL or fragment (e.g., "#!/overview")
            to_page: Destination page URL or fragment
            path_name: Optional custom name for this path
            
        Returns:
            Dictionary representing the navigation path
            
        Raises:
            ValueError: If either page is not found or no path exists
        """
        # Resolve page fragments to full URLs
        from_url = self._resolve_page_url(from_page)
        to_url = self._resolve_page_url(to_page)
        
        if not from_url or not to_url:
            raise ValueError(f"Could not resolve pages: {from_page} -> {to_page}")
        
        logger.info("Finding path: %s -> %s", from_url, to_url)
        
        # Find shortest path using NetworkX
        try:
            path_nodes = self.graph.find_shortest_path(from_url, to_url)
        except Exception as e:
            raise ValueError(f"No path found between {from_page} and {to_page}: {e}")
        
        logger.info("Found path with %d nodes", len(path_nodes))
        
        # Convert graph path to navigation steps
        steps = self._convert_path_to_steps(path_nodes)
        
        # Generate path name if not provided
        if not path_name:
            path_name = self._generate_path_name(from_page, to_page)
        
        return {
            "name": path_name,
            "from": from_page,
            "to": to_page,
            "steps": steps,
            "hops": len(steps),
        }
    
    def generate_all_paths(self, from_page: str, to_page: str, 
                          max_paths: int = 5, max_length: int = 10) -> list[dict[str, Any]]:
        """Generate all possible paths between two pages.
        
        Useful for finding alternative routes or testing different navigation flows.
        
        Args:
            from_page: Starting page URL or fragment
            to_page: Destination page URL or fragment
            max_paths: Maximum number of paths to return
            max_length: Maximum path length (number of steps)
            
        Returns:
            List of path dictionaries
        """
        from_url = self._resolve_page_url(from_page)
        to_url = self._resolve_page_url(to_page)
        
        if not from_url or not to_url:
            raise ValueError(f"Could not resolve pages: {from_page} -> {to_page}")
        
        logger.info("Finding all paths: %s -> %s (max: %d, length: %d)", 
                   from_url, to_url, max_paths, max_length)
        
        # Find all simple paths
        all_path_nodes = self.graph.find_all_paths(from_url, to_url, max_length=max_length)
        
        # Convert to navigation paths
        paths = []
        for idx, path_nodes in enumerate(all_path_nodes[:max_paths]):
            steps = self._convert_path_to_steps(path_nodes)
            path_name = self._generate_path_name(from_page, to_page, variant=idx+1)
            
            paths.append({
                "name": path_name,
                "from": from_page,
                "to": to_page,
                "steps": steps,
                "hops": len(steps),
            })
        
        logger.info("Found %d paths", len(paths))
        return paths
    
    def generate_common_paths(self) -> dict[str, Any]:
        """Generate navigation paths for common UI flows.
        
        Automatically detects important pages and generates useful paths:
        - From home/overview to all major sections
        - To admin pages
        - To commonly visited pages
        
        Returns:
            Dictionary of navigation paths
        """
        logger.info("Generating common navigation paths...")
        
        pages = self.graph.get_pages()
        
        # Find home page (overview, index, or first page)
        home_page = self._find_home_page(pages)
        
        if not home_page:
            logger.warning("Could not find home page")
            return {}
        
        logger.info("Using home page: %s", home_page)
        
        # Generate paths from home to all major pages
        paths = {}
        for page in pages:
            if page == home_page:
                continue
            
            try:
                path = self.generate_path(home_page, page)
                path_name = path["name"]
                paths[path_name] = {
                    "description": f"Navigate from home to {self._get_page_name(page)}",
                    "from": self._get_page_fragment(home_page),
                    "to": self._get_page_fragment(page),
                    "steps": path["steps"],
                }
            except ValueError as e:
                logger.debug("Skipping path to %s: %s", page, e)
        
        logger.info("Generated %d common paths", len(paths))
        return paths
    
    def _convert_path_to_steps(self, path_nodes: list[str]) -> list[dict[str, Any]]:
        """Convert a list of graph nodes to navigation steps.
        
        The path may be page-only [page1, page2, page3] due to MAPS_TO edges,
        or alternating [page1, element1, page2, element2, page3].
        We need to find the actual navigation elements.
        
        Args:
            path_nodes: List of node IDs from graph path
            
        Returns:
            List of step dictionaries
        """
        steps = []
        
        for i in range(len(path_nodes) - 1):
            current_page = path_nodes[i]
            next_page = path_nodes[i + 1]
            
            # Check node types
            current_node = self.graph.G.nodes[current_page]
            next_node = self.graph.G.nodes[next_page]
            
            # If next node is a page, find the navigation element
            if next_node.get("node_type") == "Page":
                # Find element that navigates from current_page to next_page
                nav_element = self._find_navigation_element(current_page, next_page)
                
                if nav_element:
                    elem_id, elem_node = nav_element
                    step = self._create_step_from_element(elem_id, elem_node)
                    
                    # Check for conditional requirements
                    edge_data = self.graph.G.get_edge_data(elem_id, next_page)
                    if edge_data:
                        self._add_conditional_requirements(step, edge_data)
                    
                    steps.append(step)
            
            # If next node is an element, it's already in the path
            elif next_node.get("node_type") == "Element":
                step = self._create_step_from_element(next_page, next_node)
                
                # Find target page (should be at i+2)
                if i + 2 < len(path_nodes):
                    target_page = path_nodes[i + 2]
                    edge_data = self.graph.G.get_edge_data(next_page, target_page)
                    if edge_data:
                        self._add_conditional_requirements(step, edge_data)
                
                steps.append(step)
        
        return steps
    
    def _find_navigation_element(self, from_page: str, to_page: str) -> tuple[str, dict] | None:
        """Find the element that navigates from one page to another.
        
        Args:
            from_page: Starting page URL
            to_page: Destination page URL
            
        Returns:
            Tuple of (element_id, element_node) or None
        """
        # Look for elements on from_page that navigate to to_page
        for node_id in self.graph.G.nodes():
            node_data = self.graph.G.nodes[node_id]
            
            # Must be an element
            if node_data.get("node_type") != "Element":
                continue
            
            # Must be on the from_page
            if not self.graph.G.has_edge(node_id, from_page):
                continue
            
            edge_type = self.graph.G[node_id][from_page].get("edge_type")
            if edge_type != "ON_PAGE":
                continue
            
            # Must navigate to to_page
            if self.graph.G.has_edge(node_id, to_page):
                nav_edge_type = self.graph.G[node_id][to_page].get("edge_type")
                if nav_edge_type == "NAVIGATES_TO":
                    return (node_id, node_data)
        
        return None
    
    def _create_step_from_element(self, elem_id: str, elem_node: dict) -> dict[str, Any]:
        """Create a navigation step from an element node.
        
        Args:
            elem_id: Element node ID
            elem_node: Element node attributes
            
        Returns:
            Step dictionary
        """
        element_type = elem_node.get("element_type", "unknown")
        text = elem_node.get("text", "").strip()
        locator_type = elem_node.get("locator_type", "css")
        locator_value = elem_node.get("locator_value", "")
        
        # Check if this element opens a modal
        opens_modal = False
        modal_id = None
        for successor in self.graph.G.successors(elem_id):
            edge_data = self.graph.G[elem_id][successor]
            if edge_data.get("edge_type") == "OPENS_MODAL":
                opens_modal = True
                modal_id = successor
                break
        
        # Build step
        step = {
            "action": "open_modal" if opens_modal else "click",
            "element": text or elem_id,
            "locator": {
                "by": locator_type,
                "value": locator_value,
            }
        }
        
        if opens_modal and modal_id:
            modal_node = self.graph.G.nodes[modal_id]
            step["modal"] = modal_node.get("title", "unnamed_modal")
        
        return step
    
    def _add_conditional_requirements(self, step: dict, edge_data: dict) -> None:
        """Add conditional requirements to a navigation step.
        
        Args:
            step: Step dictionary to modify
            edge_data: Edge attributes from graph
        """
        if "requires_authentication" in edge_data:
            step["requires_authentication"] = edge_data["requires_authentication"]
        
        if "requires_role" in edge_data:
            step["requires_role"] = edge_data["requires_role"]
        
        if "requires_input" in edge_data:
            step["requires_input"] = edge_data["requires_input"]
        
        if "condition" in edge_data:
            step["condition"] = edge_data["condition"]
    
    def _resolve_page_url(self, page_ref: str) -> str | None:
        """Resolve a page reference to a full URL.
        
        Args:
            page_ref: Page reference (full URL or fragment like "#!/overview")
            
        Returns:
            Full page URL or None if not found
        """
        pages = self.graph.get_pages()
        
        # If it's already a full URL in the graph, return it
        if page_ref in pages:
            return page_ref
        
        # Try to match by fragment
        for page in pages:
            if page.endswith(page_ref) or page_ref in page:
                return page
        
        return None
    
    def _generate_path_name(self, from_page: str, to_page: str, variant: int = None) -> str:
        """Generate a descriptive name for a navigation path.
        
        Args:
            from_page: Starting page
            to_page: Destination page
            variant: Optional variant number for alternative paths
            
        Returns:
            Path name
        """
        from_name = self._sanitize_name(self._get_page_name(from_page))
        to_name = self._sanitize_name(self._get_page_name(to_page))
        
        if variant:
            return f"Path_{from_name}_to_{to_name}_v{variant}"
        return f"Path_{from_name}_to_{to_name}"
    
    def _get_page_name(self, page_url: str) -> str:
        """Extract a readable name from a page URL.
        
        Args:
            page_url: Full page URL
            
        Returns:
            Page name
        """
        parsed = urlparse(page_url)
        path = parsed.fragment if parsed.fragment else parsed.path
        
        if path.startswith("!"):
            path = path[1:]
        
        segments = [s for s in path.split("/") if s and "?" not in s]
        if segments:
            return "_".join(segments)
        
        return "home"
    
    def _get_page_fragment(self, page_url: str) -> str:
        """Extract the fragment from a page URL.
        
        Args:
            page_url: Full page URL
            
        Returns:
            Fragment (e.g., "#!/overview")
        """
        parsed = urlparse(page_url)
        if parsed.fragment:
            return f"#!/{parsed.fragment.lstrip('!/')}"
        return page_url
    
    def _find_home_page(self, pages: list[str]) -> str | None:
        """Find the home page from a list of pages.
        
        Args:
            pages: List of page URLs
            
        Returns:
            Home page URL or None
        """
        # Look for common home page patterns
        for page in pages:
            page_lower = page.lower()
            if "overview" in page_lower or "home" in page_lower or "index" in page_lower:
                return page
        
        # Fall back to first page
        return pages[0] if pages else None
    
    def _sanitize_name(self, name: str) -> str:
        """Convert a string into a valid YAML key.
        
        Args:
            name: Raw name string
            
        Returns:
            Sanitized name
        """
        name = re.sub(r"[^\w\s-]", "", name)
        name = re.sub(r"[\s-]+", "_", name)
        name = name.lower()
        name = name.strip("_")
        return name or "unnamed"
    
    def save_yaml(self, output_file: str, paths: dict[str, Any] = None) -> None:
        """Save navigation paths to a YAML file.
        
        Args:
            output_file: Path to output YAML file
            paths: Optional paths dictionary (uses generated paths if None)
        """
        output_path = Path(output_file)
        
        if paths is None:
            paths = self.navigation_paths
        
        if not paths:
            logger.warning("No navigation paths to save")
            return
        
        # Create output directory if needed
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write YAML with nice formatting
        with output_path.open("w") as f:
            # Add header comment
            f.write("# UI Navigation Paths\n")
            f.write("# Auto-generated from UI discovery graph\n")
            f.write("# \n")
            f.write("# Structure: path_name -> description, from, to, steps\n")
            f.write("# Each step has an action, element, and locator\n")
            f.write("#\n\n")
            
            yaml.dump(
                paths,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                width=120,
            )
        
        logger.info("Navigation paths saved to %s", output_path)


def main():
    """Command-line interface for navigation generator."""
    parser = argparse.ArgumentParser(
        description="Generate navigation.yaml from UI discovery graph"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input UI discovery JSON file (from ui_discovery.py)",
    )
    parser.add_argument(
        "--output",
        default="navigation.yaml",
        help="Output navigation YAML file (default: navigation.yaml)",
    )
    parser.add_argument(
        "--mode",
        choices=["common", "specific", "all"],
        default="common",
        help="Generation mode: common (auto-detect), specific (use --from/--to), all (find all paths)",
    )
    parser.add_argument(
        "--from-page",
        help="Starting page for specific mode (e.g., '#!/overview')",
    )
    parser.add_argument(
        "--to-page",
        help="Destination page for specific mode (e.g., '#!/admin/presets')",
    )
    parser.add_argument(
        "--max-paths",
        type=int,
        default=5,
        help="Maximum number of alternative paths to find in 'all' mode (default: 5)",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=10,
        help="Maximum path length in 'all' mode (default: 10)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Generate navigation paths
    logger.info("Starting navigation path generation...")
    generator = NavigationGenerator(args.input)
    
    if args.mode == "common":
        paths = generator.generate_common_paths()
    elif args.mode == "specific":
        if not args.from_page or not args.to_page:
            parser.error("--from-page and --to-page are required for specific mode")
        path = generator.generate_path(args.from_page, args.to_page)
        paths = {path["name"]: {
            "description": f"Navigate from {args.from_page} to {args.to_page}",
            "from": path["from"],
            "to": path["to"],
            "steps": path["steps"],
        }}
    elif args.mode == "all":
        if not args.from_page or not args.to_page:
            parser.error("--from-page and --to-page are required for all mode")
        all_paths = generator.generate_all_paths(
            args.from_page, 
            args.to_page,
            max_paths=args.max_paths,
            max_length=args.max_length
        )
        paths = {}
        for path in all_paths:
            paths[path["name"]] = {
                "description": f"Navigate from {args.from_page} to {args.to_page}",
                "from": path["from"],
                "to": path["to"],
                "steps": path["steps"],
            }
    
    generator.save_yaml(args.output, paths)
    
    logger.info("Navigation path generation complete!")
    logger.info("Generated %d paths", len(paths))


if __name__ == "__main__":
    main()

