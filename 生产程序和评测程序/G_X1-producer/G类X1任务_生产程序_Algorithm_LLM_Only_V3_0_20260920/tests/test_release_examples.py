import json
from pathlib import Path

from gx1.production import produce_batch


def test_representative_config_produces_exactly_four_review_cases(project_root):
    cfg = project_root / "configs" / "representative_four_cases.json"
    out = project_root / ".test_representative_output"
    if out.exists():
        import shutil; shutil.rmtree(out)
    manifest = produce_batch(cfg, out)
    assert manifest["case_counts"] == {"G1": 1, "G2": 1, "G3": 1, "X1": 1}
    roots = {}
    for task in ["G1", "G2", "G3", "X1"]:
        case_dir = next((out / "cases" / task).iterdir())
        roots[task] = json.loads((case_dir / "root_case.json").read_text(encoding="utf-8"))
    assert roots["G1"]["conversion"] == "EDGE_LIST_TO_ADJACENCY_LIST"
    assert roots["G2"]["oracle_label"] == "WRONG_DIRECTION"
    assert roots["G3"]["path_cost_metric"] == "TOTAL_LENGTH_KM"
    assert roots["G3"]["answer"]["has_shared_directed_link"] is True
    assert roots["X1"]["path_cost_metric"] == "TOTAL_LENGTH_KM"
