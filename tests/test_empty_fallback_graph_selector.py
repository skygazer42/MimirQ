from app.api.v1.network_analysis import EdgeIn, GraphRequest, connected_component, k_hop_neighbors, shortest_path


def test_omitted_graph_start_does_not_create_an_empty_named_node() -> None:
    request = GraphRequest(edges=[EdgeIn(source="a", target="b")])
    assert connected_component(request)["component"] == []
    assert k_hop_neighbors(request)["neighbors"] == []
    assert shortest_path(request)["path"] == []


def test_selected_graph_start_keeps_its_component() -> None:
    request = GraphRequest(edges=[EdgeIn(source="a", target="b")], start_id="a")
    assert connected_component(request)["component"] == ["a", "b"]
