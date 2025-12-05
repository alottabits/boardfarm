"""Unit tests for UIGraph class.

Tests cover all functionality of the NetworkX-based UI graph representation:
- Node operations (pages, modals, forms, elements)
- Edge operations (navigation, triggers, dependencies)
- Query operations (get nodes, find paths)
- Analysis operations (statistics, quality checks)
- Export operations (node-link, GraphML, GEXF)
"""

import json
import tempfile
from pathlib import Path

import networkx as nx
import pytest

from boardfarm3.lib.gui.ui_graph import UIGraph


class TestNodeOperations:
    """Test adding different types of nodes to the graph."""
    
    def test_add_page(self):
        """Test adding a page node."""
        graph = UIGraph()
        page_id = graph.add_page(
            "http://test.com/#!/page1",
            title="Page 1",
            page_type="home"
        )
        
        assert page_id == "http://test.com/#!/page1"
        assert graph.G.nodes[page_id]["node_type"] == "Page"
        assert graph.G.nodes[page_id]["title"] == "Page 1"
        assert graph.G.nodes[page_id]["page_type"] == "home"
    
    def test_add_page_with_extra_attributes(self):
        """Test adding a page with custom attributes."""
        graph = UIGraph()
        page_id = graph.add_page(
            "http://test.com/#!/page1",
            title="Page 1",
            page_type="home",
            timestamp="2024-12-05",
            screenshot_path="/tmp/screenshot.png"
        )
        
        assert graph.G.nodes[page_id]["timestamp"] == "2024-12-05"
        assert graph.G.nodes[page_id]["screenshot_path"] == "/tmp/screenshot.png"
    
    def test_add_modal(self):
        """Test adding a modal node."""
        graph = UIGraph()
        graph.add_page("http://test.com/#!/page1", title="Page 1")
        
        modal_id = graph.add_modal(
            "http://test.com/#!/page1",
            title="Add Item",
            modal_type="form_dialog"
        )
        
        assert modal_id == "modal_1"
        assert graph.G.nodes[modal_id]["node_type"] == "Modal"
        assert graph.G.nodes[modal_id]["title"] == "Add Item"
        assert graph.G.nodes[modal_id]["parent_page"] == "http://test.com/#!/page1"
        
        # Check OVERLAYS edge was created
        assert graph.G.has_edge(modal_id, "http://test.com/#!/page1")
        assert graph.G[modal_id]["http://test.com/#!/page1"]["edge_type"] == "OVERLAYS"
    
    def test_add_multiple_modals(self):
        """Test modal counter increments correctly."""
        graph = UIGraph()
        graph.add_page("http://test.com/#!/page1", title="Page 1")
        
        modal1_id = graph.add_modal("http://test.com/#!/page1", title="Modal 1")
        modal2_id = graph.add_modal("http://test.com/#!/page1", title="Modal 2")
        modal3_id = graph.add_modal("http://test.com/#!/page1", title="Modal 3")
        
        assert modal1_id == "modal_1"
        assert modal2_id == "modal_2"
        assert modal3_id == "modal_3"
    
    def test_add_form(self):
        """Test adding a form node."""
        graph = UIGraph()
        graph.add_page("http://test.com/#!/page1", title="Page 1")
        
        form_id = graph.add_form(
            "http://test.com/#!/page1",
            form_name="login_form",
            form_id="login-form"
        )
        
        assert form_id == "form_1"
        assert graph.G.nodes[form_id]["node_type"] == "Form"
        assert graph.G.nodes[form_id]["form_name"] == "login_form"
        
        # Check CONTAINED_IN edge was created
        assert graph.G.has_edge(form_id, "http://test.com/#!/page1")
        assert graph.G[form_id]["http://test.com/#!/page1"]["edge_type"] == "CONTAINED_IN"
    
    def test_add_element_to_page(self):
        """Test adding an element to a page."""
        graph = UIGraph()
        graph.add_page("http://test.com/#!/page1", title="Page 1")
        
        elem_id = graph.add_element(
            "http://test.com/#!/page1",
            "button",
            "css",
            "#btn-login",
            text="Login",
            visibility_observed="visible"
        )
        
        assert elem_id == "elem_button_1"
        assert graph.G.nodes[elem_id]["node_type"] == "Element"
        assert graph.G.nodes[elem_id]["element_type"] == "button"
        assert graph.G.nodes[elem_id]["locator_type"] == "css"
        assert graph.G.nodes[elem_id]["locator_value"] == "#btn-login"
        assert graph.G.nodes[elem_id]["text"] == "Login"
        assert graph.G.nodes[elem_id]["visibility_observed"] == "visible"
        
        # Check ON_PAGE edge was created
        assert graph.G.has_edge(elem_id, "http://test.com/#!/page1")
        assert graph.G[elem_id]["http://test.com/#!/page1"]["edge_type"] == "ON_PAGE"
    
    def test_add_element_to_modal(self):
        """Test adding an element to a modal."""
        graph = UIGraph()
        graph.add_page("http://test.com/#!/page1", title="Page 1")
        modal_id = graph.add_modal("http://test.com/#!/page1", title="Modal")
        
        elem_id = graph.add_element(
            modal_id,
            "input",
            "css",
            "#device-name",
            name="device_name"
        )
        
        # Check IN_MODAL edge was created
        assert graph.G.has_edge(elem_id, modal_id)
        assert graph.G[elem_id][modal_id]["edge_type"] == "IN_MODAL"
    
    def test_add_element_to_form(self):
        """Test adding an element to a form."""
        graph = UIGraph()
        graph.add_page("http://test.com/#!/page1", title="Page 1")
        form_id = graph.add_form("http://test.com/#!/page1", "login_form")
        
        elem_id = graph.add_element(
            form_id,
            "input",
            "css",
            "#username",
            name="username"
        )
        
        # Check IN_FORM edge was created
        assert graph.G.has_edge(elem_id, form_id)
        assert graph.G[elem_id][form_id]["edge_type"] == "IN_FORM"


class TestEdgeOperations:
    """Test adding different types of edges to the graph."""
    
    def test_add_navigation_link_basic(self):
        """Test adding a basic navigation link."""
        graph = UIGraph()
        graph.add_page("http://test.com/#!/page1", title="Page 1")
        graph.add_page("http://test.com/#!/page2", title="Page 2")
        
        graph.add_navigation_link(
            "http://test.com/#!/page1",
            "http://test.com/#!/page2"
        )
        
        # Check MAPS_TO edge was created
        assert graph.G.has_edge("http://test.com/#!/page1", "http://test.com/#!/page2")
        edge_data = graph.G["http://test.com/#!/page1"]["http://test.com/#!/page2"]
        assert edge_data["edge_type"] == "MAPS_TO"
    
    def test_add_navigation_link_with_element(self):
        """Test adding a navigation link via an element."""
        graph = UIGraph()
        page1 = graph.add_page("http://test.com/#!/page1", title="Page 1")
        page2 = graph.add_page("http://test.com/#!/page2", title="Page 2")
        elem_id = graph.add_element(page1, "link", "css", "a.nav", text="Go")
        
        graph.add_navigation_link(page1, page2, via_element=elem_id)
        
        # Check NAVIGATES_TO edge from element to page
        assert graph.G.has_edge(elem_id, page2)
        assert graph.G[elem_id][page2]["edge_type"] == "NAVIGATES_TO"
        
        # Check MAPS_TO edge from page to page
        assert graph.G.has_edge(page1, page2)
        assert graph.G[page1][page2]["edge_type"] == "MAPS_TO"
        assert graph.G[page1][page2]["via_element"] == elem_id
    
    def test_add_navigation_link_with_conditions(self):
        """Test adding a navigation link with conditional metadata."""
        graph = UIGraph()
        page1 = graph.add_page("http://test.com/#!/login", title="Login")
        page2 = graph.add_page("http://test.com/#!/dashboard", title="Dashboard")
        
        graph.add_navigation_link(
            page1,
            page2,
            requires_authentication=True,
            requires_input=["username", "password"],
            state_change="logs_in_user"
        )
        
        edge_data = graph.G[page1][page2]
        assert edge_data["requires_authentication"] is True
        assert edge_data["requires_input"] == ["username", "password"]
        assert edge_data["state_change"] == "logs_in_user"
    
    def test_add_modal_trigger(self):
        """Test adding a modal trigger edge."""
        graph = UIGraph()
        page = graph.add_page("http://test.com/#!/page1", title="Page 1")
        modal_id = graph.add_modal(page, title="Modal")
        elem_id = graph.add_element(page, "button", "css", "#btn-new", text="New")
        
        graph.add_modal_trigger(elem_id, modal_id, action="click")
        
        # Check OPENS_MODAL edge was created
        assert graph.G.has_edge(elem_id, modal_id)
        edge_data = graph.G[elem_id][modal_id]
        assert edge_data["edge_type"] == "OPENS_MODAL"
        assert edge_data["action"] == "click"
    
    def test_add_dependency(self):
        """Test adding a dependency edge between elements."""
        graph = UIGraph()
        page = graph.add_page("http://test.com/#!/login", title="Login")
        username = graph.add_element(page, "input", "css", "#username")
        password = graph.add_element(page, "input", "css", "#password")
        button = graph.add_element(page, "button", "css", "#btn-login")
        
        graph.add_dependency(button, username, condition="is_populated")
        graph.add_dependency(button, password, condition="is_populated")
        
        # Check REQUIRES edges were created
        assert graph.G.has_edge(button, username)
        assert graph.G[button][username]["edge_type"] == "REQUIRES"
        assert graph.G[button][username]["condition"] == "is_populated"


class TestQueryOperations:
    """Test querying nodes and paths in the graph."""
    
    def test_get_pages(self):
        """Test getting all page nodes."""
        graph = UIGraph()
        page1 = graph.add_page("http://test.com/#!/page1", title="Page 1")
        page2 = graph.add_page("http://test.com/#!/page2", title="Page 2")
        page3 = graph.add_page("http://test.com/#!/page3", title="Page 3")
        
        pages = graph.get_pages()
        assert len(pages) == 3
        assert page1 in pages
        assert page2 in pages
        assert page3 in pages
    
    def test_get_modals(self):
        """Test getting all modal nodes."""
        graph = UIGraph()
        page = graph.add_page("http://test.com/#!/page1", title="Page 1")
        modal1 = graph.add_modal(page, title="Modal 1")
        modal2 = graph.add_modal(page, title="Modal 2")
        
        modals = graph.get_modals()
        assert len(modals) == 2
        assert modal1 in modals
        assert modal2 in modals
    
    def test_get_forms(self):
        """Test getting all form nodes."""
        graph = UIGraph()
        page = graph.add_page("http://test.com/#!/page1", title="Page 1")
        form1 = graph.add_form(page, "form1")
        form2 = graph.add_form(page, "form2")
        
        forms = graph.get_forms()
        assert len(forms) == 2
        assert form1 in forms
        assert form2 in forms
    
    def test_get_container_elements(self):
        """Test getting all elements in a container."""
        graph = UIGraph()
        page = graph.add_page("http://test.com/#!/page1", title="Page 1")
        elem1 = graph.add_element(page, "button", "css", "#btn1", text="Button 1")
        elem2 = graph.add_element(page, "input", "css", "#input1")
        elem3 = graph.add_element(page, "link", "css", "a.nav", text="Link")
        
        elements = graph.get_container_elements(page)
        assert len(elements) == 3
        
        elem_ids = [elem_id for elem_id, _ in elements]
        assert elem1 in elem_ids
        assert elem2 in elem_ids
        assert elem3 in elem_ids
    
    def test_get_page_modals(self):
        """Test getting all modals on a page."""
        graph = UIGraph()
        page = graph.add_page("http://test.com/#!/page1", title="Page 1")
        modal1 = graph.add_modal(page, title="Modal 1")
        modal2 = graph.add_modal(page, title="Modal 2")
        
        modals = graph.get_page_modals(page)
        assert len(modals) == 2
        assert modal1 in modals
        assert modal2 in modals
    
    def test_find_shortest_path(self):
        """Test finding shortest path between pages."""
        graph = UIGraph()
        page1 = graph.add_page("http://test.com/#!/page1", title="Page 1")
        page2 = graph.add_page("http://test.com/#!/page2", title="Page 2")
        page3 = graph.add_page("http://test.com/#!/page3", title="Page 3")
        
        graph.add_navigation_link(page1, page2)
        graph.add_navigation_link(page2, page3)
        
        path = graph.find_shortest_path(page1, page3)
        assert len(path) == 3
        assert path[0] == page1
        assert path[-1] == page3
    
    def test_find_shortest_path_no_path(self):
        """Test finding path when no path exists."""
        graph = UIGraph()
        page1 = graph.add_page("http://test.com/#!/page1", title="Page 1")
        page2 = graph.add_page("http://test.com/#!/page2", title="Page 2")
        
        # No edge between pages
        path = graph.find_shortest_path(page1, page2)
        assert path == []
    
    def test_find_all_paths(self):
        """Test finding all paths between pages."""
        graph = UIGraph()
        page1 = graph.add_page("http://test.com/#!/page1", title="Page 1")
        page2 = graph.add_page("http://test.com/#!/page2", title="Page 2")
        page3 = graph.add_page("http://test.com/#!/page3", title="Page 3")
        page4 = graph.add_page("http://test.com/#!/page4", title="Page 4")
        
        # Create two paths: 1->2->4 and 1->3->4
        graph.add_navigation_link(page1, page2)
        graph.add_navigation_link(page1, page3)
        graph.add_navigation_link(page2, page4)
        graph.add_navigation_link(page3, page4)
        
        paths = graph.find_all_paths(page1, page4, max_length=5)
        assert len(paths) == 2


class TestAnalysisOperations:
    """Test graph analysis and quality checks."""
    
    def test_get_statistics(self):
        """Test getting comprehensive graph statistics."""
        graph = UIGraph()
        page = graph.add_page("http://test.com/#!/page1", title="Page 1")
        modal = graph.add_modal(page, title="Modal")
        form = graph.add_form(page, "form1")
        
        graph.add_element(page, "button", "css", "#btn1")
        graph.add_element(page, "input", "css", "#input1")
        graph.add_element(modal, "button", "css", "#btn-modal")
        
        stats = graph.get_statistics()
        
        assert stats["page_count"] == 1
        assert stats["modal_count"] == 1
        assert stats["form_count"] == 1
        assert stats["element_count"] == 3
        assert stats["total_nodes"] == 6  # 1 page + 1 modal + 1 form + 3 elements
        assert stats["avg_elements_per_page"] == 3.0
    
    def test_find_orphaned_elements(self):
        """Test finding elements not linked to any container."""
        graph = UIGraph()
        page = graph.add_page("http://test.com/#!/page1", title="Page 1")
        
        # Add normal element
        elem1 = graph.add_element(page, "button", "css", "#btn1")
        
        # Add orphaned element (manually, bypassing add_element)
        graph.G.add_node(
            "orphan_elem",
            node_type="Element",
            element_type="button"
        )
        
        orphans = graph.find_orphaned_elements()
        assert len(orphans) == 1
        assert "orphan_elem" in orphans
        assert elem1 not in orphans
    
    def test_find_dead_end_pages(self):
        """Test finding pages with no outgoing navigation."""
        graph = UIGraph()
        page1 = graph.add_page("http://test.com/#!/page1", title="Page 1")
        page2 = graph.add_page("http://test.com/#!/page2", title="Page 2")
        page3 = graph.add_page("http://test.com/#!/page3", title="Page 3")
        
        # page1 -> page2, but page3 has no outgoing links
        graph.add_navigation_link(page1, page2)
        
        dead_ends = graph.find_dead_end_pages()
        assert len(dead_ends) == 2
        assert page2 in dead_ends
        assert page3 in dead_ends
        assert page1 not in dead_ends
    
    def test_find_modals_without_triggers(self):
        """Test finding modals with no trigger element."""
        graph = UIGraph()
        page = graph.add_page("http://test.com/#!/page1", title="Page 1")
        modal1 = graph.add_modal(page, title="Modal 1")
        modal2 = graph.add_modal(page, title="Modal 2")
        
        # Add trigger for modal1
        elem = graph.add_element(page, "button", "css", "#btn")
        graph.add_modal_trigger(elem, modal1)
        
        # modal2 has no trigger
        orphan_modals = graph.find_modals_without_triggers()
        assert len(orphan_modals) == 1
        assert modal2 in orphan_modals
        assert modal1 not in orphan_modals
    
    def test_find_forms_without_submits(self):
        """Test finding forms with no submit button."""
        graph = UIGraph()
        page = graph.add_page("http://test.com/#!/page1", title="Page 1")
        form1 = graph.add_form(page, "form1")
        form2 = graph.add_form(page, "form2")
        
        # Add submit button to form1
        graph.add_element(form1, "button", "css", "#btn", 
                         text="Submit", button_type="submit")
        
        # Add non-submit button to form2
        graph.add_element(form2, "button", "css", "#btn2", text="Cancel")
        
        incomplete_forms = graph.find_forms_without_submits()
        assert len(incomplete_forms) == 1
        assert form2 in incomplete_forms
        assert form1 not in incomplete_forms


class TestExportOperations:
    """Test exporting graph to different formats."""
    
    def test_export_node_link(self):
        """Test exporting as node-link JSON format."""
        graph = UIGraph()
        page = graph.add_page("http://test.com/#!/page1", title="Page 1")
        elem = graph.add_element(page, "button", "css", "#btn", text="Click")
        
        data = graph.export_node_link()
        
        assert "directed" in data
        assert "nodes" in data
        assert "links" in data
        assert len(data["nodes"]) == 2
        assert len(data["links"]) == 1
    
    def test_export_and_import_node_link(self):
        """Test round-trip export and import."""
        # Create original graph
        graph1 = UIGraph()
        page1 = graph1.add_page("http://test.com/#!/page1", title="Page 1")
        page2 = graph1.add_page("http://test.com/#!/page2", title="Page 2")
        modal = graph1.add_modal(page1, title="Modal")
        elem1 = graph1.add_element(page1, "button", "css", "#btn1")
        elem2 = graph1.add_element(modal, "input", "css", "#input1")
        graph1.add_navigation_link(page1, page2, via_element=elem1)
        graph1.add_modal_trigger(elem1, modal)
        
        # Export
        data = graph1.export_node_link()
        
        # Import
        graph2 = UIGraph.from_node_link(data)
        
        # Verify structure is preserved
        assert graph2.get_pages() == graph1.get_pages()
        assert graph2.get_modals() == graph1.get_modals()
        assert len(graph2.get_container_elements(page1)) == 1
        assert len(graph2.get_container_elements(modal)) == 1
        
        # Verify edges are preserved
        assert graph2.G.has_edge(elem1, page2)
        assert graph2.G.has_edge(elem1, modal)
        assert graph2.G.has_edge(page1, page2)
    
    def test_export_graphml(self):
        """Test exporting as GraphML format."""
        graph = UIGraph()
        page = graph.add_page("http://test.com/#!/page1", title="Page 1")
        graph.add_element(page, "button", "css", "#btn")
        
        with tempfile.NamedTemporaryFile(suffix=".graphml", delete=False) as f:
            filepath = f.name
        
        try:
            graph.export_graphml(filepath)
            assert Path(filepath).exists()
            
            # Verify it's valid GraphML by trying to read it
            imported = nx.read_graphml(filepath)
            assert imported.number_of_nodes() == 2
        finally:
            Path(filepath).unlink()
    
    def test_export_gexf(self):
        """Test exporting as GEXF format."""
        graph = UIGraph()
        page = graph.add_page("http://test.com/#!/page1", title="Page 1")
        graph.add_element(page, "button", "css", "#btn")
        
        with tempfile.NamedTemporaryFile(suffix=".gexf", delete=False) as f:
            filepath = f.name
        
        try:
            graph.export_gexf(filepath)
            assert Path(filepath).exists()
            
            # Verify it's valid GEXF by trying to read it
            imported = nx.read_gexf(filepath)
            assert imported.number_of_nodes() == 2
        finally:
            Path(filepath).unlink()
    
    def test_counter_restoration_on_import(self):
        """Test that counters are restored when importing a graph."""
        # Create original graph with specific element IDs
        graph1 = UIGraph()
        page = graph1.add_page("http://test.com/#!/page1", title="Page 1")
        elem1 = graph1.add_element(page, "button", "css", "#btn1")
        elem2 = graph1.add_element(page, "input", "css", "#input1")
        modal1 = graph1.add_modal(page, "Modal 1")
        
        # Export and import
        data = graph1.export_node_link()
        graph2 = UIGraph.from_node_link(data)
        
        # Add new elements - they should have incremented counters
        elem3 = graph2.add_element(page, "link", "css", "a.nav")
        modal2 = graph2.add_modal(page, "Modal 2")
        
        # elem1="elem_button_1", elem2="elem_input_2", elem3 should be "elem_link_3"
        assert elem3 == "elem_link_3"
        # modal1="modal_1", modal2 should be "modal_2"
        assert modal2 == "modal_2"


class TestComplexScenarios:
    """Test complex, real-world scenarios."""
    
    def test_complete_login_flow(self):
        """Test modeling a complete login flow with all features."""
        graph = UIGraph()
        
        # Login page
        login_page = graph.add_page("http://test.com/#!/login", 
                                   title="Login", page_type="login")
        
        # Login form
        login_form = graph.add_form(login_page, "login_form")
        
        # Form elements
        username_input = graph.add_element(login_form, "input", "css", "#username",
                                          name="username", visibility_observed="visible")
        password_input = graph.add_element(login_form, "input", "css", "#password",
                                          name="password", visibility_observed="visible")
        login_button = graph.add_element(login_form, "button", "css", "#btn-login",
                                        text="Login", button_type="submit")
        
        # Dependencies
        graph.add_dependency(login_button, username_input, "is_populated")
        graph.add_dependency(login_button, password_input, "is_populated")
        
        # Dashboard page
        dashboard = graph.add_page("http://test.com/#!/dashboard",
                                  title="Dashboard", page_type="home")
        
        # Navigation with conditions
        graph.add_navigation_link(
            login_page,
            dashboard,
            via_element=login_button,
            requires_authentication=True,
            requires_input=["username", "password"],
            state_change="logs_in_user"
        )
        
        # Verify structure
        assert len(graph.get_pages()) == 2
        assert len(graph.get_forms()) == 1
        elements = graph.get_container_elements(login_form)
        assert len(elements) == 3
        
        # Verify navigation exists
        path = graph.find_shortest_path(login_page, dashboard)
        assert len(path) > 0
        
        # Verify dependencies
        assert graph.G.has_edge(login_button, username_input)
        assert graph.G.has_edge(login_button, password_input)
    
    def test_modal_workflow(self):
        """Test modeling a page with modal and trigger."""
        graph = UIGraph()
        
        # Device list page
        devices_page = graph.add_page("http://test.com/#!/devices",
                                     title="Devices", page_type="device_list")
        
        # "New" button that opens modal
        new_button = graph.add_element(devices_page, "button", "css", "#btn-new",
                                      text="New", visibility_observed="visible")
        
        # Add device modal
        add_modal = graph.add_modal(devices_page, title="Add Device",
                                   modal_type="form_dialog")
        
        # Trigger relationship
        graph.add_modal_trigger(new_button, add_modal, action="click")
        
        # Modal form
        modal_form = graph.add_form(add_modal, "add_device_form")
        
        # Form elements
        name_input = graph.add_element(modal_form, "input", "css", "#device-name",
                                      name="name", visibility_observed="visible")
        submit_button = graph.add_element(modal_form, "button", "css", "#btn-submit",
                                         text="Submit", button_type="submit")
        
        # Verify structure
        modals = graph.get_page_modals(devices_page)
        assert len(modals) == 1
        assert add_modal in modals
        
        # Verify trigger
        assert graph.G.has_edge(new_button, add_modal)
        assert graph.G[new_button][add_modal]["edge_type"] == "OPENS_MODAL"
        
        # Verify modal elements
        modal_elements = graph.get_container_elements(add_modal)
        # Should only have the form, not the form's elements
        assert len(modal_elements) == 0
        
        form_elements = graph.get_container_elements(modal_form)
        assert len(form_elements) == 2

