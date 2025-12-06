"""Unit tests for query parameter capture on navigation edges.

This module tests that query parameters from links are correctly captured
and attached as edge properties in the UI graph, enabling accurate navigation
with filters and parameters.
"""

import pytest
from boardfarm3.lib.gui.ui_graph import UIGraph


class TestQueryParameterEdges:
    """Test query parameter capture on navigation edges."""
    
    def test_query_params_captured_on_navigates_to_edges(self):
        """Verify query params are attached to NAVIGATES_TO edges."""
        graph = UIGraph()
        
        # Add pages
        graph.add_page("http://localhost/#!/devices", title="Devices")
        
        # Add link element
        elem_id = graph.add_element(
            "http://localhost/#!/devices",
            "link",
            "css",
            "#filter-link",
            text="Filtered View"
        )
        
        # Add navigation with query params
        query_params = {"filter": "Events.Inform > NOW()", "sort": "desc"}
        graph.add_navigation_link(
            from_page="http://localhost/#!/devices",
            to_page="http://localhost/#!/devices",
            via_element=elem_id,
            action="click",
            query_params=query_params
        )
        
        # Verify NAVIGATES_TO edge has query_params
        edge_data = graph.G[elem_id]["http://localhost/#!/devices"]
        assert edge_data["edge_type"] == "NAVIGATES_TO"
        assert "query_params" in edge_data
        assert edge_data["query_params"] == query_params
        assert edge_data["query_params"]["filter"] == "Events.Inform > NOW()"
        assert edge_data["query_params"]["sort"] == "desc"
    
    def test_query_params_captured_on_maps_to_edges(self):
        """Verify query params are attached to MAPS_TO edges."""
        graph = UIGraph()
        
        # Add pages
        graph.add_page("http://localhost/#!/devices", title="Devices")
        
        # Add link element
        elem_id = graph.add_element(
            "http://localhost/#!/devices",
            "link",
            "css",
            "#filter-link",
            text="Filtered View"
        )
        
        # Add navigation with query params
        query_params = {"tab": "overview", "view": "compact"}
        graph.add_navigation_link(
            from_page="http://localhost/#!/devices",
            to_page="http://localhost/#!/devices",
            via_element=elem_id,
            query_params=query_params
        )
        
        # Verify MAPS_TO edge has query_params
        edge_data = graph.G["http://localhost/#!/devices"]["http://localhost/#!/devices"]
        assert edge_data["edge_type"] == "MAPS_TO"
        assert "query_params" in edge_data
        assert edge_data["query_params"] == query_params
    
    def test_empty_query_params_not_added(self):
        """Verify None is used when no query params exist."""
        graph = UIGraph()
        
        # Add pages
        graph.add_page("http://localhost/#!/devices", title="Devices")
        graph.add_page("http://localhost/#!/admin", title="Admin")
        
        # Add link element
        elem_id = graph.add_element(
            "http://localhost/#!/devices",
            "link",
            "css",
            "#admin-link",
            text="Admin"
        )
        
        # Add navigation without query params
        graph.add_navigation_link(
            from_page="http://localhost/#!/devices",
            to_page="http://localhost/#!/admin",
            via_element=elem_id,
            action="click",
            query_params=None
        )
        
        # Verify edge has query_params as None
        edge_data = graph.G[elem_id]["http://localhost/#!/admin"]
        assert edge_data["edge_type"] == "NAVIGATES_TO"
        # query_params should be None or not present
        assert edge_data.get("query_params") is None
    
    def test_fragment_query_params_captured(self):
        """Verify SPA fragment query params are captured (e.g., #!/devices?filter=X)."""
        graph = UIGraph()
        
        # Add page
        graph.add_page("http://localhost/#!/devices", title="Devices")
        
        # Add link element
        elem_id = graph.add_element(
            "http://localhost/#!/devices",
            "link",
            "css",
            "#filter-link",
            text="Recent Events"
        )
        
        # Add navigation with fragment query params
        query_params = {"filter": "Events.Inform > NOW()"}
        graph.add_navigation_link(
            from_page="http://localhost/#!/devices",
            to_page="http://localhost/#!/devices",
            via_element=elem_id,
            query_params=query_params
        )
        
        # Verify edge has query_params
        edge_data = graph.G[elem_id]["http://localhost/#!/devices"]
        assert "query_params" in edge_data
        assert edge_data["query_params"]["filter"] == "Events.Inform > NOW()"
    
    def test_standard_query_params_captured(self):
        """Verify standard URL query params are captured (e.g., /devices?filter=X)."""
        graph = UIGraph()
        
        # Add page
        graph.add_page("http://localhost/devices", title="Devices")
        
        # Add link element
        elem_id = graph.add_element(
            "http://localhost/devices",
            "link",
            "css",
            "#filter-link",
            text="Active Devices"
        )
        
        # Add navigation with standard query params
        query_params = {"status": "active", "limit": "50"}
        graph.add_navigation_link(
            from_page="http://localhost/devices",
            to_page="http://localhost/devices",
            via_element=elem_id,
            query_params=query_params
        )
        
        # Verify edge has query_params
        edge_data = graph.G[elem_id]["http://localhost/devices"]
        assert "query_params" in edge_data
        assert edge_data["query_params"]["status"] == "active"
        assert edge_data["query_params"]["limit"] == "50"
    
    def test_multiple_query_params(self):
        """Verify multiple query params are captured correctly."""
        graph = UIGraph()
        
        # Add page
        graph.add_page("http://localhost/#!/devices", title="Devices")
        
        # Add link element
        elem_id = graph.add_element(
            "http://localhost/#!/devices",
            "link",
            "css",
            "#complex-filter",
            text="Complex Filter"
        )
        
        # Add navigation with multiple query params
        query_params = {
            "filter": "Events.Inform > NOW()",
            "sort": "desc",
            "limit": "100",
            "offset": "0",
            "view": "detailed"
        }
        graph.add_navigation_link(
            from_page="http://localhost/#!/devices",
            to_page="http://localhost/#!/devices",
            via_element=elem_id,
            query_params=query_params
        )
        
        # Verify all query params are present
        edge_data = graph.G[elem_id]["http://localhost/#!/devices"]
        assert "query_params" in edge_data
        assert len(edge_data["query_params"]) == 5
        assert edge_data["query_params"]["filter"] == "Events.Inform > NOW()"
        assert edge_data["query_params"]["sort"] == "desc"
        assert edge_data["query_params"]["limit"] == "100"
        assert edge_data["query_params"]["offset"] == "0"
        assert edge_data["query_params"]["view"] == "detailed"
    
    def test_query_params_preserved_in_export(self):
        """Verify query params are preserved in graph export."""
        graph = UIGraph()
        
        # Add page and element
        graph.add_page("http://localhost/#!/devices", title="Devices")
        elem_id = graph.add_element(
            "http://localhost/#!/devices",
            "link",
            "css",
            "#filter-link",
            text="Filtered"
        )
        
        # Add navigation with query params
        query_params = {"filter": "test", "sort": "asc"}
        graph.add_navigation_link(
            from_page="http://localhost/#!/devices",
            to_page="http://localhost/#!/devices",
            via_element=elem_id,
            query_params=query_params
        )
        
        # Export and verify
        exported = graph.export_node_link()
        
        # Find the edge in exported data
        navigates_to_edge = None
        for link in exported["edges"]:
            if (link["source"] == elem_id and 
                link["target"] == "http://localhost/#!/devices" and
                link.get("edge_type") == "NAVIGATES_TO"):
                navigates_to_edge = link
                break
        
        assert navigates_to_edge is not None
        assert "query_params" in navigates_to_edge
        assert navigates_to_edge["query_params"] == query_params
    
    def test_query_params_preserved_in_round_trip(self):
        """Verify query params survive export/import round trip."""
        graph = UIGraph()
        
        # Build graph with query params
        graph.add_page("http://localhost/#!/devices", title="Devices")
        elem_id = graph.add_element(
            "http://localhost/#!/devices",
            "link",
            "css",
            "#filter-link",
            text="Filtered"
        )
        
        query_params = {"filter": "Events.Inform > NOW()", "sort": "desc"}
        graph.add_navigation_link(
            from_page="http://localhost/#!/devices",
            to_page="http://localhost/#!/devices",
            via_element=elem_id,
            query_params=query_params
        )
        
        # Export and re-import
        exported = graph.export_node_link()
        graph2 = UIGraph.from_node_link(exported)
        
        # Verify query params are preserved
        edge_data = graph2.G[elem_id]["http://localhost/#!/devices"]
        assert "query_params" in edge_data
        assert edge_data["query_params"] == query_params
    
    def test_different_query_params_same_page(self):
        """Verify multiple links to same page with different query params."""
        graph = UIGraph()
        
        # Add page
        graph.add_page("http://localhost/#!/devices", title="Devices")
        
        # Add first link with one set of params
        elem_id_1 = graph.add_element(
            "http://localhost/#!/devices",
            "link",
            "css",
            "#filter-recent",
            text="Recent"
        )
        graph.add_navigation_link(
            from_page="http://localhost/#!/devices",
            to_page="http://localhost/#!/devices",
            via_element=elem_id_1,
            query_params={"filter": "Events.Inform > NOW()"}
        )
        
        # Add second link with different params
        elem_id_2 = graph.add_element(
            "http://localhost/#!/devices",
            "link",
            "css",
            "#filter-old",
            text="Old"
        )
        graph.add_navigation_link(
            from_page="http://localhost/#!/devices",
            to_page="http://localhost/#!/devices",
            via_element=elem_id_2,
            query_params={"filter": "Events.Inform < NOW() - 86400"}
        )
        
        # Verify both edges have different query params
        edge_data_1 = graph.G[elem_id_1]["http://localhost/#!/devices"]
        edge_data_2 = graph.G[elem_id_2]["http://localhost/#!/devices"]
        
        assert edge_data_1["query_params"]["filter"] == "Events.Inform > NOW()"
        assert edge_data_2["query_params"]["filter"] == "Events.Inform < NOW() - 86400"
        assert edge_data_1["query_params"] != edge_data_2["query_params"]
