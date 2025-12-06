"""NetworkX-based graph representation of UI structure.

This module provides a graph-native representation of the Page Object Model (POM),
where pages, modals, forms, and elements are nodes, and their relationships
(containment, navigation, dependencies) are edges.

The graph can be exported to multiple formats (JSON, GraphML, GEXF) and enables
powerful analysis through NetworkX algorithms.
"""

from __future__ import annotations

from typing import Any

import networkx as nx


class UIGraph:
    """NetworkX-based graph representation of UI structure.
    
    This class provides a domain-specific wrapper around NetworkX DiGraph for
    modeling web UI structure. It supports:
    - Multiple node types: Page, Modal, Form, Element
    - Multiple edge types: ON_PAGE, IN_MODAL, NAVIGATES_TO, OPENS_MODAL, etc.
    - Conditional navigation metadata (auth requirements, inputs, state changes)
    - Element visibility tracking
    - Graph analysis (orphans, dead-ends, cycles)
    - Multiple export formats (JSON, GraphML, GEXF)
    
    Example:
        >>> graph = UIGraph()
        >>> graph.add_page("http://localhost/#!/login", title="Login")
        >>> modal_id = graph.add_modal("http://localhost/#!/devices", title="Add Device")
        >>> elem_id = graph.add_element(modal_id, "input", "css", "#device-name")
        >>> graph.export_node_link()
    
    Attributes:
        G: The underlying NetworkX directed graph
        _element_counter: Counter for generating unique element IDs
        _modal_counter: Counter for generating unique modal IDs
        _form_counter: Counter for generating unique form IDs
    """
    
    def __init__(self):
        """Initialize an empty directed graph for UI structure."""
        self.G = nx.DiGraph()
        self._element_counter = 0
        self._modal_counter = 0
        self._form_counter = 0
    
    # ========== Node Operations ==========
    
    def add_page(self, url: str, title: str = "", page_type: str = "unknown", 
                 **attrs) -> str:
        """Add a page node to the graph.
        
        Pages represent full page navigations in the UI. The URL is used as
        the node ID for easy reference.
        
        Args:
            url: Page URL (used as node ID)
            title: Page title
            page_type: Classification (login, home, device_details, etc.)
            **attrs: Additional attributes (timestamp, screenshot_path, etc.)
            
        Returns:
            Node ID (the URL itself)
            
        Example:
            >>> graph.add_page(
            ...     "http://localhost/#!/devices",
            ...     title="Devices - GenieACS",
            ...     page_type="device_list"
            ... )
            'http://localhost/#!/devices'
        """
        self.G.add_node(
            url,
            node_type="Page",
            title=title,
            page_type=page_type,
            **attrs
        )
        return url
    
    def add_modal(self, parent_page: str, title: str = "", **attrs) -> str:
        """Add a modal/dialog node to the graph.
        
        Modals are overlay containers (dialogs, popups) that appear on top of pages.
        They are first-class nodes with their own elements.
        
        Args:
            parent_page: URL of the page this modal appears on
            title: Modal title
            **attrs: Additional attributes (modal_type, modal_id, etc.)
            
        Returns:
            Modal node ID (e.g., "modal_1")
            
        Example:
            >>> modal_id = graph.add_modal(
            ...     "http://localhost/#!/devices",
            ...     title="Add Device",
            ...     modal_type="form_dialog"
            ... )
            >>> print(modal_id)
            'modal_1'
        """
        self._modal_counter += 1
        modal_id = f"modal_{self._modal_counter}"
        
        self.G.add_node(
            modal_id,
            node_type="Modal",
            title=title,
            parent_page=parent_page,
            **attrs
        )
        
        # Link modal to parent page
        self.G.add_edge(modal_id, parent_page, edge_type="OVERLAYS")
        
        return modal_id
    
    def add_form(self, container_id: str, form_name: str = "", **attrs) -> str:
        """Add a form node to the graph.
        
        Forms are logical groupings of input elements. They can exist on pages
        or within modals. Forms help organize related inputs and identify
        submission actions.
        
        Args:
            container_id: ID of container (page URL or modal ID)
            form_name: Descriptive name for the form
            **attrs: Additional attributes (form_id, action, method, etc.)
            
        Returns:
            Form node ID (e.g., "form_1")
            
        Example:
            >>> form_id = graph.add_form(
            ...     "http://localhost/#!/login",
            ...     form_name="login_form",
            ...     form_id="login-form"
            ... )
            >>> print(form_id)
            'form_1'
        """
        self._form_counter += 1
        form_id = f"form_{self._form_counter}"
        
        self.G.add_node(
            form_id,
            node_type="Form",
            form_name=form_name,
            container_id=container_id,
            **attrs
        )
        
        # Link form to container
        self.G.add_edge(form_id, container_id, edge_type="CONTAINED_IN")
        
        return form_id
    
    def add_element(self, container_id: str, element_type: str, 
                   locator_type: str, locator_value: str,
                   **attrs) -> str:
        """Add an element node to the graph.
        
        Elements are interactive UI components (buttons, inputs, links, etc.).
        They can be contained in pages, modals, or forms.
        
        Args:
            container_id: ID of container (page URL, modal ID, or form ID)
            element_type: Type of element (button, input, link, select, etc.)
            locator_type: Locator strategy (id, css, xpath, name)
            locator_value: Locator value
            **attrs: Additional attributes (text, name, href, visibility_observed, etc.)
            
        Returns:
            Element node ID (e.g., "elem_button_123")
            
        Example:
            >>> elem_id = graph.add_element(
            ...     "http://localhost/#!/login",
            ...     "button",
            ...     "css",
            ...     "#btn-login",
            ...     text="Login",
            ...     visibility_observed="visible"
            ... )
            >>> print(elem_id)
            'elem_button_1'
        """
        self._element_counter += 1
        element_id = f"elem_{element_type}_{self._element_counter}"
        
        self.G.add_node(
            element_id,
            node_type="Element",
            element_type=element_type,
            locator_type=locator_type,
            locator_value=locator_value,
            **attrs
        )
        
        # Determine edge type based on container type
        if container_id.startswith("modal_"):
            edge_type = "IN_MODAL"
        elif container_id.startswith("form_"):
            edge_type = "IN_FORM"
        else:
            edge_type = "ON_PAGE"
        
        self.G.add_edge(element_id, container_id, edge_type=edge_type)
        
        return element_id
    
    # ========== Edge Operations ==========
    
    def add_navigation_link(self, from_page: str, to_page: str, 
                          via_element: str | None = None, **attrs):
        """Add navigation relationship between pages.
        
        Creates edges representing navigation from one page to another. Supports
        conditional navigation metadata (authentication requirements, required
        inputs, state changes).
        
        Args:
            from_page: Source page URL
            to_page: Target page URL
            via_element: Optional element ID that triggers navigation
            **attrs: Navigation metadata:
                - requires_authentication: bool
                - requires_role: str (e.g., "admin")
                - requires_input: list[str] (e.g., ["username", "password"])
                - state_change: str (e.g., "logs_in_user")
                - condition: str (free-form condition description)
                - action: str (e.g., "click", "submit")
                - query_params: dict[str, str] | None (e.g., {"filter": "value", "tab": "devices"})
                  Query parameters from the original link, preserved for accurate navigation
        
        Example:
            >>> graph.add_navigation_link(
            ...     "http://localhost/#!/login",
            ...     "http://localhost/#!/dashboard",
            ...     via_element="elem_button_1",
            ...     requires_authentication=True,
            ...     requires_input=["username", "password"],
            ...     state_change="logs_in_user"
            ... )
            
            >>> # Navigation with query parameters
            >>> graph.add_navigation_link(
            ...     "http://localhost/#!/devices",
            ...     "http://localhost/#!/devices",
            ...     via_element="elem_link_5",
            ...     action="click",
            ...     query_params={"filter": "Events.Inform > NOW()", "sort": "desc"}
            ... )
        """
        # If a specific element triggers navigation, create that edge
        if via_element:
            self.G.add_edge(
                via_element, 
                to_page, 
                edge_type="NAVIGATES_TO",
                **attrs
            )
        
        # Always create page-to-page edge for analysis
        self.G.add_edge(
            from_page,
            to_page,
            edge_type="MAPS_TO",
            via_element=via_element,
            **attrs
        )
    
    def add_modal_trigger(self, trigger_element: str, modal_id: str, **attrs):
        """Add relationship showing element opens a modal.
        
        Args:
            trigger_element: Element ID that opens the modal
            modal_id: Modal ID
            **attrs: Additional attributes (action="click", etc.)
            
        Example:
            >>> graph.add_modal_trigger(
            ...     "elem_button_5",
            ...     "modal_1",
            ...     action="click"
            ... )
        """
        self.G.add_edge(
            trigger_element,
            modal_id,
            edge_type="OPENS_MODAL",
            **attrs
        )
    
    def add_dependency(self, dependent_elem: str, required_elem: str, 
                      condition: str = "is_populated"):
        """Add dependency relationship between elements.
        
        Represents that one element depends on another (e.g., submit button
        requires username field to be populated).
        
        Args:
            dependent_elem: Element that depends
            required_elem: Element it requires
            condition: Dependency condition (e.g., "is_populated", "is_checked")
            
        Example:
            >>> graph.add_dependency(
            ...     "elem_button_login",
            ...     "elem_input_username",
            ...     condition="is_populated"
            ... )
        """
        self.G.add_edge(
            dependent_elem,
            required_elem,
            edge_type="REQUIRES",
            condition=condition
        )
    
    # ========== Query Operations ==========
    
    def get_pages(self) -> list[str]:
        """Get all page node IDs.
        
        Returns:
            List of page URLs
            
        Example:
            >>> pages = graph.get_pages()
            >>> print(len(pages))
            12
        """
        return [n for n, d in self.G.nodes(data=True) 
                if d.get('node_type') == 'Page']
    
    def get_modals(self) -> list[str]:
        """Get all modal node IDs.
        
        Returns:
            List of modal IDs
            
        Example:
            >>> modals = graph.get_modals()
            >>> print(modals)
            ['modal_1', 'modal_2', 'modal_3']
        """
        return [n for n, d in self.G.nodes(data=True) 
                if d.get('node_type') == 'Modal']
    
    def get_forms(self) -> list[str]:
        """Get all form node IDs.
        
        Returns:
            List of form IDs
            
        Example:
            >>> forms = graph.get_forms()
            >>> print(forms)
            ['form_1', 'form_2']
        """
        return [n for n, d in self.G.nodes(data=True) 
                if d.get('node_type') == 'Form']
    
    def get_container_elements(self, container_id: str) -> list[tuple[str, dict]]:
        """Get all elements in a container (page, modal, or form).
        
        Args:
            container_id: Page URL, modal ID, or form ID
            
        Returns:
            List of (element_id, attributes) tuples
            
        Example:
            >>> elements = graph.get_container_elements("http://localhost/#!/login")
            >>> for elem_id, attrs in elements:
            ...     print(f"{attrs['element_type']}: {attrs.get('text', '')}")
            input: 
            input: 
            button: Login
        """
        elements = []
        for elem_id in self.G.nodes():
            if self.G.has_edge(elem_id, container_id):
                edge_data = self.G[elem_id][container_id]
                if edge_data.get('edge_type') in ['ON_PAGE', 'IN_MODAL', 'IN_FORM']:
                    elements.append((elem_id, self.G.nodes[elem_id]))
        return elements
    
    def get_page_modals(self, page_url: str) -> list[str]:
        """Get all modals that overlay a specific page.
        
        Args:
            page_url: Page URL
            
        Returns:
            List of modal IDs
            
        Example:
            >>> modals = graph.get_page_modals("http://localhost/#!/devices")
            >>> print(modals)
            ['modal_1', 'modal_2']
        """
        modals = []
        for modal_id in self.get_modals():
            if self.G.has_edge(modal_id, page_url):
                edge_data = self.G[modal_id][page_url]
                if edge_data.get('edge_type') == 'OVERLAYS':
                    modals.append(modal_id)
        return modals
    
    def find_shortest_path(self, from_page: str, to_page: str) -> list:
        """Find shortest navigation path between pages.
        
        Uses NetworkX BFS to find the shortest path. Returns empty list if
        no path exists.
        
        Args:
            from_page: Start page URL
            to_page: End page URL
            
        Returns:
            List of node IDs in path, or empty list if no path exists
            
        Example:
            >>> path = graph.find_shortest_path(
            ...     "http://localhost/#!/login",
            ...     "http://localhost/#!/devices"
            ... )
            >>> print(path)
            ['http://localhost/#!/login', 'elem_button_1', 'http://localhost/#!/dashboard', 
             'elem_link_2', 'http://localhost/#!/devices']
        """
        try:
            return nx.shortest_path(self.G, from_page, to_page)
        except nx.NetworkXNoPath:
            return []
        except nx.NodeNotFound:
            return []
    
    def find_all_paths(self, from_page: str, to_page: str, 
                      max_length: int = 10) -> list[list]:
        """Find all navigation paths between pages.
        
        Uses NetworkX to find all simple paths (no repeated nodes). Use cutoff
        to limit path length for performance.
        
        Args:
            from_page: Start page URL
            to_page: End page URL
            max_length: Maximum path length (default: 10)
            
        Returns:
            List of paths (each path is a list of node IDs)
            
        Example:
            >>> paths = graph.find_all_paths(
            ...     "http://localhost/#!/login",
            ...     "http://localhost/#!/admin",
            ...     max_length=5
            ... )
            >>> print(f"Found {len(paths)} different paths")
            Found 3 different paths
        """
        try:
            return list(nx.all_simple_paths(
                self.G, from_page, to_page, cutoff=max_length
            ))
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []
    
    # ========== Analysis Operations ==========
    
    def get_statistics(self) -> dict[str, Any]:
        """Get comprehensive graph statistics.
        
        Returns:
            Dictionary with statistics including:
            - total_nodes, total_edges
            - page_count, modal_count, form_count, element_count
            - avg_elements_per_page
            - orphaned_elements, dead_end_pages
            - modals_without_triggers, forms_without_submits
            - is_weakly_connected
            
        Example:
            >>> stats = graph.get_statistics()
            >>> print(f"Pages: {stats['page_count']}, Modals: {stats['modal_count']}")
            Pages: 12, Modals: 8
        """
        pages = self.get_pages()
        modals = self.get_modals()
        forms = self.get_forms()
        elements = [n for n, d in self.G.nodes(data=True) 
                   if d.get('node_type') == 'Element']
        
        # Find orphaned elements (not connected to any container)
        orphaned = self.find_orphaned_elements()
        
        # Find dead-end pages (no outgoing navigation)
        dead_ends = self.find_dead_end_pages()
        
        # Find modals without triggers
        modals_no_trigger = self.find_modals_without_triggers()
        
        # Find forms without submit buttons
        forms_no_submit = self.find_forms_without_submits()
        
        return {
            "total_nodes": self.G.number_of_nodes(),
            "total_edges": self.G.number_of_edges(),
            "page_count": len(pages),
            "modal_count": len(modals),
            "form_count": len(forms),
            "element_count": len(elements),
            "avg_elements_per_page": len(elements) / len(pages) if pages else 0,
            "orphaned_elements": len(orphaned),
            "dead_end_pages": len(dead_ends),
            "modals_without_triggers": len(modals_no_trigger),
            "forms_without_submits": len(forms_no_submit),
            "is_weakly_connected": nx.is_weakly_connected(self.G) if self.G.number_of_nodes() > 0 else False,
        }
    
    def find_orphaned_elements(self) -> list[str]:
        """Find elements not linked to any container.
        
        Returns:
            List of orphaned element IDs
            
        Example:
            >>> orphans = graph.find_orphaned_elements()
            >>> if orphans:
            ...     print(f"WARNING: {len(orphans)} orphaned elements found")
        """
        orphaned = []
        for node_id, data in self.G.nodes(data=True):
            if data.get('node_type') != 'Element':
                continue
            
            # Check if element has a container edge
            has_container = False
            for _, target, edge_data in self.G.out_edges(node_id, data=True):
                if edge_data.get('edge_type') in ['ON_PAGE', 'IN_MODAL', 'IN_FORM']:
                    has_container = True
                    break
            
            if not has_container:
                orphaned.append(node_id)
        
        return orphaned
    
    def find_dead_end_pages(self) -> list[str]:
        """Find pages with no outgoing navigation.
        
        Returns:
            List of dead-end page URLs
            
        Example:
            >>> dead_ends = graph.find_dead_end_pages()
            >>> print(f"Dead-end pages: {dead_ends}")
        """
        dead_ends = []
        pages = self.get_pages()
        
        for page in pages:
            # Check if page has any MAPS_TO edges
            has_navigation = False
            for _, target, edge_data in self.G.out_edges(page, data=True):
                if edge_data.get('edge_type') == 'MAPS_TO':
                    has_navigation = True
                    break
            
            if not has_navigation:
                dead_ends.append(page)
        
        return dead_ends
    
    def find_modals_without_triggers(self) -> list[str]:
        """Find modals that have no element that opens them.
        
        Returns:
            List of modal IDs without triggers
            
        Example:
            >>> orphan_modals = graph.find_modals_without_triggers()
            >>> if orphan_modals:
            ...     print(f"WARNING: {len(orphan_modals)} modals have no triggers")
        """
        modals_no_trigger = []
        modals = self.get_modals()
        
        for modal_id in modals:
            # Check if any element has OPENS_MODAL edge to this modal
            has_trigger = False
            for source, target, edge_data in self.G.in_edges(modal_id, data=True):
                if edge_data.get('edge_type') == 'OPENS_MODAL':
                    has_trigger = True
                    break
            
            if not has_trigger:
                modals_no_trigger.append(modal_id)
        
        return modals_no_trigger
    
    def find_forms_without_submits(self) -> list[str]:
        """Find forms that have no submit button.
        
        Returns:
            List of form IDs without submit buttons
            
        Example:
            >>> incomplete_forms = graph.find_forms_without_submits()
            >>> if incomplete_forms:
            ...     print(f"WARNING: {len(incomplete_forms)} forms have no submit button")
        """
        forms_no_submit = []
        forms = self.get_forms()
        
        for form_id in forms:
            # Get all elements in this form
            elements = self.get_container_elements(form_id)
            
            # Check if any is a submit button
            has_submit = False
            for elem_id, elem_data in elements:
                if elem_data.get('element_type') == 'button':
                    button_type = elem_data.get('button_type', '')
                    text = elem_data.get('text', '').lower()
                    if button_type == 'submit' or 'submit' in text or 'login' in text:
                        has_submit = True
                        break
            
            if not has_submit:
                forms_no_submit.append(form_id)
        
        return forms_no_submit
    
    # ========== Export Operations ==========
    
    def export_node_link(self) -> dict[str, Any]:
        """Export graph as NetworkX node-link format (JSON-compatible).
        
        This is the primary interchange format. Other tools can reconstruct
        the exact graph using nx.node_link_graph().
        
        Returns:
            Dictionary in node-link format with:
            - directed: bool
            - multigraph: bool
            - nodes: list of node dicts with id and attributes
            - links: list of edge dicts with source, target, and attributes
            
        Example:
            >>> data = graph.export_node_link()
            >>> # Save to file
            >>> import json
            >>> with open("ui_map.json", "w") as f:
            ...     json.dump({"graph": data, "statistics": graph.get_statistics()}, f)
            >>> 
            >>> # Later, in another tool:
            >>> with open("ui_map.json") as f:
            ...     data = json.load(f)
            >>> G = nx.node_link_graph(data["graph"])
        """
        return nx.node_link_data(self.G, edges="edges")
    
    def export_graphml(self, filepath: str):
        """Export graph as GraphML format for visualization tools.
        
        GraphML is supported by yEd, Cytoscape, and other graph visualization
        tools. Open the file in these tools to visualize the UI structure.
        
        Args:
            filepath: Output file path (e.g., "ui_graph.graphml")
            
        Example:
            >>> graph.export_graphml("ui_map.graphml")
            >>> # Open in yEd: File → Open → ui_map.graphml
        """
        nx.write_graphml(self.G, filepath)
    
    def export_gexf(self, filepath: str):
        """Export graph as GEXF format for Gephi visualization.
        
        GEXF is the native format for Gephi, a popular graph visualization tool.
        
        Args:
            filepath: Output file path (e.g., "ui_graph.gexf")
            
        Example:
            >>> graph.export_gexf("ui_map.gexf")
            >>> # Open in Gephi: File → Open → ui_map.gexf
        """
        nx.write_gexf(self.G, filepath)
    
    @classmethod
    def from_node_link(cls, data: dict[str, Any]) -> "UIGraph":
        """Create UIGraph from node-link format data.
        
        This is the inverse of export_node_link(). Allows other tools to
        reconstruct the graph.
        
        Args:
            data: Dictionary in node-link format
            
        Returns:
            New UIGraph instance with reconstructed graph
            
        Example:
            >>> import json
            >>> with open("ui_map.json") as f:
            ...     data = json.load(f)
            >>> graph = UIGraph.from_node_link(data["graph"])
            >>> pages = graph.get_pages()
        """
        instance = cls()
        instance.G = nx.node_link_graph(data, edges="edges")
        
        # Restore counters based on existing IDs
        for node_id in instance.G.nodes():
            if node_id.startswith("elem_"):
                # Extract counter from elem_type_123
                parts = node_id.split("_")
                if len(parts) >= 3 and parts[-1].isdigit():
                    counter = int(parts[-1])
                    instance._element_counter = max(instance._element_counter, counter)
            elif node_id.startswith("modal_"):
                parts = node_id.split("_")
                if len(parts) >= 2 and parts[-1].isdigit():
                    counter = int(parts[-1])
                    instance._modal_counter = max(instance._modal_counter, counter)
            elif node_id.startswith("form_"):
                parts = node_id.split("_")
                if len(parts) >= 2 and parts[-1].isdigit():
                    counter = int(parts[-1])
                    instance._form_counter = max(instance._form_counter, counter)
        
        return instance

