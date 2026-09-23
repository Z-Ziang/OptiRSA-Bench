import pytest
from src.case_core.path_validation import path_nodes_from_links, validate_directed_path

LINKS = [
    {'link_id':0,'source_node_id':0,'destination_node_id':1},
    {'link_id':1,'source_node_id':1,'destination_node_id':2},
    {'link_id':2,'source_node_id':2,'destination_node_id':0},
    {'link_id':3,'source_node_id':2,'destination_node_id':3},
]


def test_path_nodes_reconstructs_ordered_nodes():
    assert path_nodes_from_links([0,1,3], LINKS) == [0,1,2,3]


def test_path_validation_accepts_exact_directed_path_and_rejects_mismatch():
    ok = validate_directed_path([0,1,3], [0,1,2,3], LINKS, 0, 3)
    assert ok.valid
    assert not validate_directed_path([0,3], [0,1,2,3], LINKS, 0, 3).valid
    assert not validate_directed_path([1,3], [1,2,3], LINKS, 0, 3).valid
    assert not validate_directed_path([0,1], [0,1,2], LINKS, 0, 3).valid


def test_path_nodes_fails_on_unknown_or_discontinuous_links():
    with pytest.raises(ValueError):
        path_nodes_from_links([0,99], LINKS)
    with pytest.raises(ValueError):
        path_nodes_from_links([0,3], LINKS)
